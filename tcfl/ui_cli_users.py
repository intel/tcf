#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage users
--------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- Log out from all servers::

    $ tcf logout

"""

import argparse
import json
import logging
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_users")



def _logout(server_name, server, cli_args):
    server.logout(cli_args.username)
    logger.warning("%s: logged out of %s", cli_args.username, server_name)


def _cmdline_logout(cli_args: argparse.Namespace):
    """
    Logout user from all the servers
    """
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.servers.by_targetspec(
        cli_args.target, verbosity = verbosity)

    r = tcfl.servers.run_fn_on_each_server(
        servers, _logout, cli_args,
        serialize = cli_args.serialize, traces = cli_args.traces)
    # r now is a dict keyed by server_name of tuples usernames,
    # exception
    for server_name, ( _, e ) in r.items():
        # we get 401 if we are logged out already...ignore
        if e and getattr(e, "status_code", None) != 401:
            logger.error("can't log out of %s: %s",
                         server_name, e)



def cmdline_setup(arg_subparser):
    pass



def cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "logout",
        help = "Log user out of the servers")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-u", "--username", nargs = '?', action = "store", default = None,
        help = "User to logout (defaults to current); to logout others "
        "*admin* role is needed")
    ap.set_defaults(func = _cmdline_logout)
