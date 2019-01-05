#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# Run as:
#
# $ IMAGE=IMAGESPEC tcf run -vvt "TARGETNAME or NETWORKNAME" /usr/share/tcf/examples/test_pos_deploy.py
#
# Where NETWORKNAME is the name of the Network Under Test to which
# TARGETNAME is connected. IMAGESPEC is the specification of an image
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
class _test(tcfl.tc.tc_c):

    def deploy(self, ic, target):
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        ic.report_pass("powered on")
        global image
        image = tcfl.pos.deploy_image(ic, target, image)

    def start(self, ic, target):
        # fire up the target, wait for a login prompt
        target.power.cycle()
        target.shell.linux_shell_prompt_regex = re.compile('root@.*# ')
        target.shell.up(user = 'root')
        target.report_pass("Deployed %s" % image)
        # release here so we had the daemon control where we boot to
        ic.release()

    def eval(self, target):
        # do our test
        target.shell.run("echo I booted", "I booted")

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
