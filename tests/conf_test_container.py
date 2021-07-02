#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

# Fugly: this makes the server take more time to start and triggers
# the timeout check
commonl.buildah_image_create(
    "ttbd", ttbl.power.daemon_podman_container_c.dockerfile,
    capture_output = False)

target = ttbl.test_target("t0")
target.interface_add(
    "power",
    ttbl.power.interface(
        c0 = ttbl.power.daemon_podman_container_c(
            "example0",
            cmdline = [
                "ttbd",
                "/bin/sh", "-c", "while true; do echo 'alive at ' $(date); sleep 2; done"
            ],
        ),
        c1 = ttbl.power.daemon_podman_container_c(
            "example1",
            cmdline = [
                "ttbd",
                "/bin/sh", "-c", "while true; do echo 'alive at ' $(date); sleep 2; done"
            ],
        ),
    )
)
ttbl.config.target_add(target)
