import logging
import os
import socket
from subprocess import Popen, PIPE

import StringIO
from twisted.internet import defer
from twisted.internet.interfaces import IConsumer
from twisted.protocols.basic import FileSender
from twisted.python import log
from twisted.python.failure import Failure
from zope.interface import implementer

from txmailserver.reactor import reactor

VALID_DSPAM_PREFIX = ['train-spam-', 'nospam-', 'spam-']


def runDspam(user, data):
    cmds = []
    log.msg("runDspam got user value of " + user)
    if user.startswith('train-spam-'):
        user = user.strip('train-spam-')
        cmd = "dspam --deliver=spam --source=corpus --class=spam --mode=tum".split()
        cmd.extend(["--user", user])
        msg = "The following message was trained as spam:"
    elif user.startswith('nospam-'):
        # correct dspam
        user = user.strip('nospam-')
        cmd = "dspam --deliver=innocent --source=error --class=innocent --mode=tum".split()
        cmd.extend(["--user", user])
        msg = "The following message was force-categorized as ham:"
    elif user.startswith('spam-'):
        # force message to be treated as spam
        user = user.strip('spam-')
        cmd = "dspam --deliver=spam --source=error --class=spam --mode=tum".split()
        cmd.extend(["--user", user])
        user = user.split('@')[0]
        cmd.append(user)
        msg = "The following message was force-categorized as spam:"
    else:
        cmd = "dspam --deliver=innocent --mode=tum --stdout".split()
        cmd.extend(["--user", user])
        msg = "The following message was not recognized as spam:"
    try:
        log.msg("DSPAM command: %s" % ' '.join(cmd))
        dspam = Popen(cmd, stdout=PIPE, stdin=PIPE)
        output, error = dspam.communicate(input=data)
    except Exception as e:
        # not sure what exceptions are going to be thrown here...
        error = str(e)
    if error:
        log.error("There was a DSPAM error: %s" % error)
    if output:
        log.msg(msg)
        log.msg(output)
    else:
        log.msg("dspam produced no message...")
    return output

@implementer(IConsumer)
class AddMessageToMailboxTask(object):

    osopen = staticmethod(os.open)
    oswrite = staticmethod(os.write)
    osclose = staticmethod(os.close)
    osrename = staticmethod(os.rename)

    def __init__(self, mbox, msg):
        self.mbox = mbox
        self.defer = defer.Deferred()
        self.openCall = None
        if not hasattr(msg, "read"):
            msg = StringIO.StringIO(msg)
        self.msg = msg

    def startUp(self):
        self.createTempFile()
        if self.fh != -1:
            self.filesender = FileSender()
            self.filesender.beginFileTransfer(self.msg, self)

    def registerProducer(self, producer, streaming):
        self.myproducer = producer
        self.streaming = streaming
        if not streaming:
            self.prodProducer()

    def prodProducer(self):
        self.openCall = None
        if self.myproducer is not None:
            self.openCall = reactor.callLater(0, self.prodProducer)
            self.myproducer.resumeProducing()

    def unregisterProducer(self):
        self.myproducer = None
        self.streaming = None
        self.osclose(self.fh)
        self.moveFileToNew()

    def write(self, data):
        try:
            self.oswrite(self.fh, data)
        except:
            self.fail()

    def fail(self, err=None):
        if err is None:
            err = Failure()
        if self.openCall is not None:
            self.openCall.cancel()
        self.defer.errback(err)
        self.defer = None

    def moveFileToNew(self):
        while True:
            newname = os.path.join(self.mbox.path, "new", self.mbox.generateMaildirName())
            try:
                self.osrename(self.tmpname, newname)
                break
            except OSError, (err, estr):
                import errno
                # if the newname exists, retry with a new newname.
                if err != errno.EEXIST:
                    self.fail()
                    newname = None
                    break
        if newname is not None:
            self.defer.callback(newname)
            self.defer = None

    def createTempFile(self):
        attr = (os.O_RDWR | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOINHERIT", 0)
                | getattr(os, "O_NOFOLLOW", 0))
        tries = 0
        self.fh = -1
        while True:
            self.tmpname = os.path.join(self.mbox.path, "tmp", self.mbox.generateMaildirName(True))
            try:
                self.fh = self.osopen(self.tmpname, attr, 0600)
                return None
            except OSError:
                tries += 1
                if tries > 500:
                    self.defer.errback(RuntimeError("Could not create tmp file for %s" % self.mbox.path))
                    self.defer = None
                    return None


class _MaildirNameGenerator(object):
    """
    Utility class to generate a unique maildir name

    @ivar _clock: An L{IReactorTime} provider which will be used to learn
        the current time to include in names returned by L{generate} so that
        they sort properly.
    """
    n = 0
    p = os.getpid()
    s = socket.gethostname().replace('/', r'\057').replace(':', r'\072')

    def __init__(self, clock):
        self._clock = clock

    def generate(self, uid):
        """
        Return a string which is intended to unique across all calls to this
        function (across all processes, reboots, etc).

        Strings returned by earlier calls to this method will compare less
        than strings returned by later calls as long as the clock provided
        doesn't go backwards.
        """
        self.n = self.n + 1
        t = self._clock.seconds()
        seconds = str(int(t))
        microseconds = '%07d' % (int((t - int(t)) * 10e6),)
        return '%s.M%sP%sQ%s.%s,U=%i' % (seconds, microseconds,
                                    self.p, self.n, self.s, uid)

generateMaildirName = _MaildirNameGenerator(reactor).generate

