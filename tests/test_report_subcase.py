#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import tcfl
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
        raise tcfl.tc.pass_e("exception passed", dict(subcase = "sub8"))
        with tcfl.msgid_c(subcase = "sub9"):
            self.report_fail("9 failed")

    @tcfl.tc.subcase('somename')
    def eval_10(self):
        self.report_info("method subcase with name")

    @tcfl.tc.subcase()	# take it from the method name
    def eval_10_some_name(self):
        self.report_info("method subcase with default name")

    @tcfl.tc.subcase()
    def eval_20(self):
        with tcfl.msgid_c(subcase = 'deeper'):
            raise AssertionError("bleh, asserting a failure")

    @tcfl.tc.subcase()
    def eval_40(self):
        self.report_pass("I kept executing methods because"
                          " they were marked subcases")
