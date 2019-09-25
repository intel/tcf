#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Interface to press buttons in a target
--------------------------------------
"""

import time
import json
import ttbl


class impl(object):
    """
    Implementation interface for a button driver
    """
    def press(self, target, button):
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        raise NotImplementedError

    def release(self, target, button):
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        raise NotImplementedError

    def get(self, target, button):
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        # return True/False (press/release)
        raise NotImplementedError


class interface(ttbl.tt_interface):
    """
    Buttons interface to the core target API

    An instance of this gets added as an object to the main target
    with:

    >>> ttbl.config.targets['android_tablet'].interface_add(
    >>>     "buttons",
    >>>     ttbl.buttons.interface(
    >>>         power = ttbl.usbrly08b.button("00023456", 4),
    >>>         vol_up = ttbl.usbrly08b.button("00023456", 3),
    >>>         vol_down = ttbl.usbrly08b.button("00023456", 2),
    >>>     )
    >>> )

    where in this case the buttons are implemented with an USB-RLY08B
    relay board.

    This for example, can be used to instrument the power, volume up
    and volume down button of a tablet to control power switching. In
    the case of most Android tablets, the power rail then becomes:

    >>> ttbl.config.target_add(
    >>>     ttbl.tt.tt_power("android_tablet", [
    >>>         ttbl.buttons.pci_buttons_released(
    >>>             [ "vol_up", "vol_down", "power" ]),
    >>>         ttbl.buttons.pci_button_sequences(
    >>>             sequence_off = [
    >>>                 ( 'power', 'press' ),
    >>>                 ( 'vol_down', 'press' ),
    >>>                 ( 'resetting', 11 ),
    >>>                 ( 'vol_down', 'release' ),
    >>>                 ( 'power', 'release' ),
    >>>             ],
    >>>             sequence_on = [
    >>>                 ( 'power', 'press' ),
    >>>                 ( 'powering', 5 ),
    >>>                 ( 'power', 'release' ),
    >>>             ]
    >>>         ),
    >>>         ttbl.pc.delay_til_usb_device("SERIALNUMBER"),
    >>>         ttbl.adb.pci(4036, target_serial_number = "SERIALNUMBER"),
    >>>     ]),
    >>>     tags = dict(idle_poweroff = 0),
    >>>     target_type = "ANDROID TABLET'S TYPE"
    >>> )
    >>> 
    >>> ttbl.config.targets['android_tablet'].interface_add(
    >>>     "buttons",
    >>>     ttbl.buttons.interface(
    >>>         power = ttbl.usbrly08b.button("00023456", 4),
    >>>         vol_up = ttbl.usbrly08b.button("00023456", 3),
    >>>         vol_down = ttbl.usbrly08b.button("00023456", 2)
    >>>     )
    >>> )

    :param dict impls: dictionary keyed by button name and which
      values are instantiation of button drivers inheriting from
      :class:`ttbl.buttons.impl`.

      Names have to be valid python symbol names. 

    """
    def __init__(self, **impls):
        assert isinstance(impls, dict), \
            "impls must be a dictionary keyed by button name, got %s" \
            % type(impls).__name__
        ttbl.tt_interface.__init__(self)
        # Verify arguments
        for button_name, button_impl in impls.iteritems():
            assert isinstance(button_impl, impl), \
                "button implementation is type %s, expected ttbl.buttons.impl " \
                % type(button_impl)._name__
        # save it
        self.impls = impls

    def _target_setup(self, _):
        pass
        
    def press(self, who, target, button):
        assert button in self.impls.keys(), "button %s unknown" % button
        with self.target_owned_and_locked(who):
            self.impls[button].press(target, button)

    def release(self, who, target, button):
        assert button in self.impls.keys(), "button %s unknown" % button
        with self.target_owned_and_locked(who):
            self.impls[button].release(target, button)

    def _sequence(self, target, seq):
        # execute a sequence of button actions
        for name, action in seq:
            if action == 'press':
                target.log.info("%s: pressing button" % name)
                self.impls[name].press(target, name)
            elif action == 'release':
                target.log.info("%s: releasing button" % name)
                self.impls[name].release(target, name)
            else:
                target.log.info("%s: waiting %.2f seconds" % (name, action))
                time.sleep(action)

    def sequence(self, who, target, seq):
        """
        Execute a sequence of button actions on a target
        """
        assert all([
            isinstance(name, basestring) and (
                action > 0 or action == 'press' or action == 'release')
            for name, action in seq
        ])

        with target.target_owned_and_locked(who):
            self._sequence(target, seq)

    def get(self, target):
        """
        List button on a target
        """
        res = {}
        for name, impl in self.impls.iteritems():
            res[name] = impl.get(target, name)
        return dict(buttons = res)

    def _release_hook(self, target, _force):
        for button, impl in self.impls.iteritems():
            impl.release(target, button)


    def request_process(self, target, who, method, call, args, _user_path):
        ticket = args.get('ticket', "")
        if method == "POST" and call == "sequence":
            if not 'sequence' in args:
                raise RuntimeError("missing sequence arguments")
            sequence = json.loads(args['sequence'])
            target.buttons.sequence(who, target, sequence)
            r = {}
        elif method == "GET" and call == "get":
            r = target.buttons.get(target)
        else:
            raise RuntimeError("%s|%s: unsuported" % (method, call))
        target.timestamp()	# If this works, it is acquired and locked
        return r

def _check_iface(target):
    buttons_iface = getattr(target, "buttons", None)
    if not buttons_iface or not isinstance(buttons_iface, interface):
        raise RuntimeError("%s: target has no buttons interface" % target.id)


class pci_button_click(ttbl.tt_power_control_impl):
    """
    Power control implementation that clicks a button as a step to
    power on or off something on a target.
    """
    def __init__(self, button, time_on = 5, time_off = 20):
        assert isinstance(button, basestring)
        self.button = button
        self.time_on = time_on
        self.time_off = time_off

    def power_on_do(self, target):
        _check_iface(target)
        if not self.time_on:
            return
        target.buttons._sequence(target,
                                 [
                                     ( self.button, 'press' ),
                                     ( self.button, self.time_on ),
                                     ( self.button, 'release' )
                                 ])

    def power_off_do(self, target):
        _check_iface(target)
        if not self.time_off:
            return
        target.buttons._sequence(target,
                                 [
                                     ( self.button, 'press' ),
                                     ( self.button, self.time_off ),
                                     ( self.button, 'release' )
                                 ])

    def power_get_do(self, target):
        _check_iface(target)
        return None


class pci_button_sequences(ttbl.tt_power_control_impl):
    """
    Power control implementation that executest a button sequence on
    power on, another on power off.
    """
    def __init__(self, sequence_on = None, sequence_off = None):
        self.sequence_on = sequence_on
        self.sequence_off = sequence_off

    def power_on_do(self, target):
        _check_iface(target)
        if self.sequence_on:
            target.buttons._sequence(target, self.sequence_on)

    def power_off_do(self, target):
        _check_iface(target)
        if self.sequence_off:
            target.buttons._sequence(target, self.sequence_off)

    def power_get_do(self, target):
        _check_iface(target)
        return None

    
class pci_buttons_released(ttbl.tt_power_control_impl):
    """
    Power control implementation that ensures a list of buttons
    are not pressed before powering on a target.
    """
    def __init__(self, button_list):
        assert isinstance(button_list, list)
        self.button_list = button_list

    def power_on_do(self, target):
        _check_iface(target)
        for button in self.button_list:
            target.buttons.impls[button].release(target, button)

    def power_off_do(self, target):
        _check_iface(target)
        pass
        
    def power_get_do(self, target):
        _check_iface(target)
        return None

