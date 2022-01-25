#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to manage targets
import collections
import logging
import os
import sys

import commonl
import tcfl
import tcfl.targets

logger = logging.getLogger("ui_cli_target")


def _rt_get_owner_allocid_power(rt):
    # rt is in most cases the deep one vs the flat one
    powered = rt.get('interfaces', {}).get('power', {}).get('state', False)
    if powered == True:
        # having that attribute means the target is powered; otherwise it
        # is either off or has no power control
        power = " ON"
        power_summary = "!"
    else:
        power = ""
        power_summary = ""
    allocid = rt.get('_alloc', {}).get('id', None)
    owner = rt.get('owner', None)
    if allocid or owner:
        ownerl = []
        if owner:
            ownerl.append(owner)
        if allocid:
            ownerl.append(allocid)
        owner_s = "[" + ":".join(ownerl) + "]"
        owner_summary = "@"
    else:
        owner_s = ""
        owner_summary = ""
    return owner_s, owner_summary, power, power_summary


def _cmdline_ls_table(targetl):
    """
    List all the targets in a table format, appending * if powered
    up, ! if owned.
    """

    import math		# only needed here

    # Collect the targets into a list of tuples (FULLID, SUFFIX),
    # where suffix will be *! (* if powered, ! if owned)

    l = []
    for rt in targetl:
        _owner_s, owner_summary, _power, power_summary = \
            _rt_get_owner_allocid_power(rt)
        l.append(( rt['fullid'], owner_summary + power_summary ))
    if not l:
        return

    # Figure out the max target name length, so from there we can see
    # how many entries we can fit per column. Note that the suffix is
    # max two characters, separated from the target name with a
    # space and we must leave another space for the next column (hence
    # +4).
    ts = os.get_terminal_size()
    display_w = ts.columns

    maxlen = max([len(i[0]) for i in l])
    columns = int(math.floor(display_w / (maxlen + 4)))
    if columns < 1:
        columns = 1
    rows = int((len(l) + columns - 1) / columns)

    # Print'em sorted; filling out columns first -- there might be a
    # more elegant way to do it, but this one is quite simple and I am
    # running on fumes sleep-wise...
    l = sorted(l)
    for row in range(rows):
        for column in range(columns):
            index = rows * column + row
            if index >= len(l):
                break
            i = l[index]
            sys.stdout.write("{fullid:{column_width}} {suffix:2} ".format(
                fullid = i[0], suffix = i[1], column_width = maxlen))
        sys.stdout.write("\n")



def _cmdline_ls(args):
    tcfl.target_c.subsystem_initialize()

    if args.projection:
        # FIXME: not supported
        raise NotImplementedError("--projection not implemented")

    targetl = tcfl.targets.list_by_spec(args.target, args.all)

    verbosity = args.verbosity - args.quietosity
    if verbosity < 0:
        for rt in targetl:
            print(rt['fullid'])

    elif verbosity == 0:
        if sys.stderr.isatty() and sys.stdout.isatty():
            _cmdline_ls_table(targetl)
        else:
            for rt in targetl:
                _owner_s, owner_summary, _power, power_summary = \
                    _rt_get_owner_allocid_power(rt)
                print(f"{rt['fullid']}\t{owner_summary}{power_summary}")

    elif verbosity == 1:		# owner/power deets
        for rt in targetl:
            owner, _owner_summary, power, _power_summary = \
                _rt_get_owner_allocid_power(rt)
            print(f"{rt['fullid']}\t{owner} {power}")

    elif verbosity == 2:		# flat list
        for rt in targetl:
            rt_fullid = rt['fullid']
            rt_flat = tcfl.rts_flat[rt_fullid]
            print(rt_fullid)
            for k, v in sorted(rt_flat.items()):
                if isinstance(v, dict):
                    # a dictionary? don't print it, only print the
                    # header if non empty; the rest of the fiels will
                    # come in subsequent fields
                    if v:
                        print(rt_fullid + "." + k + ":")
                    continue
                print(rt_fullid + "." + k + ": " + str(v))
            #commonl.data_dump_recursive(rt, prefix = rt['fullid'])

    elif verbosity == 3:		# pprint dump
        import pprint
        pprint.pprint(targetl)

    else:				# JSON dump
        import json
        json.dump(targetl, sys.stdout, skipkeys = True, indent = 4)



def _cmdline_target_get(args):
    import json
    tcfl.target_c.subsystem_initialize()
    rt = tcfl.target_c.get_rt_by_id(args.target)
    if args.projection:
        data = { 'projections': json.dumps(args.projection) }
    else:
        data = None
    server = tcfl.server_c.servers[rt['server']]
    # note the raw -> so we can do JSON decoding our own
    r = server.send_request("GET", "targets/" + rt['id'], data = data,
                            raw = True)
    # Keep the order -- even if json spec doesn't contemplate it, we
    # use it so the client can tell (if they want) the order in which
    # for example, power rail components are defined in interfaces.power
    rt = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
    json.dump(rt, sys.stdout, skipkeys = True, indent = 4)


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "ls", help = "List targets; by default, in a terminal, it will "
        "print a multi-column display with '!' next to powered-on targets, "
        "and @ next to owned targets; -v adds more detail)")
    commonl.argparser_add_aka(arg_subparsers, "ls", "list")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase information to display about the targets (-v "
        "adds ownership/power state, -vv summarized tags, -vvv all tags "
        "in Python format, -vvvv all tags in JSON format)")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display; see -v")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "List also disabled targets")
    ap.add_argument(
        "-p", "--projection", action = "append",
        help = "List of fields to return (*? [CHARS] or [!CHARS] supported)"
        " as per python's fnmatch module")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = None,
        help = "Target's names or URLs or a general target specification "
        "which might include values of tags, etc, in single quotes (eg: "
        "'zephyr_board and not type:\"^qemu.*\"'")
    ap.set_defaults(func = _cmdline_ls)

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
