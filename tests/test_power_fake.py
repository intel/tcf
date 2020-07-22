#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target("t0")
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval(target):
        target.power.on()
        r = target.power.get()
        assert r == True, "power state is %s" % r

        target.power.off()
        r = target.power.get()
        assert r == False, "power state is %s" % r

        target.power.cycle()
        r = target.power.get()
        assert r == True, "power state is %s" % r

        target.power.off()
        r = target.power.get()
        assert r == False, "power state is %s" % r

        target.power.reset()
        r = target.power.get()
        assert r == True, "power state is %s" % r

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
