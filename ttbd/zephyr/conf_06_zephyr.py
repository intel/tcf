#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Configuration file for ttbd (place in ~/.ttbd/) or run ttbd with
# `--config-file PATH/TO/THISFILE`
#
import ttbl.tt_qemu

def nw_default_targets_zephyr_add(letter, bsps = [ 'x86', 'arm', 'nios2',
                                                   'riscv32', 'xtensa' ]):
    """
    Add the default Zephyr targets to a configuration

    This adds a configuration which consists of a network and five
    QEMU Linux and five QEMU Zephyr (times available BSPSs)
    """
    assert isinstance(letter, basestring)
    assert len(letter) == 1

    nw_idx = ord(letter)
    nw_name = "nw" + letter

    # Add five QEMU Zephyr targets on the network, one of each architecture
    #
    # Numbering them sequentially so their IP address matches and does
    # not conflict with the linux targets in the same network
    base = 30
    for bsp in bsps:
        for count in range(base, base + 2):
            ttbl.config.target_add(
                tt_qemu_zephyr("qz%02d%s-%s" % (count, letter, bsp), [ bsp ]),
                target_type = "qemu-zephyr-%s" % bsp,
                tags = {
                    "interconnects": {
                        nw_name: dict(
                            ipv4_addr = "192.168.%d.%d" % (nw_idx, count),
                            ipv4_prefix_len = 24,
                            ipv6_addr = "fc00::%02x:%02x" % (nw_idx, count),
                            ipv6_prefix_len = 112,
                            ic_index = count,
                            mac_addr = "02:%02x:00:00:00:%02x" \
                                % (nw_idx, count),
                        ),
                    }
                }
            )
        base = count + 1


#
# Add QEMUs targets
#
#
# These are for a default example, you can add as many as you care and
# your server can execute concurrently.

if ttbl.config.defaults_enabled:

    # Creates 10 QEMU targets of each BSP interconnected to networks nwa,
    # and nwb  (defined in conf_06_defaults)

    for letter in [ 'a', 'b' ]:
        nw_default_targets_zephyr_add(letter)
