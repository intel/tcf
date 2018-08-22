#! /usr/bin/python2
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
@tcfl.tc.target("bsp_model == 'x86+arc'",
                app_zephyr = {
                    'x86': os.path.join(tcfl.tl.ZEPHYR_BASE,
                                        "samples", "hello_world"),
                    'arc': os.path.join(tcfl.tl.ZEPHYR_BASE,
                                        "samples", "hello_world"),
                })
class _test(tcfl.tc.tc_c):
    @staticmethod
    @tcfl.tc.serially()
    def build_10_zephyr(target):
        # For the sake of example, have the ARC target boot one
        # second later, so the messages do not intermix
        # because the ARC and the x86 both are writing now to the same
        # serial console and messages are not line buffered, so they
        # will intermix
        target.zephyr.config_file_write(
            '900_boot_delay',	# 900 so it overrides default settings (500_*)
            "CONFIG_BOOT_DELAY=2000\n",
            bsp = 'arc')
        # Ensure x86 starts the ARC core
        target.zephyr.config_file_write(
            '900_arc_target',	# 900 so it overrides default settings (500_*)
            "CONFIG_ARC_INIT=y\n",
            bsp = 'x86')

    def eval(self, target):
        # Wait at the same time on both
        with target.on_console_rx_cm('Hello World! arc'), \
             target.on_console_rx_cm('Hello World! x86'):
            self.expecter.run()
