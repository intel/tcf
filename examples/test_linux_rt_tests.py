#! /usr/bin/python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
.. _example_rt_tests:

Deploy and run Linux's RT-tests
===============================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS,
clone the rt-tests test suite, build it and run cyclictest.

This is a bare example that can be used as a template; workloads would
ned to be added for *cyclictest*'s output to be useful, for
example. Other test from the suite can be run, etc.


.. literalinclude:: /examples/test_linux_rt_tests.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_linux_rt_tests.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=fedora tcf run -v /usr/share/tcf/examples/test_linux_rt_tests.py
  INFO1/7dzuke ... [+1.1s]: will run on target group 'ic=SERVER/nwa target=SERVER/q02a:x86_64' (PID 203967 / TID 7f7bee804640)
  ...
  INFO2/iionnvE#1 ...15_checkout [+7.2s]: assuming rt-tests.git is there
  INFO2/iionnvE#1 ...15_checkout [+7.2s]: checking out stable/v1.0
  INFO2/iionnvE#1 ...15_checkout [+7.4s]: shell/default: sent command: git -C rt-tests.git checkout stable/v1.0
  INFO2/iionnvE#1 ...15_checkout [+7.9s]: checked out stable/v1.0
  ...
  INFO2/bmbbm5E#1 ...20_cyclictest [+8.4s]: shell/default: sent command: ( cd rt-tests.git; ./cyclictest --unbuffered -q --mlockall --priority=80 --interval=200 --distance=0 -D 20 )
  DATA1/bmbbm5E#1 ...20_cyclictest [+28.7s]: Realtime Tests qemu-uefi-x86_64::cyclictest latency minimum (us)::5
  DATA1/bmbbm5E#1 ...20_cyclictest [+28.7s]: Realtime Tests qemu-uefi-x86_64::cyclictest latency maximum (us)::143
  DATA1/bmbbm5E#1 ...20_cyclictest [+28.7s]: Realtime Tests qemu-uefi-x86_64::cyclictest average (us)::7
  PASS0/ toplevel @local [+38.0s]: 5 tests (5 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:28.788512) - passed

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
    "https://git.kernel.org/pub/scm/utils/rt-tests/rt-tests.git")

git_version = os.environ.get(
    "TEST_LINUX_RT_TEST_GIT_VERSION",
    "stable/v1.0")

class _test(tcfl.pos.tc_pos_base):
    """
    Provisiong a target, boot it, run a shell command
    """

    def eval_10_setup(self, ic, target):
        tcfl.tl.sh_export_proxy(ic, target)
        target.shell.run("cd ~")


    @tcfl.tc.subcase()
    def eval_10_instalL_dependencies(self, ic, target):
        #
        # Build in SUT
        #
        if  "TEST_LINUX_RT_TEST_SKIP_BUILD" in os.environ:
            self.report_skip("skipping build per environ TEST_LINUX_RT_TEST_SKIP_BUILD")
            return

        # https://wiki.linuxfoundation.org/realtime/documentation/howto/tools/rt-tests#compile_and_install
        tcfl.tl.linux_package_add(
            ic, target,
            "git",
            fedora = [ "make", "automake", "gcc", "gcc-c++", "kernel-devel", "numactl-devel" ],
            centos = [ "make", "automake", "gcc ", "gcc-c++", "kernel-devel", "numactl-devel" ],
            # might need to refresh packagelists and brings a ton of deps
            timeout = 2000,
        )


    @tcfl.tc.subcase()
    def eval_15_checkout(self, target):
        if  "TEST_LINUX_RT_TEST_SKIP_CHECKOUT" in os.environ:
            self.report_skip("skipping checkout per environ TEST_LINUX_RT_TEST_SKIP_CHECKOUT")
            return
        output = target.shell.run(
            "test -d rt-tests.git && echo UP''DATE || echo CL''ONE",
            output = True)
        if 'CLONE' in output:
            target.shell.run("rm -rf  rt-tests.git")
            target.report_info("cloning rt-tests.git")
            target.shell.run(f"git clone {git_url} rt-tests.git")
            target.report_pass("cloned rt-tests.git")
        else:
            target.report_info("assuming rt-tests.git is there")

        if git_version.lower() != "none":
            target.report_info(f"checking out {git_version}")
            target.shell.run(f"git -C rt-tests.git checkout {git_version}")
            target.report_info(f"checked out {git_version}")


    @tcfl.tc.subcase()
    def eval_20_build(self, target):
        #
        # Build in SUT
        #
        if  "TEST_LINUX_RT_TEST_SKIP_BUILD" in os.environ:
            self.report_skip("skipping build per environ TEST_LINUX_RT_TEST_SKIP_BUILD")
            return

        target.shell.run("make -C rt-tests.git -j 20 all")
        target.shell.run("find rt-tests.git -ls")


    @tcfl.tc.subcase()
    def eval_30_cyclictest(self, target):
        cyclictest_duration = int(os.environ.get(
            "TEST_LINUX_RT_TEST_CYCLICTEST_DURATION_S",
            2 * 60))
        cyclictest_options = os.environ.get(
            "TEST_LINUX_RT_TEST_CYCLICTEST_OPTIONS",
            "")

        output = target.shell.run(
            "( cd rt-tests.git;"
            " ./cyclictest"
            # -q|--quiet makes the output easier to parse, at the expense
            # of not seeing it doing it's ting, which is quite
            # confusing anyway because it tries to do ANSI tricks
            #
            # Output looks like (in us) https://wiki.linuxfoundation.org/realtime/documentation/howto/tools/cyclictest/start
            #
            ## T: 0 ( 1533) P:80 I:200 C: 599853 Min:      4 Act:    6 Avg:    6 Max:    8225
            #
            # We only do one CPU (no --smp)
            " --unbuffered -q"
            " --mlockall --priority=80 --interval=200 --distance=0"
            " --nsecs"		# many machines hit the 1us mark
            f" -D {cyclictest_duration}"
            f" {cyclictest_options}"
            ")",
            timeout = 30 + cyclictest_duration, output = True, trim = True)

        regex = re.compile(
            r"^T:\s*[0-9]+\s+\(\s*[0-9]+\s*\)\s+"
            r"P:\s*[0-9]+\s+"
            r"I:\s*[0-9]+\s+"
            r"C:\s*[0-9]+\s+"
            r"Min:\s*(?P<min_ns>[-0-9]+)\s+"
            # we ignore actual, because it is just the last measurement
            r"Act:\s*(?P<actual_ns>[-0-9]+)\s+"
            r"Avg:\s*(?P<average_ns>[-0-9]+)\s+"
            r"Max:\s*(?P<max_ns>[-0-9]+)",
            re.MULTILINE)

        m = regex.search(output)
        if m == None:
            raise tcfl.error_e("cannot parse output with regex",
                               { "output": output, "regex": regex.pattern })
        gd = m.groupdict()
        # extract latencies
        min_ns = int(gd['min_ns'])
        average_ns = int(gd['average_ns'])
        max_ns = int(gd['max_ns'])
        target.report_data("Realtime Tests %(type)s",
                           "cyclictest latency minimum (ns)", min_ns)
        target.report_data("Realtime Tests %(type)s",
                           "cyclictest latency maximum (ns)", max_ns)
        target.report_data("Realtime Tests %(type)s",
                           "cyclictest average (ns)", average_ns)
