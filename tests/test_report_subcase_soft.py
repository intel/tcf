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
    When reporting a soft failure/error/blockage, it shan't mark the
    testcase as failed.

    So exercise multiple subcases by calling
    report_{fail/errorr/blockage} with the soft flag on or off to
    ensure the right field is updated (or not)
    """

    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_10_fail(self):

        with self.subcase("soft"):
            self.report_fail("ignore this soft failure", soft = True)

        with self.subcase("hard"):
            self.report_fail("ignore this hard failure")

        subtc_soft = self.subtc['10_fail##soft']
        subtc_hard = self.subtc['10_fail##hard']

        # we don't really care for these now, so wipe them from the
        # list of subcases so they don't taint the final result
        del self.subtc['10_fail##soft']
        del self.subtc['10_fail##hard']

        with self.subcase("soft"):
            if subtc_soft.result.failed != 0:
                self.report_fail(
                    "soft failure set failed field when it shouldn't")
            else:
                self.report_pass(
                    "soft failure did not set failed field as expected")

        with self.subcase("hard"):
            if subtc_hard.result.failed == 0:
                self.report_fail(
                    "hard failure did not set failed field when it should")
            else:
                self.report_pass(
                    "hard failure did set failed field as expected")


    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_20_errr(self):

        with self.subcase("soft"):
            self.report_error("ignore this soft error", soft = True)

        with self.subcase("hard"):
            self.report_error("ignore this hard error")

        subtc_soft = self.subtc['20_errr##soft']
        subtc_hard = self.subtc['20_errr##hard']

        del self.subtc['20_errr##soft']
        del self.subtc['20_errr##hard']

        with self.subcase("soft"):
            if subtc_soft.result.errors != 0:
                self.report_fail(
                    "soft error set errored field when it shouldn't")
            else:
                self.report_pass(
                    "soft error did not set errored field as expected")

        with self.subcase("hard"):
            if subtc_hard.result.errors == 0:
                self.report_fail(
                    "hard error did not set errored field when it should")
            else:
                self.report_pass(
                    "hard error did set errored field as expected")


    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_30_blck(self):

        with self.subcase("soft"):
            self.report_blck("ignore this soft blockage", soft = True)

        with self.subcase("hard"):
            self.report_blck("ignore this hard blockage")

        subtc_soft = self.subtc['30_blck##soft']
        subtc_hard = self.subtc['30_blck##hard']

        del self.subtc['30_blck##soft']
        del self.subtc['30_blck##hard']

        with self.subcase("soft"):
            if subtc_soft.result.blocked != 0:
                self.report_fail(
                    "soft blockage set blocked field when it shouldn't")
            else:
                self.report_pass(
                    "soft blockage did not set blocked field as expected")

        with self.subcase("hard"):
            if subtc_hard.result.blocked == 0:
                self.report_fail(
                    "hard blockage did not set blocked field when it should")
            else:
                self.report_pass(
                    "hard blockage did set blocked field as expected")
