#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import tcfl.tc

@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    def eval(self):
        filename = "testfile"
        if os.path.exists(filename):
            self.report_info("file '%s': exists! test passes" % filename)
        else:
            raise tcfl.tc.failed_e("file '%s': does not exist" % filename)
