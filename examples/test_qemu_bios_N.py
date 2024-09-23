#! /usr/bin/python3
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
:ref:`pos_deploy_N <example_pos_deploy_N>` to add that). 

Sequentially its duration would be *O(N)* where as in parallel it is
only a function of having enough network and local resources to access
each.

This test will select N targets to flash and the network they are
both connected to; note the targets must support the *images*
interface (for flashing), a *bios* flashing target and of course, the
BIOS built must fit the target machines.

This example is meant to run on targets implemented by QEMU (as
created with the server configuration :func:`pos_target_add
<conf_00_lib_pos.pos_target_add>`), but it can be adapted to any
machine:

.. literalinclude:: /examples/test_qemu_bios_N.py
   :language: python
   :pyobject: _test

This can be used to implement a rapid BIOS development cycle where
changes are done, built, deployed and a workload is run on all the
machines simultaneously.

Execute :download:`the testcase <../examples/test_qemu_bios_N.py>`::

  $ sudo dnf install -y  gcc git iasl make nasm  # or apt install -y
  $ git clone https://github.com/tianocore/edk2 edk2.git
  $ git -C edk2.git submodule update --init
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

import test_qemu_bios

# note we are inheriting test_qemu_bios which ALREADY is asking for an
# interconnect and 1 target; so we ask for TARGETS-1 more and done
@tcfl.tc.target('pos_capable and interfaces.images.bios.instrument', count = TARGETS - 1)
class _test(test_qemu_bios._test):

    # test_qemu_bios._test.configure_00 will be run here

    def configure_10(self):
        # select the targets that can be flashed with the images
        # interface all of them (target, target1, target2...) except
        # for the interconnect (ic).
        self.roles = []
        for role, target in self.target_group.targets.items():
            if 'images' in target.rt['interfaces']:
                self.roles.append(role)


    # test_qemu_bios._test.build_00 will be run here

    def deploy_50(self, ic):	# overrides test_qemu_bios._test.deploy_50
        
        class server_data_c(object):
            def __init__(self):
                self.lock = threading.Lock()
                self.remote_file = None

        # keyed by server URL, this means we'll have only ONE entry
        # per server, so we'll only upload once to each server.
        server_datas = collections.defaultdict(server_data_c)
        
        # Flash the new BIOS before power cycling; make sure we upload
        # the file only once per server
        local_file = os.path.join(
            self.builddir,
            "Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd")

        @self.threaded
        def _target_bios_flash(target, testcase, local_file):

            # upload only once to each server
            with self.lock:
                server_data = server_datas[target.server]
            with server_data.lock:
                if not server_data.remote_file:
                    server_data.remote_file = \
                        "OVMF_CODE.fd-" + self.kws['tc_hash']
                    target.report_info("uploading", level = 0)
                    target.store.upload(server_data.remote_file, local_file)
                    target.report_info("uploaded", level = 0)

            target.images.flash({ "bios" : server_data.remote_file },
                                upload = False)

        self.report_info("flashing BIOS", dlevel = -1)
        self.run_for_each_target_threaded(
            _target_bios_flash, (self, local_file, ), targets = self.roles)
        self.report_pass("flashed BIOS", dlevel = -1)


    def start_00(self, ic):	# overrides test_qemu_bios._test.start_50()
        ic.power.on()		# need the network to boot POS

        @self.threaded
        def _target_start(target):
            target.pos.boot_to_pos()

        self.run_for_each_target_threaded(
            _target_start, targets = self.roles)


    def eval(self):		# overrides test_qemu_bios._test.eval()

        @self.threaded
        def _target_eval(target):
            target.shell.run("dmidecode -t bios",
                             re.compile(f"Vendor:.*{self.new_vendor_name}"))
            target.report_pass(
                f"BIOS reports the new vendor name as: {self.new_vendor_name}")

        self.run_for_each_target_threaded(
            _target_eval, targets = self.roles)
