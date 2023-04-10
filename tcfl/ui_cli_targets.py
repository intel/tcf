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

import logging
import math
import os
import sys

import commonl

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



def _cmdline_setup(arg_subparsers):

    import tcfl.ui_cli

    ap = arg_subparsers.add_parser(
        "ls2", help = "List targets by name or search pattern")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-p", "--project", "--projection", metavar = "FIELD",
        action = "append", type = str,
        help = "consider only the given fields "
        "(default depends on verbosity")
    ap.set_defaults(func = _cmdline_ls)
