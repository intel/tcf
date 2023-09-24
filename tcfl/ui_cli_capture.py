#! /usr/bin/python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to capture data from targets
------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list capturers::

    $ tcf capture-ls TARGETSPEC

"""

import argparse
import logging
import sys

import commonl
import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_capture")


def _capture_ls(target: tcfl.tc.target_c, verbosity: int):
    state_to_str = {
        False: "not capturing",
        True: "capturing",
        None: "ready"
    }
    capturers_data = target.capture._capturers_data_get()
    capturers = target.capture.list()

    if verbosity == 0:
        import tabulate
        headers = [
            "Capturer",
            "State",
            "Streams",
        ]
        table = []
        for name, state in capturers.items():
            streams = capturers_data[name].get('stream', {})
            l = [
                name + ":" + data.get('mimetype', "mimetype-n/a")
                for name, data in streams.items()
            ]
            table.append([ name, state_to_str[state], " ".join(sorted(l)) ])
        print(tabulate.tabulate(table, headers = headers))
        return

    if verbosity == 1:

        for name, state in capturers.items():
            streams = capturers_data[name].get('stream', {})
            l = [
                name + ":" + data.get('mimetype', "mimetype-n/a")
                for name, data in streams.items()
            ]
            print(f"{name} ({state_to_str[state]}): {' '.join(sorted(l))}")
        return

    # for 2 or 3 we use a dict, so just create it
    d = {}
    for name, state in capturers.items():
        d['name'] = {
            'state': state_to_str[state],
            'stream': capturers_data[name].get('stream', {}),
        }
    print(verbosity)
    if verbosity == 2:
        commonl.data_dump_recursive(d)
    elif verbosity == 3:
        import pprint
        pprint.pprint(d, indent = True)
    elif verbosity >=4:
        import json
        json.dump(d, sys.stdout, skipkeys = True, indent = True)



def _cmdline_capture_ls(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture_ls, cli_args, verbosity,
        only_one = True,
        iface = "capture", extensions_only = [ "capture" ])



def cmdline_setup_intermediate(arg_subparser):

    ap = arg_subparser.add_parser(
        "capture-ls",
        help = "List available capturers for each target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_capture_ls)
