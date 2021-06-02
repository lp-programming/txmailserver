import socket
from twisted.names import error, dns
from twisted.internet.error import DNSLookupError

from twisted.mail.relaymanager import SmartHostESMTPRelayingManager, ESMTPManagedRelayerFactory, ESMTPManagedRelayer, _AttemptManager as AM, MXCalculator as MXC
from twisted.mail.smtp import PLAINAuthenticator
import twisted.mail.relaymanager

class MXCalculator(MXC):
    fallbackRelay = None
    def _ebMX(self, failure, domain):
        # Anything goes wrong, we punt upstream if possible
        if self.fallbackRelay is not None:
            failure.trap(error.DNSNameError)
            print("MX lookup failed for %s; using smart host %s" % (domain, self.fallbackRelay))

            # Alright, I admit, this is a bit icky.
            d = self.resolver.getHostByName(self.fallbackRelay)

            def cbResolved(addr):
                return dns.Record_MX(name=addr)

            def ebResolved(err):
                err.trap(error.DNSNameError)
                raise DNSLookupError()

            d.addCallbacks(cbResolved, ebResolved)
            return d
        return MXC._ebMX(self, failure, domain)




class ManagedRelayer(ESMTPManagedRelayer):
    def __init__(self, messages, manager, password, contextFactory, smartHost, **kw):
        ESMTPManagedRelayer.__init__(self, messages, manager, password, contextFactory, socket.gethostname(), **kw)
        self.smartHost = smartHost

    def rawDataReceived(self, data):
        raise NotImplementedError


class ManagedRelayerFactory(ESMTPManagedRelayerFactory):
    protocol = ManagedRelayer

    def __init__(self, messages, manager, relay, username, password, *args, **kw):
        ESMTPManagedRelayerFactory.__init__(self, messages, manager, password, None, relay, *args, **kw)
        self.username = username
        self.password = password
        

    def buildProtocol(self, addr):
        s = self.password
        protocol = self.protocol(self.messages, self.manager, s,
            self.contextFactory, *self.pArgs, **self.pKwArgs)
        protocol.registerAuthenticator(PLAINAuthenticator(self.username))
        protocol.factory = self
        return protocol


class SmartHostRelayingManager(SmartHostESMTPRelayingManager):
    factory = ManagedRelayerFactory
    mxcalc = MXCalculator()

    def _cbExchange(self, address, port, factory):
        return SmartHostESMTPRelayingManager._cbExchange(self, address, port, factory)

    def _ebExchange(self, failure, factory, domain):
        return SmartHostESMTPRelayingManager._ebExchange(self, failure, factory, domain)

    def __init__(self, queue, *a, **kw):
        SmartHostESMTPRelayingManager.__init__(self, queue, *a, **kw)

    def checkState(self):
        SmartHostESMTPRelayingManager.checkState(self)


class _AttemptManager(AM):
    def __init__(self, *a, **kw):
        AM.__init__(self, *a, **kw)
        self.pendingSmartHost = []

    def notifyFailure(self, relay, message):

        smartHost, username, password = self.manager.__auth__
        factory = self.manager.factory([message], self, *self.manager.__auth__, **self.manager.fKwArgs)
        from .reactor import reactor
        reactor.connectTCP(smartHost, self.manager.PORT, factory=factory)
        bn = message.split('queue/', 1)[1]
        try:
            self.manager.managed[relay].remove(bn)
        except:
            pass

        if not self.manager.managed[relay]:
            self.manager.managed.pop(relay)

        self.manager.managed[factory] = [bn]
        self.pendingSmartHost.append(relay)

    def notifyDone(self, relay):
        """A relaying SMTP client is disconnected.

        unmark all pending messages under this relay's responsibility
        as being relayed, and remove the relay.
        """
        if self._completionDeferreds is None:
            self._completionDeferreds = []
        if relay in self.pendingSmartHost:
            return AM.notifyDone(self, relay)

        messages = self.manager.managed.get(relay, ())
        if not messages:
            return AM.notifyDone(self, relay)
        
        self.pendingSmartHost.append(relay)
        smartHost, username, password = self.manager.__auth__
        factory = self.manager.factory(['queue/'+i for i in self.manager.managed[relay]], self, *self.manager.__auth__, **self.manager.fKwArgs)
        from .reactor import reactor
        reactor.connectTCP(smartHost, self.manager.PORT, factory=factory)
        self.manager.managed[factory] = self.manager.managed.pop(relay)



twisted.mail.relaymanager._AttemptManager = _AttemptManager
