#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# $ IMAGE=IMAGESPEC tcf run -vvt "TARGETNAME1 or TARGETNAME2 or TARGETNAME3 or NETWORKNAME" /usr/share/tcf/examples/test_pos_deploy_3.py
#
# Where NETWORKNAME is the name of the Network Under Test to which
# TARGETNAME* are connected. IMAGESPEC is the specification of an image
# available in NETWORKNAME's rsync server, which can be found with
#
# $ IMAGE=IMAGESPEC tcf run -vvt NETWORKNAME /usr/share/tcf/examples/test_pos_list_images.py

import os
import re

import tcfl.tc
import tcfl.tl
import tcfl.pos

image = os.environ["IMAGE"]

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    Provision two PC targets at the same time with the Provisioning OS
    """

    @tcfl.tc.serially()
    def deploy(self, ic):
        ic.power.on()

    @tcfl.tc.concurrently()
    def deploy_10_target(self, ic, target):
        image_final = target.pos.deploy_image(ic, image)
        target.report_pass("deployed %s" % image_final)

    @tcfl.tc.concurrently()
    def deploy_10_target1(self, ic, target1):
        image_final = target1.pos.deploy_image(ic, image)
        target1.report_pass("deployed %s" % image_final)

    def start(self, ic, target, target1):
        ic.power.on()			# in case we skip deploy
        target.pos.boot_normal()
        target1.pos.boot_normal()

        target.shell.linux_shell_prompt_regex = tcfl.tl.linux_root_prompts
        target.shell.up(user = 'root')

        target1.shell.linux_shell_prompt_regex = tcfl.tl.linux_root_prompts
        target1.shell.up(user = 'root')

    def eval(self, target, target1):
        target.shell.run("echo I booted", "I booted")
        target1.shell.run("echo I booted", "I booted")
        
    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
