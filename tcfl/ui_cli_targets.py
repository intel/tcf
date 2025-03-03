#! /usr/bin/env python3
#
# Copyright (c) 2021-23 Intel Corporation
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

    $ tcf ls
    $ tcf ls [TARGETNAME...] [TARGETSPEC...]

- get target's inventory in JSON format::

    $ tcf get TARGETNAME

- get a property from the target's inventory::

    $ tcf property-get TARGETNAME PROPERTYNAME

- set/reset a property in the target's inventory::

    $ tcf property-set TARGETSPEC PROPERTYNAME [VALUE]

- set multiple properties from a JSON data set::

    $ tcf patch TARGETNAME < somefile.json

- enable/disable targets::

    $ tcf disable [-r REASON] TARGETSPEC
    $ tcf enable TARGETSPEC

- run a basic healthcheck on targets::

    $ tcf healthcheck TARGETSPEC


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

logger = logging.getLogger("ui_cli_targets")


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

    def _target_get(target):
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
        _target_get, cli_args, only_one = True)[0]



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

    if cli_args.project:
        projections_list = cli_args.project       # respect user's order
        projections_set = set(cli_args.project)   # to help avoid dups
    else:
        projections_list = []
        projections_set = set()

    # ensure the most basic fields for each verbosity level are queried
    if verbosity < 1:      # basic; need only id and disable
        projections_set.add('id')
        projections_set.add('disabled')
    if verbosity >= 1:      # need also power, ownership
        projections_set.add('interfaces.power.state')
        projections_set.add('owner')
        projections_set.add('_alloc.id')
    if verbosity > 1:       # verbose, get all fields
        projections_set = None

    tcfl.targets.setup_by_spec(
        cli_args.target, verbosity = verbosity,
        project = projections_set, targets_all = cli_args.all,
        shorten_names = cli_args.shorten_names)

    if cli_args.csv:
        import csv

        row_header =  [ "Name" ] + projections_list
        rows = [
            row_header
        ]

        for rtid, rt in tcfl.rts_flat.items():
            fields = collections.defaultdict(set)
            for k, v in rt.items():
                if isinstance(v, dict):
                    continue
                projection = commonl.field_needed(k, projections_list)
                if not projection:
                    continue
                if cli_args.csv_aggregate_add_fields:
                    fields[projection].add(f"{k}:{v}")
                else:
                    fields[projection].add(v)
            row = [ rtid ]
            for projection in projections_list:
                row.append(' '.join(fields[projection]))
            rows.append(row)

        writer = csv.writer(sys.stdout, delimiter = ',',
                            quotechar = '|',
                            quoting = csv.QUOTE_MINIMAL)
        writer.writerows(rows)

    elif verbosity < 0:
        print(" \n".join(tcfl.targets.discovery_agent.rts_fullid_sorted))
    elif verbosity == 0:
        _targets_print_v0(tcfl.targets.discovery_agent)
    elif verbosity == 1:
        _targets_print_v1(tcfl.targets.discovery_agent)
    elif verbosity == 2:
        for rtfullid in tcfl.targets.discovery_agent.rts_fullid_sorted:
            rt = tcfl.targets.discovery_agent.rts[rtfullid]
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
        _target_patch, cli_args, cli_args, only_one = True)[0]



def _target_enable(target):
    target.enable()

def _cmdline_target_enable(cli_args: argparse.Namespace):

    # force seeing all targets, will ease confusion, since normally we
    # want to enable disabled targets
    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_enable, cli_args, targets_all = True)[0]



def _target_disable(target, cli_args):
    target.disable(cli_args.reason)

def _cmdline_target_disable(cli_args: argparse.Namespace):

    # force seeing all targets, will ease confusion, in case we run the
    # command twice (trying to disable a disabled target shall just work)
    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_disable, cli_args, cli_args, targets_all = True)[0]



def _target_property_set(target, cli_args):
    log = logger.getChild(target.id)
    tcfl.ui_cli.logger_verbosity_from_cli(log, cli_args)
    value = commonl.cmdline_str_to_value(cli_args.value)
    r = target.property_set(cli_args.property, value)
    log.warning(f"set property '{cli_args.property}' to"
                f" {type(value).__name__}:{value}: {r=}")
    return r

def _cmdline_target_property_set(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_property_set, cli_args, cli_args)[0]



def _target_property_get(target, cli_args):
    r = target.property_get(cli_args.property)
    if r:	# print nothing if None
        print(r)

def _cmdline_target_property_get(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _target_property_get, cli_args, cli_args, only_one = True)[0]



def _cmdline_target_healthcheck(cli_args: argparse.Namespace):
    import tcfl.healthcheck
    return tcfl.ui_cli.run_fn_on_each_targetspec(
        tcfl.healthcheck._target_healthcheck, cli_args, cli_args,
        # ensure we get the whole inventory
        projections_minimize = False)[0]



def _cmdline_help_fieldnames(cli_args: argparse.Namespace):
    import tcfl.targets

    # if callled from --help-fieldnames, we won't have cli_args with
    # some options, so fake'em to get the most info
    cli_args_target = getattr(cli_args, "target", [])
    cli_args_all = getattr(cli_args, "all", True)

    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    tcfl.targets.setup_by_spec(
        cli_args_target,
        # zero verbosity will get only minimal fields (names, etc)
        # from the servers
        verbosity = 1,
        targets_all = cli_args_all)

    # this is same as in tcfl.server_c.targets_get(); we re-do it so
    # we only show the keys for the targets queried, since
    # tcfl.inventory_keys are for all the keys found in servers
    inventory_keys = collections.defaultdict(set)
    for rtfullid in tcfl.rts_fullid_sorted:
        rt = tcfl.rts_flat[rtfullid]
        for key, value in rt.items():
            tcfl.server_c._inventory_keys_update(inventory_keys, key, value)

    if verbosity < 0:		# print just the fields
        print("\n".join(sorted(inventory_keys)))

    elif verbosity == 0:	# print fields and values in pretty form
        for key in sorted(inventory_keys):
            values = sorted(inventory_keys[key])
            prefix = f"{key}:"
            prefix_space = " " * len(prefix)
            first_value = True
            for value in values:
                if first_value:
                    print(prefix + f" [{type(value).__name__}] {value}")
                    first_value = False
                else:
                    print(f"{prefix_space} [{type(value).__name__}] {value}")

    elif verbosity == 1:	# print fields and raw values
        for key in sorted(inventory_keys):
            values = sorted(inventory_keys[key])
            print(f"{key}: {values}")

    elif verbosity == 2:	# line oriented
        commonl.data_dump_recursive(inventory_keys)

    elif verbosity == 3:	# Python pprint
        import pprint
        # convert to dict so it doesn't print it's a defaultdict
        pprint.pprint(dict(inventory_keys), indent = True)

    elif verbosity > 3:		# JSON
        import json
        def _serialize(o):
            if isinstance(o, set):
                return list(o)
            return o
        # convert to dict so it doesn't print it's a defaultdict
        json.dump(dict(inventory_keys), sys.stdout,
                  skipkeys = True, indent = 4, default = _serialize)


class argparser_action_help_fieldnames(argparse.Action):
    """
    Helper to get the list of knonw fields

    """
    def __init__(self, *args, **kwargs):
        argparse.Action.__init__(self, *args, **kwargs)

    def __call__(self, _parser, namespace, _values, _option_string = None):
        _cmdline_help_fieldnames(namespace)
        sys.exit(0)



def _cmdline_help_targetspec(_cli_args: argparse.Namespace):
    print(
"""
TCF's targetspec is a boolean query language to select targets; it can be used
with all the commands to do operations on multiple targets.

Power off machines named *lab1/2/3*, owned by a user like *smith* that are on:

  $ tcf power-off "id:'lab[123]' and interface.power.status == True and owner:'smith'"

List all targets on server *someserver*

  $ tcf ls "server:'someserver'"

This is a summary of commonl/expr_parser.py (authoritative). Expressions:

- FIELDNAME OPERATOR CONSTANT
- CONSTANT in FIELDNAME, FIELDNAME in LIST
- EXPRESSION and|or EXPRESSION, not EXPRESSION, ( EXPRESSION )
- FIELDNAME (False if undefined, True if defined)

OPERATORS by precedence: ==, !=, >, <, >=, <=, in, :, NOT, AND, OR
FIELDNAMES and possible values can be found with: 'tcf help-fieldnames'
CONSTANT is a number, float, 'string' or bool (False|True)

- : is a regular expression operator; evaluates to True if the FIELDNAME
  matches the Python regex in the CONSTANT
  "owner:'jane'"	# owner field has *jane* in it

- If FIELDNAME is not defined, it evaluates as false, so
  "unexistingfieldname"       # matches none, because the field does not exist
  "not unexistingfieldname"   # matches all, because the field does not exist

- If FIELDNAME is defined, but as false it can be tested with:
  "fieldname == False"

Examples:

- All targets that report their type as *qemu-uefi-arm*, *qemu-uefi-x86_64*:
  "type in [ 'qemu-uefi-arm', 'qemu-uefi-x86_64' ]"

- All targets whose type contains the QEMU substring and owned by *jane*:
  "'qemu' in type and owner:'jane'"

- Target's name is *central1*, RAM size more than 2 GiB and not allocated
  "( id == 'central1' or ram.size_gib > 2 ) and not owner"

** this doc is long; for paging: tcf --help-targetspec | less -S **
""")


class argparser_action_help_targetspec(argparse.Action):
    """
    Helper to get targetspec help from a command line switch
    (--help-targetspec) vs just a command

    """
    def __init__(self, *args, **kwargs):
        argparse.Action.__init__(self, *args, **kwargs)

    def __call__(self, _parser, namespace, _values, _option_string = None):
        _cmdline_help_targetspec(namespace)
        sys.exit(0)



def _cmdline_setup(arg_subparsers):

    import tcfl.ui_cli

    ap = arg_subparsers.add_parser(
        "ls",
        help = "List targets by name or search pattern")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-p", "--project", "--projection", metavar = "FIELD",
        action = "append", type = str,
        help = "consider only the given fields "
        "(default depends on verbosity")
    ap.add_argument(
        "-c", "--csv", action = "store_true", default = False,
        help = "output the fields given with --project in CSV format")
    ap.add_argument(
        "--csv-aggregate-add-fields", action = "store_true", default = False,
        help = "when fields have multiple values because we are aggregating"
        " (eg: interconnects.*.mac_addr), prefix the field name to the value")
    ap.add_argument(
        "--shorten-names",
        action = "store_true", default = True,
        help = "When unique, shorten target names"
        " (SERVER/TARGETNAME) to TARGETNAME [default]")
    ap.add_argument(
        "--no-shorten-names", "-N",
        dest = "shorten_names", action = "store_false",
        help = "Do not shorten target names when unique"
        " (SERVER/TARGETNAME) to TARGETNAME")
    ap.set_defaults(func = _cmdline_ls)


    ap = arg_subparsers.add_parser(
        "help-fieldnames",
        help = "Display all fields in the inventory for the given targets"
        " (all targets by default); verbosity controls how much info/format")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_help_fieldnames)

    ap = arg_subparsers.add_parser(
        "help-targetspec",
        help = "Display information about the target query language")
    ap.set_defaults(func = _cmdline_help_targetspec)



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
    tcfl.ui_cli.args_targetspec_add(ap, nargs = 1)
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


    ap = arg_subparsers.add_parser(
        "healthcheck",
        help = "Do a very basic health check")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "-i", "--interface", metavar = "INTERFACE",
        dest = "interfaces", action = "append", default = [],
        help = "Names of interfaces to healtcheck (default all "
        "exposed by the target)")
    ap.add_argument(
        "-p", "--priority", action = "store", type = int, default = 500,
        help = "Priority for allocation (0 highest, 999 lowest)")
    ap.add_argument(
        "--preempt", action = "store_true", default = False,
        help = "Enable allocation preemption (disabled by default)")
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_target_healthcheck)
