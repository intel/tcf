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

import os
import re
import time
import tcfl.tc

import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Want an interconnect that supports IPv4 (so we test for it having
# any IP address assigned)
@tcfl.tc.interconnect(spec = "ipv4_addr")
@tcfl.tc.target(name = "linux",
                spec = "linux and not id:'qlf.*H'",
                mode = "any")
@tcfl.tc.target(name = "zephyr_server",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86',
                              'arduino_101', 'sam_e70_xplained'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "echo_server"),
                mode = 'one-per-type')
@tcfl.tc.target(name = "zephyr_client",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86',
                              'arduino_101', 'sam_e70_xplained'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "echo_client"),
                mode = 'one-per-type')
class _test(tcfl.tc.tc_c):
    """
    A linux target can ping a Zephyr running echo_server; a Zephyr
    echo_client can see stuff sent through the echo_server.
    """

    @staticmethod
    @tcfl.tc.serially()
    def build_00_server_config(zephyr_server):
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_server.kws:
            zephyr_server.zephyr.config_file_write(
                "mac_addr",
                'CONFIG_SLIP_MAC_ADDR="%s"\n' % zephyr_server.kws['mac_addr'])
        else:
            zephyr_server.zephyr.config_file_write("mac_addr", "")

        zephyr_server.zephyr.config_file_write(
            "ip_addr",
            # Newer settings > 1.7
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_SERVER=y\n"
            "CONFIG_NET_PKT_RX_COUNT=50\n"
            "CONFIG_NET_PKT_TX_COUNT=50\n"
            "CONFIG_NET_BUF_RX_COUNT=50\n"
            "CONFIG_NET_BUF_TX_COUNT=50\n"
            "CONFIG_NET_IF_UNICAST_IPV6_ADDR_COUNT=3\n"
            "CONFIG_NET_IF_MCAST_IPV6_ADDR_COUNT=5\n"
            "CONFIG_NET_IF_UNICAST_IPV4_ADDR_COUNT=1\n"
            "CONFIG_NET_MAX_CONTEXTS=10\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            % (
                zephyr_server.kws['ipv6_addr'],
                zephyr_server.kws['ipv4_addr']
            ))

    @staticmethod
    @tcfl.tc.serially()
    def build_00_client_config(zephyr_client, zephyr_server):
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_client.kws:
            zephyr_client.zephyr.config_file_write(
                "mac_addr",
                'CONFIG_SLIP_MAC_ADDR="%s"\n' % zephyr_client.kws['mac_addr'])
        else:
            zephyr_client.zephyr.config_file_write("mac_addr", "")

        zephyr_client.zephyr.config_file_write(
            "ip_addr",
            "CONFIG_NET_IPV6=n\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_CLIENT=y\n"
            "CONFIG_NET_PKT_RX_COUNT=50\n"
            "CONFIG_NET_PKT_TX_COUNT=50\n"
            "CONFIG_NET_BUF_RX_COUNT=50\n"
            "CONFIG_NET_BUF_TX_COUNT=50\n"
            "CONFIG_NET_IF_UNICAST_IPV6_ADDR_COUNT=3\n"
            "CONFIG_NET_IF_MCAST_IPV6_ADDR_COUNT=5\n"
            "CONFIG_NET_IF_UNICAST_IPV4_ADDR_COUNT=1\n"
            "CONFIG_NET_MAX_CONTEXTS=10\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV4_ADDR=\"%s\"\n"
            % (
                zephyr_client.kws['ipv6_addr'],
                zephyr_server.kws['ipv6_addr'],
                zephyr_client.kws['ipv4_addr'],
                zephyr_server.kws['ipv4_addr'],
            ))

    @staticmethod
    def setup_verify_slip_feature(zephyr_client, zephyr_server):
        tcfl.tl.setup_verify_slip_feature(zephyr_client, zephyr_server,
                                          tcfl.tl.ZEPHYR_BASE)

    #
    # Start the targets
    #
    # We need first the interconnect, then the linux machine, then the
    # Zephyr server to be started and initialized before the Zephyr
    # client starts.

    # Override how app_zephyr starts zephyr_{server,client}so we'll
    # use overriden_start_50_zephyr_{server,client} in the right
    # order.
    def start_50_zephyr_server(self, zephyr_server):
        pass

    def start_50_zephyr_client(self, zephyr_client):
        pass

    def start(self, ic, linux, zephyr_server, zephyr_client):
        ic.power.off()
        ic.property_set('tcpdump', self.kws['tc_hash'] + ".cap")
        ic.power.cycle()
        linux.power.cycle()
        # targets zephyr* are started automagically by app_zehyr's
        # builtin stuff - we want to make sure the interconnect is
        # started always the first, otherwise the system won't be able
        # to talk to the targets (especially the virtual ones).
        self.overriden_start_50_zephyr_server(zephyr_server)
        zephyr_server.expect("shell>")
        self.overriden_start_50_zephyr_client(zephyr_client)
        zephyr_client.expect("shell>")

    def eval_01_linux_up(self, linux):
        linux.shell.up()

    # The client doesn't ping back, we only ping the server
    @staticmethod
    def eval_03_linux_pings_server(linux, zephyr_server):
        times = 4
        addr = zephyr_server.kws['ipv4_addr']
        with linux.on_console_rx_cm("Destination Host Unreachable",
                                    result = "fail", timeout = False):
            linux.send("ping -c %d %s" % (times, addr))
            linux.expect("64 bytes from %s: icmp_seq=%d" % (addr, times))
            linux.expect(re.compile(r"[0-9]+ \$ "))

    # The client keeps talking to the server and receiving data
    # The client knows the server's IP address because we configured
    # it in the image
    @staticmethod
    def eval_04_client_reports_all_ok(zephyr_client):
        zephyr_client.report_info("Giving the client 5s to run")
        time.sleep(5)
        s = zephyr_client.console.read()
        r = re.compile("Compared [0-9]+ bytes, all ok$")
        count = 0
        need = 10
        for l in s.split("\n"):
            if r.search(l.strip()):
                count += 1
            if count >= need:
                break
        else:
            raise tcfl.tc.failed_e("Didn't get at least %d 'all ok' "
                                   "messages (but %d)" % (need, count))
        zephyr_client.report_pass("Got at least %d 'all ok' messages" % count)

    def teardown(self, ic):
        tcfl.tl.console_dump_on_failure(self)
        # Get the TCP dump from the interconnect to a file in the CWD
        # called report-RUNID:HASH.tcpdump
        ic.store.dnload(
            self.kws['tc_hash'] + ".cap",
            "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)
        self.report_info("tcpdump available in file "
                         "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)
