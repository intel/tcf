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

- list serial consoles:

    $ tcf console-ls TARGETSPEC

"""

import argparse
import logging

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
