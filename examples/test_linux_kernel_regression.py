#! /usr/bin/env python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
.. _example_test_linux_kernel_regression:

Execute the Fedora Linux Kernel Regression
==========================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS and
run the Linux Kernel Regression.

.. literalinclude:: /examples/test_linux_kernel_regression.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_linux_kernel_regression.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::


  $ tcf -e IMAGE=centos run -v test_linux_kernel_regression.py
  ...
  PASS1/dupijsE#1 test_linux_kernel_regression.py##default_cachedrop @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.0s]: subcase passed
  PASS1/0yyyglE#1 test_linux_kernel_regression.py##default_insert_leap_second @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.0s]: subcase passed
  SKIP1/zqttg9E#1 test_linux_kernel_regression.py##default_libhugetlbfs @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.0s]: subcase skipped
  PASS1/rapcxcE#1 test_linux_kernel_regression.py##default_memfd @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.1s]: subcase passed
  FAIL1/5l5pavE#1 test_linux_kernel_regression.py##default_modsign @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.1s]: subcase failed
  PASS1/u1qpyiE#1 test_linux_kernel_regression.py##default_mq-memory-corruption @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.1s]: subcase passed
  SKIP1/urp8agE#1 test_linux_kernel_regression.py##default_paxtest @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.1s]: subcase skipped
  PASS1/ujzma5E#1 test_linux_kernel_regression.py##default_posix_timers @duhb-ylly|capi-lr40n07_5001/r245s001 [+386.1s]: subcase passed
  ...
  FAIL1/8axjqmE#1 test_linux_kernel_regression.py##stress_ltp_ltp_lib_newlib_tests @duhb-ylly|capi-lr40n07_5001/r245s001 [+469.6s]: subcase failed
  SKIP1/23dqsmE#1 test_linux_kernel_regression.py##stress_rcutorture @duhb-ylly|capi-lr40n07_5001/r245s001 [+469.6s]: subcase skipped
  PASS1/yfshbfE#1 test_linux_kernel_regression.py##performance_lmbench3 @duhb-ylly|capi-lr40n07_5001/r245s001 [+1221.5s]: subcase passed
  PASS1/d9xaax test_linux_kernel_regression.py @duhb-ylly [+1221.5s]: evaluation passed
  PASS1/dupijs test_linux_kernel_regression.py##default_cachedrop @duhb-ylly [+0.0s]: subcase passed
  PASS1/0yyygl test_linux_kernel_regression.py##default_insert_leap_second @duhb-ylly [+0.0s]: subcase passed
  ...
  PASS1/awq3ac test_linux_kernel_regression.py##default_stack-randomness @duhb-ylly [+0.0s]: subcase passed
  PASS1/ua9gbj test_linux_kernel_regression.py##default_sysfs-perms @duhb-ylly [+0.0s]: subcase passed
  PASS1/5gsxfo test_linux_kernel_regression.py##default_timer-overhead @duhb-ylly [+0.0s]: subcase passed
  FAIL0/bzqbra test_linux_kernel_regression.py##stress_ltp @duhb-ylly [+0.0s]: subcase failed
  FAIL0/8axjqm test_linux_kernel_regression.py##stress_ltp_ltp_lib_newlib_tests @duhb-ylly [+0.0s]: subcase failed
  PASS1/yfshbf test_linux_kernel_regression.py##performance_lmbench3 @duhb-ylly [+0.0s]: subcase passed
  FAIL0/ toplevel @local [+1232.8s]: 17 tests (10 passed, 0 error, 3 failed, 0 blocked, 4 skipped, in 0:20:23.408665) - failed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import re

import tcfl

@tcfl.tc.interconnect("ipv4_addr",
                      mode = os.environ.get('MODE', 'one-per-type'))
@tcfl.tc.target('pos_capable')
class _test(tcfl.pos.tc_pos0_base):
    """
    Basic execution of sysbench CPU test and KPI report

    **Reference**

      https://fedoraproject.org/wiki/QA:Testcase_kernel_regression

    """

    image_requested = os.environ.get("IMAGE", "fedora")

    def eval_10_ssh_setup(self, ic, target):
        # Prepares the SUT from the TCF side -- ensure SSH is up and
        # running, which also will setup proxies in the console

        # FIXME: we need a utility function for this
        if target.console.default.startswith("ssh"):
            # if the default console is on SSH, SSH on the SUT is already setup
            target.report_info("SSH already setup on SUT (on SSH console)")
            return
        try:
            target.console.select_preferred(user = 'root')  # switch to using ssh
            target.report_info("SSH: SUT already setup, SSH console enabled")
            if target.console.default.startswith("ssh"):
                # if SSH works, it means SSH is setup in the SUT
                return
        except Exception as e:
            target.report_info(
                f"SSH: can't enable preferred console, retrying: {e}")

        # seems a preferred SSH console hasn't been set, this means
        # SSH is not setup in the SUT, so set it up and try to switch
        # to a preferred SSH as a console (if there is one, otherwise
        # it'll do nothing)
        tcfl.tl.linux_network_ssh_setup(ic, target, proxy_wait_online = True)
        target.console.select_preferred(user = 'root')  # switch to using ssh


    def eval_20_setup(self, ic, target):

        # use PROMPT# vs PROMPT%, so that it also matches the
        # general initial regex in target.shell.setup() and it
        # servers in scenarios where we shortcut initialization
        target.shell.prompt_regex = re.compile("TCF-%(tc_hash)s:PROMPT# " % self.kws)
        target.shell.run(
            "export PS1='TCF-%(tc_hash)s:''PROMPT# '  # a simple prompt is "
            "harder to confuse with general output" % self.kws)

        tcfl.tl.sh_export_proxy(ic, target)
        tcfl.tl.linux_wait_online(ic, target)

        target.report_info(f"cloning/updating the kernel-tests repo",
                           dlevel = -1)
        target.shell.run(
            "cd; test -d kernel-tests"
            " && git -C kernel-tests pull -f"
            " || git clone https://pagure.io/kernel-tests.git")

        # 3. You need Package-x-generic-16.pngmake,
        #    - libtirpc,
        #    - libtirpc-devel and
        #    - policycoreutils-python-utils
        #    in order to run the tests, if it is not already installed.
        target.report_info(f"ensuring dependencies are installed",
                           dlevel = -1)
        tcfl.tl.linux_os_release_get(target, prefix = "")

        if target.kws['linux.distro'] == "ubuntu":
            # fix repositories -- there was a better way to do this
            target.shell.run(
                "sed -i 's/main restricted/main restricted universe multiverse/'"
                " /etc/apt/sources.list")
            target.shell.run("apt-get -y update")

        # this is a convention acknowloedged by
        # :class:`tcfl.pos.tc_pos0_base`).
        tcfl.tl.linux_package_add(ic, target,
                                  centos = [ 'epel-release' ])
        tcfl.tl.linux_package_add(
            ic, target,
            "gcc",
            "git",
            "libtirpc",
            "libtirpc-devel",
            "make",
            "policycoreutils-python-utils",
            "python3",
        )

        # 4. Allow testsuite to make their heap memory executable
        target.shell.run("semanage boolean -m --on selinuxuser_execheap")


    def eval_40_run(self, ic, target):

        mins = 3
        target.report_info(f"running default testcases (for max {mins}m)",
                           dlevel = -1)
        target.shell.run("cd ~/kernel-tests; rm -rf logs")
        output = target.shell.run(
            f"./runtests.sh || echo FAILED-{self.kws['tc_hash']}",
            timeout = mins * 60,
            output = True)
        self._logs_get_and_parse(target, output)

        mins = 20
        target.report_info(f"running stress testcases (for max {mins}m)",
                           dlevel = -1)
        target.shell.run("cd ~/kernel-tests; rm -rf logs")
        output = target.shell.run(
            f"./runtests.sh -t stress || echo FAILED-{self.kws['tc_hash']}",
            timeout = 20 * 60,
            output = True)
        self._logs_get_and_parse(target, output, "-stress")

        if "LINUX_KERNEL_REGRESSION_STRESS" in os.environ:
            # not always needed, takes a long time
            mins = 40
            target.report_info(f"running performance testcases (for max {mins}m)")
            target.shell.run("cd ~/kernel-tests; rm -rf logs",
                               dlevel = -1)
            output = target.shell.run(
                f"./runtests.sh -t performance || echo FAILED-{self.kws['tc_hash']}",
                timeout = mins * 60,
                output = True)
            self._logs_get_and_parse(target, output, "-performance")

        # we have it all now, report all the subcases
        for subcase_name, result in self.subcase_data.items():
            output = self.subcase_output.get(subcase_name, '<no output>')
            # ./default/somename -> default_somename
            subcase_e = subcase_name.lstrip("./").replace("/", "_")
            with self.subcase(subcase_e):
                if result in [ "PASS", "WARN" ]:
                    target.report_pass("subcase passed",
                                       dict(output = output),
                                       level = 1)
                elif result == "SKIP":
                    target.report_skip("subcase skipped",
                                       dict(output = output),
                                       level = 1)
                elif result == "FAIL":
                    target.report_fail("subcase failed",
                                       dict(output = output),
                                       level = 1, alevel = 1)
                else:
                    target.report_error(f"unexpected result {result}",
                                        dict(output = output),
                                        level = 1, alevel = 1)


    def _logs_get_and_parse(self, target, output, log_tag = ""):
        # parse the output and report subcases
        #
        ## Test suite called with default
        ## ./default/cachedrop                                              PASS
        ## ./default/insert_leap_second                                     SKIP
        ## ./default/libhugetlbfs                                           SKIP
        ## ...
        ## ./default/selinux-dac-controls                                   SKIP
        ## ./default/stack-randomness                                       PASS
        ## ./default/sysfs-perms                                            FAIL
        ## ./default/timer-overhead                                         PASS
        ##
        ## Test suite complete                                              FAIL
        ##
        ## Your log file is located at: /root/kernel-tests/logs/kernel-test-1652316328.log.txt
        ## Submit your results to: https://apps.fedoraproject.org/kerneltest/
        ## The following information is not submitted with your log;
        ## it is for informational purposes only.
        ## Checking for kernel signature:
        ## Vulnerability status:
        ## /sys/devices/system/cpu/vulnerabilities/itlb_multihit:KVM: Mitigation: VMX disabled
        ## /sys/devices/system/cpu/vulnerabilities/l1tf:Not affected
        ## ...
        ## /sys/devices/system/cpu/vulnerabilities/srbds:Not affected
        ## /sys/devices/system/cpu/vulnerabilities/tsx_async_abort:Mitigation: Clear CPU buffers; SMT vulnerable
        subcase_regex = re.compile("^(?P<subcase>[^ ]+) +(?P<result>(PASS|SKIP|FAIL))$")
        logfile_regex = re.compile("Your log file is located at: (?P<logfile>.*)$")
        self.subcase_data = {}
        logfile = None
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            m = subcase_regex.match(line)
            if m:
                subcase = m.groupdict()['subcase']
                result = m.groupdict()['result']
                self.subcase_data[subcase] = result
                continue
            m = logfile_regex.match(line)
            if m:
                logfile = m.groupdict()['logfile']

        # now pull the log file from the SUT, that contains details,
        # and divide in the output of each subcase, to have some more details
        self.subcase_output = {}
        if logfile:
            target.ssh.copy_from(logfile, self.report_file_prefix
                                 + f"kernel-test-log{log_tag}.txt")
            with open(self.report_file_prefix + f"kernel-test-log{log_tag}.txt") as l:
                ## Starting test ./default/posix_timers
                ## Testing posix timers. False negative may happen on CPU execution
                ## based timers if other threads run on the CPU...
                ## ...
                ## Starting test ./default/paxtest
                current_tc = None
                current_output = ''
                for line in l:
                    if line.startswith("Starting test "):
                        if current_tc:
                            # flush output for current testcase
                            self.subcase_output[current_tc] = current_output
                        # start new testcase
                        current_tc = line[len("Starting test"):].strip()
                        continue
                    # append
                    current_output += line
