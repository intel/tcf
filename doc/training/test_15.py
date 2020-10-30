#! /usr/bin/python3
import os
import re
import tcfl.tc
import tcfl.tl
@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target(name = "zephyr_server",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86',
                              'arduino_101', 'sam_e70_xplained'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "echo_server"))
@tcfl.tc.target(name = "zephyr_client",
                spec = """zephyr_board in [
                              'frdm_k64f', 'qemu_x86',
                              'arduino_101', 'sam_e70_xplained'
                          ]""",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "net", "echo_client"))
class _test(tcfl.tc.tc_c):

    @staticmethod
    @tcfl.tc.serially()
    def build_00_server_config(zephyr_server):
        if 'mac_addr' in zephyr_server.kws:
            zephyr_server.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_server.kws['mac_addr'])
        else:
            zephyr_server.zephyr.config_file_write("mac_addr", "")

        zephyr_server.zephyr.config_file_write(
            "ip_addr",
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            % zephyr_server.kws['ipv4_addr'])

    @staticmethod
    @tcfl.tc.serially()
    def build_00_client_config(zephyr_client, zephyr_server):
        if 'mac_addr' in zephyr_client.kws:
            zephyr_client.zephyr.config_file_write(
                "mac_addr",
                "CONFIG_SLIP_MAC_ADDR=\"%s\"\n"
                % zephyr_client.kws['mac_addr'])
        else:
            zephyr_client.zephyr.config_file_write("mac_addr", "")

        zephyr_client.zephyr.config_file_write(
            "ip_addr",
            "CONFIG_NET_APP_SETTINGS=y\n"
            "CONFIG_NET_APP_MY_IPV4_ADDR=\"%s\"\n"
            "CONFIG_NET_APP_PEER_IPV4_ADDR=\"%s\"\n"
            % (zephyr_client.kws['ipv4_addr'],
               zephyr_server.kws['ipv4_addr'],))

    def start_50_zephyr_server(self, zephyr_server):
        pass

    def start_50_zephyr_client(self, zephyr_client):
        pass

    def start_00(self, ic, zephyr_server, zephyr_client):
        ic.power.cycle()
        self.overriden_start_50_zephyr_server(zephyr_server)
        zephyr_server.expect("init_app: Run echo server")
        zephyr_server.expect("receive: Starting to wait")
        self.overriden_start_50_zephyr_client(zephyr_client)

    @staticmethod
    def eval_10_client(zephyr_client):
        zephyr_client.expect("init_app: Run echo client")
        zephyr_client.expect(re.compile("Compared [0-9]+ bytes, all ok"))
