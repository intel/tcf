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
# For each VENDOR/PRODUCT if a script exists in the PATH or
# /usr/share/tcf called usb-device-discover-VVVV-PPPP, it will be
# invoked as
#
##  usb-device-discover-VVVV-PPPP USBPATH SERIAL
##  usb-device-discover-VVVV-PPPP 25-4.3.1 32342dr4
#
# The outut of said script has to be a json dictionary containing keys
# and valus to include along the aforementioned vendor, product and
# serial keys.
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
import os
import subprocess
import sys
import time

def sysfs_read(fn):
    try:
        with open(fn) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def sysfs_read_in_tree(fn):
    """Read a sysfs file in current dir or maybe up in the tree.

    Only works for /sys/devices/, so we first make the ifle as
    absolute as we can with realpath

    """
    dirname, filename = os.path.split(os.path.realpath(fn))
    while dirname != "/sys":
        try:
            with open(os.path.join(dirname, filename)) as f:
                return f.read().strip()
        except FileNotFoundError:
            dirname = os.path.dirname(dirname) 	# try one dir up
    return None


d = {}
procs = {}
for entry in os.listdir("/sys/bus/usb/devices"):

    vendor = sysfs_read(f"/sys/bus/usb/devices/{entry}/idVendor")
    product = sysfs_read(f"/sys/bus/usb/devices/{entry}/idProduct")
    serial = sysfs_read(f"/sys/bus/usb/devices/{entry}/serial")
    if vendor == None or product == None:
        continue

    d[entry] = dict(
        product = product,
        vendor = vendor,
        bDeviceClass = sysfs_read(
            f"/sys/bus/usb/devices/{entry}/bDeviceClass"),

        vendor_name = sysfs_read(f"/sys/bus/usb/devices/{entry}/vendor"),
        product_name = sysfs_read(f"/sys/bus/usb/devices/{entry}/product"),
    )
    if serial:
        d[entry]['serial'] = serial
    d[entry]['label'] = sysfs_read_in_tree(f"/sys/bus/usb/devices/{entry}/label")
    # run hooks if any available -- just start'em in parallel, we'll
    # wait for them later
    env = dict(os.environ)
    env["PATH"] += f":{os.path.dirname(__file__)}"
    if serial == None:
        serial_cmdline = "n/a"
    else:
        serial_cmdline = serial
    cmdline = [ f"usb-device-discover-{vendor}-{product}",
                entry, serial_cmdline ]
    try:
        procs[entry] = subprocess.Popen(
            cmdline,
            stderr = subprocess.PIPE, stdout = subprocess.PIPE,
            env = env, text = True)
        print(f"INFO: {entry}: starting {cmdline}", file = sys.stderr)
    except FileNotFoundError as e:
        # that's ok, that means there is no usb-device-discover for
        # this kind of device, skip
        pass

# Wait for processes to finish
timeout = 60
ts0 = time.time()
while procs and time.time() - ts0 < timeout:
    for entry, p in list(procs.items()):
        if p.poll() == None:
            print(f"INFO: {entry}: still running", file = sys.stderr)
            continue		# still running, check next

        # done, collect info
        print(f"INFO: {entry}: done, collecting data", file = sys.stderr)
        product = d[entry]['product']
        vendor = d[entry]['vendor']
        d[entry][f"usb-device-discover-{vendor}-{product}/cmdline"] = \
            ' '.join(p.args)
        d[entry][f"usb-device-discover-{vendor}-{product}/stdout"] = \
            p.stdout.read()
        d[entry][f"usb-device-discover-{vendor}-{product}/stderr"] = \
            p.stderr.read()
        try:
            j = json.loads(d[entry][f"usb-device-discover-{vendor}-{product}/stdout"])
            if not isinstance(j, dict):
                d[entry][f"usb-device-discover-{vendor}-{product}/log"] = \
                    f"ERROR: bad format returned, expected dict, got {type(j)}"
            for k, v in j.items():
                d[entry][k] = v
        except json.decoder.JSONDecodeError as e:
            d[entry][f"usb-device-discover-{vendor}-{product}/log"] = \
                f"ERROR: bad JSON format returned: {e}"

        # wipe from the table, so we don't even check it anymore
        del procs[entry]
    time.sleep(1)


# if we are here and we timed out, kill any left over processes
for entry, p in list(procs.items()):
    p.kill()

# dump
with open(sys.argv[1], "w") as f:
    json.dump(d, f, indent = 4)
