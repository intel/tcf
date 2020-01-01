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

    # this is here so other config files can refer to it
    default_networks = [ 'a', 'b' ]

    for letter in default_networks:
        x, y, _vlan_id = nw_indexes(letter)
        nw_name = "nw" + letter

        # Add the network target
        nw_pos_add(letter, [ vlan_pci() ])

        # Add QEMU UEFI POS capable targets with addresses
        v = 1
        for v in range(2, 4):
            target_name = "qu-%02d" % v + letter
            target = target_qemu_pos_add(
                target_name,
                nw_name,
                mac_addr = "02:%02x:00:00:%02x:%02x" % (x, y, v),
                ipv4_addr = '192.%d.%d.%d' % (x, y, v),
                ipv6_addr = 'fc00::%02x:%02x:%02x' % (x, y, v))
            target.interface_add("capture", ttbl.capture.interface(
                # capture screenshots from VNC, return a PNG
                vnc0 = capture_screenshot_vnc,
                screen = "vnc0",
            ))

    index_start = 5
