#! /usr/bin/python
import os
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
    def start_00(ic):
        ic.power.cycle()

    @staticmethod
    def eval_00_server(zephyr_server):
        zephyr_server.expect("init_app: Run echo server")
        zephyr_server.expect("receive: Starting to wait")
