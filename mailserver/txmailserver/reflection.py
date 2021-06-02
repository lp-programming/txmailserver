from twisted.mail import imap4

def imap4server__cbStore(self, result, tag, mbox, uid, silent):
        if result and not silent:
              for (k, v) in result.iteritems():
                  if uid:
                      uidstr = ' UID %d' % mbox.getUID(k)
                  else:
                      uidstr = ''
                  self.sendUntaggedResponse('%d FETCH (%s FLAGS (%s))' %
                                            (k, uidstr, ' '.join(v)))
        self.sendPositiveResponse(tag, 'STORE completed')

imap4.IMAP4Server._IMAP4Server__cbStore = imap4server__cbStore
