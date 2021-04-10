#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Excercise subcase reporting
    """
    def eval(self):

        self.report_info("something happened", subcase = "sub1")
        self.report_info("something happened", subcase = "sub1")
        self.report_info("something happened", subcase = "sub2")
        self.report_pass("this one passed", subcase = "sub2")
        self.report_fail("this one failed", subcase = "sub3")
        self.report_error("this one errored", subcase = "sub4")
        self.report_blck("this one blocked", subcase = "sub5")
        self.report_skip("this one failed", subcase = "sub6")
        self.report_data("domain", "name", "value", subcase = "sub7")

        raise tcfl.tc.pass_e("exception passed", dict(subcase = sub8))
