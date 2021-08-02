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
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ])

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """

    def _eval_image(self, target, image_name, expected_duration):
        ts0 = time.time()
        target.images.flash({ image_name: __file__ })
        ts1 = time.time()
        # check this is at least 50% of the time it says it will take
        factor = (ts1 - ts0) / expected_duration
        if factor < 0.5 or factor > 1.5:
            raise tcfl.tc.failed_e(
                f"{image_name}: flashing expected to take around {expected_duration}+-50%s,"
                " took {ts1 - ts0} %{100 * factor:.1f}s")
        self.report_pass(f"{image_name}: got expected duration"
                         f" {ts1 - ts0} %{100 * factor:.1f}s")


    @tcfl.tc.subcase()
    def eval_image0(self, target):
        self._eval_image(target, "image0", 10)

    @tcfl.tc.subcase()
    def eval_image1(self, target):
        self._eval_image(target, "image1", 20)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
