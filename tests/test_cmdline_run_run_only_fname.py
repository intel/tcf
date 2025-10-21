#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import re

import tcfl.tc

import test_cmdline_skip_fname

class _test(test_cmdline_skip_fname._test_base):
    """
    Test basic operation of 'tcf run --run-only-fname' work.
    """

    @tcfl.tc.subcase()
    def eval_00_no_run_only(self):
        return self._test_expectation(
            # note we specify no extra --run-only-fname
            self._run_cmdline(
                "run -vvv"
                f" {os.path.join(self.kws['srcdir_abs'], 'test_subcase_basic.py')}"),
            # we expect to see them all ran
            [
                re.compile("test_subcase_basic.py.*: SUBCASES="),
                re.compile("test_subcase_basic.py##10 .*: ran"),
                re.compile("test_subcase_basic.py##20 .*: ran"),
                "0 skipped",
            ],
            [
                re.compile("skipped because it doesn't match any --run-only-fname regex"),
                "0 passed",
            ]
        )



    @tcfl.tc.subcase()
    def eval_10_run_only_single_fn(self):
        """
        Run requesting subcases with commas, check we get that as subcases
        """
        return self._test_expectation(
            self._run_cmdline(
                "run -vvv --run-only=eval_10"
                f" {os.path.join(self.kws['srcdir_abs'], 'test_subcase_basic.py')}"),
            [
                "WARNING! will run only function called eval_10()",
                "eval_00: skipped because it doesn't match any --run-only-fname regex: eval_10",
                "eval_20: skipped because it doesn't match any --run-only-fname regex: eval_10",
                re.compile("tests/test_subcase_basic.py##10 .*: ran"),
            ],
            [
                re.compile("tests/test_subcase_basic.py .*: SUBCASES="),
                re.compile("test_subcase_basic.py##20 .*: ran"),
            ]
        )
