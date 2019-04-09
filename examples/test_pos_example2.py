#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import re
import subprocess

import tcfl.tc
import tcfl.tl
import tcfl.pos

image = os.environ.get("IMAGE", "clear")

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    This example shows how to download and build a tarball locally,
    deploy it to the target when installing a distro and then
    executing the binary.
    """
    def build_10(self):
        # download Hello World
        # http://ftp.gnu.org/gnu/hello/hello-2.10.tar.gz, assuming
        # your proxy is setup. Autoconf it, build it and install it to
        # a rootdir
        self.shcmd_local(
            "wget -O %(tmpdir)s/hello.tar.gz"
            " http://ftp.gnu.org/gnu/hello/hello-2.10.tar.gz")
        self.shcmd_local(
            "tar xvf %(tmpdir)s/hello.tar.gz -C %(tmpdir)s")
        self.shcmd_local(
            "cd %(tmpdir)s/hello-* && ./configure --prefix=/usr")
        self.shcmd_local(
            "make -C %(tmpdir)s/hello-* DESTDIR=%(tmpdir)s/root install")


    def _deploy_hello_tree(self, _ic, target, _kws):
        target.pos.rsync_np("%(tmpdir)s/root" % self.kws, "/",
                            # keep whatever is existing, our tree is
                            # not complete, we are adding
                            option_delete = False)

    # Deploy the image to the target
    def eval_10_deploy_image(self, target, ic):
        ic.power.on()
        self.image = target.pos.deploy_image(
            ic, image,
            extra_deploy_fns = [
                # rsync the tree we installed into TMPDIR/root/
                self._deploy_hello_tree,
            ])

        # If there are errors, exceptions will come, but otherwise we
        # are here, still in the Provisioning OS, so reboot into our new OS
        target.pos.boot_normal()

        # our shell prompt will look like this...
        target.shell.linux_shell_prompt_regex = tcfl.tl.linux_root_prompts
        # wait for target to boot, login as root to the console
        target.shell.up(user = 'root')

    # Now send the two test programs created in build
    def eval_run_hello(self, target):

        # let's verify the binary is what we installed
        md5_regex = re.compile("^([0-9a-z]+) ", re.MULTILINE)

        # get the local MD5 signature
        output = subprocess.check_output(
            "md5sum < %(tmpdir)s/root/usr/bin/hello" % self.kws, shell = True)
        m = md5_regex.search(output)
        if not m:
            raise tcfl.tc.error_e("Can't parse local's MD5",
                                  attachments = dict(output = output))
        local_md5 = m.groups()[0]

        # now the remote
        output = target.shell.run("md5sum < /usr/bin/hello", output = True)
        if not m:
            raise tcfl.tc.error_e("Can't parse remote's MD5",
                                  attachments = dict(output = output,
                                                     target = target))
        remote_md5 = m.groups()[0]

        if remote_md5 != local_md5:	# compare them
            raise tcfl.tc.failed_e(
                "Local MD5 %s does not match deployed MD5 %s"
                % (local_md5, remote_md5),
                attachments = dict(output = output,
                                   target = target))

        # fine, now run it!
        target.shell.run("/usr/bin/hello", "Hello, world!")
        # thumbs up!

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
