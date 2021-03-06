#!/usr/bin/env python
# Copyright (c) 2015 Peixuan Ding
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
from __future__ import print_function

import re
import os
import sys
import json
from sqlite3 import dbapi2, Binary
from functools import reduce
from collections import MutableMapping

__version__ = "0.0.10"
DEBUG=True

class sqlmap(MutableMapping):
    def __init__(self, sqlfile):
        self.sqlfile = sqlfile
        self.connection = dbapi2.Connection(sqlfile)
        self.connection.text_factory = Binary
        self.cursor = self.connection.cursor()
        self.cursor.execute('create table if not exists token_table(token TEXT primary key, ham INTEGER, spam INTEGER)')
        self.cursor.execute('create table if not exists whitelist(address TEXT primary key)')
        self.__dirty = True
       
    def whitelist(self, From):
        if From:
            if '<' in From:
                From = From.split('<')[1].split('>')[0]
        self.cursor.execute("select * from whitelist where address=?", (From,))
        itm = self.cursor.fetchone()
        if not itm:
            self.cursor.execute("insert into whitelist values (?)", (From,))
            self.__dirty = True
    
    def isWhitelisted(self, From):
        if From:
            if '<' in From:
                From = From.split('<')[1].split('>')[0]
        self.cursor.execute("select * from whitelist where address=?", (From,))
        itm = self.cursor.fetchone()
        return bool(itm)

    def __getitem__(self, item):
        try:
            if isinstance(item, unicode):
                item = item.encode('charmap')
            elif not isinstance(item, str):
                item = str(item)
            self.cursor.execute('select * from token_table where token=?', (item,))
            itm = self.cursor.fetchone()
            if itm:
                return sqlitem(self, itm)
            raise KeyError(item)
        except:
            raise KeyError(item)

    def __setitem__(self, item, value):
        self.__dirty = True
        if isinstance(item, unicode):
            item = item.encode('charmap')
        elif not isinstance(item, str):
            item = str(item)
        value = tuple(value)
        self.cursor.execute('replace into token_table values (?, ?, ?)', (item,) + value)

    def __delitem__(self, item):
        if isinstance(item, unicode):
            item = item.encode('charmap')
        elif not isinstance(item, str):
            item = str(item)
        self.cursor.execute('delete from token_table where token=?', (item,))

    def __iter__(self):
        self.cursor.execute('select * from token_table')
        for i in self.cursor:
            yield sqlitem(self, i)

    def __len__(self):
        self.cursor.execute('select count(token) from token_table')
        return self.cursor.fetchone()[0]

    def save(self):
        self.connection.commit()

    @property
    def spam_count_total(self):
        if self.__dirty:
            self.cursor.execute(u'select sum(spam), sum(ham) from token_table')
            self.__spam_total, self.__ham_total = self.cursor.fetchone()
            self.__dirty = False
        return self.__spam_total
        

    @property
    def ham_count_total(self):
        if self.__dirty:
            self.cursor.execute(u'select sum(spam), sum(ham) from token_table')
            self.__spam_total, self.__ham_total = self.cursor.fetchone()
            self.__dirty = False
        return self.__ham_total
        

class sqlitem(object):
    def __init__(self, parent, entry):
        self.parent = parent
        self.token = entry[0]
        self.ham = entry[1]
        self.spam = entry[2]

    def __getitem__(self, idx):
        if idx==0:
            return self.ham
        if idx==1:
            return self.spam
        raise KeyError(idx)

    def __setitem__(self, idx, value):
        if idx==0:
            self.ham=value
            self.save()
            return
        if idx==1:
            self.spam=value
            self.save()
            return
        raise KeyError(idx)

    def __iter__(self):
        yield self.ham
        yield self.spam

    def save(self):
        self.parent[self.token]=self.ham, self.spam

    

    

class Model(object):
    """Save & Load the model in/from the file system using Python's json
    module.
    """
    DEFAULT_DATA_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "model.db")

    @property
    def spam_count_total(self):
        return self.token_table.spam_count_total

    @property
    def ham_count_total(self):
        return self.token_table.ham_count_total

    def __init__(self, file_path=None, create_new=False, upgrade_from=None):
        """Constructs a Model object by the indicated ``file_path``, if the
        file does not exist, create a new file and contruct a empty model.

        :param file_path: (optional) Path for the model file indicated, if
            path is not indicated, use the built-in model file provided by
            the author, which is located in the ``antispam`` package folder.

        :param create_new: (option) Boolean. If ``True``, create an empty
            model. ``file_path`` will be used when saving the model. If there
            is an existing model file on the path, the existing model file
            will be overwritten.
        """
        self.file_path = file_path if file_path else self.DEFAULT_DATA_PATH
        if create_new:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)

        self.token_table = sqlmap(self.file_path)

        if upgrade_from:
            n1, n2, token_table = self.load(upgrade_from)
            for k, v in token_table.iteritems():
                self.token_table[k] = tuple(v)

    def load(self, file_path=None):
        """Load the serialized file from the specified file_path, and return
        ``spam_count_total``, ``ham_count_total`` and ``token_table``.

        :param file_path: (optional) Path for the model file. If the path does
            not exist, create a new one.
        """
        file_path = file_path if file_path else self.DEFAULT_DATA_PATH
        if not os.path.exists(file_path):
            with open(file_path, 'a'):
                os.utime(file_path, None)
        with open(file_path, 'rb') as f:
            try:
                return json.load(f, encoding='charmap')
            except:
                return (0, 0, {})

    def save(self):
        """Serialize the model using Python's json module, and save the
        serialized modle as a file which is indicated by ``self.file_path``."""
        self.token_table.save()


class Detector(object):
    """A baysian spam filter

    :param path: (optional) Path for the model file, will be passes to
        ``Model`` and construct a ``Model`` object based on ``path``.
    """
    TOKENS_RE = re.compile(r"\$?\d*(?:[.,]\d+)+|\w+-\w+|\w+", re.U)
    INIT_RATING = 0.4

    def __init__(self, path=None, create_new=False):
        self.model = Model(path, create_new)
       
    def whitelistFrom(self, From):
        self.model.token_table.whitelist(From)

    def _get_word_list(self, msg):
        """Return a list of strings which contains only alphabetic letters,
        and keep only the words with a length greater than 2.
        """
        return filter(lambda s: len(s) > 2,
                      self.TOKENS_RE.findall(msg.lower()))

    def save(self):
        """Save ``self.model`` based on ``self.model.file_path``.
        """
        self.model.save()

    def train(self, msg, is_spam):
        """Train the model.

        :param msg: Message in string format.
        :param is_spam: Boolean. If True, train the message as a spam, if
            False, train the message as a ham.
        """
        token_table = self.model.token_table

        for word in self._get_word_list(msg.lower()):
            if word in token_table:
                token = token_table[word]
                if is_spam:
                    token[1] += 1
                else:
                    token[0] += 1
            else:
                token_table[word] = [0, 1] if is_spam else [1, 0]

    def score(self, msg, From=None):
        """Calculate and return the spam score of a msg. The higher the score,
        the stronger the liklihood that the msg is a spam is.

        :param msg: Message in string format.
        """
        if From and '<' in From:
            From = From.split('<')[1].split('>')[0]
        if From and self.model.token_table.isWhitelisted(From):
            print("whitelisted")
            return 0
        token_table = self.model.token_table
        hashes = self._get_word_list(msg.lower())
        ratings = []
        for h in hashes:
            if h in token_table:
                ham_count, spam_count = token_table[h]
                if spam_count > 0 and ham_count == 0:
                    rating = 0.99
                elif spam_count == 0 and ham_count > 0:
                    rating = 0.01
                elif self.model.spam_count_total > 0 and self.model.ham_count_total > 0:
                    ham_prob = float(ham_count) / float(
                        self.model.ham_count_total)
                    spam_prob = float(spam_count) / float(
                        self.model.spam_count_total)
                    rating = spam_prob / (ham_prob + spam_prob)
                    if rating < 0.01:
                        rating = 0.01
                else:
                    rating = self.INIT_RATING
            else:
                rating = self.INIT_RATING
            ratings.append(rating)
        
        if (len(ratings) == 0):
            return 0
        
        if (len(ratings) > 20):
            ratings.sort()
            ratings = ratings[:10] + ratings[-10:]

        product = reduce(lambda x, y: x * y, ratings)
        alt_product = reduce(lambda x, y: x * y, map(lambda r: 1.0 - r,
                                                     ratings))
        ret = product / (product + alt_product)
        if DEBUG:
            print('Score:',ret)
        return ret

    def is_spam(self, msg):
        """Decide whether the message is a spam or not.
        """
        return self.score(msg) > 0.9


module = sys.modules[__name__]

def get_detector():
    if hasattr(module, 'obj'):
        return getattr(module, 'obj')
    detector = Detector()
    setattr(module, 'obj', detector)
    return detector

def score(msg, From=None):
    """Score the message based on the built-in model.

    :param msg: Message to be scored in string format.
    """
    detector = get_detector()
    return detector.score(msg, From=From)


def is_spam(msg):
    """Decide whether the message is a spam or not based on the built-in model.

    :param msg: Message to be classified in string format.
    """
    try:
        return score(msg) > 0.9
    except:
        return False


def train(msg, isspam):
    if hasattr(module, 'obj'):
        detector = getattr(module, 'obj')

    else:
        detector = Detector()
        setattr(module, 'obj', detector)
    try:
        if msg.is_multipart():
            import re
            From = re.search('From: .*\n', str(msg._payload[0]))
            if From:
                From = From.group()
                detector.whitelistFrom(From)
                if '<' in From:
                    From = From.split('<')[1].split('>')[0]
                    detector.whitelistFrom(From)
                
    except Exception as e:
        print (332, e)

    msg = str(msg)
    ret = detector.train(msg, isspam)
    detector.save()
    return ret
    
def whitelist(message):
    import email
    original_headers = message.get_payload()[0].get_payload().split('Forwarded Message', 1)[1].split('\n',1)[1].split('\n\n')[0]
    original_message = email.message_from_string(original_headers)
    if original_message:
        original_from = original_message.get('From')
        if original_from:
            detector = get_detector()
            detector.whitelistFrom(original_from)
            
        
    
def blacklist(message):
    pass

if __name__ == "__main__":
    d = Detector(create_new=True)

    d.train("Super cheap octocats for sale at GitHub.", True)
    d.train("Hi John, could you please come to my office by 3pm? Ding", False)

    m1 = "Cheap shoes for sale at DSW shoe store!"
    print(d.score(m1))

    m2 = "Hi mark could you please send me a copy of your machine learning homework? thanks"
    print(d.score(m2))

