#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import tcfl.tc

# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target('type:"^frdm_k64f"')
@tcfl.tc.tags(ignore_example = True)
class _script(tcfl.tc.tc_c):
    """
    Script to recover an FRDM k64f MCU board stuck in a RESET/WDOG loop

    When this happens, the TCF server logs report messages such as::

      log: Info : SWD DPIDR 0x2ba01477
      log: Warn : **** Your Kinetis MCU is probably locked-up in RESET/WDOG loop. ****
      log: Warn : **** Common reason is a blank flash (at least a reset vector).  ****
      log: Warn : **** Issue 'kinetis mdm halt' command or if SRST is connected   ****
      log: Warn : **** and configured, use 'reset halt'                           ****
      log: Warn : **** If MCU cannot be halted, it is likely secured and running  ****
      log: Warn : **** in RESET/WDOG loop. Issue 'kinetis mdm mass_erase'         ****
      log: Info : SWD DPIDR 0x2ba01477
      log: Error: Failed to read memory at 0xe000ed00
      log: Info : accepting 'tcl' connection on tcp/38743

    When this happens, we forcibly stop the target after power cycling
    it and deploy a well known image (pre-compiled Zephyr Hello World
    that is distributed with the TCF server package.

    """
    def eval(self, target):
        try:
            target.property_set("openocd-relaxed", "True")
            target.power.cycle()
            r = target.debug.openocd("kinetis mdm halt")
            self.report_info("kinetis mdm halt:\n%s" % r)

            r = target.debug.openocd("reset halt")
            self.report_info("reset halt:\n%s" % r)

            r = target.debug.openocd("reset halt")
            self.report_info("reset halt:\n%s" % r)

            r = target.debug.openocd("targets")
            self.report_info("targets:\n%s" % r)
            if not 'halted' in r:
                raise tcfl.tc.failed_e("CPU is not halted, retry")

            r = target.debug.openocd("flash write_image erase "
                                     "/var/lib/ttbd/frdm_k64f_recovery.bin 0")
            r = self.report_info("recovery flash:\n%s" % r)

            target.property_set("openocd-relaxed")
            target.power.cycle()
        finally:
            target.property_set("openocd-relaxed")
