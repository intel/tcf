#! /usr/bin/env python3
#
# Copyright (c) 2026 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import tcfl.tc

@tcfl.tc.tags(
    "tcf",
    # files relative to top level this testcase exercises
    files = [ 'tcfl/tc.py' ],
    objects = [ "tcfl.tc.tc_c.subcase" ],
    level = "basic"
)
class _test(tcfl.tc.tc_c):
    """
    Test that the `with self.subcase()` decorator will catch and
    not propagate an exception with *break_on_non_pass = False* and
    viceversa.
    """

    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_20_catch_emit(self):
        try:
            with self.subcase("subcase", break_on_non_pass = False):
                raise RuntimeError("testing")
            self.report_pass("exception was caught as expected")
        except Exception:
            self.report_fail("exception was caught but it shall not")
        finally:
            # undo the recording as a blockage of the testcase
            # 'subcase' patch the result gathered above in the "with
            # self.subcase" block; it was set to blocked = 1, but in
            # truth, the fact that is was caught, it is a pass
            self.subtc['20_catch_emit##subcase'].result.passed = 1
            self.subtc['20_catch_emit##subcase'].result.blocked = 0



    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_30_not_catch_emit(self):
        try:
            with self.subcase("subcase", break_on_non_pass = True):
                raise RuntimeError("testing")
            self.report_fail("exception was not caught but it shall")
        except Exception:
            self.report_pass("exception was caught as expected")
        finally:
            # undo the recording as a blockage of the testcase
            # 'subcase' patch the result gathered above in the "with
            # self.subcase" block; it was set to blocked = 1, but in
            # truth, the fact that is was caught, it is a pass
            self.subtc['30_not_catch_emit##subcase'].result.passed = 1
            self.subtc['30_not_catch_emit##subcase'].result.blocked = 0


    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_30_catch_but_report(self):
        """
        When we have an issue in a block, we still report it as a failure
        """
        try:
            with self.subcase("subcase", break_on_non_pass = False):
                raise tcfl.fail_e("simulated failure")
            # FIXME: verify subcase was reported as a fail
            if self.subtc['30_catch_but_report##subcase'].result.failed == 1:
                self.report_pass("exception was caught as expected and reported a failure ")
            else:
                self.report_fail("exception was caught as expected but not reported a failure as expected {self.subtc['30_catch_but_report##subcase'].result.failed=}")
        except Exception:
            self.report_fail("exception was caught but it shall not")
        finally:
            # undo the recording as a blockage of the testcase
            # 'subcase' patch the result gathered above in the "with
            # self.subcase" block; it was set to blocked = 1, but in
            # truth, the fact that is was caught, it is a pass
            self.subtc['30_catch_but_report##subcase'].result.passed = 1
            self.subtc['30_catch_but_report##subcase'].result.failed = 0
