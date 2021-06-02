import re

__all__ = ["AddressType", "Actual", "Alias", "Maillist", "CatchAll", "Script"]

class AddressType(object):
    def __init__(self, initial):
        self.initial = initial.lower()

    def validate(self, destName, prefixes=None):
        names = [self.initial]
        if prefixes:
            names += [self.initial + pre for pre in prefixes]
        return destName in names

    def __repr__(self):
        return "<%s (%s)>" % (self.__class__.__name__, self.initial)

class Actual(AddressType):

    def __init__(self, userName):
        super(Actual, self).__init__(userName)
        self.dest = userName.lower()

class Alias(AddressType):

    def __init__(self, userName, dest):
        super(Alias, self).__init__(userName)
        self.dest = dest.lower()

class Maillist(AddressType):

    def __init__(self, mailListName, recipients):
        if not isinstance(recipients, list):
            raise Exception("Maillist recipients must be of type list!")
        super(Maillist, self).__init__(mailListName)
        self.dest = recipients

class _Regex(AddressType):

    def __init__(self, catchName):
        super(_Regex, self).__init__(catchName)
        self.validator = re.compile(catchName, re.I)

    def validate(self, destName, prefixes=None):
        return self.validator.match(destName)


class CatchAll(_Regex):
    
    def __init__(self, catchName, dest):
        super(CatchAll, self).__init__(catchName)
        self.dest = dest.lower()
    

class Script(_Regex):

    def __init__(self, catchName, func):        
        super(Script, self).__init__(catchName)
        self.func = func
        self.dest = catchName
