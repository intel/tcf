#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage allocations
--------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- List current allocations::

    $ tcf alloc-ls
"""

import argparse
import json
import logging
import os
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_alloc")



def _cmdline_alloc_ls(cli_args: argparse.Namespace):
    import tcfl.allocation
    tcfl.allocation.subsystem_setup()

    log = logging.getLogger("alloc-ls")
    tcfl.ui_cli.logger_verbosity_from_cli(log, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.servers.by_targetspec(
        cli_args.target, verbosity = verbosity)

    if not tcfl.server_c.servers:
        log.error("E: no servers available, did you configure?")
        return

    allocations = tcfl.allocation.ls(
        cli_args.username,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)

    if verbosity < 0:
        # just print the list of alloc ids for each server, one per line
        for _, data in allocations.items():
            if data:
                print("\n".join(data.keys()))
        return
    elif verbosity == 3:
        import pprint
        pprint.pprint(allocations)
        return
    elif verbosity == 4:
        print(json.dumps(allocations, skipkeys = True, indent = 4))
        return

    table = []
    for server_url, ( r, e, tb ) in allocations.items():
        for allocid, data in r.items():
            userl = []
            user = data.get('user', None)
            creator = data['creator']
            guests = data.get('guests', [])
            if 'priority' in data:
                prio = str(data['priority'])
                if data['preempt']:
                    prio += ":P"
            else:
                prio = "n/a"
            userl = [ user ]
            if user != creator:
                userl.append(creator + "[creator]")
            for guest in guests:
                userl.append(guest + "[guest]")
            if verbosity == 0:
                table.append([
                    allocid,
                    # put state/prio/preempt together
                    data['state'] + "\n" + prio,
                    "\n".join(userl),
                    data.get('reason', "n/a"),
                ])
            elif verbosity == 1:
                tgs = []
                for name, group in data.get('target_group', {}).items():
                    tgs.append( name + ":" + ",".join(group))
                server = tcfl.server_c.servers[server_url]
                table.append([
                    allocid,
                    server.aka,
                    data['state'],
                    prio,
                    data.get('timestamp', 'n/a'),
                    "\n".join(userl),
                    "\n".join(tgs),
                    data.get('reason', "n/a"),
                ])
            elif verbosity == 2:
                commonl.data_dump_recursive(data, allocid,)

    if verbosity == 0:
        # To try to be more or less responsive to the terminal size,
        # we calculate the percentage we give to certain columns so
        # let's calculate the max length of the rest, taking into
        # account a min of 70 columns
        try:
            ts = os.get_terminal_size()
            display_w = max(ts.columns, 70)
            # First three columns are max around 30 characters
            #
            ## AllocID    State          Users
            ## ---------- -------------- -------...
            ## ipv3_ry7   active 500000  ...
            #
            columns_available = display_w - 44
            maxcolwidths = [
                8,
                None,
                int(0.30 * columns_available) - 2,
                int(0.70 * columns_available) - 2,
            ]
        except OSError:
            maxcolwidths = None
        import tabulate
        print(tabulate.tabulate(
            table,
            headers = [
                "AllocID",
                "State",
                "Users",
                "Reason"
            ],
            maxcolwidths = maxcolwidths
        ))

    if verbosity == 1:
        # To try to be more or less responsive to the terminal size,
        # we calculate the percentage we give to certain columns so
        # let's calculate the max length of the rest, taking into
        # account a min of 70 columns
        try:
            ts = os.get_terminal_size()
            display_w = max(ts.columns, 70)
            # First three columns are max around 30 characters
            #
            ## AllocID    State          Users
            ## ---------- -------------- -------...
            ## ipv3_ry7   active 500000  ...
            #
            columns_available = display_w - 44
            maxcolwidths = [
                8,				   # allocid
                int(0.10 * columns_available) - 2, # server
                6,				   # state
                6,                                 # priority
                14,                                # timestamp
                int(0.15 * columns_available) - 2, # users
                int(0.28 * columns_available) - 2, # groups
                int(0.37 * columns_available) - 2, # reason
            ]
        except OSError:
            maxcolwidths = None

        import tabulate
        print(tabulate.tabulate(
            table,
            headers = [
            "AllocID",
            "Server",
            "State",
            "Prio",
            "Timestamp",
            "Users",
            "Groups",
            "Reason",
            ],
            maxcolwidths = maxcolwidths
        ))




def _alloc_rm_by_username(server_name: str, server: tcfl.server_c,
                          cli_args: argparse.Namespace):

    count = tcfl.allocation.rm_server_by_username(
        server_name, server, cli_args.username)
    if count == 0:
        logger.info("removed 0 allocations @%s", server.url)
    else:
        logger.warning("removed %s allocations @%s", count, server.url)
    return count	# return how many we found


def _alloc_rm_by_allocid(server_name: str, server: tcfl.server_c,
                         _cli_args: argparse.Namespace, allocid: str):
    try:
        tcfl.allocation.rm_server_by_allocid(server_name, server, allocid)
        # most likely we'll remove only ONE allocation in ONE server,
        # so no need to plan for a multicolumn display
        print(f"allocation '{allocid}' removed from server {server.url}")
        return 1	# let known we found something
    except Exception as e:
        if 'invalid allocation' in str(e):
            # this might be way too common, as we try to remove in all
            # servers, so don't bother if invalid, just if we -vv it
            logger.warning("%s: invalid allocation: %s", server.url, allocid)
            return 0	# let know we found nothing
        raise



def _cmdline_alloc_rm(cli_args: argparse.Namespace):
    import tcfl.allocation
    tcfl.allocation.subsystem_setup()

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    tcfl.servers.subsystem_setup()

    if not tcfl.server_c.servers:
        logger.error("E: no servers available, did you configure?")
        return 1

    if cli_args.allocid:
        retval = 0
        for allocid in cli_args.allocid:
            retval, r = tcfl.ui_cli.run_fn_on_each_server(
                tcfl.server_c.servers,
                _alloc_rm_by_allocid, cli_args, allocid)
            # r is a dict keyed by server name of tuples ( retval,
            # exception, traceback )
            if all(i[0] == 0 for i in r.values()):
                logger.error("allocation '%s' not found in any server",
                             allocid)
                retval = 1
        return retval
    if cli_args.username:
        _, r = tcfl.ui_cli.run_fn_on_each_server(
            tcfl.server_c.servers,
            _alloc_rm_by_username, cli_args)
        if all(i[0] == 0 for i in r.values()):
            logger.error("no allocations for user found")
            return 1
        return 0
    raise RuntimeError(
        "need to specify ALLOCIDs or --user USERNAME or --self;"
        " see --help")



def _release(target: tcfl.tc.target_c, cli_args: argparse.Namespace):
    logger.info("%s: releasing", target.id)
    target.release(force = cli_args.force)
    logger.warning("%s: released", target.id)

def _cmdline_release(cli_args: argparse.Namespace):
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    retval, r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _release, cli_args, cli_args)
    return retval



def cmdline_setup(arg_subparser):
    pass


def cmdline_setup_intermediate(arg_subparser):
    ap = arg_subparser.add_parser(
        "alloc-ls",
        help = "List information about current allocations "
        "in all the servers or the servers where the named "
        "targets are")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-u", "--username", action = "store", default = None,
        help = "ID of user whose allocs are to be displayed"
        " (optional, defaults to anyone visible)")
    ap.add_argument(
        "-r", "--refresh", action = "store",
        type = float, nargs = "?", const = 1, default = 0,
        help = "Repeat every int seconds (by default, only once)")
    ap.set_defaults(func = _cmdline_alloc_ls)


    ap = arg_subparser.add_parser(
        "alloc-rm",
        help = "Delete an existing allocation (which might be "
        "in any state; any targets allocated to said allocation "
        "will be released")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "-u", "--username", action = "store", default = None,
        help = "Remove allocations by user")
    ap.add_argument(
        "-s", "--self", action = "store_const", dest = "username",
        const = "self",
        help = "Remove allocations by the logged in user")
    ap.add_argument(
        "allocid", metavar = "[SERVER/]ALLOCATIONID", nargs = "*",
        action = "store", default = [],
        help = "Allocation IDs to remove")
    ap.set_defaults(func = _cmdline_alloc_rm)


    ap = arg_subparser.add_parser(
        "release",
        help = "Release targets from allocation;" \
        " note the allocations might still be active, but" \
        " the released targets won't be usable from there"
    )
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-f", "--force", action = "store_true", default = False,
        help = "Force release of a target you don't own (only admins)")
    ap.set_defaults(func = _cmdline_release)


def cmdline_setup_advanced(arg_subparser):
    pass
