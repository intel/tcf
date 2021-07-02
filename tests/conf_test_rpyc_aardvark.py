#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import os

import commonl
import ttbl.power

port_base = commonl.tcp_port_assigner(1)

# Fugly: this makes the server take more time to start and triggers
# the timeout check
commonl.buildah_image_create(
    "ttbd", ttbl.power.daemon_podman_container_c.dockerfile,
    capture_output = False)

commonl.buildah_image_create(
    "aardvark_py", ttbl.power.rpyc_aardvark_c.dockerfile,
    capture_output = False)

usb_serial_number = os.environ.get("AARDVARK_USB_SERIAL_NUMBER", "NODEVICE")

target = ttbl.test_target("t0")
target.interface_add(
    "power",
    ttbl.power.interface(
        aa0 = ttbl.power.rpyc_aardvark_c(usb_serial_number, port_base),
    )
)
ttbl.config.target_add(target)
