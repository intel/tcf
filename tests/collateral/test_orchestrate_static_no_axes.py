#! /usr/bin/env python3
#
# Copyright (c) 2019-26 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import tcfl.tc

@tcfl.axes()			# force no axis
class _test(tcfl.tc.tc_c):
    def eval(self):
        self.report_pass("static evaluation with no axis")
