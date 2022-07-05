#! /usr/bin/python3
#
# Copyright (c) 2017-21 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import collections
import concurrent.futures
import datetime
import inspect
import itertools
import json
import logging
import os
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

import filelock

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


    def __bool__(self):
        """
        If we have no results to speak of, this eavluates as *False*,
        otherwise it is considered *True*
        """
        if (
            self.passed == 0
            and self.errors == 0
            and self.failed == 0
            and self.blocked == 0
            and self.skipped == 0
        ):
            return False
        return True


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

        # FIXME:HACK until we are done solving the import hell
        from . import tc
        if isinstance(_tc, tc.target_c):
            tc = _tc.testcase
        else:
            assert isinstance(_tc, tc.tc_c)
            tc = _tc

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
                "stdout": e.stdout,
                "stderr": e.stderr,
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

    # Run cls_init_maybe() if cls_init() has not been initialized
    @classmethod
    def cls_init_maybe(cls):
        if not hasattr(cls.tls, "msgid_lifo"):
            cls.tls.msgid_lifo = []

    def __init__(self, s = None,
                 phase = None, depth = None, parent = None,
                 depth_relative = None,
                 testcase = None, subcase = None):
        cls = type(self)
        if not hasattr(cls.tls, "msgid_lifo"):
            cls.cls_init()
        cls.cls_init_maybe()

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
        cls.cls_init_maybe()
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
        cls.cls_init_maybe()
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._depth
        else:
            return 0

    @classmethod
    def phase(cls):
        cls.cls_init_maybe()
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._phase
        else:
            return None

    @classmethod
    def ident(cls):
        cls.cls_init_maybe()
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._ident
        else:
            return None

    @classmethod
    def subcase(cls):
        cls.cls_init_maybe()
        if cls.tls.msgid_lifo:
            f = cls.tls.msgid_lifo[-1]
            return f._subcase
        else:
            return None

    @classmethod
    def current(cls):
        cls.cls_init_maybe()
        if cls.tls.msgid_lifo:
            return cls.tls.msgid_lifo[-1]
        else:
            return None

    @classmethod
    def parent(cls):
        cls.cls_init_maybe()
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


import tcfl.config		# FIXME: this is bad, will be removed


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

    #: List of servers found indexed by AKA
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

    def cache_wipe(self):
        """
        Delete this server's cache entry, database and lockfiles
        """
        with filelock.FileLock(self.cache_lockfile):
            r = self.fsdb.set(self.aka, None)
            commonl.rm_f(self.cache_lockfile)
            return r

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
                cls.servers[url] = cls(url, ssl_verify = ssl_verify, aka = aka,
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



class tc_info_c:
    """
    Information about a testcase

    This class contains the most basic data about a testcase,
    such as its name, tags, in which targets it can run.

    It is extracted by each test case driver and allows the
    orchestrator to decide how and where a testcase has to be run.

    If the process of discovering the testcase produces an error or
    exception condition, or skipped, it is reported as such by setting
    values in :data:`result`, :data:`exception` and :data:`output`.
    """
    # This shall be pickable so we can send it over a queue
    def __init__(self, name, file_path,
                 origin = None,
                 subcase_spec = None,
                 axes = None,
                 target_roles = None, driver_name = None, tags = None,
                 result = None, output = "",
                 exception = None, formatted_traceback = None):
        #: Name of this testcase
        #:
        #: in most cases, it is going to contain :data:`file_path` in
        #: the form *FILEPATH[#SUBCASE]*
        self.name = name
        #: path of file where this testcase was found
        self.file_path = file_path
        #: line number or location inside :data:`file_path` where this
        #: test was found
        self.origin = origin
        #: list of subcases by name that the runner is supposed to execute
        self.subcase_spec = subcase_spec
        self.axes = axes
        self.target_roles = target_roles
        self.tags = tags
        self.driver_name =  driver_name
        self.result = result
        assert isinstance(output, str), \
            f"output: expected str, got '{type(output)}'"
        #: If the testcase has produced any high level summary output, said
        #: output in string form
        self.output = output
        #: Exception or completion message information
        #:
        #: This is an object that describes an issue with the testcase
        #: execution or the summary of if
        self.exception = exception
        #: Formated traceback that applies to :data:`exception`
        #:
        #: Needs to be formatted so it is just a list of strings that
        #: can be easily pickable when sending this object via a
        #: queue.
        #:
        #: >>> formatted_traceback = traceback.format_exc()
        #: >>> formatted_traceback = traceback.format_tb(sys.exc_info()[2])
        self.formatted_traceback = formatted_traceback



# we don't need too much logging level from this
logging.getLogger("filelock").setLevel(logging.CRITICAL)

# add a server "ttbd" which the admins can initialize by just aliasing
# DNS and this triggers all servers auto-discovering.
server_c.seed_add(
    "ttbd", port = 5000, ssl_verify = False,
    origin = f"defaults @{commonl.origin_get()}")
