#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache 2.0
"""
Miscellaneous helpers for USB devices
-------------------------------------
"""

# ttbl needs to be able to import this

def synth_fields_maker(sys_path: str, expensive: bool) -> dict:
    """
    Scan USB devices and return fields

    This looks for files called usb-device-discover-VVVV-PPPP in
    /usr/share/tcf [shared with
    /usr/share/tcf/usb-devices-capture.py], imports them as a python
    module and runs a function inside them called *run* passing the
    following arguments:

    - str: USB path (eg: 10-1.3.4) in /sys/bus/usb/devices

    - str: USB Serial Number

    - bool: expensive: *True* if extraction can be expensive (can take
      up to 5s), *False* otherwise (has to stay well under one
      second--return empty dict)

    """
    # Note this is called from a bunch of deep contexts in
    # ttbl.device_resolver_c, so we import stuff only when we need it
    # to avoid import hells

    # Note this ONLY works for top level USB device nodes (eg: would
    # work for /sys/bus/devices/1-2 but not for
    # /sys/bus/devices/1-2:1.1)
    if not sys_path.startswith('/sys/bus/usb/devices'):
        return {}

    # these always exist in USB, they have to exist
    import ttbl		# might be called from an environment that lacks this
    vendor = ttbl._sysfs_read(sys_path + "/idVendor")
    product = ttbl._sysfs_read(sys_path + "/idProduct")
    if not vendor or not product:
        return {}

    # Try to load as cript for gathering more info -- we share this
    # with usb-devices-capture.py
    try:
        import importlib
        import importlib.machinery
        import logging

        import commonl
        import ttbl._install

        # use the helper locator so it works from the source tree or
        # installed
        try:
            usb_device_discover_script = commonl.ttbd_locate_helper(
                f"usb-device-discover-{vendor}-{product}",
                ttbl._install.share_path,
                log = logging, relsrcpath = ".")
        except RuntimeError as e:
            if "Can't find" in str(e):
                # fallback to default
                usb_device_discover_script = \
                    f"/usr/share/tcf/usb-device-discover-{vendor}-{product}"

        import_spec = importlib.util.spec_from_loader(
            f"usb_device_discover_{vendor}_{product}",
            # Can't use just importlib.util.spec_from_file_location() because it
            # wants the file to end in .py, so SourceFileLoader() works that around
            importlib.machinery.SourceFileLoader(
                f"usb_device_discover_{vendor}_{product}",
                usb_device_discover_script
            )
        )
        if import_spec == None:
            raise ImportError(
                f"usb_device_discover_{vendor}_{product}:"
                " can't load module: import spec is None")
        module = importlib.util.module_from_spec(import_spec)
        import_spec.loader.exec_module(module)
    except FileNotFoundError:
        # if there is not a valid parser, then return no data but
        # allow it to be cached; this means we have no tool for parsing
        # more info out of this device
        return {}

    # this parses the output of Y2ProgCli discovery and returns them
    # as a dictionary keyed { y2prog_FIELD: VALUE }
    usb_serial_number = ttbl._sysfs_read(sys_path + "/serial")
    import os
    return module.run(os.path.dirname(sys_path), usb_serial_number,
                      expensive = expensive)
