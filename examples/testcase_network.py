#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# We don't need to document every single thing
# pylint: disable = missing-docstring

import re
import tcfl.tc

class _base(tcfl.tc.tc_c):
    """
    A bunch of linux targets networked can ping each other and the router.
    """
    def start(self):
        for _twn, target in self.targets.items():
            target.power.cycle()

    @staticmethod
    def _target_up(target):
        # Wait for the shell prompt, ensure we have connectivity
        target.expect(re.compile(r" [0-9]+ \$ "))
        target.send('ifconfig -a')
        # Make sure ifconfig reports we found the IP address of the target
        target.expect("%(ipv4_addr)s" % target.kws)

    @staticmethod
    def _ping_addr(target, addr):
        target.send("ping -c 3 %s" % addr)
        target.expect("64 bytes from %s: icmp_seq=3" % addr)

    def eval_targets_are_up(self):
        # Each target is up
        for twn, target  in self.targets.items():
            if twn == 'ic':
                continue
            self._target_up(target)

    def eval_targets_can_ping4_router(self, ic):
        # Each target can ping the router
        for twn, target  in self.targets.items():
            if twn == 'ic':
                continue
            self._ping_addr(target, ic.kws['ipv4_addr'])

    def eval_targets_can_ping_eachother(self):
        # Each target can ping each other
        for twna, targeta in self.targets.items():
            if twna == 'ic':
                continue
            for twnb, targetb in self.targets.items():
                if twnb == 'ic':
                    continue
                self._ping_addr(targeta, targetb.kws['ipv4_addr'])

    def teardown_dump_console(self):
        if not self.result_eval.failed and not self.result_eval.blocked:
            return
        for target in list(self.targets.values()):
            if not hasattr(target, "console"):
                continue
            if self.result_eval.failed:
                reporter = target.report_fail
                reporter("console dump due to failure")
            else:
                reporter = target.report_blck
                reporter("console dump due to blockage")
            for line in target.console.read().split('\n'):
                reporter("console: " + line.strip())


    def teardown(self):
        # FIXME: move this to the library of common test functions
        for _twn, target  in reversed(list(self.targets.items())):
            target.power.off()

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
class _test_2(_base):
    pass

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
class _test_3(_base):
    pass

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
@tcfl.tc.target("linux")
class _test_4(_base):
    pass
