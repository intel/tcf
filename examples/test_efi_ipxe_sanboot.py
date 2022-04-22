#! /usr/bin/python3
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

Note this functionality can be accessed by using
:func:`tcfl.tl.ipxe_sanboot_url`.

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

  $ SANBOOT_URL=http://someserver.com/Fedora-Workstation-Live-x86_64-31-1.9.iso tcf run -v /usr/share/tcf/examples/test_efi_ipxe_sanboot.py
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

If SANBOOT_URL is "skip*, then no sanboot is executed and the iPXE
command line is left available for use.

Optionally you can environment set *IMAGES_FLASH* to have the script
flash something first (see :meth:`target.images.flash_spec_parse
<tcfl.target_ext_images.extension.flash_spec_parse>`)::

  $ tcf -e IMAGES_FLASH="bios:SOMEBIOSFILE nic:SOMEFIRMWAREFILE run ...

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import os
import re
import time

import commonl
import tcfl.biosl
import tcfl.tc
import tcfl.tl


class _test(tcfl.pos.tc_pos_base):

    sanboot_url = None

    # tcfl.pos.tc_pos_base.deploy_10_flash(self, target) does the BIOS
    # flashing for us


    @tcfl.tc.serially()			# make sure it executes in order
    def deploy_10_flash(self, target):
        self.image_flash, upload, soft = target.images.flash_spec_parse(
            self.testcase.image_flash_requested)

        if self.image_flash:
            if upload:
                target.report_info("uploading files to server and flashing")
            else:
                target.report_info("flashing")
            target.images.flash(self.image_flash, upload = upload, soft = soft)

    # ignore tcfl.pos.tc_pos_base template actions
    def deploy_50(self, ic, target):
        pass

    # ignore tcfl.pos.tc_pos_base template actions
    def start_50(self, ic, target):
        pass

    def eval(self, target):

        if self.sanboot_url == None:
            SANBOOT_URL = os.environ.get("SANBOOT_URL", None)
            if SANBOOT_URL == None:
                raise tcfl.tc.blocked_e(
                    "No default sanboot_url programmed or"
                    " SANBOOT_URL environment given")
            self.sanboot_url = SANBOOT_URL

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
        target.expect("Ctrl-B", timeout = 250)
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.console.write("\x02\x02")	# use this iface so expecter
        time.sleep(0.3)
        target.expect("iPXE>")
        prompt_orig = target.shell.prompt_regex
        try:
            #
            # When matching end of line, match against \r, since depends
            # on the console it will send one or two \r (SoL vs SSH-SoL)
            # before \n -- we removed that in the kernel driver by using
            # crnl in the socat config
            #
            # FIXME: block on anything here? consider infra issues
            # on "Connection timed out", http://ipxe.org...
            target.shell.prompt_regex = "iPXE>"
            kws = dict(target.kws)
            boot_ic = target.kws['pos_boot_interconnect']
            mac_addr = target.kws['interconnects'][boot_ic]['mac_addr']
            ipv4_addr = target.kws['interconnects'][boot_ic]['ipv4_addr']
            ipv4_prefix_len = target.kws['interconnects'][boot_ic]['ipv4_prefix_len']
            kws['ipv4_netmask'] = commonl.ipv4_len_to_netmask_ascii(ipv4_prefix_len)

            # Find what network interface our MAC address is; the
            # output of ifstat looks like:
            #
            ## net0: 00:26:55:dd:4a:9d using 82571eb on 0000:6d:00.0 (open)
            ##   [Link:up, TX:8 TXE:1 RX:44218 RXE:44205]
            ##   [TXE: 1 x "Network unreachable (http://ipxe.org/28086090)"]
            ##   [RXE: 43137 x "Operation not supported (http://ipxe.org/3c086083)"]
            ##   [RXE: 341 x "The socket is not connected (http://ipxe.org/380f6093)"]
            ##   [RXE: 18 x "Invalid argument (http://ipxe.org/1c056082)"]
            ##   [RXE: 709 x "Error 0x2a654089 (http://ipxe.org/2a654089)"]
            ## net1: 00:26:55:dd:4a:9c using 82571eb on 0000:6d:00.1 (open)
            ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
            ##   [Link status: Down (http://ipxe.org/38086193)]
            ## net2: 00:26:55:dd:4a:9f using 82571eb on 0000:6e:00.0 (open)
            ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
            ##   [Link status: Down (http://ipxe.org/38086193)]
            ## net3: 00:26:55:dd:4a:9e using 82571eb on 0000:6e:00.1 (open)
            ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
            ##   [Link status: Down (http://ipxe.org/38086193)]
            ## net4: 98:4f:ee:00:05:04 using NII on NII-0000:01:00.0 (open)
            ##   [Link:up, TX:10 TXE:0 RX:8894 RXE:8441]
            ##   [RXE: 8173 x "Operation not supported (http://ipxe.org/3c086083)"]
            ##   [RXE: 268 x "The socket is not connected (http://ipxe.org/380f6093)"]
            #
            # thus we need to match the one that fits our mac address
            ifstat = target.shell.run("ifstat", output = True, trim = True)
            regex = re.compile(
                "(?P<ifname>net[0-9]+): %s using" % mac_addr.lower(),
                re.MULTILINE)
            m = regex.search(ifstat)
            if not m:
                raise tcfl.tc.error_e(
                    "iPXE: cannot find interface name for MAC address %s;"
                    " is the MAC address in the configuration correct?"
                    % mac_addr.lower(),
                    dict(target = target, ifstat = ifstat,
                         mac_addr = mac_addr.lower())
                )
            ifname = m.groupdict()['ifname']

            dhcp = bool(target.property_get("ipxe.dhcp", True))
            if dhcp:
                target.shell.run("dhcp " + ifname, re.compile("Configuring.*ok"))
                target.shell.run("show %s/ip" % ifname, "ipv4 = %s" % ipv4_addr)
            else:
                # static is much faster and we know the IP address already
                # anyway; but then we don't have DNS as it is way more
                # complicated to get it
                target.shell.run("set %s/ip %s" % (ifname, ipv4_addr))
                target.shell.run("set %s/netmask %s" % (ifname, kws['ipv4_netmask']))
                target.shell.run("ifopen " + ifname)

            if self.sanboot_url == "skip":
                target.report_info("not booting", level = 0)
            else:
                target.send("sanboot %s" % self.sanboot_url)
                # can't use shell.run...it will timeout, since we'll print no more prompt
                # ESXi would print now...
                #target.expect("Booting from SAN device")
        finally:
            target.shell.prompt_regex = prompt_orig
