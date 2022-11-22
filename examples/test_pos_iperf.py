#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos_iperf:

Run iperf from a client to a server target
==========================================

Given two targets that can be booted with :ref:`Provisioning OS
<provisioning_os>` and that are interconnected by a network, boot them
and run iperf to measure network bandwidth.

.. literalinclude:: /examples/test_pos_iperf.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_pos_iperf.py>` with::

  $ tcf run -v /usr/share/tcf/examples/test_pos_iperf.py
  INFO1/oavzee test_pos_iperf.py @jffh-iilb [+0.2s]: allocation ID: any
  PASS1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+23.0s]: network interfaces configured
  PASS1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+32.9s]: client -> server pings
  PASS1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+42.8s]: server -> client pings
  INFO1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+44.2s]: iperf server started
  INFO1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+56.7s]: iperf ran successfully
  DATA1/oavzeeE#1 test_pos_iperf.py @jffh-iilb|... [+56.7s]: iperf::duration (seconds)::10.01
  DATA1/oavzeeE#1 test_pos_iperf.py @jffh-iilb|... [+56.7s]: iperf::size (Mbytes)::35950.0
  DATA1/oavzeeE#1 test_pos_iperf.py @jffh-iilb|... [+56.7s]: iperf::bandwidth (mbits/s)::30128.0
  INFO1/oavzeeE#1 test_pos_iperf.py @jffh-iilb [+57.5s]: iperf server killed
  PASS1/oavzee test_pos_iperf.py @jffh-iilb [+57.5s]: evaluation passed 
  PASS0/ toplevel @local [+62.7s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:57.542388) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import re
import tcfl.tc


@tcfl.tc.target("pos_capable", name = "client")
@tcfl.tc.target("pos_capable", name = "server")
@tcfl.tc.interconnect("ipv4_addr", name = "network")
class _test(tcfl.tc.tc_c):
    
    def deploy_00_maybe_flash(self, client, server, network):
        self.image_flash, upload, soft = client.images.flash_spec_parse()
        if self.image_flash:

            @self.threaded
            def _target_flash(target, images, upload, soft):
                target.report_info("flashing", dlevel = -1)
                target.images.flash(images, upload = upload, soft = soft)
                target.report_info("flashed", dlevel = -1)

            self.run_for_each_target_threaded(
                _target_flash, ( self.image_flash, upload, soft, ),
                targets = [ "client", "server" ])

    def deploy_10_power_on_and_boot_pos(self, client, server, network):
        network.power.cycle()

        @self.threaded
        def _boot_to_pos(target):
            target.pos.boot_to_pos()

        self.run_for_each_target_threaded(
            _boot_to_pos,
            targets = [ "client", "server" ])


    def eval_10(self, client, server, network):

        if False or self._phase_skip("deploy"):

            server.send("\x03\x03")
            server.shell.setup()

            client.send("\x03\x03")
            client.shell.setup()
        
            server.shell.setup()
            client.shell.setup()

        tcfl.tl.linux_if_configure(client, network)
        tcfl.tl.linux_if_configure(server, network, method = "dhcp")
        self.report_pass("network interfaces configured", dlevel = -1)


    def eval_20_client_ping_server(self, network, client, server):
        server_ipv4_addr = server.addr_get(network, "ipv4")
        client.shell.run(f"ping -c 10 {server_ipv4_addr}")
        self.report_pass("client -> server pings", dlevel = -1)


    def eval_25_server_ping_client(self, network, client, server):
        client_ipv4_addr = client.addr_get(network, "ipv4")
        server.shell.run(f"ping -c 10 {client_ipv4_addr}")
        self.report_pass("server -> client pings", dlevel = -1)


    def eval_30_iperf_server(self, network, client, server):
        server.shell.run("killall -9 iperf || true")	# kill left overs
        # Run the iperf server on the background
        # ------------------------------------------------------------
        # Server listening on TCP port 5001
        # TCP window size:  128 KByte (default)
        # ------------------------------------------------------------
        server.shell.run("iperf -s &")
        self.report_info("iperf server started", dlevel = -1)


    def eval_35_iperf_client(self, network, client, server):
        client.shell.run("killall -9 iperf || true")	# kill left overs

        # Run the iperf client, which prints
        server_ipv4_addr = server.addr_get(network, "ipv4")
        output = client.shell.run(
            f"iperf --format m -c {server_ipv4_addr}",
            output = True)
        self.report_info("iperf ran successfully", dlevel = -1)


        # Parse the output, which printed
        #
        ## ------------------------------------------------------------
        ## Client connecting to 192.30.0.20, TCP port 5001
        ## TCP window size: 16.0 KByte (default)
        ## ------------------------------------------------------------
        ## [  1] local 192.30.0.24 port 39586 connected with 192.30.0.20 port 5001 (icwnd/mss/irtt=14/1448/444)
        ## [ ID] Interval       Transfer     Bandwidth
        ## [  1] 0.00-10.01 sec  32502 MBytes  27245 Mbits/sec
        #
        # We use --format m so we report performance always in
        # megabits and transfer will be reported in MBytes
        #
        regex = re.compile(
            "-(?P<duration>[\.0-9]+) sec"
            "\s+(?P<size>[\.0-9]+) MBytes"
            "\s+(?P<bandwidth>[\.0-9]+) Mbits/sec")
        m = regex.search(output)
        if not m:
            raise tcfl.error_e(
                "can't parse iperf client output", { 'output': output })
        gd = m.groupdict()
        duration = float(gd['duration'])
        size = float(gd['size'])
        bandwidth = float(gd['bandwidth'])

        # Report the KPIs
        # FIXME: add vectors (fw version, HW type, etc) to
        # duration/size/bandwidth
        client.report_data("iperf", "duration (seconds)", duration)
        client.report_data("iperf", "size (Mbytes)", size)
        client.report_data("iperf", "bandwidth (mbits/s)", bandwidth)


    def teardown_30_iperf_server(self, server):
        server.shell.run("killall -9 iperf || true")	# kill left overs
        self.report_info("iperf server killed", dlevel = -1)
