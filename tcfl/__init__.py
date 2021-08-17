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
import subprocess
import sys
import traceback
import threading

import commonl


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

    def report(self, tc, message, attachments = None,
               level = None, dlevel = 0, alevel = 2):
        assert isinstance(tc, tc_c)
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
            reporter = tc

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

    def attachments_get(self):
        return self.args[1]

    def attachments_update(self, d):
        """
        Update an exception's attachments
        """
        assert isinstance(d, dict)
        self.args[1].update(d)

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
