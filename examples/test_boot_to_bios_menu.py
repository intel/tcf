#! /usr/bin/python
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_boot_to_bios_menu:

Direct a target to boot to the BIOS main menu
=============================================

A target whose BIOS can be controlled via the BIOS can be made to go
into the BIOS main menu.

Assumptions:

- target's BIOSes can be driven via a serial port, using ANSI
  command sequences and key presses (see :ref:`tcfl.biosl
  <bios_menus>` contains utilities for using those)

- the target's inventory :ref:`needs to be configured
  <bios_inventory>` to declare what the BIOS interface needs / expects.

Execute :download:`the testcase
<../examples/test_boot_to_bios_menu.py>` and run it::

  $ tcf run -vv /usr/share/tcf/examples/test_boot_to_bios_menu.py
  INFO3/	toplevel @local [+0.6s]: version v0.14-665-g9d425b4-dirty
  INFO2/	toplevel @local [+0.6s]: scanning for test cases
  INFO3/	test_boot_to_bios_menu.py @local [+4.6s]: queuing for pairing
  INFO3/8xldzi	test_boot_to_bios_menu.py @local [+0.9s]: read property 'interfaces.console.default': 'None' [None]
  INFO1/wpoaqz	test_boot_to_bios_menu.py @TARGETNAME [+1.0s]: will run on target group 'target=TARGETNAME:x86_64' (PID 23830 / TID 7f2065bf0700)
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+1.3s]: power cycling
  INFO2/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+30.7s]: power cycled
  INFO2/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+31.1s]: BIOS: waiting for main menu after power on
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]: 00/Press_s___F6___s_to_show_boot_menu_options: found 'b'Press\\\\s+\\\\[F6\\\\]\\\\s+to show boot menu options'' at @2903-2942 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  ...
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]:    console output (partial): \r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]:    console output (partial):           Press [Enter] to directly boot.\r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]:    console output (partial):           Press [F2]    to enter setup and select boot options.\r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]:    console output (partial):           Press [F6]    to show boot menu options.\r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+49.9s]:    console output (partial):           Press [F12]   to boot from network.\r\r
  INFO2/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+50.6s]: sol0_ssh: wrote 5B (\x1b[12~) to console
  ...
  INFO2/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.2s]: BIOS: confirming we are at toplevel menu
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.4s]: 01/BIOS-toplevel/Main: found 'b'Main'' at @8566-8570 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.4s]:    console output: .\r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.4s]:    console output:           Press [F12]   to boot from network.\r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.4s]:    console output: \x1b[25;01H                                                               \r\r
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.4s]:    console output:                                                                \r\r
  ...
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+57.7s]: 02/BIOS-toplevel/Advanced: found 'b'Advanced'' at @8670-8678 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+58.1s]: 03/BIOS-toplevel/Security: found 'b'Security'' at @8752-8760 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+58.5s]: 04/BIOS-toplevel/Server Management: found 'b'Server\\\\ Management'' at @8834-8851 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+59.0s]: 05/BIOS-toplevel/Error Manager: found 'b'Error\\\\ Manager'' at @8916-8929 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+59.4s]: 06/BIOS-toplevel/Boot Manager: found 'b'Boot\\\\ Manager'' at @8998-9010 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+59.7s]: 07/BIOS-toplevel/Boot Maintenance Manager: found 'b'Boot\\\\ Maintenance\\\\ Manager'' at @9080-9104 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+60.2s]: 08/BIOS-toplevel/Save & Exit: found 'b'Save\\\\ \\\\&\\\\ Exit'' at @9162-9173 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  INFO3/wpoaqzE#1	test_boot_to_bios_menu.py @TARGETNAME [+60.7s]: 09/BIOS-toplevel/Tls Auth Configuration: found 'b'Tls\\\\ Auth\\\\ Configuration'' at @9244-9266 on console TARGETNAME:sol0_ssh [report-:wpoaqz.console-target.r01s19.sol0_ssh.txt]
  PASS1/wpoaqz	test_boot_to_bios_menu.py @TARGETNAME [+60.9s]: evaluation passed
  PASS0/	toplevel @local [+66.2s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:01:00.941210) - passed

  (depending on your installation method, location might be
  *~/.local/share/tcf/examples*)

"""

import os

import tcfl.tc
import tcfl.biosl

@tcfl.tc.target(mode = os.environ.get('MODE', 'one-per-type'))
class _test(tcfl.tc.tc_c):

    @tcfl.tc.serially()			# make sure it executes in order
    def deploy_10_flash(self, target):
        # maybe flash a firmware image if present in the environment
        if not hasattr(target, 'images'):
            return

        self.image_flash, upload, soft = target.images.flash_spec_parse(
            self.image_flash_requested)

        if self.image_flash:
            target.images.flash(self.image_flash, upload = upload, soft = soft)


    def eval(self, target):

        target.power.cycle()
        tcfl.biosl.main_menu_expect(target)
