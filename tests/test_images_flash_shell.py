#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

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

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):
    """
    Verify that different drivers that shall pass/fail do what is
    expected, exercising the checks in :class:ttbl.images.flash_shell_cmd_c

    """
    def eval(self, target):
        target.images.flash({ "image_works_0_0": __file__ })
        self.report_pass("driver 0-0 expected to pass passes")
        target.images.flash({ "image_works_1_1": __file__ })
        self.report_pass("driver 1-1 expected to pass passes")
        try:
            target.images.flash({ "image_fails_0_3": __file__ })
            raise tcfl.tc.failed_e(
                "flash() didn't raise error when flashing 0_3 as expected")
        except tcfl.tc.error_e:
            self.report_pass("driver 0-3 expected to fail fails")
        try:
            target.images.flash({ "image_fails_3_2": __file__ })
            raise tcfl.tc.failed_e(
                "flash() didn't raise error when flashing 3_2 as expected")
        except tcfl.tc.error_e as e:
            self.report_pass("driver 3_2 expected to fail fails")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
