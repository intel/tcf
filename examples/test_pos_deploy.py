#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
.. _example_pos_deploy:

Deploy an OS image to a target
==============================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`.

- to copy other content to the image after deploying the OS, see
  :ref:`this example <example_deploy_files>`

This test will select two targets: a computer to provision and the
network it is connected to; the deploying happens over the network
(thus why the network is requested).

To accomplish this, the target is first booted in Provisioning mode, a
version of a Linux OS whose root filesystem runs off a read-only NFS
server in the target; provisioning mode is reached depending on the
type of target, via PXE boot or other means. The client then can drive
partitioning of the target's storage and rsyncs root filesystem images
in.

If the rootfilesystem is already initialized present, rsync will
transfer only changes, or refresh, which is much faster.

This can be used to start every single test with *first install a
fresh OS*.

.. literalinclude:: /examples/test_pos_deploy.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_pos_deploy.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_pos_deploy.py
  INFO1/cz1c	 .../test_pos_deploy.py#_test @sv3m-twgl: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64'
  INFO1/cz1cDPOS .../test_pos_deploy.py#_test @sv3m-twgl|localhost/qu06b: POS: rsyncing clear:desktop:29820::x86_64 from 192.168.98.1::images to /dev/sda5
  PASS1/cz1c	 .../test_pos_deploy.py#_test @sv3m-twgl: evaluation passed 
  PASS0/	 toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:03:21.020510) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

In general, you can use *tcf run test_pos_deploy.py* to provision
machines any time for any reason from the command line.

"""

import os
import re
import string

import commonl
import tcfl.tc
import tcfl.tl
import tcfl.pos

MODE = os.environ.get('MODE', 'one-per-type')

@tcfl.tc.interconnect("ipv4_addr", mode = MODE)
@tcfl.tc.target("pos_capable")
class _test(tcfl.tc.tc_c):

    image_requested = None
    image = "not deployed"

    # format for specifying images to flash is IMAGE:NAME[ IMAGE:NAME[..]]]
    _image_flash_regex = re.compile(r"\S+:\S+( \S+:\S+)*")

    @tcfl.tc.serially()			# otherwise it runs out of order
    def deploy_10_flash(self, target):
        """
        Flash anything specified in IMAGE_FLASH* environment variables
        """
        # this also in tcfl/pos.tc_pos0_base.deploy_10-flash
        target_id_safe = commonl.name_make_safe(
            target.id, string.ascii_letters + string.digits)
        target_fullid_safe = commonl.name_make_safe(
            target.fullid, string.ascii_letters + string.digits)
        target_type_safe = commonl.name_make_safe(
            target.type, string.ascii_letters + string.digits)

        source = None	# keep pylint happy
        for source in [
                "IMAGE_FLASH_%s" % target_type_safe,
                "IMAGE_FLASH_%s" % target_fullid_safe,
                "IMAGE_FLASH_%s" % target_id_safe,
                "IMAGE_FLASH",
            ]:
            flash_image_s = os.environ.get(source, None)
            if flash_image_s:
                break
        else:
            self.report_info(
                "skipping image flashing (no environment IMAGE_FLASH*)")
            return

        if not self._image_flash_regex.search(flash_image_s):
            raise tcfl.tc.blocked_e(
                "image specification in %s does not conform to the form"
                " IMAGE:NAME[ IMAGE:NAME[..]]]" % source)
        flash_images = {}
        for entry in flash_image_s.split(" "):
            name, value = entry.split(":", 1)
            flash_images[name] = value
        target.report_info("uploading flash images to remoting server")
        target.images.flash(flash_images, upload = True)

    def deploy_50_os(self, ic, target):

        if self.image_requested == None:
            if not 'IMAGE' in os.environ:
                raise tcfl.tc.blocked_e(
                    "No image to install specified, set envar IMAGE")
            self.image_requested = os.environ["IMAGE"]
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        self.image = target.pos.deploy_image(ic, self.image_requested)
        target.report_pass("deployed %s" % self.image)

    def start(self, ic, target):
        # fire up the target, wait for a login prompt, ensure the
        # network is on so the PXE controller can direct the target
        # where to boot--also, if we skip deployment, ensures we have
        # networking on
        ic.power.on()
        target.pos.boot_normal()		# boot no Provisioning OS
        target.shell.up(user = 'root')		# login as root
        ic.release()			# if we don't need the network

    def eval(self, target):
        # do our test
        target.shell.run("echo I booted", "I booted")

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
