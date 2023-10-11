#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to manage targets that can be connected to other targets
----------------------------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list things that can be connected to each target::

    $ tcf thing-ls TARGETSPEC

- report plug state of a single thing::

    $ tcf thing-ls TARGETSPEC

"""

import argparse
import logging

import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_things")


def _thing_ls(target: tcfl.tc.target_c):

    r = target.things.list()
    for thing, state in r['result'].items():
        if state == True:
            _state = 'plugged'
        elif state == False:
            _state = 'unplugged'
        elif state == None:
            _state = "n/a (need to acquire targets)"
        else:
            _state = "BUG:unknown-state"
        print(f"{thing}: {_state}")

def _cmdline_thing_ls(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _thing_ls, cli_args,
        only_one = True,
        iface = "things", extensions_only = [ "things" ])
    return retval



def _thing_get(target: tcfl.tc.target_c, thing: str):
    r = target.things.get(thing)
    print(f"{target.id}: {'plugged' if r == True else 'unplugged'}")

def _cmdline_thing_get(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _thing_get, cli_args, cli_args.thing,
        only_one = True,
        iface = "things", extensions_only = [ "things" ])
    return retval



def _thing_plug(target: tcfl.tc.target_c, thing: str):
    target.things.plug(thing)

def _cmdline_thing_plug(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _thing_plug, cli_args, cli_args.thing,
        only_one = True,
        iface = "things", extensions_only = [ "things" ])
    return retval



def _thing_unplug(target: tcfl.tc.target_c, thing: str):
    target.things.unplug(thing)

def _cmdline_thing_unplug(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _thing_unplug, cli_args, cli_args.thing,
        only_one = True,
        iface = "things", extensions_only = [ "things" ])
    return retval



def cmdline_setup_intermediate(arg_subparser):

    ap = arg_subparser.add_parser(
        "thing-ls",
        help = "List plugged and unplugged things")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_thing_ls)

    ap = arg_subparser.add_parser(
        "thing-get",
        help = "Return current thing's state")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "thing", metavar = "THING", action = "store",
        default = None,
        help = "Name of thing to query state about")
    ap.set_defaults(func = _cmdline_thing_get)

    ap = arg_subparser.add_parser(
        "thing-plug",
        help = "Plug a thing to a target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "thing", metavar = "THING", action = "store",
        default = None,
        help = "Name of the thing to plug")
    ap.set_defaults(func = _cmdline_thing_plug)

    ap = arg_subparser.add_parser(
        "thing-unplug",
        help = "Unplug a thing from a target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "thing", metavar = "THING", action = "store",
        default = None,
        help = "Name of the thing to unplug")
    ap.set_defaults(func = _cmdline_thing_unplug)
