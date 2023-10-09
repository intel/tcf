#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to move files from and to the server's storage area
-----------------------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- List files availables on servers::

    $ tcf store-ls TARGETs

- Upload files to server's user storage area::

    $ tcf store-upload TARGETs REMOTEFILENAME LOCALFILENAME

- Download files from the server's user storage area::

    $ tcf store-dnload TARGETs REMOTEFILENAME LOCALFILENAME

- Remove files from the server's user storage area::

    $ tcf store-rm TARGETs REMOTEFILENAME
"""

import argparse
import logging
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_store")


def _store_ls(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    if not cli_args.filename:
        filename = None
    else:
        filename = cli_args.filename
    r = target.store.list2(
        path = cli_args.path, filenames = filename,
        digest = cli_args.digest)
    return r


def _cmdline_store_ls(cli_args: argparse.Namespace):

    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    retval, r0 =  tcfl.ui_cli.run_fn_on_each_targetspec(
        _store_ls, cli_args, cli_args,
        one_per_server = True,
        iface = "store", extensions_only = [ "store" ])

    # r0 is { TARGETNAME: ( { FILENAME: FIELDS }, EXCEPTION ) }
    # transform to  { SERVER: { FILENAME: FIELDS } }
    r = {}
    for targetid, ( filesdata, exception ) in r0.items():
        if exception or not filesdata:	# yup, we ignore errors (reported
            continue                    # by run_fn_on_each...) and empties
        rt = tcfl.rts_flat[targetid]
        server = rt['server_aka']
        r[server] = filesdata

    if verbosity == 0:
        import tabulate
        table = []
        headers = [
            "Type",
            "Size",
            "Name",
        ]
        if cli_args.digest:
            headers.append(f"Hash ({cli_args.digest})")

        seen = set()		# report only one per server
        for targetid, filesdata in r.items():
            for file_name, file_data in sorted(filesdata.items()):
                if file_name in seen:
                    continue
                seen.add(file_name)
                entry = [
                    file_data.get('type', '-'),
                    file_data.get('size', '-'),
                ]
                if cli_args.digest:
                    entry.append(file_data.get('digest', "-"))
                aliases = file_data.get('aliases', None)
                if aliases:
                    entry.append(file_name + "\n-> " + aliases)
                else:
                    entry.append(file_name)
                table.append(entry)
        table.sort(key = lambda e: e[2])
        if table:
            print(tabulate.tabulate(table, headers = headers))

    elif verbosity == 1:
        import tabulate
        table = []
        headers = [
            "Type",
            "Size",
            "Name",
            "Server",
            "Aliases"
        ]
        if cli_args.digest:
            headers.append(f"Hash ({cli_args.digest})")

        for server_aka, filesdata in r.items():
            for file_name, file_data in sorted(filesdata.items()):
                entry = [
                    file_data.get('type', '-'),
                    file_data.get('size', '-'),
                    file_name,
                    server_aka,
                    file_data.get('aliases', '-'),
                ]
                if cli_args.digest:
                    entry.append(file_data.get('digest', "-"))
                table.append(entry)
        table.sort(key = lambda e: e[2])
        if table:
            print(tabulate.tabulate(table, headers = headers))

    elif verbosity == 2:
        commonl.data_dump_recursive(r)

    elif verbosity == 3:
        import pprint
        pprint.pprint(r)

    elif verbosity >= 4:
        import json
        json.dump(r, sys.stdout, skipkeys = True, indent = 4)
        print()

    return retval



def _store_upload(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: uploading %s -> %s", target.rt['server_aka'],
                cli_args.local_filename, cli_args.remote_filename)
    target.store.upload(cli_args.remote_filename, cli_args.local_filename)
    logger.warning("%s: uploaded %s -> %s", target.rt['server_aka'],
                   cli_args.local_filename, cli_args.remote_filename)

def _cmdline_store_upload(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _r =  tcfl.ui_cli.run_fn_on_each_targetspec(
        _store_upload, cli_args, cli_args,
        one_per_server = True,
        iface = "store", extensions_only = [ "store" ])
    return retval



def _store_rm(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    target.store.delete(cli_args.remote_filename)
    logger.warning("%s: deleted %s", target.rt['server_aka'],
                   cli_args.remote_filename)

def _cmdline_store_rm(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _r =  tcfl.ui_cli.run_fn_on_each_targetspec(
        _store_rm, cli_args, cli_args,
        one_per_server = True,
        iface = "store", extensions_only = [ "store" ])
    return retval



def _store_dnload(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: dpwnloading %s -> %s", target.rt['server_aka'],
                cli_args.remote_filename, cli_args.local_filename)
    target.store.dnload(cli_args.remote_filename, cli_args.local_filename)
    logger.warning("%s: downloaded %s -> %s", target.rt['server_aka'],
                   cli_args.remote_filename, cli_args.local_filename)

def _cmdline_store_dnload(cli_args: argparse.Namespace):
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    retval, _r =  tcfl.ui_cli.run_fn_on_each_targetspec(
        _store_dnload, cli_args, cli_args,
        only_one = True,	# see comments in cmdline_setup_intermediate()
        one_per_server = True,
        iface = "store", extensions_only = [ "store" ])
    return retval



def cmdline_setup_intermediate(argsp):

    ap = argsp.add_parser(
        "store-ls",
        help = "List files stored in the server")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "--path", metavar = "PATH", action = "store",
        default = None, help = "Path to list")
    ap.add_argument(
        "--digest", action = "store",
        default = None, help = "Digest to use"
        " (zero, md5, sha256 [default], sha512)")
    ap.add_argument(
        "filename", nargs = "*", action = "store",
        default = [], help = "Files to list (defaults to all)")
    ap.set_defaults(func = _cmdline_store_ls)

    ap = argsp.add_parser(
        "store-upload",
        help = "Upload a local file to the server")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "remote_filename", action = "store",
        help = "Name of remote file"
        " (note the file will be stored in a user specific area)")
    ap.add_argument(
        "local_filename", action = "store",
        help = "Path to local file to upload")
    ap.set_defaults(func = _cmdline_store_upload)

    ap = argsp.add_parser(
        "store-rm",
        help = "Remove a file from the server")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "remote_filename", action = "store",
        help = "Name of the remote file to remove")
    ap.set_defaults(func = _cmdline_store_rm)

    ap = argsp.add_parser(
        "store-dnload",
        help = "Download a file from the server")
    tcfl.ui_cli.args_verbosity_add(ap)
    # we allow only one target, so that we don't parallelize by
    # mistake and override files with the same name, yadah yadah
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "remote_filename", action = "store",
        help = "Path to remote file in user's storage area")
    ap.add_argument(
        "local_filename", action = "store",
        help = "Filename to which to save the locally")
    ap.set_defaults(func = _cmdline_store_dnload)
