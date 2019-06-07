#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import filecmp
import os
import re
import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Want an interconnect that supports IPv4 (so we test for it having
# any IP address assigned)
@tcfl.tc.interconnect(spec = "ipv4_addr")
@tcfl.tc.target(name = "linux", spec = "linux", mode = "any")
@tcfl.tc.target(name = "zephyr_server",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86',
                              'arduino_101', 'sam_e70_xplained'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "echo_server"),
                mode = 'one-per-type')
class _test(tcfl.tc.tc_c):
    """
    A Linux target can ping a Zephyr target and pass data around the
    echo server.
    """

    @staticmethod
    @tcfl.tc.serially()
    def build_zephyr_server_config(linux, zephyr_server):
        # Force the IP and MAC address from the target into the
        # configuration.

        if 'mac_addr' in zephyr_server.kws:
            zephyr_server.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_server.kws['mac_addr'])
        else:
            zephyr_server.zephyr.config_file_write("mac_addr", "")

        zephyr_server.zephyr.config_file_write(
            "ip_addr",
            # Debugging settings
            "CONFIG_NET_DEBUG_L2_ETHERNET=y\n"
            "CONFIG_SYS_LOG_NET_LEVEL=4\n"
            "CONFIG_SLIP_DEBUG=y\n"
            # Old settings, <= 1.7
            "CONFIG_NET_SAMPLES_MY_IPV4_ADDR=\"%s\"\n"
            "CONFIG_NET_SAMPLES_PEER_IPV4_ADDR=\"%s\"\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV4_ADDR=\"%s\"\n"
            % (
                zephyr_server.kws['ipv4_addr'],
                linux.kws['ipv4_addr'],
                zephyr_server.kws['ipv6_addr'],
                linux.kws['ipv6_addr'],
                zephyr_server.kws['ipv4_addr'],
                linux.kws['ipv4_addr'],
            )
        )

    @staticmethod
    def start(ic, linux):
        ic.power.cycle()
        linux.power.cycle()
        # targets zephyr* are started automagically by app_zehyr's
        # builtin stuff - we want to make sure the interconnect is
        # started always the first, otherwise the system won't be able
        # to talk to the targets (especially the virtual ones).

    def eval_01_linux_up(self, linux):
        # Giving it ample time to boot, wait for a shell prompt (the
        # VM is set to autologin on the console)
        self.expecter.timeout = 60
        linux.expect(re.compile(r"[0-9]+ \$"))

        # Trap the shell to complain loud if a command fails, and catch it
        linux.send("trap 'echo ERROR-IN-SHELL' ERR")
        linux.on_console_rx("ERROR-IN-SHELL", result = 'fail', timeout = False)

        # There has to be an interface that IS NOT loopback that has
        # UP and LOWER_UP enabled (connected, online)
        linux.send('ip link show')
        # lo won't have BROADCAST or MULTICAST
        linux.expect("BROADCAST,MULTICAST,UP,LOWER_UP")
        linux.expect(re.compile(r"[0-9]+ \$"))
        linux.send('ip addr show')
        linux.expect(re.compile(r"[0-9]+ \$"))
        linux.send('route -vn')
        linux.expect(re.compile(r"[0-9]+ \$"))
        linux.send('route -vnA inet6')
        linux.expect(re.compile(r"[0-9]+ \$"))

    @staticmethod
    def eval_02_linux_pings_server(linux, zephyr_server):
        times = 4
        addr = zephyr_server.kws['ipv4_addr']
        with linux.on_console_rx_cm("Destination Host Unreachable",
                                    result = "fail", timeout = False):
            linux.send("ping -c %d %s" % (times, addr))
            linux.expect("64 bytes from %s: icmp_seq=%d" % (addr, times))

    @staticmethod
    def eval_03_linux_pings_server(linux, zephyr_server):
        times = 4
        addr = zephyr_server.kws['ipv6_addr']
        with linux.on_console_rx_cm("Destination Host Unreachable",
                                    result = "fail", timeout = False):
            linux.send("ping6 -c %d %s" % (times, addr))
            linux.expect("64 bytes from %s: icmp_seq=%d" % (addr, times))

    def eval_05_linux_netcats_server(self, ic, linux, zephyr_server):
        linux.send('dd if=/dev/urandom of=sample.tx.file bs=1024 count=4')
        linux.expect(re.compile(r"[0-9]+ \$"))
        linux.send('nc %s 4242 < sample.tx.file > sample.rx.file & '
                   # Wait for the zephyr side to reply and then kill netcat
                   'sleep 3s; '
                   'kill %%1 || true'
                   % zephyr_server.kws['ipv4_addr'])
        linux.expect(re.compile(r"[0-9]+ \$"))
        linux.send('ls -l sample.tx.file sample.rx.file')
        linux.expect(re.compile(r"[0-9]+ \$"))
        # Are files the same?
        os.chdir(self.tmpdir)
        linux.tunnel.ip_addr = linux.addr_get(ic, "ipv4")
        linux.ssh.copy_from("sample.tx.file")
        linux.ssh.copy_from("sample.rx.file")
        if filecmp.cmp("sample.tx.file", "sample.tx.file", False) == False:
            raise tcfl.tc.failed_e("TXed and RXed files differ")

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


    def teardown(self):
        for _twn, target  in reversed(list(self.targets.items())):
            target.power.off()
