#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import commonl

import ttbl.power

port_base = commonl.tcp_port_assigner(1)

commonl.buildah_image_create(
    "ttbd", ttbl.power.daemon_podman_container_c.dockerfile,
    capture_output = False)

target = ttbl.test_target("t0")
target.interface_add(
    "power",
    ttbl.power.interface(
        c0 = ttbl.power.rpyc_c(
            "ttbd",
            port_base,
            run_files = {
                "runthis.sh": """
#! /bin/sh -xe
ls -l /etc/ttbd
ls -l /etc/ttbd/run
echo "ein belegtes Brot mit Schinken" > /tmp/runthisexecuted
"""
            },
        ),
    )
)
ttbl.config.target_add(target)
