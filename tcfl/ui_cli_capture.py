#! /usr/bin/env python3
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
import os
import sys
import time

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

    retval, _ = tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture_ls, cli_args, verbosity,
        only_one = True,
        iface = "capture", extensions_only = [ "capture" ])
    return retval



def _capture_stop(target: tcfl.tc.target_c, capturer: str):
    return target.capture.stop(capturer)


def _cmdline_capture_stop(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    retval, r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture_stop, cli_args, cli_args.capturer,
        iface = "capture", extensions_only = [ "capture" ])

    # r is keyed by { TARGET: { STREAMNAME: FILENAME } }
    if verbosity == 0 or verbosity == 1:
        import tabulate
        headers = [
            "Target",
            "Stream",
            "Filename",
        ]
        table = []
        for targetid, ( data, _e, _tb ) in list(r.items()):
            for stream, filename in data.items():
                table.append([ targetid, stream, filename ])
        print(tabulate.tabulate(table, headers = headers))
        return retval

    if verbosity == 2:
        commonl.data_dump_recursive(r)
    elif verbosity == 3:
        import pprint
        pprint.pprint(r, indent = True)
    elif verbosity >= 4:
        import json
        json.dump(r, sys.stdout, indent = True)
    return retval


def _capture_start(target: tcfl.tc.target_c, capturer: str):
    return target.capture.start(capturer)


def _cmdline_capture_start(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    retval, r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture_start, cli_args, cli_args.capturer,
        iface = "capture", extensions_only = [ "capture" ])

    # r is keyed by { TARGET: { STREAMNAME: FILENAME } }
    if verbosity == 0 or verbosity == 1:
        import tabulate
        headers = [
            "Target",
            "Capturing",
            "Stream",
            "Filename",
        ]
        table = []
        for targetid, ( data, _e, _tb ) in list(r.items()):
            if not data:
                continue
            capturing = False
            for stream, filename in data.items():
                if stream == "capturing":	# special case
                    capturing = filename
                    continue
                table.append([ targetid, capturing, stream, filename ])
        print(tabulate.tabulate(table, headers = headers))
        return retval

    if verbosity == 2:
        commonl.data_dump_recursive(r)
    elif verbosity == 3:
        import pprint
        pprint.pprint(r, indent = True)
    elif verbosity >= 4:
        import json
        json.dump(r, sys.stdout, indent = True)
    return retval



def _capture_get(target: tcfl.tc.target_c, capturer: str, prefix: str,
                 follow: bool, wait: float):

    if not prefix:
        prefix = target.id + "."

    while True:
        r = target.capture.get(capturer, prefix = prefix, follow = follow)
        for stream_name, file_name in r.items():
            stat_info = os.stat(file_name)
            print(f"{stream_name}: {file_name} [{stat_info.st_size}B]")
        if not follow:
            break
        time.sleep(wait)

    return target.capture.start(capturer)



def _cmdline_capture_get(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    retval, r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture_get, cli_args, cli_args.capturer,
        cli_args.prefix, cli_args.follow, cli_args.wait,
        iface = "capture", extensions_only = [ "capture", "store" ])
    return retval



def _capture(target: tcfl.tc.target_c, cli_args: argparse.Namespace):

    logger = logging.getLogger(f"{target.fullid}/capture")
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    if cli_args.prefix:
        prefix = cli_args.prefix
    else:
        prefix = target.id + "."

    capturers = target.capture.list()
    for capturer in cli_args.capturer:
        if capturer not in target.kws['interfaces'].get('capture', {}):
            raise RuntimeError(f"{capturer}: unknown capturer: {capturers}")

    got_to_wait = False

    # start capturing

    # We might want to parallelize for snapshot taking, since it might
    # be a more resource consuming thing; for streams, start is a
    # quick operations, so we don't really need to.
    for capturer in cli_args.capturer:

        streaming = capturers[capturer]
        if streaming == None:
            # snapshot
            logger.info(f"{capturer}: taking snapshot")
            target.capture.start(capturer)

        elif streaming == False:
            # not snapshot, start, wait, stop, get
            logger.info(f"{capturer}: non-snapshot capturer was stopped, starting")
            target.capture.start(capturer)
            got_to_wait = True

        elif streaming == True:
            # already capturing, do nothing
            logger.info(f"{capturer}: already capturing")
            got_to_wait = True

    if got_to_wait:
        logger.info(f"capturing for {cli_args.wait} seconds")
        time.sleep(cli_args.wait)

    # Stop the capture
    for capturer in cli_args.capturer:
        streaming = capturers[capturer]
        if streaming == None:	# snapshots need no stopping
            continue

        logger.info(f"{capturer}: stopping capture")
        target.capture.stop(capturer)

    # Download the capture

    # We won't gain much by parallelizing because this is downloading
    # from the same server, if it becomes a problem we might do it in
    # the future but for now...meh
    for capturer in cli_args.capturer:
        streaming = capturers[capturer]
        logger.warning(f"{capturer}: downloading capture")
        r = target.capture.get(capturer, prefix = prefix)
        for stream_name, file_name in r.items():
            logger.warning(f"{capturer}: downloaded stream {stream_name} -> {file_name}")


def _cmdline_capture(cli_args: argparse.Namespace):
    cli_args.verbosity += 2	# default to informational messages

    retval, _r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _capture, cli_args, cli_args,
        iface = "capture", extensions_only = [ "capture", "store" ])
    return retval



def cmdline_setup_intermediate(arg_subparser):

    ap = arg_subparser.add_parser(
        "capture-ls",
        help = "List available capturers for each target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_capture_ls)

    ap = arg_subparser.add_parser(
        "capture-start", help = "Start capturing")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "capturer", metavar = "CAPTURER-NAME", action = "store",
        type = str, help = "Name of capturer that should start")
    ap.set_defaults(func = _cmdline_capture_start)

    ap = arg_subparser.add_parser(
        "capture-stop", help = "stop capturing")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "capturer", metavar = "CAPTURER-NAME", action = "store",
        type = str, help = "Name of capturer that should stop")
    ap.set_defaults(func = _cmdline_capture_stop)

    ap = arg_subparser.add_parser(
        "capture-get",
        help = "stop capturing and get the result to a file")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "capturer", metavar = "CAPTURER-NAME", action = "store", type = str,
        help = "Name of capturer whose streams are to be downloaded")
    ap.add_argument(
        "--prefix", action = "store", type = str, default = None,
        help = "Prefix for downloaded files")
    ap.add_argument(
        "--wait", action = "store", metavar = 'SECONDS', type = float,
        default = 2,
        help = "When --follow, time to wait between downloads"
        " [%(default).1f seconds]")
    ap.add_argument(
        "--follow",
        action = "store_true", default = False,
        help = "Read any changes from the last download")
    ap.set_defaults(func = _cmdline_capture_get)

    ap = arg_subparser.add_parser(
        "capture", help = "Generic capture; takes a snapshot or captures"
        " for given SECONDS (default 5) and downloads captured data")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = True, nargs = 1)
    ap.add_argument(
        "capturer", metavar = "CAPTURER-NAME", action = "store", nargs = "+",
        type = str, help = "Name of capturer where to capture from")
    ap.add_argument(
        "--prefix", action = "store", type = str, default = None,
        help = "Prefix for downloaded files")
    ap.add_argument(
        "--wait",
        action = "store", metavar = 'SECONDS', type = float, default = 5,
        help = "How long to wait between starting and stopping")
    ap.add_argument(
        "--stream", action = "append", metavar = 'STREAM-NAME',
        type = str, default = [], nargs = "*",
        help = "Specify stream(s) to download (default all)")
    ap.set_defaults(func = _cmdline_capture)
