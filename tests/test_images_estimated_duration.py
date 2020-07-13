#! /usr/bin/python2
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
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    @staticmethod
    def eval(target):
        ts0 = time.time()
        target.images.flash({ "image0": __file__ })
        ts1 = time.time()
        # this shall take around 80% of 10s, so we configured it
        delta = abs(10 - (ts1 - ts0))
        if delta > 1:
            raise tcfl.tc.failed_e(
                "image0 flashing expected to take around 10s, took %s (%s)"
                % (ts1 - ts0, delta))
            
        ts0 = time.time()
        target.images.flash({ "image1": __file__ })
        ts1 = time.time()
        # this shall take around 20s, complain if it goes of +-2
        delta = abs(20 - (ts1 - ts0))
        if delta > 2:
            raise tcfl.tc.failed_e(
                "image0 flashing expected to take around 20s, took %s (%s)"
                % (ts1 - ts0, delta))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
