#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import tcfl.tc

class fake_report_driver_c(tcfl.tc.report_driver_c):
    """
    Report driver that records the maximum level a message has been
    sent with in the reporter's field called *level_max*.
    """

    def report(self, reporter, tag, ts, delta,
               level, message, alevel, attachments):

        if not hasattr(reporter, "level_max"):
            return	# testcase that is not valid

        if level > reporter.level_max:
            reporter.level_max = level


fake_report_driver = fake_report_driver_c()
tcfl.tc.report_driver_c.add(fake_report_driver, name = "fake")

class _test(tcfl.tc.tc_c):

    """
    Report multiple levels, but the fake reporter shall record the
    maximum level at #2
    """

    level_max_expected = 3
    report_level_driver_max = { "fake": level_max_expected }
    level_max = 0

    def eval(self):

        for method in (
                self.report_pass, self.report_fail, self.report_error,
                self.report_blck, self.report_skip, self.report_info ):
            for level in range(30):
                method("reporting level %d" % level, level = level)


        if self.level_max >= 3:
            raise tcfl.tc.failed_e(
                "recorded a maximum log level %d, expected %d"
                % (self.level_max, self.level_max_expected))
