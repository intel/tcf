#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import re
import os

import tcfl
import tcfl.tc

class _test_base(tcfl.tc.tc_c):
    # FIXME: this needs to be the path using tests.clil
    def _run_cmdline(self, args: str):
        tcf_path = os.path.join(self.kws['srcdir_abs'], os.path.pardir, "tcf")
        return self.run_local(f"{tcf_path} {args}")


    def _test_expectation(self, output: str,
                          expected_regexes: list, unexpected_regexes: list):
        result = tcfl.result_c()
        # should print these
        for expected_regex in expected_regexes:
            if ( isinstance(expected_regex, re.Pattern) and expected_regex.search(output)) \
               or ( isinstance(expected_regex, str) and expected_regex in output ):
                self.report_pass(f"expected string '{expected_regex}' found in output")
                result.passed += 1
            else:
                self.report_fail(f"expected string '{expected_regex}' not found output",
                                 { "output": output })
                result.failed += 1

        # should not print any of these
        for unexpected_regex in unexpected_regexes:
            if ( isinstance(unexpected_regex, re.Pattern) and unexpected_regex.search(output)) \
               or ( isinstance(unexpected_regex, str) and unexpected_regex in output ):
                self.report_fail(f"unexpected string '{unexpected_regex}' found in output",
                                 { "output": output })
                result.failed += 1
            else:
                self.report_pass(f"unexpected string '{unexpected_regex}' not found in output")
                result.passed += 1

        return result


class _test(_test_base):
    """
    Test basic operation of 'tcf run --skip-fname' work.
    """

    @tcfl.tc.subcase()
    def eval_00_skip_all(self):
        """
        Run requesting subcases with commas, check we get that as subcases
        """
        return self._test_expectation(
            self._run_cmdline(
                "run -vvv --skip-fname=.*"
                f" {os.path.join(self.kws['srcdir_abs'], 'test_subcase_basic.py')}"),
            [
                "WARNING! will skip any function called .*()",
                "eval_00: skipped because it matches --skip-fname '.*'",
                "eval_10: skipped because it matches --skip-fname '.*'",
                "eval_20: skipped because it matches --skip-fname '.*'",
                # shall see it all skipped
                re.compile("test_subcase_basic.py.*: evaluation skipped"),
            ],
            [
                re.compile("tests/test_subcase_basic.py##10 .*: ran"),
                re.compile("tests/test_subcase_basic.py##20 .*: ran"),
                "0 skipped",
            ]
        )



    @tcfl.tc.subcase()
    def eval_10_skip_not_all(self):
        """
        Run requesting subcases with commas, check we get that as subcases
        """
        return self._test_expectation(
            self._run_cmdline(
                "run -vvv --skip-fname=.*eval_10.*"
                f" {os.path.join(self.kws['srcdir_abs'], 'test_subcase_basic.py')}"),
            [
                "WARNING! will skip any function called .*eval_10.*()",
                "eval_10: skipped because it matches --skip-fname '.*eval_10.*'",
                re.compile("tests/test_subcase_basic.py##20 .*: ran"),
            ],
            [
                re.compile("tests/test_subcase_basic.py##10 .*: ran"),
            ]
        )
