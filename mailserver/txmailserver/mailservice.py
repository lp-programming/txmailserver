import json
import os
from email.Header import Header

from zope.interface import implements
from twisted.cred import portal
from twisted.mail import mail, relay, relaymanager

from txmailserver import auth
from txmailserver.SmartHostRelayingManager import SmartHostRelayingManager
from txmailserver.smtp import SMTPFactory, ESMTPFactory
from txmailserver.pop3 import POP3Factory
from txmailserver.imap4 import IMAP4Factory


class MailService(mail.MailService):

    def __init__(self, baseDir, configDir, forwardDir, validDomains,
                 relayServers=[], relayCheckInterval=15, relayUsername=None, relayPassword=None):
        mail.MailService.__init__(self)
        MailService.instance = self
        self.baseDir = baseDir
        self.configDir = configDir
        self.forwardDir = forwardDir
        self.validDomains = validDomains
        self.relayServers = relayServers
        self.relayCheckInterval = relayCheckInterval
        self.relayManager = None
        self.relayQueueTimer = None
        self.realm = auth.MailUserRealm(self.baseDir)
        self.portal = portal.Portal(self.realm)
        passwords = {}
        self.checker = auth.CredentialsChecker(passwords)

        if not os.path.exists(self.forwardDir):
            os.mkdir(self.forwardDir)
        queue = relaymanager.Queue(self.forwardDir)
        self.queuer = relay.DomainQueuer(self)
        self.setQueue(queue)
        self.domains.setDefaultDomain(self.queuer)
        if relayServers:
            self.relayManager = SmartHostRelayingManager(
                queue)
            self.relayManager.mxcalc.fallbackRelay = relayServers
            self.relayManager.fArgs += (self.relayServers, None, None)
            self.relayManager.__auth__ = (self.relayServers, relayUsername, relayPassword)
            self.relayQueueTimer = relaymanager.RelayStateHelper(
                self.relayManager, 15)

    def getNextUIDValidity(self):
        if not os.path.isdir(self.baseDir):
            os.mkdir(self.baseDir, 0700)
        if not os.path.exists(os.path.join(self.baseDir, 'NextUIDValidity.json')):
            with open(os.path.join(self.baseDir, 'NextUIDValidity.json'), 'wb') as f:
                f.write('1')
        with open(os.path.join(self.baseDir, 'NextUIDValidity.json'), 'rb+') as f:
            validity = json.load(f)
            f.seek(0)
            json.dump(validity+1, f)
            return validity

    def getSMTPFactory(self):
        factory = SMTPFactory(
            self.baseDir, self.configDir, self.validDomains, self.queuer)
        factory.configDir = self.configDir
        factory.portal = self.portal
        factory.portal.registerChecker(self.checker)
        self.smtpPortal = factory.portal
        return factory

    def getESMTPFactory(self):
        factory = ESMTPFactory(
            self.baseDir, self.configDir, self.validDomains, self.queuer)
        factory.configDir = self.configDir
        factory.portal = self.portal
        factory.portal.registerChecker(self.checker)
        self.smtpPortal = factory.portal
        return factory

    def getPOP3Factory(self):
        factory = POP3Factory()
        factory.portal = self.portal
        factory.portal.registerChecker(self.checker)
        return factory

    def getIMAP4Factory(self):
        factory = IMAP4Factory()
        factory.portal = self.portal
        factory.portal.registerChecker(self.checker)
        return factory

