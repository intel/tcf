#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to manage targets
import collections
import json
import logging
import sys

import tcfl

logger = logging.getLogger("ui_cli_target")

def _cmdline_target_get(args):
    tcfl.target_c.subsystem_initialize()
    rt = tcfl.target_c.get_rt_by_id(args.target)
    if args.projection:
        data = { 'projections': json.dumps(args.projection) }
    else:
        data = None
    server = tcfl.server_c.servers[rt['server']]
    # note the raw -> so we can do JSON decoding our own
    r = server.send_request("GET", "targets/" + rt['id'], json = data,
                            raw = True)
    # Keep the order -- even if json spec doesn't contemplate it, we
    # use it so the client can tell (if they want) the order in which
    # for example, power rail components are defined in interfaces.power
    rt = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
    json.dump(rt, sys.stdout, skipkeys = True, indent = 4)


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "get", help = "Return target information straight from the "
        "server formated as JSON (unlike 'ls', which will add some "
        "client fields)")
    ap.add_argument(
        "-p", "--projection", action = "append",
        help = "List of fields to return (*? [CHARS] or [!CHARS] supported)"
        " as per python's fnmatch module")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.set_defaults(func = _cmdline_target_get)
