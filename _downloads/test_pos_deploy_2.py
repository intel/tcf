#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos_deploy_2:

Deploy an OS image to two targets simultaneously
================================================

Given two target that can be provisioned with :ref:`Provisioning OS
<provisioning_os>`, deploy to them images :ref:`available in the
server <pos_list_images>`.

This test will select three targets: two machines to provision and the
network they are both connected to; the deploying happens over the
network (thus why the it is requested).

.. literalinclude:: /examples/test_pos_deploy_2.py
   :language: python
   :pyobject: _test

This can be used to implement client/server testcases, where one
target is configured as a server, the other as client and tests are
executed in a private, isolated network with fresh OS instalations. It
can be easily extended to any number of targets by adding more
:func:`tcfl.tc.target` decorators, and *deploy_targetN()* and
*start_targetN()* methods.

Execute :download:`the testcase <../examples/test_pos_deploy_2.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`available in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_pos_deploy_2.py
  INFO1/x9uz	.../test_pos_deploy_2.py#_test @sv3m-fmav: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64 target1=localhost/qu05b:x86_64'
  PASS1/x9uz	.../test_pos_deploy_2.py#_test @sv3m-fmav: evaluation passed 
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:02:43.525650) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import re

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    Provision two PC targets at the same time with the Provisioning OS
    """
    image_requested = None
    image_requested1 = None

    @tcfl.tc.serially()
    def deploy_00(self, ic):
        ic.power.on()
        if self.image_requested == None:
            if not 'IMAGE' in os.environ:
                raise tcfl.tc.blocked_e(
                    "No image to install specified, set envar IMAGE")
            self.image_requested = os.environ["IMAGE"]
        self.image_requested1 = os.environ.get("IMAGE1", self.image_requested)

    @tcfl.tc.concurrently()
    def deploy_10_target(self, ic, target):
        image = target.pos.deploy_image(ic, self.image_requested)
        target.report_pass("deployed %s" % image, dlevel = -1)

    @tcfl.tc.concurrently()
    def deploy_10_target1(self, ic, target1):
        image = target1.pos.deploy_image(ic, self.image_requested1)
        target1.report_pass("deployed %s" % image, dlevel = -1)

    @tcfl.tc.serially()
    def start_ic(self, ic):
        ic.power.on()			# in case we skip deploy

    def start_target(self, target):
        target.pos.boot_normal()
        target.shell.up(user = 'root')
        
    def start_target1(self, target1):
        target1.pos.boot_normal()
        target1.shell.up(user = 'root')

    def eval(self, target, target1):
        target.shell.run("echo I booted", "I booted")
        target1.shell.run("echo I booted", "I booted")
        
    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
