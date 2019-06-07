#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
""" This sample test verifies the packet transfer between server
and client in zephyr through UDP/TCP in IPv4 and IPv6
"""
import os
import re
import time
import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
class _test_base(tcfl.tc.tc_c):
    """A Zephyr target running echo client can talk to an echo server.

    This is the common class that contains the common tests to IPv4
    and 6, then we'll inherit from it.

    """

    @staticmethod
    def setup_verify_slip_feature(zephyr_client, zephyr_server):
        tcfl.tl.setup_verify_slip_feature(zephyr_client, zephyr_server,
                                          tcfl.tl.ZEPHYR_BASE)

    #
    # Start the targets
    #
    # We need first the interconnect, then the Zephyr server to be
    # started and initialized before the Zephyr client starts.

    # Override how app_zephyr starts zephyr_{server,client}so we'll
    # use overriden_start_50_zephyr_{server,client} in the right
    # order.
    def start_50_zephyr_server(self, zephyr_server):
        """start zephyr server"""
        pass

    def start_50_zephyr_client(self, zephyr_client):
        """start zephyr client"""
        pass

    def start(self, ic, zephyr_server, zephyr_client):
        """power cycle's zephyr client,server and interconnect"""
        ic.power.cycle()
        # targets zephyr* are started automagically by app_zehyr's
        # builtin stuff - we want to make sure the interconnect is
        # started always the first, otherwise the system won't be able
        # to talk to the targets (especially the virtual ones).
        self.overriden_start_50_zephyr_server(zephyr_server)
        time.sleep(1)
        zephyr_server.expect(re.compile("[a-zA-Z]"))
        self.overriden_start_50_zephyr_client(zephyr_client)

    # The client keeps talking to the server and receiving data
    # The client knows the server's IP address because we configured
    # it in the image
    def eval_04_client_reports_all_ok(self, ic, zephyr_server, zephyr_client):
        """Verification of packets transmission between client
        and server"""
        if True:
            zephyr_client.report_info("Giving the client 20s to run")
            time.sleep(20)
        else:
            for i in range(1, 11):
                self.report_info("Giving the client 50s #%d/10" % i)
                zephyr_client.active()
                zephyr_server.active()
                ic.active()
                time.sleep(50)
                self.report_info("Waited 50s #%d/10" % i)
        s = zephyr_client.console.read()
        r = re.compile("Compared [0-9]+ bytes, all ok")
        # Do this so we run the expect loop and look for failures
        zephyr_client.expect(r)
        count = 0
        need = 10
        # Re-read all the console output and look for at least 10 packets
        s = zephyr_client.console.read()
        for l in s.split("\n"):
            self.report_info("DEBUG: checking line " + l)
            if r.search(l.strip()):
                count += 1
            if count >= need:
                break
        else:
            raise tcfl.tc.failed_e("Didn't get at least %d 'all ok' "
                                   "messages (but %d)" % (need, count))
        zephyr_client.report_pass("Got at least %d 'all ok' messages" % count)

    def teardown_dump_console(self):
        tcfl.tl.console_dump_on_failure(self)


# Want an interconnect that supports IPv4 (so we test for it having
# any IP address assigned)
@tcfl.tc.interconnect(spec = "ipv4_addr")
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
class _test_ipv4(_test_base):
    """
    A Zephyr target running echo client can talk to an echo server.
    """

    @staticmethod
    @tcfl.tc.serially()
    def build_00_server_config(zephyr_server):
        """configuration build for the server"""
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_server.kws:
            zephyr_server.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_server.kws['mac_addr'])
        else:
            zephyr_server.zephyr.config_file_write("mac_addr", "")

        zephyr_server.zephyr.config_file_write(
            "ipv4_addr",
            "CONFIG_NET_IPV4=y\n"
            "CONFIG_NET_IPV6=n\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_SERVER=y\n"
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            % (zephyr_server.kws['ipv4_addr']))

    @staticmethod
    @tcfl.tc.serially()
    def build_00_client_config(zephyr_client, zephyr_server):
        """configuration build for the client"""
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_client.kws:
            zephyr_client.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_client.kws['mac_addr'])
        else:
            zephyr_client.zephyr.config_file_write("mac_addr", "")

        zephyr_client.zephyr.config_file_write(
            "ipv4_addr",
            "CONFIG_NET_IPV4=y\n"
            "CONFIG_NET_IPV6=n\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_CLIENT=y\n"
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV4_ADDR=\"%s\"\n"
            % (zephyr_client.kws['ipv4_addr'],
               zephyr_server.kws['ipv4_addr']))


@tcfl.tc.interconnect(spec = "ipv6_addr")
@tcfl.tc.target(name = "zephyr_server",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86', 'arduino_101',
                              'sam_e70_xplained'
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
class _test_ipv6(_test_base):
    """
    A Zephyr target running echo client can talk to an echo server.
    """

    @staticmethod
    @tcfl.tc.serially()
    def build_00_server_config(zephyr_server):
        """configuration build for the server"""
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_server.kws:
            zephyr_server.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_server.kws['mac_addr'])
        else:
            zephyr_server.zephyr.config_file_write("mac_addr", "")

        zephyr_server.zephyr.config_file_write(
            "ipv6_addr",
            "CONFIG_NET_IPV4=n\n"
            "CONFIG_NET_IPV6=y\n"
            # Newer settings > 1.7
            "CONFIG_NET_APP_SERVER=y\n"
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            % (zephyr_server.kws['ipv6_addr']))

    @staticmethod
    @tcfl.tc.serially()
    def build_00_client_config(zephyr_client, zephyr_server):
        """configuration build for the client"""
        # Force the IP and MAC address from the target into the
        # configuration.

        # FIXME: this might be movable to app_zephyr?
        if 'mac_addr' in zephyr_client.kws:
            zephyr_client.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_client.kws['mac_addr'])
        else:
            zephyr_client.zephyr.config_file_write("mac_addr", "")

        zephyr_client.zephyr.config_file_write(
            "ipv6_addr",
            "CONFIG_NET_IPV4=n\n"
            "CONFIG_NET_IPV6=y\n"
            "CONFIG_NET_APP_CLIENT=y\n"
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV6_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV6_ADDR=\"%s\"\n"
            % (zephyr_client.kws['ipv6_addr'],
               zephyr_server.kws['ipv6_addr']))
