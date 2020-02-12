#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_qemu_bios:

Build, install and boot a QEMU machine with modified BIOS
=========================================================

Given a QEMU target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, build a UEFI BIOS with the vendor field modified,
provision the OS and the new BIOS, boot into it and verify via
*dmidecode* that the BIOS reports the new vendor information.

Builds on :ref:`deploying an OS to a target <example_pos_base>` and
:ref:`deploying files to a target <example_deploy_files>`. You can
find the list of OS images :ref:`installed in the server
<pos_list_images>`.

This demonstrates how TCF can be used to create a fast development
cycle for working on changes to the BIOS code; for using any other
machine than QEMU, something with a :mod:`images <ttbl.images>`
interface that can flash the BIOS can be used.

**TIPS**:

- always use the same target (give ``-t 'nwX or TARGETX'`` so that the
  content is cached and each run doesn't try to send the your built
  kernel to a new target but just the bare changes. See methods for
  doing this in the :ref:`how-to section <howto_target_keep_acquired>`

- if only the BIOS code is modified and there is no need to
  re-provision the OS, method *disabled_deploy_50()* can be renamed
  to *deploy_50()* to override the template inherited from
  :class:`tcfl.pos.tc_pos_base` and skip the OS provisioning step.

.. literalinclude:: /examples/test_qemu_bios.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_qemu_bios.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ git clone https://github.com/tianocore/edk2 edk2.git
  $ EDK2_DIR=$HOME/edk2.git IMAGE=clear tcf run -v /usr/share/tcf/examples/test_qemu_bios.py

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import subprocess

import tcfl.tc
import tcfl.tl
import tcfl.pos

class _test(tcfl.pos.tc_pos_base):
    def configure_00(self):
        if not 'EDK2_DIR' in os.environ:
            raise tcfl.tc.skip_e(
                "please export env EDK2_DIR pointing to path of "
                "configured, built or ready-to-build tree")
        self.builddir = os.environ["EDK2_DIR"]

    def build_00(self, target):
        # Modify the BIOS vendor string to showcase a change
        #
        # Backslashes here are killing us; the original C code is
        #
        ## #define TYPE0_STRINGS \
        ##   "EFI Development Kit II / OVMF\0"     /* Vendor */ \
        ##   "0.0.0\0"                             /* BiosVersion */ \
        ##   "02/06/2015\0"                        /* BiosReleaseDate */
        #
        # So we need to replace all in the Vendor string until the \0,
        # but we need to escape that \\ for both python and the
        # shell. bleh.
        self.shcmd_local(
            r"sed -i"
            " '/Vendor/s|.*\\\\0\"|\"I am the vendor now\\\\0\"|'"
            " '%s/OvmfPkg/SmbiosPlatformDxe/SmbiosPlatformDxe.c'"
            % self.builddir)

        #
        # Build the new BIOS
        #
        # I lifted the build instructions of the Fedora 29 spec file
        # and simplified to the max, but I only know them to work on
        # this git version; complain otherwise
        rev = subprocess.check_output(
            "git -C '%s' rev-parse HEAD" % self.builddir,
            shell = True)
        if rev.strip() != "cb5f4f45ce1fca390b99dae5c42b9c4c8b53deea":
            self.report_info(
                "WARNING!! WARNING!!! These build process only verified to"
                " workwith git version cb5f4f45ce, found %s" % rev,
                level = 0)
        env = dict(
            GCC5_X64_PREFIX = "x86_64-linux-gnu-",
            CC_FLAGS = "-t GCC5 -n 4 --cmd-len=65536 -b DEBUG --hash" ,
        )
        env['OVMF_FLAGS'] = "%(CC_FLAGS)s -FD_SIZE_2MB" % env

        self.report_pass("re/building BaseTools in %s" % self.builddir,
                         dlevel = -1)
        self.shcmd_local(
            "${MAKE:-make} -C '%s/BaseTools' -j4" % self.builddir)

        # there are warnings that otherwise kill the build
        self.shcmd_local(
            "sed -i -e 's/-Werror//' '%s/Conf/tools_def.txt'" % self.builddir)

        self.report_pass("re/building OVMF in %s" % self.builddir, dlevel = -1)
        self.shcmd_local(
            "cd %s && build $OVMF_FLAGS -a X64 -p OvmfPkg/OvmfPkgX64.dsc"
            % self.builddir)

        # Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd
        target.report_pass("built BIOS", dlevel = -1)

    def disabled_deploy_50(self, ic, target):
        # remove "disabled_" to override the method from the
        # tcfl.pos.tc_pos_base that flashes the OS--this makes the
        # scrip to only build, flash the bios, powercycle into the
        # installed OS and run the eval* steps--which works if you
        # know
        pass

    def deploy_90(self, target):
        # Flash the new BIOS before power cycling
        target.images.flash(
            {
                "bios" : os.path.join(
                    self.builddir,
                    "Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd")
            },
            upload = True)

    def eval(self, target):
        # power cycle to the new kernel
        target.shell.run("dmidecode -t bios", "Vendor: I am the vendor now2")
        target.report_pass("New BIOS is reporting via DMI/bios Vendor field")
