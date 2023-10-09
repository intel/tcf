#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to manage targets that support Android fasboot
------------------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list acceptable commands::

    $ tcf fastboot-ls TARGETSPEC

- run a command::

    $ tcf fastboot TARGETSPEC COMMANDNAME [COMMANDARGS]

"""

import argparse
import logging

import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_fastboot")



def _fastboot_ls(target: tcfl.tc.target_c):
    r = target.fastboot.list()
    for command, params in r.items():
        print(f"{target.id}: {command}: {params}")

def _cmdline_fastboot_ls(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _fastboot_ls, cli_args,
        only_one = True,
        iface = "fastboot", extensions_only = [ "fastboot" ])
    return retval



def _fastboot(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: running command %s",
                target.fullid, cli_args.command_name)
    r = target.fastboot.run(cli_args.command_name, *cli_args.parameters)
    logger.warning("%s: ran command %s: %s",
                   target.fullid, cli_args.command_name, r)

def _cmdline_fastboot(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _fastboot, cli_args, cli_args,
        iface = "fastboot", extensions_only = [ "fastboot" ])
    return retval



def cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "fastboot-ls",
        help = "List allowed fastboot commands")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_fastboot_ls)

    ap = arg_subparser.add_parser(
        "fastboot",
        help = "Run a fastboot command")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "command_name", metavar = "COMMAND", action = "store",
        type = str, help = "Name of the command to run")
    ap.add_argument(
        "parameters", metavar = "PARAMETERS", action = "store",
        nargs = "*", default = [],
        help = "Parameters to the fastboot command")
    ap.set_defaults(func = _cmdline_fastboot)
