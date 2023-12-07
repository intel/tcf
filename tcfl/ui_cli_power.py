#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME: once ensured this support is stabilized, this module will be
#        moved to tcfl/ui_cli_power.py, removing the implementations
#        from tcfl.target_ext_power
"""
Command line interface UI to to manage target power
---------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- power on/off/cycle targets::

    $ tcf power-on [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-off [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-cycle [TARGETSPEC [TARGETSPEC [..]]

- get power state::

    $ tcf power-get [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-ls [TARGETSPEC [TARGETSPEC [..]]


"""

import argparse
import json
import logging
import re
import sys

import commonl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_power")

# note in all these functions we pass the cli_args to
# tcfl.ui_cli.run_fn_on_each_targetspec() twice; one for it to use it,
# the ther one for _power_on_by_*() to use it.

def _cmdline_power_on(cli_args: argparse.Namespace):

    def _power_on_by_target(target, cli_args):
        component =  f" {cli_args.component}" if cli_args.component else ""
        logger.warning(f"{target.id}: powering on {component}")
        target.power.on(component = cli_args.component,
                        explicit = cli_args.explicit)
        logger.warning(f"{target.id}: powered on {component}")
        return 0

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_on_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])[0]



def _cmdline_power_off(cli_args: argparse.Namespace):

    def _power_off_by_target(target, cli_args):
        component =  f" {cli_args.component}" if cli_args.component else ""
        logger.warning(f"{target.id}: powering off {component}")
        target.power.off(component = cli_args.component,
                         explicit = cli_args.explicit)
        logger.warning(f"{target.id}: powered off {component}")
        return 0

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_off_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])[0]



def _cmdline_power_cycle(cli_args: argparse.Namespace):

    def _power_cycle_by_target(target, cli_args):
        component =  f" {cli_args.component}" if cli_args.component else ""
        logger.warning(f"{target.id}: power cycling {component}")
        target.power.cycle(component = cli_args.component,
                           explicit = cli_args.explicit)
        logger.warning(f"{target.id}: power cycled {component}")
        return 0

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_cycle_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])[0]


# this is a very loose match in the format, so we can easily support
# new functionailities in the server
_sequence_valid_regex = re.compile(
    r"^("
    r"(?P<wait>wait):(?P<time>[\.0-9]+)"
    r"|"
    r"(?P<action>\w+):(?P<component>[ /\w]+)"
    r")$")

def _cmdline_power_sequence(cli_args: argparse.Namespace):

    def _power_sequence_by_target(target, cli_args):
        sequence = []
        total_wait = 0
        for s in cli_args.sequence:
            m = _sequence_valid_regex.match(s)
            if not m:
                raise ValueError(f"{s}: invalid specification, see --help")
            gd = m.groupdict()
            if gd['wait'] == 'wait':
                time_to_wait = float(gd['time'])
                sequence.append(( 'wait', time_to_wait))
                total_wait += time_to_wait
            else:
                sequence.append(( gd['action'], gd['component']))
        logger.warning(f"{target.id}: power sequencing {sequence}")
        target.power.sequence(
            sequence, timeout = cli_args.timeout + 1.5 * total_wait)
        logger.warning(f"{target.id}: power sequenced {sequence}")
        return 0

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_sequence_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])[0]



def _cmdline_power_get(cli_args: argparse.Namespace):

    def _power_get_by_target(target, _cli_args):
        r = target.power.get()
        # this we can put it here, it won't race with others since
        # line output is buffered
        print(f"{target.id}: {'on' if r == True else 'off'}")
        sys.stdout.flush()

    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_get_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])
    return retval


def _power_list_by_target(target, cli_args):
    state, substate, components = target.power.list()

    def _state_to_str(state):
        if state == True:
            return 'on'
        if state == False:
            return 'off'
        if state == None:
            return "n/a"
        return "BUG:unknown-state"

    verbosity = cli_args.verbosity - cli_args.quietosity
    if verbosity < 2:
        _state = _state_to_str(state)
        print(f"{target.id}: overall: {_state} ({substate})")
        for component, data in components.items():
            state = data['state']
            explicit = data.get('explicit', None)
            _state = _state_to_str(state)
            if explicit and verbosity == 0:
                continue
            if not explicit:
                explicit = ""
            else:
                explicit = " (explicit/" + explicit + ")"
            print(f"  {component}: {_state}{explicit}")

    elif verbosity == 2:
        r = dict(state = state, substate = substate,
                 components = components)
        commonl.data_dump_recursive(r, prefix = target.id)

    else:  # verbosity >= 2:
        r = { target.id: dict(state = state, substate = substate,
                              components = components) }
        json.dump(r, sys.stdout, skipkeys = True, indent = 4)
        print(",")
    sys.stdout.flush()


def _cmdline_power_list(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _power_list_by_target, cli_args, cli_args,
        iface = "power", extensions_only = [ 'power' ])[0]



def _cmdline_setup(arg_subparser):

    ap = arg_subparser.add_parser(
        "power-on",
        help = "Power on target's power rail (or individual components)")
    ap.add_argument(
        "--component", "-c",
        metavar = "COMPONENT", action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components; "
        " explicit components are only powered on if"
        " --explicit is given or if they are explicitly selected"
        " with --component")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_power_on)

    ap = arg_subparser.add_parser(
        "power-off",
        help = "Power off target's power rail (or individual components)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "--component", "-c", metavar = "COMPONENT",
        action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components; "
        " explicit components are only powered off if"
        " --explicit is given or if they are explicitly selected"
        " with --component")
    ap.set_defaults(func = _cmdline_power_off)

    ap = arg_subparser.add_parser(
        "power-cycle",
        help = "Power cycle target's power rail (or individual components)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components;  explicit"
        " components are only power cycled if --explicit is given or"
        " if they are explicitly selected with --component")
    ap.add_argument(
        "-w", "--wait",
        metavar = "SECONDS", action = "store", default = None,
        help = "How long to wait between power off and power on;"
        " default to server configuration")
    ap.add_argument(
        "--component", "-c", metavar = "COMPONENT",
        action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.set_defaults(func = _cmdline_power_cycle)

    ap = arg_subparser.add_parser(
        "power-sequence",
        help = "Execute a power sequence")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "sequence",
        metavar = "STEP", action = "store", nargs = "+",
        help = "sequence steps (list {on,off,cycle}:{COMPONENT,all,full}"
        " or wait:SECONDS; *all* means all components except explicit ones,"
        " *full* means all components including explicit ones")
    ap.add_argument("-t", "--timeout",
                    action = "store", default = 60, type = int,
                    help = "timeout in seconds [%(default)d, plus "
                    " all the waits +50%%]")
    ap.set_defaults(func = _cmdline_power_sequence)

    ap = arg_subparser.add_parser(
        "power-ls",
        help = "List power rail components and their state"
        "; increase verbosity of information to display "
        "(default displays state of non-explicit components,"
        " -v adds component flags and lists explicit components,"
        " -vv python dictionary, -vvv JSON format)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_power_list)

    ap = arg_subparser.add_parser(
        "power-get",
        help = "Print target's power state."
        "A target is considered *on* when all of its power rail"
        "components are on; fake power components report power state as"
        "*n/a* and those are not taken into account.")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_power_get)
