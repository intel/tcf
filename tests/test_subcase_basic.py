#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import tcfl

class _test(tcfl.tc.tc_c):
    def eval_00(self):
        self.report_pass(f"SUBCASES={':'.join(self.subcases)}", level = 0)
