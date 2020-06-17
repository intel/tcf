#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

@tcfl.tc.target("t0")
class _test(tcfl.tc.tc_c):
    """
    Exercise the power/sequence call
    """
    def eval(self, target):
        try:
            target.power.sequence()
            raise tcfl.tc.failed_e(
                "sequence() didn't raise TypeError on having no arguments")
        except TypeError as e:
            self.report_pass("sequence() complains ok about no arguments")

        for bad_argument in [
                # yeah, there might be a smarter way to define this
                # ugly list
                1, 'some string', dict(), 2.0, True, False,
                [ ( 'wait' ) ],
                [ ( 'wait', None ) ],
                # turns out True and False map to 1 and 0 in Python...
                #[ ( 'wait', True ) ],
                #[ ( 'wait', False ) ],
                [ ( 'wait', 'string' ) ],
                [ ( 'wait', [ ] ) ],
                [ ( 'wait', dict() ) ],
                [ ( 'wait', {} ) ],
                [ ( 'wait', () ) ],
                # on operation
                [ ( 'on' ) ],
                [ ( 'on', None ) ],
                [ ( 'on', True ) ],
                [ ( 'on', False ) ],
                [ ( 'on', [ ] ) ],
                [ ( 'on', dict() ) ],
                [ ( 'on', {} ) ],
                [ ( 'on', () ) ],
                [ ( 'on', 1 ) ],
                [ ( 'on', 1.0 ) ],
                # off operation
                [ ( 'off' ) ],
                [ ( 'off', None ) ],
                [ ( 'off', True ) ],
                [ ( 'off', False ) ],
                [ ( 'off', [ ] ) ],
                [ ( 'off', dict() ) ],
                [ ( 'off', {} ) ],
                [ ( 'off', () ) ],
                [ ( 'off', 1 ) ],
                [ ( 'off', 1.0 ) ],
                # cycle operation
                [ ( 'cycle' ) ],
                [ ( 'cycle', None ) ],
                [ ( 'cycle', True ) ],
                [ ( 'cycle', False ) ],
                [ ( 'cycle', [ ] ) ],
                [ ( 'cycle', dict() ) ],
                [ ( 'cycle', {} ) ],
                [ ( 'cycle', () ) ],
                [ ( 'cycle', 1 ) ],
                [ ( 'cycle', 1.0 ) ],
                # other things
                [ ( 'invalid', None ) ],
                [ ( 'invalid', True ) ],
                [ ( 'invalid', False ) ],
                [ ( 'invalid', [ ] ) ],
                [ ( 'invalid', dict() ) ],
                [ ( 'invalid', {} ) ],
                [ ( 'invalid', () ) ],
                [ ( 'invalid', 1 ) ],
                [ ( 'invalid', 1.0 ) ],

        ]:
            try:
                target.power.sequence(bad_argument)
                raise tcfl.tc.failed_e(
                    "sequence() didn't raise error on bad argument %s"
                    % bad_argument)
            except tcfl.tc.error_e as e:
                self.report_pass(
                    "server's sequence() complains ok about bad argument %s"
                    % bad_argument, dict(exception = e))
                # "t0: power/sequence: remote call failed: 400: t0: t0: sequence #0: invalid type: expected list; got <type 'unicode'>"
                # ->
                # "invalid type: expected list; got <type 'unicode'>"
                #
                # so we can ignore it in the server's error log, which
                # doesn't contain the part we are removing (added by
                # the client)
                ttbd.errors_ignore.append(
                    re.sub("^.*remote call failed.*sequence", "",
                           str(e.args[0])))

        # now test basic operation
        ts0 = time.time()
        target.power.sequence([ ( 'wait', 3 ) ])
        ts = time.time()
        if ts - ts0 < 3:
            raise tcfl.tc.failed_e(
                "wait 3s took less than 3 seconds (%.1fs)" % ts-ts0)
        if ts - ts0 > 3.5:
            raise tcfl.tc.failed_e(
                "wait 3s took less than 3.5 seconds (%.1fs)" % ts-ts0)

        # now test basic operation
        ts0 = time.time()
        target.power.sequence([ ( 'wait', 3 ) ])
        ts = time.time()
        if ts - ts0 < 3:
            raise tcfl.tc.failed_e(
                "wait 3s took less than 3 seconds (%.1fs)" % ts-ts0)
        if ts - ts0 > 3.5:
            raise tcfl.tc.failed_e(
                "wait 3s took less than 3.5 seconds (%.1fs)" % ts-ts0)

        target.power.sequence([ ( 'on', 'power0' ) ])
        state, substate, components = target.power.list()
        assert components['power0']['state'] == True, components
        target.power.sequence([ ( 'off', 'power0' ) ])
        state, substate, components = target.power.list()
        assert components['power0']['state'] == False, components
        target.power.sequence([ ( 'cycle', 'power0' ) ])
        state, substate, components = target.power.list()
        assert components['power0']['state'] == True, components

        target.power.sequence([ ( 'off', 'all' ) ])
        state, substate, components = target.power.list()
        assert state == False, ( state, substate, components )
        assert substate == 'full', ( state, substate, components )

        target.power.sequence([ ( 'on', 'all' ) ])
        state, substate, components = target.power.list()
        assert state == True, ( state, substate, components )
        assert substate == 'full', ( state, substate, components )

        target.power.sequence([
            ( 'off', 'all' ),
            ( 'wait', 1 ),
            ( 'on', 'power0' ),
            ( 'on', 'power1' ),
            ( 'on', 'power2' ),
            ( 'off', 'power1' ),
        ])
        state, substate, components = target.power.list()
        assert components['power0']['state'] == True, components
        assert components['power1']['state'] == False, components
        assert components['power2']['state'] == True, components


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
