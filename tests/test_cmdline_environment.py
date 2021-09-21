#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import shutil

import tcfl
import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Test both methods of running and asking for subcases (with commas
    or hashes) work
    """

    def eval(self):
        # copy the cmdline_environment_run.py file to temp as test_ ->
        # we do it like this so when we 'tcf run tests/', we don't
        # run that one.
        tmp_testcasename = os.path.join(self.tmpdir, "test_cmdline_environment_run.py")
        shutil.copy(os.path.join(self.kws['srcdir_abs'], "cmdline_environment_run.py"), tmp_testcasename)
        tcf_path = os.path.join(self.kws['srcdir_abs'], os.path.pardir, "tcf")
        output = self.run_local(
            tcf_path
            + f" -e VAR1=value1 -e VAR2=value2 run -vvv {tmp_testcasename}")
        ## PASS0/suzhzlE#1 .../test_subcase_basic.py @localic-localtg [+0.0s]: SUBCASES=subcase1:subcase2
        ## PASS0/ toplevel @local [+2.4s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.025167) - passed
        #
        # extract that subcase list from SUBCASES=XYZ...
        if 'on the environment as expected' in output:
            raise tcfl.tc.error_e("can't find environment variables expected output",
                                  dict(output = output), level = 1, alevel = 0)
