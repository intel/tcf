#! /usr/bin/python3
#
# Copyright (c) 2017-21 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""TCF client library
==================

Utilities for connecting to ttbd servers and managing the targets exposed by them


Debug support
-------------

- *SSL tracing*: invoke any thing that uses this library with the
  environment variable *SSLKEYLOGFILE* defined to a file name where to
  log SSL traffic so it can be analyzed with tools such as wireshark

  - https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=&cad=rja&uact=8&ved=2ahUKEwjeuoy3q6SDAxXwBTQIHY5eDLUQFnoECBAQAQ&url=https%3A%2F%2Fsslkeylog.readthedocs.io%2F&usg=AOvVaw0AlYxgLSaopOJpermTyvNN&opi=89978449

  - https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=&cad=rja&uact=8&ved=2ahUKEwjeuoy3q6SDAxXwBTQIHY5eDLUQFnoECBIQAQ&url=https%3A%2F%2Fmy.f5.com%2Fmanage%2Fs%2Farticle%2FK50557518&usg=AOvVaw3paDq2czEK4CQhE0keC4Nb&opi=89978449

  - https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=&cad=rja&uact=8&ved=2ahUKEwih4bHLq6SDAxVRNzQIHZjdAHwQFnoECBYQAQ&url=https%3A%2F%2Fwww.comparitech.com%2Fnet-admin%2Fdecrypt-ssl-with-wireshark%2F&usg=AOvVaw16YzciaANpU9FnBj8RaZkv&opi=89978449

"""
import collections
import concurrent.futures
import datetime
import errno
import inspect
import itertools
import json
import logging
import os
import pickle
import shutil
import socket
import tempfile
import time
import urllib

import base64
import hashlib
import random
import requests
import subprocess
import sys
import threading
import traceback

import filelock

import commonl

logger = logging.getLogger("tcfl")
log_sd = logging.getLogger("server-discovery")

#: List of paths which we use to look for configuration files;
#: initialized by tcfl.config.subsystem_setup()
config_path = []

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
            target = _tc
        else:
            assert isinstance(_tc, tc.tc_c)
            tc = _tc
            target = None

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
        if isinstance(reporter, tcfl.tc.reporter_c):
            for report_exception_hook, origin in tc._report_exception_hooks.items():
                try:
                    report_exception_hook(
                        reporter, tc, target, e,
                        level + dlevel, level + dlevel + alevel + trace_alevel, msg_tag,
                        _attachments,
                        subcase = subcase, subcase_base = subcase_base)
                except Exception as e:
                    # this is a bug, so log with traces
                    logging.exception(
                        "BUG! report_from_exception() report exception hook"
                        f" {report_exception_hook}[@{origin}]"
                        f" raised exception: {e} ")
            reporter._report(
                level + dlevel, level + dlevel + alevel + trace_alevel, msg_tag,
                "%s%s: %s" % (phase, tag, _e),
                _attachments,
                subcase = subcase, subcase_base = subcase_base,
            )
        else:
            logging.error(
                f"BUG! report_from_exception() reporter is {type(reporter)}/{reporter};"
                f" expected tcfl.tc.reporter_c. _tc is {type(_tc)} "
                f" target attachment is {type(attachments.get('target', None))}: "
                + ''.join(traceback.format_stack()))
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


tls = threading.local()

def tls_var(name, factory, *args, **kwargs):
    value = getattr(tls, name, None)
    if value == None:
        value = factory(*args, **kwargs)
        setattr(tls, name, value)
    return value


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

    # FIXME: merge with tcfl.tls
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
        # Check the exception against None; that's what says we had no
        # exception. Don't do a bool(exce_value) because if
        # they type does it's on bool'ing, then we'll miss things that
        # bool to False for any reason.
        if exce_value != None:
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


# Export all SSL keys to a file, so we can analyze traffic on
# wireshark & friends
if 'SSLKEYLOGFILE' in os.environ:
    import sslkeylog
    sslkeylog.set_keylog(os.environ['SSLKEYLOGFILE'])


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
    Broker*-- in areas of the client code you might see *rtb* and
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
        self.url_safe = commonl.file_name_make_safe(self.parsed_url.geturl())
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
        # FIXME: self.lock() is at this point only used for the
        # cookies...which are in self.cookies and we should be
        # updating to the file all the time anyway after calling
        # send_request()
        self.lock = threading.Lock()
        self.cookies = {}
        self.cache_lockfile = None
        self.fsdb = None
        self.log = logger.getChild(self.url_safe)

        # Sets up any other internal data structure that are no strictly
        # needed until operating seconday parts of the API (eg: file paths)
        self.aka_make()
        self.log = logger.getChild(self.aka)
        self._cache_setup()


    #: where to store state path (login info, etc); updated by
    #: tcfl.config.subsystem_setup()
    state_path = None

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
            log_sd.warning(f"ignoring hostname '{hostname}' [{origin}]: {e}",
                           exc_info = commonl.debug_traces)
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
        logger.info("%s: cache deleted in %s", self.url, self.cache_lockfile)
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
        with filelock.FileLock(self.cache_lockfile):
            self._cache_set_unlocked(
                "last_success",
                datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))
            # since this has been succesful, reset the failure markers
            self._cache_set_unlocked("failure_count", 0)
            self._cache_set_unlocked("failure_last", None)



    def _record_failure(self):
        with filelock.FileLock(self.cache_lockfile):
            current_count = self._cache_get_unlocked("failure_count", 0)
            if isinstance(current_count, str):	# COMPAT: previously was str
                current_count = int(current_count)
            current_count += 1
            self._cache_set_unlocked("failure_count", current_count)
            utcnow = float(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S.%f"))
            self._cache_set_unlocked("failure_last", utcnow)

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

        failure_count = self._cache_get_unlocked("failure_count", 0)
        if isinstance(failure_count, str):	# COMPAT: previously was str
            failure_count = int(failure_count)
        utcnow = float(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S.%f"))
        failure_last = self._cache_get_unlocked("failure_last", utcnow)
        failure_delta = utcnow - failure_last

        # Shall we scan this guy? This depends on it having failed recently
        #
        # We have two magnitudes
        #
        # - failure_count: increased every time we call
        #   _record_failure(), reset to zero once we call
        #   _record_success()
        #
        # - failure_delta: the time in seconds from the last failure to know
        #
        # We need to determine that if the last failure happened less
        # than MAX seconds ago, it'll probably fail again.
        #
        # - make sense to increase MAX when we detect more failures,
        #   so we weed out bad servers quickly
        #
        # - makes sense to decrease MAX to take into account glitches
        #
        # So MAX has to be proportional to the failure count, but also
        # capped to 10 min, so each 10 min we retry at least once.
        #
        failure_delta_max = min(failure_count, 10) * 60

        if failure_delta > 0 and failure_delta < failure_delta_max:
            return self, None, \
                f"{self.url}/ttb: not scanning, failed {failure_delta:.2f}s" \
                f" ago ({failure_count=}), less than {failure_delta_max}s"
        log_sd.info("#%d/%d: scanning %s: @%s: failure_delta %.2fs count %d",
                    count, loops_max,
                    self.url, self.origin, failure_delta, failure_count)

        # this is always available with no login
        try:
            # FIXME: use server.send_request, so it retries
            r = requests.get(self.url + "/ttb",
                             verify = self.ssl_verify,
                             # want fast response, go quick or go
                             # away--otherwise when discovering many we
                             # could be here many times
                             timeout = 2)
        except Exception as e:
            self._record_failure()
            return self, None, \
                f"{self.url}/ttb: got exception {e}"

        # this we set it as an UTC YYYYmmddHHMMSS -- we'll check it
        # later when doing discovery to avoid doing them too often
        self._cache_set(
            "last_discovery",
            datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))

        if r.status_code != 200:
            if r.status_code != 404:
                self._record_failure()
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
            self._record_failure()
            return self, None, \
                f"{self.url}/ttb: bad JSON {e}"
        if not isinstance(j, dict):
            self._record_failure()
            return self.url, None, \
                f"{self.url}/ttb: expected a dictionary, got {type(j)}"
        # note it is legal for a server to report no herds if it
        # working alone.
        herds = r.json().get('herds', {})
        if not isinstance(herds, dict):
            self._record_failure()
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
                last_discovery = int(server._cache_get("last_discovery", 0))
                utcnow = int(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"))
                failure_last = int(server._cache_get("failure_last", utcnow))
                # this we set it as an UTC YYYYmmddHHMMSS
                ellapsed = utcnow - last_discovery
                if failure_last > last_discovery:
                    delta = failure_last - last_discovery
                    log_sd.warning(
                        "%s: ignoring cache age; re-discovering:"
                        " failure detected %.2fs after last discovery",
                        server_name, delta)
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


    API_VERSION = 2
    API_PREFIX = "/ttb-v" + str(API_VERSION)

    # FIXME: this timeout has to be proportional to how long it takes
    # for the target to flash, which we know from the tags
    def send_request(self, method, url,
                     data = None, json = None, files = None,
                     stream = False, raw = False,
                     timeout = 160, timeout_extra = None,
                     retry_timeout = 0, retry_backoff = 0.5,
                     skip_prefix = False):
        """
        Send a request to the server

        Using url and data and current loging cookies, save the
        cookies generated from the request, search for issues on
        connection and raise and exception or return the response
        object.

        :param str url: url to request
        :param dict data: args to send in the request. default None
        :param str method: method used to request GET, POST and
          PUT. Defaults to PUT.
        :param bool raise_error: if true, raise an error if something goes
           wrong in the request. default True

        :param int timeout_extra: extra timeout on top of the
          *timeout* variable; this is meant to add extra timeouts from
          environment.
-
          If *None*, take the extra timeout from the environment
          variable *TCFL_TIMEOUT_EXTRA*.

        :param float retry_timeout: (optional, default 0--disabled)
          how long (in seconds) to retry connections in case of failure
          (:class:`requests.exceptions.ConnectionError`,
          :class:`requests.exceptions.ReadTimeout`)

          Note a retry can have side effects if the request is not
          idempotent (eg: writing to a console); retries shall only be
          enabled for GET calls. Support for non-idempotent calls has
          to be added to the protocol.

          See also :meth:`tcfl.tc.target_c.ttbd_iface_call`

        :returns requests.Response: response object

        """
        # FIXME: unify this with tcfl.tc.target_c.ttbd_iface_call()'s
        # repeat and error handling, now they are nested so that ttbd_iface_call()
        # just calls send_request() without loop
        assert not (data and json), \
            "can't specify data and json at the same time"
        assert isinstance(retry_timeout, (int, float)) and retry_timeout >= 0, \
            f"retry_timeout: {retry_timeout} has to be an int/float >= 0"
        assert isinstance(retry_backoff, (int, float)) and retry_backoff > 0
        if retry_timeout > 0:
            assert retry_backoff < retry_timeout, \
                f"retry_backoff {retry_backoff} has to be" \
                f" smaller than retry_timeout {retry_timeout}"

        if timeout_extra == None:
            timeout_extra = int(os.environ.get("TCFL_TIMEOUT_EXTRA", 0))
        assert timeout_extra >= 0, \
            "TCFL_TIMEOUT_EXTRA: (from environment) must be positive" \
            " number of seconds;  got {timeout_extra}"
        timeout += timeout_extra

        # create the url to send request based on API version
        if url.startswith("/"):		# url is always relative, but for
            url = url[1:]		# ...join() to work, leading / removed

        # note: urljoin() takes only the HOSTNAME:PORT, skipping any
        # PATH, so, do it by hand
        url_base = self.parsed_url.geturl()
        if not skip_prefix:
            url_base += self.API_PREFIX
        url_request = url_base + "/" + url
        logger.debug("send_request: %s %s", method, url_request)
        cookies = self.state_load()	# keep' em on self for reference
        with self.lock:
            self.cookies = dict(cookies)     # to access out of the
        # lock keep the sessions per-host/port, otherwise the cookies
        # will be messed up
        session = tls_var("session" + self.parsed_url.netloc, requests.Session)
        retry_count = -1
        retry_ts = None
        r = None
        while True:
            retry_count += 1
            try:
                if method == 'GET':
                    r = session.get(url_request, cookies = cookies, json = json,
                                    data = data, verify = self.ssl_verify,
                                    stream = stream, timeout = (timeout, timeout))
                elif method == 'PATCH':
                    r = session.patch(url_request, cookies = cookies, json = json,
                                      data = data, verify = self.ssl_verify,
                                      stream = stream, timeout = ( timeout, timeout ))
                elif method == 'POST':
                    r = session.post(url_request, cookies = cookies, json = json,
                                     data = data, files = files,
                                     verify = self.ssl_verify,
                                     stream = stream, timeout = ( timeout, timeout ))
                elif method == 'PUT':
                    r = session.put(url_request, cookies = cookies, json = json,
                                    data = data, verify = self.ssl_verify,
                                    stream = stream, timeout = ( timeout, timeout ))
                elif method == 'DELETE':
                    r = session.delete(url_request, cookies = cookies, json = json,
                                       data = data, verify = self.ssl_verify,
                                       stream = stream, timeout = ( timeout, timeout ))
                else:
                    raise AssertionError(f"{method}: unknown HTTP method" )
                break
            except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout,
            ) as e:
                # Retry only these; note these cannot report
                # Report how many retries we have done, wait a backoff
                # and then loop it.
                if retry_timeout == 0:
                    raise
                ts = time.time()
                if retry_ts == None:
                    retry_ts = ts	# first one
                else:
                    if ts - retry_ts > retry_timeout:
                        raise RuntimeError(
                            f"{url_request}: giving up after {retry_timeout}s"
                            f" retrying {retry_count} connection errors") from e
                time.sleep(retry_backoff)
                # increase the backoff to avoid pestering too much,
                # but make sure it doesn't get too big so we at least
                # get 10 tries in the timeout period
                if retry_backoff < retry_timeout / 10:
                    retry_backoff *= 1.2
                continue


        # update cookies; save to the file so other instances can get
        # the updated cookies
        if len(r.cookies) > 0:
            cookies = {}
            # Need to update like this because r.cookies is not
            # really a dict, but supports items() -- overwrite
            # existing cookies (session cookie) and keep old, as
            # it will have the stuff we need to auth with the
            # server (like the remember_token)
            # FIXME: maybe filter to those two only?
            for cookie, value in r.cookies.items():
                cookies[cookie] = value
            self.state_save(cookies)
            with self.lock:
                self.cookies = cookies
        commonl.request_response_maybe_raise(r)
        if raw:
            return r
        rdata = r.json(object_pairs_hook = collections.OrderedDict)
        if '_diagnostics' in rdata:
            diagnostics = rdata.pop('_diagnostics')
            # this is not very...memory efficient
            for line in diagnostics.split("\n"):
                logger.warning("diagnostics: " + line)
        return rdata



    def state_load(self):
        """
        Load saved state
        """
        file_name = os.path.join(self.state_path,
                                 f"cookies-{self.url_safe}.pickle")
        try:
            with open(file_name, "rb") as f:
                cookies = pickle.load(f)
            logger.info("%s: loaded state", file_name)
            return cookies
        except pickle.UnpicklingError as e: #invalid state, clean file
            os.remove(file_name)
            return {}
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise e
            logger.debug("%s: no state-file, will not load", file_name)
            return {}


    def state_save(self, cookies):
        """
        Save state information (login, etc), so it can be loaded with
        :meth:`state_load`.

        """
        commonl.makedirs_p(self.state_path, reason = "server state directory")
        file_name = os.path.join(self.state_path,
                                 f"cookies-{self.url_safe}.pickle")
        if not cookies:
            logger.debug("%s: state deleted (no cookies)", self.url)
            commonl.rm_f(file_name)
            return
        # do not delete the "not-so-temp" file with the new cookies,
        # as we are going to use it to write the new permanent one
        # with replace later on.
        with tempfile.NamedTemporaryFile(dir = self.state_path,
                                         delete = False) as f:
            # create a temporary file and replace, so the operation is
            # atomic--other proceses might have done this in
            # parallel--there would be no conflict
            pickle.dump(cookies, f, protocol = 2)
            f.flush()
        os.replace(f.name, file_name)
        logger.debug("%s: state saved in %s", self.url, file_name)



    def state_wipe(self):
        """
        Delete state information for this server as created with
        :meth:`state_save`.
        """
        file_name = os.path.join(self.state_path,
                                 f"cookies-{self.url_safe}.pickle")
        commonl.rm_f(file_name)
        logger.info("%s: state deleted in %s", self.url, file_name)


    def login(self, username, password):
        try:
            self.send_request('PUT', "login",
                              data = {"email": username, "password": password})
            return True
        except requests.exceptions.HTTPError as e:
            if e.status_code // 100 != 2:
                logger.error("%s: login failed: %s", self.url, e)
            return False



    def logout(self, username = None):
        if username:
            self.send_request('DELETE', "users/" + username)
        else:
            # backwards compath
            self.send_request('PUT', "logout")
        logger.info("%s: logged out", self.url)



    def logged_in_username(self):
        """
        Return the user name logged into a server

        Based on the cookies, ask the server to translate the special name
        *self* to the currently logged in user with the cookies stored.

        :returns: name of the user we are logged in as
        """
        try:
            r = self.send_request("GET", "users/self")
            # this call returns a dictionary with the user name in the
            # key name, because we asked for "self", the server will
            # return only one, but maybe also fields with diagnostics, that
            # start with _; filter them
            for username in r:
                if not username.startswith("_"):
                    return username
            raise error_e(
                f"server can't translate user 'self'; got '{r}'")
        except (
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
                requests.urllib3.exceptions.MaxRetryError ) as e:
            if 'User unauthorized' in str(e):
                # HACK, need a better way
                return "n/a:need-login"
            raise block_e(
                f"server can't translate user 'self': {e}") from e
        except Exception as e:
            raise error_e(
                f"server can't translate user 'self': {e}") from e


    @staticmethod
    def _inventory_keys_update(server_inventory_keys, key, value, log = logging):
        if value == None:
            # in practice, we don't record None values, since this
            # means the value is not actually registered in the DB, so
            # skip it; these come from pieces in the code that still
            # haven't been moved to real-time DB and still rely on
            # tags
            return
        # we collect all the different keys we know in the
        # whole inventory (easier for the orchestrator) and
        # collect them in a unified list, with all the values
        # seen
        #
        # We only do this with the flat keys to avoid conflicts
        try:
            # FIXME: filter out _alloc.id, _alloc.queue.*
            #   bsps.x86_64.lcpu-N? .cpu-N?
            #   instrumentation.*.*?
            #   interconnects.XYZ. mhmmm
            #   *.instrument
            #   path
            if isinstance(value, dict):
                # dictionaries are stored as a boolean,
                # meaning the dictionary is present; subfields
                # will be listed as field.subfield.subsubfield...
                server_inventory_keys[key].add(True)
            elif isinstance(value, ( list, set, tuple )):
                # lists are just updated -- FIXME not sure if
                # this is the best idea
                server_inventory_keys[key].update(value)
            else:
                server_inventory_keys[key].add(value)
        except Exception as e:
            # shrug
            log.warning("can't collect inventory key '%s'"
                        " value (%s) '%s': %s",
                        key, type(value), value, e)



    def targets_get(self, target_id = None, projections = None):
        commonl.assert_none_or_list_of_strings(projections, "projections",
                                               "field name")

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
            server_inventory_keys = collections.defaultdict(set)

            def _rt_handle(target_id, rt):
                rt[target_id] = True
                fullid = self.aka + "/" + target_id
                rt[fullid] = True
                # this might get shortened later in
                # tcfl.targets.discovery_agent_c.update_complete(), so
                # also include field 'fullid_always' that is always
                # long
                rt['fullid'] = fullid
                rt['fullid_always'] = fullid
                # these are needed to later one be able to go from an
                # rt straight to the server
                rt['server'] = self.url
                rt['server_aka'] = self.aka
                server_rts[fullid] = rt
                server_rts_flat[fullid] = dict(rt)
                # Note the empty_dict!! it's important; we want to
                # keep empty nested dictionaries, because even if
                # empty, the presence of the key might be used by
                # clients to tell things about the remote target
                server_rts_flat[fullid].update(
                    commonl.dict_to_flat(rt, empty_dict = True))

            if projections:
                if isinstance(projections, set):
                    projections = list(projections)
                data = { 'projections': json.dumps(projections) }
            else:
                data = None
            # we do a short timeout here, so dead servers don't hold
            # us too long
            if target_id:
                r = self.send_request("GET", "targets/" + target_id,
                                      data = data, raw = True, timeout = 10)
                # when we are asking for a single target, we get
                #
                ## { FIELD: VALUE, ... }
                #
                # Keep the order -- even if json spec doesn't contemplate it, we
                # use it so the client can tell (if they want) the order in which
                # for example, power rail components are defined in interfaces.power
                rt = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
                _rt_handle(target_id, rt)
            else:
                r = self.send_request("GET", "targets/",
                                      data = data, raw = True, timeout = 10)
                # When asking for multiple targets, we get
                #
                ## { TARGETID1: { FIELD: VALUE, ... }, TARGETID2: ... }
                #
                # Keep the order -- even if json spec doesn't contemplate it, we
                # use it so the client can tell (if they want) the order in which
                # for example, power rail components are defined in interfaces.power
                r = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
                for target_id, rt in r.items():
                    _rt_handle(target_id, rt)
            # for this server, collect how many different keys and
            # values we have; server_rts_flat is keyed by target name;
            # each contains a dict of inventory key and value
            # NOTE: tcfl.ui_cli_targets._cmdline_help_fieldnames() has to
            # kinda do the same as this
            for _rtid, rt in server_rts_flat.items():
                for key, value in rt.items():
                    self._inventory_keys_update(server_inventory_keys, key, value)
            return server_rts, server_rts_flat, server_inventory_keys
        except requests.exceptions.RequestException as e:
            self._record_failure()
            log_sd.error("%s: can't use: %s", self.url, e)
            return {}, {}, {}



    def release(self, targetid: str, force: bool = False, ticket = ''):
        """Tell the server to release a target from its allocation

        :param str targetid: name of the target in the server

        :param bool force: (optional; default *False*) force releasing
          the target even if not the owner

        :param ticket: deprecated and ignored

        Note: this does not remove the allocation the target is in
        (see allocation removal FIXME:link for that), just removes the
        target from the allocation.
        """
        assert isinstance(targetid, str), \
            f"targetid: expected str, got {type(targetid)}"
        assert isinstance(force, bool), \
            f"force: expected boolstr, got {type(force)}"
        self.send_request(
            "PUT", f"targets/{targetid}/release",
            data = { 'force': force })



def assert_axes_valid(axes):
    """
    Verify an axes definition as specified in argument *axes* to
    :class:`target_role_c`.

    :param None,dict axes: axes to verify (or *None* if none)

    :raises: AssertionError on invalid specification
    """
    if axes == None:
        return
    assert isinstance(axes, dict), \
        f"axes: expected dictionary, got {type(axes)}"
    signature = inspect.signature(assert_axes_valid)
    for axes_name in signature.parameters:
        # get the first argument variable name, kinda tricky
        break
    for k, v in axes.items():
        assert isinstance(k, str), \
            f"'{axes_name}' needs to be a dict keyed by string;" \
            " got a key type '{type(k}}'; expected string"
        assert v == None or isinstance(v, ( list, set, tuple )), \
            f"'{axes_name}' axis {k} value shall be " \
            " None or a list to spin on; got a key type '{type(k}}'"



class target_role_c:
    """
    Describe a target that is needed for a testcase

    :param str role: name of this target's role (eg: *server*,
      *client*); for most simple cases that only need one target it is
      *target*. If it is a network, then *network* or *ic* (interconnect).

    :param str origin: (optional) where is this the need for this
      target role declared (normally as a *FILENAME[:LINENUMBER]*).

    :param dict axes: (optional) dictionary keyed by string of the
      axes on which to spin this target role (see :ref:`testcase
      pairing testcase_pairing`).

      >>> dict(
      >>>     AXISNAME = [ VALUE0, VALUE 1... ],
      >>>     AXISNAME = None,
      >>> ...)

      The key name is the axis name, which as to be a valid Python
      identifier and the values are *None* (to get all the values
      from a field named as the axis in the inventory) or a list of
      values valid axis values (which an be *bool*, *int*, *float* or
      *str*).

      Note that when getting the values from the inventory, only
      values that apply to a target that matches the *spec* will
      be considered [*ic_spec* is ignored for this].

      See :ref:'axis specification <axis_specification>` for more
      information

    :param str,callable spec: (optional) target specification
      filter--used to filter which targets are acceptable for this
      role.

      This can be a string describing a logical expression or a
      function that does the filtering; the function *MUST* be
      not depend on global data other than the target inventory
      and be estable over calls, since its results will be cached.

      See :ref:'target filtering <target_filtering>` for more
      information

      FIXME: the function needs to be available on the core TCFL
      image, not on the testcase definition, otherwise it needs to be
      pickled?

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

    :param bool interconnects: if *True* consider, consider this
      role as an interconnect, a target that interconnects other
      targets (eg: a network).

    """
    def __init__(self, role: str,
                 origin: str = None,
                 axes: dict = None,
                 spec = None,			# FIXME: spec str|callable
                 spec_args = None,
                 ic_spec = None,                # FIXME: spec str|callable
                 ic_spec_args: dict = None,
                 interconnect: bool = False):
        assert isinstance(role, str)
        assert origin == None or isinstance(origin, str)
        # FIXME: properly verify this
        assert spec == None or isinstance(spec, str) or callable(spec)
        assert spec_args == None or isinstance(spec_args, dict)
        assert ic_spec == None or callable(ic_spec)
        assert ic_spec_args == None or isinstance(ic_spec_args, dict)
        assert isinstance(interconnect, bool), \
            f"interconnect: expected boolean, got {type(interconnect)}"

        self.role = role
        self.origin = origin
        if axes == None:
            self.axes = {}	# so iterators need no extra checks
        else:
            assert_axes_valid(axes)
            self.axes = axes
        # FIXME: pre-compile if text?
        self.spec = spec
        self.spec_args = spec_args
        self.ic_spec = ic_spec
        self.ic_spec_args = ic_spec_args
        self.interconnect = interconnect


    def __repr__(self):
        return self.role



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
    # thus, keep it very simple
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
        if axes == None:
            self.axes = {}	# so iterators need no extra checks
        else:
            assert_axes_valid(axes)
            self.axes = axes

        # see tcfl.orchestrate.executor_c._axes_expand_testcase();
        #
        # these are all the axes (from the testcase and the testcase
        # roles) and they are always sorted the same so we can
        # reproduce the pseudo-random sequences.
        #
        # FIXME: move all .axes to ._axes; move to orchestrator, as
        #        this is orchestrator internal
        self._axes_all = collections.OrderedDict()
        self._axes_all_mr = None

        if target_roles != None:
            commonl.assert_dict_of_types(target_roles, "target_roles",
                                         target_role_c)
            self.target_roles = target_roles
        else:
            self.target_roles = {}
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
        #: >>> formatted_traceback = traceback.format_tb(sys.exc_info()[2])
        #: >>> formatted_traceback = traceback.format_stack()
        #
        #: Do not use
        #:
        #: >>> formatted_traceback = traceback.format_exc()
        #:
        #: somehow it just returns a string and messes everything up.
        #:
        self.formatted_traceback = formatted_traceback


        # How many axes permutations are to be considered (doc in
        # axes_permutations)
        self._axes_permutations = 0

        #: How are we randomizing the axes permutations (str: *random*,
        #: *sequential*; any other string is a seed to a randomizer).
        self._axes_randomizer = "random"


        # method to filter axes permutations
        self._axes_permutation_filter = None


        #
        # Orchestrator specific area
        #
        # The data in this area is initialized / used by the
        # orchestrator (eg: tcfl/orchestrate.py or others); it is
        # initiailized by the orchestrator.
        #
        # By default is kept uninitialized so this object can be
        # pickled to pass it from the testcase discovery process to
        # the orchestrating engine.
        #

        self.log = None

        # initialized by the orchestrator based on self._axes_randomizer
        self._axes_randomizer_impl = None



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
        What kind of randomization is to be done to sequence axes values?

        See :ref:`execution modes <execution_modes>` for more information.

        :getter: return the current randomizer
          (:class:`random.Random` or *None* for sequential execution).

        :setter: sets the randomizer:

          - *None* or (str) *sequential* for sequential execution

          - *random* (str) constructs a default random device
            :class:`random.Random`.

          - *SEED* (str) any random string which will used as seed to
            construct a :class:`random.Random` object

        :type: :class:`random.Random`
        """
        return self._axes_randomizer


    @axes_randomizer.setter
    def axes_randomizer(self, r = "random"):
        assert isinstance(r, str)
        self._axes_randomizer = r
        return self._axes_randomizer


    @property
    def axes_permutation_filter(self):
        """Set an axes permutation filter

        By default, no filtering is done (this is *None*); otherwise,
        set to the name of a filter registerd with
        :meth:`tcfl.orchestrate.axes_permutation_filter_register` in
        any :ref:`TCF configuration file <tcf_client_configuration>`

        See :meth:`tcfl.orchestrate.axes_permutation_filter_register`
        for how to implement filters.

        FIXME: not clarified Setting mechanisms (needed except when
        creating the method called *axes_permutation_filter*):

        - :func:`tcfl.tc.execution_mode` decorator, argument *axes_permutation_filter*

        """
        return self._axes_permutation_filter


    @axes_permutation_filter.setter
    def axes_permutation_filter(self, f):
        assert isinstance(f, str)
        self._axes_permutation_filter = f
        return self._axes_permutation_filter




    def report_info(self, msg, **kwargs):
        # HACK
        self.log.info(msg + str(kwargs))


# we don't need too much logging level from this
logging.getLogger("filelock").setLevel(logging.CRITICAL)

# add a server "ttbd" which the admins can initialize by just aliasing
# DNS and this triggers all servers auto-discovering.
server_c.seed_add(
    "ttbd", port = 5000, ssl_verify = False,
    origin = f"defaults @{commonl.origin_get()}")
