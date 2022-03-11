#! /usr/bin/env python3
#
# Copyright (c) 2019-22 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_kickstart_network_install:

Boot a machine over PXE to a kickstart network installer (Fedora / CentOS / RHEL...)
====================================================================================

Given a target that can boot PXE, have it boot the network image for a
kickstart OS and start the installation process. If a kickstart file
is provided, use that (otherise the user needs to drive the process
manually themselves).

.. literalinclude:: /examples/test_kickstart_network_install.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_kickstart_network_install.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ tcf run -v /usr/share/tcf/examples/test_example_kickstart_install.py
  PASS0/	 toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:01:51.845546) - passed


optionally you can add the following environment vars to tcf to
control the source repository and kickstart file url:

REPO_URL is the path to the kickstart network boot images (eg REPO_URL/images/pxeboot/vmlinuz

- CentOS::

    $ tcf -e REPO_URL=https://mirrors.edge.kernel.org/centos/8-stream/BaseOS/x86_64/os/ ...

- Fedora::

    $ tcf -e REPO_URL=http://mirrors.kernel.org/fedora/releases/35/releases/34/Everythin/x86_64/os ...

Add an specific kickstart file::

  $ tcf -e KICKSTART_URL=http://PATH/TO/file.ks ...

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import re
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

        repo_url = os.environ.get(
            "REPO_URL",
            # Centos: https://mirrors.edge.kernel.org/centos/8-stream/BaseOS/x86_64/os/
            "http://mirrors.kernel.org/fedora/releases/35/releases/34/Everythin/x86_64/os")

        kickstart_url = os.environ.get("KICKSTART_URL", "")
        if kickstart_url:
            target.kw_set("kickstart_url", "ks=" + kickstart_url)
        else:
            target.kw_set("kickstart_url", "")

        tcfl.tl.ipxe_sanboot_url(target, "skip")	# skip: we'll drive

        prompt_orig = target.shell.prompt_regex
        try:
            target.shell.prompt_regex = "iPXE>"

            target.shell.run(
                f"set repo {repo_url}")
            target.shell.run(
                "set pxeboot ${repo}/images/pxeboot")
            target.shell.run(
                "kernel ${pxeboot}/vmlinuz"
                " initrd=initrd.img"
                " repo=${repo}"
                " console=%(linux_serial_console_default)s,115200n81"
                " text"		# so we can install over serial console
                " %(kickstart_url)s" % target.kws)
            target.report_info("loading initrd, might take a while")
            target.shell.run(
                "initrd ${pxeboot}/initrd.img", timeout = 300)
            target.report_info("booting")
            target.send(
                "boot")
        finally:
            target.shell.prompt_regex = prompt_orig

        # Look for installation signs on the serial console, so we can
        # tackle checkpoints for things we know the Anaconda installer
        # prints
        target.expect(re.compile("anaconda.*started"),
                      timeout = 200)
        target.expect(re.compile("Running pre-installation scripts"),
                      timeout = 200)
        target.expect(re.compile("Setting up the installation environment"),
                      timeout = 200)
        target.report_info("installation running now")

        target.expect(re.compile("Performing post-installation setup tasks"),
                      # give it about 15min; assumes a reasonably fast link
                      timeout = 16 * 60)
        target.report_info("post-installation running now")

        target.expect(re.compile("Installing boot loader"),
                      timeout = 200)
        target.report_info("installing boot-loader")

        target.expect(re.compile("Performing post-installation setup tasks"),
                      timeout = 200)
        target.report_info("post-installation setup")

        target.expect(re.compile("Running post-installation scripts"),
                      timeout = 200)
        target.report_info("post-installation scripts")

        target.expect(re.compile("Installation complete"),
                      timeout = 200)
        target.report_pass("Installation complete")
