#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_qemu_bios:

Build, install and boot a QEMU target with modified BIOS, verify the changes
============================================================================

A UEFI EDK2 BIOS is built with a modified vendor string; it is then
flashed into the target using the *images* interface; the target is
then booted into the Provisioning OS and *dmidecode* is used to verify
that the BIOS now reports the changed vendor string.

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

Execute :download:`the testcase <../examples/test_qemu_bios.py>` with
(where *IMAGE* is the name of a Linux OS image :ref:`installed in the
server <pos_list_images>`); install dependencies first (use whatever
command fits your distribution)::

  # dnf install -y nasm acpica-tools gcc make libuuid-devel git
  # apt-get install build-essential uuid-dev iasl git gcc-5 nasm

now run the testcase::

  $ git clone https://github.com/tianocore/edk2 edk2.git
  $ git -C edk2.git checkout cb5f4f45ce1f
  $ export EDK2_DIR=$HOME/edk2.git 
  $ IMAGE=clear tcf run -vv /usr/share/tcf/examples/test_qemu_bios.py
  INFO2/	toplevel @local [+0.5s]: scanning for test cases
  INFO1/u5v3	.../test_qemu_bios.py @4ohw-epcv [+0.0s]: will run on target group 'ic=local-master/nwa target=local-master/qu-93a:x86_64' (PID 14959 / TID 7fa056783580)
  PASS2/u5v3	.../test_qemu_bios.py @4ohw-epcv [+0.2s]: configure passed 
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+0.2s]: build passed: 'sed -i '/Vendor/s|.*\\\\0"|"I am the vendor now\\\\0"|' '.../edk2.git/OvmfPkg/SmbiosPlatformDxe/SmbiosPlatformDxe.c'' @.../test_qemu_bios.py:92
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+0.2s]: re/building BaseTools in .../edk2.git
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+1.3s]: build passed: 'cd .../edk2.git; source ./edksetup.sh; ${MAKE:-make} -C BaseTools -j4' @.../test_qemu_bios.py:120
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+1.3s]: build passed: 'sed -i -e 's/-Werror//' '.../edk2.git/Conf/tools_def.txt'' @.../test_qemu_bios.py:125
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+1.3s]: re/building OVMF in .../edk2.git
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+18.5s]: build passed: 'cd .../edk2.git; source ./edksetup.sh; build -a X64 -t GCC5 -p OvmfPkg/OvmfPkgX64.dsc' @.../test_qemu_bios.py:132
  PASS2/u5v3B	.../test_qemu_bios.py @4ohw-epcv [+18.5s]: built BIOS
  PASS1/u5v3	.../test_qemu_bios.py @4ohw-epcv [+18.6s]: build passed 
  INFO2/u5v3D	.../test_qemu_bios.py @4ohw-epcv|local-master/nwa [+144.8s]: powered on
  ...
  PASS2/u5v3D	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+258.1s]: deployed clear:live:29100::x86_64
  PASS2/u5v3	.../test_qemu_bios.py @4ohw-epcv [+258.2s]: deploy passed 
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/nwa [+258.2s]: powered on
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+258.2s]: POS: setting target not to PXE boot Provisioning OS
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+260.8s]: power cycled
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+275.2s]: ttyS0: wrote 5B (root<NL>) to console
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+276.1s]: ttyS0: wrote 29B (export PS1="TCF-u5v32g:$PS1"<NL>) to console
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+277.2s]: ttyS0: wrote 40B (test ! -z "$BASH" && set +o vi +o emacs<NL>) to console
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+278.3s]: ttyS0: wrote 33B (trap 'echo ERROR''-IN-SHELL' ERR<NL>) to console
  INFO2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+279.0s]: ttyS0: wrote 18B (dmidecode -t bios<NL>) to console
  PASS2/u5v3E#1	.../test_qemu_bios.py @4ohw-epcv|local-master/qu-93a [+279.6s]: New BIOS is reporting via DMI/bios Vendor field
  PASS1/u5v3	.../test_qemu_bios.py @4ohw-epcv [+279.6s]: evaluation passed 
  PASS0/	toplevel @local [+282.4s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:04:41.636762) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Notes:

- ``-B`` can be passed to *tcf run* to skip the compilation phase if
  there is no need to recompile

"""

import re
import os
import subprocess

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable and interfaces.images.bios.instrument')
class _test(tcfl.tc.tc_c):

    def configure_00(self):
        if not 'EDK2_DIR' in os.environ:
            raise tcfl.tc.skip_e(
                "please export env EDK2_DIR pointing to path of "
                "configured, built or ready-to-build tree", dict(level = 0))
        self.builddir = os.environ["EDK2_DIR"]


    def build_00(self):
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
            EDK_DIR = self.builddir,
            GCC5_X64_PREFIX = "x86_64-linux-gnu-",
            CC_FLAGS = "-t GCC5 -n 4 --cmd-len=65536 -b DEBUG --hash" ,
            EDK_TOOLS_PATH = os.path.join(self.builddir, "BaseTools"),
        )
        env['OVMF_FLAGS'] = "%(CC_FLAGS)s -FD_SIZE_2MB" % env

        self.report_pass("re/building BaseTools in %s" % self.builddir)
        self.shcmd_local(
            "cd %s;"
            " source ./edksetup.sh;"
            " ${MAKE:-make} -C BaseTools -j4" % self.builddir, env = env)

        # remove -Werror from the configuratio, as there are warnings
        # that otherwise kill the build
        self.shcmd_local(
            "sed -i -e 's/-Werror//' '%s/Conf/tools_def.txt'" % self.builddir)

        self.report_pass("re/building OVMF in %s" % self.builddir)
        self.shcmd_local(
            "cd %(EDK_DIR)s;"
            " source ./edksetup.sh;"
            " build -a X64 -t GCC5 -p OvmfPkg/OvmfPkgX64.dsc"
            % env, env = env)

        self.report_pass("built BIOS")


    def deploy_90(self, target):
        # Flash the new BIOS before power cycling
        target.images.flash(
            {
                "bios" : os.path.join(
                    self.builddir,
                    "Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd")
            },
            upload = True)

    def eval(self, ic, target):
        ic.power.cycle()		# need the network to boot POS
        target.pos.boot_to_pos()
        target.shell.run("dmidecode -t bios",
                         re.compile("Vendor:.*I am the vendor now"))
        target.report_pass("New BIOS is reporting via DMI/bios Vendor field")
