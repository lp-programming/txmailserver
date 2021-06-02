import os
import re

from email.parser import FeedParser
from email.header import Header
from subprocess import Popen, PIPE
from cStringIO import StringIO

import datetime
from twisted.cred import credentials
from twisted.mail.imap4 import PLAINCredentials
from twisted.mail.smtp import LOGINCredentials
from zope.interface import implements

from twisted.mail import smtp, maildir, mail
from twisted.internet import protocol, defer
from twisted.internet.threads import deferToThread
from twisted.application.internet import TimerService
from twisted.python import log

from txmailserver import mailbox
from txmailserver.reactor import reactor
from txmailserver.util import runDspam, VALID_DSPAM_PREFIX
from txmailserver.domain import Alias, Actual, Maillist, CatchAll, Script
import re

try:
    import antispam
except ImportError:
    antispam = None


def checkSpamMessageData(user, data):
    if antispam:
        From = re.search('^From:.*\n', data, flags=re.IGNORECASE|re.MULTILINE)
        if From:
            From = From.group()
            if '<' in From:
                From = From.split('<')[1].split('>')[0]
            else:
                From = None
        print 33, 'checking spam'
        return antispam.score(data, From), data
    return 0, data


def processMessageData(user, data, dspamEnabled):
    if dspamEnabled:
        data = runDspam(user, data)
    return data


def scriptTask(user, data, callback):
    d = defer.Deferred()

    parser = FeedParser()
    parser.feed(data)
    message = parser.close()

    callback(user, message)

    d.callback(None)

    return d


class ScriptMessageWriter(object):
    implements(smtp.IMessage)

    def __init__(self, user, func):
        self.user = user
        self.func = func
        self.lines = []

    def lineReceived(self, line):
        self.lines.append(line)

    def eomReceived(self):
        log.msg("Message data complete.")
        self.lines.append('') # add a trailing newline
        data = '\n'.join(self.lines)
        return scriptTask(self.user, data, self.func)

    def connectionLost(self):
        log.msg("Connection lost unexpectedly!")
        # unexpected loss of connection; don't save
        del(self.lines)


class MaildirMessageWriter(object):
    implements(smtp.IMessage)

    def __init__(self, userDir, dspamEnabled, orig_user=None):
        self.dspamEnabled = dspamEnabled
        self.user = os.path.split(userDir)[-1]
        self.orig_user = orig_user
        if not os.path.exists(userDir):
            os.mkdir(userDir)
        inboxDir = os.path.join(userDir, 'INBOX')
        self.mailbox = mailbox.Mailbox(inboxDir)
        if os.path.exists(os.path.join(userDir, 'SPAM')):
            self.spambox = mailbox.Mailbox(os.path.join(userDir, 'SPAM'))
        else:
            self.spambox = None
        self.lines = []
        if orig_user:
            self.lines.append("from %s@%s %s"%(
                orig_user.orig.local.lower(),
                orig_user.orig.domain.lower(),
                str(datetime.datetime.now())
            ))

    def lineReceived(self, line):
        self.lines.append(line)

    def eomReceived(self):
        # message is complete, store it
        log.msg("Message data complete.")
        self.lines.append('') # add a trailing newline
        data = '\n'.join(self.lines)
        messageData = processMessageData(self.user, data, self.dspamEnabled)
        if self.spambox:
            is_spam, messageData = checkSpamMessageData(self.user, data)
            if 'From' in data:
                From = data.split('From: ', 1)[1].split('\n', 1)[0].strip()
                if str(self.orig_user.orig) not in From:
                    print "forged 'From:' header"
                    is_spam += 0.5
            if is_spam > 0.9:
                print 'probably spam'
                return self.spambox.addMessage(messageData)
        return self.mailbox.addMessage(messageData)

    def connectionLost(self):
        log.msg("Connection lost unexpectedly!")
        # unexpected loss of connection; don't save
        del(self.lines)


class MaildirListMessageWriter(MaildirMessageWriter):

    def __init__(self, userDirList, dspamEnabled):
        self.dspamEnabled = dspamEnabled
        self.mailboxes = {}
        self.lines = {}
        self.dspamUsers = {}
        for userDir in userDirList:
            if not os.path.exists(userDir):
                os.mkdir(userDir)
            inboxDir = os.path.join(userDir, 'INBOX')
            self.mailboxes[userDir] = mailbox.Mailbox(inboxDir)
            self.lines[userDir] = []

    def lineReceived(self, line):
        for key in self.lines.keys():
            self.lines[key].append(line)

    def eomReceived(self):
        dl = []
        for key in self.lines.keys():
            # message is complete, store it
            self.lines[key].append('')
            log.msg("Message data complete for %s." % key)
            user = os.path.split(key)[-1]
            data = '\n'.join(self.lines[key])
            messageData = processMessageData(user, data, self.dspamEnabled)
            dl.append(self.mailboxes[key].addMessage(messageData))
        return defer.DeferredList(dl)


class LocalDelivery(object):
    implements(smtp.IMessageDelivery)
    avatarId = None

    def __init__(self, baseDir, validDomains, domainQueuer, dspamEnabled):
        if not os.path.isdir(baseDir):
            raise ValueError("'%s' is not a directory" % baseDir)
        self.baseDir = baseDir
        self.validDomains = validDomains
        self.domainQueuer = domainQueuer
        self.dspamEnabled = dspamEnabled
        self.blacklist = self.whitelist = self.whitelistQueue = []

    def receivedHeader(self, helo, origin, recipients):
        myHostname, clientIP = helo
        headerValue = "by %s from %s with ESMTP ; %s" % (
            myHostname, clientIP, smtp.rfc822date())
        # email.Header.Header used for automatic wrapping of long lines
        return "Received: %s" % Header(headerValue)

    def updateWhitelist(self, user):
        if user not in self.whitelist:
            self.whitelistQueue.append(user)

    def validateFrom(self, helo, originAddress):
        log.msg("validateFrom(): %s" % originAddress)
        if originAddress in self.whitelist + self.whitelistQueue:
            return originAddress
        elif originAddress in self.blacklist:
            log.msg("Sender in blacklist! Denying message...")
            raise smtp.SMTPBadSender(originAddress)
        return originAddress

    def validateTo(self, user):
        log.msg("validateTo: %s" % user)
        destDomain = user.dest.domain.lower()
        destUser = user.dest.local.lower()
        origDomain = user.orig.domain.lower()
        origUser = user.orig.local.lower()
        localDomains = self.validDomains.keys()
        localUsersOrig = self.validDomains.get(origDomain)
        localUsersDest = self.validDomains.get(destDomain)
        if not destDomain in self.validDomains:
            if self.avatarId is None:
                raise smtp.SMTPBadRcpt(user)
            # get all local users
            localUsers = ([x.initial for x in localUsersOrig] +
                          [x.dest for x in localUsersOrig])
            if (origDomain in localDomains and origUser in localUsers):
                # startMessage returns
                # createNewMessage returns (headerFile, FileMessage)
                d = self.domainQueuer
                msg = lambda: d.startMessage(user)
                d.exists = lambda: msg
                dest = "%s@%s" % (destUser, destDomain)
                if dest not in localUsers:
                    self.updateWhitelist(dest)
                return defer.maybeDeferred(d.exists)
            # Not a local user. raising SMTPBadRcpt...
            raise smtp.SMTPBadRcpt(user)
        for userType in localUsersDest:
            # set 'nospam-' and 'spam-' prefixes to user names as valid
            # recipients
            name = userType.initial
            # with dspam
            #if userType.validate(destUser, prefixes=VALID_DSPAM_PREFIX):
            if userType.validate(destUser):
                ## no DSPAM
                ##if destUser != name:
                ##    userType.dest = "%s@%s" % (destUser, destDomain)
                ##    log.msg("Setting DSPAM username as:")
                log.msg("Accepting mail for %s..." % user.dest)
                if isinstance(userType, Alias):
                    finalDest = userType.dest
                elif isinstance(userType, Actual):
                    finalDest = user.dest
                elif isinstance(userType, Maillist):
                    addressDirs = [self._getAddressDir(x)
                                   for x in userType.dest]
                    log.msg("Looks like destination is a mail list...")
                    log.msg("list addresses: %s" % addressDirs)
                    return lambda: MaildirListMessageWriter(
                        addressDirs, self.dspamEnabled)
                elif isinstance(userType, CatchAll):
                    finalDest = userType.dest
                else:
                    log.err(userType)

                if not isinstance(userType, Script):
                    return lambda: MaildirMessageWriter(
                        self._getAddressDir(finalDest), self.dspamEnabled, orig_user=user)
                else:
                    return lambda: ScriptMessageWriter(
                        user.dest, userType.func)
        raise smtp.SMTPBadRcpt(user.dest)

    def _getAddressDir(self, address):
        address = str(address)
        if '@' in address:
            address = address.split('@')[0]
        address = address.lower()
        return os.path.join(self.baseDir, "%s" % address)

class SMTPFactory(protocol.ServerFactory):

    def __init__(self, baseDir, configDir, validDomains, domainQueuer):
        self.baseDir = baseDir
        self.whitelistFile = os.path.join(configDir, 'whitelist.txt')
        self.blacklistFile = os.path.join(configDir, 'blacklist.txt')
        self.whitelist = self._getWhitelistFromFile()
        self.blacklist = self._getBlacklistFromFile()
        self.whitelistQueue = []
        self.validDomains = validDomains
        self.domainQueuer = domainQueuer
        self.configDir = None
        self.dspamEnabled = False
        self.whitelistPurgeTimer = TimerService(300, self.purgeWhitelistQueue)

    def getDelivery(self):
        ld = LocalDelivery(
            self.baseDir, self.validDomains, self.domainQueuer,
            self.dspamEnabled)
        ld.blacklist = self.blacklist
        ld.whitelist = self.whitelist
        ld.whitelistQueue = self.whitelistQueue
        return ld

    def buildProtocol(self, addr):
        print 249, self
        delivery = self.getDelivery()
        delivery.client_address = addr
        smtpProtocol = smtp.SMTP(delivery)
        smtpProtocol.factory = self
        return smtpProtocol

    def _getWhitelistFromFile(self):
        if os.path.exists(self.whitelistFile):
            wl = open(self.whitelistFile).readlines()
            return list(set(wl))
        else:
            log.err("%s - whitelist not found" % self.whitelistFile)
            return []

    def _getBlacklistFromFile(self):
        if os.path.exists(self.blacklistFile):
            return open(self.blacklistFile).readlines()
        else:
            log.err("%s - blacklist not found" % self.blacklistFile)
            return []

    def purgeWhitelistQueue(self):
        # XXX there's a race condition between this and the local delivery
        # instantiation updating the whitelist attribute
        log.msg("Entries in whitelist: %s" % len(self.whitelist))
        log.msg("Entries in whitelist queue: %s" % len(self.whitelistQueue))
        wl = self._getWhitelistFromFile()
        uniq = list(set(self.whitelistQueue + wl))
        #fh = open(self.whitelistFile, 'w+')
        #fh.write('\n'.join(uniq))
        #fh.close()
        self.whitelistQueue = []
        self.whitelist = self._getWhitelistFromFile()
        log.msg("Entries in whitelist (updated): %s" % len(self.whitelist))

class ESMTPFactory(SMTPFactory):
    tlsFactory = None

    def buildProtocol(self, addr):
        print 286, self
        from txmailserver.mailservice import MailService
        from txmailserver.auth import SMTPRealm
        from twisted.cred import portal

        delivery = self.getDelivery()
        delivery.client_address = addr
        esmtpProtocol = smtp.ESMTP(contextFactory=self.tlsFactory)
        esmtpProtocol.delivery = delivery
        esmtpProtocol.factory = self
        esmtpProtocol.challengers = {"LOGIN": LOGINCredentials}

        esmtpProtocol.portal = portal.Portal(SMTPRealm(MailService.instance.portal.realm, delivery))
        esmtpProtocol.portal.registerChecker(MailService.instance.checker, credentials.IUsernamePassword)
        esmtpProtocol.checker = MailService.instance.checker
        return esmtpProtocol

def connectionMade(self):
    # Ensure user-code always gets something sane for _helo
    peer = self.transport.getPeer()
    try:
        host = peer.host
    except AttributeError: # not an IPv4Address
        host = str(peer)

    _helo = (None, host)

    if host == '63.227.187.208' or host == '209.181.47.143' or host.startswith('127.0'):
        print 'saying hello'
        self._sendHello(_helo)
    else:
        reactor.callLater(8, self._sendHello, _helo)

smtp.SMTP.connectionMade = connectionMade

def _sendHello(self, helo):
    self._helo = helo
    self.waited = True
    self.sendCode(220, self.greeting())
    self.setTimeout(self.timeout)

smtp.SMTP._sendHello = _sendHello

old_do_HELO = smtp.SMTP.do_HELO
def do_HELO(self, rest):
    if not self.waited:
        print 'rejecting rude connection'
        self.rejected = True
        self.sendCode(554, '%s not accepting messages' % (self.__class__.__name__))
    return old_do_HELO(self, rest)

smtp.SMTP.do_HELO = do_HELO

old_do_EHLO = smtp.ESMTP.do_EHLO
def do_EHLO(self, rest):
    if not self.waited:
        print 'rejecting rude connection'
        self.rejected = True
        self.sendCode(554, '%s not accepting messages' % (self.__class__.__name__))
    else:
        print 'got ehlo'
    return old_do_EHLO(self, rest)

smtp.ESMTP.do_EHLO = do_EHLO

old_do_MAIL = smtp.SMTP.do_MAIL
def do_MAIL(self, rest):
    if self.rejected or not self.waited:
        print 'rejecting rude connection'
        self.sendCode(554, '%s not accepting messages' % self.__class__.__name__)
        self.sendCode(550, '5.0.0 Command rejected')
        self.rejected = True
        return

    return old_do_MAIL(self, rest)

smtp.SMTP.do_MAIL = do_MAIL

old_do_STARTTLS = smtp.ESMTP.ext_STARTTLS

def do_STARTTLS(self, *args):
    print 'got starttls'
    return old_do_STARTTLS(self, *args)

smtp.ESMTP.ext_STARTTLS = do_STARTTLS

smtp.SMTP.waited = False
smtp.SMTP.rejected = False


old_sendCode = smtp.SMTP.sendCode
def sendCode(self, *args):
    print 'sending', args
    return old_sendCode(self, *args)

smtp.SMTP.sendCode = sendCode
