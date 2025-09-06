#! /usr/bin/python3
#
# Copyright (c) 2025 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import tcfl.tc
import clil

@tcfl.tc.tags(
    "tcf_client",
    # files relative to top level this testcase exercises
    files = [ 'tcf', 'tcfl/ui_cli_main.py' ],
    level = "basic")
class _test(clil.test_base_c):
    """
    When *tcf run* finds no testcases, it returns a non-zero exit code
    """

    def eval_10(self, target):
        # the environment has been set so this runs the right TCF
        # command; eg PATH has been set to be:
        #
        # - for running from source, the first path component is the
        #   source tree
        #
        # - for running from python vevn, activated and the path set
        #   to the python venv
        #
        # - for running from prefix, the first path is set to the
        #   prefix's path
        #
        output = None
        try:
            # target.shell.setup() has configured this to raise an
            # excetion if ERROR-IN-SHELL is printed in the console; the
            # shell has been configured to print that (with trap) if a
            # command line exits with non-zero exit
            output = target.shell.run("tcf run -vv test_this_does_not_exist.py",
                                      output = True)
        except Exception:
            self.report_pass(
                "tcf run on an nonexistant testcase failed returning non-zero exit code",
                { "output": output })
            return

        if 'WARNING! No testcases found' in output:
            self.report_pass(
                "tcf run on an nonexistant testcase at least reports they weren't found",
                { "output": output })
        raise tcfl.tc.fail_e(
            "tcf run on an nonexistant testcase didn't fail or wasn't caught",
            { "output": output })
