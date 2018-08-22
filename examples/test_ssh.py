#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import filecmp

import tcfl.tc

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target("linux and ssh_client")
class _test(tcfl.tc.tc_c):

    @staticmethod
    def start(ic, target):
        ic.power.cycle()
        target.power.cycle()
        target.shell.up()		# wait for target to power up
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")

    def eval(self, target):
        # Yes, we could do this in python, but the goal is to do
        # things that someone on the console can do by hand
        target.shcmd_local(
            "dd if=/dev/random of=%(tmpdir)s/testfile bs=1024 count=1"
            % self.kws)
        target.shcmd_local("cat %(tmpdir)s/testfile %(tmpdir)s/testfile "
                           "> %(tmpdir)s/testfile2")
        target.shcmd_local("cat %(tmpdir)s/testfile2 %(tmpdir)s/testfile2 "
                           "> %(tmpdir)s/testfile")
        target.shcmd_local("cat %(tmpdir)s/testfile %(tmpdir)s/testfile "
                           "> %(tmpdir)s/testfile2")
        target.shcmd_local("cat %(tmpdir)s/testfile2 %(tmpdir)s/testfile2 "
                           "> %(tmpdir)s/testfile")

        for rep in range(0, 10):
            src2_fn = self.tmpdir + "/testfile"
            src3_fn = self.tmpdir + "/testfile3.%d" % rep
            dst2_fn = "/home/testfile2.%d" % rep
            dst3_fn = "/home/testfile3.%d" % rep
            target.ssh.copy_to(src2_fn, dst2_fn)
            target.ssh.check_output("ls -l %s" % dst2_fn)
            try:
                # Should fail
                target.ssh.check_output("ls -l %s" % dst3_fn)
            except tcfl.tc.failed_e as e:
                cause = getattr(e, "__cause__", None)
                if cause == None or not hasattr(cause, "output"):
                    raise
                if not "ls: cannot access '%s'" % dst3_fn in cause.output:
                    raise

            target.ssh.copy_from(dst2_fn, src3_fn)
            if not filecmp.cmp(src2_fn, src3_fn):
                raise tcfl.tc.failed_e("pass %d: Original and copied "
                                       "files are different" % rep)
            self.report_pass("pass %d: Original and copied "
                             "files are identical" % rep)
