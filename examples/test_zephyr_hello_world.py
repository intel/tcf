#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# We don't care for documenting all the interfaces, names should be
# self-descriptive:
#
# - pylint: disable = missing-docstring

import os
import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target("zephyr_board",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "hello_world"))
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval(target):
        target.expect("Hello World! %s" % target.kws['zephyr_board'])
