#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import os
import time

import usb.core
import usb.util

import commonl
import ttbl
import ttbl.things
import ttbl.power

# FIXME: ename to _pc
# FIXME: move this file to ykush.py, since it provides other
#        components, not just a power controller
class ykush(ttbl.power.impl_c, ttbl.things.impl_c):

    class notfound_e(ValueError):
        pass

    # This code is SINGLE THREADED, so we are going to share one
    # backend to cut in the number of open file handles
    backend = None

    def __init__(self, ykush_serial, port, **kwargs):
        """
        A power control implementation using an YKUSH switchable hub
        https://www.yepkit.com/products/ykush

        This is mainly devices that are USB powered and the ykush hub
        is used to control the power to the ports.

        Note this devices appears as a child connected to the YKUSH
        hub, with vendor/device IDs 0x04d8:f2f7 (Microchip Technology)

        You can find the right one with `lsusb.py -ciu`::

          usb1             1d6b:0002 09  2.00  480MBit/s 0mA 1IF  (Linux 4.3.3-300.fc23.x86_64 xhci-hcd xHCI Host Controller 0000:00:14.0) hub
           1-2             2001:f103 09  2.00  480MBit/s 0mA 1IF  (D-Link Corp. DUB-H7 7-port USB 2.0 hub) hub
            1-2.5          0424:2514 09  2.00  480MBit/s 2mA 1IF  (Standard Microsystems Corp. USB 2.0 Hub) hub
             1-2.5.4       04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK20345)
              1-2.5.4:1.0   (IF) 03:00:00 2EPs (Human Interface Device:No Subclass:None)

        Note the *Yepkit Ltd, YK20345*; *YK20345* is the serial number.

        To avoid permission issues:

        - choose a Unix group that the daemon will be running under

        - add a UDEV rule to ``/etc/udev/rules.d/90-tcf.rules`` (or
          other name)::

            # YKUSH power switch hubs
            SUBSYSTEM=="usb", ATTR{idVendor}=="04d8", ATTR{idProduct}=="f2f7", \
              GROUP="GROUPNAME", MODE = "660"

        - restart UDEV, replug your hubs::

            $ sudo udevadm control --reload-rules

        :param str ykush_serial: Serial number of the ykush's control
          device.

        :param int port: Port number in the hub (one-based)

        Other parameters as to :class:ttbl.power.impl_c.

        .. warning: it is *strongly* recommended to also create targets with
                    with :func:`ykush_targets_add` to manage the hub
                    itself and that it is power controlled so it can
                    be automatically recovered when it fails (that it
                    happens). Look at :meth:`_try_resolving`.
        """
        if not isinstance(port, int) or port < 1 or port > 3:
            raise ValueError("ykush ports are 1, 2 and 3, gave %s" % port)
        ttbl.power.impl_c.__init__(self, **kwargs)
        ttbl.things.impl_c.__init__(self)
        self.port = port
        self.ykush_serial = ykush_serial
        self.retries = 10
        self.soft_retries = 4
        self.upid_set("Yepkit YKUSH power control hub %s, port #%d" % (
            self.ykush_serial, port),
                      serial_number = self.ykush_serial, port = port)

    def _find_dev(self, target):
        try:
            ykush_dev = usb.core.find(
                idVendor = 0x04d8,
                backend = type(self).backend,
                custom_match = lambda d: ttbl.usb_serial_number(d) == self.ykush_serial,
            )
        except Exception as e:
            target.log.info("[retryable] Can't find USB devices: %s" % e)
            ykush_dev = None
            # When this happens, kill the backend and have a new one
            # allocated; there are cases where the USB device has been
            # reassigned for whichever reason and has to be fully
            # re-scaned and re-initialized.
            if type(self).backend:
                del type(self).backend
                type(self).backend = None
        if ykush_dev == None:
            raise self.notfound_e("Cannot find YKUSH serial '%s'"
                                  % self.ykush_serial)
        if type(self).backend == None:
            type(self).backend = ykush_dev._ctx.backend
        return ykush_dev

    def _command_send(self, target, cmd):
        ykush_dev = self._find_dev(target)
        driver_active = False
        try:
            driver_active = ykush_dev.is_kernel_driver_active(0)
            if driver_active:
                ykush_dev.detach_kernel_driver(0)
            ykush_dev.set_configuration(1)
            usb.util.claim_interface(ykush_dev, 0)
            try:
                # Well, if I don't do this, then the device gets all
                # gaga and doesn't reply -- saw this on the YKUSH code.
                ykush_dev.reset()
                # Command block is s64 bytes, first byte with the
                # command sent twice.
                s = bytearray([cmd, cmd]) + bytearray(62)
                ykush_dev.write(0x01, s)
                target.log.log(8, "ykush command sent %s[%d] / 0x%02x"
                               % (self.ykush_serial, self.port, cmd))
                r = ykush_dev.read(0x81, 64)
                target.log.log(8, "ykush command %s[%d] / 0x%02x = 0x%02x %02x"
                               % (self.ykush_serial, self.port, cmd,
                                  r[0], r[1]))
                ykush_dev.reset()
                # The response buffer: first byte is 0x1 if it worked
                # ok, r[1] is the status, which varies by command.
                return (r[0], r[1])
            finally:
                usb.util.release_interface(ykush_dev, 0)
        finally:
            if driver_active:
                ykush_dev.attach_kernel_driver(0)
            ykush_dev._ctx.managed_close()
            del ykush_dev

    def _try_resolving(self, target):
        """
        The driver has tried to open the device by its serial
        number but it can't find it, so after a couple retries, it
        comes here to try to resolve

        If the user has created targets to manage the YKUSH hub (as
        he should), then we will try to power cycle the--as sometimes
        they just pass out (maybe riding a recovery in process
        happening in another process).
        """
        ykush_target_name = self.ykush_serial
        ykush_target = ttbl.test_target.get(ykush_target_name)
        if not ykush_target:
            target.log.error("can't find a target named %s to try "
                             "to power cycle missing %s hub"
                             % (ykush_target_name, self.ykush_serial))
            return

        # is there a recovery in process? ride it -- in case of
        # timeout, try our own too
        recovery_in_process = ykush_target.fsdb.get("recovery-in-process")
        if recovery_in_process:
            t0 = time.time()
            timeout = 11
            while True:
                recovery_in_process = ykush_target.fsdb.get(
                    "recovery-in-process")
                if not recovery_in_process:
                    target.log.info("ykush %s: waited for recovery in progress"
                                    % ykush_target_name)
                    return
                t = time.time()
                if t - t0 > timeout:
                    # timedout doing the recovery? the heck?
                    target.log.info("ykush %s: timed out %fs waiting for "
                                    "recovery in progress"
                                    % (ykush_target_name, timeout))
                    ykush_target.fsdb.set("recovery-in-process", None)
                    break
                target.log.info("ykush %s: waiting for recovery in process"
                                % ykush_target_name)
                time.sleep(0.5)

        # No recovery in process; acquire the target and if powered
        # off, power cycle it. Powered off test includes looking for
        # the USB serial number in the system, so it will triple
        # check.
        #
        # FIXME: only do this if the target has proper power control?
        owner = target.owner_get()
        if owner == None:
            owner = "local-recovery"
        try:
            ykush_target.fsdb.set("recovery-in-process", owner)
            target.log.error("ykush %s: acquiring as %s to power cycle"
                             % (ykush_target_name, owner))
            # Try a few times to acquire, in case it is busy
            t0 = time.time()
            timeout = 10
            while True:
                try:
                    ykush_target.acquire(owner, True)
                    break
                except ttbl.test_target_busy_e as e:
                    t = time.time()
                    if t - t0 > timeout:
                        target.log.error(
                            "ykush %s: timed out %fs trying to acquire"
                            % (ykush_target_name, timeout))
                        raise e
                    time.sleep(0.5)
            powered = ykush_target.power_get()
            # only power cycle if not powered; if powered, it means is
            # either working ok or someone was able to recover it
            # right before us. If we power-cycle again we will mess it
            # up for someone else.
            if powered:
                target.log.info("ykush %s: power is %s, not power cycling"
                                % (ykush_target_name, powered))
            else:
                target.log.info("ykush %s: power is %s, power cycling"
                                % (ykush_target_name, powered))
                ykush_target.power_cycle(owner)
        finally:
            # If we acquired it, we'll be able to release it
            # We do that because we want to make double sure we
            # release this -- if the target has skip cleanup and we
            # dump ourselves into not releasing, then other processes
            # can't attempt recovery.
            target.log.info("ykush %s: releasing" % ykush_target_name)
            ykush_target.release_v1(owner)
            # FIXME: replace with lockfile?
            ykush_target.fsdb.set("recovery-in-process", None)

    def _command(self, target, cmd):
        # FIXME: add a manager lock to make sure only accessing one
        # ykush at the time
        # Access the ykush under this lock, to make sure nobody
        # else (at least on this server) is accessing it at the
        # same time. There is a single instance of each per
        # thread.
        count = 0
        had_to_retry = False
        while count < self.retries:
            count += 1
            try:
                r = self._command_send(target, cmd)
                if had_to_retry:
                    target.log.info("%s[%d]: retrying succesful",
                                    self.ykush_serial, self.port)
                return r
            except self.notfound_e as e:
                if count >= self.retries:
                    raise
                if count % self.soft_retries == 0:
                    target.log.info("%s[%d]: can't find; "
                                    "power cycling it and retrying",
                                    self.ykush_serial, self.port)
                    self._try_resolving(target)
                else:
                    target.log.info("%s[%d]: can't find; retrying",
                                    self.ykush_serial, self.port)
                time.sleep(0.25)
                had_to_retry = True
            except usb.core.USBError as e:
                if count >= self.retries:
                    target.log.error(
                        "%s[%d]: USB Error (%s), retried too much",
                        self.ykush_serial, self.port, e)
                    raise
                target.log.info("%s[%d]: USB Error (%s), retrying",
                                self.ykush_serial, self.port, e)
                time.sleep(0.25)
                had_to_retry = True

    def on(self, target, _component):
        cmd = 0x10 | self.port
        r = self._command(target, cmd)
        target.log.log(8, "ykush power on %s[%d] / 0x%02x = 0x%02x %02x"
                       % (self.ykush_serial, self.port, cmd, r[0], r[1]))

    def off(self, target, _component):
        # Okie, this is quite a hack -- when we try to power it off,
        # if the serial is not found, we just assume the device is not
        # there and thus it is off -- so we ignore it. Why? Becuase
        # when we are part of a power control rail, we can't
        # interrogate the device or turn it off because maybe it is
        # disconnected. _command() has tried a few times to rule out
        # the device being quirky.
        cmd = self.port
        try:
            r = self._command(target, cmd)
            target.log.log(8, "ykush power off %s[%d] / 0x%02x = 0x%02x %02x"
                           % (self.ykush_serial, self.port, cmd, r[0], r[1]))
        except self.notfound_e:
            target.log.log(8, "ykush power off %s[%d] / 0x%02x = (not found)"
                           % (self.ykush_serial, self.port, cmd))
            pass

    def get(self, target, _component):
        cmd = 0x20 | self.port
        try:
            r = self._command(target, cmd)
            target.log.log(8, "ykush power get %s[%d] / 0x%02x = 0x%02x %02x"
                           % (self.ykush_serial, self.port, cmd, r[0], r[1]))
            if r[1] & 0x10 == 0x10:
                return True
            else:
                return False
        except self.notfound_e:
            # If it is not connected, it is off
            return False

    # things interface, to use as a plugger
    # get() is implemented above
    def plug(self, target, _thing):	# pylint: disable = missing-docstring
        self._command(target, 0x10 | self.port)

    def unplug(self, target, _thing):	# pylint: disable = missing-docstring
        self._command(target, self.port)


if __name__ == "__main__":
    import unittest

    logging.basicConfig()

    class _tt(object):
        log = logging

    class _test_ykush(unittest.TestCase):
        longMessage = True
        serial = None

        def test_0(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)

            y1.power_get_do(tt)

        def test_1(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)
            y1.retries = 1

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

        def test_2(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

        def test_3(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

        def test_4(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

        def test_5(self):
            tt = _tt()
            y1 = ykush(self.serial, 1)

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

            y1.power_off_do(tt)
            self.assertFalse(y1.power_get_do(tt))

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

            y1.power_on_do(tt)
            self.assertTrue(y1.power_get_do(tt))

    if 'SERIAL' in os.environ:
        _test_ykush.serial = os.environ['SERIAL']
    else:
        logging.warning("missing serial number for test YKUSH, "
                        "export SERIAL env variable")
    unittest.main()
