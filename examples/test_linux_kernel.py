#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_linux_kernel:

Build, install and boot a Linux kernel alongside a given OS
===========================================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, build a Linux kernel and modules, deploy an OS into the
target along with the just built kernel/modules. Then power cycle into
the installed OS with the new kernel.

From there on, different tests to exercise the new kernel could be
executed etc. This is a very common pattern for rapid development of
kernel code.

When the same target (for caching purposes) and build trees are used,
it allows for very quick turn arounds to test new code in the
hardware.

Builds on :ref:`deploying an OS to a target <example_pos_base>` and
:ref:`deploying files to a target <example_deploy_files>`. You can
find the list of OS images :ref:`installed in the server
<pos_list_images>`.

The kernel deployment process removes any other kernel that was
available in the target's ``/boot`` directory, replacing it with the
just built one, so the bootloader is configured to boot it.

**TIPS**:

- always use the same target (give ``-t 'nwX or TARGETX'`` so that the
  content is cached and each run doesn't try to send the your built
  kernel to a new target but just the bare changes. See methods for
  doing this in the :ref:`how-to section <howto_target_keep_acquired>`

- note depending on your connection to the target, sending the code to
  the target can take a long time and even release the target as
  inactive.

  stripping the modules helps (only debug info!), as the debug info
  accumulates and is usually not needed in the target.

.. literalinclude:: /examples/test_linux_kernel.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_linux_kernel.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ mkdir -p build
  $ cp CONFIGFILE build/.config
  $ make -C PATH/TO/SRC/linux O=build oldconfig
  $ make -C build -j all
  
  $ LK_ROOTDIR=$PWD/build IMAGE=clear tcf run -v /usr/share/tcf/examples/test_linux_kernel.py
  INFO1/ormorh	  ..../test_linux_kernel.py#_test @3hyt-uo3g: will run on target group 'ic=localhost/nwa target=localhost/qu04a:x86_64'
  PASS1/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: re/building kernel in /home/inaky/t/gp/build-linux
  PASS0/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: re/built kernel in /home/inaky/t/gp/build-linux
  PASS1/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: installing kernel to /tmp/tcf.run-X2SMmK/ormorh/root
  PASS0/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: installed kernel to /tmp/tcf.run-X2SMmK/ormorh/root
  PASS2/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: output: Cannot find LILO.
  PASS2/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: stripping debugging info
  PASS1/ormorhB	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: stripped debugging info
  PASS1/ormorh	  ..../test_linux_kernel.py#_test @3hyt-uo3g: build passed 
  INFO3/ormorhD	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/nwa: Powering on
  INFO2/ormorhD	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/nwa: Powered on
  INFO3/ormorhDPOS  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: POS: rebooting into Provisioning OS [0/3]
  INFO3/ormorhDPOS  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: POS: setting target to PXE boot Provisioning OS
  ...
  INFO3/ormorhDPOS  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: POS: rsynced clear:live:29100::x86_64 from 192.168.97.1::images to /dev/sda5
  ...
  PASS3/ormorhDPOS  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: linux kernel transferred
  INFO3/ormorhDPOS  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: POS: configuring bootloader
  ...
  PASS2/ormorh	  ..../test_linux_kernel.py#_test @3hyt-uo3g: deploy passed 
  INFO3/ormorhE#1	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/nwa: Powering on
  INFO2/ormorhE#1	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/nwa: Powered on
  ...
  INFO2/ormorhE#1	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: wrote 'echo I booted' to console 'localhost/qu04a:<default>'
  PASS3/ormorhE#1	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: found expected `I booted` in console `localhost/qu04a:default` at 0.01s
  PASS2/ormorhE#1	  ..../test_linux_kernel.py#_test @3hyt-uo3g|localhost/qu04a: eval passed: found expected `I booted` in console `localhost/qu04a:default` at 0.01s
  ...
  PASS1/ormorh	  ..../test_linux_kernel.py#_test @3hyt-uo3g: evaluation passed 
  INFO0/ormorh	  ..../test_linux_kernel.py#_test @3hyt-uo3g: WARNING!! not releasing targets
  PASS0/            toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:03:18.911685) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import subprocess

import commonl
import tcfl.tc
import tcfl.tl
import tcfl.pos

class _test(tcfl.pos.tc_pos_base):
    """
    Build, install and boot a linux kernel
    """

    def build_00(self, ic, target):
        if not 'LK_BUILDDIR' in os.environ:
            raise tcfl.tc.skip_e(
                "please export env LK_BUILDDIR pointing to path of "
                "configured, built or ready-to-build linux kernel tree")
        builddir = os.environ["LK_BUILDDIR"]
        rootdir = os.environ.get("LK_ROOTDIR", self.tmpdir + "/root")

        # update the build
        #
        ## $ make -C BUILDDIR all
        ## ...
        #
        target.report_pass("re/building kernel in %s" % builddir, dlevel = -1)
        output = subprocess.check_output(
            "${MAKE:-make} -C %s all" % builddir,
            shell = True, stderr = subprocess.STDOUT)
        target.report_pass("re/built kernel in %s" % builddir,
                           dict(output = output),
                           alevel = 0, dlevel = -2)

        target.report_pass("installing kernel to %s" % rootdir, dlevel = -1)
        # will run to install the kernel to our fake root dir
        #
        ## $ make INSTALLKERNEL=/dev/null \
        ##       INSTALL_PATH=ROOTDIR/boot INSTALL_MOD_PATH=ROOTDIR \
        ##       install modules_install
        ## sh PATH/linux.git/arch/x86/boot/install.sh 4.19.5 arch/x86/boot/bzImage \
	##    System.map "../root-linux/boot"
        ## Cannot find LILO.
        ## INSTALL arch/x86/crypto/blowfish-x86_64.ko
        ## INSTALL arch/x86/crypto/cast5-avx-x86_64.ko
        ## INSTALL arch/x86/crypto/cast6-avx-x86_64.ko
        ## INSTALL arch/x86/crypto/des3_ede-x86_64.ko
        ## INSTALL arch/x86/crypto/sha1-mb/sha1-mb.ko
        ## ...
        #
        # note that:
        #
        # - INSTALLKERNEL: shortcircuit kernel installer, not needed,
        #   since we won't boot it in the machine doing the building
        #
        # - LILO will not we found, we don't care -- we only want the
        #   files in rootdir/
        commonl.makedirs_p(rootdir + "/boot")
        output = subprocess.check_output(
            "${MAKE:-make} -C %s INSTALLKERNEL=ignoreme"
            " INSTALL_PATH=%s/boot INSTALL_MOD_PATH=%s"
            " install modules_install" % (builddir, rootdir, rootdir),
            shell = True, stderr = subprocess.STDOUT)
        target.report_pass("installed kernel to %s" % rootdir,
                           dict(output = output), dlevel = -2)

        target.report_pass("stripping debugging info")
        subprocess.check_output(
            "find %s -iname \*.ko | xargs strip --strip-debug" % rootdir,
            shell = True, stderr = subprocess.STDOUT)
        target.report_pass("stripped debugging info", dlevel = -1)
    
    def deploy_00(self, ic, target):
        # tell the deployment code to rsync our fake rootdir over the
        # /boot and /lib/modules/VERSION dirs in the target
        rootdir = os.environ.get("LK_ROOTDIR", self.tmpdir + "/root")
        target.deploy_linux_kernel_tree = rootdir
        self.deploy_image_args = dict(extra_deploy_fns = [
            tcfl.pos.deploy_linux_kernel ])
    
    def eval(self, ic, target):
        # power cycle to the new kernel
        target.shell.run("echo I booted", "I booted")
        output = target.shell.run("uname -a", output = True, trim = True)
        target.report_pass("uname -a: %s" % output.strip())
        
