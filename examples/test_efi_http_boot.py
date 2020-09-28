#! /usr/bin/python
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_efi_http_boot:

Boot an EFI image off the network with EDK2 EFI BIOS and HTTP boot
==================================================================

Given a machine that has an EDK2 based EFI BIOS, power cycle the
machine and using the serial console, break into the BIOS menu to
direct the machine to HTTP boot with EFI an EFI image located in the
network over HTTP.

The image gets mounted as a local drive

Assumptions:

 - The machine's bios can do HTTP boot

 - The EFI boot image is HTTP available

Note how this testcase is reusing the template
:class:tcfl.pos.tc_pos_base; this allows to use this script to flash
firmware images (see :meth:`tcfl.pos.tc_pos0_base.deploy_10_flash` for
more information).

.. literalinclude:: /examples/test_efi_http_boot.py
   :language: python
   :pyobject: _test

Create an EFI system image with just the shell and a sample file and
upload to the HTTP server::

  # sudo dnf install -y mtools edk2-ovmf
  $ echo "Hello World!" > hello.txt
  $ /usr/share/tcf/mk-efi-image.sh boot.img hello.txt
  $ scp boot.img file.server:/var/www/html

Execute :download:`the testcase <../examples/test_efi_http_boot.py>`
with, indicating with the environment variable IMG_URL where the boot
URL is::

  $ export IMG_URL=http://file.server/boot.img
  $ tcf run -v /usr/share/tcf/examples/test_efi_http_boot.py
  INFO3/	toplevel @local [+0.5s]: version v0.14-444-gb45b53e-dirty
  INFO2/	toplevel @local [+0.5s]: scanning for test cases
  INFO3/	test_efi_http_boot.py @local [+3.6s]: queuing for pairing
  INFO3/glg6n2	test_efi_http_boot.py @local [+0.8s]: read property 'interfaces.console.default': 'None' [None]
  INFO1/zo6ots	test_efi_http_boot.py @huty-ehnc [+1.5s]: will run on target group 'ic=local/qu-06b-nw target=local/qu-06b:x86_64' (PID 10870 / TID 7f13b45cc580)
  INFO2/zo6otsD	test_efi_http_boot.py @huty-ehnc [+2.3s]: skipping image flashing (no environment IMAGE_FLASH*)
  PASS2/zo6ots	test_efi_http_boot.py @huty-ehnc [+2.4s]: deploy passed 
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+2.4s]: power cycling
  INFO2/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+32.0s]: power cycled
  INFO2/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+32.3s]: BIOS: waiting for main menu after power on
  ...
  INFO2/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+89.1s]: BIOS: confirming we are at toplevel menu
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+89.2s]: 01/BIOS-toplevel/EDKII Menu: found 'EDKII\\ Menu' at @264506-264516 on console local/qu-06b:serial0 [report-:zo6ots.console-target.qu-06b.serial0.txt]
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+90.8s]: BIOS:main menu: scrolling to 'Boot Manager Menu'
  ...
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+105.5s]: BIOS:Boot Manager Menu: scrolling to 'HTTP yka3'
  ...
  INFO2/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+105.9s]: BIOS:Boot Manager Menu/HTTP yka3: highlighted entry found
  INFO2/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+106.7s]: serial0: wrote 1B (\\r) to console
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+107.2s]: 14/Start__HTTP__Boot: found 'Start\\ HTTP\\ Boot' at @280753-280768 on console local/qu-06b:serial0 [report-:zo6ots.console-target.qu-06b.serial0.txt]
  ...
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+107.2s]:    console output: \\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+107.2s]:    console output: >>Start HTTP Boot over IPv4...
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]: 15/Downloading______: found 'Downloading\\.\\.\\.' at @280919-280933 on console local/qu-06b:serial0 [report-:zo6ots.console-target.qu-06b.serial0.txt]
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output:  over IPv4.....\\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output:   Station IP address is 10.291.183.9\\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output: \\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output:   URI: http://file.server//boot.img\\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output:   File Size: 110100480 Bytes\\r
  INFO3/zo6otsE#1	test_efi_http_boot.py @huty-ehnc|local/qu-06b [+110.6s]:    console output: \\r  Downloading...1%\\r  Downloading...2%
  PASS1/zo6ots	test_efi_http_boot.py @huty-ehnc [+110.6s]: evaluation passed 
  PASS0/	toplevel @local [+115.2s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:01:51.024391) - passed 
  
(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import os

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

        IMG_URL = os.environ.get("IMG_URL", None)
        if IMG_URL == None:
            raise tcfl.tc.blocked_e("No IMG_URL environment given")

        target.power.cycle()
        tcfl.biosl.boot_network_http(target, r"HTTP %(ID)s", IMG_URL)

        # expect something to happen:

        ## >>Start HTTP Boot over IPv4.....^M$
        ## Station IP address is 10.291.183.9^M$
        ## ^M$
        ## URI: http://file.server/boot.img^M$
        ## File Size: 110100480 Bytes^M$
        ## Downloading...1%^M  Downloading...2%^M  Downloading...
        ## Downloading...100
        target.expect("Start HTTP Boot")
        # let's just expect one Downloading because dep on the file
        # size not sure how many progress' will be printed
        target.expect("Downloading...")
