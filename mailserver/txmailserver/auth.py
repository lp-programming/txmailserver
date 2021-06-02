import os

from twisted.mail.smtp import IMessageDelivery
from zope.interface import implements

from twisted.mail import maildir
from twisted.mail.pop3 import IMailbox
from twisted.mail.imap4 import IAccount
from twisted.cred import portal, checkers, credentials, error as credError
from twisted.internet import protocol, reactor, defer
from twisted.python import log

from txmailserver.pop3 import POP3Account
from txmailserver.imap4 import IMAP4Account
import subprocess

from twisted.internet import utils

from txmailserver.smtp import LocalDelivery
from .reactor import reactor


class SMTPRealm(object):
    implements(portal.IRealm)

    def __init__(self, parent, md):
        self.baseDir = parent.baseDir
        self.messageDelivery = md

    def requestAvatar(self, avatarId, mind, *interfaces):
        log.msg(interfaces)
        if IMessageDelivery in interfaces:
            self.messageDelivery.avatarId = avatarId
            return defer.succeed((IMessageDelivery, self.messageDelivery, lambda: None))

        # none of the requested interfaces was supported
        print 45, avatarId, mind, interfaces
        raise KeyError("None of the requested interfaces is supported")

class MailUserRealm(object):
    implements(portal.IRealm)
    avatarInterfaces = {
        IMailbox: POP3Account,
        IAccount: IMAP4Account,
        }

    def __init__(self, baseDir):
        self.baseDir = baseDir

    def requestAvatar(self, avatarId, mind, *interfaces):
        log.msg(interfaces)
        for requestedInterface in interfaces:
            if self.avatarInterfaces.has_key(requestedInterface):
                # make sure the user dir exists
                userDir = os.path.join(self.baseDir, avatarId)
                if not os.path.exists(userDir):
                    os.mkdir(userDir)
                # return an instance of the correct class
                avatarClass = self.avatarInterfaces[requestedInterface]
                avatar = avatarClass(userDir)
                # null logout function: take no arguments and do nothing
                logout = lambda: None
                return defer.succeed((requestedInterface, avatar, logout))
            
        # none of the requested interfaces was supported
        print 45, avatarId, mind, interfaces
        raise KeyError("None of the requested interfaces is supported") 


class SuChecker(utils._ValueGetter):
    def __init__(self, username, password):
        utils._ValueGetter.__init__(self, defer.Deferred())
        self.username = username.split('@')[0].lower()
        self.password = password

    def connectionMade(self):
        self.transport.write(self.username+'\n')
        self.transport.write(self.password+'\n')
        #self.transport.loseConnection()

    def processEnded(self, reason):
        return utils._ValueGetter.processEnded(self, reason)

    def checkPassword(self):
        reactor.spawnProcess(self, '/usr/bin/checkpw', ['/usr/bin/checkpw'], {}, None, None, None, True)
        return self.deferred


class CredentialsChecker(object):
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, passwords):
        "passwords: a dict-like object mapping usernames to passwords"
        self.passwords = passwords

    def requestAvatarId(self, credentials):
        username = credentials.username.split('@')[0]

        if not username.isalpha():
            raise credError.UnauthorizedLogin("No such user")
        password = credentials.password

        return SuChecker(username, password).checkPassword().addCallback(self._checkedPassword, credentials.username)

    def _checkedPassword(self, matched, username):
        print 85, matched, username
        if matched == 0:
            # password was correct
            return username
        else:
            raise credError.UnauthorizedLogin("Bad password")

def passwordFileToDict(filename):
    passwords = {}
    if os.path.exists(filename):
        for line in file(filename):
            if line and line.count(':'):
                username, password = line.strip().split(':')
                passwords[username.strip()] = password.strip()
    else:
        log.err("%s - passwords not found" % filename)
    return passwords

def getPasswords(configDir):
    return os.path.join(configDir, 'passwords.txt')

def getChecker(configDir):
    passwords = passwordFileToDict(passwordFile)
    checker = CredentialsChecker(passwords)
    return checker

