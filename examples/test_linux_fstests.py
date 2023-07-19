#! /usr/bin/python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
.. _example_rt_tests:

Deploy and run Linux's FS-tests
===============================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS,
clone the xfstests-dev test suite, build it and run.

This is a bare example that can be used as a template.

.. literalinclude:: /examples/test_linux_fstests.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_linux_fstests.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=fedora tcf run -v /usr/share/tcf/examples/test_linux_fstests.py
  INFO2/ toplevel @local [+0.4s]: scanning for test cases
  INFO1/5mqmry test_linux_fstests.py @737f-5e2f [+0.3s]: will run on target group 'ic=TARGETNAME-nw target=TARGETNAME:x86_64' (PID 101869 / TID 7fa1db1c16c0)
  INFO1/5mqmry test_linux_fstests.py @737f-5e2f [+0.3s]: allocation ID: any
  INFO2/5mqmryD test_linux_fstests.py @737f-5e2f [+0.6s]: powered on
  PASS2/5mqmry test_linux_fstests.py @737f-5e2f [+810.4s]: deploy passed
  ...
  INFO2/mfpxjeE#1 test_linux_fstests.py##70_checkout @737f-5e2f [+1091.9s]: shell/default: sent command: test -d xfstests-dev.git && echo UP''DATE || echo CL''ONE
  INFO2/mfpxjeE#1 test_linux_fstests.py##70_checkout @737f-5e2f [+1092.4s]: shell/default: sent command: rm -rf xfstests-dev.git
  INFO2/mfpxjeE#1 test_linux_fstests.py##70_checkout @737f-5e2f [+1092.8s]: cloning xfstests-dev.git
  INFO2/mfpxjeE#1 test_linux_fstests.py##70_checkout @737f-5e2f [+1092.8s]: shell/default: sent command: git clone https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git xfstests-dev.git
  PASS2/mfpxjeE#1 test_linux_fstests.py##70_checkout @737f-5e2f [+1094.6s]: cloned xfstests-dev.git
  INFO2/du6aa3E#1 test_linux_fstests.py##75_build @737f-5e2f [+1094.7s]: shell/default: sent command: make -C xfstests-dev.git -j 5
  INFO2/du6aa3E#1 test_linux_fstests.py##75_build @737f-5e2f [+1113.7s]: shell/default: sent command: find xfstests-dev.git -ls > manifest
  INFO2/grmptcE#1 test_linux_fstests.py##80_users @737f-5e2f [+1114.1s]: shell/default: sent command: id fsgqa || useradd -m fsgqa
  INFO2/grmptcE#1 test_linux_fstests.py##80_users @737f-5e2f [+1114.6s]: shell/default: sent command: id 123456-fsgqa || useradd -m 123456-fsgqa
  INFO2/grmptcE#1 test_linux_fstests.py##80_users @737f-5e2f [+1115.0s]: shell/default: sent command: id fsgqa2 || useradd -m fsgqa2
  INFO2/grmptcE#1 test_linux_fstests.py##80_users @737f-5e2f [+1115.4s]: shell/default: sent command: getent group fsgqa || groupadd fsgqa
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1115.9s]: shell/default: sent command: cd /var/tmp/xfstests-dev.git
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1116.3s]: shell/default: sent command: export TEST_DEV=$(readlink -e /dev/disk/by-partlabel/TCF-scratch)
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1116.8s]: shell/default: sent command: mkdir -p /test
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1117.2s]: shell/default: sent command: umount /test || true
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1117.6s]: shell/default: sent command: export TEST_DIR=/test
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1118.1s]: shell/default: sent command: swapoff -a
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1118.5s]: shell/default: sent command: export SCRATCH_DEV=$(readlink -e /dev/disk/by-partlabel/TCF-swap)
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1119.0s]: shell/default: sent command: mkdir -p /scratch
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1119.4s]: shell/default: sent command: umount /scratch || true
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1119.8s]: shell/default: sent command: export SCRATCH_MNT=/scratch
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1120.3s]: shell/default: sent command: systemctl daemon-reload || true
  INFO2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1120.8s]: shell/default: sent command: ./check -n -g auto
  ERRR2/w7ijl4E#1 test_linux_fstests.py##30_run @737f-5e2f [+1121.2s]: eval errored: error detected in shell
  ERRR2/5mqmryE#1 test_linux_fstests.py @737f-5e2f [+1122.5s]: console dump due to errors
  ERRR0/5mqmry test_linux_fstests.py @737f-5e2f [+1122.8s]: evaluation errored
  INFO2/7noanx test_linux_fstests.py##65_install_dependencies @737f-5e2f [+0.0s]: NOTE: this is a subtestcase of test_linux_fstests.py (5mqmry); refer to it for full information
  PASS1/7noanx test_linux_fstests.py##65_install_dependencies @737f-5e2f [+0.0s]: subcase passed
  INFO2/mfpxje test_linux_fstests.py##70_checkout @737f-5e2f [+0.0s]: NOTE: this is a subtestcase of test_linux_fstests.py (5mqmry); refer to it for full information
  PASS1/mfpxje test_linux_fstests.py##70_checkout @737f-5e2f [+0.0s]: subcase passed
  INFO2/du6aa3 test_linux_fstests.py##75_build @737f-5e2f [+0.0s]: NOTE: this is a subtestcase of test_linux_fstests.py (5mqmry); refer to it for full information
  PASS1/du6aa3 test_linux_fstests.py##75_build @737f-5e2f [+0.0s]: subcase passed
  INFO2/grmptc test_linux_fstests.py##80_users @737f-5e2f [+0.0s]: NOTE: this is a subtestcase of test_linux_fstests.py (5mqmry); refer to it for full information
  PASS1/grmptc test_linux_fstests.py##80_users @737f-5e2f [+0.0s]: subcase passed
  INFO2/w7ijl4 test_linux_fstests.py##30_run @737f-5e2f [+0.0s]: NOTE: this is a subtestcase of test_linux_fstests.py (5mqmry); refer to it for full information
  ERRR0/w7ijl4 test_linux_fstests.py##30_run @737f-5e2f [+0.0s]: subcase errored
  ERRR0/ toplevel @local [+1124.7s]: 6 tests (4 passed, 2 error, 0 failed, 0 blocked, 0 skipped, in 0:18:43.154329) - errored

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import re

import tcfl.tc
import tcfl.tl
import tcfl.pos

git_url = os.environ.get(
    "TEST_LINUX_RT_TEST_GIT_URL",
    "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git")

git_version = os.environ.get(
    "TEST_LINUX_RT_TEST_GIT_VERSION",
    "stable/v1.0")

class _test(tcfl.pos.tc_pos_base):
    """

    https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git/about/
    """

    def start_60_setup(self, ic, target):
        target.console.select_preferred()
        target.shell.setup()
        tcfl.tl.sh_export_proxy(ic, target)
        target.shell.run("cd /var/tmp")


    @tcfl.tc.subcase(break_on_non_pass = True)
    def start_65_install_dependencies(self, ic, target):
        #
        # Build in SUT
        #
        if  "TEST_LINUX_RT_TEST_SKIP_BUILD" in os.environ:
            self.report_skip("skipping build per environ TEST_LINUX_RT_TEST_SKIP_BUILD")
            return

        tcfl.tl.linux_package_add(
            ic, target, "git",
            fedora = [
                "acl",
                "attr",
                "automake",
                "bc",
                "btrfs-progs",
                "dbench",
                "dump",
                "e2fsprogs",
                "exfatprogs",
                "f2fs-tools",
                "fio",
                "gawk",
                "gcc",
                "gdbm-devel",
                "git",
                "indent",
                "kernel-devel",
                "libacl-devel",
                "libaio-devel",
                "libcap-devel",
                "libtool",
                "liburing-devel",
                "libuuid-devel",
                "lvm2",
                "make",
                "ocfs2-tools",
                "psmisc",
                "python3",
                "quota",
                "sed",
                "sqlite",
                "udftools",
                "xfsdump",
                "xfsprogs",
                "xfsprogs-devel",
            ],
            centos = [
                "acl",
                "attr",
                "automake",
                "bc",
                "dbench",
                "dump",
                "exfatprogs",
                "fio",
                "gawk",
                "gcc",
                "gdbm-devel",
                "git",
                "indent",
                "kernel-devel",
                "libacl-devel",
                "libaio-devel",
                "libcap-devel",
                "libtool",
                "liburing-devel",
                "libuuid-devel",
                "lvm2",
                "make",
                "psmisc",
                "python3",
                "quota",
                "sed",
                "sqlite",
                "udftools",
                "xfsdump",
                "xfsprogs",
                "xfsprogs-devel",
                #"btrfs-progs",
                #"e2fsprogs",
                #"f2fs-tools",
                #"ocfs2-tools",
            ],
            # might need to refresh packagelists and brings a ton of deps
            timeout = 2000,
        )


    @tcfl.tc.subcase(break_on_non_pass = True)
    def start_70_checkout(self, target):
        if  "TEST_LINUX_FSTESTS_SKIP_CHECKOUT" in os.environ:
            self.report_skip("skipping checkout per environ TEST_LINUX_FSTESTS_SKIP_CHECKOUT")
            return
        output = target.shell.run(
            "test -d xfstests-dev.git && echo UP''DATE || echo CL''ONE",
            output = True)
        if 'CLONE' in output:
            target.shell.run("rm -rf xfstests-dev.git")
            target.report_info("cloning xfstests-dev.git")
            target.shell.run(f"git clone {git_url} xfstests-dev.git")
            target.report_pass("cloned xfstests-dev.git")
        else:
            target.report_info("assuming xfstests-dev.git is there")



    @tcfl.tc.subcase(break_on_non_pass = True)
    def start_75_build(self, target):
        #
        # Build in SUT
        #
        if  "TEST_LINUX_FSTESTS_SKIP_BUILD" in os.environ:
            self.report_skip("skipping build per environ TEST_LINUX_FSTESTS_SKIP_BUILD")
            return

        target.shell.run("make -C xfstests-dev.git -j 5")
        target.shell.run("find xfstests-dev.git -ls > manifest")



    @tcfl.tc.subcase(break_on_non_pass = True)
    def start_80_users(self, target):
        target.shell.run("id fsgqa || useradd -m fsgqa")
        target.shell.run("id 123456-fsgqa || useradd -m 123456-fsgqa")
        target.shell.run("id fsgqa2 || useradd -m fsgqa2")
        target.shell.run("getent group fsgqa || groupadd fsgqa")



    @tcfl.tc.subcase()
    def eval_30_run(self, target):
        target.shell.run("cd /var/tmp/xfstests-dev.git")

        target.shell.run("export TEST_DEV=$(readlink -e /dev/disk/by-partlabel/TCF-scratch)")
        target.shell.run("mkdir -p /test")
        target.shell.run("umount /test || true")	# unmount if mounted
        target.shell.run("export TEST_DIR=/test")

        target.shell.run("swapoff -a")
        target.shell.run("export SCRATCH_DEV=$(readlink -e /dev/disk/by-partlabel/TCF-swap)")
        target.shell.run("mkdir -p /scratch")
        target.shell.run("umount /scratch || true")	# unmount if mounted
        target.shell.run("export SCRATCH_MNT=/scratch")

        # Reload systemctl to refresh and avoid the message:
        #
        ## mount: (hint) your fstab has been modified, but systemd still uses the old version; use 'systemctl daemon-reload' to reload
        target.shell.run("systemctl daemon-reload || true")

        # List which tests we are going to run
        groups = "auto"
        output = target.shell.run(f"./check -n -g {groups}", output = True)
        ##
	## FSTYP         -- ext4
	## PLATFORM      -- Linux/x86_64 q09h 6.0.7-301.fc37.x86_64 #1 SMP PREEMPT_DYNAMIC Fri Nov 4 18:35:48 UTC 2022
	## MKFS_OPTIONS  -- -F /dev/sda2
	## MOUNT_OPTIONS -- -o acl,user_xattr -o context=system_u:object_r:root_t:s0 /dev/sda2 /scratch
	##
	## mount: (hint) your fstab has been modified, but systemd still uses
	##        the old version; use 'systemctl daemon-reload' to reload.
	## ext4/001
	## ext4/002
        ## ...
        #
        # We'll look for ^[\s
        regex = re.compile("^\S+/\S+$", re.MULTILINE)
        subcases = re.findall(regex, output)
        target.report_info(f"found {len(subcases)} subcases for groups {groups}")

        # initialize the subcase list and then run it
        for subcase in subcases:
            self.subtc[subcase] = tcfl.tc.subtc_c(
                self.name + "##" + subcase.replace("/", "##"),
                self.kws['thisfile'], f"xfstests-dev.git/tests/{subcase}", self)

        target.shell.run("rm -rf results")
        for subcase in subcases:
            subcase_name = subcase.replace("/", "##")
            output = target.shell.run(f"./check -d {subcase} || true",
                                      output = True, trim = True,
                                      timeout = 600)
            # will print
            # Ran: SUBCASE
            # Failure: SUBCASE
            # Not run: SUBCASE
            if re.search(f'^Not run: {subcase}$', output, re.MULTILINE):
                target.report_skip("not run", subcase = subcase_name)
                self.subtc[subcase].update(tcfl.tc.result_c(skipped = 1),
                                           "Not run", output)
            elif re.search(f'^Failures: {subcase}$', output, re.MULTILINE):
                target.report_fail("Failure", subcase = subcase_name)
                self.subtc[subcase].update(tcfl.tc.result_c(failed = 1),
                                           "Not run", output)
            elif re.search(f'^Ran: {subcase}$', output, re.MULTILINE):
                target.report_pass("Ran", subcase = subcase_name)
                self.subtc[subcase].update(tcfl.tc.result_c(passed = 1),
                                           "Ran", output)
            else:
                target.report_blck("No info", subcase = subcase_name)
                self.subtc[subcase].update(tcfl.tc.result_c(blocked = 1),
                                           "No info", output)
