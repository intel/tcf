#! /usr/bin/python
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

from . import tc
from . import ttb_client
from . import msgid_c

class extension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to manipulate buttons
    connected to the target.

    Buttons can be pressed, released or a sequence of them (eg: press
    button1, release button2, wait 0.25s, press button 2, wait 1s
    release button1).

    >>> target.buttons.list()
    >>> target.tunnel.press('button1')
    >>> target.tunnel.release('button2')
    >>> target.tunnel.sequence([
    >>>     ( 'button1', 'press' ),
    >>>     ( 'button2', 'release' ),
    >>>     ( 'wait 1', 0.25 ),
    >>>     ( 'button2', 'press' ),
    >>>     ( 'wait 2', 1 ),
    >>>     ( 'button1', 'release' ),
    >>> ])

    Note that for this interface to work, the target has to expose a
    buttons interface and expose said buttons (list them). You can use
    the command line::

      $ tcf button-list TARGETNAME

    to find the buttons available to a targert and use
    ``button-press``, ``button-release`` and ``button-click`` to
    manipulate from the command line.
    """

    def __init__(self, target):
        if not 'buttons' in target.rt.get('interfaces', []):
            raise self.unneeded

    def _sequence(self, sequence):
        self.target.ttbd_iface_call("buttons", "sequence", method = "PUT",
                                    sequence = sequence)

    def press(self, button_name):
        self.target.report_info("%s: pressing" % button_name, dlevel = 1)
        self._sequence([ [ 'press', button_name ] ])
        self.target.report_info("%s: pressed" % button_name)

    def release(self, button_name):
        self.target.report_info("%s: releasing" % button_name, dlevel = 1)
        self._sequence([ [ 'release', button_name ] ])
        self.target.report_info("%s: released" % button_name)

    def sequence(self, sequence):
        self.target.report_info("running sequence: %s" % sequence, dlevel = 1)
        self._sequence(sequence)
        self.target.report_info("ran sequence: %s" % sequence)

    def click(self, button_name, duration = 0.25):
        self.target.report_info("clicking: %s for %.02f"
                                % (button_name, duration), dlevel = 1)
        self._sequence([
            [ 'press', button_name ],
            [ 'wait', duration ],
            [ 'release', button_name ]
        ])
        self.target.report_info("clicked: %s for %.02f"
                                % (button_name, duration))

    def double_click(self, button_name,
                     duration_click = 0.25, duration_release = 0.25):
        self.target.report_info("double-clicking: %s for %.02f/%.2fs"
                                % (button_name, duration_click,
                                   duration_release),
                                dlevel = 1)
        self._sequence([
            [ 'press', button_name ],
            [ 'wait', duration_click ],
            [ 'release', button_name ],
            [ 'wait', duration_release ],
            [ 'press', button_name ],
            [ 'wait', duration_click ],
            [ 'release', button_name ],
        ])
        self.target.report_info("double-clicked: %s for %.02f/%.2fs"
                                % (button_name, duration_click,
                                   duration_release))

    def list(self):
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call("buttons", "list", method = "GET")
        self.target.report_info("listed: %s" % r['result'])
        return r['result']

        
def _cmdline_button_press(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "buttons")
        target.button.press(args.button_name)

def _cmdline_button_release(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "buttons")
        target.button.release(args.button_name)

def _cmdline_button_click(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "buttons")
        target.button.click(args.button_name, args.click_time)

def _cmdline_button_double_click(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "buttons")
        target.button.double_click(args.button_name,
                                   args.click_time, args.wait_time)

def _cmdline_button_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "buttons")
        data = target.button.list()
        for name, state in data.items():
            if state:
                _state = 'pressed'
            else:
                _state = 'released'
            print(name + ": " + _state)

def _cmdline_setup(argsp):
    ap = argsp.add_parser("button-press", help = "press a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button")
    ap.set_defaults(func = _cmdline_button_press)

    ap = argsp.add_parser("button-release", help = "release a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button")
    ap.set_defaults(func = _cmdline_button_release)

    ap = argsp.add_parser("button-click", help = "click a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button")
    ap.add_argument("-c", "--click-time", metavar = "CLICK-TIME",
                    action = "store", type = float, default = 0.25,
                    help = "Seconds to click for (%(default).2fs)")
    ap.set_defaults(func = _cmdline_button_click)

    ap = argsp.add_parser("button-double-click",
                          help = "double-click a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button")
    ap.add_argument("-c", "--click-time", metavar = "CLICK-TIME",
                    action = "store", type = float, default = 0.25,
                    help = "Seconds to click for (%(default).2fs)")
    ap.add_argument("-w", "--wait-time", metavar = "WAIT-TIME",
                    action = "store", type = float, default = 0.25,
                    help = "Seconds to wait between clicks (%(default).2fs)")
    ap.set_defaults(func = _cmdline_button_double_click)

    ap = argsp.add_parser("button-list", help = "List available buttons")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = _cmdline_button_list)
