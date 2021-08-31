#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import tcfl
import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Test both methods of running and asking for subcases (with commas
    or hashes) work
    """

    def _run_cmdline(self, sep, l):
        tcf_path = os.path.join(self.kws['srcdir_abs'], os.path.pardir, "tcf")
        output = self.run_local(
            tcf_path
            + f" run {os.path.join(self.kws['srcdir_abs'], 'test_subcase_basic.py')}"
            + sep + sep.join(l))
        ## PASS0/suzhzlE#1 .../test_subcase_basic.py @localic-localtg [+0.0s]: SUBCASES=subcase1:subcase2
        ## PASS0/ toplevel @local [+2.4s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.025167) - passed
        #
        # extract that subcase list from SUBCASES=XYZ...
        start = output.find("SUBCASES=")
        if start == -1:
            raise tcfl.tc.error_e("can't find SUBCASES= in output",
                                  dict(output = output))
        subcases_string, _ = output[start + len("SUBCASES="):].split('\n', 1)
        return set(subcases_string.split(':'))


    def eval_comma(self):
        """
        Run requesting subcases with commas, check we get that as subcases
        """
        subcases = set([ "1", "2", "3", "4" ])

        # separate subcases with commas: tcf run somecase,subcase1,subcase2
        subcases_seen = self._run_cmdline(",", subcases)
        if subcases_seen != subcases:
            raise tcfl.tc.fail_e(
                "expected list of subcases doesn't match",
                dict(subcases_seen = subcases_seen,
                     subcases_expected = subcases)
            )

        # separate subcases with hashes: tcf run somecase#subcase1#subcase2
        subcases_seen = self._run_cmdline("#", subcases)
        if subcases_seen != subcases:
            raise tcfl.tc.fail_e(
                "expected list of subcases doesn't match",
                dict(subcases_seen = subcases_seen,
                     subcases_expected = subcases)
            )
