from twisted.internet.epollreactor import EPollReactor
from twisted.internet.main import installReactor
reactor = EPollReactor()
installReactor(reactor)
