#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos_deploy_N:

Deploy an OS image to many targets targets simultaneously
=========================================================

Given N targets that can be provisioned with :ref:`Provisioning OS
<provisioning_os>`, deploy to them images :ref:`available in the
server <pos_list_images>`.

This test showcases how to scale the provisioning :ref:`example
<example_pos_deploy_2>` to an unlimited number of targets by running
the processes in parallel. Sequentially its duration would be *O(N)*
where as in parallel it is only a function of network and local
resources to access each.

This test will select N targets to provision and the network they are
both connected to; the deploying happens over the network (thus why
the network is requested).

.. literalinclude:: /examples/test_pos_deploy_N.py
   :language: python
   :pyobject: _test

This can be used to implement cloud workloads where brining up the
cloud (eg: Kubernetes or OpenCloud cluster is part of the workload) in
a private, isolated network with fresh OS instalations.

Execute :download:`the testcase <../examples/test_pos_deploy_N.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`available in
the server <pos_list_images>`)::

  $ IMAGE=clear TARGETS=3 tcf run -v /usr/share/tcf/examples/test_pos_deploy_N.py
  INFO1/x9uz	.../test_pos_deploy_2.py#_test @sv3m-fmav: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64 target1=localhost/qu05b:x86_64'
  PASS1/x9uz	.../test_pos_deploy_2.py#_test @sv3m-fmav: evaluation passed 
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:02:43.525650) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Environment variables that can be set to control:

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

  thus on this network we'd be able to operate with a maximum of
  ``TARGETS=6``.

  Note you might need to also pass ``--threads=M`` to ``tcf run`` if
  ``TARGETS`` is greater than 10, where M is your number of targets
  plus two.

"""

import os
import sys

import tcfl
import tcfl.tc
import tcfl.tl
import tcfl.pos

TARGETS = int(os.environ.get('TARGETS', 4))
MODE = os.environ.get('MODE', 'one-per-type')

@tcfl.tc.interconnect("ipv4_addr", mode = MODE)
@tcfl.tc.target('pos_capable', count = TARGETS)
class _test(tcfl.tc.tc_c):
    image_requested = None

    def configure_00(self):
        if self.image_requested == None:
            if not 'IMAGE' in os.environ:
                raise tcfl.tc.blocked_e(
                    "No image to install specified, set envar IMAGE")
            self.image_requested = os.environ["IMAGE"]

        # select the targets that can be flashed...this is basically
        # all of them (target, target1, target2...) except for the
        # interconnect (ic).
        self.roles = []
        for role, target in self.target_group.targets.items():
            if 'pos_capable' in target.rt:
                self.roles.append(role)


    def deploy_50(self, ic):
        ic.power.cycle()

        @self.threaded
        def _target_pos_deploy(target, ic):
            return target.pos.deploy_image(ic, self.image_requested)

        self.run_for_each_target_threaded(
            _target_pos_deploy, (ic, ), targets = self.roles)


    def start_00(self, ic):
        ic.power.on()

        @self.threaded
        def _target_start(target):
            target.pos.boot_normal()
            # higher timeout, some VM implementations take more when
            # you spin up 80 of them at the same time...
            target.shell.up(user = 'root', timeout = 120)

        self.run_for_each_target_threaded(
            _target_start, targets = self.roles)


    def eval(self):

        @self.threaded
        def _target_eval(target):
            target.shell.run("echo 'I ''booted'", "I booted")

        self.run_for_each_target_threaded(
            _target_eval, targets = self.roles)


    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
