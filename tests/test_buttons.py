#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target("t0")
class _test(tcfl.tc.tc_c):

    """Some basic button exercising

    Target configured with two buttons which are to be released upon
    power on and power off and one of them pressed 5s to power the
    target on, 10s to power it off.

    """


    @staticmethod
    def eval(target):
        ts0 = time.time()
        target.power.off()
        ts = time.time()
        if ts - ts0 < 10 or ts - ts0 > 12:
            raise tcfl.tc.failed_e(
                "power off took %.1fs, expected around 10" % (ts - ts0))
        target.report_pass("powered off in %.1fs, as expected" % (ts - ts0))

        r = target.button.list()
        for button in [ 'reset', 'power' ]:
            if button not in r:
                raise tcfl.tc.failed_e(
                    "didn't get expected state info for button '%s'" % button,
                    dict(r = r))
            if r[button] != False:
                raise tcfl.tc.failed_e(
                    "button '%s' not in expected released (False) state" % button,
                    dict(r = r))

        target.report_pass('all buttons in expected state after power off',
                           dict(r = r))

        ts0 = time.time()
        target.power.on()
        ts = time.time()
        if ts - ts0 < 5 or ts - ts0 > 7:
            raise tcfl.tc.failed_e(
                "power on took %.1fs, expected around 5" % (ts - ts0))
        target.report_pass("powered on in %.1fs, as expected" % (ts - ts0))

        r = target.button.list()
        for button in [ 'reset', 'power' ]:
            if button not in r:
                raise tcfl.tc.failed_e(
                    "didn't get expected state info for button '%s'" % button,
                    dict(r = r))
            if r[button] != False:
                raise tcfl.tc.failed_e(
                    "button '%s' not in expected released (False) state" % button,
                    dict(r = r))

        target.report_pass('all buttons in expected state after power on',
                           dict(r = r))

        target.button.press("reset")
        target.button.release("reset")
        ts0 = time.time()
        target.button.sequence([
            ( "release", "power"),
            ( "press", "reset"),
            ( "wait", 5 ),
            ( "release", "reset")
        ])
        ts = time.time()
        if ts - ts0 < 5 or ts - ts0 > 7:
            raise tcfl.tc.failed_e(
                "sequence took %.1fs, expected around 5" % (ts - ts0))
        target.report_pass("sequence took %.1fs, as expected" % (ts - ts0))

        r = target.button.list()
        for button in [ 'reset', 'power' ]:
            if button not in r:
                raise tcfl.tc.failed_e(
                    "didn't get expected state info for button '%s'" % button,
                    dict(r = r))
            if r[button] != False:
                raise tcfl.tc.failed_e(
                    "button '%s' not in expected released (False) state" % button,
                    dict(r = r))

        target.report_pass('all buttons in expected state after sequence',
                           dict(r = r))

        ts0 = time.time()
        target.button.click("reset", click_time = 5)
        ts = time.time()
        if ts - ts0 < 5 or ts - ts0 > 7:
            raise tcfl.tc.failed_e(
                "click took %.1fs, expected around 5" % (ts - ts0))
        target.report_pass("click took %.1fs, as expected" % (ts - ts0))

        r = target.button.list()
        for button in [ 'reset', 'power' ]:
            if button not in r:
                raise tcfl.tc.failed_e(
                    "didn't get expected state info for button '%s'" % button,
                    dict(r = r))
            if r[button] != False:
                raise tcfl.tc.failed_e(
                    "button '%s' not in expected released (False) state" % button,
                    dict(r = r))

        target.report_pass('all buttons in expected state after click',
                           dict(r = r))
        ts0 = time.time()
        target.button.double_click("reset", click_time = 2, interclick_time = 1)
        ts = time.time()
        if ts - ts0 < 5 or ts - ts0 > 7:
            raise tcfl.tc.failed_e(
                "double click took %.1fs, expected around 5" % (ts - ts0))
        target.report_pass("double click took %.1fs, as expected" % (ts - ts0))

        r = target.button.list()
        for button in [ 'reset', 'power' ]:
            if button not in r:
                raise tcfl.tc.failed_e(
                    "didn't get expected state info for button '%s'" % button,
                    dict(r = r))
            if r[button] != False:
                raise tcfl.tc.failed_e(
                    "button '%s' not in expected released (False) state" % button,
                    dict(r = r))

        target.report_pass('all buttons in expected state after double click',
                           dict(r = r))


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
