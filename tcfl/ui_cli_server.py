#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to manage servers
import concurrent.futures
import getpass
import logging
import os
import sys

import tcfl

logger = logging.getLogger("ui_cli_server")

def _credentials_get(domain, aka, args):
    # env general
    user_env = os.environ.get("TCF_USER", None)
    password_env = os.environ.get("TCF_PASSWORD", None)
    # server specific
    user_env_aka = os.environ.get("TCF_USER_" + aka, None)
    password_env_aka = os.environ.get("TCF_PASSWORD_" + aka, None)

    # from commandline
    user_cmdline = args.user
    password_cmdline = args.password

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
        if args.quiet:
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
        if args.quiet:
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


def _cmdline_login(args):
    """
    Login into remote servers.

    :param argparse.Namespace args: login arguments like -q (quiet) or
      userid.
    :returns: True if it can be logged into at least 1 remote server.
    """
    if not args.split and sys.stdout.isatty() and not args.quiet:
        if args.user == None:
            args.user = input('Login [%s]: ' % getpass.getuser())
        if args.password in ( "ask", None):
            args.password = getpass.getpass("Password: ")

    if not tcfl.server_c.servers:
        logging.error("E: no servers available, did you configure/discover?")
        return 0

    # we can't get this in parallel
    username = {}
    password = {}
    for server in tcfl.server_c.servers.values():
        username[server.url], password[server.url] = \
            _credentials_get(server.url, server.aka, args)

    # but we can login in parallel
    with concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
        futures = {}
        for server in tcfl.server_c.servers.values():
            server._cookies_trash()
            futures[server] = ex.submit(
                server.login,
                username[server.url], password[server.url]
            )

        passed = 0
        failed = 0
        for server, future in futures.items():
            try:
                _r = future.result()	# access to trigger exception check
                passed += 1
            except Exception as e:
                logger.error(f"{server.url}: login failed: {str(e)}")
                failed += 1

    if failed:
        logger.warning("could not login to some servers")

    if not passed:
        logger.error("could not login to any servers")
        return 1
    return 0


def _cmdline_logout(args):
    """
    Logout user from all the servers
    """
    if not tcfl.server_c.servers:
        logging.error("E: no servers available, did you configure/discover?")
        return 0

    with concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
        futures = {}
        for server in tcfl.server_c.servers.values():
            futures[server] = ex.submit(
                server.logout,
                args.username
            )

        passed = 0
        failed = 0
        for server, future in futures.items():
            try:
                _r = future.result()	# access to trigger exception check
                passed += 1
            except Exception as e:
                logger.error(f"{server.url}: logout failed: {str(e)}")
                failed += 1
                # trash cookies after sending the logout request
            server._cookies_trash()

        if not passed:
            return 1
        return 0


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser("login",
                                   help = "Login to the different servers")
    ap.add_argument("--password", "-p", metavar = "PASSWORD", action = "store",
                    default = None,
                    help = "User's password ('ask' to get it asked on"
                    " the terminal)")
    ap.add_argument("-s","--split", action = "store_true", default = False,
                    help = "Ask for different user names and passwords for"
                    " each server")
    ap.add_argument("-q","--quiet", action = "store_true",
                    default = False, help = "Quiet mode. Don't ask for user or "
                    "password and instead look for env variables like "
                    "'TCF_{USER|PASSWORD}_${AKA}'. "
                    "AKA is the short name of the server (defaults to the sole "
                    "host name, without the domain).")
    ap.add_argument("user", nargs = '?', metavar = "USERNAME",
                    action = "store", default = None,
                    help = "User's login ID")
    ap.set_defaults(func = _cmdline_login)


    ap = arg_subparsers.add_parser(
        "logout",
        help = "Log user out of the servers brokers")
    ap.add_argument(
        "username", nargs = '?', action = "store", default = None,
        help = "User to logout (defaults to current); to logout others "
        "*admin* role is needed")
    ap.set_defaults(func = _cmdline_logout)
