#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command line interface UI to to deal with targets
=================================================

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
import tcfl.targets

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
    assert isinstance(tda, tcfl.targets.discovery_agent_c)

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



def _cmdline_ls(args):

    verbosity = args.verbosity - args.quietosity

    # let's do some voodoo (for speed) -- we want to load (project)
    # only the minimum amount of fields we need for doing what we need
    # so, guess those.
    if args.project == None:
        if verbosity >= 1:
	    # we want verbosity, no fields were specified, so ask for
            # all fields (None); makes no sense with verbosity <=1, since it
            # only prints ID, owner
            args.project = None
        else:
            args.project = { 'id', 'disabled' }
    else:
        args.project = set(args.project)   # to help avoid dups

    # ensure the name and the disabled fields (so we can filter on it)
    # if we are only doing "tcf ls" to list target NAMEs, then
    # we don't care whatsoever by the rest of the fields, so
    # don't get them, except for disabled, to filter on it.
    logger.info(f"original projection list: {args.project}")
    if args.project != None:
        args.project.update({ 'id', 'disabled' })
        if verbosity >= 0:
            args.project.add('interfaces.power.state')
            args.project.add('owner')
    logger.info(f"updated projection list: {args.project}")

    # parse TARGETSPEC, if any -- because this will ask for extra
    # fields from the inventory, so we'll have to add those to what we
    # are asking from the server
    if args.target:
        # we need to decide which fields are requested by the
        # targetspec specification
        expressionl = [ ]
        for spec in args.target:
            expressionl.append("( " + spec + " ) ")
        # combine expressions in the command line with OR, so
        # something such as
        #
        #   $ tcf ls TARGET1 TARGET2
        #
        # lists both targets
        expression = "(" + " or ".join(expressionl) + ")"
        logger.info(f"filter expression: {expression}")
        expr_ast = commonl.expr_parser.precompile(expression)
        expr_symbols = commonl.expr_parser.symbol_list(expr_ast)
        logger.info(f"symbols from target filters: {', '.join(expr_symbols)}")
    else:
        expr_ast = None
        expr_symbols = []

    # aah...projections -- we want the minimum amount of fields so we
    # can pull the data as fast as possible; need the following
    # minimum deck of fields:
    #
    # - id, disabled
    #
    # - any field we are testing ("ram.size == 32")
    fields = args.project
    if expr_symbols:		# bring anything from fields we are testing
        if fields == None:
            # if fields is None, keep it as None as it will pull ALL the fi
            logger.info(f"querying all fields, so not upating from filter"
                        f" expression ({', '.join(expr_symbols)})")
        else:
            fields.update(expr_symbols)
            logger.info(f"fields from filter expression: {', '.join(fields)}")

    # so now we are actually querying the servers; this will
    # initialize the servers, discover them and them query them for
    # the target list and the minimum amount of inventory needed to
    # filter and display
    if fields:
        logger.info(f"querying inventories with fields: {', '.join(fields)}")
    else:
        logger.info("querying inventories with all fields")
    tcfl.targets.subsystem_setup(projections = fields)

    # filter targets: because this discovery agent is created just for
    # us, we can directly modify its lists, deleting any target that
    # doesn't match the critera

    for rtfullid in filter(
            lambda rtfullid: not tcfl.targets.select_by_ast(
                tcfl.targets.discovery_agent.rts_flat[rtfullid],
                expr_ast, args.all
            ),
            list(tcfl.targets.discovery_agent.rts_fullid_sorted)):
        tcfl.targets.discovery_agent.rts_fullid_sorted.remove(rtfullid)
        del tcfl.targets.discovery_agent.rts[rtfullid]
        del tcfl.targets.discovery_agent.rts_flat[rtfullid]

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



def _common_args_add(ap):
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Display more progress information")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Display more progress information less progress info")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")



def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "ls2", help = "List targets by name or search pattern")
    _common_args_add(ap)
    ap.add_argument(
        "-p", "--project", "--projection", metavar = "FIELD",
        action = "append", type = str,
        help = "consider only the given fields "
        "(default depends on verbosity")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = None,
        help = "Target's names or URLs or a general target specification "
        "which might include values of tags, etc, in single quotes (eg: "
        "'ram.size_gib >= 2 and not type:\"^qemu.*\"'")
    # FIXME add url
    ap.set_defaults(func = _cmdline_ls)
