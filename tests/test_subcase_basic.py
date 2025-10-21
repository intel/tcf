#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# WARNING! This testcase is used also by other scripts to test execution.

import tcfl

class _test(tcfl.tc.tc_c):
    def eval_00(self):
        self.report_pass(f"SUBCASES={':'.join(self.subcases)}", level = 0)

    @tcfl.tc.subcase()
    def eval_10(self):		# used to test --{run-only,skip}-fname}
        self.report_pass("ran", level = 0)

    @tcfl.tc.subcase()
    def eval_20(self):		# used to test --{run-only,skip}-fname}
        self.report_pass("ran", level = 0)
