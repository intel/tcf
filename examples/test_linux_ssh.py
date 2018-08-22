#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# We don't care for documenting all the interfaces, names should be
# self-descriptive:
#
# - pylint: disable = missing-docstring

import hashlib
import os
import re
import subprocess
import time

import commonl
import tcfl
import tcfl.tc

# Want an interconnect that supports IPv4 (so we test for it having
# any IP address assigned)
@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target("linux", name = "linux")
@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    """A linux target (or any target that declares itself as an SSH
    client with a tag *ssh_client* can be accessed via SSH via the SSH
    extension.
    """
    def __init__(self, *args):
        tcfl.tc.tc_c.__init__(self, *args)
        self.ts = None

    @staticmethod
    def start(ic, linux):
        ic.power.cycle()
        linux.power.cycle()

    def eval_01_linux_up(self, linux):
        linux.shell.up()

        # There has to be an interface that IS NOT loopback that has
        # UP and LOWER_UP enabled (connected, online)
        linux.shell.run('ip link show', "BROADCAST,MULTICAST,UP,LOWER_UP")
        linux.expect(re.compile(r"[0-9]+ \$ "))

    def eval_02(self, ic, linux):
        self.ts = "%f" % time.time()
        linux.tunnel.ip_addr = linux.addr_get(ic, "ipv4")
        linux.ssh.check_output("echo -n %s > somefile" % self.ts)
        self.report_pass("created a file with SSH command")

    def eval_03(self, linux):
        linux.ssh.copy_from("somefile", self.tmpdir)
        with open(os.path.join(self.tmpdir, "somefile")) as f:
            read_ts = f.read()
            linux.report_info("read ts is %s, gen is %s" % (read_ts, self.ts))
            if read_ts != self.ts:
                raise tcfl.tc.failed_e(
                    "The timestamp read from the file we copied from "
                    "the target (%s) differs from the one we generated (%s)"
                    % (read_ts, self.ts))
        self.report_pass("File created with SSH command copied back ok")

    def eval_04(self, linux):
        linux.ssh.copy_to(__file__)
        base_file = os.path.basename(__file__)
        copied_file = os.path.join(self.tmpdir, base_file)
        linux.ssh.copy_from(base_file, copied_file)

        orig_hash = commonl.hash_file(hashlib.sha256(), __file__)
        copied_hash = commonl.hash_file(hashlib.sha256(), copied_file)
        if orig_hash.digest() != copied_hash.digest():
            raise tcfl.tc.failed_e("Hashes in copied files changed")
        self.report_pass("Bigger file copied around is identical")


    def eval_04_tree_copy(self, linux):
        dirname = os.path.dirname(__file__)
        copied_subdir = os.path.join(self.tmpdir, "subdir")

        # Copy a tree to remote, then copy it back
        linux.ssh.copy_to(dirname, "subdir", recursive = True)
        linux.ssh.copy_from("subdir", copied_subdir, recursive = True)

        # Generate MD5 signatures of the python files in the same order
        local_md5 = subprocess.check_output(
            r"find %s -type f -iname \*.py | sort | xargs cat | md5sum"
            % dirname,
            shell = True).strip()
        copied_md5 = subprocess.check_output(
            r"find %s -type f -iname \*.py | sort | xargs cat | md5sum"
            % copied_subdir,
            shell = True).strip()

        self.report_info("local_md5 %s" % local_md5, dlevel = 1)
        self.report_info("copied_md5 %s" % copied_md5, dlevel = 1)

        if local_md5 != copied_md5:
            raise tcfl.tc.failed_e("local and copied MD5s differ")

        self.report_pass("Tree copy passed")

    def teardown_dump_console(self):
        if not self.result_eval.failed and not self.result_eval.blocked:
            return
        for target in self.targets.values():
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
