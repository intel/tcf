#! /usr/bin/python3
#
# Copyright (c) 2025 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import shutil

import tcfl
import tcfl.tc

@tcfl.tc.tags(
    "tcf_client",
    # files relative to top level this testcase exercises
    files = [ 'tcf', 'tcfl/ui_cli_main.py' ],
    level = "basic")
class _test(tcfl.tc.tc_c):
    """
    Test running the config command basically works
    """

    def eval(self):
        # copy the cmdline_environment_run.py file to temp as test_ ->
        # we do it like this so when we 'tcf run tests/', we don't
        # run that one.
        with self.subcase("execution"):
            output = self.run_local(
                os.path.join(self.kws['srcdir_abs'], os.path.pardir, "tcf")
                + " config")
            self.report_pass(
                "can run 'tcf config' command",
                { "output": output }, subcase = "execution")
        #
        # This shall print
        #
        ## tcf: ./tcf
        ## tcf/realpath: .../tcf
        ## tcfl: .../tcfl/__init__.py
        ## commonl: .../commonl/__init__.py
        ## share path: ...
        ## state path: $HOME/.tcf
        ## config path: .../zephyr:...:$HOME/.tcf:.tcf
        ## config file 0: .../zephyr/conf_zephyr.py
        ## config file 1: .../conf_global.py
        ## version: ...
        ## python: ...
        ## uname.machine: ...
        ## uname.node: ...
        ## uname.processor: ...
        ## uname.release: ...
        ## uname.system: ...
        ## uname.version: ...
        ## servers: 11
        ## server ...: ...
        ## resolvconf: ...
        ## resolvconf: ...
        #
        with self.subcase("section_presence"):
            for subsection in [
                    "tcf",
                    "tcf/realpath",
                    "tcfl",
                    "commonl",
                    "share path",
                    "state path",
                    "config path",
                    # at least it will discover one config file
                    "config file 0",
                    "version",
                    "python",
                    "servers",
                    # this is only if we discover servers, which we
                    # won't in this run
                    #"server",
                    "resolvconf",
            ]:
                if not subsection + ":" in output:
                    self.report_fail(
                        f"can't find section '{subsection}': in 'tcf config' output",
                        subcase = subsection)
