#! /usr/bin/python
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_qemu_bios_N:

Build, install and boot a N QEMU targets with modified BIOS, verify the changes
===============================================================================

A UEFI EDK2 BIOS is built with a modified vendor string; N targets
are booted into the Provisioning OS and *dmidecode* is used to verify
that the BIOS now reports as vendor string the change made.

This test showcases how to scale the previous :ref:`example
<example_qemu_bios>` to an unlimited number of targets by running the
processes in parallel (note in this one we skip the flashing, look at
:ref:`pos_deploy_N <_example_pos_deploy_N>` to add that). 

Sequentially its duration would be *O(N)* where as in parallel it is
only a function of having enough network and local resources to access
each.

This test will select N targets to flash and the network they are
both connected to; note the targets must support the *images*
interface (for flashing), a *bios* flashing target and of course, the
BIOS built must fit the target machines.

This example is meant to run on targets implemented by QEMU (as
created with the server configuration :func:`target_pos_add`), but it
can be adapted to any machine:

.. literalinclude:: /examples/test_qemu_bios_N.py
   :language: python
   :pyobject: _test

This can be used to implement a rapid BIOS development cycle where
changes are done, built, deployed and a workload is run on all the
machines simultaneously.

Execute :download:`the testcase <../examples/test_qemu_bios_N.py>`::

  $ git clone https://github.com/tianocore/edk2 edk2.git
  $ git -C edk2.git checkout cb5f4f45ce1f
  $ export EDK2_DIR=$HOME/edk2.git
  $ TARGETS=3 tcf run -vv /usr/share/tcf/examples/test_qemu_bios_N.py
  INFO2/		toplevel @local [+0.5s]: scanning for test cases
  INFO1/n7azod		.../test_qemu_bios_N.py @4ohw-6elg [+0.1s]: will run on target group 'ic=local-master/nwa target=local-master/qu-92a:x86_64 target1=local-master/qu-91a:x86_64 target2=local-master/qu-93a:x86_64' (PID 11815 / TID 7f2b8ee1c580)
  PASS2/n7azod		.../test_qemu_bios_N.py @4ohw-6elg [+0.2s]: configure passed 
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+0.2s]: build passed: 'sed -i '/Vendor/s|.*\\\\0"|"I am the vendor now\\\\0"|' '.../edk2.git/OvmfPkg/SmbiosPlatformDxe/SmbiosPlatformDxe.c'' @.../test_qemu_bios_N.py:148
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+0.3s]: re/building BaseTools in .../edk2.git
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+1.2s]: build passed: 'cd .../edk2.git; source ./edksetup.sh; ${MAKE:-make} -C BaseTools -j4' @.../test_qemu_bios_N.py:176
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+1.3s]: build passed: 'sed -i -e 's/-Werror//' '.../edk2.git/Conf/tools_def.txt'' @.../test_qemu_bios_N.py:181
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+1.3s]: re/building OVMF in .../edk2.git
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+18.5s]: build passed: 'cd .../edk2.git; source ./edksetup.sh; build -a X64 -t GCC5 -p OvmfPkg/OvmfPkgX64.dsc' @.../test_qemu_bios_N.py:188
  PASS2/n7azodB		.../test_qemu_bios_N.py @4ohw-6elg [+18.5s]: built BIOS
  PASS1/n7azod		.../test_qemu_bios_N.py @4ohw-6elg [+18.6s]: build passed 
  INFO0/n7azodDdrmzxiyw	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-93a [+27.5s]: uploading
  INFO0/n7azodDdrmzxiyw	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-93a [+27.6s]: uploaded
  PASS2/n7azod		.../test_qemu_bios_N.py @4ohw-6elg [+27.8s]: deploy passed 
  INFO2/n7azodE#1	.../test_qemu_bios_N.py @4ohw-6elg|local-master/nwa [+27.8s]: powered on
  INFO2/n7azodE#1b7cn	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-93a [+27.8s]: POS: rebooting into Provisioning OS [0/3]
  ...
  INFO2/n7azodE#1b73o	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-91a [+30.3s]: power cycled
  INFO2/n7azodE#1b7pz	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-92a [+30.3s]: power cycled
  ...
  INFO2/n7azodE#1b7pz	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-92a [+56.2s]: POS: got Provisioning OS shell
  INFO2/n7azodE#1b73o	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-91a [+56.4s]: POS: got Provisioning OS shell
  INFO2/n7azodE#1b7cn	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-93a [+56.4s]: POS: got Provisioning OS shell
  INFO2/n7azodE#1tcmt	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-91a [+57.0s]: ttyS0: wrote 18B (dmidecode -t bios<NL>) to console
  INFO2/n7azodE#1tcoa	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-93a [+57.0s]: ttyS0: wrote 18B (dmidecode -t bios<NL>) to console
  INFO2/n7azodE#1tceo	.../test_qemu_bios_N.py @4ohw-6elg|local-master/qu-92a [+57.0s]: ttyS0: wrote 18B (dmidecode -t bios<NL>) to console
  PASS1/n7azod		.../test_qemu_bios_N.py @4ohw-6elg [+57.7s]: evaluation passed 
  PASS0/		toplevel @local [+58.7s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:57.960897) - passed 
  
(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Notes:

- ``TARGETS``: (integer) number of targets to run simultaneously; note
  your server must be configured with that many targets that are all
  members of the same network for this to work. A current (awkward)
  way to find which targets are part of the *nwa* network::

    $ tcf list -vv -p interconnects.nwa.mac_addr | grep mac_addr -B1
      id: qu-80a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:50
    --
      id: qu-81a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:51
    --
      id: qu-82a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:52
    --
      id: qu-83a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:53
    --
      id: qu-84a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:54
    --
      id: qu-85a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:55
    --
      id: qu-86a
      interconnects.nwa.mac_addr: 02:a8:00:00:61:56
    ...

  Note you might need to also pass ``--threads=M`` to ``tcf run`` if
  ``TARGETS`` is greater than 10, where M is your number of targets
  plus two.

- ``-B`` can be passed to *tcf run* to skip the compilation phase if
  there is no need to recompile

"""

import collections
import os
import re
import subprocess
import sys
import threading

import commonl
import tcfl
import tcfl.tc
import tcfl.tl
import tcfl.pos

TARGETS = int(os.environ.get('TARGETS', 4))
MODE = os.environ.get('MODE', 'one-per-type')

@tcfl.tc.interconnect("ipv4_addr", mode = MODE)
@tcfl.tc.target('pos_capable and "bios" in images', count = TARGETS)
class _test(tcfl.tc.tc_c):

    def configure_00(self):
        if not 'EDK2_DIR' in os.environ:
            raise tcfl.tc.skip_e(
                "please export env EDK2_DIR pointing to path of "
                "configured, built or ready-to-build tree", dict(level = 0))
        self.builddir = os.environ["EDK2_DIR"]

        # select the targets that can be flashed with the images
        # interface all of them (target, target1, target2...) except
        # for the interconnect (ic).
        self.roles = []
        for role, target in self.target_group.targets.items():
            if 'images' in target.rt['interfaces']:
                self.roles.append(role)


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



    def deploy_50(self, ic):
        
        class rtb_data_c(object):
            def __init__(self):
                self.lock = threading.Lock()
                self.remote_file = None

        rtb_datas = collections.defaultdict(rtb_data_c)
        
        # Flash the new BIOS before power cycling; make sure we upload
        # the file only once per server
        local_file = os.path.join(
            self.builddir,
            "Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd")

        @self.threaded
        def _target_bios_flash(target, testcase, local_file):

            # upload only once to each server
            with self.lock:
                rtb_data = rtb_datas[target.rtb]
            with rtb_data.lock:
                if not rtb_data.remote_file:
                    rtb_data.remote_file = \
                        "OVMF_CODE.fd-" + self.kws['tc_hash']
                    target.report_info("uploading", level = 0)
                    target.store.upload(rtb_data.remote_file, local_file)
                    target.report_info("uploaded", level = 0)

            target.images.flash({ "bios" : rtb_data.remote_file },
                                upload = False)

        self.report_info("flashing BIOS", dlevel = 1)
        self.run_for_each_target_threaded(
            _target_bios_flash, (self, local_file, ), targets = self.roles)
        self.report_pass("flashed BIOS")


    def start_00(self, ic):
        ic.power.on()		# need the network to boot POS

        @self.threaded
        def _target_start(target):
            target.pos.boot_to_pos()

        self.run_for_each_target_threaded(
            _target_start, targets = self.roles)


    def eval(self):

        @self.threaded
        def _target_eval(target):
            target.shell.run("dmidecode -t bios",
                             re.compile("Vendor:.*Irving"))

        self.run_for_each_target_threaded(
            _target_eval, targets = self.roles)
