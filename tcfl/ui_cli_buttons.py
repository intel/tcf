#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to manage buttons/relays/jumpers
----------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list buttons / jumpers / relays::

    $ tcf buttons-ls TARGETSPEC

"""

import argparse
import logging
import os
import re
import sys
import time

import commonl
import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_capture")


def _button_ls(target: tcfl.tc.target_c, _verbosity: int):

    r = target.button.list()
    for name, state in r.items():
        if state == True:
            _state = 'pressed'
        elif state == False:
            _state = 'released'
        else:
            _state = 'n/a'
        print(name + ": " + _state)

def _cmdline_button_ls(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_ls, cli_args, verbosity,
        only_one = True,
        # Ugh: note the interfce is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



def _button_press(target: tcfl.tc.target_c, button_name: str):
    logger.info("pressing button %s", button_name)
    target.button.press(button_name)
    logger.warning("pressed button %s", button_name)

def _cmdline_button_press(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_press, cli_args, cli_args.button_name,
        # Ugh: note the interfce is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



def _button_release(target: tcfl.tc.target_c, button_name: str):
    logger.info("releasing button %s", button_name)
    target.button.release(button_name)
    logger.warning("released button %s", button_name)

def _cmdline_button_release(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_release, cli_args, cli_args.button_name,
        # Ugh: note the interfce is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



def _button_click(target: tcfl.tc.target_c, button_name: str,
                  click_time: float):
    logger.info("clicking button %s", button_name)
    target.button.click(button_name, click_time)
    logger.warning("clicked button %s", button_name)

def _cmdline_button_click(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_click, cli_args, cli_args.button_name,
        cli_args.click_time,
        # Ugh: note the interfce is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



def _button_double_click(target: tcfl.tc.target_c, button_name: str,
                         click_time: float, interclick_time: float):
    logger.info("double-clicking button %s", button_name)
    target.button.double_click(button_name, click_time, interclick_time)
    logger.warning("double-clicked button %s", button_name)

def _cmdline_button_double_click(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_double_click, cli_args, cli_args.button_name,
        cli_args.click_time, click_args.interclick_time,
        # Ugh: note the interface is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



# this is a very loose match in the format, so we can easily support
# new functionailities in the server
_sequence_valid_regex = re.compile(
    r"^("
    r"(?P<wait>wait):(?P<time>[\.0-9]+)"
    r"|"
    r"(?P<action>\w+):(?P<component>[ /\w]+)"
    r")$")

def _button_sequence(target: tcfl.tc.target_c, verbosity: int,
                     sequence: list, timeout: int):
    logger.info("running sequence: %s", sequence)
    r = target.button.sequence(sequence, timeout)
    logger.warning("ran sequence: %s: %s", r, sequence)
    return r

def _cmdline_button_sequence(cli_args: argparse.Namespace):
    # do a basic sequence validation
    sequence = []
    total_wait = 0
    for s in cli_args.sequence:
        m = _sequence_valid_regex.match(s)
        if not m:
            raise ValueError("%s: invalid specification, see --help" % s)
        gd = m.groupdict()
        if gd['wait'] == 'wait':
            time_to_wait = float(gd['time'])
            sequence.append(( 'wait', time_to_wait))
            total_wait += time_to_wait
        else:
            sequence.append(( gd['action'], gd['component']))

    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _button_sequence, cli_args, verbosity,
        sequence, cli_args.timeout + 1.5 * total_wait,
        # Ugh: note the interfce is called buttons, but we call the
        # exception button (that missing S)
        iface = "buttons", extensions_only = [ "button" ])
    return retval



def cmdline_setup_intermediate(arg_subparser):

    ap = arg_subparser.add_parser(
        "button-ls",
        help = "List available buttons / relays / jumpers")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_button_ls)

    ap = arg_subparser.add_parser(
        "button-press",
        help = "press a button / turn relay on / short jumper."
        " NOTE! this doesn't release it after--see *click*")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "button_name",
        metavar = "BUTTON-NAME", action = "store",
        type = str, help = "Name of the button / relay / jumper")
    ap.set_defaults(func = _cmdline_button_press)

    ap = arg_subparser.add_parser(
        "button-release",
        help = "release a button / turn relay off / open a jumper")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "button_name",
        metavar = "BUTTON-NAME", action = "store",
        type = str, help = "Name of the button / relay / jumper")
    ap.set_defaults(func = _cmdline_button_release)

    ap = arg_subparser.add_parser(
        "button-click",
        help = "press & release a button / relay / jumper")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-w", "--click-time", metavar = "CLICK-TIME",
        action = "store", type = float, default = 0.25,
        help = "Seconds to click for (%(default).2fs)")
    ap.add_argument(
        "button_name",
        metavar = "BUTTON-NAME", action = "store",
        type = str, help = "Name of the button / relay / jumper")
    ap.set_defaults(func = _cmdline_button_click)

    ap = arg_subparser.add_parser(
        "button-double-click",
        help = "double press & release a button / relay / jumper")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-w", "--click-time", metavar = "CLICK-TIME",
        action = "store", type = float, default = 0.25,
        help = "Seconds to click for (%(default).2fs)")
    ap.add_argument(
        "-i", "--interclick-time", metavar = "WAIT-TIME",
        action = "store", type = float, default = 0.25,
        help = "Seconds to wait between clicks (%(default).2fs)")
    ap.add_argument(
        "button_name",
        metavar = "BUTTON-NAME", action = "store",
        type = str, help = "Name of the button / relay / jumper")
    ap.set_defaults(func = _cmdline_button_double_click)

    ap = arg_subparser.add_parser(
        "button-sequence",
        help = "Execute a button / relay / jumper sequence")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "sequence",
        metavar = "STEP", action = "store", nargs = "+",
        help = "sequence steps (list of {on,off}:{NAME,all}"
        " or wait:SECONDS; *all* means all buttons/jumpers/relays"
        " eg: press:reset press:cmos_clear wait:3"
        " release:cmos_clear release:reset"
    )
    ap.add_argument(
        "-t", "--timeout",
        action = "store", default = 60, type = int,
        help = "timeout in seconds [%(default)d, plus all the waits +50%%]")
    ap.set_defaults(func = _cmdline_button_sequence)
