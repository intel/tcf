#! /usr/bin/python

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    Boot a target to Provisioning OS
    """

    def eval(self, ic, target):
        ic.power.on()
        target.pos.boot_to_pos()

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
