from twisted.protocols import tls
from twisted.application import internet, service

from twisted.python import log
from twisted.internet import ssl
from OpenSSL import SSL
from OpenSSL import crypto

from txmailserver import mailservice
from txmailserver.domain import Alias, Actual, Maillist, CatchAll, Script

import re

# sample script
from txmailserver.reactor import reactor

def trainSpam(dest, message):
    import antispam
    message = str(message)
    if message:
        print '(spam) initial score:'
        antispam.score(message)
        antispam.train(str(message), True)
        print 'final score:'
        antispam.score(message)

def trainNotSpam(dest, message):
    import antispam
    if message:
        print '(notspam) initial score:'
        antispam.score(str(message))
        antispam.train(message, False)
        print 'final score:'
        antispam.score(str(message))

def getLocalUsers():
    users = []
    with open('/etc/passwd', 'r') as f:
        for user in f:
            username, pw, uid, gid, notes, home, shell = user.split(':')
            if 65534 > int(uid) > 999 and home.startswith('/home') and shell not in ['/bin/false', '/usr/sbin/nologin']:
                users.append(username)
    return users

def whitelist(dest, message):
    return
    import antispam
    antispam.whitelist(message)
    trainNotSpam(dest, message)

def blacklist(dest, message):
    return
    import antispam
    antispam.blacklist(message)
    trainSpam(dest, message)
    


employees = getLocalUsers()

employees += [
   # 'other_employee_here'

]

maillists = {
   # 'somelistname': ['user1', 'user2']
}

aliases = {
   # 'postmaster': 'root'
}


domains = {}

domains['example.com'] = [
    Actual(i) for i in employees
] + [
    Alias('%s@example.com' % i, i) for i in employees
] + [
    Maillist(i, v) for i,v in maillists.items()
] + [
    Alias(i,v) for i,v in maillists.items()
] + [
    Script('^spam', trainSpam),
    Script('^nospam', trainNotSpam),
    Script('^notspam', trainNotSpam),
    Script('^whitelist', whitelist),
    Script('^blacklist', blacklist),
    Alias('notspam', 'nospam@example.com')
]

domains['.*.example.com'] = [
    Alias(i, '%s@example.com' % i) for i in employees
]



class SubDomains(object):
    def __init__(self, d):
        self._items = d

    def __getitem__(self, item):
        if item in self._items:
            return self._items[item]
        for k in self.keys():
            if re.match(k, item):
                return self._items[k]

    def __contains__(self, item):
        if self._items.__contains__(item):
            return True
        sigil = object()
        return self.get(item, sigil) is not sigil

    def get(self, key, default=None):
        sigil = object()
        ret = self._items.get(key, sigil)
        if ret is not sigil:
            return ret
        for k in self.keys():
            if re.match(k, key):
                return self._items[k]
        return default

    def keys(self):
        return self._items.keys()

domains = SubDomains(domains)

mailboxDir = '/var/mail/Maildir'
configDir = 'etc'
forwardDir = 'queue'
smtpPort = 25
imap4Port = 143
tlsFactory = ssl.DefaultOpenSSLContextFactory('/etc/letsencrypt/live/example.com/privkey.pem', '/etc/letsencrypt/live/example.com/cert.pem', SSL.TLSv1_2_METHOD)
#/etc/letsencrypt/live/www.mail2.alestan.publicvm.com/fullchain.pem.

relayServers = 'relay.example.com'
relayUsername = 'redacted'
relayPassword = 'redacted'

# setup the application
application = service.Application("smtp, pop and imap server")
svc = service.IServiceCollection(application)

# setup the mail service
ms = mailservice.MailService(mailboxDir, configDir, forwardDir, domains, relayServers=relayServers, relayUsername=relayUsername, relayPassword=relayPassword)

# setup the queue checker
queueTimer = ms.relayQueueTimer
if queueTimer:
    queueTimer.setServiceParent(svc)

# setup the SMTP server
smtpFactory = ms.getESMTPFactory()
smtpFactory.tlsFactory = tlsFactory

smtp = internet.TCPServer(smtpPort, smtpFactory)
smtp.setServiceParent(svc)



# setup the whitelist queue timer
whitelistQueueTimer = smtpFactory.whitelistPurgeTimer
whitelistQueueTimer.setServiceParent(svc)

# setup the POP3 server
#pop3Factory = ms.getPOP3Factory()
#pop3 = internet.TCPServer(pop3Port, pop3Factory)
#pop3.setServiceParent(svc)

# setup the IMAP server
imap4Factory = ms.getIMAP4Factory()
imap4Factory.tlsFactory = tlsFactory
imap4 = internet.TCPServer(imap4Port, imap4Factory)
imap4.setServiceParent(svc)


from twisted.internet import reactor

# from objgraph import show_growth
# def sg():
#     show_growth()
#     reactor.callLater(1, sg)

# sg()

# vim:ft=python:
import code
def interact():
    code.interact()

#reactor.callInThread(interact)

