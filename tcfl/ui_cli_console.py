#! /usr/bin/python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage tunnels to targets
---------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list serial consoles::

    $ tcf console-ls TARGETSPEC

- setup serial console::

    $ tcf console-setup [-c CONSOLENAME] TARGETSPEC VAR=VALUE [VAR=VALUE [...]]

  reset settings::

    $ tcf console-setup [-c CONSOLENAME] --reset TARGETSPEC

  print current settings::

    $ tcf console-setup [-c CONSOLENAME] TARGETSPEC [-v[v[v[v]]]]


"""

import argparse
import logging
import sys

import commonl
import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_console")


def _console_ls(target):
    for console in target.console.list():
        if console in target.console.aliases:
            real_name = "|" + target.console.aliases[console]
        else:
            real_name = ""
        size = target.console.size(console)
        if size != None:
            print("%s%s: %d" % (console, real_name, size))
        else:
            print("%s%s: disabled" % (console, real_name))


def _cmdline_console_ls(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_ls, cli_args,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_disable(target, console):
    target.console.disable(console)

def _cmdline_console_disable(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_disable, cli_args, cli_args.console,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_enable(target, console):
    target.console.enable(console)

def _cmdline_console_enable(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_enable, cli_args, cli_args.console,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_setup(target, console: str, reset: bool, cli_parameters,
                   verbosity: int):

    if reset:
        logger.info("%s: reseting settings for console %s",
                    target.id, console)
        r = target.console.setup(console)

    elif cli_parameters == []:
        logger.info("%s: getting settings for console %s",
                    target.id, console)
        r = target.console.setup_get(console)

        if verbosity in ( 0, 1 ):
            for key, value in r.items():
                print(f"{key}: {value}")
        elif verbosity == 2:
            commonl.data_dump_recursive(r)
        elif verbosity == 3:
            import pprint		# pylint: disable = import-outside-toplevel
            pprint.pprint(r, indent = True)
        elif verbosity > 3:
            import json		# pylint: disable = import-outside-toplevel
            json.dump(r, sys.stdout, skipkeys = True, indent = 4)
            print()

        r = 0

    else:
        import pprint
        parameters = {}
        for parameter in cli_parameters:
            if '=' in parameter:
                key, value = parameter.split("=", 1)
                value = commonl.cmdline_str_to_value(value)
            else:
                key = parameter
                value = True
            parameters[key] = value
        logger.info("%s: applying settings for console %s: %s",
                    target.id, console, pprint.pformat(parameters))
        target.console.setup(console, **parameters)

    return 0


def _cmdline_console_setup(cli_args: argparse.Namespace):

    verbosity = cli_args.verbosity - cli_args.quietosity

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_setup, cli_args,
        cli_args.console, cli_args.reset, cli_args.parameters, verbosity,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser(
        "console-ls",
        help = "list consoles this target exposes")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_console_ls)



def _cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "console-disable",
        help = "Disable a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to disable")
    ap.set_defaults(func = _cmdline_console_disable)

    ap = arg_subparser.add_parser(
        "console-enable",
        help = "Enable a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to enable")
    ap.set_defaults(func = _cmdline_console_enable)

    ap = arg_subparser.add_parser(
        "console-setup",
        help = "Setup a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to setup (default console if not specified")
    ap.add_argument(
        "--reset", "-r",
        action = "store_true", default = False,
        help = "reset to default values")
    ap.add_argument(
        "parameters", metavar = "KEY=[TYPE:]VALUE", nargs = "*",
        help = "Parameters to set in KEY=[TYPE:]VALUE format; "
        "TYPE can be b(ool), i(nteger), f(loat), s(string), "
        " defaulting to string if not specified")
    ap.set_defaults(func = _cmdline_console_setup)
