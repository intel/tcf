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
import time
import tcfl.tc

# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target("zephyr_board == 'quark_se_c1000_devboard' "
                "and bsp_model == 'x86'")
@tcfl.tc.tags(ignore_example = True)
class _fwup(tcfl.tc.tc_c):
    @staticmethod
    def eval_flash(target):
        try:
            rom_filename = os.environ['QC1000_ROM_FILENAME']
        except KeyError:
            raise tcfl.tc.blocked_e(
                "Define QC1000_ROM_FILENAME environment with path to file")
        try:
            target.property_set("disable_power_cycle_before_flash", "True")
            target.power.cycle()
            target.debug.reset()
            target.debug.reset_halt()

            target.report_info("running: clk32M 5000")
            target.debug.openocd("clk32M 5000")

            target.report_info("Magic :( let clock stabilize (waiting 10s)")
            time.sleep(10)

            target.report_info("running: mass_erase")
            target.debug.openocd("mass_erase")
            target.report_info("flashing the new bootrom")
            target.images.flash({ "rom": rom_filename })
            target.debug.reset_halt()
            target.power.off()
        finally:
            target.property_set("disable_power_cycle_before_flash")
