import os

from zope.interface import implements

from twisted.mail import imap4, maildir
from twisted.internet import protocol, defer
from twisted.python import log

from txmailserver.mailbox import Mailbox, Message, MessagePart


__all__ = ["IMAP4Account", "IMAP4Protocol", "IMAP4Factory"]


class IMAP4Account:
    implements(imap4.IAccount)
    
    def __init__(self, userdir):
        if '@' in userdir:
            userdir = userdir.split('@')[0]
        userdir = userdir.lower()
        self.userdir = userdir
        self.mailboxes = {
            i: Mailbox(os.path.join(userdir, i)) for i in os.listdir(userdir)
            }
    
    def addMailbox(self, name, mbox=None):
        """ Add a new mailbox to this account 
        name:str
        mbox:IMailbox
        """
        if mbox:
            raise "Not implemented"

        return self.create(name)

    def create(self, pathspec):
        """ Create a new mailbox from the given hierarchical name. 
        pathspec:str
        """
        if pathspec not in self.mailboxes.keys():
            path = os.path.join(self.userdir, pathspec)
            if not os.path.exists(path):
                maildir.initializeMaildir(path)
            self.mailboxes[pathspec] = Mailbox(path)
        return self.mailboxes[pathspec]

    def select(self, name, rw=True):
        """ Acquire a mailbox, given its name. 
        name:str
        rw:bool
        """
#        if not rw:
#            raise Exception("Not implemented")

        print 53, name, self.mailboxes
        if name in self.mailboxes:
            return self.mailboxes[name]
        else:
            None

    def delete(self, name):
        """ Delete the mailbox with the specified name.
        name:str
        """
        raise imap4.MailboxException("Permission denied")

    def rename(self, oldname, newname):
        """ Rename a mailbox
        oldname:str
        newname:str
        """
        os.rename(os.path.join(self.userdir, oldname),
                  os.path.join(self.userdir, newname))
        self.mailboxes[newname] = self.mailboxes[oldname]
        del self.mailboxes[oldname]

    def isSubscribed(self, name):
        """ Check the subscription status of a mailbox
        name:str
        """
        return self.mailboxes[name].getMeta('subscribed')
    
    def subscribe(self, name):
        """ Subscribe to a mailbox
        name:str
        """
        self.mailboxes[name].setMeta('subscribed', True)

    def unsubscribe(self, name):
        """ Unsubscribe from a mailbox
        name:str
        """
        self.mailboxes[name].setMeta('subscribed', False)

    def listMailboxes(self, ref, wildcard):
        """ List all the mailboxes that meet a certain criteria 
        ref:str
        wildcard:str
        """
        o = []
        for box in os.listdir(self.userdir):
            o.append((box, self.create(box)))
        return o


class IMAP4Protocol(imap4.IMAP4Server):
    debug = True
    
    def sendLine(self, line):
        if self.debug: log.msg("IMAP4 SERVER:", line)
        imap4.IMAP4Server.sendLine(self, line)


    def lineReceived(self, line):
        if self.debug: log.msg("IMAP4 CLIENT:", line)
        imap4.IMAP4Server.lineReceived(self, line)

class IMAP4Factory(protocol.Factory):
    protocol = IMAP4Protocol
    tlsFactory = None
    portal = None
    
    def buildProtocol(self, address):
        p = self.protocol(contextFactory=self.tlsFactory)
        p.portal = self.portal
        p.factory = self
        return p

