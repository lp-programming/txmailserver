# txmailserver
PyPy2-Twisted based (e)smtp/imap4 implementation

Based on the great mailserver skeleton by Duncan McGreggor circa 2006-2009 (the homepage for which has vanished).  
This has some changes relative to that version.  Notably it uses an external Bayesian spam filter, and can read `/etc/passwd` for a list of mail accounts to populate.  
The mailbox format has been reworked to be compatible with Dovecot and similar IMAP servers.

## (E)SMTP Notes
The SMTP/ESMTP implementation is the most mature part of this software, largely unchanged from Duncan's original work.  By default, it does *require* either `SSL` or `starttls` for external connections.  Also, I strongly recommend setting up a backup outbound MX, as some poorly configured DNS records can cause it to choke on delivering mail.

## IMAP Notes
Using the imap implementation is optional.  You can easily configure an external IMAP server (tested extensively with Dovecot).  If you want to use thunderbird or other third party mail clients, I recommend using an external server.  This package strives to be strictly standards compliant, but does not perfectly handle clients which *aren't* standard compliant.  

By default, the IMAP server *never* deletes anything.  Files flagged deleted get the standard IMAP deleted flag set.  When the `EXPUNGE` command is issued, the files get moved to a separate trash directory.  In my standard setup, they are deleted via a cronjob after a week.

