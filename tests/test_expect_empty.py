#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import time
import tcfl.tc

class _none(tcfl.tc.tc_c):
    """
    When expecting nothing, we we still get the top level timeout
    """

    def eval(self):

        ts0 = time.time()
        r = self.expect(timeout = 3)
        ts = time.time()
        assert ts - ts0 >= 3 and ts - ts0 - 3 < 0.5, \
            "empty wait of three seconds took %.fs instead" % (ts - ts0)
        assert r == {}, \
            "expected empty r, got %s" % r
        self.report_pass("empty expect took expected %.fs" % (ts - ts0),
                         dict(r = r))

class _delay_expectation_c(tcfl.tc.expectation_c):
    """
    Expectator for tcfl.tc.expect() that just delays @delay seconds
    before returning success in detecting
    """
    def __init__(self, delay, **kwargs):
        # we rely on a short poll period to adjust the timeouts below
        tcfl.tc.expectation_c.__init__(self, None, 0.1, **kwargs)
        self.delay = delay

    def poll_context(self):
        return ""

    def poll(self, testcase, run_name, buffers_poll):
        # first time we poll, take a timestamp
        if buffers_poll.get('ts0', None) == None:
            buffers_poll['ts0'] = time.time()

    def detect(self, testcase, run_name, buffers_poll, buffers):
        ts0 = buffers_poll['ts0']
        ts = time.time()
        if ts - ts0 > self.delay:
            testcase.report_pass("%s: detected after %.fs" % (
                self.name, ts - ts0))
            return { "message": "detected after %.fs" % (ts - ts0) }
        return None

    def flush(self, testcase, run_name, buffers_poll, buffers, results):
        pass


class _all_zero_timeouts(tcfl.tc.tc_c):
    """
    When waiting for multiple zero timeouts, we still get the top
    level timeout
    """
    def eval(self):

        ts0 = time.time()
        r = self.expect(
            _delay_expectation_c(1, timeout = 0),
            _delay_expectation_c(2, timeout = 0),
            # note we won't get to detect this one because we timeout
            # right at 3 seconds
            _delay_expectation_c(3, timeout = 0),
            _delay_expectation_c(4, timeout = 0),
            _delay_expectation_c(5, timeout = 0),
            timeout = 3)
        ts = time.time()
        assert ts - ts0 >= 3 and ts - ts0 - 3 < 0.5, \
            "empty wait of three seconds took %.fs instead" % (ts - ts0)
        assert len(r) == 2, \
            "expected two expectations found, got %d (%s)" % (len(r), r)
        self.report_pass("empty expect took expected %.fs" % (ts - ts0),
                         dict(r = r))


class _mix_zero_timeouts(tcfl.tc.tc_c):
    """
    When waiting for a combination of zero timeouts and non-zero
    timeouts, it returns the first found expectation.
    """
    def eval(self):

        ts0 = time.time()
        r = self.expect(
            _delay_expectation_c(3, timeout = 3.5),
            _delay_expectation_c(10, timeout = 0),
            timeout = 5)
        ts = time.time()
        assert len(r) == 1, \
            "expected one delays found, got %s" % r
        assert ts - ts0 >= 3 and ts - ts0 - 3 < 0.5, \
            "expect expected of 3 seconds, took %.fs instead" % (ts - ts0)
        self.report_pass("expect took expected %.fs and returned "
                         "%d detected expectation" % (ts - ts0, len(r)),
                         dict(r = r))

class _no_zero_timeouts(tcfl.tc.tc_c):
    """
    When waiting for a combination of zero timeouts and non-zero
    timeouts, it returns the first found expectation.
    """
    def eval(self):

        ts0 = time.time()
        r = self.expect(
            _delay_expectation_c(1, timeout = 3.5),
            _delay_expectation_c(2, timeout = 3.5),
            _delay_expectation_c(3, timeout = 3.5),
            timeout = 3.5)
        ts = time.time()
        assert len(r) == 3, \
            "expected two delays found, got %s" % r
        assert ts - ts0 >= 3 and ts - ts0 - 3 < 0.5, \
            "expect expected of 3 seconds, took %.fs instead" % (ts - ts0)
        self.report_pass("expect took expected %.fs and returned "
                         "%d detected expectation" % (ts - ts0, len(r)),
                         dict(r = r))
