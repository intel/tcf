#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_boot_to_efi_shell:

Direct a target to boot to the EFI shell
========================================

A target whose BIOS can be controlled via the serial port can be made
to boot into the EFI shell.

Assumptions:

- target's BIOSes can be driven via a serial port, using ANSI
  command sequences and key presses (see :ref:`tcfl.biosl
  <bios_menus>` contains utilities for using those)

- the target's inventory :ref:`needs to be configured
  <bios_inventory>` to declare what the BIOS interface needs / expects.

Execute :download:`the testcase
<../examples/test_boot_to_efi_shell.py>` and run it::

  $ tcf run -vv /usr/share/tcf/examples/test_boot_to_efi_shell.py

  (depending on your installation method, location might be
  *~/.local/share/tcf/examples*)

"""
import os
import re

import tcfl.biosl
import tcfl.tc

@tcfl.tc.target(mode = os.environ.get('MODE', 'one-per-type'))
class _test(tcfl.tc.tc_c):
    """
    Boot an UEFI target to the EFI shell
    """

    @tcfl.tc.serially()			# make sure it executes in order
    def deploy_10_flash(self, target):
        # maybe flash a firmware image if present in the environment
        if not hasattr(target, 'images'):
            return

        self.image_flash, upload, soft = target.images.flash_spec_parse()

        if self.image_flash:
            target.images.flash(self.image_flash, upload = upload, soft = soft)

    
    def eval(self, target):

        target.capture.streamers_start()
        try:
            target.power.cycle()
            tcfl.biosl.boot_efi_shell(target)
            target.shell.prompt_regex = re.compile("[^>]+>")
            target.shell.run("echo I booted", "I booted", timeout = 80)
        finally:
            target.capture.streamers_stop_and_get()
            target.capture.snapshoters_get()
