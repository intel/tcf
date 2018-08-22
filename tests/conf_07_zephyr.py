#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.tt_qemu

#
# This is a copy of ../ttbd/zephyr/conf_07_zephyr.py, but without
# Riscv32, as QEMu fails to start some times.
#

bsps = [ 'x86', 'arm', 'nios2' ]

for nw in [ 'a', 'b', 'c' ]:
    # nwa is 192.168.10.*, b is 192.168.11.*, etc..
    nw_idx = 10 + ord(nw) - ord('a')
    # Now create 5 targets of each architecture, numbering them
    # sequentially so their IP address matches and does not conflict
    # with the linux targets in the same network
    base = 30
    for bsp in bsps:
        for count in range(base, base + 5):
            ttbl.config.target_add(
                tt_qemu_zephyr("qz%02d%s-%s" % (count, nw, bsp), [ bsp ]),
                target_type = "qemu-%s" % bsp,
                tags = {
                    "interconnects": {
                        "nw%s" % nw: dict(
                            ipv4_addr = "192.168.%d.%d" % (nw_idx, count),
                            ic_index = count,
                            mac_addr = "02:%02x:00:00:00:%02x" % (
                                nw_idx, count),
                        ),
                    }
                }
            )
        base = count + 1
