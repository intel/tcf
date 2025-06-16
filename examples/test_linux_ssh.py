#! /usr/bin/python3
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
""".. _example_linux_ssh:

Different options of accessing a target via SSH
===============================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, setup its SSH server and run commands, copy files around.

Note that accessing a target over *ssh* with automation is not as
straightforward as doing it by hand, since humans are way slower than
automation. We also tend to assume passwords and keys are setup,
hostnames availables and server started and ready to go. Those are the
most common source of issues.

.. literalinclude:: /examples/test_linux_ssh.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_linux_ssh.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ tcf run -v /usr/share/tcf/examples/test_linux_ssh.py
  INFO1/q4ux      ..../test_linux_ssh.py#_test @t7rd-4e2t: will run on target group 'ic=jfsotc11/nwk target=jfsotc11/nuc-70k:x86_64'
  INFO1/q4uxDPOS  ..../test_linux_ssh.py#_test @t7rd-4e2t|jfsotc11/nuc-70k: POS: rsyncing clear:server:30590::x86_64 from 192.168.107.1::images to /dev/sda6
  PASS1/q4ux      ..../test_linux_ssh.py#_test @t7rd-4e2t: evaluation passed
  PASS0/  toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:02:20.841000) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

where IMAGE is the name of a Linux OS image :ref:`installed in the
server <pos_list_images>`.

"""

import hashlib
import os
import re
import shutil
import subprocess
import time

from tcfl import commonl
import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect('ipv4_addr', mode = os.environ.get('MODE', 'all'))
@tcfl.tc.target('pos_capable and ic.id in interconnects',
                mode = os.environ.get('MODE', 'all'))
                # For example, it could add
                # ' and interfaces.capture.screen.type == "snapshot"')
class _test(tcfl.pos.tc_pos0_base):
    """
    Exercise different SSH calls with the SSH extension on a PC target
    that is provisioned to a Linux OS (Clear, by default)
    """
    image_requested = os.environ.get("IMAGE", 'clear:desktop')

    def eval_00_setup(self, ic, target):
        # setup the SSH server to allow login as root with no password
        tcfl.tl.linux_ssh_root_nopwd(target)
        tcfl.tl.linux_sshd_restart(ic, target)

    def eval_01_run_ssh_commands(self, ic, target):
        tcfl.tl.linux_wait_online(ic, target)
        #
        # Run commands over SSH
        #
        # https://intel.github.io/tcf/doc/09-api.html?highlight=ssh#tcfl.target_ext_ssh.ssh.check_output
        #target.ssh._ssh_cmdline_options.append("-v")	# DEBUG login problems
        #target.ssh._ssh_cmdline_options.append("-v")	# DEBUG login problems
        output = target.ssh.check_output("echo hello")
        assert b'hello' in output

        # Alternative way to do it https://intel.github.io/tcf/doc/04-HOWTOs.html?highlight=ssh#linux-targets-ssh-login-from-a-testcase-client
        # by hand

        # create a tunnel from server_name:server_port -> to target:22
        server_name = target.server.parsed_url.hostname
        server_port = target.tunnel.add(22)
        output = subprocess.check_output([
            "/usr/bin/ssh", "-p", str(server_port), f"root@{server_name}",
            "echo", "hello" ])
        # this is done behind the doors of TCF, it doesn't know that
        # it was run, so report about it
        target.report_info("Ran SSH: %s" % output)
        assert b'hello' in output

    def eval_02_call(self, target):
        self.ts = "%f" % time.time()
        if target.ssh.call("true"):
            self.report_pass("true over SSH passed")
        if not target.ssh.call("false"):
            self.report_pass("false over SSH passed")

    def eval_03_check_output(self, target):
        self.ts = "%f" % time.time()
        target.ssh.check_output("echo -n %s > somefile" % self.ts)
        self.report_pass("created a file with SSH command")

    def eval_04_check_output(self, target):
        output = target.ssh.check_output("echo example output")
        self.report_pass("SSH check_output returns: %s" % output.strip())

    def eval_05_copy_from(self, target):
        target.ssh.copy_from("somefile", self.tmpdir)
        with open(os.path.join(self.tmpdir, "somefile")) as f:
            read_ts = f.read()
            target.report_info("read ts is %s, gen is %s" % (read_ts, self.ts))
            if read_ts != self.ts:
                raise tcfl.tc.failed_e(
                    "The timestamp read from the file we copied from "
                    "the target (%s) differs from the one we generated (%s)"
                    % (read_ts, self.ts))
        self.report_pass("File created with SSH command copied back ok")

    def eval_06_copy_to(self, target):
        # test copying file relative to the script source
        target.ssh.copy_to('data/beep.wav')
        base_file = os.path.basename(__file__)	# this file
        target.ssh.copy_to(base_file)
        copied_file = os.path.join(self.tmpdir, base_file)
        target.ssh.copy_from(base_file, copied_file)

        orig_hash = commonl.hash_file(hashlib.sha256(), __file__)
        copied_hash = commonl.hash_file(hashlib.sha256(), copied_file)
        if orig_hash.digest() != copied_hash.digest():
            raise tcfl.tc.failed_e("Hashes in copied files changed")
        self.report_pass("Bigger file copied around is identical")


    def eval_07_tree_copy(self, target):
        copied_subdir = self.kws['tmpdir'] + "/dest"

        # Copy a tree to remote, then copy it back
        target.shell.run("rm -rf subdir")
        shutil.rmtree(copied_subdir, True)
        target.ssh.copy_to(self.kws['srcdir_abs'], "subdir", recursive = True)
        target.ssh.copy_from("subdir", copied_subdir, recursive = True)

        # Generate MD5 signatures of the python files in the same order
        local_md5 = self.shcmd_local(
            r"find %(srcdir)s -type f -iname \*.py"
            " | sort | xargs cat | md5sum").strip()
        copied_md5 = self.shcmd_local(
            r"find %(tmpdir)s/dest -type f -iname \*.py"
            " | sort | xargs cat | md5sum").strip()

        self.report_info("local_md5 %s" % local_md5, dlevel = 1)
        self.report_info("copied_md5 %s" % copied_md5, dlevel = 1)

        if local_md5 != copied_md5:
            local_list = self.shcmd_local(
                r"find %(srcdir)s -type f -iname \*.py | sort").strip()
            copied_list = self.shcmd_local(
                r"find %(tmpdir)s/dest -type f -iname \*.py | sort").strip()
            raise tcfl.tc.failed_e(
                "local and copied MD5s differ",
                dict(local_list = local_list, copied_list = copied_list))

        self.report_pass("tree copy passed")

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
