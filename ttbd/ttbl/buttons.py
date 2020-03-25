#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Press target's buttons
----------------------

A target that has physical buttons that can be pressed can be
instrumented so they can be pressed/released. This interface provides
means to access said interface.

A target will offer the :class:`interface <ttbl.buttons.interface>` to
press each button, each of which is implemented by different instances
of :class:`ttbl.buttons.impl_c`.

"""

import time
import json
import ttbl


class impl_c(ttbl.tt_interface_impl_c):
    """
    Implementation interface for a button driver

    A button can be pressed or it can be released; it's current state
    can be obtained.
    """
    def __init__(self):
        ttbl.tt_interface_impl_c.__init__(self)
        self.parameters = {}

    def press(self, target, button):
        """
        Press a target's button

        :param ttbl.test_target target: target where the button is
        :param str button: name of button
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        raise NotImplementedError

    def release(self, target, button):
        """
        Release a target's button

        :param ttbl.test_target target: target where the button is
        :param str button: name of button
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        raise NotImplementedError

    def get(self, target, button):
        """
        Get a target's button state

        :param ttbl.test_target target: target where the button is
        :param str button: name of button
        :returns: *True* if pressed, *False* otherwise.
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(button, basestring)
        # return True/False (press/release)
        raise NotImplementedError


class interface(ttbl.tt_interface):
    """
    Buttons interface to the core target API

    This provides access to all of the target's buttons, independent
    of their implementation, so they can be pressed, released or their
    state queried.

    An instance of this gets added as an object to the main target
    with:

    >>> ttbl.test_target.get('android_tablet').interface_add(
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

    >>> target.interface_add("power", ttbl.power.interface(
    >>>     ttbl.buttons.pci_buttons_released(
    >>>         [ "vol_up", "vol_down", "power" ]),
    >>>     ttbl.buttons.pci_button_sequences(
    >>>         sequence_off = [
    >>>             ( 'power', 'press' ),
    >>>             ( 'vol_down', 'press' ),
    >>>             ( 'resetting', 11 ),
    >>>             ( 'vol_down', 'release' ),
    >>>             ( 'power', 'release' ),
    >>>         ],
    >>>         sequence_on = [
    >>>             ( 'power', 'press' ),
    >>>             ( 'powering', 5 ),
    >>>             ( 'power', 'release' ),
    >>>         ]
    >>>     ),
    >>>     ttbl.pc.delay_til_usb_device("SERIALNUMBER"),
    >>>     ttbl.adb.pci(4036, target_serial_number = "SERIALNUMBER"),
    >>> ))
    >>> 
    >>> ttbl.test_target.get('android_tablet').interface_add(
    >>>     "buttons",
    >>>     ttbl.buttons.interface(
    >>>         power = ttbl.usbrly08b.button("00023456", 4),
    >>>         vol_up = ttbl.usbrly08b.button("00023456", 3),
    >>>         vol_down = ttbl.usbrly08b.button("00023456", 2)
    >>>     )
    >>> )

    :param dict impls: dictionary keyed by button name and which
      values are instantiation of button drivers inheriting from
      :class:`ttbl.buttons.impl_c`.

      Names have to be valid python symbol names. 

    """
    def __init__(self, *impls, **kwimpls):
        ttbl.tt_interface.__init__(self)
        self.impls_set(impls, kwimpls, impl_c)

    def _target_setup(self, target):
        target.tags_update(dict(buttons = self.impls.keys()))
        
    def _release_hook(self, target, _force):
        for button, impl in self.impls.iteritems():
            impl.release(target, button)

    def sequence(self, target, sequence):
        """Execute a sequence of button actions on a target

        The sequence argument has to be a list of pairs:

        - *( 'press', BUTTON-NAME)*
        - *( 'release', BUTTON-NAME)*
        - *( 'wait', NUMBER-OF-SECONDS)*

        """
        target.timestamp()
        for action, arg in sequence:
            if action == 'press':
                impl, _ = self.impl_get_by_name(arg, "button")
                target.log.info("%s: pressing button" % arg)
                impl.press(target, arg)
            elif action == 'release':
                impl, _ = self.impl_get_by_name(arg, "button")
                target.log.info("%s: releasing button" % arg)
                impl.release(target, arg)
            elif action == 'wait':
                assert arg > 0, "argument to wait has to be a" \
                    " positive seconds interval; got %s" % arg
                target.log.info("waiting %s seconds" % arg)
                time.sleep(arg)
            else:
                raise RuntimeError(
                    "unknown action '%s'; expected 'press', " \
                    "'release', 'wait'" % action)

    def put_sequence(self, target, who, args, _files, _user_path):
        """Execute a sequence of button actions on a target

        The sequence argument has to be a list of pairs:

        - *( 'press', BUTTON-NAME)*
        - *( 'release', BUTTON-NAME)*
        - *( 'wait', NUMBER-OF-SECONDS)*

        """
        if not 'sequence' in args:
            raise RuntimeError("missing sequence argument")
        sequence = json.loads(args['sequence'])
        with target.target_owned_and_locked(who):
            target.timestamp()
            self.sequence(target, sequence)
            return {}

    def get_list(self, target, _who, _args, _files, _user_path):
        """
        List buttons on a target and their state
        """
        res = {}
        for name, impl in self.impls.iteritems():
            res[name] = impl.get(target, name)
        return dict(result = res)


def _check_iface(target):
    buttons_iface = getattr(target, "buttons", None)
    if not buttons_iface or not isinstance(buttons_iface, interface):
        raise RuntimeError("%s: target has no buttons interface" % target.id)


class button_click_pc(ttbl.power.impl_c):
    """
    Power control implementation that clicks a button as a step to
    power on or off something on a target.
    """
    def __init__(self, button, time_on = 5, time_off = 20):
        ttbl.power.impl_c.__init__(self)
        assert isinstance(button, basestring)
        self.button = button
        self.time_on = time_on
        self.time_off = time_off

    def on(self, target, _component):
        _check_iface(target)
        if self.time_on:
            target.buttons.sequence(target, [
                ( 'press', self.button ),
                ( 'wait', self.time_on ),
                ( 'release', self.button )
            ])

    def off(self, target, component):
        _check_iface(target)
        if self.time_off:
            target.buttons.sequence(target, [
                ( 'press', self.button ),
                ( 'wait', self.time_off ),
                ( 'release', self.button )
            ])

    def get(self, target, component):
        # no real press status, so can't tell
        return None


class button_sequence_pc(ttbl.power.impl_c):
    """
    Power control implementation that executest a button sequence on
    power on, another on power off.
    """
    def __init__(self, sequence_on = None, sequence_off = None):
        ttbl.power.impl_c.__init__(self)
        self.sequence_on = sequence_on
        self.sequence_off = sequence_off

    def on(self, target, _component):
        _check_iface(target)
        if self.sequence_on:
            target.buttons.sequence(target, self.sequence_on)

    def off(self, target, _component):
        _check_iface(target)
        if self.sequence_off:
            target.buttons.sequence(target, self.sequence_off)

    def get(self, target, _component):
        # no real press status, so can't tell
        return None

    
class buttons_released_pc(ttbl.power.impl_c):
    """
    Power control implementation that ensures a list of buttons
    are released (not pressed) before powering on a target.
    """
    def __init__(self, button_list):
        assert isinstance(button_list, list)
        ttbl.power.impl_c.__init__(self)
        self.sequence = [ ( 'release', button )
                          for button in button_list ]

    def on(self, target, _component):
        _check_iface(target)
        target.buttons.sequence(target, self.sequence)

    def off(self, target, _component):
        pass
        
    def get(self, target, _component):
        # no real press status, so can't tell
        return None
