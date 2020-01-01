#! /usr/bin/python2
#
# Copyright (c) 2017-2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Add default QEMU Zephyr OS targets on default networks added by
# conf_06_default.

if ttbl.config.defaults_enabled:

    for letter in default_networks:	# conf_06_default.default_networks
        x, y, _vlan_id = nw_indexes(letter)
        nw_name = "nw" + letter
        # network has been created by conf_06_default
        index = index_start
        for bsp in target_qemu_zephyr_desc.keys():
            target = target_qemu_zephyr_add(
                "qz-%02d%s-%s" % (index, letter, bsp),
                bsp, nw_name = nw_name)
            target.add_to_interconnect(    	# Add target to the interconnect
                nw_name, dict(
                    mac_addr = "02:%02x:00:00:%02x:%02x" % (x, y, index),
                    ipv4_addr = '192.%d.%d.%d' % (x, y, index),
                    ipv4_prefix_len = 24,
                    ipv6_addr = 'fc00::%02x:%02x:%02x' % (x, y, index),
                    ipv6_prefix_len = 112)
            )
            index += 1

    index_start += len(target_qemu_zephyr_desc)	# conf_06_default.index_start

