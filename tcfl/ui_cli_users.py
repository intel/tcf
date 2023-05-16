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
import getpass
import json
import logging
import os
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_users")



def _credentials_get(domain: str, aka: str, cli_args: argparse.Namespace):
    # env general
    user_env = os.environ.get("TCF_USER", None)
    password_env = os.environ.get("TCF_PASSWORD", None)
    # server specific
    user_env_aka = os.environ.get("TCF_USER_" + aka, None)
    password_env_aka = os.environ.get("TCF_PASSWORD_" + aka, None)

    # from commandline
    user_cmdline = cli_args.username
    password_cmdline = cli_args.password

    # default to what came from environment
    user = user_env
    password = password_env
    # override with server specific from envrionment
    if user_env_aka:
        user = user_env_aka
    if password_env_aka:
        password = password_env_aka
    # override with what came from the command line
    if user_cmdline:
        user = user_cmdline
    if password_cmdline:
        password = password_cmdline

    if not user:
        if cli_args.quiet:
            raise RuntimeError(
                "Cannot obtain login name and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_AKA]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain login name and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_AKA]")
        user = input('Login for %s [%s]: ' \
                     % (domain, getpass.getuser()))
        if user == "":	# default to LOGIN name
            user = getpass.getuser()
            print("I: defaulting to login name %s (login name)" % user)

    if not password:
        if cli_args.quiet:
            raise RuntimeError(
                "Cannot obtain password and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_AKA]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain password and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_AKA]")
        password = getpass.getpass("Password for %s at %s: " % (user, domain))
    return user, password



def _login(_server_name, server, credentials):
    user, password = credentials[server.aka]
    r = server.login(user, password)
    logger.warning("%s: logged in as %s", server.url, user)
    return r


def _cmdline_login(cli_args: argparse.Namespace):
    #
    # Login into remote servers.
    #
    # We login in parallel to all the servers, asking info before
    # parallelizing, so we don't jumble it
    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity

    logged = False
    servers = tcfl.server_c.servers
    # we only ask on the terminal HERE!
    credentials = {}
    for server_name, server in servers.items():
        credentials[server.aka] = \
            _credentials_get(server.url, server.aka, cli_args)

    r = tcfl.servers.run_fn_on_each_server(
        servers, _login, credentials,
        serialize = cli_args.serialize, traces = cli_args.traces)
    # r now is a dict keyed by server_name of tuples usernames,
    # exception
    logged_count = 0
    for server_name, ( r, e ) in r.items():
        server = servers[server_name]
        user, _password = credentials[server.aka]
        if e:
            logger.error("%s: can't login as %s: exception: %s",
                         server.url, user, e)
        elif r:
            logged_count += 1
        else:
            logger.error("%s: can't login as %s: bad credentials",
                         server.url, user)

    if logged_count == 0:
        logger.error("Could not login to any server, "
                     "please check your username, password and config")
        return 1
    return 0


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

    ap = arg_subparser.add_parser(
        "login",
        help = "Login to known servers")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--password", "-p", metavar = "PASSWORD", action = "store",
        default = None,
        help = "User's password ('ask' to get it asked on"
        " the terminal)")
    ap.add_argument(
        "-s","--split", action = "store_true", default = False,
        help = "Ask for different user names and passwords for"
        " each server")
    ap.add_argument(
        "-Q","--quiet", action = "store_true",
        default = False, help = "Quiet mode. Don't ask for user or "
        "password and instead look for env variables like "
        "'TCF_{USER|PASSWORD}_${AKA}'. "
        "AKA is the short name of the server (defaults to the sole "
        "host name, without the domain). Find it with 'tcf servers'")
    ap.add_argument(
        "--serialize", action = "store_true", default = False,
        help = "Serialize (don't parallelize) the operation on"
        " multiple servers")
    ap.add_argument(
        "username", nargs = '?', metavar = "USERNAME",
        action = "store", default = None,
        help = "User's login ID")
    ap.set_defaults(
        func = _cmdline_login)



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
