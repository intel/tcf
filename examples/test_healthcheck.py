#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
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
                                          "samples", "hello_world"),
                mode = "all")
@tcfl.tc.tags(ignore_example = True)
class _healtcheck_zephyr(tcfl.tc.tc_c):
    def configure_50_target(self, target):
        self.overriden_configure_50_target(target)

    @staticmethod
    def eval(target):
        target.expect("Hello World! %s" % target.kws['zephyr_board'])


# Ignore QEMU Zephyr, as they cannot power on/off w/o an image -- let
# the Hello World test test those
@tcfl.tc.target("not type:'^qemu-zephyr'", mode = "all")
@tcfl.tc.tags(ignore_example = True)
class _healtcheck_power(tcfl.tc.tc_c):
    @staticmethod
    def eval_power(target):
        if not getattr(target, "power"):
            raise tcfl.tc.skip_e("No power control interface")

        target.report_info("Powering off")
        target.power.off()
        target.report_pass("Powered off")

        target.report_info("Querying power status")
        power = target.power.get()
        if power != 0:
            raise tcfl.tc.failed_e("Power should be 0, reported %d" % power)
        target.report_pass("Power is reported correctly as %d" % power)

        target.report_info("Powering on")
        target.power.on()
        target.report_pass("Powered on")

        target.report_info("Querying power status")
        power = target.power.get()
        if power == 0:
            raise tcfl.tc.failed_e(
                "Power should be not 0, reported %d" % power)
        target.report_pass("Power is reported correctly as %d" % power)

@tcfl.tc.target(mode = "all")
@tcfl.tc.tags(ignore_example = True)
class _healtcheck_console(tcfl.tc.tc_c):
    @staticmethod
    def eval_console(target):
        if not getattr(target, "console"):
            raise tcfl.tc.skip_e("No console interface")

        target.report_info("reading default console")
        target.console.read()
        target.report_pass("read default console")

        target.report_info("listing consoles")
        consoles = target.console.list()
        target.report_pass("listed consoles: %s" % " ".join(consoles))

        for console in consoles:
            target.report_info("reading console '%s'" % console)
            target.console.read(console_id = console)
            target.report_pass("read console '%s'" % console)

        # We don't test writing...don't want to mess anything up
