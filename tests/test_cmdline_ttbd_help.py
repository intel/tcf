#! /usr/bin/python3
#
# Copyright (c) 2025 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import tcfl
import tcfl.tc

@tcfl.tc.tags(
    "ttbd",
    # files relative to top level this testcase exercises
    files = [ 'ttbd/ttbd', 'ttbd/ttbl/ui_cli_main.py' ],
    level = "basic")
class _test(tcfl.tc.tc_c):
    """
    Test running the 'tcf config' works basically
    """

    def eval(self):
        # copy the cmdline_environment_run.py file to temp as test_ ->
        # we do it like this so when we 'tcf run tests/', we don't
        # run that one.
        with self.subcase("execution"):
            output = self.run_local(
                os.path.join(self.kws['srcdir_abs'], os.path.pardir, "ttbd", "ttbd")
                + " --help")
            self.report_pass(
                "can run 'ttbd --help' command",
                { "output": output }, subcase = "execution")
        #
        # This shall print
        #
        ## usage: ..
        ##
        ## options:
        ##  -h, --help ...
        ##  ...
        #
        with self.subcase("text_presence"):
            for substring in [
                    "usage:",
                    "options:",
                    "--help",
                    "--version",
            ]:
                if not substring in output:
                    self.report_fail(
                        f"can't find section '{substring}': in 'tcf config' output",
                        subcase = substring)
