#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.capture

class _stream_c(ttbl.capture.impl_c):

    def get(self, target, capturer):
        return { "data": 1 }

    def stop_and_get(self, target, capturer):
        return { "data": 1 }


class _snapshot_c(ttbl.capture.impl_c):
    def start(self, target, capturer):
        target.fsdb.set(f"interfaces.capture.{capturer}", True)

    def get(self, target, capturer):
        target.fsdb.set(f"interfaces.capture.{capturer}", None)
        return { "data": 1 }

    def stop_and_get(self, target, capturer):
        return { "data": 1 }



target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'skip_cleanup' : True,
    }
)

target.interface_add(
    "capture",
    ttbl.capture.interface(
        stream = _stream_c(True, "application/json"),
        snapshot = _snapshot_c(False, "application/json")
    )
)
