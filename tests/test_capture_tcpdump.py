#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import socket
import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd'))),
    ],
    errors_ignore = [
        "Traceback",
        # we will trigger this
        "RuntimeError(",
        "RuntimeError: CONFIG BUG",
    ])

# FIXME: add TC that captures on whichever local netif is configured
# to the local machine to its MAC

@tcfl.tc.target(ttbd.url_spec + " and t0")
class clo(tcfl.tc.tc_c):
    capturer = "clo"
    time = 5
    r = None

    @tcfl.tc.subcase()
    def eval_00_list(self, target):
        r = target.capture.list()
        if self.capturer not in r:
            raise tcfl.tc.failed_e(
                f"tcpdump capturer {self.capturer} not in list",
                dict(r = r, level = 0))
        self.report_pass(f"{self.capturer} shows up in list")

    @tcfl.tc.subcase()
    def eval_10_start(self, target):
        r = target.capture.start(self.capturer)
        target.report_pass("tcpdump: starts ok", dict(r = r))


    @tcfl.tc.subcase()
    def eval_30_stop(self, target):
        time.sleep(self.time)
        r = target.capture.stop(self.capturer)
        target.report_pass(f"tcpdump: stops ok {r}")

    @tcfl.tc.subcase()
    def eval_40_get(self, target):
        # for later
        self.r = target.capture.get(self.capturer)
        target.report_pass(f"tcpdump: downloaded to {self.r}")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)


@tcfl.tc.target(ttbd.url_spec + " and t0")
class clo_parse(tcfl.tc.tc_c):
    """
    This needs tcpdump to be isntalled either suid or in a way that
    the runner of this testcase can execute it, since it requires to
    tap network devices

    Yah, don't run as root, please
    """
    def eval_60_capture(self, target):
        target.capture.start("clo")
        target.report_info("capturing")
        # generate some traffic on localhost
        tcp_port = commonl.tcp_port_assigner(1)
        with socket.socket() as client, socket.socket() as server:
            server.bind(( "127.0.0.1", tcp_port ))
            server.listen()
            client.connect(( "127.0.0.1", tcp_port ))
            connection, address = server.accept()
            client.sendall(b"good vibes")
            data = connection.recv(100)
            assert data == b"good vibes"
        target.report_info(f"sent/received {data} on TCP:{tcp_port} {address}")
        target.capture.stop("clo")
        target.report_info("done capturing")
        r = target.capture.get("clo")

        with open(r['default'], "rb") as f:
            data = f.read()
            # technically speaking we'd parse the packets and such,
            # but this will do for now
            if b"good vibes" not in data:
                raise tcfl.tc.failed_e(
                    f"didn't find string sent in packet capture {r['default']}",
                    dict(level = 0))
            target.report_pass("found string sent in packet capture")


@tcfl.tc.target(ttbd.url_spec + " and t0")
class cfail(tcfl.tc.tc_c):
    capturer = "c3fail"

    def eval(self, target):
        try:
            target.capture.start("c3fail")
        except tcfl.tc.exception as e:
            if 'CONFIG BUG' not in str(e):
                raise tcfl.tc.failed_e(
                    f"c3fail/start did not fail as expected")
        target.report_pass("c3fails as expected")
