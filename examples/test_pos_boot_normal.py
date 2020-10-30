#! /usr/bin/python3

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    Boot a target to the provisioned OS (not Provisioning OS)
    """

    def eval(self, ic, target):
        ic.power.on()
        target.pos.boot_normal()
        target.shell.up(user = 'root')

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
