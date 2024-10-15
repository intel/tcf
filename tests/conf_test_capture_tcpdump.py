#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import pyroute2
import socket

import ttbl.capture


ic = ttbl.test_target("i0")
ttbl.config.interconnect_add(ic)
ic = ttbl.test_target("t0-nw")
ttbl.config.interconnect_add(ic)

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.add_to_interconnect("i0", { 'mac_addr': "i0s mac addr" } )
target.add_to_interconnect("t0-nw", { 'mac_addr': "t0s mac addr" } )

local_ifaces = pyroute2.IPDB()
this_host = socket.getfqdn()
this_host_ip_addr = socket.gethostbyname(this_host)
netif = None
for _, data in local_ifaces.interfaces.items():
    for ipaddr, netmask in data['ipaddr']:
        if ipaddr == this_host_ip_addr:
            netif = data['ifname']
            break
    if netif != None:
        break
else:
    raise ValueError("can't find this hosts' interface")


target.interface_add(
    "capture", ttbl.capture.interface(
        c0 = ttbl.capture.tcpdump_c(netif, macaddr = "fake:mac:addr"),
        c1 = ttbl.capture.tcpdump_c(netif, macaddr = "%(interconnects.%(id)s-nw.mac_addr)s"),
        c2 = ttbl.capture.tcpdump_c(netif, ic_name = "i0"),
        c3fail = ttbl.capture.tcpdump_c(netif),	# shall fail
        c4 = ttbl.capture.tcpdump_c(netif, ic_name = "interconnects.%(id)s-nw"),
        # capture all -- this is the only "config" we can get to
        # actually do any real capture in any system without resorting
        # to a lot of setup--WARNING! needs privileges! WARNING might
        # capture sensitive data
        clo = ttbl.capture.tcpdump_c(
            "lo", macaddr = "",
            # this needs extra magic since we are sending very little
            # data for testing, so the kernel caches won't flush that often
            extra_tcpdump_args = [ "--immediate-mode" ],
        )
    )
)
