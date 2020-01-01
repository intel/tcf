#! /usr/bin/python2
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
import urlparse

import requests
import usb.core
import usb.util

import commonl
import ttbl
import ttbl.power

# FIXME: move all these to ttbl.power once the old implementation is
#        all removed
# FIXME: replace with ttbl.power.fake()
# COMPAT: old interface, ttbl.tt_power_control_impl
class nil(ttbl.tt_power_control_impl):
    """
    """
    def __init__(self, id):
        ttbl.tt_power_control_impl.__init__(self)
        self.id = id

    def power_on_do(self, target):
        target.fsdb.set('pc-nil-%s' % self.id, 'On')

    def power_off_do(self, target):
        target.fsdb.set('pc-nil-%s' % self.id, None)

    def power_get_do(self, target):
        return target.fsdb.get('pc-nil-%s' % self.id) != None

# COMPAT: old interface, ttbl.tt_power_control_impl
# FIXME: remove, unused, impractical
class manual(ttbl.tt_power_control_impl):
    """
    Implement a manual power control interface that prompts the user
    to do the stuff.

    """
    def __init__(self, id):
        ttbl.tt_power_control_impl.__init__(self)
        self.id = id
        self.log = logging.getLogger("target-" +  id)
        self.log.error("USER: ensure power is off to target %s; "
                       "press [Ctrl-D] when done", self.id)
        sys.stdin.read()

    def power_on_do(self, target):
        self.log.error("USER: power on target %s; press [Ctrl-D] when done",
                       self.id)
        sys.stdin.read()
        target.fsdb.set('powered-manual-%s' % self.id, 'On')

    def power_off_do(self, target):
        self.log.error("USER: power off target %s; press [Ctrl-D] when done",
                       self.id)
        sys.stdin.read()
        target.fsdb.set('powered-manual-%s' % self.id, None)

    def power_get_do(self, target):
        # Tracks the power state of the whole target
        return target.fsdb.get('powered-manual-%s' % self.id) != None


class delay(ttbl.tt_power_control_impl, ttbl.power.impl_c):
    """
    Introduce artificial delays when calling on/off/get to allow
    targets to settle.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.
    """
    def __init__(self, on = 0, off = 0):
        ttbl.power.impl_c.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        self.on_delay = float(on)
        self.off_delay = float(off)

    def on(self, target, component):
        target.log.debug("%s: on delay %f", component, self.on_delay)
        time.sleep(self.on_delay)

    def off(self, target, component):
        target.log.debug("%s: off delay %f", component, self.off_delay)
        time.sleep(self.off_delay)

    def get(self, target, component):
        # this reports None because this is is just a delay loop
        return None

    # COMPAT: old interface, ttbl.tt_power_control_impl
    def power_on_do(self, target):
        return self.on(target, "n/a")

    def power_off_do(self, target):
        return self.off(target, "n/a")

    def power_get_do(self, target):
        # this reports None because this is is just a delay loop
        return None



class delay_til_file_gone(ttbl.power.impl_c, ttbl.tt_power_control_impl):
    """
    Delay until a file dissapears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.
    """
    def __init__(self, poll_period = 0.25, timeout = 25,
                 on = None, off = None, get = None):
        ttbl.power.impl_c.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        self.on_file = on
        self.off_file = off
        self.get_file = get
        self.poll_period = poll_period
        self.timeout = timeout

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

    # COMPAT: old interface, ttbl.tt_power_control_impl
    def power_on_do(self, target):
        return self.on(target, "n/a")

    def power_off_do(self, target):
        return self.off(target, "n/a")

    def power_get_do(self, target):
        # this reports None because this is is just a delay loop
        return None


class delay_til_file_appears(ttbl.power.impl_c, ttbl.tt_power_control_impl):
    """
    Delay until a file appears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.
    """
    def __init__(self, filename,
                 poll_period = 0.25, timeout = 25,
                 action = None, action_args = None):
        ttbl.power.impl_c.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        self.filename = filename
        self.poll_period = poll_period
        self.timeout = timeout
        assert action == None \
            or isinstance(action, Exception) \
            or callable(action), \
            "action '%s' has to be an exception type or callable" % action
        self.action = action
        self.action_args = action_args

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

    # COMPAT: old interface, ttbl.tt_power_control_impl
    def power_on_do(self, target):
        return self.on(target, "n/a")

    def power_off_do(self, target):
        return self.off(target, "n/a")

    def power_get_do(self, target):
        # this reports None because this is is just a delay loop
        return None



class delay_til_usb_device(ttbl.power.impl_c, ttbl.tt_power_control_impl):
    """
    Delay power-on until a USB device dis/appears.

    This is meant to be used in a stacked list of power
    implementations given to a power control interface.

    :param str serial: Serial number of the USB device to monitor

    :param bool when_powering_on: Check when powering on if True
      (default) or when powering off (if false)

    :param bool want_connected: when checking, we want the device to
      be connected (True) or disconnected (False)

    :param collections.Callable action: action to execute when the
      device is not found, before waiting. Note the first parameter
      passed to the action is the target itself and then any other
      parameter given in ``action_args``

    :param action_args: tuple of parameters to pass to ``action``.
    """
    def __init__(self, serial, when_powering_on = True, want_connected = True,
                 poll_period = 0.25, timeout = 25,
                 action = None, action_args = None):
        ttbl.tt_power_control_impl.__init__(self)
        ttbl.power.impl_c.__init__(self)
        self.serial = serial
        self.when_powering_on = when_powering_on
        self.want_connected = want_connected
        self.poll_period = poll_period
        self.timeout = timeout
        self.action = action
        self.action_args = action_args
        self.component = None		# filled in by _on/_off/_get
        if action != None:
            assert hasattr(action, "__call__")
        self.log = None			# filled out in _on/_off/_get

    class not_found_e(Exception):
        "Exception raised when a USB device is not found"
        pass

    # This code is SINGLE THREADED, so we are going to share one
    # backend to cut in the number of open file handles
    backend = None

    def _usb_match_on_serial(self, d):
        try:
            try:
                # Use get_string(); it is being better at working
                # around an issue with context. When we get here, the
                # 'd' object for some reasons doesn't have all the stuff
                # it needs to have to properly obtain langIDs and
                # stuff. Somehow, using get_string() works better
                # instead of accessing d.serial_number (which triggers
                # it being updated on the side and things fail more).
                serial_number = usb.util.get_string(d, d.iSerialNumber)
            except ValueError as e:
                # Some devices get us here, unknown why--probably
                # permissions issue
                if e.message == "The device has no langid":
                    self.log.debug("%s: USB %04x:%04x @%d/%03d: "
                                   "langid error: %s",
                                   self.component,
                                   d.idVendor, d.idProduct,
                                   d.bus, d.address, d.langids)
                    serial_number = None
                else:
                    raise
            self.log.log(7, "%s: USB %04x:%04x @%d/%03d [%s]: considering",
                         self.component,
                         d.idVendor, d.idProduct,
                         d.bus, d.address, serial_number)
            return serial_number == self.serial
        except usb.core.USBError as e:
            # Ignore errors, normally means we have no permission to
            # read the device
            self.log.log(
                7, "%s: USB %04x:%04x @%d/%03d: can't access: %s",
                self.component, d.idVendor, d.idProduct, d.bus, d.address, e)
            return False
        except Exception as e:
            self.log.error(
                "BUG: %s: %04x:%04x @%d/%03d: exception %s\n%s",
                self.component, d.idVendor, d.idProduct, d.bus, d.address, e,
                traceback.format_exc())

    def _find_device(self):
        # We do not cache the backend [commented out code], as
        # it (somehow) makes it miss the device we are looking
        # for; talk about butterfly effect at a local level --
        # might be a USB library version issue?
        return usb.core.find(find_all = False,
                             #backend = type(self).backend,
                             custom_match = self._usb_match_on_serial)

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
            try:
                t = time.time()
                if t - t0 > timeout:
                    raise self.not_found_e(
                        "%s: timeout (%.2fs) on %s waiting for "
                        "USB device with serial %s to %s"
                        % (self.component, t - t0, action, self.serial, text))
                # We do not cache the backend [commented out code], as
                # it (somehow) makes it miss the device we are looking
                # for; talk about butterfly effect at a local level --
                # might be a USB library version issue?
                dev = self._find_device()
                if dev == None:
                    self.log.log(8, "%s: USB [%s]: NOT FOUND",
                                 self.component, self.serial)
                    if not self.want_connected:
                        break
                else:
                    self.log.log(8, "%s: USB %04x:%04x @%d/%03d [%s]: found",
                                 self.component, dev.idVendor, dev.idProduct,
                                 dev.bus, dev.address, dev.serial_number)
#                    if type(self).backend == None:
#                        type(self).backend = dev._ctx.backend
                    # We don't need this guy, close it
                    dev._ctx.managed_close()
                    if self.want_connected:
                        break
            except usb.core.USBError as e:
                self.log.info("%s/%s: delaying %.2fs for USB device "
                              "for serial %s to %s: exception %s"
                              % (self.component, action, self.poll_period,
                                 self.serial, text, e))
                if e.errno != errno.EACCES:
                    raise
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
        self.log = target.log		# for _usb_match_on_serial
        self.component = component	# for _usb_match_on_serial
        if self.when_powering_on:
            self._is_device_present(target, "power-on")

    def off(self, target, component):
        self.log = target.log		# for _usb_match_on_serial
        self.component = component	# for _usb_match_on_serial
        if not self.when_powering_on:
            self._is_device_present(target, "power-off")

    def get(self, target, component):
        # Return if the USB device is connected
        #
        # Why? because for some targets, we can only tell if they are
        # connected by seeing a USB device plugged to the system. For
        # example, a USB connected Android target which we power
        # on/off by tweaking the buttons so there is no PDU to act upon.
        self.log = target.log		# for _usb_match_on_serial
        self.component = component	# for _usb_match_on_serial
        try:
            dev = self._find_device()
            # if we find a device, it is connected, we are On
            return dev != None
        except usb.core.USBError as e:
            target.log.warning(
                "%s: can't tell if USB device `%s` is connected: %s"
                % (component, self.serial, e))
            return False

    # COMPAT: old interface, ttbl.tt_power_control_impl
    def power_on_do(self, target):
        return self.on(target, "n/a")

    def power_off_do(self, target):
        return self.off(target, "n/a")

    def power_get_do(self, target):
        # this reports None because this is is just a delay loop
        return None



class dlwps7(ttbl.power.impl_c, ttbl.tt_power_control_impl):
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

    Access language documented at http://www.digital-loggers.com/http.html.

    If you get an error like:

        Exception: Cannot find '<!-- state=(?P<state>[0-9a-z][0-9a-z]) lock=[0-9a-z][0-9a-z] -->' in power switch response

    this might be that you are going through a proxy that is messing
    up things. In some cases the proxy was messing up the
    authentication and imposing javascript execution that made the
    driver fail.
    """
    def __init__(self, _url, reboot_wait_s = 0.5):
        ttbl.tt_power_control_impl.__init__(self)
        ttbl.power.impl_c.__init__(self)
        assert isinstance(_url, basestring)
        assert isinstance(reboot_wait_s, (int, float))
        url = urlparse.urlparse(_url)
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

    def on(self, target, component):
        r = requests.get(self.url + "/outlet?%d=ON" % self.outlet)
        commonl.request_response_maybe_raise(r)

    def off(self, target, _component):
        r = requests.get(self.url + "/outlet?%d=OFF" % self.outlet)
        commonl.request_response_maybe_raise(r)

    state_regex = re.compile("<!-- state=(?P<state>[0-9a-z][0-9a-z]) lock=[0-9a-z][0-9a-z] -->")
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

    # COMPAT: old interface, ttbl.tt_power_control_impl
    def power_on_do(self, target):
        return self.on(target, "n/a")

    def power_off_do(self, target):
        return self.off(target, "n/a")

    def power_get_do(self, target):
        # this reports None because this is is just a delay loop
        return None

    def power_cycle_do(self, target, wait = 0):
        if self.power_get_do(target):
            r = requests.get(self.url + "/outlet?%d=OFF" % self.outlet)
            commonl.request_response_maybe_raise(r)
            if self.reboot_wait_s > 0 or wait > 0:
                time.sleep(max(self.reboot_wait_s, wait))
        r = requests.get(self.url + "/outlet?%d=ON" % self.outlet)
        commonl.request_response_maybe_raise(r)
        # Give it time to settle
        time.sleep(self.reboot_wait_s)
        self.power_get_do(target)
