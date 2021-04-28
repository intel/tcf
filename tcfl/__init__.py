#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import base64
import hashlib
import random
import sys
import threading

import commonl

class msgid_c(object):
    """
    Accumulate data local to the current running thread.

    This is used to generate a random ID (four chars) at the beginning
    of the testcase run in a thread by instantiating a local object of
    this class. As we call deeper into functions to do different
    parts, we instantiate more objects that will add random characters
    to said ID *just* for that call (as when the object created goes
    out of scope, the ID is returned to what it was.

    So thus, as the call chain gets deeper, the message IDs go::

      abcd
      abcdef
      abcdefgh
      abcdefghij

    this allows for easy identification / lookup on a log file or
    classification.

    Note we also keep a depth (usefuly for increasing the verbosity of
    log messages) and a phase, which we use it to set the phase in
    which we are running, so log messages don't have to specify it.

    Note this is to be used as::

      with msgid_c(ARGS):
        do stuff...
        msgid_c.ident()
        msgid_c.phase()
        msgid_c.depth()
    """

    tls = threading.local()

    @classmethod
    def cls_init(cls):
        cls.tls.msgid_lifo = []

    def __init__(self, s = None,
                 phase = None, depth = None, parent = None,
                 depth_relative = None,
                 subcase = None):
        cls = type(self)
        if not hasattr(cls.tls, "msgid_lifo"):
            cls.cls_init()

        if depth_relative == None:
            # if a subcase is given but no relative depth, mostly this
            # is used to set hte case, not to increase verbosity
            # depth, so keep it at zero
            if subcase:
                depth_relative = 0
            else:
                depth_relative = 1

        # Init from parent or first in the stack or defaults
        if parent:
            assert isinstance(parent, msgid_c), \
                "parent must be type msgid_c; got %s" % type(parent)
            # inherited from the parent
            self._ident = parent._ident
            self._depth = parent._depth
            self._phase = parent._phase
            self._subcase = parent._subcase
        elif cls.tls.msgid_lifo:	# init from the first in the stack
            f = cls.tls.msgid_lifo[-1]
            self._ident = f._ident
            self._depth = f._depth + depth_relative
            self._phase = f._phase
            self._subcase = f._subcase
        else:
            self._ident = ""
            self._phase = None
            self._depth = 0
            self._subcase = None

        # that then can be overriden
        if s:
            if not isinstance(s, str):
                raise TypeError('expected str, but got {!r}'.format(type(s)))
            self._ident += s

        if phase:
            assert isinstance(phase, str)
            self._phase = phase
        if depth != None:
            assert isinstance(depth, int)
            self._depth = depth

        subl = []
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            if f._subcase:
                subl.append(f._subcase)
        if subcase:
            subl.append(subcase)
        self._subcase = "##".join(subl)


    def __enter__(self):
        cls = type(self)
        cls.tls.msgid_lifo.append(self)
        return self

    def __exit__(self, exct_type, exce_value, traceback):
        cls = type(self)
        if exce_value:
            # set this for tcfl.tc.result_c.from_exception()--when we
            # raise any exception from inside a msgid_c context, we
            # want it to be reported with the right subcase
            setattr(exce_value, "_subcase_base", cls.subcase())
        cls.tls.msgid_lifo.pop()

    @classmethod
    def encode(cls, s, l):
        assert isinstance(s, str)
        assert isinstance(l, int)
        # Instead of +/ we use AZ, even if it removes some key-space,
        # it shall be good enough
        m = hashlib.sha256(s.encode('utf-8'))
        return base64.b64encode(bytes(m.digest()), b'AZ')[:l].lower()

    @classmethod
    def generate(cls, l = 4):
        assert isinstance(l, int)
        return cls.encode("".join(chr(random.randint(0, 255))
                                  for i in range(l)), l)

    @classmethod
    def depth(cls):
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._depth
        else:
            return 0

    @classmethod
    def phase(cls):
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._phase
        else:
            return None

    @classmethod
    def ident(cls):
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._ident
        else:
            return None

    @classmethod
    def subcase(cls):
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._subcase
        else:
            return None

    @classmethod
    def current(cls):
        if cls.tls.msgid_lifo:
            return cls.tls.msgid_lifo[-1]
        else:
            return None

    @classmethod
    def parent(cls):
        if len(cls.tls.msgid_lifo) > 1:
            return cls.tls.msgid_lifo[-2]
        return None


def inventory_keys_fix(d):
    """
    Given a dictionary, transform the keys so it is valid as a TCF inventory

    :param dict d: dictionary where all the keys are strings
    """
    # convert all keys to have only chars in the -_A-Za-z0-9 set
    seen = set()
    current_keys = list(d.keys())
    for key in current_keys:
        safe = commonl.name_make_safe(key)
        # safe making looses data, key 1:2 will be converted to 1_2; if
        # there is already a 1_2...it would overwrite it. So we append
        # a counter until it is different. Note we also do this with
        # keys made safe, othrewise 1:2 would be overriden by 1/2.
        count = 0
        while safe in seen or (safe != key and safe in current_keys):
            count += 1
            safe = f"{safe}.{count}"
        seen.add(safe)
        value = d[key]
        if safe != key:
            if isinstance(value, dict):
                d[safe] = inventory_keys_fix(value)
            else:
                d[safe] = value
            del d[key]
    return d
