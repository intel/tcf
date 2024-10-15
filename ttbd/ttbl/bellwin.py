#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Drivers for Bellwin hardware
----------------------------

"""

import contextlib
import usb.core

import ttbl.power




class usb_power_splitter_pc(ttbl.power.impl_c):
    """
    USB Power Splitter smart PDU control

    http://www.digipdu.com/product/html/?202.html
    """
    class notfound_e(ValueError):
        pass

    # This code is SINGLE THREADED, so we are going to share one
    # backend to cut in the number of open file handles
    backend = None

    def __init__(self, usb_serial_number, port, **kwargs):
        assert isinstance(port, int) or port < 1 or port > 5, \
            "ports is an integer 1-5; got %s" % port
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.port = port - 1	# device wants them 0 indexed
        self.usb_serial_number = usb_serial_number
        self.retries = 10
        self.soft_retries = 4
        self.upid_set(
            "Bellwin USB Power Splitter %s, port #%d" % (
                self.usb_serial_number, port),
            serial_number = self.usb_serial_number, port = port)


    USB_VENDOR = 0x04d8 	
    USB_PRODUCT = 0xfedc 	

    CMD_READFWOUTPUT = 8
    CMD_WRITEFWOUTPUTSINGLE = 11
    CMD_RESETFWDEVICE = 255

    OUTLET_OFF = 0
    OUTLET_ON = 1

    def _find_dev(self, target):
        try:
            usb_dev = usb.core.find(
                idVendor = self.USB_VENDOR,
                #backend = type(self).backend,
                custom_match = lambda d: ttbl.usb_serial_number(d) == self.usb_serial_number
            )
        except Exception as e:
            target.log.info("[retryable] Can't find USB devices: %s" % e)
            usb_dev = None
            # When this happens, kill the backend and have a new one
            # allocated; there are cases where the USB device has been
            # reassigned for whichever reason and has to be fully
            # re-scaned and re-initialized.
            if type(self).backend:
                del type(self).backend
                type(self).backend = None
        if usb_dev == None:
            raise self.notfound_e("Cannot find USB serial '%s'"
                                  % self.usb_serial_number)
        if type(self).backend == None:
            type(self).backend = usb_dev._ctx.backend
        return usb_dev

    @contextlib.contextmanager
    def _usb_dev_setup(self, target):
        usb_dev = self._find_dev(target)
        driver_active = False
        try:
            driver_active = usb_dev.is_kernel_driver_active(0)
            if driver_active:
                usb_dev.detach_kernel_driver(0)
            usb_dev.set_configuration(1)
            usb.util.claim_interface(usb_dev, 0)
            try:
                yield usb_dev
            finally:
                usb.util.release_interface(usb_dev, 0)
        finally:
            if driver_active:
                usb_dev.attach_kernel_driver(0)
            usb_dev._ctx.managed_close()
            del usb_dev

    def _outlet_state_set(self, target, state):
        with self._usb_dev_setup(target) as usb_dev:
            # Command block is 64 bytes:
            # byte 0: CMD_
            # byte 5: port (indexed at 0)
            # byte 6: 0 - off, 1 - on
            s = bytearray(64)
            s[0] = self.CMD_WRITEFWOUTPUTSINGLE
            s[5] = self.port
            s[6] = self.OUTLET_ON if state else self.OUTLET_OFF
            # send to endpoint 1 (interrupt endpoint)
            usb_dev.write(0x01, s)

    def _reset(self, target):
        with self._usb_dev_setup(target) as usb_dev:
            # Command block is 64 bytes:
            # byte 0: CMD_
            # byte 5: port (indexed at 0)
            # byte 6: 0 - off, 1 - on
            s = bytearray(64)
            s[0] = self.CMD_RESETFWDEVICE
            # send to endpoint 1 (interrupt endpoint)
            usb_dev.write(0x01, s)

    def _cmd(self, target, cmd):
        with self._usb_dev_setup(target) as usb_dev:
            # Command block is 64 bytes:
            # byte 0: CMD_
            # byte 5: port (indexed at 0)
            # byte 6: 0 - off, 1 - on
            s = bytearray(64)
            s[0] = cmd
            # send to endpoint 1 (interrupt endpoint)
            usb_dev.write(0x01, s)


    def _get(self, target):
        with self._usb_dev_setup(target) as usb_dev:
            s = usb_dev.read(0x81, 64)
            return s


    def _outlet_state_get(self, target):
        with self._usb_dev_setup(target) as usb_dev:
            # Command block is 64 bytes:
            # byte 0: CMD_
            # byte 5: port (indexed at 0)
            # byte 6: 0 - off, 1 - on
            s = bytearray(64)
            s[0] = self.CMD_READFWOUTPUT
            # send to endpoint 1 (interrupt endpoint)
            usb_dev.write(1, s)
            s = usb_dev.read(0x81, 64)
            return s[5]


    # ttbl.power.imple_c Interface

    def on(self, target, _component):
        self._outlet_state_set(target, True)

    def off(self, target, _component):
        self._outlet_state_set(target, False)

    def get(self, target, _component):
        try:
            s = self._outlet_state_get(target)
            # bit N is the state for port N
            return bool(s & 1 << self.port)
        except self.notfound_e:
            # If it is not connected, we can't tell if it is on or
            # off, so we just report n/a
            return None

