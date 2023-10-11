#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to manage target's debug capabilities
---------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list acceptable commands::

    $ tcf debug-ls TARGETSPEC

- print GDB bridge information::

    $ tcf debug-gdb TARGETSPEC

"""

import argparse
import logging

import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_debug")


def _debug_ls(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    r = target.debug.list(cli_args.component)
    for component, value in r.items():
        if value == None:
            print(component + ": <debugging stopped>")
        elif value == {}:
            print(component + ": <debugging started, target probably off>")
        else:
            print(component + ":",)
            commonl.data_dump_recursive(value)

def _cmdline_debug_ls(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_ls, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_gdb(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    r = target.debug.list(cli_args.component)
    for component, value in r.items():
        # if there is only one component, do not print the
        # component prefix, so we can chain this up to GDB's
        # command line:
        #
        #   (gdb) tcf debug-gdb -c x86 TARGETNAME
        #   tcp:hostname:20049
        #   (gdb) target remote tcp:hostname:20049

        if len(r) == 1:
            prefix = ""
        else:
            prefix = component + ": "
        if value == None:
            print(f"{target.id}:{component}: <debugging is off>")
        elif 'GDB' in value:
            print(f"{target.id}:{component}: {value['GDB']}")
        else:
            print(f"{target.id}:{component}: debugging is on,"
                  " but GDB bridge not available--maybe power on?")

def _cmdline_debug_gdb(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_gdb, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_start(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: starting debug on %s", target.id, cli_args.component)
    target.debug.start(cli_args.component)
    logger.warning("%s: started debug on %s", target.id, cli_args.component)

def _cmdline_debug_start(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_start, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_stop(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: stopping debug on %s", target.id, cli_args.component)
    target.debug.stop(cli_args.component)
    logger.warning("%s: stopped debug on %s", target.id, cli_args.component)

def _cmdline_debug_stop(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_stop, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_halt(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s:%s: halting CPUs", target.id, cli_args.component)
    target.debug.halt(cli_args.component)
    logger.warning("%s:%s: halted CPUs", target.id, cli_args.component)

def _cmdline_debug_halt(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_halt, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_reset(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s:%s: resetting CPUs", target.id, cli_args.component)
    target.debug.reset(cli_args.component)
    logger.warning("%s:%s: reset CPUs", target.id, cli_args.component)

def _cmdline_debug_reset(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_reset, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_reset_halt(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s:%s: resetting and halting CPUs", target.id, cli_args.component)
    target.debug.reset_halt(cli_args.component)
    logger.warning("%s:%s: reset and halted CPUs", target.id, cli_args.component)

def _cmdline_debug_reset_halt(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_reset_halt, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def _debug_resume(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s:%s: resumeing CPUs", target.id, cli_args.component)
    target.debug.resume(cli_args.component)
    logger.warning("%s:%s: resumed CPUs", target.id, cli_args.component)

def _cmdline_debug_resume(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _debug_resume, cli_args, cli_args,
        iface = "debug", extensions_only = [ "debug" ])
    return retval



def cmdline_setup_advanced(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "debug-ls",
        help = "Report debug information on target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "component for which to display info")
    ap.set_defaults(func = _cmdline_debug_ls)

    ap = arg_subparsers.add_parser(
        "debug-gdb",
        help = "Report GDB bridge information on target's components")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "component for which to display info")
    ap.set_defaults(func = _cmdline_debug_gdb)

    ap = arg_subparsers.add_parser(
        "debug-start",
        help = "Start debugging support on target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_start)

    ap = arg_subparsers.add_parser(
        "debug-stop",
        help = "Stop debugging support on target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_stop)

    ap = arg_subparsers.add_parser(
        "debug-halt",
        help = "Halt target's CPUs")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_halt)

    ap = arg_subparsers.add_parser(
        "debug-reset",
        help = "Reset target's CPUs")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_reset)

    ap = arg_subparsers.add_parser(
        "debug-reset-halt",
        help = "Reset and halt target's CPUs")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_reset_halt)

    ap = arg_subparsers.add_parser(
        "debug-resume",
        help = "Resume target's CPUs")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c", "--component",
        action = "append", default = [],
        help = "components on which to operate (defaults to all)")
    ap.set_defaults(func = _cmdline_debug_resume)
