#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command line interface UI to discover targets
---------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- find testcases on PATHs or files::

    $ tcf ls2
    $ tcf ls2 [TARGETNAME...] [TARGETSPEC...]


"""

import argparse
import collections
import json
import logging
import math
import os
import sys

import commonl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_testcases")


def _cmdline_targets_init(args):
    # initialize reporting based on what the commandline wants

    # late imports, only if needed
    import tcfl.tc	# FIXME: move report_driver_c -> tcfl to remove include hell
    import tcfl.report_console
    import tcfl.report_jinja2

    # add reporters for logging, so if we find issues when importing
    # we'll see detailed data logged
    tcfl.tc.report_driver_c.add(
        tcfl.report_console.driver(args.verbosity - args.quietosity),
        name = "console")
    # report file writer, so we get details
    tcfl.tc.report_driver_c.add(
        tcfl.report_jinja2.driver(args.log_dir),
        name = "jinja2")



def _cmdline_target_get(cli_args: argparse.Namespace):

    def _target_get(target, _cli_args):
        projections = cli_args.project
        server = tcfl.server_c.servers[target.rt['server']]
        rt = server.targets_get(target_id = target.id,
                                projections = cli_args.project)
        # rt is a list of dicts keyed by fullid, we care only for the first
        json.dump(rt[0][target.fullid], sys.stdout, indent = 4)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        # note we scan ignoring --projections, since that we'll use
        # later; we want to identify the target to get as soon as
        # possible and then in _target_get() we do the stuff
        _target_get, cli_args, only_one = True)



def _targets_list_v0_table(l):

    if not l:		# avoid divide by zero errors
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
    columns = max(columns, 1)
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



def _targets_list_make_v01(tda, verbosity):

    # List all the targets in a table format, appending * if powered
    # up, ! if owned.

    # Collect the targets into a list of tuples (FULLID, SUFFIX),
    # where suffix will be ! if powered, ! if owned.

    l = []
    for rtfullid in tda.rts_fullid_sorted:
        rt = tda.rts_flat[rtfullid]
        suffix = ""
        owner = rt.get('owner', None)
        allocid = rt.get('_alloc', {}).get('id', None)
        if owner:
            # target might declare no owner
            if verbosity >= 1:
                ownerl = []
                if owner:
                    ownerl.append(owner)
                if allocid:
                    ownerl.append(allocid)
                suffix += "[" + ":".join(ownerl) + "] "
                # note the trailing space
            else:
                suffix += "@"
        power = rt.get('interfaces.power.state', False)
        if power:
            # having that attribute means the target is powered;
            # otherwise it is either off or has no power control
            if verbosity >= 1:
                suffix += "ON"
            else:
                suffix += "!"
        l.append(( rtfullid, suffix ))
    return l



def _targets_print_v0(tda):
    # print just target IDs and if owned/powered; as a table if
    # interactive (to a tty), a one-per-line item if a pipe

    l = _targets_list_make_v01(tda, 0)
    if not sys.stderr.isatty() or not sys.stdout.isatty():
        for fullid, suffix in l:
            print(fullid, "\t", suffix)
    else:
        _targets_list_v0_table(l)



def _targets_print_v1(tda):
    # print just target IDs, owner and if powered

    l = _targets_list_make_v01(tda, 1)
    for fullid, suffix in l:
        print(fullid, "\t", suffix)



def _cmdline_ls(cli_args):

    import tcfl.targets

    verbosity = cli_args.verbosity - cli_args.quietosity

    if cli_args.project == None:
        if verbosity >= 1:
	    # we want verbosity, no fields were specified, so ask for
            # all fields (None); makes no sense with verbosity <=1, since it
            # only prints ID, owner
            cli_args.project = None
        else:
            cli_args.project = { 'id', 'disabled' }
    else:
        cli_args.project = set(cli_args.project)   # to help avoid dups

    # ensure the most basic fields for each verbosity level are queried
    if cli_args.project and verbosity < 1:
        cli_args.project.add('id')
        cli_args.project.add('disabled')
    if cli_args.project and verbosity > 0:
        cli_args.project.add('interfaces.power.state')
        cli_args.project.add('owner')

    tcfl.targets.setup_by_spec(
        cli_args.target, verbosity = verbosity,
        project = cli_args.project, targets_all = cli_args.all)

    if verbosity < 0:
        print(" \n".join(tcfl.targets.discovery_agent.rts_fullid_sorted))
    elif verbosity == 0:
        _targets_print_v0(tcfl.targets.discovery_agent)
    elif verbosity == 1:
        _targets_print_v1(tcfl.targets.discovery_agent)
    elif verbosity == 2:
        for rtfullid in tcfl.targets.discovery_agent.rts_fullid_sorted:
            rt = tcfl.targets.discovery_agent.rts_flat[rtfullid]
            print(rt['fullid'])
            commonl.data_dump_recursive(rt, prefix = rt['fullid'])
    elif verbosity == 3:	# late import, only when needed
        import pprint		# pylint: disable = import-outside-toplevel
        pprint.pprint(tcfl.targets.discovery_agent.rts, indent = True)
    elif verbosity > 3:		# late import, only when needed
        import json		# pylint: disable = import-outside-toplevel
        json.dump(tcfl.targets.discovery_agent.rts,
                  sys.stdout, skipkeys = True, indent = 4)



def _target_patch(target, cli_args):
    # set data
    data = collections.OrderedDict()	# respect user's order
    for data_s in cli_args.data:
        if not "=" in data_s:
            raise AssertionError(
                "data specification has to be in the format KEY=JSON-DATA;"
                " got (%s) %s" % (type(data_s), data_s))
        k, v = data_s.split("=", 1)
        data[k] = v
    server = tcfl.server_c.servers[target.rt['server']]
    if data:
        server.send_request("PATCH", "targets/" + target.id, json = data)
    else:
        # JSON from stdin
        server.send_request("PATCH", "targets/" + target.id,
                            json = json.load(sys.stdin))


def _cmdline_target_patch(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_patch, cli_args, only_one = True)



def _target_enable(target, _cli_args):
    target.enable()

def _cmdline_target_enable(cli_args: argparse.Namespace):

    # force seeing all targets, will ease confusion, since normally we
    # want to enable disabled targets
    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_enable, cli_args, targets_all = True)



def _target_disable(target, cli_args):
    target.disable(cli_args.reason)

def _cmdline_target_disable(cli_args: argparse.Namespace):

    # force seeing all targets, will ease confusion, in case we run the
    # command twice (trying to disable a disabled target shall just work)
    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_disable, cli_args, targets_all = True)



def _target_property_set(target, cli_args):
    value = commonl.cmdline_str_to_value(cli_args.value)
    target.property_set(cli_args.property, value)

def _cmdline_target_property_set(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_property_set, cli_args, only_one = True)



def _target_property_get(target, cli_args):
    r = target.property_get(cli_args.property)
    if r:	# print nothing if None
        print(r)

def _cmdline_target_property_get(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_property_get, cli_args, only_one = True)



def _cmdline_setup(arg_subparsers):

    import tcfl.ui_cli

    ap = arg_subparsers.add_parser(
        f"ls{tcfl.ui_cli.commands_new_suffix}",
        help = "List targets by name or search pattern")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-p", "--project", "--projection", metavar = "FIELD",
        action = "append", type = str,
        help = "consider only the given fields "
        "(default depends on verbosity")
    ap.set_defaults(func = _cmdline_ls)



def _cmdline_setup_advanced(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "get", help = "Return target information straight from the "
        "server formated as JSON (unlike 'ls', which will add some "
        "client fields)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-p", "--project", "--projection", metavar = "FIELD",
        action = "append", type = str,
        help = "consider only the given fields "
        "(default depends on verbosity")
    ap.set_defaults(func = _cmdline_target_get)

    ap = arg_subparsers.add_parser(
        "patch",
        help = "Store multiple fields of data on the target's inventory"
        " from JSON or KEY=VALUE (vs property-set just storing one)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "data", metavar = "KEY=JSON-VALUE", nargs = "*",
        default = None, help = "Data items to store; if"
        " none, specify a JSON dictionary over stdin")
    ap.set_defaults(func = _cmdline_target_patch)


    ap = arg_subparsers.add_parser(
        "enable",
        help = "Enable disabled target/s")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_target_enable)


    ap = arg_subparsers.add_parser(
        "disable",
        help = "Disable enabled target/s")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-r", "--reason", metavar = "REASON", action = "store",
        default = 'disabled by the administrator',
        help = "Reason why targets are disabled")
    ap.set_defaults(func = _cmdline_target_disable)


    ap = arg_subparsers.add_parser(
        "property-set",
        help = "Set a target's property")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "property", metavar = "PROPERTY", action = "store",
        default = None, help = "Name of property to set")
    ap.add_argument(
        "value", metavar = "VALUE", action = "store",
        nargs = "?", default = None,
        help = "Value of property (none to remove it; i:INTEGER, f:FLOAT"
        " b:false or b:true, otherwise it is considered a string)")
    ap.set_defaults(func = _cmdline_target_property_set)


    ap = arg_subparsers.add_parser(
        "property-get",
        help = "Get a target's property")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "property", metavar = "PROPERTY", action = "store", default = None,
        help = "Name of property to read")
    ap.set_defaults(func = _cmdline_target_property_get)
