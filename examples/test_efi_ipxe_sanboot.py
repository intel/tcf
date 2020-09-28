#! /usr/bin/python
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_efi_pxe_sanboot:

Boot an ISO image off the network with EDK2 EFI BIOS and iPXE
=============================================================

Given a machine that has an EDK2 based EFI BIOS, power cycle the
machine and using the serial console, break into the BIOS menu to
direct the machine to boot the PXE boot entry associated to the MAC
address declared in the inventory.

Assumptions:

 - The DHCP service in the network to which this machine is connected
   directs the machine too a TFTP boot server in which iPXE is
   available

 - iPXE has enabled the Ctrl-B escape sequence to go to the iPXE
   console (see :ref:`more info <howto_fog_ipxe>`)

Note how this testcase is reusing the template
:class:tcfl.pos.tc_pos_base; this allows to use this script to flash
firmware images (see :meth:`tcfl.pos.tc_pos0_base.deploy_10_flash` for
more information).

.. literalinclude:: /examples/test_efi_ipxe_sanboot.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_efi_ipxe_sanboot.py>`
with::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_efi_ipxe_sanboot.py
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+438.5s]: power cycled
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+438.9s]: BIOS: waiting for main menu after power on
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+492.0s]: BIOS:main menu/Boot Manager Menu: highlighted entry found
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+498.5s]: BIOS: can't find PXE network boot entry 'UEFI PXEv4 \\(MAC:4AFB6017383C\\)'; attempting to enable EFI network support
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+498.5s]: BIOS: going to main menu
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+507.9s]: BIOS:top/EDKII Menu: highlighted entry found
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+507.9s]: BIOS: top: selecting menu entry 'EDKII Menu'
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+510.5s]: BIOS:top > EDKII Menu: found menu header
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+526.3s]: BIOS: top > EDKII Menu: selecting menu entry 'Platform Configuration'
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+531.4s]: BIOS: top > EDKII Menu > Platform Configuration: selecting menu entry 'Network Configuration'
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+534.9s]: BIOS: EFI Network: enabling (was: <Disable>)
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+546.5s]: BIOS: escaped to main
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+552.0s]: BIOS:top/Reset: highlighted entry found
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+552.8s]: serial0: wrote 1B (\\r) to console
  ...
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+552.8s]: BIOS: waiting for main menu after power on
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+616.2s]: BIOS: confirming we are at toplevel menu
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+619.2s]: BIOS:main menu/Boot Manager Menu: highlighted entry found
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+621.7s]: BIOS:Boot Manager Menu: found menu header
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+623.5s]: BIOS:Boot Manager Menu/UEFI PXEv4 \\(MAC:4AFB6017383C\\): highlighted entry found
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+637.8s]: serial0: wrote 25B (set net0/ip 10.129.318.9\\r) to console
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+639.4s]: serial0: wrote 31B (set net0/netmask 255.255.252.0\\r) to console
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+640.1s]: serial0: wrote 7B (ifopen\\r) to console
  INFO2/x74ds3E#1  .../test_efi_ipxe_sanboot.py @huty-ehnc|localhost/qu06b [+642.4s]: serial0: wrote 48B (sanboot http://someserver.com/Fedora-Workstation-Live-x86_64-31-1.9.iso\\r) to console
  PASS1/x74ds3  .../test_efi_ipxe_sanboot.py @huty-ehnc [+644.0s]: evaluation passed 
  PASS0/	toplevel @local [+648.6s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:10:44.397730) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)
"""
import os
import time

import commonl
import tcfl.biosl
import tcfl.tc
import tcfl.tl


class _test(tcfl.pos.tc_pos_base):

    # tcfl.pos.tc_pos_base.deploy_10_flash(self, target) does the BIOS
    # flashing for us

    # ignore tcfl.pos.tc_pos_base template actions
    def deploy_50(self, ic, target):
        pass

    # ignore tcfl.pos.tc_pos_base template actions
    def start_50(self, ic, target):
        pass

    def eval(self, target):

        SANBOOT_URL = os.environ.get("SANBOOT_URL", None)
        if SANBOOT_URL == None:
            raise tcfl.tc.blocked_e("No SANBOOT_URL environment given")

        target.power.cycle()

        boot_ic = target.kws['pos_boot_interconnect']
        mac_addr = target.kws['interconnects'][boot_ic]['mac_addr']
        tcfl.biosl.boot_network_pxe(
            target,
            # Eg: UEFI PXEv4 (MAC:4AB0155F98A1)
            r"UEFI PXEv4 \(MAC:%s\)" % mac_addr.replace(":", "").upper().strip())

        # can't wait also for the "ok" -- debugging info might pop in th emiddle
        target.expect("iPXE initialising devices...")
        # if the connection is slow, we have to start sending Ctrl-B's
        # ASAP
        #target.expect(re.compile("iPXE .* -- Open Source Network Boot Firmware"))

        # send Ctrl-B to go to the PXE shell, to get manual control of iPXE
        #
        # do this as soon as we see the boot message from iPXE because
        # otherwise by the time we see the other message, it might already
        # be trying to boot pre-programmed instructions--we'll see the
        # Ctrl-B message anyway, so we expect for it.
        #
        # before sending these "Ctrl-B" keystrokes in ANSI, but we've seen
        # sometimes the timing window being too tight, so we just blast
        # the escape sequence to the console.
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.expect("Ctrl-B")
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.expect("iPXE>")
        prompt_orig = target.shell.shell_prompt_regex
        try:
            #
            # When matching end of line, match against \r, since depends
            # on the console it will send one or two \r (SoL vs SSH-SoL)
            # before \n -- we removed that in the kernel driver by using
            # crnl in the socat config
            #
            # FIXME: block on anything here? consider infra issues
            # on "Connection timed out", http://ipxe.org...
            target.shell.shell_prompt_regex = "iPXE>"
            kws = dict(target.kws)
            boot_ic = target.kws['pos_boot_interconnect']
            ipv4_addr = target.kws['interconnects'][boot_ic]['ipv4_addr']
            ipv4_prefix_len = target.kws['interconnects'][boot_ic]['ipv4_prefix_len']
            kws['ipv4_netmask'] = commonl.ipv4_len_to_netmask_ascii(ipv4_prefix_len)

            if False: #dhcp:
                target.shell.run("dhcp", re.compile("Configuring.*ok"))
                target.shell.run("show net0/ip", "ipv4 = %s" % ipv4_addr)
            else:
                # static is much faster and we know the IP address already
                # anyway; but then we don't have DNS as it is way more
                # complicated to get it
                target.shell.run("set net0/ip %s" % ipv4_addr)
                target.shell.run("set net0/netmask %s" % kws['ipv4_netmask'])
                target.shell.run("ifopen")

            target.send("sanboot %s" % SANBOOT_URL)
            # can't use shell.run...it will timeout, since we'll print no more prompt
            target.expect("Booting from SAN device")
        finally:
            target.shell.shell_prompt_regex = prompt_orig
