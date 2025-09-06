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
    Test *tcf -e* command line switch
    """
    def eval(self):

        var1 = os.environ.get("VAR1", None)
        if var1 != 'value1':
            raise tcfl.fail_e(
                "VAR1 not defined to 'value1' on the environment"
                f" as expected; got '{var1}'")
        self.report_pass("VAR1=value1 as expected", level = 0)

        var2 = os.environ.get("VAR2", None)
        if var2 != 'value2':
            raise tcfl.fail_e(
                "VAR2 not defined to 'value2' on the environment"
                f" as expected; got '{var2}'")
        self.report_info("VAR2=value2 as expected", level = 0)
