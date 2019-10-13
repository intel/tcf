#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""\
Expecting things that have to happen
====================================

This module implements an *expecter* object: something that is told to
expect things to happen, what to do when they happen (or not).

It is a combination of a poor man's select() and Tk/Tcl Expect.

We cannot use select() or Tk/TCL Expect or Python's PyExpect because:

- we need to listen to many things over HTTP connections and the
  library is quite very simplistic in that sense, so there is maybe no
  point on hooking up a pure event system.

- we need to be able to listen to poll for data and evaluate it from
  one or more sources (like serial port, sensor, network data,
  whatever) in one or more targets all at the same time.

- it is simple, and works quite well

Any given testcase has an `expecter` object associated with it that
can be used to wait for a list of events to happen in one or more
targets. This allows, for example, to during the execution of a
testcase with multiple nodes, to always have pollers reading (eg)
their serial consoles and evaluators making sure no kernel panics are
happening in none while at the same time checking for the output that
should be coming from them.

The 'expecter' object can be also associated just to a single target
for a more simple interface when only access to one target is needed.
"""
import contextlib
import hashlib
import mmap
import os
import re
import time
import traceback

import requests.exceptions

import commonl
import tc
import tcfl

class expecter_c(object):
    """Object that is told to expect things to happen and what to do when
    they happen (or

    When calling :py:meth:`run`, a loop is called by that will run
    repeatedly, waiting :py:data:`poll_period` seconds in between
    polling periods until a given :py:data:`timeout` ellapses.

    On each loop run, a bunch of functions are run. Functions are
    added with :py:meth:`add` and removed with :py:meth:`remove`.

    Each function polls and stores data, evals said data or both. It
    can then end the loop by raising an exception. It is also possible
    that nothing of the interest happened and thus it won't cause the
    loop to end.  thus it will evaluate nothing. See :py:meth:`add`
    for more details

    Some of those functions can be considered 'expectations' that have
    to pass for the full loop to be considered succesful. An boolean
    to :py:meth:`add` clarifies that. All those 'expectations' have to
    pass before the run can be considered succesful.

    The loop will timeout if no evaluating function raises an exception to
    get out of it and fail with a timeout.

    **Rationale**

    This allows to implement simple usages like waiting for something to
    come off any console with a default

    >>> target.wait('STRING', TIMEOUT, console = None)

    which also check for other things we know that can come from the OS in
    a console, like abort strings, kernel panics or dumps for which new
    know we should abort inmediately with an specific message.


    FIXME:

    it has to be easy to use and still providing things like

    >>> target.wait('STRING', TIMEOUT, console = None) -> { True | False }
    >>>    target.expecter.add(console_rx, (STRING, console),)
    >>> target.expect('STRING', TIMEOUT) -> raise error/fail/block
    >>> target.on_rx('STRING', raise failure function)

    """
    def __init__(self, log, testcase, poll_period = 0.25, timeout = 30):
        self._log = log
        #: Time in seconds the :py:meth:`run` function waits before
        #: calling all the polling/evaluation functions
        self.poll_period = poll_period
        #: Time in seconds the :py:meth:`run` will consider we have
        #: timed out if no polling/evaluation function raises an
        #: exception to complete the loop
        self.timeout = timeout
        #: List of functions to call for poll and evaluation; this is
        #a list so there is a set order.
        self.functors = []
        #: dictionary for poll/eval functions to store data from run
        #: to run of the loop that can be examined for evaluation;
        #: will be cleared every time the :py:func:`run` function is
        #: called.
        self.buffers = {}
        #: Each this many seconds, touch the targets to indicate the
        #: server we are actively using them (in case the pollers are
        #: not polling every target)
        self.active_period = 20
        #: dictionary for poll/eval functions to store data from run
        #: to run of the loop that can be examined for evaluation;
        #: will NOT be cleared every time the :py:func:`run` function is
        #: called.
        self.buffers_persistent = {}
        #: Number of expectations that have to pass for a run to be
        #: successful
        self.have_to_pass = 0
        self.testcase = testcase
        #: Time base, to calculate relative timestamps; when we call
        #: run(), we reinitialized it, but we also set it here for when
        #: we call the poller outside of run()
        self.ts0 = time.time()
        self._consoles = set()

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        if timeout <= 0:
            raise ValueError("timeout has to be greater than 0")
        self._timeout = timeout

    @property
    def poll_period(self):
        return self._poll_period

    @poll_period.setter
    def poll_period(self, poll_period):
        if poll_period <= 0:
            raise ValueError("poll_period has to be greater than 0")
        self._poll_period = poll_period

    def console_get_file(self, target, console = None):
        """
        :returns: file descriptor for the file that contains the
          currently read console.

        Note the pointer in this file descriptor shall not be modified
        as it might be being used by expectations. If you need to read
        from the file, dup it:

        >>> f_existing = self.tls.expecter.console_get_file(target, console_id)
        >>> f = open(f_existing.name)
        """
        _, console_code = console_mk_code(target, console)
        return self.buffers.get(console_code, None)

    def add(self, has_to_pass, functor, arguments, origin = None):
        """Add a function to the list of things to poll/evaluate

        These functions shall either poll, evaluate or both:

        - poll data and store it in the dictionary or anywhere else
          where it can be accessed later. Use a unique key into the
          dictorionary :py:data:`buffers`.

        - evaluate some previously polled data or whichever system
          condition and raise an exception to indicate what happened
          (from the set :exc:`tcfl.tc.pass_e`,
          :py:exc:`tcfl.tc.blocked_e`,
          :py:exc:`tcfl.tc.error_e`,
          :py:exc:`tcfl.tc.failed_e`,
          :py:exc:`tcfl.tc.skip_e`).

        Eval functions can check their own timeouts and raise an
        exception to signal it (normally
        :py:exc:`tcfl.tc.error_e`)

        It is also possible that nothing of the interest of this
        evaluation function happened and thus it will evaluate
        nothing.

        :param bool has_to_pass: In order to consider the whole expect
          sequence a pass, this functor has to declare its evaluation
          passes by returning anything but `None` or by raising
          :py:exc:`tcfl.tc.pass_e`.

        :raises: to stop the :py:meth:`run` loop, raise
          :py:exc:`tcfl.tc.pass_e`,
          :py:exc:`tcfl.tc.blocked_e`,
          :py:exc:`tcfl.tc.error_e` or
          :py:exc:`tcfl.tc.skip_e`.

        :returns: ignored

        """
        if not origin:
            origin = tcfl.origin_get(1)
        setattr(functor, "origin", origin)
        if not (functor, arguments, has_to_pass) in self.functors:
            self.functors.append((functor, arguments, has_to_pass))
            if has_to_pass:
                self.have_to_pass += 1
            return True
        else:
            return False


    def remove(self, functor, arguments):
        count = 0
        for f, a, has_to_pass in self.functors:
            if f == functor and a == arguments:
                if has_to_pass:
                    self.have_to_pass -= 1
                del self.functors[count]
                break
            count += 1

    def log(self, msg, attachments = None):
        self._log(msg, attachments)

    def run(self, timeout = None):
        """\
        Run the expectation loop on the testcase until all
        expectations pass or the timeout is exceeded.

        :param int timeout: (optional) maximum time to wait for all
          expectations to be met (defaults to
          :attr:`tcfl.expecter.expecter_c.timeout`)
        """
        if timeout == None:
            timeout = self._timeout
        else:
            assert isinstance(timeout, int)
        # Fresh start
        self.buffers.clear()
        self.ts0 = time.time()
        _active_ts = self.ts0
        functors_pending = self.functors
        while True:
            ts = time.time()
            td = ts - self.ts0
            _functors_pending = list(functors_pending)

            for f, a, has_to_pass in _functors_pending:
                if a == None:
                    args = (self,)
                else:
                    args = (self, ) + a
                try:
                    self._log(
                        "running %s %s @%s" % (f.__name__, f.origin, args),
                        dlevel = 5)
                    _ts0 = time.time()
                    r = f(*args)
                    _ts1 = time.time()
                except tc.pass_e as e:
                    if has_to_pass:
                        # Report pass information, including attachments
                        tc.result_c.report_from_exception(self.testcase, e)
                        r = True

                # Once it passes, we don't check it anymore
                if has_to_pass and r != None:
                    self.remove(f, a)
                    # if this returned normally or raised a tc.pass_e,
                    # then it means the test passed; except if it
                    # returns None, then ignore it (might have
                    # been a poller)
                    if self.have_to_pass == 0:
                        raise tc.pass_e("all expectations found")

            # Check like this because we want to run the check
            # functions before determining a timeout as some of them
            # might also check on their own and offer better messages
            if td >= self.timeout:
                raise tc.error_e("Timed out (%.2fs)" % self.timeout)
            if ts - _active_ts > self.active_period:
                self.testcase._targets_active()
                _active_ts = ts
            time.sleep(self._poll_period)

    def power_on_post(self, target = None):
        """
        Reinitialize things that need flushing for a new power on
        """
        for _target, _console in self._consoles:
            if target == None or target == _target:
                console_rx_flush(self, _target, _console, True)

def console_mk_code(target, console):
    # This mimics console_rx_eval
    console_id_name = "default" if console in (None, "") else console
    return console_id_name, "console-rx-" + \
        commonl.file_name_make_safe(target.fullid) + "-" + console_id_name

def console_mk_uid(target, what, console, _timeout, result):
    # Create a unique identifier for this evaluator, we'll use it to
    # save the offset at which we are reading
    huid = hashlib.sha256()		# No need for crypto strength
    huid.update(target.fullid)
    huid.update(what)
    huid.update("%s" % console)
    huid.update("%s" % _timeout)
    huid.update("%s" % result)
    return huid.hexdigest()

def console_rx_poller(expecter, target, console = None):
    """
    Poll a console
    """
    # Figure out to which file we are writing
    console_id_name, console_code = console_mk_code(target, console)
    of = expecter.buffers.setdefault(
        console_code,
        open(os.path.join(target.testcase.buffersdir,
                          "console-%s:%s-%s.log" % (
                              commonl.file_name_make_safe(target.fullid),
                              target.kws['tc_hash'], console_id_name)),
             "a+", 0))
    ofd = of.fileno()
    expecter.buffers.setdefault(console_code + "-ts0", time.time())

    # Don't read too much, leave the rest for another run -- otherwise
    # we could spend our time trying to read a 1G console log file
    # from a really broken test case that spews a lot of stuff.
    # FIXME: move this to configuration
    max_size = 3000

    # Read anything new since the last time we read -- this relies
    # on we having an exclusive lock on the target
    try:
        offset = os.fstat(ofd).st_size
        ts_start = time.time()
        target.report_info("reading from console %s @%d at %.2fs [%s]"
                           % (console_id_name, offset,
                              ts_start - expecter.ts0, of.name),
                           dlevel = 3)
        # We are dealing with a file as our buffering and accounting
        # system, so because read_to_fd() is bypassing caching, flush
        # first and sync after the read.
        of.flush()
        total_bytes = target.console.read(console = console, offset = offset,
                                          max_size = max_size, fd = of)
        of.flush()
        os.fsync(ofd)
        ts_end = time.time()
        target.report_info("read from console %s @%d %dB at %.2fs (%.2fs) "
                           "[%s]"
                           % (console_id_name, offset, total_bytes,
                              ts_end - expecter.ts0, ts_end - ts_start,
                              of.name),
                           dlevel = 3)
        # FIXME: do we want to print some debug of what we read? how
        # do we do it for huge files anyway?
        expecter._consoles.add(( target, console ))

    except requests.exceptions.HTTPError as e:
        raise tc.blocked_e("error reading console %s: %s\n"
                           % (console_id_name, e),
                           { "error trace": traceback.format_exc() })
    # Don't count this as something that we need to treat as succesful
    return None

def console_rx_flush(expecter, target, console = None, truncate = False):
    """
    Reset all the console read markers to 0

    When we (for example) power cycle, we start capturing from zero,
    so we need to reset all the buffers of what we read.
    """
    console_rx_poller(expecter, target, console)
    _, console_code = console_mk_code(target, console)
    of = expecter.buffers.get(console_code, None)
    if of == None:
        return
    if truncate:
        of.truncate(0)
        new_offset = 0
    else:
        ofd = of.fileno()
        new_offset = os.fstat(ofd).st_size
    offset_code = "offset_" + console_code
    expecter.buffers_persistent[offset_code] = new_offset

def console_rx_eval(expecter, target,
                    regex, console = None, _timeout = None, result = None,
                    uid = None):
    """
    Check what came on a console and act on it

    :param str uid: (optional) identifier to use to store offset data
    """

    if hasattr(regex, "pattern"):
        what = regex.pattern
    else:
        what = regex
        regex = re.compile(re.escape(regex))

    if not uid:
        uid = console_mk_uid(target, what, console, _timeout, result)

    console_id_name, console_code = console_mk_code(target, console)
    # These were set by the poller
    of = expecter.buffers.get(console_code, None)
    if of == None:
        # FIXME: debug lof output here? expecter->tc backlink?
        return None
    ofd = of.fileno()
    ts = time.time()

    # Get the offset we saved before as the last part where we looked
    # at. If none, then get the last offset the poller has
    # recorded. Otherwise, just default to look from the start
    # Note the idea is each eval function has a different offset where
    # it is looking at. Likewise the poller for each console.
    offset_poller_code = "offset_" + console_code
    offset = expecter.buffers_persistent.get(
        uid,
        expecter.buffers_persistent.get(offset_poller_code, 0))
    if _timeout != False:
        timeout = expecter.timeout if _timeout == None else _timeout

        # We can do timeout checks that provide better information
        # than a generic 'timeout'
        if ts - expecter.ts0 > timeout:
            of.seek(offset)	# so we report console from where searched
            raise tc.error_e(
                "expected console output '%s' from console '%s:%s' " \
                "NOT FOUND after %.1f s" \
                % (what, target.id, console_id_name, ts - expecter.ts0),
                { 'target': target, "console output": of })

    # mmap the whole file (which doesn't alter the file pointer)
    #
    # We have to mmap as the file might be getting huge and thus,
    # reading line by line might be dumb.
    #
    # However, we only search starting at @offset, which is set later
    # to the last success searching we had. So we shan't really map
    # the whole file, shall map on demand.

    stat_info = os.fstat(ofd)
    if stat_info.st_size == 0:	# Nothing to read
        return None

    with contextlib.closing(mmap.mmap(of.fileno(), 0, mmap.MAP_PRIVATE,
                                      mmap.PROT_READ, 0)) as mapping:
        target.report_info("looking for `%s` in console %s:%s @%d-%d at "
                           "%.2fs [%s]"
                           % (what, target.fullid, console_id_name, offset,
                              stat_info.st_size, ts - expecter.ts0, of.name),
                           dlevel = 3)
        m = regex.search(mapping[offset:])
        if m:
            new_offset = offset + m.end()
            expecter.buffers_persistent[uid] = new_offset
            if result == None or result == "pass":
                # raising pass gets stopped at expecter.run(), so we
                # print instead, so we can see the console
                of.seek(offset)	# so we report console from where searched
                target.report_pass(
                    "found expected `%s` in console `%s:%s` at %.2fs @%d"
                    % (what, target.fullid, console_id_name,
                       ts - expecter.ts0, offset + m.start()),
                    { "console output": of }, dlevel = 4, alevel = 2)
                raise tc.pass_e(
                    "found expected `%s` in console `%s:%s` at %.2fs"
                    % (what, target.fullid, console_id_name,
                       ts - expecter.ts0),
                    {'target': target })
            elif result == "fail":
                of.seek(offset)	# so we report console from where searched
                raise tc.failed_e(
                    "found expected (for failure) `%s` in console "
                    "`%s:%s` at %.2fs"
                    % (what, target.fullid, console_id_name,
                       ts - expecter.ts0),
                    { 'target': target, "console output": of })
            elif result == "error" or result == "errr":
                of.seek(offset)	# so we report console from where searched
                raise tc.error_e(
                    "found expected (for error) `%s` in console "
                    "`%s:%s` at %.2fs"
                    % (what, target.fullid, console_id_name,
                       ts - expecter.ts0),
                    { 'target': target, "console output": of })
            elif result == "skip":
                of.seek(offset)	# so we report console from where searched
                raise tc.skip_e(
                    "found expected (for skip) `%s` in console "
                    "'%s:%s' at %.2fs"
                    % (what, target.fullid, console_id_name,
                       ts - expecter.ts0),
                    { 'target': target, "console output": of })
            else:
                of.seek(offset)	# so we report console from where searched
                raise tc.blocked_e(
                    "BUG: invalid result requested (%s)" % result)
    return None
