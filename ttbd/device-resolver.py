#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import time

import ttbl
import ttbl.pci
import ttbl.usb

if len(sys.argv) <= 1:
    print(f"""
Usage: {sys.argv[0]} [DEVICESPEC,[DEVICESPEC,[...]]]

Resolve device specifications and list which devices they apply to
(using ttbl.device_resolver_c).

DEVICESPECs

- usb,deep_match,usb_depth=4,label=SLOT%203,renesas_controller=4,idVendor=0403,idProduct=601c,!bInterfaceClass,+y2prog_dest=bios
- usb,idVendor=06cb,idProduct=00fc,bInterfaceNumber=00
- usb,idVendor=06cb,idProduct=00fc,usb_depth=0
- usb,idProduct=3f41,usb_depth=2,!bInterfaceClass

eg:

 $ {sys.argv[0]} 'usb,deep_match,usb_depth=4,label=SLOT%203,renesas_controller=4,idVendor=0403,idProduct=601c,!bInterfaceClass,+y2prog_dest=bios'

eg:
""", file = sys.stderr)
device_specs = sys.argv[1:]

ttbl.test_target.state_path = os.path.join(
    os.path.expanduser("~"),
    ".cache",
    # don't mix with with the core library
    "ttbl.device-resolver")

import logging
logging.basicConfig(level = logging.DEBUG)

target = ttbl.test_target("unused")
target.acquirer = ttbl.symlink_acquirer_c(target)
for device_spec in device_specs:
    device_resolver = ttbl.device_resolver_c(
        target,
        device_spec,
        f"instrumentation.TEST.device_spec")
    ts0 = time.time()
    devices = device_resolver.devices_find_by_spec(
        only_one = "only_one" in os.environ)
    ts1 = time.time()
    print(f"{device_spec} [{ts1-ts0:.02f}s]")
    print("\n".join([ " - " + i for i in devices]))
