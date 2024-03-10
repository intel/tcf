#! /usr/bin/env python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
.. _example_sysbench:

Deploy an Linux OS and run sysbench
===================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS and
run sysbench, report data.

.. literalinclude:: /examples/test_sysbench.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_sysbench.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ tcf -e IMAGE=fedora run -v /usr/share/tcf/examples/test_sysbench.py
  INFO2/ toplevel @local [+0.7s]: scanning for test cases
  INFO1/vnc2ri test_sysbench.py @llkn-jibx [+0.1s]: will run on target group 'ic=NETWORKNAME target=TARGETNAME:x86_64' (PID 807339 / TID 7f385739f640)
  INFO1/vnc2ri test_sysbench.py @llkn-jibx [+0.2s]: allocation ID: xhczvb9f
  INFO2/vnc2riD test_sysbench.py @llkn-jibx|NETWORKNAME [+1.7s]: powered on
  DATA2/vnc2riDPOS test_sysbench.py @llkn-jibx|TARGETNAME [+65.0s]: TCF persistant cache usage::TARGETNAME:/dev/sda5::2566
  INFO1/vnc2riDPOS test_sysbench.py @llkn-jibx|TARGETNAME [+65.4s]: POS: rsyncing fedora:workstation:33:1.2:x86_64 from 192.168.117.1::images to /dev/sda5
  DATA2/vnc2riDPOS test_sysbench.py @llkn-jibx|TARGETNAME [+124.9s]: Deployment stats image fedora:workstation:33:1.2:x86_64::image rsync to TARGETNAME (s)::58.97
  PASS2/vnc2riD test_sysbench.py @llkn-jibx|TARGETNAME [+135.2s]: deployed fedora:workstation:33:1.2:x86_64
  PASS2/vnc2ri test_sysbench.py @llkn-jibx [+135.2s]: deploy passed
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|NETWORKNAME [+135.2s]: powered on
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+135.2s]: POS: setting target to not boot Provisioning OS
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+143.0s]: power cycled
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+246.7s]: shell-up: sending a couple of blind CRLFs to clear the command line
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+269.4s]: shell/serial0: sent command: echo $PS1 | grep -q ^TCF- || export PS1="TCF-vnc2ri:$PS1"
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+269.7s]: shell/serial0: sent command: test ! -z "$BASH" && set +o vi +o emacs
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+270.0s]: shell/serial0: sent command: trap 'echo ERROR''-IN-SHELL' ERR
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+270.4s]: shell/default: sent command: export http_proxy=http://192.168.117.1:8888; export HTTP_PROXY=$http_proxy
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+270.7s]: shell/default: sent command: export https_proxy=http://192.168.117.1:8888; export HTTPS_PROXY=$https_proxy
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+271.0s]: shell/default: sent command: export  no_proxy=127.0.0.1,localhost,192.168.117.1/24,fd:a8:75::1/104
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+271.4s]: shell/default: sent command: export NO_PROXY=$no_proxy
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+271.7s]: shell/default: sent command: for i in {1..20}; do hostname -I | grep -Fq 192.168.117.78 && break; date +'waiting 0.5 @ %c'; sleep 0.5s;done; hostname -I # block until the expected IP is assigned, we are online
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+272.1s]: shell/default: sent command: cat /etc/os-release || true
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+272.5s]: shell/default: sent command: date -us '2021-10-08 19:52:18.652848'; hwclock -wu
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+273.6s]: shell/default: sent command: dnf install --releasever 33 -qy sysbench
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+317.5s]: shell/default: sent command: sysbench memory  run
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Memory speed / events (count)::63716962.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Memory speed / events per second (events/s)::6370611.73
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Memory speed / transferred size (MiB)::62223.6
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Memory speed / transfer speed (MiB/s)::6221.3
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::General statistics / total time (s)::10.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::General statistics / total number of events::63716962.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Latency / Minimum (ms)::0.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Latency / Average (ms)::0.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Latency / Maximum (ms)::0.02
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Latency / 95th percentile (ms)::0.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Latency / Sum (ms)::4716.13
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Threads fairness / events average (s)::63716962.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Threads fairness / events standard deviation (s)::0.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Threads fairness / execution time average (s)::4.7161
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.0s]: sysbench <TARGETYPE>: memory::Threads fairness / execution time standard deviation (s)::0.0
  INFO2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+328.1s]: shell/default: sent command: sysbench cpu --cpu-max-prime=2000 run
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::CPU speed / events per second (count)::10140.42
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::General statistics / total time (s)::10.0001
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::General statistics / total number of events::101427.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Latency / Minimum (ms)::0.1
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Latency / Average (ms)::0.1
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Latency / Maximum (ms)::0.14
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Latency / 95th percentile (ms)::0.1
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Latency / Sum (ms)::9987.51
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Threads fairness / events average (s)::101427.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Threads fairness / events standard deviation (s)::0.0
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Threads fairness / execution time average (s)::9.9875
  DATA2/vnc2riE#1 test_sysbench.py @llkn-jibx|TARGETNAME [+338.5s]: sysbench <TARGETYPE>: cpu --cpu-max-prime=2000::Threads fairness / execution time standard deviation (s)::0.0
  PASS1/vnc2ri test_sysbench.py @llkn-jibx [+338.5s]: evaluation passed
  PASS0/ toplevel @local [+339.7s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:05:38.651842) - passed

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

    """

    image_requested = os.environ.get("IMAGE", "fedora")

    def eval(self, ic, target):

        # use PROMPT# vs PROMPT%, so that it also matches the
        # general initial regex in target.shell.setup() and it
        # servers in scenarios where we shortcut initialization
        target.shell.prompt_regex = re.compile("TCF-%(tc_hash)s:PROMPT# " % self.kws)
        target.shell.run(
            "export PS1='TCF-%(tc_hash)s:''PROMPT# '  # a simple prompt is "
            "harder to confuse with general output" % self.kws)

        tcfl.tl.sh_export_proxy(ic, target)
        tcfl.tl.linux_wait_online(ic, target)

        tcfl.tl.linux_os_release_get(target, prefix = "")
        # Switch to SSH console if available
        if 'preferred' in target.console.list():
            real_name = target.console.setup_get('preferred')['real_name']
            if real_name.startswith("ssh"):
                tcfl.tl.linux_network_ssh_setup(ic, target)
                target.console.select_preferred(user = 'root')
                # use PROMPT# vs PROMPT%, so that it also matches the
                # general initial regex in target.shell.setup() and it
                # servers in scenarios where we shortcut initialization
                target.shell.prompt_regex = re.compile("TCF-%(tc_hash)s:PROMPT# " % self.kws)
                target.shell.run(
                    "export PS1='TCF-%(tc_hash)s:''PROMPT# '  # a simple prompt is "
                    "harder to confuse with general output" % self.kws)
                tcfl.tl.sh_export_proxy(ic, target)

        if target.kws['linux.distro'] == "ubuntu":
            # fix repositories -- there was a better way to do this
            target.shell.run(
                "sed -i 's/main restricted/main restricted universe multiverse/'"
                " /etc/apt/sources.list")
            target.shell.run("apt-get -y update")

        if 'REBOOT_DISABLED' not in os.environ:
            # this is a convention acknowloedged by
            # :class:`tcfl.pos.tc_pos0_base`).
            tcfl.tl.linux_package_add(ic, target,
                                      centos = [ 'epel-release' ])
            tcfl.tl.linux_package_add(ic, target, 'sysbench')

        self.sysbench_run(target)


    def sysbench_run(self, target):
        """
        Run the benchmark

        This function can be easily overriden to execute other
        combination of sysbench tests
        """

        test_name = "memory"
        test_params = ""
        output = target.shell.run(
            f"sysbench {test_name} {test_params} run",
            output = True, trim = True)
        self.ouput_parse_report(target, test_name, test_params, output)

        test_name = "cpu"
        test_params = "--cpu-max-prime=2000"
        output = target.shell.run(
            f"sysbench {test_name} {test_params} run",
            output = True, trim = True)
        self.ouput_parse_report(target, test_name, test_params, output)


    # parse the output and report data
    # break it down in multiple regexes instead of a big one,
    # easier to handle

    # Sysbench console output is in parts:
    #
    # - initial while it runs
    # - test-specifc results
    # - general
    #
    # Kinda like
    #
    ## sysbench 1.0.11 (using system LuaJIT 2.1.0-beta3)\r
    ## \r
    ## Running the test with following options:\r
    ## Number of threads: 1\r
    ## Initializing random number generator from current time\r
    ## \r
    ## \r
    ## Prime numbers limit: 20000\r
    ## \r
    ## Initializing worker threads...\r
    ## \r
    ## Threads started!\r
    ## \r
    ## CPU speed:\r
    ##     events per second:   599.78\r
    ## \r
    #
    # From here, the output is general to all the testcases
    #
    ## General statistics:\r
    ##     total time:                          10.0010s\r
    ##     total number of events:              5999\r
    ## \r
    ## Latency (ms):\r
    ##          min:                                  1.64\r
    ##          avg:                                  1.67\r
    ##          max:                                  6.55\r
    ##          95th percentile:                      1.76\r
    ##          sum:                               9999.77\r
    ## \r
    ## Threads fairness:\r
    ##     events (avg/stddev):           5999.0000/0.00\r
    ##     execution time (avg/stddev):   9.9998/0.00\r
    ## \r
    ## root@localhost:~#
    #
    #
    output_parse_specific = {
        "cpu": {
            #
            ## CPU speed:
            ## events per second: 10124.10
            #
            re.compile(
                r"^\s+events per second: +(?P<value>[\.0-9]+)$",
                re.MULTILINE): {
                    'value': "CPU speed / events per second (count)",
            },
        },
        "memory": {
            #
            ## Total operations: 63659271 (6364591.44 per second)
            ##
            ## 62167.26 MiB transferred (6215.42 MiB/sec)
            #
            re.compile(
                r"^\s*Total operations:\s+(?P<ops>[0-9]+)\s+\((?P<speed>[\.0-9]+) per second\)$",
                re.MULTILINE): {
                    'ops': "Memory speed / events (count)",
                    'speed': "Memory speed / events per second (events/s)",
            },
            re.compile(
                r"^\s*(?P<size>[\.0-9]+)\s+MiB transferred\s+\((?P<speed>[\.0-9]+) MiB/sec\)$",
                re.MULTILINE): {
                    'size': "Memory speed / transferred size (MiB)",
                    'speed': "Memory speed / transfer speed (MiB/s)",
            },
        }
    }

    output_parse_general = {
        re.compile(
            r"^\s+total time: +(?P<value>[\.0-9]+)s$",
            re.MULTILINE): {
                'value': "General statistics / total time (s)",
        },

        re.compile(
            r"^\s+total number of events: +(?P<total_number_of_events>[0-9]+)$",
            re.MULTILINE): {
                'total_number_of_events': "General statistics / total number of events",
        },

        re.compile(r"^\s+min: +(?P<value>[\.0-9]+)$", re.MULTILINE): {
            'value': "Latency / Minimum (ms)",
        },

        re.compile(r"^\s+avg: +(?P<value>[\.0-9]+)$", re.MULTILINE): {
            'value': "Latency / Average (ms)",
        },

        re.compile(r"^\s+max: +(?P<value>[\.0-9]+)$", re.MULTILINE): {
            'value': "Latency / Maximum (ms)",
        },

        re.compile(r"^\s+95th percentile: +(?P<value>[\.0-9]+)$", re.MULTILINE): {
            'value': "Latency / 95th percentile (ms)",
        },

        re.compile(r"^\s+sum: +(?P<value>[\.0-9]+)$", re.MULTILINE): {
            'value': "Latency / Sum (ms)",
        },

        re.compile(
            r"^\s+events \(avg/stddev\): +(?P<avg>[\.0-9]+)/(?P<stddev>[\.0-9]+)\s*$",
            re.MULTILINE): {
                'avg': "Threads fairness / events average (s)",
                'stddev': "Threads fairness / events standard deviation (s)",
        },

        re.compile(
            r"^\s+execution time \(avg/stddev\): +(?P<avg>[\.0-9]+)/(?P<stddev>[\.0-9]+)\s*$",
            re.MULTILINE): {
                'avg': "Threads fairness / execution time average (s)",
                'stddev': "Threads fairness / execution time standard deviation (s)",
        },
    }

    def _ouput_parse_report(self, target, test_name_params, output, parse):
        for r, fields in parse.items():
            m = r.search(output)
            if m:
                gd = m.groupdict()
                for key, message in fields.items():
                    target.report_data("sysbench %(type)s: " + test_name_params,
                                       message, float(gd[key]))
            else:
                raise tcfl.error_e(
                    f"can't find data in sysbench output for: {r.pattern}",
                    dict(output = output, target = target))

    def ouput_parse_report(self, target, test_name, test_params, output):
        if test_params:
            test_name_params = test_name + " " + test_params
        else:
            test_name_params = test_name
        self._ouput_parse_report(target, test_name_params, output,
                                 self.output_parse_specific[test_name])
        self._ouput_parse_report(target, test_name_params, output,
                                 self.output_parse_general)
