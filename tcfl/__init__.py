#! /usr/bin/python3
#
# Copyright (c) 2017-21 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import collections
import concurrent.futures
import copy
import datetime
import errno
import hashlib
import inspect
import itertools
import json
import logging
import os
import pickle
import pprint
import random
import re
import shutil
import socket
import urllib

import base64
import hashlib
import random
import requests
import subprocess
import sys
import traceback
import threading
import urllib
import warnings

import filelock
import requests

import commonl
import tcfl.ttb_client # ...ugh

logger = logging.getLogger("tcfl")
log_sd = logging.getLogger("server-discovery")

class result_c:
    def __init__(self, passed = 0, errors = 0, failed = 0,
                 blocked = 0, skipped = 0):
        self.passed = passed
        self.errors = errors
        self.failed = failed
        self.blocked = blocked
        self.skipped = skipped

    def __iadd__(self, b):
        self.passed += b.passed
        self.errors += b.errors
        self.failed += b.failed
        self.blocked += b.blocked
        self.skipped += b.skipped
        return self

    def __eq__(self, b):
        if b == None:
            return False
        return self.passed == b.passed \
            and self.errors == b.errors \
            and self.failed == b.failed \
            and self.blocked == b.blocked \
            and self.skipped == b.skipped

    def __add__(self, b):
        return result_c(self.passed + b.passed,
                        self.errors + b.errors,
                        self.failed + b.failed,
                        self.blocked + b.blocked,
                        self.skipped + b.skipped)

    def __repr__(self):
        return "%d (passed=%d errors=%d failed=%d blocked=%d skipped=%d)" % (
            self.total(), self.passed, self.errors, self.failed,
            self.blocked, self.skipped)

    def total(self):
        return self.passed + self.errors + self.failed \
            + self.blocked + self.skipped

    # Return an object on which only one value is set to one and the
    # rest to zero; choose by priority, to report the worse condition
    #
    # If any failed, 1 failure
    # If any errrors, 1 error
    # if any blocked, 1 block
    # if any passed, 1 pass
    # if any skipped, 1 skip
    def summary(self):
        if self.failed > 0:
            return result_c(0, 0, 1, 0, 0)
        elif self.errors > 0:
            return result_c(0, 1, 0, 0, 0)
        elif self.blocked > 0:
            return result_c(0, 0, 0, 1, 0)
        elif self.passed > 0:
            return result_c(1, 0, 0, 0, 0)
        elif self.skipped > 0:
            return result_c(0, 0, 0, 0, 1)
        return result_c(0, 0, 0, 0, 0)

    def normalized(self):
        # There might be a more elegant way to do this, but this is
        # quite intelligible
        if self.passed == 0:
            passed = 0
        else:
            passed = 1
        if self.errors == 0:
            errors = 0
        else:
            errors = 1
        if self.failed == 0:
            failed = 0
        else:
            failed = 1
        if self.blocked == 0:
            blocked = 0
        else:
            blocked = 1
        if self.skipped == 0:
            skipped = 0
        else:
            skipped = 1
        return result_c(passed, errors, failed, blocked, skipped)

    @staticmethod
    def from_retval(retval):
        if isinstance(retval, result_c):
            return retval
        # things that mean pass -- return nothing or True
        if retval == True or retval == None:
            return result_c(passed = 1)
        # but returning Flase, something failed
        if retval == False:
            return result_c(failed = 1)
        if retval == "SKIP":
            # FIXME: undocumented
            return result_c(skipped = 1)
        raise blocked_e(
            f"don't know how to interpret return value of type '{type(retval)}';"
            " return None/True (PASS), False (FAIL), raise an"
            " exception (FAIL/ERRR/BLCK); see FIXME:documentation")


    @staticmethod
    def _e_maybe_info(e, attachments):
        # Exceptions might raise, in their arguments, a tuple
        # (str, dict), where the string is the message and the
        # dictionary are attachments passed to report_*()
        # functions. In said case, update the attachments and
        # return the message. See :py:class:`exception`.
        if isinstance(e, exception):
            attachments.update(e.attachments_get())
            return e.args[0]
        return e

    def report(self, _reporter, message, attachments = None,
               level = None, dlevel = 0, alevel = 2):
        assert isinstance(_reporter, (tc.tc_c, tc.target_c))
        assert isinstance(message, str)
        if attachments:
            assert isinstance(attachments, dict)
        else:
            attachments = dict()
        if level:
            assert level >= 0
        assert dlevel >= 0
        assert alevel >= 0

        if 'target' in attachments:
            reporter = attachments['target']
            # create a copy of the dictionary and remove the target
            # spec, use it as reporter.
            attachments = dict(attachments)
            attachments.pop('target')
            assert isinstance(reporter, target_c), \
                "attachment 'target' does not point to a " \
                "tcfl.tc.target_c but to a type %s" % type(reporter).__name__
        else:
            reporter = _reporter

        if self.blocked:
            report_fn = reporter.report_blck
        elif self.failed:
            report_fn = reporter.report_fail
        elif self.errors:
            report_fn = reporter.report_error
        elif self.passed:
            report_fn = reporter.report_pass
        elif self.skipped:
            report_fn = reporter.report_skip
        else:
            report_fn = reporter.report_blck
            message = '(nothing ran) ' + message

        report_fn(message, attachments,
                  level = level, dlevel = dlevel, alevel = alevel)


    @staticmethod
    def report_from_exception(_tc, e, attachments = None,
                              force_result = None):
        """
        Given an exception, report using the testcase or target report
        infrastructure on the exception, traces to it as well as any
        attachments it came with and return a valid :class:`result_c`
        code.

        By default, this is the mapping:

        - :meth:`tc.report_pass<reporter_c.report_pass>` is used for
          :exc:`pass_e`
        - :meth:`tc.report_pass<reporter_c.report_error>` is used for
          :exc:`error_e`
        - :meth:`tc.report_pass<reporter_c.report_fail>` is used for
          :exc:`failed_e`
        - :meth:`tc.report_pass<reporter_c.report_blck>` is used for
          :exc:`blocked_e` and any other exception
        - :meth:`tc.report_pass<reporter_c.report_skip>` is used for
          :exc:`skip_e`

        However, it can be forced by passing as *force_result* or each
        testcase can be told to consider specific exceptions as others
        per reporting using the :attr:`tcfl.tc.tc_c.exception_to_result`.

        Attachments:

         - *subcase* (str): the name of a subcase as which to report this

        :param bool force_result: force the exception to be
          interpreted as :exc:`tcfl.tc.pass_e`, :exc:`error_e`,
          :exc:`failed_e`, :exc:`tcfl.tc.blocked_e`, or :exc:`skip_e`; note
          there is also translation that can be done from
          :attr:`tcfl.tc.tc_c.exception_to_result`.
        """
        if attachments == None:
            attachments = {}
        phase = msgid_c.phase()
        if phase == None:
            phase = ""
        else:
            phase = phase + " "
        _e = result_c._e_maybe_info(e, attachments)
        reporter = attachments.pop('target', _tc)
        subcase = attachments.pop('subcase', None)
        alevel = attachments.pop('alevel', 1)
        dlevel = attachments.pop('dlevel', 0)
        level = attachments.pop('level', msgid_c.depth())

        # this is created by tcfl.msgid_c.__exit__() if it catches an
        # exception flying up, so we can report it with proper subcase
        # context
        subcase_base = getattr(e, '_subcase_base', None)

        # COMPAT: type(_tc).__name__ == "target_c" for old style tcfl.tc
        if isinstance(_tc, target_c) or type(_tc).__name__ == "target_c":
            tc = _tc.testcase
        elif isinstance(reporter, tc_c) or type(_tc).__name__ == "tc_c":
            tc = _tc
        else:
            raise AssertionError(
                "_tc: expected type tc_c or target_c or subclass;"
                f" got {type(_tc)}")

        trace_alevel = 1
        if force_result == None:
            force_result = tc.exception_to_result.get(type(e), None)
        if isinstance(e, pass_e) or force_result == pass_e:
            msg_tag = "PASS"
            tag = valid_results['PASS'][1]
            result = result_c(1, 0, 0, 0, 0)
        elif isinstance(e, error_e) or force_result == error_e:
            msg_tag = "ERRR"
            tag = valid_results['ERRR'][1]
            result = result_c(0, 1, 0, 0, 0)
        elif isinstance(e, failed_e) or force_result == failed_e:
            msg_tag = "FAIL"
            tag = valid_results['FAIL'][1]
            result = result_c(0, 0, 1, 0, 0)
        elif isinstance(e, blocked_e) or force_result == blocked_e:
            msg_tag = "BLCK"
            tag = valid_results['BLCK'][1]
            result = result_c(0, 0, 0, 1, 0)
        elif isinstance(e, skip_e) or force_result == skip_e:
            msg_tag = "SKIP"
            tag = valid_results['SKIP'][1]
            result = result_c(0, 0, 0, 0, 1)
        else:
            msg_tag = "BLCK"
            tag = 'blocked: exception'
            result = result_c(0, 0, 0, 1, 0)
            # This is bad, report as high as we can
            dlevel = 0
            trace_alevel = 0
        _attachments = { "trace": traceback.format_exc() }
        _attachments.update(attachments)
        reporter._report(
            level + dlevel, level + dlevel + alevel + trace_alevel, msg_tag,
            "%s%s: %s" % (phase, tag, _e),
            _attachments,
            subcase = subcase, subcase_base = subcase_base,
        )
        return result

    @staticmethod
    def from_exception_cpe(tc, e, result_e = None):
        # can't default to error_e because it is defined after this
        # AND we need result_c to define error_e
        if result_e == None:
            result_e = error_e
        return result_c.report_from_exception(
            tc, e, attachments = {
                "output": e.output,
                "return": e.returncode,
                "cmd": e.cmd
            },
            force_result = result_e
        )

    @staticmethod
    def call_fn_handle_exception(fn, *args, **kwargs):

        _tc = args[0] # The `self`  argument to the test case
        try:
            return fn(*args, **kwargs)
        # Some exceptions that are common and we know about, so we
        # can print some more info that will be helpful
        except AssertionError as e:
            if isinstance(e.args, tuple) and len(e.args) > 0 \
               and len(e.args[0]) == 2:
                # if you raise AssertionError and the second
                # expression is a tupple (str, dict), we convert
                # that to a blocke_d(str, attachments = dict)
                if isinstance(e.args[0][1], dict):
                    newe = blocked_e(e.args[0][0], e.args[0][1])
                    return result_c.report_from_exception(_tc, newe)
            return result_c.report_from_exception(_tc, e)
        except subprocess.CalledProcessError as e:
            return result_c.from_exception_cpe(_tc, e)
        except OSError as e:
            attachments = dict(
                errno = e.errno,
                strerror = e.strerror
            )
            if e.filename:
                attachments['filename'] = e.filename
            return result_c.report_from_exception(_tc, e, attachments)
        except Exception as e:
            return result_c.report_from_exception(_tc, e)


    @staticmethod
    def from_exception(fn):
        """
        Call a phase function to translate exceptions into
        :class:`tcfl.tc.result_c` return codes.


        Passes through the return code, unless it is None, in which
        case we just return result_c(1, 0, 0, 0, 0)

        Note this function prints some more extra detail in case of
        fail/block/skip.
        it.
        """
        def _decorated_fn(*args, **kwargs):
            return result_c.call_fn_handle_exception(fn, *args, **kwargs)

        return _decorated_fn


class exception(Exception, result_c):
    """\
    General base exception for reporting results of any phase of test
    cases

    :param str msg: a message to report

    :param dict attachments: a dictionary of items to report, with a
      few special fields:

      - `target`: this is a :py:class:`tcfl.tc.target_c` which shall be used
        for reporting--when indicating this field, the reporting will
        associate this exception to the given target.

      - `dlevel`: this is an integer that indicates the relative
        level of verbosity (FIXME: link to detailed explanation)

      - `alevel`: this is an integer that indicates the relative
        level of verbosity for attachments (FIXME: link to detailed
        explanation)

      - `recoverable`: (bool) for conditions that might want to be
        retried, the upper layers of code might want to determine what
        to do about them.

      - any other fields will be passed verbatim and reported

    Have to use a dictionary (vs using kwargs) so the name of the
    keys can contain spaces, for better reporting.
    """
    def __init__(self, description, attachments = None, **result_c_kwargs):
        if attachments == None:
            attachments = {}
        else:
            assert isinstance(attachments, dict)
        Exception.__init__(self, description, attachments)
        result_c.__init__(self,  **result_c_kwargs)
        self.attachments = attachments

    def attachments_get(self):
        return self.attachments

    def attachment_get(self, name, default = None):
        return self.attachments.get(name, default)

    def attachments_update(self, d):
        """
        Update an exception's attachments
        """
        assert isinstance(d, dict)
        self.attachments.update(d)

    def __repr__(self):
        return self.args[0]

    tag = None

    def _descr(self):
        result = valid_results.get(self.tag, None)
        if result == None:
            raise AssertionError(
                "Invalid tag '%s', not a tcfl.tc.valid_result" % self.tag)
        return result

    def descr(self):
        """
        Return the conceptual name of this exception in present tense

        >>> pass_e().descr()
        >>> "pass"
        >>> fail_e().descr()
        >>> "fail"
        ...
        """
        return self._descr()[0]

    def descr_past(self):
        """
        Return the conceptual name of this exception in past tense

        >>> pass_e().descr()
        >>> "passed"
        >>> fail_e().descr()
        >>> "failed"
        ...
        """
        return self._descr()[1]


class pass_e(exception):
    """
    The test case passed
    """
    tag = 'PASS'	# see valid_results and exception.descr*

class block_e(exception):
    """
    The test case could not be completed because something failed and
    disallowed testing if it woud pass or fail
    """
    tag = 'BLCK'	# see valid_results and exception.descr*
blocked_e = block_e

class error_e(exception):
    """
    Executing the test case found an error
    """
    tag = 'ERRR'	# see valid_results and exception.descr*

class timeout_error_e(error_e):
    """
    The test case timedout and we consider it an error
    """
    pass

class fail_e(exception):
    """
    The test case failed
    """
    tag = 'FAIL'	# see valid_results and exception.descr*
failed_e = fail_e

class timeout_fail_e(fail_e):
    """
    The test case timedout and we consider it a failure
    """
    pass
timeout_failed_e = timeout_fail_e

class skip_e(exception):
    """
    A decission was made to skip executing the test case
    """
    tag = 'SKIP'	# see valid_results and exception.descr*

#: List of valid results and translations in present and past tense
#:
#: - *pass*: the testcase has passed (raise :py:exc:`tcfl.tc.pass_e`)
#:
#: - *fail*: the testcase found a problem it **was** looking for, like an
#:   assertion failure or inconsistency in the code being exercised (raise
#:   :py:exc:`tcfl.tc.failed_e`)
#:
#: - *errr*: the testcase found a problem it **was not** looking for,
#:   like a driver crash; raise :py:exc:`tcfl.tc.error_e`,
#:
#: - *blck*: the testcase has blocked due to an infrastructure issue
#:   which forbids from telling if it passed, failed or errored (raise
#:   :py:exc:`tcfl.tc.blocked_e`)
#:
#: - *skip*: the testcase has detected a condition that deems it not
#:   applicable and thus shall be skipped (raise
#:   :py:exc:`tcfl.tc.skip_e`)
valid_results = dict(
    PASS = ( 'pass', 'passed' ),
    ERRR = ( 'error', 'errored' ),
    FAIL = ( 'fail', 'failed' ),
    BLCK = ( 'block', 'blocked' ),
    SKIP = ( 'skip', 'skipped' ),
)



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
                 testcase = None, subcase = None):
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
            if testcase == None:	# get testcase from the stack
                testcase = f.testcase
        self.testcase = testcase
        if subcase:
            subl.append(subcase)
        self.subcase = subcase		# this subcase name
        self._subcase = "##".join(subl)	# current subcase chain
        if self.testcase and self.subcase:
	    # we need to create a new subcase, so get to it, so we
            # account for it properly
            self.subtc = testcase._subcase_get(self._subcase)
        else:
            self.subtc = None

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
        else:
            # if we were in a subcase--if no result is filled up with
            # reporting, we'll assume it is a pass--in line with how
            # tc_c.__method_trampoline_call() does when a function
            # returns nothing.
            #
            # Note we only do this if no exception, we let exceptin
            # handling do its own accounting -- urg mess
            if self.subtc:
                if self.subtc.result.total() == 0:
                    self.subtc.result.passed = 1
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
            safe = f"{safe}_{count}"
        seen.add(safe)
        value = d[key]
        if isinstance(value, dict):
            d[safe] = inventory_keys_fix(value)
        else:
            d[safe] = value
        if safe != key:
            del d[key]
    return d



@commonl.lru_cache_disk(
    os.path.join(os.path.expanduser("~"),
                 ".cache", "tcf", "socket_gethostbyname_ex"),
    10 * 60,	# age this cache after 10min
    512)
def socket_gethostbyname_ex_cached(*args, **kwargs):
    return socket.gethostbyname_ex(*args, **kwargs)

@commonl.lru_cache_disk(
    os.path.join(os.path.expanduser("~"),
                 ".cache", "tcf", "socket_gethostbyaddr"),
    10 * 60,	# age this cache after 10min
    512)
def socket_gethostbyaddr_cached(*args, **kwargs):
    return socket.gethostbyaddr(*args, **kwargs)


class server_c:
    """Describe a Remote Target Server.

    Historically this was called *rtb*, meaning *Remote Target
    Broker*-- in many areas of the client code you will see *rtb* and
    *rt* for remote target.

    - Constructor is very simple on purpose, so we can just use it to
      store a pointer to a server without doing network access. All it
      does is validate the URL

    - :meth:`create` <- _url_servers_add(), creates one or more server
      objects from a URL/hostname.

    - :meth:`setup` has to be called before it's used to gather state

    - :meth:`discover` is a high level process used to discover
       servers (querying the network and servers for other servers)

    .. _tcf_discovery_process:

    Server discovery process
    ========================

    This process helps to discover all the servers available in an
    infrastructure with minimum configuration on the client side (ideally
    none).

    This relies on the following assumptions:

    - the servers describe other servers they know about (herd data)
      without login in

    - the servers can trust each other

    - the number of servers might be very high >100s

    - multiple clients and threads might be doing this in parallel;
      the database for caching has to be low

    The client starts the discovery process via a set of seed URLs, that
    come from:

    - the command line and environment

    - entries provided in the :ref:`client configuration files
      <tcf_client_configuration>`

      >>> tcfl.server_c.seed_add("https://myserver.domain:1234")
      >>> tcfl.server_c.seed_add("plainhostname")

    - load cached entries from previous runs (~/.cache/tcf/servers)

    - default seed URL *http://ttbd*; thus, the sysadmin of the local
      network can create a DNS CNAME that points to one or more DNS
      address records representing servers.

    Upon start, the client:

    1. (in parallel) queries each seed URL for their herd dara

    2. parses the herd data for each seed URL, extract the URLs in there,
       recording them all in a list of all URLs; return the new ones as a
       new list of seed URLs

    3. repeats process 1 and 2 with the new list of seed URLs until no more
       new servers are returned for a couple of times.

    Currently, :func:`tcfl.config.setup` calls
    :func:`tcfl.server_discover` which is seeded from URLs added with
    :meth:`tcfl.config.url_add`, command line


    Herd data published by the servers
    ----------------------------------

    When a server has a target called *local*, it is meant to describe the
    server itself and in its inventory it may have a :term:`herd` definition
    section specified :ref:`below <inventory_server_herds>`, which in
    summary looks like::

      $ tcf ls -avv SERVER_AKA/local | grep herds
      SERVER_AKA/local.herds...
      SERVER_AKA/local.herds.HERDNAME1.ID1.url: http://somehost:4323
      SERVER_AKA/local.herds.HERDNAME1.ID1.instance: INSTANCENAME
      SERVER_AKA/local.herds.HERDNAME1.ID2.url: http://somehost.somedomain:5000
      SERVER_AKA/local.herds.HERDNAME1.ID3.url: http://host34.domain.com:5000
      ...
      SERVER_AKA/local.herds.HERDNAME3.ID3.url: http://host34.sweet.com:5000

    The sever also publishes this information in the http://HOSTNAME/ttb
    endpoint with no login required.

    How this information is provisioned into the different servers is left
    to the user/admins, but it can be set from the command line with::

      $ tcf property-set SERVER_AKA/local herds.HERDNAME1.ID1.url http://somehost:4323
      $ tcf property-set SERVER_AKA/local herds.HERDNAME1.ID2.url http://somehost.somedomain:5000

    or via scripting using the :meth:`target.property_set
    <tcfl.tc.target_c.property_set>` call.


    Server Inventory: Herds
    -----------------------

    .. _inventory_server_herds:

    FIXME: this table has horrible formatting when rendered, figure out
    how to make the columns narrower so it is readable

    .. list-table:: Server Inventory
       :header-rows: 1
       :widths: 20 10 10 60
       :width: 50%

       * - Field name
         - Type
           (str, bool, integer,
           float, dictionary)
         - Disposition
           (mandatory, recommended,
           optional[default])
         - Description

       * - herds
         - dictionary
         - Optional
         - Information about other servers this server knows about

       * - herds.HERDNAME
         - dictionary
         - Optional
         - Information about a herd called *HERDNAME*

       * - herds.HERDNAME.HASH
         - dictionary
         - Optional
         - Information about a host in herd called *HERDNAME*; *HASH* is
           an alphanumeric identifier of four or more characters that is
           unique to each server and meant to distinguish different
           entries. The client shall not use it for anything.

       * - herds.HERDNAME.HASH.url
         - string
         - Mandatory
         - Base URL for the server in the form
           *http[s]//HOSTNAME[:PORT]/*.

       * - herds.HERDNAME.HASH.instance
         - string
         - Optional
         - Name for this instance (currently ignored)


    Pending/FIXME
    -------------

    - bad_servers -> register a count of failures to connect, stop
      after three tries consider it unusable
      other bad conditions (bad responses) refuse them

    - fix reporting list tcfl.config.urls -> used in report to jinja2,
      move to use tcfl.server_c.servers

    - replace tcfl.ttb_client.rest_target_broker with tcfl.server_c

    - as soon as we call a server good, start reading its inventory
      in the background

    - if cached, don't query from network until XYZ old?

    """

    def __init__(self, url, ssl_verify = False, aka = None, ca_path = None,
                 herd = None, herds = None, origin = None):

        self.parsed_url = urllib.parse.urlparse(url)
        if self.parsed_url.scheme == "" or self.parsed_url.netloc == "":
            raise ValueError(f"{url}: malformed URL? missing hostname/schema")
        self.url = url
        self.ssl_verify = ssl_verify
        self.aka = aka
        self.ca_path = ca_path
        self.herds = set()
        if herd:
            self.herds.add(herd)
        if herds:
            self.herds.update(herds)
        if origin:
            self.origin = origin
        else:
            self.origin = commonl.origin_get()
        self.reason = None
        self.cache_lockfile = None
        self.fsdb = None


    def setup(self):
        """
        Sets up any other internal data structure that are no strictly
        needed until operating seconday parts of the API (eg: file paths)
        """
        self.aka_make()
        self._cache_setup()

    #: only initialized once we start commiting to disk
    cache_dir = None

    def __repr__(self):
        return self.url + f"@{id(self)}"


    def aka_make(self, override = False):
        if self.aka and not override:
            return
        aka = self.parsed_url.hostname.split('.')[0]
        if self.parsed_url.port:
            aka += f"_{self.parsed_url.port}"
        if self.parsed_url.scheme.lower() != "https":
            aka += "_unencrypted"
        self.aka = aka
        return aka


    def target_release(self, target_id: str, force: bool = False):
        """
        Tell the server to release a target from ownership

        :param str target_id: target name

        :param bool force: request the server to force the releasing
          (might be denied by policy)

        :returns: same as :meth:`send_request`, an empy dictionary on
          success
        """
        return self.send_request(
            "PUT", f"targets/{target_id}/release",
            data = { 'force': force })


    #: List of servers found indexed by URL
    servers = {}

    @classmethod
    def _servers_add_hostname_url(cls, servers, url, origin, seed_port,
                                  aka = None,
                                  ssl_verify = False, ca_path = None,
                                  herd = None, herds = None):

        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.netloc:
            # this looks like a proper URL
            server = cls(url, origin = origin, aka = aka,
                         ssl_verify = ssl_verify, ca_path = ca_path,
                         herd = herd, herds = herds)
            servers[parsed_url.geturl()] = server
            log_sd.info(f"seeded URL {server.url} [{server.origin}]")
            return

        # this looks like a hostname, not a url; let's resolve, in
        # case it yields multiple A records, reverse resolve to
        # names and use defaults on them (HTTPS)
        hostname = url
        try:
            name, aliases, addresses = socket_gethostbyname_ex_cached(hostname)
            log_sd.info(f"seed hostname '{hostname}' [{origin}] -> {name}, {aliases}, {addresses}")
        except OSError as e:
            log_sd.warning(f"ignoring hostname '{hostname}' [{origin}]: {e}")
            return

        servers_from_addresses = set()
        for address in addresses:
            try:
                name, _aliases, _addresses = socket_gethostbyaddr_cached(address)
            except socket.herror as e:
                log_sd.info(
                    f"{address}: can't revers DNS lookup, using IP address:"
                    f" {e}")
                # Overwrite the AKA
                # replace IPv4 or IPv6, because other code will
                # puke on .s and :s
                aka = address.replace(".", "_").replace(":", "_")
            server = cls(
                f"https://{name}:{seed_port}",
                origin = f"{origin} -> DNS address {address} for" \
                f" '{hostname}' -> reverse DNS lookup ",
                aka = aka,
                ssl_verify = ssl_verify, ca_path = ca_path,
                herd = herd, herds = herds)
            servers[f"https://{name}:{seed_port}"] = server
            servers_from_addresses.add(name)
            log_sd.info(f"seeded reverse DNS lookup {server.url} [{server.origin}]")

        # only add servers from aliases if we got none from addresses
        # reverse lookup. Why? because if this record was, eg:
        #
        # ttbd -> ttbd.DOMAIN A1 A2 A3
        #
        # then we'd have three servers NAME(A1), NAME(A2) and NAME(A3)
        # and a fourth ttbd.DOMAIN that would randomly map to A1 A2 or
        # A3 and make things confusing.
        #
        # If it is just giving us an alias but no addresses, then at
        # least it won't get confused--so that's the only case when we
        # consider the alias.
        if servers_from_addresses:
            log_sd.info(
                f"{hostname}: ignoring aliases ({' '.join(aliases)}) in"
                f" favour of reverse-DNS addresses"
                f" ({' '.join(servers_from_addresses)})")
            return

        for alias in aliases:
            server = cls(
                f"https://{alias}:{seed_port}",
                origin =  f"{origin} -> DNS aliases for '{hostname}'",
                aka = aka,
                ssl_verify = ssl_verify, ca_path = ca_path,
                herd = herd, herds = herds)
            servers[f"https://{alias}:{seed_port}"] = server
            log_sd.info(f"seeded alias {server.url} [{server.origin}]")


    def _cache_set_unlocked(self, field, value):
        self.fsdb.set(self.aka + "." + field, value)

    def _cache_set(self, field, value):
        with filelock.FileLock(self.cache_lockfile):
            self.fsdb.set(self.aka + "." + field, value)

    def _cache_get_unlocked(self, field, default = None):
        return self.fsdb.get(self.aka + "." + field, default)

    def _cache_get(self, field, default = None):
        with filelock.FileLock(self.cache_lockfile):
            return self.fsdb.get(self.aka + "." + field, default)

    def _cache_wipe(self):
        # a wee bit obscure; writing None wipes the field and all
        # the subfields (NAME. and NAME.*)
        return self.fsdb.set(self.aka, None)

    def _cache_setup(self):
        # don't call from initialization, only once we start using it
        # in earnest
        self.cache_lockfile = os.path.join(
            self.cache_dir, self.aka + ".lockfile")
        self.fsdb = commonl.fsdb_c.create(self.cache_dir)
        self.cache_lockfile = os.path.join(self.cache_dir, self.aka + ".lockfile")
        with filelock.FileLock(self.cache_lockfile):
            self._cache_set_unlocked("url", self.url)
            self._cache_set_unlocked("ssl_verify", self.ssl_verify)
            self._cache_set_unlocked("origin", self.origin)
            self._cache_set_unlocked("ca_path", self.ca_path)
            val = self._cache_get_unlocked("last_success", None)
            if val == None:
                # first time set up, so we count it as success so we
                # have a base
                self._cache_set_unlocked(	# same as _record success
                    "last_success",
                    datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))


    def _record_success(self):
        self._cache_set(
            "last_success",
            datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))

    def _record_failure(self):
        with filelock.FileLock(self.cache_lockfile):
            current_count = int(self._cache_get_unlocked("failure_count", 0))
            current_count += 1
            self._cache_set_unlocked("failure_count", str(current_count))
            utcnow = int(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))
            self._cache_set_unlocked("last_failure", utcnow)

    def _destroy_if_too_bad(self):
        utcnow = int(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))
        elapsed_success_max = 7 * 24 * 60 * 60 # a week in seconds
        try:
            # last success is an integer YYYYMMDDHHMMSS
            last_success = int(self._cache_get("last_success", 0))
        except ( ValueError, TypeError ):
	    # we might get corrupted, bad stuff, older versions, ignore'em
            self._cache_set("last_success", None)
            last_success = 0
        elapsed_success = utcnow - last_success
        if elapsed_success > elapsed_success_max:
            # last success was too long, just wipe it
            days = elapsed_success / 60 / 60 / 24
            days_max = elapsed_success_max / 60 / 60 / 24
            log_sd.info(
                f"{self.aka}: destroying:"
                f" last success was {days:.0} days ago (more than {days_max:.1})")
            self._cache_wipe()

    def _herds_get(self, count, loops_max):
        """
        Query for a given server the /ttb URL, which provides
        information about the server and the herds of other servers it
        knows about.

        :returns: tuple of:

         - server_c object where the discovery was done
         - dictionary of new servers found (server_c) keyed by URL,
           *None* in case of error
         - *None* on sucess, else string with error description
        """

        log_sd.info(f"#{count}/{loops_max}: scanning {self.url}:"
                    f" {self.origin}")
        # this is always available with no login
        try:
            # FIXME: ttb_client.send_request, so it retries
            r = requests.get(self.url + "/ttb",
                             verify = self.ssl_verify,
                             # want fast response, go quick or go
                             # away--otherwise when discovering many we
                             # could be here many times
                             timeout = 2)
        except requests.RequestException as e:
            return self, None, \
                f"{self.url}/ttb: got HTTP exception {e}"

        # this we set it as an UTC YYYYmmddHHMMSS -- we'll check it
        # later when doing discovery to avoid doing them too often
        self._cache_set(
            "last_discovery",
            datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))

        if r.status_code != 200:
            if r.status_code != 404:
                return self, None, \
                    f"{self.url}/ttb: got HTTP code {r.status_code}"
            # 404 - maybe an old server, since it lacks the /ttb endpoint,
            # so we'll still consider it
            log_sd.info(
                f"#{count}/{loops_max}: considering {self.url}/ttb:"
                f" maybe an older server")
        try:
            j = r.json()
        except json.decoder.JSONDecodeError as e:
            return self, None, \
                f"{self.url}/ttb: bad JSON {e}"
        if not isinstance(j, dict):
            return self.url, None, \
                f"{self.url}/ttb: expected a dictionary, got {type(j)}"
        # note it is legal for a server to report no herds if it
        # working alone.
        herds = r.json().get('herds', {})
        if not isinstance(herds, dict):
            return self, None, \
                f"{self.url}/ttb: expected ['herds'] to be a dictionary," \
                f" got {type(herds)}"

        # This parses the herds data we got from the server, which
        # looks like:
        #
        # "herds": {
        #   "HERD1": {       << OUTER LOOP
        #     "2ddd": {    << INNER LOOP
        #       "instance": "production",
        #       "url": "https://HOSTNAME1.DOMAIN1:5000"
        #     },
        #    "co4g": {
        #      "instance": "production",
        #       ...
        #   ...
        new_hosts = {}

        self._record_success()
        # If we get here, this means we got data from this host, so we'll
        # add it as a possible one -- note we don't know if it has any
        # herds, so we just add it
        for herd_name, herd_data in herds.items():
            if not isinstance(herd_data, dict):
                log_sd.info(
                    f"#{count}/{loops_max}: {self.url}/ttb:"
                    f" ['herds.{herd_name}']: expected a dictionary,"
                    f" got {type(herd_data)}; ignoring")
                continue
            # see INNER LOOP above
            for host_hash, host_data in herd_data.items():
                if not isinstance(host_data, dict):
                    log_sd.info(
                        f"#{count}/{loops_max}: ignoring {self.url}/ttb:"
                        f" ['herds.{herd_name}.{host_hash}]:"
                        f" expected a dictionary, got {type(host_data)}")
                    continue
                new_server_url = host_data.get('url', None)
                if not new_server_url:
                    log_sd.info(
                        f"#{count}/{loops_max}: {self.url}/ttb:"
                        f" ['herds.{herd_name}.{host_hash}]:"
                        f" no 'url' field; ignoring")
                    continue
                try:
                    # create a server_c object to return -- we create
                    # it here so if in the future we increase the
                    # amount of data returned, we don't have to pass
                    # it back and forth, since the server_c object
                    # will have it.
                    # Note we do not access the global lists here
                    server = new_hosts.get(new_server_url, None)
                    if server == None:			# new
                        server = type(self)(
                            new_server_url,
                            herd = herd_name,
                            origin = f"discovered from {self.url}/ttb")
                        new_hosts[server.url] = server
                    else:				# new herd
                        server.herds.add(herd_name)
                except Exception as e:
                    log_sd.info(f"#{count}/{loops_max}:"
                                f" {new_server_url} from {self.url}:"
                                f" ignoring due to bad URL: {e}")
                    continue

        return self, new_hosts, None

    @classmethod
    def _discover_once(cls, servers, bad_servers, count, loops_max):
        """
        Given a list of servers (good and bad), try to discover more
        servers from them

        Bad servers are retried since the could have had a
        glitch--this needs a better retry/circuit-breaker pattern.

        :param current_servers: dict keyed by URL of :class:`server_c`
          representing a known host we have to discover on

        :param bad_servers: dict keyed by URL of :class:`server_c`
          representing a known host we have to discover on, but that
          we know was bad for any reason before.
        """

        if not servers and not bad_servers:
            return {}, 0, 0

        bad_server_count = 0
        new_server_count = 0
        new_servers = {}

        # Parallelize discovery of each server FIXME: cap it?
        with concurrent.futures.ThreadPoolExecutor(
                len(servers) + len(bad_servers)) as executor:

            rs = executor.map(
                lambda i: i._herds_get(count, loops_max),
                itertools.chain(
                    servers.values(),
                    bad_servers.values()
                )
            )
            # now gather each the resposne from each server we queried
            # and join them into the current list FIXME: pass a lock
            # to _herds_get() and have it done straight to save an
            # iteration? when we have multiple servers, it'll add to
            # significant wasted computation
            for server, new_hosts_on_this_server, reason in rs:
                if new_hosts_on_this_server == None:
                    # this means there was an error querying this
                    # server and is bad (as in we can't contact it or
                    # it returns junk meaning TTBD not spoken there)
                    bad_servers[server.url] = server
                    server.reason = reason
                    server.setup()
                    server._record_failure()
                    bad_server_count += 1
                    log_sd.info(f"#{count}/{loops_max}: skipping"
                                f" {server.url}: bad server [{reason}]")
                    continue
                for new_url, new_server in new_hosts_on_this_server.items():
                    # do this here, single threaded
                    if new_url in cls.servers:
                        log_sd.info(f"#{count}/{loops_max}:"
                                    f" skipping {new_url}: already known")
                        continue

                    new_server_count += 1
                    log_sd.info(f"#{count}/{loops_max}: adding {new_url}:"
                                f" discovered from {server.url}")
                    cls.servers[new_url] = new_server
                    new_server.setup()
                    new_servers[new_url] = new_server

        return new_servers, new_server_count, bad_server_count

    @classmethod
    def flush(cls):
        cls.servers = {}
        log_sd.info(f"wiping cache directory {cls.cache_dir}")
        shutil.rmtree(cls.cache_dir, ignore_errors = True)


    _seed_default = {}

    @classmethod
    def seed_add(cls, url, aka = None, port = 5000,
                 ssl_verify = False, ca_path = None,
                 herd = None, herds = None, origin = None):
        """
        Add hosts and server info to the default list of seeds

        All arguments are directly fed to the :class:`server_c`
        constructor, if missing they are guessed.
        """
        # same arguments as _servers_add_hostname_url
        cls._seed_default[url] = dict(
            # lame, but clear
            aka = aka, port = port,
            ssl_verify = ssl_verify, ca_path = ca_path,
            herd = herd, herds = herds,
            origin = origin if origin else commonl.origin_get(1)
        )

    #: Maximum time we consider a discovered server's data fresh
    #:
    #: After this time, we'll rescan it
    max_cache_age = 10 * 60

    @classmethod
    def discover(cls, ssl_ignore = True,
                 # named as a host, so we do A/AAAA discovery
                 seed_url = None,
                 seed_port = 5000,
                 herds_exclude = None, herds_include = None,
                 zero_strikes_max = 2,
                 max_cache_age = None,
                 loops_max = 4,
                 origin = "source code defaults",
                 ignore_cache = False):
        """
        Discover servers

        Given a list of seed servers, use them to discover more servers
        on the network.

        The seed server list comes from:

        - resolving a hardcoded list of hostnames/URLs (that defaults
          to *ttbd*) and others added with
          :func:`tcfl.server_c.seed_add()` in configuration files

          >>> tcfl.server_c.seed_add("https://myserver.domain:1234")
          >>> tcfl.server_c.seed_add("plainhostname")

        - any server already initialized

        - hosts for which we have cached information

        This tries a few times (controlled by *loops_max*) to query
        each known server for more servers and gives up if it can't
        get more server twice. If a run provides more servers, on the
        next run those new servers will be query for others not yet
        known.

        Any bad server is removed from the list so we don't waste time
        on it.

        This is normally called by the *TCFL* library initialization
        sequence and the user does not need to worry about it.

        :param str seed_url: (optional; default *ttbd*) URL
          (or list of URLs) for a server (which to use for finding more
          servers).

          A good practice is to create a CNAME or a RECORD FOR
          *ttbd.DEFAULTDOMAIN* that points to one or more servers in your
          organization, so clients don't have to do any further server
          configuration.


        """

        # FIXME: get default from tcfl.config -- this is always USER specific
        cls.cache_dir = os.path.expanduser(
            os.path.join("~", ".cache", "tcf", "servers"))
        commonl.makedirs_p(cls.cache_dir, reason = "server cache")

        bad_servers = collections.defaultdict(int)

        log_sd.warning("finding servers")
        count_start = len(cls.servers)
        # Prep seed of servers from function arguments and anything the
        # config files have already asked us to load or anything gthat
        # already exists
        if seed_url == None:
            seed_url = cls._seed_default
            origin = "default seed list in tcfl.server_c.seed_default"

        if origin == None:
            origin = "defaults " + commonl.origin_get(1)

        if isinstance(seed_url, str):
            cls._servers_add_hostname_url(cls.servers, seed_url,
                                          origin, seed_port)
        elif isinstance(seed_url, list):	# if we are given seed URLs, add them
            commonl.assert_list_of_strings(
                seed_url, "list of URL/hostnames", "URL/hostname")
            for url in seed_url:
                cls._servers_add_hostname_url(cls.servers, url,
                                              origin, seed_port)
        elif isinstance(seed_url, dict):	# if we are given seed URLs, add them
            commonl.assert_dict_key_strings(
                seed_url, "URL/hostnames and parameters")

            for url, parameters in seed_url.items():
                cls._servers_add_hostname_url(
                    cls.servers, url, parameters['origin'], parameters['port'],
                    parameters['aka'],
                    parameters['ssl_verify'], parameters['ca_path'],
                    parameters['herd'], parameters['herds'])
        else:
            raise ValueError(f"seed_url: expected string or list of strings;"
                             f" got {type(seed_url)}")
        count_seed = len(cls.servers)
        log_sd.warning(
            f"added {count_seed - count_start} new servers from"
            " (configuration/cmdline) seeding")

        # from tcfl.config.url_add()	# COMPAT
        import tcfl.config		# FIXME: this is bad, will be removed
        for url, _ssl_ignore, aka, ca_path in tcfl.config.urls:
            origin = tcfl.config.urls_data[url].get(
                'origin', 'probably tcfl.config.url_add() in a config file')
            server = cls(url, aka = aka, ssl_verify = not _ssl_ignore,
                         origin = origin, ca_path = ca_path)
            if server.aka == None:
                server.aka_make()
            if server.url in cls.servers:
                if origin == cls.servers[server.url].origin:
                    # already there, log anyway so we know is there
                    log_sd.info(f"seeded {server.url} [{server.origin}]")
                    continue
                log_sd.warning(f"{origin}: overriding server AKA {server.aka}"
                               f" from {cls.servers[server.url].origin}")
            log_sd.info(f"seeded {server.url} [{server.origin}]")
            cls.servers[server.url] = server
        count_config = len(cls.servers)
        log_sd.warning(
            f"added {count_config - count_seed} new servers from"
            " configuration files")


        # take known servers from the cache
        fsdb = commonl.fsdb_c.create(cls.cache_dir)
        for key in fsdb.keys("*.url") if ignore_cache == False else []:
            # key is AKA.url
            aka = key.rsplit(".", 1)[0]
            url = fsdb.get(key)

            try:
                # get fields something wrong? wipe the whole entry
                if not isinstance(url, str) or not url:
                    log_sd.debug(
                        f"{key}: wiping invalid cache entry (bad url)")
                    fsdb.set(aka, None)
                    continue

                ssl_verify = fsdb.get(aka + ".ssl_verify", False)
                if not isinstance(ssl_verify, bool):
                    log_sd.debug(
                        f"{key}: wiping invalid cache entry (bad ssl_verify)")
                    fsdb.set(aka, None)
                    continue

                origin = fsdb.get(aka + ".origin", f"cached @{cls.cache_dir}")
                if not isinstance(origin, str):
                    log_sd.debug(
                        f"{key}: wiping invalid cache entry (bad origin)")
                    fsdb.set(aka, None)
                    continue

                ca_path = fsdb.get(aka + ".ca_path", None)
                if ca_path and not type(ca_path, str):
                    log_sd.debug(
                        f"{key}: wiping invalid cache entry (bad ca_path)")
                    fsdb.set(aka, None)
                    continue

                if 'cached @' not in origin:
                    # we want to keep the true origin message, but also
                    # append that then it was cached, so kinda like add that
                    origin = f"cached @{cls.cache_dir}, " + origin

                if url in cls.servers:
                    log_sd.debug(
                        f"ignoring already loaded cached server AKA {aka}"
                        f" [{cls.servers[url].origin}]")
                    continue
                cls.servers[url] = cls(url, ssl_verify = ssl_verify,
                                       origin = origin, ca_path = ca_path)
            except ValueError as e:
                log_sd.debug(f"{key}: wiping invalid cache entry ({e})")
                fsdb.set(aka, None)

        if ignore_cache == False:
            count_cache = len(cls.servers)
            log_sd.warning(
                f"added {count_cache - count_config} new servers from"
                f" the known server cache at {cls.cache_dir}")
        else:
            count_cache = count_seed

        if not cls.servers:
            # FIXME: unify this message with tcfl.config.load()
            config_path = [
                ".tcf", os.path.join(os.path.expanduser("~"), ".tcf"),
            ] + _install.sysconfig_paths
            log_sd.warning(
                "No seed servers available; please use --url or "
                "add to a file called conf_ANYTHING.py in any of %s with:\n"
                "\n"
                "  tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)\n"
                "\n" % ":".join(config_path))
            return

        # we'll need these properly setup in disk so we can record
        # statistics
        for aka, server in cls.servers.items():
            server.setup()

        zero_strikes = 0
        cls.servers = dict(cls.servers)	# yup, make a copy of the dict
        new_servers = dict()

        if max_cache_age == None:
            max_cache_age = tcfl.server_c.max_cache_age

        # So now for each of those servers we know of, let's
        # re-discover only those who have been not discovered for a
        # long time, since they don't change this often
        for server_name, server in cls.servers.items():
            try:
                last_discovery = int(server._cache_get("last_discovery"))
                # this we set it as an UTC YYYYmmddHHMMSS
                utcnow = int(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))
                ellapsed = utcnow - last_discovery
                if max_cache_age == 0:
                    log_sd.warning(
                        f"{server_name}: ignoring cache age; re-discovering")
                elif ellapsed < 0:
                    log_sd.warning(
                        f"{server_name}: last discovery happened in the"
                        f" future ({ellapsed}); clock skew?: re-discovering")
                elif ellapsed < max_cache_age:
                    log_sd.info(
                        f"{server_name}: last discovery happened"
                        f" {ellapsed} seconds ago, under {max_cache_age};"
                        f" not forcing re-discovery")
                    continue
                else:
                    log_sd.warning(
                        f"{server_name}: last discovery happened"
                        f" {ellapsed} seconds ago, over {max_cache_age};"
                        f" re-discovering")
            except Exception as e:
                log_sd.info(f"{server_name}: can't get last discovery"
                            f" date or invalid; forcing re-discovery: {e}")
            new_servers[server_name] = server

        if not new_servers:
            log_sd.warning(
                f"not discovering, all {len(cls.servers)} servers' "
                f"info is warm")
            return

        for count in range(1, loops_max + 1):
            # start searching the seed servers, but then only search
            # the new servers found in the previous run
            new_servers, new_server_count, bad_server_count = \
                cls._discover_once(new_servers, bad_servers, count, loops_max)

            if new_server_count == 0:
                zero_strikes += 1
                if zero_strikes >= zero_strikes_max:
                    log_sd.warning(
                        f"#{count}/{loops_max}: done (got no new servers"
                        f" {zero_strikes} times in a row even after retrying"
                        " those that failed before)")
                    break
                log_sd.warning(
                    f"#{count}/{loops_max}: no new servers"
                    f" (retrying {bad_server_count} of those that failed)")
                continue

            # _discover() adds directlry to cls.servers
            log_sd.warning(
                f"#{count}/{loops_max}: found {new_server_count} new server/s")
        else:
            log_sd.info(f"done after #{count} iterations")

        # prune bad servers that might have sneaked in
        for bad_url, bad_server in bad_servers.items():
            bad_server._destroy_if_too_bad()
            if bad_url not in cls.servers:
                continue
            # these 'command line' or 'configured' settings are
            # done in set in the main tcf script or in
            # tcfl.config.url_add() and are a bit of a wild guess.
            # Allows us to be more explicit for what the
            # user has explicitly configured
            if bad_server.origin == "command line" \
               or 'configured' in bad_server.origin:
                log_sd.error(f"{bad_url}: skipping, listed as"
                             f" bad [{bad_server.origin}]")
            else:
                log_sd.info(f"{bad_url}: skipping, listed as"
                            f" bad [{bad_server.origin}]")
            del cls.servers[bad_url]


    def _targets_get(self, target_id = None, projections = None):
        commonl.assert_none_or_list_of_strings(projections, "projections",
                                               "field name")
        log_server.error(f"DEBUG {self.url}: projecting {projections}")

        # load the raw description from the server and then do some
        # minimal manipulation for the cache:
        #
        # - add fullid, server, server_aka
        # - add TARGETNAME=True
        # - return both nested and flat dictionary
        #
        # if a given target is given, load only that one
        try:
            server_rts = dict()
            server_rts_flat = dict()

            def _rt_handle(target_id, rt):
                rt[target_id] = True
                fullid = self.aka + "/" + target_id
                rt[fullid] = True
                rt['fullid'] = fullid
                # these are needed to later one be able to go from an
                # rt straight to the server
                rt['server'] = self.url
                rt['server_aka'] = self.aka
                # DO NOT publish rt['rtb'], it is an internal object
                server_rts[fullid] = rt
                server_rts_flat[fullid] = dict(rt)
                # Note the empty_dict!! it's important; we want to
                # keep empty nested dictionaries, because even if
                # empty, the presence of the key might be used by
                # clients to tell things about the remote target
                server_rts_flat[fullid].update(
                    commonl.dict_to_flat(rt, empty_dict = True))

            if projections:
                data = { 'projections': json.dumps(projections) }
            else:
                data = None
            # we do a short timeout here, so dead servers don't hold
            # us too long
            if target_id:
                r = self.send_request("GET", "targets/" + target_id,
                                      data = data, raw = True, timeout = 10)
                # Keep the order -- even if json spec doesn't contemplate it, we
                # use it so the client can tell (if they want) the order in which
                # for example, power rail components are defined in interfaces.power
                rt = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
                _rt_handle(target_id, rt)
            else:
                r = self.send_request("GET", "targets/",
                                      data = data, raw = True, timeout = 10)
                # Keep the order -- even if json spec doesn't contemplate it, we
                # use it so the client can tell (if they want) the order in which
                # for example, power rail components are defined in interfaces.power
                r = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
                for target_id, rt in r.items():
                    _rt_handle(target_id, rt)
            return server_rts, server_rts_flat
        except requests.exceptions.RequestException as e:
            log_server.error("%s: can't use: %s", self.url, e)
            return {}, {}


    # this accesses the global tcfl.rts* variables without locks, to
    # be executed sequential only
    @staticmethod
    def _cache_rt_handle(fullid, rt):
        pos = bisect.bisect_left(rts_fullid_sorted, fullid)
        if not rts_fullid_sorted or rts_fullid_sorted[-1] != fullid:
            rts_fullid_sorted.insert(pos, fullid)
        if rt.get('disabled', None):
            rts_fullid_disabled.add(fullid)
            rts_fullid_enabled.discard(fullid)
        else:
            rts_fullid_disabled.discard(fullid)
            rts_fullid_enabled.add(fullid)


    def target_update(self, target_id):
        """
        Update information about a target

        Pulls a fresh inventory off the server for the given target,
        updates the cached copy and returns the updated data

        :param str target_id: ID of the target to operate on

        :returns: updated target tags
        """
        server_rts, server_rts_flat = self._targets_get(target_id)
        if not server_rts:
            raise ValueError(f"{self.aka}/{target_id}: unknown target")
        global rts
        global rts_flat
        # we might get back more targets, so ignore all of those that
        # are not the one we asked for
        rt = None
        rt_flat = None
        for fullid, rt in server_rts.items():
            if rt['id'] != target_id:
                logging.warning("%s: asked for RT %s, also got info for %s",
                                self.url, target_id, rt['id'])
                continue
            # this might be a new target, so handle it in the cache
            self._cache_rt_handle(fullid, rt)
            rts[fullid] = rt
        # rts_flat are the same info as rt, but in flat form
        for fullid, rt_flat in server_rts_flat.items():
            rts_flat[fullid] = rt_flat
        return rt, rt_flat


    @classmethod
    def targets_load(cls, projections = None):
        """
        Reload the remote target cache for all the servers

        :param list(str) projections: (optional; default all) list of
          fields to load

          Depending on the operation that is to be performed, not all
          fields might be needed and depending on network conditions
          and how many remote targets are available and how much data
          is in their inventory, this can considerably speed up
          operation.

          For example, to only list the target names:

          >>> tcfl.server_c.targets_reload(projections = [ 'id' ])

          Only targets that have the field defined will be fetched
          (PENDING: prefix field name with a period `.` will gather
          all targets irrespective of that field being defined or
          not).

        """
        log_server.info("caching target information")
        global rts
        global rts_flat
        global rts_fullid_sorted
        rts.clear()
        rts_flat.clear()
        rts_fullid_sorted.clear()
        # load all the servers at the same time using a thread pool
        if not cls.servers:
            return
        log_server.info("reading all targets")
        with concurrent.futures.ThreadPoolExecutor(len(cls.servers)) as e:
            rs = e.map(lambda server: server._targets_get(projections = projections),
                       cls.servers.values())
        for server_rts, server_rts_flat in rs:
            # do this here to avoid multithreading issues; only one
            # thread updating the sorted list
            for fullid, rt in server_rts.items():
                cls._cache_rt_handle(fullid, rt)
            rts.update(server_rts)
            rts_flat.update(server_rts_flat)
        log_server.info("read all targets")


#: Character used to separate RUNID/HASHID in reports
#:
#: This is the consequence of a very bad past design decisison which
#: called for a filename *report-RUNID:HASHID.txt* and of course,
#: colons are bad because they are used to mean a lot of things.
#:
#: Trying to move to hashes, but there is a lot of legacy, so these
#: variables allow to quickly to new behaviour via configuration.
#:
#: Defaults to existing *:*
report_runid_hashid_separator = ":"

#: Character used to separate RUNID/HASHID in filenames
#:
#: Defaults to existing *:* (see comments for
#: data:`report_runid_hashid_separator`)
report_runid_hashid_file_separator = ":"


class report_driver_c:
    """Reporting driver interface

    To create a reporting driver, subclass this class, implement
    :meth:`report` and then create an instance, adding it calling
    :meth:`add`.

    A testcase reports information by calling the `report_*()` APIs in
    :class:`reporter_c`, which multiplexes into each reporting driver
    registered with :meth:`add`, calling each drivers :meth:`report`
    function which will direct it to the appropiate place.

    Drivers can be created to dump the information in any format and
    to whichever location, as needed.

    For examples, look at:

    - :mod:`tcfl.report_console`
    - :mod:`tcfl.report_jinja2`
    - :mod:`tcfl.report_taps`
    - :mod:`tcfl.report_mongodb`

    """

    #: Name for the driver
    #
    #: This is optional and can be set with the
    #: :meth:`report_driver_c.add() <add>` call.
    name = None

    def report(self, testcase, target, tag, ts, delta,
               level, message, alevel, attachments):
        """Low level report from testcases

        The reporting API calls this function for the final recording
        of a reported message. In here basically anything can be
        done--but they being called frequently, it has to be efficient
        or will slow testcase execution considerably. Actions done in
        this function can be:

        - filtering (to only run for certain testcases, log levels, tags or
          messages)
        - dump data to a database
        - record to separate files based on whichever logic
        - etc

        When a testcase is completed, it will issue a message
        *COMPLETION <result>*, which marks the end of the testcase.

        When all the testcases are run, the global testcase reporter
        (:data:`tcfl.tc.tc_global`) will issue a *COMPLETION <result>*
        message. The global testcase reporter can be identified because
        it has an attribute *skip_reports* set to *True* and thus can
        be identified with:

        .. code-block:: python

           if getattr(_tc, "skip_reports", False) == True:
               do_somethin_for_the_global_reporter

        Important points:

        - **do not rely on globals**; this call is not lock protected
          for concurrency; will be called for *every* single report the
          internals of the test runner and the testcases do from
          multiple threads at the same time. Expect a *lot* of calls.

          Must be ready to accept multiple threads calling from
          different contexts. It is a good idea to use thread local
          storage (TLS) to store state if needed. See an example in
          :class:`tcfl.report_console.driver`).

        :param tcfl.tc_c testcase: testcase tho is reporting
          this. Note this might be a top level or a subcase.

        :param tcfl.target_c target: target who is reporting this;
          might be *None* if the report is not associated to a target.

        :param str tag: type of report (PASS, ERRR, FAIL, BLCK, INFO,
          DATA); note they are all same length and described in
          :data:`valid_results`.

        :param float ts: timestamp for when the message got generated
          (in seconds)

        :param float delta: time lapse from when the testcase started
          execution until this message was generated.

        :param int level: report level for the *message* (versus for
          the attachments); note report levels greater or equal to
          1000 are used to pass control messages, so they might not be
          subject to normal verbosity control (for example, for a log
          file you might want to always include them).

        :param str message: single line string describing the message
          to report.

          If the message starts with  *"COMPLETION "*, this is the
          final message issued to mark the result of executing a
          single testcase. At this point, you can use fields such
          as :data:`tc_c.result` and :data:`tc_c.result_eval` and it
          can be used as a synchronization point to for example, flush
          a file to disk or upload a complete record to a database.

          Python2: note this has been converted to unicode UTF-8

        :param int alevel: report level for the attachments

        :param dict attachments: extra information to add to the
          message being reported; shall be reported as *KEY: VALUE*;
          VALUE shall be recursively reported:

          - lists/tuples/sets shall be reported indicating the index
            of the member (such as *KEYNAME[3]: VALUE*

          - dictionaries shall be recursively reported

          - strings and integers shall be reported as themselves

          - any other data type can be reported as what it's *repr*
            function returns when converting it to unicode ro whatever
            representation the driver can do.

          You can use functions such :func:`commonl.data_dump_recursive`
          to convert a dictionary to a unicode representation.

          This might contain strings that are not valid UTF-8, so you
          need to convert them using :func:`commonl.mkutf8` or
          similar. :func:`commonl.data_dump_recursive` do that for you.

        """
        raise NotImplementedError

    _drivers = []

    @classmethod
    def add(cls, obj, name = None, origin = None):
        """
        Add a driver to handle other report mechanisms

        A report driver is used by *tcf run*, the meta test runner, to
        report information about the execution of testcases.

        A driver implements the reporting in whichever way it decides
        it needs to suit the application, uploading information to a
        server, writing it to files, printing it to screen, etc.

        >>> class my_report_driver(tcfl.report_driver_c)
        >>>     ...
        >>> tcfl.report_driver_c.add(my_report_driver())

        :param tcfl.report_driver_c obj: object subclasss of
          :class:`tcfl.report_driver_c` that implements the
          reporting.

        :param str name: (optional) driver name; useful so
          :data:`reporter_c.level_driver_max` can be used.

          The name *console* refers to a driver used to print stuff to
          the console/command line from which *tcf run* (for example)
          is exectuted.

          If from a configuration file a report driver is added as
          *console*, then core will not add the default one
          (:class:`tcfl.report_console.driver`).

        :param str origin: (optional) where is this being registered;
          defaults to the caller of this function.
        """
        assert isinstance(obj, cls)
        if origin == None:
            origin = commonl.origin_get(2)
        argspec = inspect.getfullargspec(cls.report)
        if len(argspec.args) != 10:
            # old style, bail out
            raise RuntimeError(
                f"WARNING! Driver {cls} (@{origin}) is old style,"
                f" please update to new report_driver_c.report() [{len(argspec.args)}]")

        setattr(obj, "origin", origin)
        obj.name = name
        cls._drivers.append(obj)

    @classmethod
    def get_by_name(cls, name: str):
        """
        Return a reporting driver given its name

        :param str: name the driver was registered with
        :returns tcfl.report_driver_c: driver instance
        :raises ValueError: if not found
        """
        for driver in cls._drivers:
            if driver.name == name:
                return driver
        raise ValueError("%s: report driver does not exist" % name)

    @classmethod
    def remove(cls, obj):
        """
        Remove a report driver previously added with :meth:`add`

        :param tcfl.report_driver_c obj: object subclasss of
          :class:`tcfl.report_driver_c` that implements the
          reporting.

        """
        assert isinstance(obj, cls)
        cls._drivers.remove(obj)


class reporter_c(object):
    """
    High level reporting API

    Embedded as part of a target or testcase, allows them to report in
    a unified way

    This class accesses members that are undefined in here but defined
    by the class that inherits it (tc_c and target_c):

    - self.kws

    """
    def __init__(self, testcase = None):
        # this is to be set by whoever inherits this
        self._report_prefix = "reporter_c._report_prefix/uninitialized"
        #: time when this testcase or target was created (and thus all
        #: references to it's inception are done); note if this is for
        #: a testcase, in __init_shallow__() we update this for when
        #: we assign it to a target group to run.
        if testcase:
            self.ts_start = testcase.ts_start
            # COMPAT
            assert isinstance(testcase, tc_c) \
                or type(testcase).__name__ == "tc_c", \
                f"testcase: expected tcfl.tc_c; got {type(testcase)}"
            self.testcase = testcase	# record who our testcase is
        else:
            self.ts_start = time.time()
            assert isinstance(self, tc_c)
            self.testcase = self

        self._ticket = None
        # this will actually come from the testcase/target definition
        # and be initialized in the testcase/target constructions
        self.kws = {}


    #: Ignore messages with verbosity about this level
    #:
    #: >>> self.level_max = 4
    report_level_max = None

    #: Ignore messages with verbosity about this level (per driver)
    #:
    #: >>> class _test(tcf.tc.tc_c):
    #: >>>     ...
    #: >>>     report_level_driver_max = {
    #: >>>         "DRIVERNAME": 4,
    #: >>>         "DRIVERNAME2": 7
    #: >>>     }
    #:
    report_level_driver_max = {}

    @staticmethod
    def _argcheck(message, attachments, level, dlevel, alevel):
        assert isinstance(message, str), \
            f"message: expected str, got {type(message)}"
        if attachments:
            assert isinstance(attachments, dict)
            # FIXME: valid values?
        assert level >= 0
        # just check is some kind of integer (positive, negative or zero)
        assert dlevel >= 0 or dlevel < 0
        assert alevel >= 0 or alevel < 0

    def _report(self, level, alevel, tag, message,
                attachments, subcase = None, subcase_base = None):
        assert subcase == None or isinstance(subcase, str), \
            f"subcase: expected short string; got {type(subcase)}"
        if self.report_level_max != None and level >= self.report_level_max:
            return
        ts = time.time()
        delta = ts - self.ts_start

        testcase = self.testcase
        subl = []
        # If there is no subcase_base, then we take it from the TLS
        # stack; this is normally used when we raise an exception that
        # has to be reported in a different subcase path, not in the
        # current one in the stack. That is done by tcfl.msgid_c.__exit__
        if subcase_base == None:
            subcase_base = msgid_c.subcase()
        if subcase_base:
            subl.append(subcase_base)
        if subcase:
            subl.append(subcase)
        subcase = "##".join(subl)

        if subcase:
            subtc = testcase._subcase_get(subcase)
            if tag == "PASS":
                subtc.result.passed += 1
            elif tag == "FAIL":
                subtc.result.failed += 1
            elif tag == "ERRR":
                subtc.result.errors += 1
            elif tag == "BLCK":
                subtc.result.blocked += 1
            elif tag == "SKIP":
                subtc.result.skipped += 1
            report_on = subtc
        else:
            report_on = testcase

        for driver in report_driver_c._drivers:
            if driver.name:
                level_driver_max = self.report_level_driver_max.get(driver.name, None)
                if level_driver_max != None and level >= level_driver_max:
                    continue
            if isinstance(self, target_c):
                target = self
            else:
                target = None
            driver.report(
                report_on, target, tag, ts, delta, level,
                commonl.mkutf8(message), alevel, attachments)

    def report_pass(self, message, attachments = None,
                    level = None, dlevel = 0, alevel = 2, subcase = None):
        """Report a check has passed (a positive condition we were
        looking for was found).

        >>> report_pass("this thing worked ok",
        >>>             dict(
        >>>                 measurement1 = 34,
        >>>                 log = commonl.generator_factory_c(
        >>>                     commonl.file_iterator, "LOGILENAME")
        >>>             ),
        >>>             subcase = "subtest1")

        A check, described by *message* has passed

        :param str message: message describing the check or condition
          that has passed

        :param dict attachments: (optional) a dictionary of extra data
          to append to the report, keyed by string. Stick to simple
          values (bool, int, float, string, nested dict of the same )
          for all report drivers to be able to handle it.

          Additionally, use class:`commonl.generator_factory_c` for
          generators (since the report drivers will have to spin the
          generator once each).

        :param str subcase: (optional, default *None*) report this
          message as coming from a subcase

        :param int level: (optional, default set by
          :class:`tcfl.msgid_c` context depth) verbosity level of this
          message. Must be a zero or positive integer. 0 is most
          important. Usually you want to set *dlevel*.

        :param int dlevel: (optional, default 0) verbosity level of
          this message relative to level (normally to the default
          level).

          Eg: if given -2 and level resolves to 4, the verbosity level
          would be 2.

        :param int alevel: (optional, default 2) verbosity level of
          the attachments to this message relative to level (normally
          to the default level).

          The attachments might contain a lot of extra data that in
          some cases is not necessary unless more verbosity is
          declared.

        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "PASS", message,
                     attachments, subcase = subcase)

    def report_fail(self, message, attachments = None,
                    level = None, dlevel = 0, alevel = 2, subcase = None):
        """
        Report a check that has failed (an negative condition we were
        looking for was found).

        Same parameters as :meth:`report_pass`.
        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "FAIL", message,
                     attachments, subcase = subcase)

    def report_error(self, message, attachments = None,
                     level = None, dlevel = 0, alevel = 2, subcase = None):
        """
        Report a check that has errored (a negative condition we were
        not looking for was found).

        Same parameters as :meth:`report_pass`.
        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "ERRR", message,
                     attachments, subcase = subcase)

    def report_blck(self, message, attachments = None,
                    level = None, dlevel = 0, alevel = 2, subcase = None):
        """
        Report a check that has blocked (something has happened most
        likely in infrastructure that disallows us for checking
        conditions to determine pass/fail/error/skip).

        Same parameters as :meth:`report_pass`.
        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "BLCK", message,
                     attachments, subcase = subcase)

    def report_skip(self,  message, attachments = None,
                    level = None, dlevel = 0, alevel = 2, subcase = None):
        """
        Report a check that has skipped (the conditions needed to test
        are not met).

        Same parameters as :meth:`report_pass`.
        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "SKIP", message,
                     attachments, subcase = subcase)

    def report_info(self, message, attachments = None,
                    level = None, dlevel = 0, alevel = 2, subcase = None):
        """
        Report an informational progress message.

        Same parameters as :meth:`report_pass`.
        """
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(message, attachments, level, dlevel, alevel)
        level += dlevel
        self._report(level, level + alevel, "INFO", message,
                     attachments, subcase = subcase)

    def report_data(self, domain, name, value, expand = True,
                    level = 2, dlevel = 0, subcase = None):
        """Report measurable data

        When running a testcase, if data is collected that has to be
        reported for later analysis, use this function to report
        it. This will be reported by the report driver in a way that
        makes it easy to collect later on.

        Measured data is identified by a *domain* and a *name*, plus
        then the actual value.

        A way to picture how this data can look once aggregated is as
        a table per domain, on which each invocation is a row and each
        column will be the values for each name.

        :param str domain: to which domain this measurement applies
          (eg: "Latency Benchmark %(type)s");

          Well known domains:

           - *Warnings [%(type)s]*: values would be accumulated over
             how many times it has been reported

             >>> # self is a tcfl.tc.tc_c
             >>> condition = "SOMENAME"
             >>> with self.lock:
             >>>     self.buffers.setdefault(condition, 0)
             >>>     self.buffers[condition] += 1
             >>> self.report_data("Warnings [%(type)s]", condition,
             >>>     self.buffers[condition])

           - *Recovered conditions [%(type)s]*: values would be
             accumulated over how many times it has been reported

             Same reporting example as for *Warnings* above.

        :param str name: name of the value  (eg: "context switch
          (microseconds)"); it is recommended to always add the unit
          the measurement represents.

        :param value: value to report for the given domain and name;
           any type can be reported.

        :param bool expand: (optional) by default, the *domain* and
          *name* fields will be %(FIELD)s expanded with the keywords
          of the testcase or target. If *False*, it will not be
          expanded.

          This enables to, for example, specify a domain of "Latency
          measurements for target %(type)s" which will automatically
          create a different domain for each type of target.
        """
        assert isinstance(domain, str)
        assert isinstance(name, str)
        assert level >= 0
        assert dlevel >= 0
        assert isinstance(expand, bool)

        if expand:
            domain = domain % self.kws
            name = name % self.kws
        level += dlevel

        self._report(
            level, 1000, "DATA",
            domain + "::" + name + "::" + str(value), subcase = subcase,
            attachments = dict(domain = domain, name = name, value = value))

    def report_tweet(self, what, result, extra_report = "",
                     ignore_nothing = False, attachments = None,
                     level = None, dlevel = 0, alevel = 2,
                     dlevel_failed = 0, dlevel_blocked = 0,
                     dlevel_passed = 0, dlevel_skipped = 0, dlevel_error = 0,
                     subcase = None):
        if level == None:		# default args are computed upon def'on
            level = msgid_c.depth()
        self._argcheck(what, attachments, level, dlevel, alevel)
        assert dlevel_failed >= 0
        assert dlevel_blocked >= 0
        assert dlevel_passed >= 0
        assert dlevel_skipped >= 0
        assert dlevel_error >= 0
        level += dlevel
        r = False
        if result.failed > 0:
            tag = "FAIL"
            msg = valid_results[tag][1]
            level += dlevel_failed
        elif result.errors > 0:
            tag = "ERRR"
            msg = valid_results[tag][1]
            level += dlevel_error
        elif result.blocked > 0:
            tag = "BLCK"
            msg = valid_results[tag][1]
            level += dlevel_blocked
        elif result.passed > 0:
            tag = "PASS"
            msg = valid_results[tag][1]
            r = True
            level += dlevel_passed
        elif result.skipped > 0:
            tag = "SKIP"
            msg = valid_results[tag][1]
            r = True
            level += dlevel_skipped
        else:            # When here, nothing was run, all the counts are zero
            if ignore_nothing == True:
                return True
            self._report(level, level + alevel, "BLCK",
                         what + " / nothing ran " + extra_report,
                         attachments, subcase = subcase)
            return False
        self._report(level, level + alevel,
                     tag, what + " " + msg + " " + extra_report,
                     attachments, subcase = subcase)
        return r

    # Deprecated APIs
    @property
    def ticket(self):
        warnings.warn("reporter_c.ticket", DeprecationWarning)
        return self._ticket


    @ticket.setter
    def ticket(self, value):
        warnings.warn("reporter_c.ticket", DeprecationWarning)
        self._ticket = value
        return self._ticket


class target_c:

    #: Length of the hash used to identify groups or lists of targets
    #:
    #: Used to create a unique string that represents a dictionary of
    #: role/targetname assignments and others for caching.
    #:
    #: The underlying implementation takes a sha512 hash of a string
    #: that represents the data, base32 encodes it and takes the as
    #: many characters as this length for the ID (for humans base32 it
    #: is easier than base64 as it does not mix upperand lower
    #: case).
    #:
    #: If there are a lot of target roles and/or targets, it might be
    #: wise to increase it to avoid collisions...but how much is a lot
    #: is not clear. 10 gives us a key space of 32^10 (1024 Peta)
    hash_length = 10

    #: How many times to retry to generate a group before giving up
    #:
    #: If the generation ess yields an empty group more than this
    #: many times, stop trying and return.
    spin_max = 3000
    keys_from_inventory = collections.defaultdict(set)
    target_inventory = None

    def __init__(self, role, origin,
                 axes = None,
                 spec = None,
                 spec_args = None,
                 ic_spec = None,
                 ic_spec_args = None,
                 interconnect = False):
        """FIXME

        **Internal API for testcase/target pairing**

        :param bool interconnect: (optional; default *False*) this
          role will serve as an interconnect, binding other target
          roles together. Other target roles might request being
          connected to this one.

        """
        assert spec == None or isinstance(spec, str) or callable(spec)
        assert spec_args == None or isinstance(spec_args, dict)
        assert ic_spec == None or callable(ic_spec)
        assert ic_spec_args == None or isinstance(ic_spec_args, dict)
        assert isinstance(interconnect, bool), \
            f"interconnect: expected boolean, got {type(interconnect)}"

        self.role = role
        # FIXME: pre-compile if text
        self.spec = spec
        self.spec_args = spec_args
        self.ic_spec = ic_spec
        self.ic_spec_args = ic_spec_args
        # make a copy of the axes (because it'll be modified
        # later). Note that any axes with value None will be expanded
        # later by target_ext_run.executor_c from values in the
        # inventory, thus we'll be demanding it is present in the
        # inventory
        # See also the note in tc_c._axes_all.
        self.axes = collections.OrderedDict(axes)
        #FIXME: this is expanded by executor_c.axes_expand() once we
        #have read the inventory of targets
        self.axes_from_inventory = set()
        self.interconnect = interconnect
        self.origin = origin

        # these are not defined until _bind() is called
        self.rtb_aka = None	# filled by _bind
        self.rtb = None		# FIXME: this is resolved later
        self.fullid = None	# filled by _bind()
        self.id = None		# filled by _bind()
        self.rt = None		# filled by _bind()
        self.allocid = None	# filled by _bind()

    def __repr__(self):
        #return f"role:{self.role} spec:'{self.spec}' axes:{self.axes}"
        return self.role

    @staticmethod
    def get_rt_by_id(targetid):
        """
        Returns the (cached) dictionary of inventory data received from the
        server for a given target

        :param str target_id: name of the target; this can be
          shortname (*TARGETNAME*) or full id (*SERVER/FULLID*)

        :returns dict: inventory data for target

        :raises KeyError: if target name not found
        """
        global rts
        if '/' in targetid:		# targetid is a fullid (SERVER/TARGET)
            return rts[targetid]
        for rt_fullid, rt in rts.items():
            if rt['id'] == targetid:
                return rt
        raise KeyError(f"unknown target {targetid}")

    @classmethod
    def _inventory_update(cls):
        # Collects a list of all the keys available in the target's
        # inventory and all their values, which we'll use when we need
        # to use them as axes to spin their values.
        #
        #
        # FIXME: this needs to be a hook in target_update(),
        # targets_load() so it is always kept updated.
        cls.keys_from_inventory.clear()
        for fullid in rts_fullid_sorted:
            # FIXME: this belongs somehwere else? might not be needed
            # once we finalize axes_from_inventory
            for key, value in rts_flat[fullid].items():
                try:
                    # FIXME: filter out _alloc.id, _alloc.queue.*
                    #   bsps.x86_64.lcpu-N? .cpu-N?
                    #   instrumentation.*.*?
                    #   interconnects.XYZ. mhmmm
                    #   *.instrument
                    #   path
                    if isinstance(value, dict):
                        cls.keys_from_inventory[key].add(True)
                    elif isinstance(value, list):
                        cls.keys_from_inventory[key].update(value)
                    else:
                        cls.keys_from_inventory[key].add(value)
                except Exception as e:
                    print("ERRR key %s value %s %s" % (key, value, e))

        #log_role.debug(
        #    "keys from inventory: %s",
        #    json.dumps(list(cls.keys_from_inventory.keys()), skipkeys = True, indent = 4))

    def _bind(self, rtb_aka, target_id, target_fullid, allocid):
        self.rtb_aka = rtb_aka
        self.id = target_id
        self.fullid = target_fullid
        self.allocid = allocid


class tc_logadapter_c(logging.LoggerAdapter):
    """
    Logging adapter to prefix test case's current prefix and target name.
    """
    id = 0
    prefix = ""
    def process(self, msg, kwargs):
        return '[%08x] %s: %s ' % (self.id, self.prefix, msg), kwargs

    def isEnabledFor(self, level):
        return True

class tc_c(reporter_c):

    """FIXME:

    A more detailed description of how tescases are paired for
    execution with targets or group of targets is explained :ref:`here
    <testcase_pairing>`.


    FIXME: these parameters need to be moved to cls, along with axes
    and that they can be set with a decorator and a method, since we
    can't do constructor

    :param int target_group_permutations_max: an interger greater than
      zero that capping how many target group permutations to produce
      per axes permutation.

    :param bool target_group_randomize: (optional) override the
      randomization deduced from *target_group_permutations_max*.

    :param int replication_factor: (default: 1) how many different
      target group permutations to execute. For example, 3 would mean
      that the same testcase would be run three times, once in a
      different target group.

    """
    def __init__(
            self,
            name: str, tc_file_path: str, origin: str,
            # FIXME: this needs to be controlled from somewhere
            # else? not feasible here -- maybe max can be computed
            # dynamically, but not really a good idea....
            target_group_permutations_max = -100,
            replication_factor = 1,
    ):
        assert isinstance(target_group_permutations_max, int), \
            "target_group_permutations_max: expected integer (-N random N targets," \
            " 0: all targets randomly, N targets alphabetically)"
        assert replication_factor >= 1 and isinstance(replication_factor, int), \
            "replication_factor: expected > 0 integer"
        assert isinstance(origin, str)
        #
        # need this before calling reporter_c.__init__
        #
        #: Time when this testcase was created (and thus all
        #: references to it's inception are done); note in
        #: __init_shallow__() we update this for when we assign it to
        #: a target group to run.
        self.ts_start = time.time()
        self.ts_end = None

        reporter_c.__init__(self, testcase = self)

        self.name = name
        self.tc_file_path = tc_file_path
        self.origin = origin

        # most of these will be initialized later in
        # testcase.discovery_init() or others FIXME
        #: :term:`hashid` for this execution
        self.hashid = None

        #: Identification of the target group where this testcase is
        #: running (set when exeuting on a target group and bound to
        #: it)
        self.tgid = None

        #: FIXME: in the report, always use this to say who this is a
        #: child of
        #: Parent testcase (when this is a subcase of someone)
        self.parent = None

        #: Keywords for *%(KEY)[sd]* substitution specific to this
        #: testcase.
        #:
        #: Note these do not include values gathered from remote
        #: targets (as they would collide with each other). Look at
        #: data:`target.kws <tcfl.tc.target_c.kws>` for that.
        #:
        #: These can be used to generate strings based on information,
        #: as:
        #:
        #:   >>>  print "Something %(FIELD)s" % target.kws
        #:   >>>  target.shcmd_local("cp %(FIELD)s.config final.config")
        #:
        #: Fields available:
        #:
        #:   - `runid`: string specified by the user that applies to
        #:     all the testcases
        #:
        #:   - `srcdir` and `srcdir_abs`: directory where this
        #:     testcase was found
        #:
        #:   - `thisfile`: file where this testscase as found
        #:
        #:   - `tc_hash`: unique four letter ID assigned to this
        #:     testcase instance. Note that this is the same for all
        #:     the targets it runs on. A unique ID for each target of
        #:     the same testcase instance is the field *tg_hash* in the
        #:     target's keywords :data:`target.kws
        #:     <tcfl.tc.target_c.kws>` (FIXME: generate, currently
        #:     only done by app builders)
        #:
        #: (this will actually be fully initialzied in *__init_shallow__()*)
        self.kws = {}
        self.kws_origin = {}

        # This is initialized by tcfl.testcase.discovery_init()
        #: Report file prefix
        #:
        #: When needing to create report file collateral of any kind,
        #: prefix it with this so it always shows in the same location
        #: for all the collateral related to this testcase:
        #:
        #: >>>    target.shell.file_copy_from("remotefile",
        #: >>>                                self.report_file_prefix + "remotefile")
        #:
        #: will produce *LOGDIR/report-RUNID:HASHID.remotefile* if
        #: *--log-dir LOGDIR -i RUNID* was provided as command line.
        #:
        #: >>>    target.capture.get('screen',
        #: >>>                       self.report_file_prefix + "screenshot.png")
        #:
        #: will produce *LOGDIR/report-RUNID:HASHID.screenshot.png*
        #:
        self.report_file_prefix = "report_file_prefix-UNINITIALIZED"

        # if tags were set with the tcfl.tags() decorator at the class
        # level, make a copy so we can alter them dictionary of tags
        # this test case has been stamped with
        self._tags = dict(self._tags)
        self._tags_origin = dict(self._tags_origin)
        self.tag_set('name', self.name)

        # specialize the list of places where this testcase was
        # declared build only, so each instance can further refine its
        # own
        self.build_only = list(self.build_only)

        # Initialized by testcase.discovery_init()
        #: directory where collaterals are placed
        self.log_dir = os.getcwd()

        # Initialized by testcase.discovery_init()
        #: directory where temporary files can be placed
        self.tmpdir = None

        #: object for logging
        self.log = tc_logadapter_c(logger, None)

        # especialize this from the class version, so the instance can
        # control what it cleans up
        self.cleanup_files = set(self.cleanup_files)

        ##
        ## FIXME: let's wrap this on a run_data structure and move it
        ## away from the testcase to make it leaner
        ##

        # we need an OrderedDict so we have move_to_end(), which we
        # need in role_add(). Also, the order is
        # important--we'll use it throughout.

        # see _axes_all_update(); these are all the axes (from the
        # testcase and the testcase roles) and they are always sorted
        # the same so we can reproduce the pseudo-random sequences.
        # FIXME: move all .axes to ._axes
        self._axes_all = collections.OrderedDict()
        self._axes_all_mr = None
        # The initialization of the multiple-radix number representing
        # the axes is done by called by executor_c.axes_expand(), who
        # will call self._axes_all_update() once the axes expansion is
        # done.

        # These two are set by the pairing/execution engines

        #: FIXME: only assigned once an Axes Permutation has been
        #: assigned
        #: dict
        self.axes_permutation = None	# FIXME: dict
        #: FIXME: only assigned once an Axes Permutation ID has been assigned
        #: integer
        self.axes_permutation_id = None	# FIXME: integer

        # Data used by the allocation phase; see
        # __init__allocation__()
        #
        ## { GROUPNAME: { ( rtb.aka, allocid ) } }
        #
        # to make sure they # are fast and easy to pickle around
        # betwween threads.
        self._allocations_pending = None
        #
        # Allocations active: dict keyed by groupname, value is a set
        # of tuples RTB.AKA and allocid in that server
        #
        ## { GROUPNAME: { ( rtb.aka, allocid ) } }
        self._allocations_complete = None


    #
    # Variables for a class of testcases
    #
    # maybe especialized later by the instance

    # These are set with tag_set() and tags_set(), accessed with tag()
    _tags = dict()
    _tags_origin = dict()


    #: list of files to remove when the testcase is done
    cleanup_files = set()


    #
    # Variables for all testcases (read only for the testcase)
    #

    #: List of places where we declared this testcase is build only
    build_only = []

    #: Salt used to generate the testcase :term:`hash`
    hash_salt = ""

    #: Number of characters in the testcase's :term:`hash`
    #:
    #: The testcase's *HASHID* is a unique identifier to identify a
    #: testcase the group of test targets where it ran.
    #:
    #: This defines the lenght of such hash; before it used 4 to be
    #: four but once over 40k testcases are being run, conflicts start
    #: to pop up, where more than one testcase/target combo maps to
    #: the same hash.
    #:
    #:  32 ^ 4 = 1048576 unique combinations
    #:
    #:  32 ^ 6 = 1073741824 unique combinations
    #:
    #: 6 chars offers a keyspace 1024 times larger with base32 than
    #: 4 chars. Base64 increases the amount, but not that much
    #: compared to the ease of confusion between caps and non caps.
    #:
    #: So it has been raised to 6.
    #:
    #: FIXME: add a registry to warn of used ids
    hashid_len = 6

    # initialized by tcfl.testcase.discovery_setup()
    #: Identification of this execution
    runid = ""

    #: Temporary directory where testcases can drop things; this will
    #: be specific to each testcase instance (testcase and target
    #: group where it runs). It will be wiped upon test completion.
    #:
    #: For test collateral, use instead :data:`report_file_prefix`.
    #:
    #: It's initialized at by :func:tcfl.testcase.discovery_init();
    #: three uses:
    #:
    #: - For writing a temporary file that is common to all testcases:
    #:
    #:   >>> tcfl.tc_c.tmpdir
    #:
    #: - For writing a temporary file that is common to one testcases:
    #:
    #:   >>> self.tmpdir
    #:
    tmpdir = None

    #: Map exception types to results
    #:
    #: this allows to automaticall map an exception raised
    #: automatically and be converted to a type. Any testcase can
    #: define their own version of this to decide how to convert
    #: exceptions from the default of them being considered blockage
    #: to skip, fail or pass
    #:
    #: >>> class _test(tcfl.tc.tc_c):
    #: >>>     def configure_exceptions(self):
    #: >>>         self.exception_to_result[OSError] = tcfl.tc.error_e
    exception_to_result = {
        AssertionError: blocked_e,
    }

    def __init__allocation__(self):
        # Used by target_ext_run.executor_c._alloc_create()
        #
        # Initializes the allocation state; it is not needed in any
        # other phase, so we create it then and wipe it later to avoid
        # having to pickle it around.
        #
        # these are both keyed by target-group-name and contain a set
        # of the allocations *( RTB_AKA:str, ALLOCID:str )* that are
        # trying to get that target group allocated
        self._allocations_pending = collections.defaultdict(set)
        self._allocations_complete = collections.defaultdict(set)
        # keep track of how many copies of the testcase we have
        # scheduled on target groups (up until
        # testcase.target_group_permutations).
        self._target_groups_launched = 0

    def __init__shallow__(self, other):
        pass


    def _clone(self):
        c = copy.deepcopy(self)
        # since this might be defined at the class level, copy()
        # doesn't seem to always pick it up.
        c.target_roles = copy.deepcopy(self.target_roles)
        c.__init__shallow__(self)
        return c


    def kw_set(self, key, value, origin = None):
        """
        Set a string keyword for later substitution in commands

        :param str kw: keyword name
        :param str value: value for the keyword
        :param str origin: origin of this setting; if none, it will be
          taken from the stack
        """
        assert isinstance(key, str)
        assert isinstance(value, (str, int)), \
                "value: expected str|int, got %s: %s" % (type(value).__name__, value)
        if origin == None:
            origin = commonl.origin_get(1)
        else:
            assert isinstance(origin, str)
        self.kws[key] = value
        self.kws_origin.setdefault(key, []).append(origin)


    def _tags_update(self, tags = None):
        # Tag/s are to be updated, see if there are any special ones
        # we need to handle; expect the tag is set already, alng with origin
        if not tags:
            return
        for name, value in tags.items():
            origin = self._tags_origin.get(name, "n/a")
            if name == 'build_only' and value == True:
                self.build_only.append('tag:' + origin)


    def tag_set(self, tagname, value = None, origin = None):
        """
        Set a testcase tag.

        :param str tagname: name of the tag (string)
        :param value: (optional) value for the tag; can be a string,
          bool; if none specified, it is set to True
        :param str origin: (optional) origin of the tag; defaults to
          the calling function
        """

        assert isinstance(tagname, str), (
            "tagname has to be a string, not a %s" % type(tagname).__name__)
        if value == None:
            value = True
        else:
            assert isinstance(value, ( str, bool ))
        if origin == None:
            origin = "[builtin default] " + commonl.origin_get(1)
        else:
            assert isinstance(origin, str)
        self._tags[tagname] = value
        self._tags_origin[tagname] = origin
        self._tags_update({ tagname: value } )


    def tags_set(self, tags, origin = None, overwrite = True):
        """
        Set multiple testcase tags.

        :param dict tags: dictionary of tags and values
        :param str origin: (optional) origin of the tag; defaults to
          the calling function

        Same notes as for :meth:`tag_set` apply
        """
        if origin == None:
            origin = "[builtin default] " + commonl.origin_get(1)

        for name, value in tags.items():
            assert isinstance(name, str), \
                f"name has to be a string, not a {type(name)}"
            if value == None:
                value = True
            else:
                assert isinstance(value, (str, bool)), \
                    "tag value has to be None (taken as True), bool, " \
                    "string, not a %s" % type(value).__name__
            if name in self._tags and overwrite == False:
                continue
            self._tags[name] = value
            self._tags_origin[name] = origin
        self._tags_update(tags)


    def tag_get(self, tagname, value_default, origin_default = None):
        """
        Return a tags' value

        :returns tuple: Return a tuple *(value, origin)* with the
          value of the tag and where it was defined.
        """
        if origin_default == None:
            origin_default = "[builtin default] " + commonl.origin_get(1)
        return (
            self._tags.get(tagname, value_default),
            self._tags_origin.get(tagname, origin_default)
        )


    #
    # Internal APIs
    #
    # FIXME: rename to _

    # Linkage into the report API and support for it
    @staticmethod
    def ident():
        """
        Returns the current phase identifier for the testcase

        The phase identifier is accumulated per thread and the user
        can add more to it by running:

        >>> with tcfl.msgid_c("L1"):
        >>>    ...more code...

        Any calls inside the *with* block will be reported as:

          RUNID:HASHIDL1

        If a second with is done (eg: inside another function):

        >>> with tcfl.msgid_c("L1"):
        >>>    ...more code...
        >>>    with tcfl.msgid_c("L2"):
        >>>        ...more code...

        It would be reported as:

          RUNID:HASHIDL2L3

        :returns: a string with the current accumulated phase
          identifier.
        """
        return msgid_c.ident()


    # Deprecated APIs
    @property
    def ticket(self):
        warnings.warn("tcfl.tc_c.ticket", DeprecationWarning)
        return self.hashid

    @ticket.setter
    def ticket(self, value):
        warnings.warn("tcfl.tc_c.ticket", DeprecationWarning)
        self.hashid = value
        return self.hashid

    @property
    def id(self):
        # FIXME: also replace in tc.kws
        warnings.warn("tcfl.tc_c.id", DeprecationWarning)
        return self.name

    @property
    def runid_visible(self):
        # FIXME: also replace in tc.kws
        warnings.warn("tcfl.tc_c.runid_visible", DeprecationWarning)
        return self.name

    def _kw_set(self, *args, **kwargs):
        warnings.warn("tcfl.tc_c._kw_set", DeprecationWarning)
        return self.kw_set(*args, **kwargs)


    _axes = collections.OrderedDict()
    axes_origin = []

    #: Dictionary of target roles
    #:
    #: Keyed by a string, the role name
    #:
    #: The values are :class:`target_c`, which describe the
    #: target roles and during testcase execution, also provice
    #: access to the actual :class:`target_c` object to manipulate
    #: the target via :data:`target_c.target`.
    target_roles = collections.OrderedDict()
    # needs to be here so the decorator can set it

    #
    # See Execution Modes above
    #
    _axes_permutations = 0
    _axes_randomizer_original = "random"
    _axes_randomizer = random.Random()
    _target_group_permutations = 1
    _target_group_randomizer_original = "random"
    _target_group_randomizer = random.Random()
    # FIXME: add manipulators
    _target_groups_overallocation_factor = 10


    @property
    def axes_permutations(self):
        """
        How many axes permutations are to be considered

        See :ref:`execution modes <execution_modes>` for more information.

        :getter: return the number of axes permutations
        :setter: sets the number of axes permutations
        :type: int
        """
        return self._axes_permutations

    @axes_permutations.setter
    def axes_permutations(self, n):
        assert isinstance(n, int) and n >= 0, \
            f"axes_permutations: expected >= integer, got {type(n)}"
        self._axes_permutations = n
        return self._axes_permutations


    @property
    def axes_randomizer(self):
        """
        Randomizer object for the targes group permutation iterator

        See :ref:`execution modes <execution_modes>` for more information.

        :getter: return the current randomizer
          (:class:`random.Random` or *None* for sequential execution).

        :setter: sets the randomizer:

          - *None* or (str) *sequential* for sequential execution

          - *random* (str) constructs a default random device
            :class:`random.Random`.

          - *SEED* (str) any random string which will used as seed to
            construct a :class:`random.Random` object

          - a :class:`random.Random` instance

        :type: :class:`random.Random`
        """
        return self._axes_randomizer


    @staticmethod
    def _randomizer_make(r, what):
        if isinstance(r, str):
            if r == 'sequential':
                return None
            elif r == 'random':
                return random.Random()
            else:
                return random.Random(r)
        if isinstance(r, random.Random):
            return r
        raise AssertionError(
            f"{what}: expecting a string"
            f" ('sequential', 'random' or anything else to use"
            f" as a SEED) or a random.Random instance; got {type(r)}")


    @axes_randomizer.setter
    def axes_randomizer(self, r):
        self._axes_randomizer = self._randomizer_make(r, "axes_randomizer")
        self._axes_randomizer_original = r
        return self._axes_randomizer


    @property
    def target_group_permutations(self):
        """
        How many target group permutations on each axes permutations
        are to be considered

        See :ref:`execution modes <execution_modes>` for more information.

        :getter: return the number of target group permutations
        :setter: sets the number of target group permutations (n >= 0)
        :type: int
        """
        return self._target_group_permutations

    @target_group_permutations.setter
    def target_group_permutations(self, n):
        assert isinstance(n, int) and n >= 0, \
            f"target_group_permutations: expected >= integer, got {type(n)}"
        self._target_group_permutations = n
        return self._target_group_permutations


    @property
    def target_group_randomizer(self):
        """
        Randomizer object for the targes group permutation iterator

        See :ref:`execution modes <execution_modes>` for more information.

        :getter: return the current randomizer
          (:class:`random.Random` or *None* for sequential execution).

        :setter: sets the randomizer:

          - *None* or (str) *sequential* for sequential execution

          - *random* (str) constructs a default random device
            :class:`random.Random`.

          - *SEED* (str) any random string which will used as seed to
            construct a :class:`random.Random` object

          - a :class:`random.Random` instance

        :type: :class:`random.Random`
        """
        return self._target_group_permutations

    @target_group_randomizer.setter
    def target_group_randomizer(self, r):
        self._target_group_randomizer = self._randomizer_make(r, "target_group_randomizer")
        self._target_group_randomizer_original = r


    @staticmethod
    def _legacy_mode_set(where, mode):
        assert isinstance(where, tc_c) or issubclass(where, tc_c)
        # See Execution modes in the documentation on top of this file
        if mode == "one-per-type":
            where._axes_permutations = 0
            where._target_group_permutations = 1
        elif mode == "all":
            where._axes_permutations = 0
            print("WARNING: woah, trying to run everywhere"
                  "--you might not be able to chew it all")
            where._target_group_permutations = 0
        elif mode == "any":
            where._axes_permutations = 1
            where._target_group_permutations = 1


    def _axes_all_update(self):
        #
        # This will be called by executor_c.axes_expand() before doing
        # the pairing run or iterating the axes.
        #
        # update the unified list of axes [testcase + target roles's]
        #
        # Note we always have keep this as an ordered dictionary and
        # we sort the keys alphabetically and also the values.
        #
        # This is **important** because when we need to reproduce the
        # permutations by issuing the same random seed, they need to
        # start always from the same order.
        #
        # So ensure the order is always the same: sort everything,
        # don't use sets :/ because we don't have the OrderedSet in
        # the std. Anywhoo, these are short lists, so not a biggie
        self._axes_all.clear()
        if self._axes:
            for k, v in sorted(self._axes.items(), key = lambda k: k[0]):
                self._axes_all[k] = sorted(list(v))
        for role_name, role in sorted(self.target_roles.items(), key = lambda k: k[0]):
            if role.axes:
                for axis_name, axis_data in role.axes.items():
                    self._axes_all[( role, axis_name )] = sorted(list(axis_data))
        self._axes_all_mr = mrn.mrn_c(*self._axes_all.values())


    def axes_names(self):
        """
        Return the names of all the axes known for the testcase

        **Internal API for testcase/target pairing**

        :return list(str): list of axes for the testcase and each
          target roles.
        """
        return list(self._axes_all.keys())

    _axes_permutation_filter = None

    @property
    def axes_permutation_filter(self):
        """
        A callable to filter a particular axes permutation

        A testcase can override this method (when subclassing or just
        setting on an instance) to filter out invalid axis values.

        >>> @tcfl.tc.axes(axisA = [ 'valA0', 'valA1', 'valA2' ],
        >>>               axisB = [ 'valB0', 'valB1' ])
        >>> class _test(tcfl.tc.tc_c):
        >>>    pass
        >>>
        >>> def my_filter(axes_permutation):
        >>>     if axes_permutation[0] == 'valA0':
        >>>         return False
        >>>
        >>> testcase.axes_permutation_filter = my_filter

        To have the permutation system ignore a particular
        permutation, return a *False* value.

        There are multiple ways this can be specified:

        - create a method in your test class called
          *axes_permutation_filter* that takes as arguments the group
          id and the axes permutation (FIXME: implement classmethod)

          >>> class _test(tcfl.tc.tc_c):
          >>>
          >>>     @staticmethod
          >>>     def axes_permutation_filter(i, axes_permutation):
          >>>         if axes_permutation[0] == 'valA0':
          >>>             return False


        - create a static method in your test class called
          *SOMETHING* that takes as arguments the group
          id and the axes permutation and then set it (FIXME: implement classmethod)

          >>> class _test(tcfl.tc.tc_c):
          >>>
          >>>     @staticmethod
          >>>     def SOMETHING(i, axes_permutation):
          >>>         if axes_permutation[0] == 'valA0':
          >>>             return False

        - create a function to do the filtering

        Setting mechanisms (needed except when creating the method
        called *axes_permutation_filter*):

        - :func:`tcfl.tc.execution_mode` decorator, argument *axes_permutation_filter*

        - for an existing instance, direct assignment:

          >>> testcase.axes_permutation_filter = MYFUNC

        """
        return self._axes_permutation_filter

    @axes_permutation_filter.setter
    def axes_permutation_filter(self, f):
        assert callable(f)
        self._axes_permutation_filter = f
        return self._axes_permutation_filter


    # Target group iteration
    # ----------------------

    #: A callable to filter a target group permutation
    #:
    #: A testcase can override this method (when subclassing or just
    #: setting on an instance) to filter out invalid axis values.
    #:
    #: >>> def my_filter(groupid, groupid_ic, target_group):
    #: >>>     if target_group['target'] == 'SOMETARGET':
    #: >>>         return False
    #: >>>
    #: >>> testcase.target_group_filter = my_filter
    #:
    #: To have the permutation system ignore a particular
    #: target group, return a *False* value.
    #:
    #: .. warning:: target group filtering can be VERY *computational*
    #:              intensive if you have a lot of checks, it might
    #:              make discovery very slow. It is more efficient to
    #:              filter individual targets using *spec*, *ic_spec*
    #:              and *axes* spinning.
    target_group_filter = None


    @staticmethod
    def _axes_verify(axes):
        if axes == None:
            return
        commonl.assert_dict_key_strings(axes, "axes")
        for axis, values in axes.items():
            if values != None:
                commonl.assert_list_of_types(values, f"{axis} values", "value",
                                             ( type(None), int, str, bool, float, bytes, dict ))
            else:
                # we'll fill this a list of the values in the
                # inventory for this field
                pass

    def axes_update(self, origin = None, **kwargs):
        """
        Add axes to a testcase instance

        See :func:`tcfl.tc.axes` for further information.
        """
        self._axes_verify(kwargs)
        if origin == None:
            origin = commonl.origin_get(2)
        self._axes.update(kwargs)
        self.axes_origin.append(origin)
        self._axes_all_update()


    @staticmethod
    def _role_add_args_verify(role_name,
                              axes, axes_extra,
                              spec, spec_args,
                              ic_spec, ic_spec_args,
                              origin, interconnect, count):
        assert isinstance(role_name, str) and role_name.isidentifier(), \
            f"role_name: expected string naming target role" \
            f" (has to be a valid Python identifier); got {type(spec)}"
        assert spec == None or isinstance(spec, str) or callable(spec), \
            f"spec: expected None, a string describing a filtering spec" \
            f" or a filtering function; got {type(spec)}"
        if spec_args:
            commonl.assert_dict_key_strings(spec_args, "spec_args")
        assert ic_spec == None or isinstance(ic_spec, str) or callable(ic_spec), \
            f"ic_spec: expected None, a string describing a filtering spec" \
            f" or a filtering function; got {type(ic_spec)}"
        if ic_spec_args:
            commonl.assert_dict_key_strings(ic_spec_args, "ic_spec_args")
        if origin != None:
            assert isinstance(origin, str), \
                f"origin: expected None or a string describing origin" \
                f" (note *origin* cannot be used as an axis name);" \
                f" got {type(origin)}"
        tc_c._axes_verify(axes)
        tc_c._axes_verify(axes_extra)
        assert isinstance(interconnect, bool), \
            f"interconnect: expected bool; got {type(interconnect)}"
        assert isinstance(count, int) and count >= 1, \
            f"count: expected > 1 integert; got {type(count)}"


    def role_add(self, role_name = "target",
                 axes = None, axes_extra = None,
                 spec = None, spec_args = None,
                 ic_spec = None, ic_spec_args = None,
                 origin = None, interconnect = False, count = 1):
        """Add a :term:`target role` to an instance of a test case

        :param str role_name: (optional; default *target*) name for the
          role; this shall be a simple string and a valid python
          identifier.

          Examples: *client*, *server*, *target*

        :param dict axes: (optional) dictionary keyed by string of the
          axes on which to spin the target role (see :ref:`testcase
          pairing testcase_pairing`).

          >>> dict(
          >>>     AXISNAME = [ VALUE0, VALUE 1... ],
          >>>     AXISNAME = None,
          >>> ...)

          The key name is the axis name, which as to be a valid Python
          identifier and the values are *None* (to get all the values
          from the inventory) or a list of values valid axis values
          (which an be *bool*, *int*, *float* or *str*).

          Note that when getting the values from the inventory, only
          values that apply to a target that matches the *spec* will
          be considered [*ic_spec* is ignored for this].

          See :func:`tcfl.tc.axes` for more descriptions on axis.

          By default, this is set to only spin on the *type* axis; to
          add to this default, set instead the *axes_extra*
          parameter. To override the default, set this parameter.

        :param dict axes_extra: (optional) same as *axes*, but to add
          to it instead of overriding.

        :param str,callable spec: (optional) target specification
          filter--used to filter which targets are acceptable for this
          role.

          This can be a string describing a logical expression or a
          function that does the filtering; the function *MUST* be
          not depend on global data other than the target inventory
          and be estable over calls, since its results will be cached.

          See :ref:'target filtering <target_filtering>` for more
          information

        :param dict spec_args: (optional) dictionary of arguments to
          the *spec* call (if used)

        :param str,callable ic_spec: (optional) target specification
          filter for interconnectivity--used to filter which targets
          meet the connectivity needs of the testcase (eg: is target *A*
          is connected to networks *E* and *F*?).

          This is separate from the *spec* filter above for
          performance reasons. To calculate connectivity maps the
          permutations are heavily reduced if we have been able to
          first reduce and cache the valid targets and then cache by
          connectivity.

          For example, to request a target that is connected to
          another two targets (declared as interconnects)

          >>> ic_spec = pairer._spec_filter_target_in_interconnect,
          >>> ic_spec_args = { 'interconnects': [ 'ctl', 'nut' ] }

          See :ref:'target filtering and interconnectivity
          <target_filtering_ic>` for more information

        :param dict ic_spec_args: (optional) dictionary of arguments to
          the *ic_spec* call (if used)

        :param str origin: (optional) where is this being registered;
          defaults to the caller of this function.

        :param bool interconnects: if *True* consider, consider this
          role as an interconnect, a target that interconnects other
          targets (eg: a network).

        :param int count: (optional, default 1) positive number that
          indicates how many roles to create--this is used to easily
          add targets that will be called the same, with the same
          *spec*, adding an index to their name (eg: target, target1,
          target2...targetN)

        """
        if axes == None:
            axes = { "type": None }
        self._role_add_args_verify(role_name, axes, axes_extra,
                                   spec, spec_args, ic_spec, ic_spec_args,
                                   origin, interconnect, count)

        _axes = collections.OrderedDict(axes)
        if axes_extra:	# FIXME: just ove this to target_c
            assert isinstance(axes_extra, dict)
            # FIXME: verify
            _axes.update(axes_extra)

        for index in range(count):
            _role_name = role_name if index == 0 else role_name + f"{index}"
            self.target_roles[_role_name] = target_c(
                _role_name, origin, _axes,
                spec, spec_args, ic_spec, ic_spec_args,
                interconnect)

    #
    # Execution
    #
    # FIXME: move to executor_c
    #
    # - we end up passing the testcase around; not sure I fully like
    #   it, since it means it has to be pickable -- oh well?
    #
    #   generators are not pickable
    #
    # - break execution in static and tg
    #
    # - basically piece stuff in a queue; mp pool picks things to do
    #   from the queue
    #
    allocation_groups = 10

    def _report_results(self, r):
        self.log(f"NOTIMPLEMENTED: report_results {r}")

    def _run_static(self):
        # FIXME: move to executor_c
        # _run_for_axes_permutation has set
        #
        # self.{axes_permutation}{,_id}, target_group_permutation

        # FIXME configure, build
        self.report_info(f"running configure/build")
        if not self.target_roles:
            self.report_info(f"running cleanup")
            self._report_results("FIXME")

    def _run_tg(self):
        # scheduled by the allocator when the target group is allocated
        self.log(f"DEBUG: running eval")
        self.log(f"DEBUG: running cleanup")
        self._report_results("FIXME")


    # Driver API

    @classmethod
    def driver_setup(cls, *args, **kwargs):
        """
        Steps to perform to configure the driver; called when added

        Driver writers can subclass to perform steps upon addition

        Parameters are as passed to :meth:`tcfl.testcase.driver_add`.
        """
        return


    @classmethod
    def find_testcases(cls, testcases, testcase_path, subcases_cmdline):
        """Find testcases in a given path

        WARNING! It is unlikely a testcase driver has to define this method

        Given a path, scan for test cases and put them in the
        dictionary @testcases based on filename where found. list of zero
        or more paths, scan them for files that contain testcase tc
        information and report them.

        Normally all you need for a new driver is subclassing
        :meth:`is_testcase`.

        :param dict tcs: dictionary where to add the test cases found,
          keyed by testcase name, values have to be a class or
          subclass of :class:`tcfl.tc_c`

        :param str path: path where to scan for test cases

        :param list subcases: list of subcase names the testcase should
          consider

        :returns: :class:`tcfl.result_c` with counts of tests
          passed/failed (zero, as at this stage we cannot know),
          blocked (due to error importing) or skipped(due to whichever
          condition).

        """
        return result_c()


    @classmethod
    def is_testcase(cls, path, from_path, tc_name, subcases_cmdline):
        """Determine if a given file describes one or more testcases and
        crete them

        TCF's test case discovery engine calls this method for each
        file that could describe one or more testcases. It will
        iterate over all the files and paths passed on the command
        line files and directories, find files and call this function
        to enquire on each.

        This function's responsibility is then to look at the contents
        of the file and create one or more objects of type
        :class:`tcfl.tc.tc_c` which represent the testcases to be
        executed, returning them in a list.

        When creating :term:`testcase driver`, the driver has to
        create its own version of this function. The default
        implementation recognizes python files called *test_\*.py* that
        contain one or more classes that subclass :class:`tcfl.tc.tc_c`.

        See examples of drivers in:

        - :meth:`tcfl.tc_clear_bbt.tc_clear_bbt_c.is_testcase`
        - :meth:`tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.is_testcase`
        - :meth:`examples.test_ptest_runner` (:term:`impromptu
          testcase driver`)

        note drivers need to be registered with
        :meth:`tcfl.tc.tc_c.driver_add`; on the other hand, a Python
        :term:`impromptu testcase driver` needs no registration, but
        the test class has to be called *_driver*.

        :param str path: path and filename of the file that has to be
          examined; this is always a regular file (or symlink to it).

        :param str from_path: source command line argument this file
          was found on; e.g.: if *path* is *dir1/subdir/file*, and the
          user ran::

            $ tcf run somefile dir1/ dir2/

          *tcf run* found this under the second argument and thus:

          >>> from_path = "dir1"

        :param str tc_name: testcase name the core has determine based
          on the path and subcases specified on the command line; the
          driver can override it, but it is recommended it is kept.

        :param list(str) subcases_cmdline: list of subcases the user
          has specified in the command line; e.g.: for::

            $ tcf run test_something.py#sub1#sub2

          this would be:

          >>> subcases_cmdline = [ 'sub1', 'sub2']

        :returns: list of testcases found in *path*, empty if none
          found or file not recognized / supported.

        """
        raise NotImplementedError


#
# tc_c decorators
# ---------------

def axes(origin = None, **kwargs):
    """
    Add axes to a testcase class

    This is used as a decorator to a testcase class to add axes that
    need to be considered during execution.

    >>> @tcfl.tc.axes(axisA = [ 'valA0', 'valA1', 'valA2' ],
    >>>               axisB = [ 'valB0', 'valB1' ])
    >>> class _test(tcfl.tc.tc_c):
    >>      pass

    To add axes to an instance of a testcase, use
    :meth:`tcfl.tc.tc_c.axes_update()`

    :param str origin: (optional; defaults to current file and line
      number) record a file origin from where axes were added.

    :param axes: the rest of the parameters are in the form *AXISNAME
      = LIST(VALUES)*, where *AXISNAME* will be the axis name and has to
      be a valid Python identifier. *LIST(VALUES)* is a list of valid
      axis values (which an be *bool*, *int*, *float* or *str*).

      A common construct to get axis valus from the environment is:

      >>> @tcfl.tc.axes(axisA = [ 'valA0', 'valA1', 'valA2' ],
      >>>               axisB = os.environ.get(AXISB_VALUES, "valB0 valB1").split())
      >>> class _test(tcfl.tc.tc_c):
      >>>     pass


    """
    assert origin == None or isinstance(origin, str), \
        "origin: expected None or a string describing origin" \
        " (note *origin* cannot be used as an axis name)"
    tc_c._axes_verify(kwargs)
    if origin == None:
        origin = commonl.origin_get(2)

    def decorate_class(cls):
        assert isinstance(cls, type)
        assert issubclass(cls, tc_c)
        cls._axes.update(kwargs)
        cls.axes_origin.append(origin)
        return cls

    return decorate_class


def role_add(name = "target",
             axes = None, axes_extra = None,
             spec = None, spec_args = None,
             ic_spec = None, ic_spec_args = None,
             origin = None, interconnect = False, count = 1,
             # legacy
             mode = None):
    """
    Add a generic target role (target or interconnect) to a testcase class

    For more clarity, you might want to use :func:`tcfl.tc.target` or
    :func:`tcfl.tc.interconnect` instead.

    See :tcfl.tc.tc_c.role_add() for parameter information
    :param axes: the rest of the parameters are in

    A common construct would be:

    >>> @tcfl.tc.role_add(
    >>>     name = "target",
    >>>     axisA = [ 'valA0', 'valA1', 'valA2' ],
    >>>     axisB = os.environ.get(AXISB_VALUES, "valB0 valB1").split())
    >>> class _test(tcfl.tc.tc_c):
    >>>     ...
    """
    if axes == None:
        axes = { "type": None }
    tc_c._role_add_args_verify(name, axes, axes_extra,
                               spec, spec_args, ic_spec, ic_spec_args,
                               origin, interconnect, count)

    _axes = collections.OrderedDict(axes)
    if axes_extra:	# FIXME: just ove this to target_c
        assert isinstance(axes_extra, dict)
        # FIXME: verify
        _axes.update(axes_extra)

    def decorate_class(cls):
        assert isinstance(cls, type)
        assert issubclass(cls, tc_c)

        # Ugly way of doing it; we want to build upon the base class's
        # dictionary -- but not modify them; so when we add, we COPY the
        # base's dictionary and modify it to this.
        super_cls = super(cls, cls)
        if id(super_cls.target_roles) == id(cls.target_roles):
            cls.target_roles = collections.OrderedDict(super_cls.target_roles)

        for index in range(count):
            _role_name = name if index == 0 else name + f"{index}"
            cls.target_roles[_role_name] = target_c(
                _role_name, origin, _axes,
                spec, spec_args, ic_spec, ic_spec_args,
                interconnect = interconnect)

        if mode != None:
            tc_c._legacy_mode_set(cls, mode)

        return cls

    return decorate_class


def target(spec = None, name = "target", count = 1, **kwargs):
    """
    Add a target role to a testcase class

    See :tcfl.tc.tc_c.role_add() for parameter information.

    A common construct would be:

    >>> @tcfl.tc.target(
    >>>     name = "target",
    >>>     axisA = [ 'valA0', 'valA1', 'valA2' ],
    >>>     axisB = os.environ.get(AXISB_VALUES, "valB0 valB1").split())
    >>> class _test(tcfl.tc.tc_c):
    >>>     ...
    """
    try:
        del kwargs['interconnect']
    except KeyError:
        pass
    return role_add(
        spec = spec, name = name, count = count, interconnect = False,
        **kwargs)


def interconnect(spec = None, name = "ic", count = 1, **kwargs):
    """
    Add an interconnect role to a testcase class

    See :tcfl.tc.tc_c.role_add() for parameter information.

    A common construct to get axis valus from the environment is:

    >>> @tcfl.tc.interconnect(name = "ic", spec = "ipv4_address")
    >>> @tcfl.target(name = "target",
    >>>              ic_spec = pairer._spec_filter_target_in_interconnect,
    >>>              ic_spec_args = { 'interconnects': [ 'ic' ] })
    >>> class _test(tcfl.tc.tc_c):
    >>>     ...
    """
    try:
        del kwargs['interconnect']
    except KeyError:
        pass
    # default for interconnects, if you override, assume you know
    # what you are doing i ¯\_(ツ)_/¯
    kwargs.setdefault('axes', { 'interfaces.interconnect_c':  [ {} ] })
    return role_add(
        spec = spec, name = name, count = count, interconnect = True,
        **kwargs)


def execution_mode(
        axes_permutations = None, axes_randomizer = None,
        axes_permutation_filter = None,
        target_group_permutations = None, target_group_randomizer = None):
    """
    Decorator to change the execution mode of a testcase

    >>> @tcfl.tc.execution_mode(ARGUMENTS)
    >>> class _test(tcfl.tc.tc_c):
    >>>     ...

    See the documentation in:

    - :attr:tc_c.axes_permutations
    - :attr:tc_c.axes_randomizer
    - :attr:tc_c.axes_permutation_filter
    - :attr:tc_c.target_group_permutations
    - :attr:tc_c.target_group_randomizer

    for valid values. All arguments are optional
    """
    def decorate_class(cls):
        assert isinstance(cls, type)
        assert issubclass(cls, tc_c)

        # it's kinda hard to make setters for class variables, so just
        # do it straight
        if axes_permutations != None:
            assert isinstance(axes_permutations, int) \
                and axes_permutations >= 0, \
                f"axes_permutations: expected >= integer," \
                f" got {type(axes_permutations)}"
            cls._axes_permutations = axes_permutations
        if axes_randomizer != None:
            cls._axes_randomizer = cls._randomizer_make(
                axes_randomizer, "axes_randomizer")
        if axes_permutation_filter != None:
            assert callable(axes_permutation_filter), \
                f"axes_permutation_filter: expected a callable function;" \
                f" got {type(axes_permutation_filter)}"
            cls._axes_permutation_filter = axes_permutation_filter
        if target_group_permutations != None:
            assert isinstance(target_group_permutations, int) \
                and target_group_permutations >= 0, \
                f"target_group_permutations: expected >= integer," \
                f" got {type(target_group_permutations)}"
            cls._target_group_permutations = target_group_permutations
        if target_group_randomizer != None:
            cls._target_group_randomizer = cls._randomizer_make(
                target_group_randomizer, "target_group_randomizer")
        return cls

    return decorate_class


def serially():
    """
    Force a testcase method to run serially (vs :func:`concurrently`).

    Remember methods that are ran serially are run first and by
    default are those that

    - take more than one target as arguments

    - are evaluation methods

    >>> class _test(tcfl.tc_c):
    >>>    ...
    >>>    @tcfl.serially
    >>>    def deploy(self, target):
    >>>        ...
    """
    def decorate_fn(fn):
        setattr(fn, "execution_mode", 'serial')
        return fn
    return decorate_fn


def concurrently():
    """
    Force a testcase method to run concurrently after all the serial
    methods (vs decorator :func:`serially`).

    Remember methods that are ran concurrently are run after the
    serial methods and by default those that:

    - are not evaluation methods

    - take only one target as argument (if you force two methods that
      share a target to run in parallel, it is your responsiblity to
      ensure proper synchronization

    >>> class _test(tcfl.tc_c):
    >>>    ...
    >>>    @tcfl.concurrently()
    >>>    def deploy(self, target):
    >>>        ...
    """
    def decorate_fn(fn):
        setattr(fn, "execution_mode", 'parallel')
        return fn
    return decorate_fn


def _spec_filter_target_in_interconnect(target_roles, target_group,
                                        target_role, extra_args, target_rt):
    # inventory is now in target_roles.target_inventory
    # FIXME: not clear how we can do this here--this wants to check if
    # target_rt is in an interconnect

    ic_role_names = extra_args.get('interconnects', None)
    if ic_role_names == None:
        raise ValueError(
            f'filter configuration error: target role {target_role.role} '
            'needs to specify argument "ic_spec_args" as a dictionary '
            'containing a "interconnects" entry with the name (or '
            'list of names) of the '
            'interconnect/s the target has to be connected to')

    if isinstance(ic_role_names, str):
        ic_role_names = [ ic_role_names ]
    else:
        commonl.assert_list_of_strings(ic_role_names,
                                       "ic_role_names", "role name")
    for ic_role_name in ic_role_names:
        # the target group creation process first resolves the
        # interconnects, so by the time we get to the targets, the
        # interconnect name has been assigned already. This means that
        # interconnect depedencies can't be circular.
        ic_fullid = target_group.get(ic_role_name, None)
        if ic_fullid == None:
            raise RuntimeError(
                f'target role {target_role.role} interconnectivity spec error: '
                f'it is demanding being connected to interconnect {ic_role_name} '
                f'but it is not yet known/resolved'
                #FIXME needs better explanation
                )


        # Because interconnects span servers, we refer to them with
        # their ID (vs their *fullid* which includes the server name);
        # so in the interconnect info they are referred to as *id* only.
        #
        # thus convert fullid -> id
        ic_server, ic_id = ic_fullid.split("/", 1)

        # List the target's interconnects  and let's see if one of
        # them is the interconnect ic_id
        target_interconnects = target_rt.get('interconnects', {})
        if ic_id not in target_interconnects:
            return False, f"target is not in interconnect {ic_fullid}"

    return True, None


def shutdown():
    """
    Shutdown API, saving state in *path*.

    :param path: Path to where to save state information
    :type path: str
    """
    if not server_c.servers:
        return
    with concurrent.futures.ThreadPoolExecutor(len(server_c.servers)) as e:
        e.map(lambda server: server._state_save(), server_c.servers.values())


# we don't need too much logging level from this
logging.getLogger("filelock").setLevel(logging.CRITICAL)

# add a server "ttbd" which the admins can initialize by just aliasing
# DNS and this triggers all servers auto-discovering.
server_c.seed_add(
    "ttbd", port = 5000, ssl_verify = False,
    origin = f"defaults @{commonl.origin_get()}")
