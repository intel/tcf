#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import types
import urllib.parse

import requests
import tcfl.tc
import tcfl.tl

_cmd_regex_shell = re.compile(r" [0-9]+ \$ ")
def _cmd(linux, command, expect = None):
    linux.send(command)
    if expect:
        if isinstance(expect, list):
            for item in expect:
                linux.expect(item)
        else:
            linux.expect(expect)
    linux.expect(_cmd_regex_shell)

# Want an interconnect that supports IPv4 (so we test for it having
# any IP address assigned)
@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.interconnect(spec = "ipv4_addr or ipv6_addr")
@tcfl.tc.target(name = "linux", spec = "linux", mode = "any")
@tcfl.tc.target(name = "zephyr",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86', 'arduino_101'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "http_server"),
                mode = 'one-per-type')
class _test(tcfl.tc.tc_c):
    """Test a basic HTTP request

    Make an HTTP request to Zephyr over a tunnel from the machine
    executing this testcase and another from a linux target to the
    Zephyr target.
    """

    # Ensure no proxy information is used
    proxies = {
        "http": None,
        "https": None,
    }

    @staticmethod
    @tcfl.tc.serially()
    def configure(linux, zephyr):
        # FIXME: this needs to be moved somewhere
        linux.cmd = types.MethodType(_cmd, linux)

    @staticmethod
    @tcfl.tc.serially()
    def build_zephyr_config(linux, zephyr):
        # Force the IP and MAC address from the target into the
        # configuration.

        # This is needed for SLIP on QEMU
        if 'mac_addr' in zephyr.kws:
            zephyr.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n" % zephyr.kws['mac_addr'])
        else:
            zephyr.zephyr.config_file_write("mac_addr", "")

        zephyr.zephyr.config_file_write(
            "ip_addr",
            # Debugging settings
            "CONFIG_NET_DEBUG_ARP=y\n"
            "CONFIG_NET_DEBUG_L2_ETHERNET=y\n"
            "CONFIG_SYS_LOG_NET_LEVEL=4\n"
            "CONFIG_SLIP_DEBUG=y\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            % (
                zephyr.kws['ipv6_addr'],
                zephyr.kws['ipv4_addr'],
            )
        )

    def start(self, ic, linux):
        ic.property_set('tcpdump', self.kws['tc_hash'] + ".cap")
        ic.power.cycle()
        linux.power.cycle()
        # targets zephyr* are started automagically by app_zehyr's
        # builtin stuff - we want to make sure the interconnect is
        # started always the first, otherwise the system won't be able
        # to talk to the targets (especially the virtual ones).

    def eval_08_zephyr(self, zephyr):
        self.zephyr = zephyr
        # This creates a tunnel to target's port 80 that we can access
        # at the server
        self.port = zephyr.tunnel.add(80)
        self.report_info("Tunnel added")
        # To connect to the tunnel, we need to know the server's hostname
        url = urllib.parse.urlparse(zephyr.rt['url'])
        self.report_info("Sending request")
        try:
            # Send the request to the server's tunnel end that will go
            # to the target's port 80
            r = requests.get('http://%s:%d/index.html'
                             % (url.hostname, self.port),
                             proxies = self.proxies, timeout = 5)
        except requests.exceptions.RequestException as e:
            raise tcfl.tc.failed_e("Can't connect: %s" % e,
                                   {
                                       "console %s output" % zephyr.fullid:
                                       zephyr.console.read()
                                   })
        self.report_info("Request returns %s" % r)
        if r.status_code != 200:
            raise tcfl.tc.failed_e("Status code is not 200 but %d"
                                   % r.status_code)

    def eval_01_linux_up(self, linux):
        # Giving it ample time to boot, wait for a shell prompt (the
        # VM is set to autologin on the console)
        self.expecter.timeout = 60
        linux.expect(_cmd_regex_shell)

        # Trap the shell to complain loud if a command fails, and catch it
        linux.cmd("trap 'echo ERROR-IN-SHELL' ERR")
        linux.on_console_rx("ERROR-IN-SHELL", result = 'fail', timeout = False)

        # Ensure there is a network interface up; lo won't have
        # BROADCAST or MULTICAST
        linux.cmd('ip link show', "BROADCAST,MULTICAST,UP,LOWER_UP")
        # print network info, to diagnose
        linux.cmd('ip addr show; route -vn; route -vnA inet6')

    @staticmethod
    def eval_02_linux_pings_zephyr(linux, zephyr):
        # Verify the linux target can ping the zephyr target
        times = 4
        addr = zephyr.kws['ipv4_addr']
        with linux.on_console_rx_cm("Destination Host Unreachable",
                                    result = "fail", timeout = False):
            linux.cmd("ping -c %d %s" % (times, addr),
                      "64 bytes from %s: icmp_seq=%d" % (addr, times))


    def eval_05_linux_wgets4_zephyr(self, linux, zephyr):
        # Have the linux target get from Zephyr
        # FIXME: how to capture zephyr's console when this fails
        # Set timeout on curl?
        self.expecter.timeout = 10
        linux.cmd("curl -vvv http://%(ipv4_addr)s" % zephyr.kws,
                  re.compile("HTTP/.* 200 OK"))

    def eval_05_linux_wgets6_zephyr(self, linux, zephyr):
        # Have the linux target get from Zephyr
        # FIXME: how to capture zephyr's console when this fails
        # Set timeout on curl?
        self.expecter.timeout = 10
        # Curl needs square brackets to distinguish an IPv6 address
        # from a host:port pair and the shell needs the backslash to
        # avoid interpreting those square brackets as a metachar
        linux.cmd(r"curl -vvv http://\[%(ipv6_addr)s\]" % zephyr.kws,
                  re.compile("HTTP/.* 200 OK"))

    def teardown_dump_console(self):
        if not self.result_eval.failed and not self.result_eval.blocked:
            return
        for target in list(self.targets.values()):
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

    def teardown(self, ic):
        ic.power.off()	# ensure tcpdump flushes
        # Get the TCP dump from the interconnect to a file in the CWD
        # called report-RUNID:HASH.tcpdump
        ic.store.dnload(
            self.kws['tc_hash'] + ".cap",
            "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)
        self.report_info("tcpdump available in file "
                         "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)
