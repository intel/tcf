#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import tcfl.tc
import tcfl.tl
import tcfl.pos_uefi

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    """
    Cleanup EFI boot entries

    The tcfl.pos_uefi module configures EFI boot entries to boot first
    off PXE and then localboot.

    Sometimes EFI boot entries are accumulated for other reasons; this
    script helps clean them up, removing any entry that is not PXE
    boot or localboot based on the regular expressions in:

    - tcfl.pos_uefi.pos_boot_names
    - tcfl.pos_uefi.local_boot_names
    """

    @staticmethod
    def eval(ic, target):
        ic.power.on()
        target.pos.boot_to_pos()
        output = target.shell.run("efibootmgr", output = True)
        _boot_order, boot_entries = \
            tcfl.pos_uefi._efibootmgr_output_parse(target, output)
        for entry, _name, category, _index in boot_entries:
            if category != 0 and category != 10:
                target.shell.run("efibootmgr -b %s -B" % entry)
        output = target.shell.run("efibootmgr", output = True, trim = True)
        target.report_info(output)

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
