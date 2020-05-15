#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import pprint

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target("t0")
class _test(tcfl.tc.tc_c):
    """
    Test that explicity vs normal power components follow the rules
    when executing power on/off sequences.
    """
    def eval(self, target):
        # power ALL off
        target.power.off(explicit = True)
        r = target.power.list()
        assert all(s[1] == False for s in r), \
            "after explicit off, power state is not all off: %s" % r
        self.report_pass("explicit off powered everything off")

        # power ALL on
        target.power.on(explicit = True)
        r = target.power.list()
        assert all(s[1] == True for s in r), \
            "after explicit on, power state is not all on: %s" % r
        self.report_pass("explicit on powered everything on")
        
        # power off, leaving explicits on
        target.power.off()
        r = target.power.list()
        d = {}
        for k, v in r:
            d[k] = v
        assert all(i == True for i in [ d['ex'], d['ac1'], d['ac2'] ]), \
            "after normal off," \
            " expected explicit/offs not ON after normal power off: %s" % r
        assert all(i == False for i in [ d['fp1'], d['fp2'], d['dc'] ]), \
            "after normal off," \
            " expected non-explicit not OFF after normal power off: %s" % r
        self.report_pass("normal off powered non-explicits off")
        
        # power ALL off
        target.power.off(explicit = True)
        r = target.power.list()
        assert all(s[1] == False for s in r), \
            "after explicit off, power state is not all off: %s" % r
        self.report_pass("explicit off powered everything off")

        # power on, leaving explicits off
        target.power.on()
        r = target.power.list()
        d = {}
        for k, v in r:
            d[k] = v
        assert all(i == False for i in [ d['fp1'], d['fp2'], d['ex'] ]), \
            "expected explicit not OFF after normal power on: %s" % r
        assert all(i == True for i in [ d['ac1'], d['ac2'], d['dc'] ]), \
            "after normal power on, expected all ON but 'ex': %s" % r
        self.report_pass("normal on powered non-explicits on")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
