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

from . import tc
from . import ttb_client
import logging

def _rest_tb_target_button_sequence(rtb, rt, sequence, ticket = ''):
    _sequence = json.dumps(sequence)
    rtb.send_request("POST", "targets/%s/buttons/sequence" % rt['id'],
                     data = { 'sequence': _sequence, 'ticket': ticket })

def _rest_tb_target_buttons_get(rtb, rt, ticket = ''):
    return rtb.send_request("GET", "targets/%s/buttons/get" % rt['id'],
                            data = { 'ticket': ticket })

class buttons(tc.target_extension_c):
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

    def press(self, button_name):
        self.target.report_info("%s: pressing" % button_name, dlevel = 1)
        _rest_tb_target_button_sequence(self.target.rtb, self.target.rt,
                                        [ [ button_name, 'press' ] ],
                                        ticket = self.target.ticket)
        self.target.report_info("%s: pressed" % button_name)

    def release(self, button_name):
        self.target.report_info("%s: releasing" % button_name, dlevel = 1)
        _rest_tb_target_button_sequence(self.target.rtb, self.target.rt,
                                        [ [ button_name, 'release' ] ],
                                        ticket = self.target.ticket)
        self.target.report_info("%s: released" % button_name)

    def sequence(self, sequence):
        self.target.report_info("running sequence: %s" % sequence, dlevel = 1)
        _rest_tb_target_button_sequence(self.target.rtb, self.target.rt,
                                        sequence, ticket = self.target.ticket)
        self.target.report_info("ran sequence: %s" % sequence)

    def click(self, button_name, duration = 1):
        self.target.report_info("clicking: %s for %.02f"
                                % (button_name, duration), dlevel = 1)
        _rest_tb_target_button_sequence(self.target.rtb, self.target.rt,
                                        [
                                            ( button_name, 'press' ),
                                            ( button_name, duration ),
                                            ( button_name, 'release' ),
                                        ],
                                        ticket = self.target.ticket)
        self.target.report_info("clicked: %s for %.02f"
                                % (button_name, duration))

    def double_click(self, button_name,
                     duration_click = 0.25, duration_release = 0.25):
        self.target.report_info("clicking: %s for %.02f"
                                % (button_name, duration), dlevel = 1)
        _rest_tb_target_button_sequence(self.target.rtb, self.target.rt,
                                        [
                                            ( button_name, 'press' ),
                                            ( button_name, duration_click ),
                                            ( button_name, 'release' )
                                        ( button_name, duration_release ),
                                            ( button_name, 'press' )
                                            ( button_name, duration_click ),
                                            ( button_name, 'release' )
                                        ],
                                        ticket = self.target.ticket)
        self.target.report_info("clicked: %s for %.02f"
                                % (button_name, duration))

    def list(self):
        self.target.report_info("listing", dlevel = 1)
        data = _rest_tb_target_buttons_get(self.target.rtb, self.target.rt,
                                              ticket = self.target.ticket)
        self.target.report_info("listed: %s" % buttons)
        return data['buttons']

        
def cmdline_button_press(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    _rest_tb_target_button_sequence(rtb, rt,
                                    [ [ args.button_name, 'press' ] ],
                                    ticket = args.ticket)

def cmdline_button_release(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    _rest_tb_target_button_sequence(rtb, rt,
                                    [ [ args.button_name, 'release' ] ],
                                    ticket = args.ticket)

def cmdline_button_click(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    _rest_tb_target_button_sequence(rtb, rt,
                                    [
                                        ( args.button_name, 'press' ),
                                        ( args.button_name, args.click_time ),
                                        ( args.button_name, 'release' ),
                                    ],
                                    ticket = args.ticket)

def cmdline_button_list(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    data = _rest_tb_target_buttons_get(rtb, rt, ticket = args.ticket)
    for name, state in data['buttons'].items():
        if state:
            _state = 'pressed'
        else:
            _state = 'released'
        print("%s:%s" % (name, _state))


def cmdline_setup(argsp):
    ap = argsp.add_parser("button-press", help = "press a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button to press")
    ap.set_defaults(func = cmdline_button_press)

    ap = argsp.add_parser("button-release", help = "release a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button to release")
    ap.set_defaults(func = cmdline_button_release)

    ap = argsp.add_parser("button-click", help = "click a button")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("button_name", metavar = "BUTTON-NAME", action = "store",
                    type = str, help = "Name of the button to release")
    ap.add_argument("click_time", metavar = "CLICK-TIME", action = "store",
                    type = float, default = 0.25, nargs = "?",
                    help = "Seconds to click for")
    ap.set_defaults(func = cmdline_button_click)

    ap = argsp.add_parser("button-list", help = "List available buttons")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = cmdline_button_list)
