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
import collections
import logging
import os
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_alloc")



def _cmdline_alloc_ls(cli_args: argparse.Namespace):
    import tcfl.allocation
    import tcfl.targets
    tcfl.allocation.subsystem_setup()

    log = logging.getLogger("alloc-ls")
    tcfl.ui_cli.logger_verbosity_from_cli(log, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity

    tcfl.targets.setup_by_spec(
        cli_args.target or [], verbosity = verbosity, targets_all = cli_args.all)

    if not tcfl.server_c.servers:
        log.error("E: no servers available, did you configure?")
        return

    if cli_args.target:
        # user specified targets, so we only need to query those
        # servers those targets are at, let's remove the rest.
        servers = { rt['server'] for rt in tcfl.rts.values() }
        for server_url, server in list(tcfl.server_c.servers.items()):
            if server_url not in servers:
                del tcfl.server_c.servers[server_url]

    # List now allocations in the servers listed in tcfl.server_c.servers
    allocations = tcfl.allocation.ls(
        allocids = cli_args.allocids, username = cli_args.username,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)

    # Now filter, for the allocations listed, which ones include the
    # targets listed
    if not cli_args.full:
        for _, ( r, e, e ) in allocations.items():
            for allocid, data in list(r.items()):
                for rt_allocated in data.get("group_allocated", "").split(","):
                    if rt_allocated not in tcfl.rts:
                        #print(f"DEBUG: skipping {allocid} because {rt_allocated} not there")
                        del r[allocid]
                        break


    if verbosity < 0:
        # just print the list of alloc ids for each server, one per line
        for _, ( data, e, e ) in allocations.items():
            if data:
                print("\n".join(data.keys()))
        return
    elif verbosity == 3:
        import pprint
        pprint.pprint(allocations)
        return
    elif verbosity == 4:
        import json
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
    if not table:
        logging.error("No allocations found")
        return 1

    if verbosity == 0:
        # To try to be more or less responsive to the terminal size,
        # we calculate the percentage we give to certain columns so
        # let's calculate the max length of the rest, taking into
        # account a min of 70 columns
        try:
            ts = os.get_terminal_size()
            display_w = max(ts.columns, 70)
            logger.info("terminal is %d columns wide, display with %d",
                        ts.columns, display_w)
            # First three columns are max around 30 characters
            #
            ## AllocID    State          Users
            ## ---------- -------------- -------...
            ## ipv3_ry7   active 500000  ...
            #
            columns_available = display_w - 8 - 8
            maxcolwidths = [
                8,
                8,	# some more random one are longer, they will wrap
                int(0.30 * columns_available),
                int(0.70 * columns_available),
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
            logger.info("terminal is %d columns wide, display with %d",
                        ts.columns, display_w)
            # First three columns are max around 30 characters
            #
            ## AllocID    State          Users
            ## ---------- -------------- -------...
            ## ipv3_ry7   active 500000  ...
            #
            # note we need to remove some from the columns_available
            # calculation to adjust for extra space added for
            # padding. This as done experimenting until there was no
            # clipping
            columns_available = display_w - 8 - 6 - 6 - 14
            maxcolwidths = [
                8,				   # allocid
                int(0.10 * columns_available) - 2, # server
                6,				   # state
                6,                                 # priority
                14,                                # timestamp
                int(0.15 * columns_available) - 2, # users
                int(0.28 * columns_available) - 3, # groups
                int(0.37 * columns_available) - 3, # reason
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

    retval, _r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _release, cli_args, cli_args)
    return retval



def _aka_allocid_extract(allocid: str):
    # SERVERAKA/ALLOCID -> None, allocid
    if '/' not in allocid:
        return None, allocid
    server_aka, allocid = allocid.split('/', 1)
    for server in tcfl.server_c.servers.values():
        if server.aka == server_aka:
            return server, allocid
    logging.error("%s: unknown server AKA", server_aka)
    return None, allocid



def _guest_add(server_name: str, server: tcfl.server_c,
               _cli_args: argparse.Namespace, allocids_by_server: dict,
               guests: list):

    r = {}
    for allocid in allocids_by_server[server_name]:
        for guest in guests:
            if guest == "self":
                guest = server.logged_in_username()
            try:
                r[allocid + guest] = server.send_request(
                    "PATCH", "allocation/%s/%s" % (allocid, guest))
                logger.info("%s: added guest %s to allocation %s",
                            server.url, guest, allocid)
            except Exception as e:
                if "invalid allocation" not in str(e):
                    raise
                # convert this condition so we don't trigger error
                # handling in run_fn_on_each_server--we have basically
                # tried every server for the allocid and if it says I
                # can't find it, it's fine
                r[allocid + guest] = None
    return r


def _cmdline_guest_add(cli_args: argparse.Namespace):
    import tcfl.servers

    cli_args.verbosity += 1	# we want to default to have warnings
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    tcfl.servers.subsystem_setup()
    # are we addressing by allocid or by targets
    if cli_args.target:
        tcfl.targets.setup_by_spec(
            [ cli_args.allocid ],	# we callit allocid but here is a targetspec
            verbosity = verbosity,
            project = { "_alloc.id" }, targets_all = True)
        # only brings up servers that have those targets
    else:
        tcfl.servers.subsystem_setup()

    if not tcfl.server_c.servers:
        logger.error("E: no servers available? did you discover?")
        return 1

    if not cli_args.guests:	# if no args, add current user
        cli_args.guests = [ "self" ]

    allocids_by_server = collections.defaultdict(set)
    if cli_args.target:
        # when we have targets we know what server and allocid, so we
        # don't need to fire requests to all servers

        for target_id, rt_flat in tcfl.rts_flat.items():
            allocid = rt_flat.get('_alloc.id', None)
            if allocid == None:
                logger.warning("%s: ignoring, not acquried", target_id)

            allocids_by_server[rt_flat['server']].add(allocid)

    else:

        server, allocid = _aka_allocid_extract(cli_args.allocid)
        if server:
            allocids_by_server = { server.url: { allocid } }
        else:
            # fire it to all servers
            for server in tcfl.server_c.servers:
                allocids_by_server[server] = { allocid }

    retval, r = tcfl.ui_cli.run_fn_on_each_server(
        allocids_by_server,
        _guest_add, cli_args, allocids_by_server, cli_args.guests)

    # r is not a dict { SERVERURL : ( GUESTLIST, EXCEPTION, TRACEBACK
    # ) } however, the allocation IDs are unique to a server, so in
    # theory we should get an entry for only one server--in case we
    # expand this in the future to dif server, same allocid, we scan
    # them all
    guests = []
    invalid_allocations = 0
    total_allocations = 0
    for serverurl, ( data, ex, _ex_traceback ) in list(r.items()):
        if ex:			# reported by tcfl.ui_cli.run_fn_on_each_server
            del r[serverurl]
        # data is { ALLOCID: retval, ALLOCID: retval... } from _guest_add()
        for allocid, alloc_data in data.items():
            total_allocations += 1
            if alloc_data == None:
                invalid_allocations += 1

    if total_allocations == invalid_allocations:
        # all failed with invalid allocation, so it's an invalid alloc
        logger.error(f"{cli_args.allocid}: invalid allocation")
        return 1
    return retval



def _guest_rm(server_name: str, server: tcfl.server_c,
               _cli_args: argparse.Namespace, allocids_by_server: dict,
               guests: list):
    r = {}
    for allocid in allocids_by_server[server_name]:
        if not guests:
            logging.info("%s: no guests given, removing all; listing first",
                         server.url)
            # no guests given, remove'em all -- so list them first
            rls = server.send_request("GET", f"allocation/{allocid}")
            guests = rls.get('guests', [])
            logging.info("%s: no guests given, found guests: %s",
                         server.url, " ".join(guests))

        for guest in guests:
            if guest == "self":
                guest = server.logged_in_username()
            try:
                r[allocid + guest] = server.send_request("DELETE", f"allocation/{allocid}/{guest}")
                logger.info("%s: removed guest %s from allocation %s",
                            server.url, guest, allocid)
            except Exception as e:
                if "invalid allocation" not in str(e):
                    raise
                # convert this condition so we don't trigger error
                # handling in run_fn_on_each_server--we have basically
                # tried every server for the allocid and if it says I
                # can't find it, it's fine
                r[allocid + guest] = None
    return r


def _cmdline_guest_rm(cli_args: argparse.Namespace):
    import tcfl.servers

    cli_args.verbosity += 1	# we want to default to have warnings
    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    # are we addressing by allocid or by targets
    if cli_args.target:
        tcfl.targets.setup_by_spec(
            [ cli_args.allocid ],	# we callit allocid but here is a targetspec
            verbosity = verbosity,
            project = { "_alloc.id" }, targets_all = True)
        # only brings up servers that have those targets
    else:
        tcfl.servers.subsystem_setup()
    if not tcfl.server_c.servers:
        logger.error("E: no servers available? did you discover?")
        return 1

    allocids_by_server = collections.defaultdict(set)
    if cli_args.target:
        # when we have targets we know what server and allocid, so we
        # don't need to fire requests to all servers

        for target_id, rt_flat in tcfl.rts_flat.items():
            allocid = rt_flat.get('_alloc.id', None)
            if allocid == None:
                logger.warning("%s: ignoring, not acquried", target_id)

            allocids_by_server[rt_flat['server']].add(allocid)

    else:
        server, allocid = _aka_allocid_extract(cli_args.allocid)
        if server:
            allocids_by_server = { server.url: { allocid } }
        else:
            # fire it to all servers
            for server in tcfl.server_c.servers:
                allocids_by_server[server] = { allocid }

    if cli_args.all:	# if --all, remove all users, set it to empty
        cli_args.guests = [ ]
    elif not cli_args.guests:	# if no args, remove current user
        cli_args.guests = [ "self" ]

    retval, r = tcfl.ui_cli.run_fn_on_each_server(
        allocids_by_server,
        _guest_rm, cli_args, allocids_by_server, cli_args.guests)

    # r is not a dict { SERVERURL : ( GUESTLIST, EXCEPTION, TRACEBACK
    # ) } however, the allocation IDs are unique to a server, so in
    # theory we should get an entry for only one server--in case we
    # expand this in the future to dif server, same allocid, we scan
    # them all
    guests = []
    total_allocations = 0
    invalid_allocations = 0
    for serverurl, ( data, ex, _ex_traceback ) in list(r.items()):
        if ex:			# reported by tcfl.ui_cli.run_fn_on_each_server
            del r[serverurl]
        # data is { ALLOCID: retval, ALLOCID: retval... } from _guest_rm()
        for allocid, allocid_data in data.items():
            total_allocations += 1
            if allocid_data == None:
                invalid_allocations += 1

    if total_allocations == invalid_allocations:
        # all failed with invalid allocation, so it's an invalid alloc
        logger.error(f"{cli_args.allocid}: invalid allocation")
        return 1
    return retval



def _guests_list(server_name: str, server: tcfl.server_c,
                 _cli_args: argparse.Namespace, allocids_by_server: dict):
    guest_list_by_allocid = {}
    for allocid in allocids_by_server[server_name]:
        try:
            r = server.send_request("GET", "allocation/%s" % allocid)
            guest_list_by_allocid[allocid] = r.get('guests', [])
        except Exception as e:
            if "invalid allocation" not in str(e):
                raise
            # convert this condition so we don't trigger error handling in
            # run_fn_on_each_server
            guest_list_by_allocid[allocid] = None
    return guest_list_by_allocid


def _cmdline_guest_ls(cli_args: argparse.Namespace):
    import tcfl.servers

    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    tcfl.servers.subsystem_setup()

    # are we addressing by allocid or by targets
    if cli_args.target:
        tcfl.targets.setup_by_spec(
            [ cli_args.allocid ],	# we callit allocid but here is a targetspec
            verbosity = verbosity,
            project = { "_alloc.id" }, targets_all = True)
        # only brings up servers that have those targets
    else:
        tcfl.servers.subsystem_setup()

    if not tcfl.server_c.servers:
        logger.error("E: no servers available? did you discover?")
        return 1

    allocids_by_server = collections.defaultdict(set)
    if cli_args.target:
        # when we have targets we know what server and allocid, so we
        # don't need to fire requests to all servers

        for target_id, rt_flat in tcfl.rts_flat.items():
            allocid = rt_flat.get('_alloc.id', None)
            if allocid == None:
                logger.warning("%s: ignoring, not acquried", target_id)

            allocids_by_server[rt_flat['server']].add(allocid)

    else:	# [SERVERAKA/]ALLOCID
        server, allocid = _aka_allocid_extract(cli_args.allocid)
        if server:
            allocids_by_server = { server.url: { allocid } }
        else:
            # fire it to all servers
            for server in tcfl.server_c.servers:
                allocids_by_server[server] = { allocid }

    retval, r = tcfl.ui_cli.run_fn_on_each_server(
        allocids_by_server,
        _guests_list, cli_args, allocids_by_server)

    # r is not a dict { SERVERURL : ( GUESTLIST, EXCEPTION, TRACEBACK
    # ) } however, the allocation IDs are unique to a server, so in
    # theory we should get an entry for only one server--in case we
    # expand this in the future to dif server, same allocid, we scan
    # them all
    invalid_allocations = 0
    guests = {}
    for serverurl, ( guest_list_by_allocid, ex, _ex_traceback ) in r.items():
        if ex:			# reported by tcfl.ui_cli.run_fn_on_each_server
            del r[serverurl]
        if not guest_list_by_allocid:	# from _guest_list()
            invalid_allocations += 1
        for allocid, guest_list in guest_list_by_allocid.items():
            if verbosity < 2:
                print(allocid + ": " + " ".join(sorted(guest_list)))
            elif verbosity == 2:
                guests[allocid] = sorted(guest_list)
            elif verbosity >= 3:
                guests[allocid] = sorted(guest_list)

    if verbosity == 2:
        import pprint
        pprint.pprint(guests, indent = True)
    if verbosity >= 3:
        import json
        json.dump(guests, sys.stdout, indent = True)
        print()

    if invalid_allocations == len(r):
        # all failed with invalid allocation, so it's an invalid alloc
        logger.error(f"{cli_args.allocid}: invalid allocation")
        return 1

    return retval



def cmdline_setup(arg_subparser):
    pass


def cmdline_setup_intermediate(arg_subparser):
    ap = arg_subparser.add_parser(
        "alloc-ls",
        help = "List information about current allocations "
        "in all the servers or the servers where the named "
        "targets are. Note as TARGETSPEC you can also add "
        "allocation IDs")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, argspec = [ "-t", "--target" ], nargs = 1)
    ap.add_argument(
        "-u", "--username", action = "store", default = None,
        help = "ID of user whose allocs are to be displayed"
        " (optional, defaults to anyone visible)")
    ap.add_argument(
        "-r", "--refresh", action = "store",
        type = float, nargs = "?", const = 1, default = 0,
        help = "Repeat every int seconds (by default, only once)")
    ap.add_argument(
        "-f", "--full", action = "store_true", default = False,
        help = "list all allocations, not just active ones")
    ap.add_argument(
        "allocids",
        metavar = "ALLOCID", action = "store",
        nargs = "*",
        help = "Alloc IDs to list info for (if none, all are listed)")
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


    ap = arg_subparser.add_parser(
        "guest-add",
        help = "Add a guest to an allocation so they can use the"
        " targets the same way as the owner")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "--target", "-t",
        action = "store_true", default = False,
        help = "filter by targetspec, not ALLOCID")
    ap.add_argument(
        "allocid", metavar = "[SERVERAKA/]ALLOCATIONID|TARGETSPEC",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to; if -t, TARGETSPEC")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "*",
        action = "store", default = None,
        help = "Name of guest to add; note this is the names"
        " the users logged in with; use *self* for yourself."
        " If none specifies, adds the calling user.")
    ap.set_defaults(func = _cmdline_guest_add)


    ap = arg_subparser.add_parser(
        "guest-rm",
        help = "Remove guests from an allocation; they will no longer"
        " be able to use the targets the same way as the owner")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "--all", "-a",
        action = "store_true", default = False,
        help = "remove all guests")
    ap.add_argument(
        "--target", "-t",
        action = "store_true", default = False,
        help = "filter by targetspec, not ALLOCID")
    ap.add_argument(
        "allocid", metavar = "[SERVERAKA/]ALLOCATIONID|TARGETSPEC",
        action = "store", default = None,
        help = "Allocation IDs to which to remove guest from; if -t, TARGETSPEC")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "*",
        action = "store", default = None,
        help = "Names of guests to remove; note this is the names"
        " the users logged in with. If none given or *self* specified"
        " will remove current user.")
    ap.set_defaults(func = _cmdline_guest_rm)


    ap = arg_subparser.add_parser(
        "guest-ls",
        help = "list guests in an allocation"
    )
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "--target", "-t",
        action = "store_true", default = False,
        help = "filter by targetspec, not ALLOCID")
    ap.add_argument(
        "allocid", metavar = "[SERVERAKA/]ALLOCATIONID|TARGETSPEC",
        action = "store", default = None,
        help = "Allocation IDs to list to add guest to; if -t, TARGETSPEC")
    ap.set_defaults(func = _cmdline_guest_ls)



def cmdline_setup_advanced(arg_subparser):
    pass
