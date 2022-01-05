#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to manage users
import concurrent.futures
import getpass
import json
import logging
import os
import pprint
import sys

import tabulate

import commonl
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


def _cmdline_role_drop(args):
    if not tcfl.server_c.servers:
        logging.error("E: no servers available, did you configure/discover?")
        return 0

    with concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
        futures = {}
        for server in tcfl.server_c.servers.values():
            futures[server] = ex.submit(
                server.role_drop,
                args.role, args.username
            )

        passed = 0
        failed = 0
        for server, future in futures.items():
            try:
                _r = future.result()	# access to trigger exception check
                passed += 1
            except Exception as e:
                logger.error(f"{server.url}: role drop failed: {e}")
                failed += 1
        if not passed:
            return 1
        return 0


def _cmdline_role_gain(args):
    if not tcfl.server_c.servers:
        logging.error("E: no servers available, did you configure/discover?")
        return 0

    with concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
        futures = {}
        for server in tcfl.server_c.servers.values():
            futures[server] = ex.submit(
                server.role_gain,
                args.role, args.username
            )

        passed = 0
        failed = 0
        for server, future in futures.items():
            try:
                _r = future.result()	# access to trigger exception check
                passed += 1
            except Exception as e:
                logger.error(f"{server.url}: role gain failed: {e}")
                failed += 1
        if not passed:
            return 1
        return 0


def _user_list(server, userids):
    result = {}
    if userids:
        for userid in userids:
            try:
                result.update(server.send_request("GET", "users/" + userid))
            except Exception as e:
                logger.error("%s: error getting user's info: %s", userid, e)
    else:
        try:
            result.update(server.send_request("GET", "users/"))
        except Exception as e:
            logger.error("error getting all user info: %s", e)
    return result


def _cmdline_user_list(args):
    result = {}
    if not tcfl.server_c.servers:
        logging.error("E: no servers available, did you configure?")
        return
    with tcfl.msgid_c("cmdline"), \
         concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
        futures = {
            ex.submit(_user_list, server, args.userid): server
            for server in tcfl.server_c.servers.values()
        }
        for future in concurrent.futures.as_completed(futures):
            server = futures[future]
            try:
                r = future.result()
                result[server.aka] = r
            except Exception as e:
                logger.exception(f"{server.url}: exception {e}")
                continue

    if args.verbosity == 0:
        headers = [
            "Server",
            "UserID",
        ]
        table = []
        for server, r in result.items():
            for userid, data in r.items():
                table.append([ server, userid ])
        print((tabulate.tabulate(table, headers = headers)))
    elif args.verbosity == 1:
        headers = [
            "Server",
            "UserID",
            "Roles",
        ]
        table = []
        for server, r in result.items():
            for userid, data in r.items():
                rolel = []
                for role, state in data['roles'].items():
                    if state == False:
                        rolel.append(role + " (dropped)")
                    else:
                        rolel.append(role)
                table.append([
                    server, userid, "\n".join(rolel) ])
        print((tabulate.tabulate(table, headers = headers)))
    elif args.verbosity == 2:
        commonl.data_dump_recursive(result)
    elif args.verbosity == 3:
        pprint.pprint(result)
    elif args.verbosity >= 4:
        print(json.dumps(result, skipkeys = True, indent = 4))


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


def _cmdline_setup_advanced(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "role-gain",
        help = "Gain access to a role which has been dropped")
    ap.add_argument("-u", "--username", action = "store", default = "self",
                    help = "ID of user whose role is to be dropped"
                    " (optional, defaults to yourself)")
    ap.add_argument("role", action = "store",
                    help = "Role to gain")
    ap.set_defaults(func = _cmdline_role_gain)


    ap = arg_subparsers.add_parser(
        "role-drop",
        help = "Drop access to a role")
    ap.add_argument("-u", "--username", action = "store", default = "self",
                    help = "ID of user whose role is to be dropped"
                    " (optional, defaults to yourself)")
    ap.add_argument("role", action = "store",
                    help = "Role to drop")
    ap.set_defaults(func = _cmdline_role_drop)

    ap = arg_subparsers.add_parser(
        "user-ls",
        help = "List users known to the server (note you need "
        "admin role privilege to list users others than your own)")
    ap.add_argument("userid", action = "store",
                    default = None, nargs = "*",
                    help = "Users to list (default all)")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(none is a table, -v table with more details, "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.set_defaults(func = _cmdline_user_list)
