#! /usr/bin/python3
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
        nw_pos_add(letter)

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
                ipv6_addr = 'fd:%02x:%02x::%02x' % (x, y, v))

    index_start = 5

#
# Create the local target
#
# The local target allows listing USB devices with:
#
## $ tcf capture AKA/local usb_devices
## usb_devices: taking snapshot
## usb_devices: downloading capture
## usb_devices: downloaded stream log -> local.usb_devices.log.log
## usb_devices: downloaded stream default -> local.usb_devices.default.json
#
target_local = ttbl.test_target('local')
ttbl.config.target_add(
    target_local,
    tags = {
        "versions.server": commonl.version_get(ttbl, "ttbd"),
        "skip_cleanup": True,
        "disabled": "meant only for describing the server",
    }
)
target_local.interface_add(
    "capture",
    ttbl.capture.interface(
        usb_devices = capture_usb_devices,
    )
)
