import os
import os.path
import re
import stat
import email
import simplejson as json
from datetime import datetime
from StringIO import StringIO

from zope.interface import implements

from twisted.mail import imap4, maildir

from txmailserver import util

DELIMITER = "."
META = "meta.json"

class AttrDict(dict):
    def __getattr__(self, item):
        if item in self:
            return self[item]
        raise AttributeError(item)

FLAGS = AttrDict({
    "SEEN": r"\Seen",
    "UNSEEN": r"\Unseen",
    "DELETED": r"\Deleted",
    "FLAGGED": r"\Flagged",
    "ANSWERED": r"\Answered",
    "RECENT": r"\Recent",
    "S": r"\Seen",
    "U": r"\Unseen",
    "D": r"\Deleted",
    "F": r"\Flagged",
    "A": r"\Answered",
    "R": r"\Recent",
    })


class FlagSet(set):
    def __add__(self, other):
        return self.union(other)

    def __str__(self):
        attrs = [i.replace("\\",'')[0].upper() for i in self if i != r'\Recent']
        attrs.sort()
        return str.join('', attrs)

    @classmethod
    def fromString(cls, string):
        self = cls()
        for s in string.upper():
            if s in FLAGS:
                self.add(FLAGS[s])
        return self


class Mailbox(object):
    """
    IMAP4 mailbox, stores the IMAP4 metadatas as suffixes on the filenames.  Stores the mailbox state in meta.json
    """
    implements(imap4.IMailbox, imap4.IMessageCopier)
    mboxes = []
    def __init__(self, path):
        self.path = path
        maildir.initializeMaildir(path)
        self.listeners = []
        self.meta_filename = os.path.join(self.path, META)

        if not os.path.exists(self.meta_filename):
            with open(self.meta_filename, 'wb') as f:
                from txmailserver.mailservice import MailService
                json.dump(dict(
                    uidvalidity=MailService.instance.getNextUIDValidity(),
                    uidnext=1,
                    subscribed=False
                ), f)
        for i in os.listdir(os.path.join(self.path, 'new')):
            if ':2,' not in i:
                self.fixOldMessage(os.path.join(self.path, 'new', i))

    def fixOldMessage(self, name):
        os.rename(name, name+',U=%i:2,' % self.newUID)

    def notifyListeners(self, event, *args):
        for listener in self.listeners:
            handler = getattr(listener, event, None)
            if handler:
                print 93, listener
                handler(*args)

    def getMeta(self, meta):
        with open(self.meta_filename, 'rb') as f:
            return json.load(f)[meta]

    def hasMeta(self, meta):
        with open(self.meta_filename, 'rb') as f:
            return meta in json.load(f)

    def setMeta(self, meta, value):
        with open(self.meta_filename, 'rb+') as f:
            values = json.load(f)
            f.seek(0)
            f.truncate(0)
            values[meta] = value
            json.dump(values, f)

    @property
    def nextUID(self):
        return self.getMeta('uidnext')

    @property
    def newUID(self):
        uid = self.nextUID
        self.setMeta('uidnext', uid+1)
        return uid

    def getMessageNames(self):
        names = os.listdir(os.path.join(self.path, 'new')) + os.listdir(os.path.join(self.path, 'cur'))
        names.sort()
        return names

    def getFlagsFromFilename(self, filename):
        if ':2,' not in filename:
            if self.isNew(filename):
                return FlagSet.fromString('r')
            return FlagSet()
        flagstr = filename.split(':2,')[1].split(',')[0]
        flags = FlagSet.fromString(flagstr)
        if self.isNew(filename):
            flags.add(FLAGS.RECENT)
        return flags

    def isNew(self, msg):
        return os.path.basename(msg) in os.listdir(os.path.join(self.path, 'new'))

    def markNotNew(self, msg):
        if self.isNew(msg):
            oldname = self.getAbsolutePath(msg)
            os.rename(oldname, os.path.join(self.path, 'cur', os.path.basename(msg)))

    def getUIDFromFilename(self, filename):
        return int(re.match('.*?U=([0-9]+),?.*(:2,)?', filename).group(1))

    def generateMaildirName(self, Temporary=False):
        if Temporary:
            return util.generateMaildirName(self.nextUID)
        return util.generateMaildirName(self.newUID)

    def getUIDFilenameMap(self):
        o = {}
        for name in self.getMessageNames():
            uid = self.getUIDFromFilename(name)
            o[uid] = name
        return o

    def getAbsolutePath(self, name):
        if name in os.listdir(os.path.join(self.path, 'new')):
            return os.path.join(self.path, 'new', name)
        return os.path.join(self.path, 'cur', name)


    # IMailboxInfo
    def getFlags(self):
        """ Return the flags defined in this mailbox """
        return set(FLAGS.values())

    def getHierarchicalDelimiter(self):
        """ Get the character which delimits namespaces for in this mailbox. """
        return DELIMITER

    # IMailbox
    def getUIDValidity(self):
        """ Return the unique validity identifier for this mailbox. """
        return self.getMeta('uidvalidity')

    def getUIDNext(self):
        """ Return the likely UID for the next message added to this mailbox. """
        return self.nextUID

    def getUID(self, message):
        """ Return the UID of a message in the mailbox
        message:int message sequence number"""

        names = self.getMessageNames()
        m = names[message-1]
        return self.getUIDFromFilename(m)

    def getFlagCount(self, flag):
        """ Return the number of message with the given flag """
        count = 0
        for message in self.getMessageNames():
            flags = self.getFlagsFromFilename(message)
            if flag in flags:
                count += 1

        return count

    def getMessageCount(self):
        """ Return the number of messages in this mailbox. """
        return len(self.getMessageNames())

    def getRecentCount(self):
        """ Return the number of messages with the 'Recent' flag. """
        return len(os.listdir(os.path.join(self.path, 'new')))

    def getUnseenCount(self):
        """ Return the number of messages with the 'Unseen' flag. """
        return len(self.getMessageNames()) - self.getFlagCount(FLAGS.SEEN)

    def isWriteable(self):
        """ Get the read/write status of the mailbox. """
        return True

    def destroy(self):
        """ Called before this mailbox is deleted, permanently."""
        raise imap4.MailboxException("Permission denied")

    def requestStatus(self, names):
        """ Return status information about this mailbox.
        names:iterable containing MESSAGES, RECENT, UIDNEXT, UIDVALIDITY, UNSEEN
        """
        return imap4.statusRequestHelper(self, names)

    def addListener(self, listener):
        """ Add a mailbox change listener.
        listener:IMailboxListener
        """
        self.listeners.append(listener)

    def removeListener(self, listener):
        """ Remove a mailbox change listener.
        listener:IMailboxListener
        """
        self.listeners.remove(listener)

    def addMessage(self, message, flags=(), date=None):
        """ Add the given message to this mailbox.
        message:RFC822 message
        flags:iter or str
        date:str
        """

        task = util.AddMessageToMailboxTask(self, message)
        result = task.defer
        task.startUp()
        result.addCallback(self.cbAddedMessage, FlagSet(flags))

        return result

    def cbAddedMessage(self, filename, flags):
        os.rename(filename, filename+':2,%s' % str(flags))
        self.notifyListeners('newMessages', self.getMessageCount(), self.getUnseenCount())

    def expunge(self):
        """ Remove all messages flagged \Deleted.  """
        count = self.getMessageCount()
        recent = self.getRecentCount()
        o = []
        for message in self.getMessageNames():
            flags = self.getFlagsFromFilename(message)
            if FLAGS.DELETED in flags:
                path = self.getAbsolutePath(message)
                os.rename(path, '/var/mail/trash/%s' % path.rsplit('/', 1)[1])
                o.append(self.getUIDFromFilename(message))
        if o:
            newCount = self.getMessageCount()
            newRecent = self.getRecentCount()
            if newCount==count:
                newCount = None
            if newRecent == recent:
                newRecent = None
            self.notifyListeners('newMessages', newCount, newRecent)
        return o

    def fetch(self, messages, uid):
        return list(self._fetch(messages, uid))

    def _fetch(self, messages, uid):

        out = []
        if uid:
            if not messages.last:
                messages.last = self.nextUID
            filenames = self.getUIDFilenameMap()
            for u in messages:
                if int(u) in filenames:
                    out.append((u, filenames[int(u)]))
        else:
            if not messages.last:
                names = self.getMessageNames()
                messages.last = max(0, len(names))
            for message in messages:
                uid = self.getUIDFromFilename(names[message-1])
                out.append((uid, names[message-1]))

        #result = []
        #changed_flags = {}
        names = self.getMessageNames()
        for uid, basename in out:
            flags = self.getFlagsFromFilename(basename)
            filename = self.getAbsolutePath(basename)
            ctime = os.stat(filename)[stat.ST_CTIME]
            with open(filename, 'rb') as f:
                data = f.read()
            date = datetime.fromtimestamp(ctime)

            if self.isNew(basename):
                self.markNotNew(basename)
                changed_flags = {names.index(basename)+1: self.getFlagsFromFilename(filename)}
                self.notifyListeners('flagsChanged', changed_flags)
            yield ((uid, Message(uid, None, flags, date, filename=filename)))

        #return result

    def copy(self, message):
        data = message.data
        flags = message.flags
        date = message.date
        return self.addMessage(data, flags, date)

    def store(self, messages, flags, mode, uid):
        """ Set the flags of one or more messages .
        messages:MessageSet
        flags:sequence of str
        mode:int(-1,0,1)
        uid:bool
        """
        print 324, messages, uid

        mode = int(mode)
        d = {-1: self.removeFlags,
                +0: self.setFlags,
                +1: self.addFlags}[mode](messages, flags, uid)

        print 331, d
        return d

    def removeFlags(self, messages, flags, uid):
        o = {}
        changed_flags = {}
        flags = FlagSet(flags)
        filenames = self.getUIDFilenameMap()
        uids = list(filenames.keys())
        for uid, message in self.fetch(messages, uid):
            filename = filenames[uid]
            oldflags = self.getFlagsFromFilename(filename)
            newflags = oldflags - flags
            newflags.discard(FLAGS.RECENT)
            if newflags != oldflags:
                changed_flags[uid] = newflags
                self._setFlags(filename, newflags)
            o[uid] = newflags
        changed_flags = {uids.index(uid)+1: newflags for uid, newflags in changed_flags.iteritems()}
        o = {uids.index(uid)+1: newflags for uid, newflags in o.iteritems()}
        #self.notifyListeners('flagsChanged', changed_flags)
        return o

    def setFlags(self, messages, flags, uid):
        o = {}
        changed_flags = {}
        flags = FlagSet(flags)
        filenames = self.getUIDFilenameMap()
        uids = list(filenames.keys())
        for uid, message in self.fetch(messages, uid):
            filename = filenames[uid]
            oldflags = self.getFlagsFromFilename(filename)
            newflags = flags.copy()
            newflags.discard(FLAGS.RECENT)
            if newflags != oldflags:
                changed_flags[uid] = newflags
                self._setFlags(filename, newflags)
            o[uid] = newflags
        changed_flags = {uids.index(uid)+1: newflags for uid, newflags in changed_flags.iteritems()}
        o = {uids.index(uid)+1: newflags for uid, newflags in o.iteritems()}
        #self.notifyListeners('flagsChanged', changed_flags)
        return o

    def addFlags(self, messages, flags, uid):
        o = {}
        changed_flags = {}
        flags = FlagSet(flags)
        filenames = self.getUIDFilenameMap()

        for uid, message in self.fetch(messages, uid):
            filename = filenames[uid]
            oldflags = self.getFlagsFromFilename(filename)
            newflags = oldflags + flags
            newflags.discard(FLAGS.RECENT)
            if newflags != oldflags:
                changed_flags[uid] = newflags
                self._setFlags(filename, newflags)
            o[uid] = newflags
        filenames = self.getUIDFilenameMap()
        uids = list(filenames.keys())
        changed_flags = {uids.index(uid)+1: newflags for uid, newflags in changed_flags.iteritems()}
        o = {uids.index(uid)+1: newflags for uid, newflags in o.iteritems()}
        if changed_flags:
            pass
            #self.notifyListeners('flagsChanged', changed_flags)
        return o

    def _setFlags(self, filename, newflags):
        filename = os.path.basename(filename)
        self.markNotNew(filename)
        absolute_path = self.getAbsolutePath(filename)
        prefix, oldflags = filename.split(':2,')
        if ',' in oldflags:
            suffix = oldflags.split(',')
        else:
            suffix = None
        newname = prefix+':2,'+str(newflags)
        if suffix:
            newname += ','+suffix
        os.rename(absolute_path, os.path.join(self.path, 'cur', newname))



class MessagePart(object):
    implements(imap4.IMessagePart)

    def __init__(self, messagestr=None, message=None):
        if messagestr is not None:
            self.message = email.message_from_string(messagestr)
            self.data = str(messagestr)
        else:
            self.message = message
            self.data = str(message)
    def getHeaders(self, negate, *names):
        headers = tuple(self._getHeaders(negate, *names))
        return dict(headers)

    def _getHeaders(self, negate, *names):
        """ Retrieve a group of messag headers.
        names:truple|str
        negate:bool omit the given names?
        """
        if not names:
            names = self.message.keys()

        if not negate:
            for name, header in self.message.items():
                if name not in names:
                    yield name, header
        else:
            for name in names:
                yield name.lower(), self.message.get(name, None)

    def getBodyFile(self):
        """ Retrieve a file object containing only the body of this message. """
        return StringIO(self.message.get_payload())

    def getSize(self):
        """ Retrieve the total size, in octets/bytes, of this message. """
        return len(self.data)

    def isMultipart(self):
        """ Indicate whether this message has subparts. """
        return self.message.is_multipart()

    def getSubPart(self, part):
        """ Retrieve a MIME sub-message.
        part:int indexed from 0
        """
        return MessagePart(message=self.message.get_payload()[part])


class Message(MessagePart):
    implements(imap4.IMessage)

    def __init__(self, uid, message, flags=None, date=None, filename=None):
        if message is not None:
            super(Message, self).__init__(message)
            self.email = email.message_from_string(message)
        self.filename = filename

        self.uid = uid
        self.flags = flags
        self.date = date

    def __getattribute__(self, item):
        if item=='message' or item=='data' or item=='email':
            if self.filename is not None:
                with open(self.filename, 'rb') as f:
                    messagestr = f.read()
                    if item=='message' or item=='email':
                        message = email.message_from_string(messagestr)
                        return message
                    else:
                        return messagestr
        return MessagePart.__getattribute__(self, item)

    def getUID(self):
        return self.uid

    def getFlags(self):
        return self.flags

    def getInternalDate(self):
        return self.date.strftime("%a, %d  %b  %Y  %H:%M:%S")
