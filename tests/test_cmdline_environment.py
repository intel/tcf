#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import tcfl
import tcfl.tc

import clil

@tcfl.tc.tags(
    "tcf_client",
    # files relative to top level this testcase exercises
    files = [ 'tcf', 'tcfl/ui_cli_main.py' ],
    level = "basic")
class _test(clil.test_base_c):
    """
    Test both methods of running and asking for subcases (with commas
    or hashes) work
    """

    def eval(self, target):
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
        output = target.shell.run(
            "tcf -e VAR1=value1 -e VAR2=value2"
            f" run -vv {clil.ttbd.srcdir}/tests_collateral/test_cmdline_environment_run.py",
            output = True)
        ## PASS0/suzhzlE#1 .../test_subcase_basic.py @localic-localtg [+0.0s]: SUBCASES=subcase1:subcase2
        ## PASS0/ toplevel @local [+2.4s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.025167) - passed
        #
        # extract that subcase list from SUBCASES=XYZ...
        if 'on the environment as expected' in output:
            raise tcfl.tc.error_e("can't find environment variables expected output",
                                  dict(output = output), level = 1, alevel = 0)
