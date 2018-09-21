#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target("zephyr_board",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "hello_world"))
@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    """
    Show an example on how to override pre-defined actions created by
    app_zephyr while running Hello World!
    """
    def build_50_target(self, target):
        target.report_info("building our own way, we are "
                           "going to hack the source first")
        self.overriden_build_50_target(target)

    @staticmethod
    def eval(target):
        target.expect("Hello World! %s" % target.kws['zephyr_board'])
