#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage servers
----------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- List available servers::

    $ tcf servers

"""

import argparse
import json
import logging
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_servers")


def _logged_in_username(_server_name, server):
    return server.logged_in_username()


def _cmdline_servers(cli_args: argparse.Namespace):
    import tcfl.targets
    # collect data in two structures, makes it easier to print at
    # different verbosity levels...yah, lazy
    d = {}
    servers = {}	# new stuff
    usernames = {}

    if cli_args.target:
        # we are given a list of targets to look for their servers or
        # default to all, so pass it on to initialize the inventory
        # system so we can filter
        tcfl.targets.setup_by_spec(
            cli_args.target, cli_args.verbosity - cli_args.quietosity,
            targets_all = cli_args.all)

        # now for all the selected targets, let's pull their servers
        servers = {}
        # pull the server from rt[server], the server's URL, which is how
        # tcfl.server_c.servers indexes servers too
        for rt in tcfl.rts.values():
            server_url = rt['server']
            servers[server_url] = tcfl.server_c.servers[server_url]
    else:
        # no targets, so all, just init the server discovery system
        import tcfl.servers
        tcfl.servers.subsystem_setup()
        servers = tcfl.server_c.servers

    verbosity = cli_args.verbosity - cli_args.quietosity

    # servers is now a dict of servers we care for, keyed by server URL
    if verbosity >= -1:

        r = tcfl.servers.run_fn_on_each_server(
            servers, _logged_in_username,
            serialize = cli_args.serialize, traces = cli_args.traces)
        # r now is a dict keyed by server_name of tuples usernames,
        # exception
        for server_name, ( username, _e ) in r.items():
            usernames[server_name] = username if username else "n/a"

    servers_sorted = {}
    for server_url in sorted(servers.keys()):
        servers_sorted[server_url] = servers[server_url]
    servers = servers_sorted

    if verbosity < -2:		# print just the AKAs
        for server in servers.values():
            print(server.aka)
    elif verbosity == -2:	# print just the hostnames
        for server in servers.values():
            print(server.parsed_url.hostname)
    elif verbosity == -1:	# print aka, url, hostname
        for server_url, server in servers.items():
            print(server.aka, server.url, usernames[server_url])
    elif verbosity == 0:	# more details in table form
        import tabulate		# lazy import, only when needed
        headers = [
            "Server",
            "URL",
            "UserID",
        ]
        table = []
        for server_url, server in servers.items():
            table.append([
                server.aka, server.url, usernames[server_url]
            ])
        print(tabulate.tabulate(table, headers = headers))
    elif verbosity == 1:	# add origin
        import tabulate		# lazy import, only when needed
        headers = [
            "Server",
            "URL",
            "UserID",
            "Origin"
        ]
        table = []
        for server_url, server in servers.items():
            table.append([
                server.aka, server.url, usernames[server_url], server.origin
            ])
        print(tabulate.tabulate(table, headers = headers))
    elif verbosity == 2:	# key/value
        d = {}
        for server_url, server in servers.items():
            d[server.aka] = dict(
                url = server.url,
                username = usernames[server_url],
                origin = server.origin
            )
        commonl.data_dump_recursive(d)
    elif verbosity >= 2:	# JSON
        d = {}
        for server_url, server in servers.items():
            d[server.aka] = dict(
                url = server.url,
                username = usernames[server_url],
                origin = server.origin
            )
        json.dump(d, sys.stdout, skipkeys = True, indent = 4)



def cmdline_setup(arg_subparser):

    ap = arg_subparser.add_parser(
        "servers",
        help = "List configured/discovered servers")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_servers)
