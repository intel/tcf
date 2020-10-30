#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target(ttbd.url_spec)
class _test(tcfl.tc.tc_c):
    """
    Exercise basic tunnel calls

    Generate a list of tunnels, add them all, remove them all,
    verifying the listing reports all those added / removed.

    Then check add all, verify listing, remove all.
    """

    def eval(self, target):

        l = [
            ( "127.0.0.1", 'tcp', port )
            for port in range(22, 50)
        ]

        d = target.tunnel.list()
        if len(d) != 0:
            raise tcfl.tc.failed_e(
                "pre-check: expected no entries in dictionary", dict(d = d))
        target.report_pass("before adding/removing tunnels, none are listed")

        for ip_addr, protocol, port in l:
            p = target.tunnel.add(port, ip_addr, protocol)
            target.report_pass("tunnel to %s:%s:%d created to %s:%d"
                               % (protocol, ip_addr, port, target.rtb, p))
            d = target.tunnel.list()
            if len(d) != 1:
                raise tcfl.tc.failed_e(
                    "expected only one entry in dictionary", dict(d = d))
            # returns { p: { ip_addr: DEST, protocol: PROTOCOL, port:L PORT }}
            if p not in d:
                raise tcfl.tc.failed_e(
                    "expected port '%d' in dictionary" % p,
                    dict(d = d))
            data = d[p]
            if not 'ip_addr' in data or data['ip_addr'] != ip_addr:
                raise tcfl.tc.failed_e(
                    "expected ip_addr '%s' in dictionary" % ip_addr,
                    dict(d = d))
            if data.get('protocol', None) != protocol:
                raise tcfl.tc.failed_e(
                    "expected protocol '%s' in dictionary" % protocol,
                    dict(d = d))
            if data.get('port', None) != port:
                raise tcfl.tc.failed_e(
                    "expected port '%s' in dictionary" % port, dict(d = d))

            target.report_pass("listed expected items")
            target.tunnel.remove(port, ip_addr, protocol)
            target.report_pass("tunnel to %s:%s:%d removed"
                               % (protocol, ip_addr, port))

        d = target.tunnel.list()
        if len(d) != 0:
            raise tcfl.tc.failed_e(
                "post1-check: expected no entries in dictionary; got %d"
                % len(d), dict(d = d))
        target.report_pass("after adding/removing tunnels, none are listed")

        local_ports = set()
        count = 0
        for ip_addr, protocol, port in l:
            p = target.tunnel.add(port, ip_addr, protocol)
            target.report_pass("tunnel to %s:%s:%d created to %s:%d"
                               % (protocol, ip_addr, port, target.rtb, p))
            local_ports.add(str(p))
            count += 1
            d = target.tunnel.list()
            if len(d) != count:
                raise tcfl.tc.blocked_e(
                    "added %d tunnels, list reports %d (should be same)" % (
                        count, len(d)),
                    dict(d = d))

        d = target.tunnel.list()
        reported_local_ports = set([ str(key) for key in d.keys()])
        if reported_local_ports != local_ports:
            raise tcfl.tc.failed_e(
                "after adding %d local ports, expected them to be listed; "
                " got %d" % (len(local_ports), len(reported_local_ports)),
                dict(
                    reported_local_ports = reported_local_ports,
                    local_ports = local_ports,
                    d = d)
            )
        target.report_pass("after adding three tunnels, they are listed")

        for ip_addr, protocol, port in l:
            p = target.tunnel.remove(port, ip_addr, protocol)
            target.report_pass("tunnel to %s:%s:%d removed"
                               % (protocol, ip_addr, port))

        target.report_pass("after adding/removing tunnels, none are listed")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
