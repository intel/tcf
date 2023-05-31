#! /usr/bin/python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Snapshot capture to list all USB devices connected to the
# server. This is mainly useful to add to the local target that
# represents the server, to be able to list which USB device are
# available and do automated serial number scanning.
#
# Args: OUTPUTFILE
#
# It writes to the OUTPUTFILE a json formated file with a list of
# devices in dictionary format
#
## {
##   PATH: { vendor: VENDORID, product: PRODUCTID, serial: SERIALNUMBER },
##   PATH: { vendor: VENDORID, product: PRODUCTID, serial: SERIALNUMBER },
##   PATH: { vendor: VENDORID, product: PRODUCTID, serial: SERIALNUMBER },
##   ...
## }
#
#
# To configure:
#
## 
## usb_device_capture_py = commonl.ttbd_locate_helper(
##     "usb-devices-capture.py",
##     ttbl._install.share_path,
##     log = logging)
## 
## capture_usb_devices = ttbl.capture.generic_snapshot(
##     "%(id)s USB devices",
##     usb_device_capture_py + " %(output_file_name)s",
##     mimetype = "application/json", extension = ".json",
## )
## 
## 
## target = ...
## target.interface_add(
##     "capture",
##     ttbl.capture.interface(
##         usb_devices = capture_usb_devices,
##     )
## )
##
##
## ttbl.config.target_add(target)

import json
import logging
import os
import sys

def sysfs_read(fn):
    try:
        with open(fn) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

d = {}
for entry in os.listdir("/sys/bus/usb/devices"):

    vendor = sysfs_read(f"/sys/bus/usb/devices/{entry}/idVendor")
    product = sysfs_read(f"/sys/bus/usb/devices/{entry}/idProduct")
    serial = sysfs_read(f"/sys/bus/usb/devices/{entry}/serial")
    if vendor == None or product == None:
        continue

    d[entry] = dict(product = product, vendor = vendor)
    if serial:
        d[entry]['serial'] = serial

with open(sys.argv[1], "w") as f:
    json.dump(d, f, indent = 4)
