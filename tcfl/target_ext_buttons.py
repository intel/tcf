#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Press and release buttons in the target
---------------------------------------

"""
import json
import logging
import re

from . import tc
from . import msgid_c

class extension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to manipulate buttons
    connected to the target.

    Buttons can be pressed, released or a sequence of them (eg: press
    button1, release button2, wait 0.25s, press button 2, wait 1s
    release button1).

    >>> target.button.list()
    >>> target.button.press('button1')
    >>> target.button.release('button2')
    >>> target.button.sequence([
    >>>     ( 'on', 'button1' ),	# press
    >>>     ( 'off', 'button2' ),	# release
    >>>     ( 'wait', 0.25 ),
    >>>     ( 'off', 'button2', ),
    >>>     ( 'wait', 1 ),
    >>>     ( 'off', 'button1' ),
    >>> ])

    Note that for this interface to work, the target has to expose a
    buttons interface and expose said buttons (list them). You can use
    the command line::

      $ tcf button-ls TARGETNAME

    to find the buttons available to a targert and use
    ``button-press``, ``button-release`` and ``button-click`` to
    manipulate from the command line.
    """

    # allows quick setting of the interface name for testing
    iface_name = "buttons"

    def __init__(self, target):
        if not self.iface_name in target.rt.get('interfaces', []):
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

    def _sequence(self, sequence, timeout = None):
        self.target.ttbd_iface_call(self.iface_name, "sequence",
                                    method = "PUT",
                                    sequence = sequence, timeout = timeout)

    def press(self, button_name):
        """
        Press a given button

        :param str button_name: name of the button
        """
        self.target.report_info("%s: pressing" % button_name, dlevel = 1)
        self._sequence([ [ 'on', button_name ] ])
        self.target.report_info("%s: pressed" % button_name)

    def release(self, button_name):
        """
        Release a given button

        :param str button_name: name of the button
        """
        self.target.report_info("%s: releasing" % button_name, dlevel = 1)
        self._sequence([ [ 'off', button_name ] ])
        self.target.report_info("%s: released" % button_name)

    def sequence(self, sequence, timeout = None):
        """
        Run a sequence of events on buttons

        :param str sequence: a list of pairs:

          >>> ( OPERATION, ARGUMENT )

          *OPERATION* is a string that can be:

          - *on*/*press*/*close* or *off*/*release*/*open* to *press*
             *release* a button named ARGUMENT* (another string)

          - *wait*: *ARGUMENT* is a number describing how many seconds
            to wait

        :param float timeout: (optional) maximum seconds to wait
          before giving up; default is whatever calculated based on
          how many *wait* operations are given or if none, whatever
          the default is set in
          :meth:`tcfl.tc.target_c.ttbd_iface_call`.

        """
        self.target.report_info("running sequence: %s" % sequence, dlevel = 1)
        total_wait = 0
        if timeout == None:
            for operation, argument in sequence:
                if operation == "wait":
                    total_wait += float(argument)
        self._sequence(sequence, timeout = 30 + total_wait * 1.5)
        self.target.report_info("ran sequence: %s" % sequence)

    def click(self, button_name, click_time = 0.25):
        """
        Click (press/wait/release) a given button

        :param str button_name: name of the button
        :param float click_time: (seconds) how long to keep the click
        """
        self.target.report_info("clicking: %s for %.02f"
                                % (button_name, click_time), dlevel = 1)
        self._sequence([
            [ 'on', button_name ],
            [ 'wait', click_time ],
            [ 'off', button_name ]
        ])
        self.target.report_info("clicked: %s for %.02f"
                                % (button_name, click_time))

    def double_click(self, button_name,
                     click_time = 0.25, interclick_time = 0.25):
        """
        Double click (press/wait/release/wait/press/wait/release) a
        given button

        :param str button_name: name of the button
        :param float click_time: (seconds) how long to keep the click
        :param float interclick_time: (seconds) how long to wait in
          between clicks
        """
        self.target.report_info("double-clicking: %s for %.02f/%.2fs"
                                % (button_name, click_time, interclick_time),
                                dlevel = 1)
        self._sequence([
            [ 'on', button_name ],
            [ 'wait', click_time ],
            [ 'off', button_name ],
            [ 'wait', interclick_time ],
            [ 'on', button_name ],
            [ 'wait', click_time ],
            [ 'off', button_name ],
        ])
        self.target.report_info("double-clicked: %s for %.02f/%.2fs"
                                % (button_name, click_time, interclick_time))

    def list(self):
        """
        List available buttons and their corresponding state

        :returns: dictionary keyed by button name listing its current state:

          - *True*: pressed
          - *False*: released
          - *None*: unknown / unavailable (might be an error condition)

        """
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call(self.iface_name, "list",
                                        method = "GET")
        self.target.report_info("listed: %s" % r)
        l = {}
        for name, data in r.get('components', {}).items():
            # this will be True/False/None
            l[name] = data.get('state', None)
        return l
