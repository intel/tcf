#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache 2.0
"""
Miscellaneous helpers for PCI devices
-------------------------------------
"""

# ttbl needs to be able to import this


def synth_fields_maker_pexusb3s44v(syspath: str, expensive: bool) -> dict:
    """
    Find extra information for a USB3 QUAD Host Controller PEXUSB3S44V

    This is to be used with :class:`ttbl.device_resolver_c`:

    >>> ttbl.device_resolver_c.synth_fields_maker_register(ttbl.pci.synth_fields_maker_pexusb3s44v)

    Mainly tells us which controller number in a QUAD card this
    controller is so it can be matched with device resolver
    specification, eg:

    >>> device_spec = "...,renesas_controller=4,..."

    - https://www.startech.com/en-us/cards-adapters/pexusb3s44v
    - https://www.amazon.com/Port-PCI-Express-USB-Card/dp/B00HJZEA2S/

    :param str syspath: path to */sys/bus/pci/devices* sysfs entry
      (eg: */sys/bus/pci/devices/0000:3d:00.0*)

    :returs dict: dictionary keyed by string:

      - *renesas_controller*: controller number (1 farthest from PCI
        connector to 4 closest to PCI connector)

    """
    # Note this is called from a bunch of deep contexts in
    # ttbl.device_resolver_c, so we import stuff only when we need it
    # to avoid import hells
    import os

    import ttbl

    d = {}

    # translate the BUS locatio to the physical path location, so we
    # can see the tree
    #
    # /sys/bus/pci/devices/0000:3d:00.0
    # -> /sys/devices/pci0000:3a/0000:3a:00.0/0000:3b:00.0/0000:3c:01.0/0000:3d:00.0
    device_syspath = os.path.realpath(syspath)
    vendor = ttbl._sysfs_read(device_syspath + "/vendor")
    device = ttbl._sysfs_read(device_syspath + "/device")
    if vendor != "0x1912" or device != "0x0015":
        return d
    device_name = os.path.basename(device_syspath)

    # 12d8:8608 are PCI bridge controllers
    parent_syspath = os.path.dirname(device_syspath)
    vendor = ttbl._sysfs_read(parent_syspath + "/vendor")
    device = ttbl._sysfs_read(parent_syspath + "/device")
    if vendor != "0x12d8":
        return d
    if  device != "0x8608" and device != "0x2608":
        return d
    parent_name = os.path.basename(parent_syspath)

    grandparent_syspath = os.path.dirname(parent_syspath)
    vendor = ttbl._sysfs_read(grandparent_syspath + "/vendor")
    device = ttbl._sysfs_read(grandparent_syspath + "/device")
    if vendor != "0x12d8":
        return d
    if device != "0x8608" and device != "0x2608":
        return d
    grandparent_name = os.path.basename(grandparent_syspath)

    # So this is a Renensas controller because it's a 1912:0015 whose
    # parent and grandparent are 12d8:8606, so they look like
    #
    # SOMETHING:3d:00.0   -> the controller
    # SOMETHING:3c:0N.0   -> parent
    # SOMETHING:3b:00.0   -> grandparent

    # divide in PCIBUS:PCIDEVICE:PCIFUNCTION so we can compare
    device_l = device_name.split(":")
    parent_l = parent_name.split(":")
    grandparent_l = grandparent_name.split(":")

    if device_l[0] != parent_l[0] or parent_l[0] != grandparent_l[0]:
        # devices need to be in the same PCI BUS
        return d

    # make'em numeric
    device_fn = int(device_l[1], 16)
    parent_fn = int(parent_l[1], 16)
    grandparent_fn = int(grandparent_l[1], 16)

    # the grandparent must be parent - 1
    if grandparent_fn != parent_fn - 1:
        return d

    # parent - controller => controller #
    # 3d - 3c -> controller 1
    # the device must be from 1 to 4 devices more
    device_delta = device_fn - parent_fn
    if device_delta < 1 or device_delta > 4:
        # if the controller is waaay far away, we don't know what this
        # thing is; we only know the controllers listed above
        return d

    d["renesas_controller"] = str(device_delta)
    return d
