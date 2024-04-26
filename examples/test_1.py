#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import os
import random

import tcfl.tc

random.seed()

@tcfl.axes(
    axisA = [ 'a1', 'a2', 'a3' ],
    axisb = [ 'b1', 'b2' ]
)
class _test(tcfl.tc.tc_c):
    def eval(self):
        self.report_pass("I am causing a pass by raising")
        # or you can just return nothing, that means pass
        raise tcfl.tc.pass_e("I passed")
