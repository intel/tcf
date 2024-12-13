#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""

"""
import errno
import logging
import os
import re
import sys
import time
import traceback
import urllib.parse

import requests
import usb.core
import usb.util

import commonl
import ttbl
import ttbl.power

# FIXME: move all these to ttbl.power once the old implementation is
#        all removed
# FIXME: replace with ttbl.power.fake()

class delay(ttbl.power.impl_c):
    """
    Introduce artificial delays when calling on/off/get to allow
    targets to settle.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, on = 0, off = 0, **kwargs):
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.on_delay = float(on)
        self.off_delay = float(off)
        self.upid_set(
            "Delays on power on (%.fs) / off (%.fs)" % (on, off),
            on = on, off = off)

    def on(self, target, component):
        target.log.debug("%s: on delay %f", component, self.on_delay)
        time.sleep(self.on_delay)

    def off(self, target, component):
        target.log.debug("%s: off delay %f", component, self.off_delay)
        time.sleep(self.off_delay)

    def get(self, target, component):
        # this reports None because this is is just a delay loop
        return None



class delay_til_device_spec_c(ttbl.power.impl_c):
    
    """
    Delay power-on until a device dis/appears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    This replaces :class:`ttbl.pc.delay_til_usb_device` and company,
    since it look for a generic device specification

    :param str device_spec: device specification, see
      :class:`ttbl.device_resolver_c`

    :param upid: Unique Physical IDentification descriptor used to
      identify this device we are looking for; normally set to match
      that that describes the object to tie them together; eg:

      >>> serial0 = ttbl.console.serial_pc("usb,#12141323")
      >>> delay_til_serial0 = ttbl.console.delay_til_device_spec_c(
      >>>     "usb,#12141323", upid = serial0.upid)

    :param str property_name: (optional, default *usb_serial_number*)
      where to read the device specification from in the inventory,
      normally instrumentation.UPID.PROPERTYNAME.

    :param str spec_prefix: (optional, default *usb,#*) see
      :class:`ttbl.device_resolver_c`.

    :param bool when_powering_on: Check when powering on if True
      (default) or when powering off (if false)

    :param bool want_connected: when checking, we want the device to
      be connected (True) or disconnected (False)

    :param collections.Callable action: action to execute when the
      device is not found, before waiting. Note the first parameter
      passed to the action is the target itself and then any other
      parameter given in ``action_args``

    :param action_args: tuple of parameters to pass to ``action``.

    Other parameters as to :class:ttbl.power.impl_c.
    """

    def __init__(self, device_spec, when_powering_on = True, want_connected = True,
                 poll_period = 0.25, timeout = 25,
                 action = None, action_args = None,
                 # most devices are USB anyway
                 property_name = "usb_serial_number",
                 spec_prefix = "usb,#",
                 expected_count = 1,
                 upid = None,
                 **kwargs):
        assert isinstance(expected_count, int), \
            f"expected_count: expected >= 1 integer, got {type(expected_count)}"
        assert expected_count >= 1, \
            f"expected_count: expected >= 1 integer, got {expected_count}"
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.device_spec = device_spec
        self.when_powering_on = when_powering_on
        self.want_connected = want_connected
        self.poll_period = poll_period
        self.timeout = timeout
        self.action = action
        self.action_args = action_args
        self.component = None		# filled in by _on/_off/_get
        self.property_name = property_name
        self.spec_prefix = spec_prefix
        self.expected_count = expected_count
        if action != None:
            assert callable(action)
        self.log = None			# filled out in _on/_off/_get
        when = "powering-on" if when_powering_on else "powering-off"
        what = "connected" if want_connected else "disconnected"
        if upid == None:
            self.upid_set(
                "Delayer until device with device_spec '%s' is %s when %s,"
                " checking every %.2fs timing out at %.1fs" % (
                    device_spec, what, when, poll_period, timeout),
                device_spec = device_spec,
                when_powering_on = when_powering_on,
                want_connected = want_connected,
                poll_period = poll_period,
                timeout = timeout)
        else:
            self.upid = upid


    class not_found_e(Exception):
        """Exception raised when a device is not found."""

        pass



    def _is_device_present(self, target, action, timeout = None):
        if timeout == None:
            timeout = self.timeout
        t0 = time.time()
        self.log = target.log
        if self.want_connected:
            text = "appear"
            text_past = "appear"
        else:
            text = "disappear"
            text_past = "disappear"
        dev = None
        device_resolver = ttbl.device_resolver_c(
            target, self.device_spec,
            f"instrumentation.{self.upid_index}.{self.property_name}",
            spec_prefix = self.spec_prefix)
        spec, origin = device_resolver.spec_get()

        while True:
            t = time.time()
            if t - t0 > timeout:
                raise self.not_found_e(
                    "%s: timeout (%.2fs) on %s waiting for "
                    "device %s @%s to %s"
                    % (self.component, t - t0, action,
                       spec, origin, text))

            devices = device_resolver.devices_find_by_spec()
            if not devices:
                self.log.debug("%s: device %s @%s: NOT FOUND",
                               self.component, spec, origin)
                if not self.want_connected:
                    break
            else:		# this can be more than one edevice...
                self.log.debug("%s: device %s@%s: found: %s",
                               spec, origin, " ".join(devices))
                if self.want_connected:
                    break

            if self.action:
                self.log.debug("%s/%s: executing action %s"
                               % (self.component, action, self.action))
                try:
                    self.action(target, *self.action_args)
                except Exception as e:
                    self.log.error("%s/%s: error executing action %s: %s",
                                   self.component, action, self.action, e)
                    raise
            self.log.info("%s/%s: delaying %.2fs for device %s @%s to %s"
                          % (self.component, action, self.poll_period,
                             spec, origin, text))
            time.sleep(self.poll_period)
        target.log.debug(
            "%s/%s: delayed %.2fs for USB device %s @%s to %s"
            % (self.component, action, t - t0, spec, origin, text_past))
        return dev


    def on(self, target, component):
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present
        if self.when_powering_on:
            self._is_device_present(target, "power-on")


    def off(self, target, component):
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present
        if not self.when_powering_on:
            self._is_device_present(target, "power-off")


    def get(self, target, component):
        # Return if the USB device is connected
        #
        # Why? because for some targets, we can only tell if they are
        # connected by seeing a USB device plugged to the system. For
        # example, a USB connected Android target which we power
        # on/off by tweaking the buttons so there is no PDU to act upon.
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present

        device_resolver = ttbl.device_resolver_c(
            target, self.device_spec,
            f"instrumentation.{self.upid_index}.{self.property_name}",
            spec_prefix = self.spec_prefix)

        devices = device_resolver.devices_find_by_spec()
        if devices:
            return True
        return False



class delay_til_file_gone(ttbl.power.impl_c):
    """
    Delay until a file dissapears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, poll_period = 0.25, timeout = 25,
                 on = None, off = None, get = None, **kwargs):
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.on_file = on
        self.off_file = off
        self.get_file = get
        self.poll_period = poll_period
        self.timeout = timeout
        l = []
        if on:
            l.append("'%s' disappears when power-on" % on)
        if off:
            l.append("'%s' disappears when power-off" % off)
        self.upid_set(
            "Delayer until %s, checking every %.2fs timing out at %.1fs" % (
                ", ".join(l), poll_period, timeout),
            on_file = on,
            off_file = off,
            poll_period = poll_period,
            timeout = timeout)

    def on(self, target, component):
        if self.on_file == None:
            return
        t0 = time.time()
        while os.path.exists(self.on_file):
            t = time.time()
            if t - t0 > self.timeout:
                raise RuntimeError("%s: timeout (%.2fs) on power-on delay "
                                   "waiting for file %s to disappear"
                                   % (component, t - t0, self.on_file))
            target.log.debug("%s: delaying power-on %.2fs until "
                             "file %s dissapears",
                             component, self.poll_period, self.on_file)
            time.sleep(self.poll_period)
        target.log.debug("%s: delayed power-on %.2fs until file %s "
                         "dissapeared",
                         component, time.time() - t0, self.on_file)

    def off(self, target, component):
        if self.off_file == None:
            return
        t0 = time.time()
        while os.path.exists(self.off_file):
            t = time.time()
            if t - t0 > self.timeout:
                raise RuntimeError("%s: timeout (%.2fs) on power-off delay "
                                   "waiting for file %s to disappear"
                                   % (component, t - t0, self.off_file))
            target.log.debug("%s: delaying power-on %.2fs until file %s "
                             "dissapears",
                             component, self.poll_period, self.off_file)
            time.sleep(self.poll_period)
        target.log.debug("%s: delayed power-off %.2fs until file %s "
                         "dissapeared",
                         component, time.time() - t0, self.off_file)

    def get(self, target, component):
        return not os.path.exists(self.filename)


class delay_til_file_appears(ttbl.power.impl_c):
    """
    Delay until a file appears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, filename,
                 poll_period = 0.25, timeout = 25,
                 action = None, action_args = None, **kwargs):
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.filename = filename
        self.poll_period = poll_period
        self.timeout = timeout
        assert action == None \
            or isinstance(action, Exception) \
            or callable(action), \
            "action '%s' has to be an exception type or callable" % action
        self.action = action
        self.action_args = action_args
        self.upid_set(
            "Delayer until file '%s' appears during power-on,"
            " checking every %.2fs timing out at %.1fs" % (
                filename, poll_period, timeout),
            filename = filename,
            poll_period = poll_period,
            timeout = timeout)

    def on(self, target, component):
        if self.filename == None:
            return
        t0 = time.time()
        while not os.path.exists(self.filename):
            t = time.time()
            if t - t0 > self.timeout:
                raise RuntimeError("%s: timeout (%.2fs) on power-on delay "
                                   "waiting for file %s to appear"
                                   % (component, t - t0, self.filename))
            if self.action:
                target.log.debug("%s: executing action %s"
                                 % (component, self.action))
                if isinstance(self.action, Exception):
                    raise self.action(*self.action_args)
                else:
                    try:
                        self.action(target, *self.action_args)
                    except Exception as e:
                        target.log.error("%s: error executing action %s: %s",
                                         component, self.action, e)
                        raise
            target.log.debug("%s: delaying power-on %.2fs until file %s "
                             "appears"
                             % (component, self.poll_period, self.filename))
            time.sleep(self.poll_period)
        target.log.debug("%s: delayed power-on %.2fs until file %s appeared"
                         % (component, time.time() - t0, self.filename))

    def off(self, target, component):
        # hmm, missing no file
        pass

    def get(self, target, component):
        return os.path.exists(self.filename)


class delay_til_usb_device(ttbl.power.impl_c):
    """
    Delay power-on until a USB device dis/appears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    :param str serial: Serial number of the USB device to monitor

    :param int sibling_port: (optional) work instead on the device
      that is in the same hub as the given device, but in this port
      number. See :func:`ttbl.usb_device_by_serial`.

    :param bool when_powering_on: Check when powering on if True
      (default) or when powering off (if false)

    :param bool want_connected: when checking, we want the device to
      be connected (True) or disconnected (False)

    :param collections.Callable action: action to execute when the
      device is not found, before waiting. Note the first parameter
      passed to the action is the target itself and then any other
      parameter given in ``action_args``

    :param action_args: tuple of parameters to pass to ``action``.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, serial, when_powering_on = True, want_connected = True,
                 sibling_port = None,
                 poll_period = 0.25, timeout = 25,
                 action = None, action_args = None, **kwargs):
        if sibling_port != None:
            assert isinstance(sibling_port, int) and sibling_port > 0, \
                "invalid sibling_port; expected positive integer > 0"
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.serial = serial
        self.when_powering_on = when_powering_on
        self.want_connected = want_connected
        self.poll_period = poll_period
        self.timeout = timeout
        self.action = action
        self.action_args = action_args
        self.component = None		# filled in by _on/_off/_get
        self.sibling_port = sibling_port
        if action != None:
            assert hasattr(action, "__call__")
        self.log = None			# filled out in _on/_off/_get
        when = "powering-on" if when_powering_on else "powering-off"
        what = "connected" if want_connected else "disconnected"
        self.upid_set(
            "Delayer until USB device with serial number '%s' is %s when %s,"
            " checking every %.2fs timing out at %.1fs" % (
                serial, what, when, poll_period, timeout),
            serial = serial, sibling_port = sibling_port,
            when_powering_on = when_powering_on,
            want_connected = want_connected,
            poll_period = poll_period,
            timeout = timeout)


    class not_found_e(Exception):
        "Exception raised when a USB device is not found"
        pass


    def _is_device_present(self, target, action, timeout = None):
        if timeout == None:
            timeout = self.timeout
        t0 = time.time()
        self.log = target.log
        if self.want_connected:
            text = "appear"
            text_past = "appear"
        else:
            text = "disappear"
            text_past = "disappear"
        dev = None
        while True:
            t = time.time()
            if t - t0 > timeout:
                raise self.not_found_e(
                    "%s: timeout (%.2fs) on %s waiting for "
                    "USB device with serial %s/%s to %s"
                    % (self.component, t - t0, action,
                       self.serial, self.sibling_port, text))
            # We do not cache the backend [commented out code], as
            # it (somehow) makes it miss the device we are looking
            # for; talk about butterfly effect at a local level --
            # might be a USB library version issue?
            dev, product, vendor, busnum, devnum = ttbl.usb_device_by_serial(
                self.serial, self.sibling_port,
                "idProduct", "idVendor", "busnum", "devnum")

            if dev == None:
                self.log.debug("%s: USB [%s/%s]: NOT FOUND",
                               self.component, self.serial, self.sibling_port)
                if not self.want_connected:
                    break
            else:
                self.log.debug("%s: USB %s:%s @%s.%s [%s/%s]: found",
                               self.component, product, vendor,
                               busnum, devnum, self.serial, self.sibling_port)
                if self.want_connected:
                    break

            if self.action:
                self.log.debug("%s/%s: executing action %s"
                               % (self.component, action, self.action))
                try:
                    self.action(target, *self.action_args)
                except Exception as e:
                    self.log.error("%s/%s: error executing action %s: %s",
                                   self.component, action, self.action, e)
                    raise
            self.log.info("%s/%s: delaying %.2fs for USB device with "
                          "serial %s to %s"
                          % (self.component, action, self.poll_period,
                             self.serial, text))
            time.sleep(self.poll_period)
        target.log.debug(
            "%s/%s: delayed %.2fs for USB device with serial %s to %s"
            % (self.component, action, t - t0, self.serial, text_past))
        return dev


    def on(self, target, component):
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present
        if self.when_powering_on:
            self._is_device_present(target, "power-on")


    def off(self, target, component):
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present
        if not self.when_powering_on:
            self._is_device_present(target, "power-off")


    def get(self, target, component):
        # Return if the USB device is connected
        #
        # Why? because for some targets, we can only tell if they are
        # connected by seeing a USB device plugged to the system. For
        # example, a USB connected Android target which we power
        # on/off by tweaking the buttons so there is no PDU to act upon.
        self.log = target.log		# for _is_device_present
        self.component = component	# for _is_device_present
        try:
            dev = ttbl.usb_device_by_serial(self.serial, self.sibling_port)
            # if we find a device, it is connected, we are On
            return dev != None
        except usb.core.USBError as e:
            target.log.warning(
                "%s: can't tell if USB device `%s` is connected: %s"
                % (component, self.serial, e))
            return False


class dlwps7(ttbl.power.impl_c):
    """
    Implement a power control interface to the Digital Logger's Web
    Power Switch 7

    :param str _url: URL describing the unit and outlet number, in
      the form::

        http://USER:PASSWORD@HOST:PORT/OUTLETNUMBER

      where `USER` and `PASSWORD` are valid accounts set in the
      Digital Logger's Web Power Switch 7 administration interface
      with access to the `OUTLETNUMBER`.

    :param float reboot_wait: Seconds to wait in when power cycling an
      outlet from off to on (defaults to 0.5s) or after powering up.

    Other parameters as to :class:ttbl.power.impl_c.

    Access language documented at http://www.digital-loggers.com/http.html.

    If you get an error like:

        Exception: Cannot find '<!-- state=(?P<state>[0-9a-z][0-9a-z]) lock=[0-9a-z][0-9a-z] -->' in power switch response

    this might be that you are going through a proxy that is messing
    up things. In some cases the proxy was messing up the
    authentication and imposing javascript execution that made the
    driver fail.
    """
    def __init__(self, _url, reboot_wait_s = 0.5, **kwargs):
        ttbl.power.impl_c.__init__(self, paranoid = True, **kwargs)
        # we run the driver in paranoid mode so the on and off
        # operations become synchronous and won't return until we
        # confirm the power is on or off. We do one sample only, since
        # we know it returns values correctly
        self.paranoid_get_samples = 1
        assert isinstance(_url, str)
        assert isinstance(reboot_wait_s, (int, float))
        url = urllib.parse.urlparse(_url)
        self.reboot_wait_s = reboot_wait_s
        self.url = "%s://%s" % (url.scheme, url.netloc)
        self.url_no_password = "%s://%s" % (url.scheme, url.hostname)
        outlet = url.path[1:]
        if outlet == "":
            raise Exception("%s: URL missing outlet number" % _url)
        try:
            self.outlet = int(outlet)
        except Exception:
            raise Exception("%s: outlet number '%s' not an integer"
                            % (_url, outlet))
        if self.outlet < 1 or self.outlet > 8:
            raise Exception("%s: outlet number '%d' has to be 1 >= outlet >= 8"
                            % (_url, self.outlet))
        self.url = self.url
        self.upid_set(
            "DLI Web Power Switch %s #%d" % (
                self.url_no_password, self.outlet),
            url = self.url_no_password, outlet = self.outlet)

    def on(self, target, component):
        r = requests.get(self.url + "/outlet?%d=ON" % self.outlet)
        commonl.request_response_maybe_raise(r)

    def off(self, target, _component):
        r = requests.get(self.url + "/outlet?%d=OFF" % self.outlet)
        commonl.request_response_maybe_raise(r)

    state_regex = re.compile(b"<!-- state=(?P<state>[0-9a-z][0-9a-z]) lock=[0-9a-z][0-9a-z] -->")
    def get(self, target, component):
        """Get the power status for the outlet

        The unit returns the power state when querying the
        ``/index.htm`` path...as a comment inside the HTML body of the
        respose. *Chuckle*

        So we look for::

          <!-- state=XY lock=ANY -->

        *XY* is the hex bitmap of states against the outlet
        number. *ANY* is the hex lock bitmap (outlets that can't
        change).

        """
        r = requests.get(self.url + "/index.htm")
        commonl.request_response_maybe_raise(r)
        m = self.state_regex.search(r.content)
        if not m:
            raise Exception("Cannot find '%s' in power switch response"
                            % self.state_regex.pattern)
        state = int(m.group('state'), base = 16)
        # Note outlet numbers are base-1...
        if state & (1 << self.outlet - 1) == 0:
            return False
        else:
            return True
