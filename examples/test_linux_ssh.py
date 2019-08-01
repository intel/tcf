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
import tcfl.tc
import tcfl.tl
import tcfl.pos

image = os.environ.get("IMAGE", "clear")

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable', mode = 'any')
class _test(tcfl.tc.tc_c):
    """
    Example test using different SSH calls with the SSH extension on a
    PC target that is provisioned to a Linux OS (Clear, by default)
    """
    def deploy(self, ic, target):
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        ic.report_pass("powered on")

        target.power.on()

        _image = target.pos.deploy_image(
            ic, image,
            extra_deploy_fns = [
                # Config SSH to allow login as root with no password
                tcfl.pos.deploy_linux_ssh_root_nopwd
            ])
        target.report_info("Deployed %s" % _image)

    def setup(self, ic, target):
        # Tell the tunnelling system which IP address to use
        # Note the client running this can't connect directly to the
        # DUT because the DUT is connected to an isolated
        # NUT. However, the server is connceted to the NUT and can
        # bridge us. With this we tell the tunneling system which ip
        # address to use.
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")

    def start(self, target):
        target.power.cycle()
        target.expect("login")
        target.shell.linux_shell_prompt_regex = tcfl.tl.linux_root_prompts
        target.shell.up(user = "root")

    def eval_00_run_ssh_commands(self, target):
        #
        # Run commands over SSH
        #
        # https://intel.github.io/tcf/doc/09-api.html?highlight=ssh#tcfl.target_ext_ssh.ssh.check_output
        #target.ssh._ssh_cmdline_options.append("-v")	# DEBUG login problems
        output = target.ssh.check_output("echo hello")
        assert 'hello' in output

        # Alternative way to do it https://intel.github.io/tcf/doc/04-HOWTOs.html?highlight=ssh#linux-targets-ssh-login-from-a-testcase-client
        # by hand

        # create a tunnel from server_name:server_port -> to target:22
        server_name = target.rtb.parsed_url.hostname
        server_port = target.tunnel.add(22)
        output = subprocess.check_output(
            "/usr/bin/ssh -p %d root@%s echo hello"
            % (server_port, server_name),
            shell = True)
        # this is done behind the doors of TCF, it doesn't know that
        # it was run, so report about it
        target.report_info("Ran SSH: %s" % output)
        assert 'hello' in output

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
        output = target.ssh.check_output("dmidecode -t system | grep UUID")
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
        target.ssh.copy_to(__file__)
        base_file = os.path.basename(__file__)
        copied_file = os.path.join(self.tmpdir, base_file)
        target.ssh.copy_from(base_file, copied_file)

        orig_hash = commonl.hash_file(hashlib.sha256(), __file__)
        copied_hash = commonl.hash_file(hashlib.sha256(), copied_file)
        if orig_hash.digest() != copied_hash.digest():
            raise tcfl.tc.failed_e("Hashes in copied files changed")
        self.report_pass("Bigger file copied around is identical")


    def eval_07_tree_copy(self, target):
        dirname = self.kws['srcdir']
        copied_subdir = self.kws['tmpdir'] + "/dest"

        # Copy a tree to remote, then copy it back
        target.shell.run("rm -rf subdir")
        target.ssh.copy_to(dirname, "subdir", recursive = True)
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
            raise tcfl.tc.failed_e("local and copied MD5s differ")

        self.report_pass("tree copy passed")


    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
