#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Add default targets on two sample networks; provide default_networks
# and index_start for other default config files.
import ttbl

if ttbl.config.defaults_enabled:

    for letter in ttbl.config.default_networks:
        x, y, _vlan_id = nw_indexes(letter)
        nw_name = "nw" + letter

        # Add the network target
        nw_pos_add(letter, [ vlan_pci() ])

        # Add QEMU UEFI POS capable targets with addresses
        v = 1
        for v in range(
                ttbl.config.default_qemu_start,
                ttbl.config.default_qemu_start
                + ttbl.config.default_qemu_count):
            target_name = "qu-%02d" % v + letter
            target = target_qemu_pos_add(
                target_name,
                nw_name,
                mac_addr = "02:%02x:00:00:%02x:%02x" % (x, y, v),
                ipv4_addr = '192.%d.%d.%d' % (x, y, v),
                ipv6_addr = 'fc00::%02x:%02x:%02x' % (x, y, v))

    index_start = 5

ttbl.config.target_add(
    ttbl.test_target('local'),
    tags = {
        "versions.server": commonl.version_get(ttbl, "ttbd"),
        "skip_cleanup": True,
        "disabled": "meant only for describing the server",
    }
)
