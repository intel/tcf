#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import re

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    This example shows how to image a machine to run a Linux distro
    and testing a couple scripts built locally and sent to the target.

    We'll build the artifacts on build_* and then deploy them to the
    target using the simple (slow) method of sending-over-console.
    """
    def build_10(self):
        # Let's assume our build step is creating files
        with open("%(tmpdir)s/test1.sh" % self.kws, "w+") as test1f:
            test1f.write("""\
#! /bin/sh
echo Hello World in sh!
""")

        # A C test program that we build here and will deploy later
        with open("%(tmpdir)s/test2.c" % self.kws, "w") as test2f:
            test2f.write("""\
#include <stdio.h>
int main(void) {
        printf("Hello World in C!\\n");
        return 0;
}
""")
        self.shcmd_local("make -C %(tmpdir)s CFLAGS='-O0 -Wall' test2")
        # strip and compress, to reduce the size
        self.shcmd_local("strip %(tmpdir)s/test2")
        self.shcmd_local("bzip2 -9 %(tmpdir)s/test2")

    # Deploy the image to the target
    def eval_10_deploy_image(self, target, ic):
        ic.power.cycle()
        target.pos.deploy_image(ic, "clear")

        # If there are errors, exceptions will come,but otherwise we
        # are here, still in the service OS, so reboot into our new OS
        target.power.cycle()

        # our shell prompt will look like this...
        target.shell.linux_shell_prompt_regex = tcfl.tl.linux_root_prompts
        # wait for target to boot, login as root to the console
        target.shell.up(user = 'root')

    # Now send the two test programs created in build_10
    def eval_15_deploy_artifacts(self, target, ic):

        # Because test.sh is short, we can use simple sending via the console:
        target.shell.file_copy_to('%(tmpdir)s/test1.sh' % self.kws, 'test1.sh')
        target.shell.run("chmod a+x test1.sh")

        # test2 is way bigger, so it'll take longer to send over the
        # console
        target.shell.file_copy_to('%(tmpdir)s/test2.bz2' % self.kws,
                                  'test2.bz2')
        target.shell.run("sync")
        target.shell.run("ls -l")
        target.shell.run("file *")

        # We don't need the interconnect anymore by-- after we booted!!
        # release it for anyone else -- a TC that needs the
        # interconnect would not do this
        ic.release()
        target.report_pass("booted")

    # Now do the actual test running
    def eval_20(self, target):
        target.shell.run("./test1.sh", "Hello World in sh!")
        target.shell.run("bunzip2 ./test2.bz2")
        target.shell.run("chmod a+x test2")
        target.shell.run("./test2", "Hello World in C!")

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
