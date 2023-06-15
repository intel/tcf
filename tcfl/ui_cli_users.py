#! /usr/bin/python3
#
# Copyright (c) 2017-23 Intel Corporation
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

- Gain or drop roles::

    $ tcf role-drop ROLENAME
    $ tcf role-gain ROLENAME

- List users::

    $ tcf user-ls

"""

import argparse
import collections
import getpass
import json
import logging
import os
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_users")



def _credentials_get_global(cli_args: argparse.Namespace):
    # env general
    user_env = os.environ.get("TCF_USER", None)
    password_env = os.environ.get("TCF_PASSWORD", None)

    # from commandline
    user_cmdline = cli_args.username
    password_cmdline = cli_args.password

    # default to what came from environment
    user = user_env
    password = password_env
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
                " TCF_USER[_<AKA>]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain login name and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_<AKA>]")
        user = input(f'Login for all servers [{getpass.getuser()}]'
                     ' (use *ask* for server-specific): ')
        if user == "":	# default to LOGIN name
            user = getpass.getuser()
            print("I: defaulting to login name '{user}'")
        elif user == "ask":
            user = None

    if user and not password:
        if cli_args.quiet:
            raise RuntimeError(
                "Cannot obtain password and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_<AKA>]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain password and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_<AKA>]")
        password = getpass.getpass(f"Password for {user} (on all servers): ")
    return user, password



def _credentials_get(domain: str, aka: str, user: str, password: str,
                     cli_args: argparse.Namespace):
    # server specific
    user_env_aka = os.environ.get("TCF_USER_" + aka, None)
    password_env_aka = os.environ.get("TCF_PASSWORD_" + aka, None)

    # override with server specific from envrionment
    if user_env_aka:
        user = user_env_aka
    if password_env_aka:
        password = password_env_aka
    # we don't override from the commandline, since we did it in
    # _credentials_get_global()

    if not user:
        if cli_args.quiet:
            raise RuntimeError(
                "Cannot obtain login name and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_<AKA>]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain login name and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_<AKA>]")
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
    user, password = _credentials_get_global(cli_args)
    credentials = {}
    for server_name, server in servers.items():
        credentials[server.aka] = \
            _credentials_get(server.url, server.aka, user, password, cli_args)

    r = tcfl.servers.run_fn_on_each_server(
        servers, _login, credentials,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)
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
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)
    # r now is a dict keyed by server_name of tuples usernames,
    # exception
    for server_name, ( _, e ) in r.items():
        # we get 401 if we are logged out already...ignore
        if e and getattr(e, "status_code", None) != 401:
            logger.error("can't log out of %s: %s",
                         server_name, e)



def _user_role(server_name, server,
               cli_args: argparse.Namespace,
               action):
    if action == "gain":
        action_msg = ( "gaining", "gained" )
    elif action == "drop":
        action_msg = ( "dropping", "dropped" )
    else:
        raise AssertionError(f"invalid action {action}")
    try:
        r = server.send_request(
            "PUT", "users/" + cli_args.username + "/" + action + "/" + cli_args.role)
        logger.info(
            "%s: %s role %s for user %s",
            server_name, action_msg[1], cli_args.role,cli_args.username)
    except Exception as e:
        logger.error(
            "%s: error %s role %s for user %s: %s",
            server_name, action_msg[0], cli_args.role,cli_args.username, e,
            exc_info = cli_args.traces)
        raise


def _cmdline_role_gain(cli_args: argparse.Namespace):

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.server_c.servers

    tcfl.servers.run_fn_on_each_server(
        servers, _user_role, cli_args, "gain",
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)


def _cmdline_role_drop(cli_args: argparse.Namespace):

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.server_c.servers

    tcfl.servers.run_fn_on_each_server(
        servers, _user_role, cli_args, "drop",
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)



def _user_list(_server_name, server,
               cli_args: argparse.Namespace):
    userids = cli_args.userid
    result = {}
    if not userids:
        r = server.send_request("GET", "users/")
        return r

    for userid in userids:
        result.update(server.send_request("GET", "users/" + userid))
    return result


def _cmdline_user_list(cli_args: argparse.Namespace):

    result = tcfl.servers.run_fn_on_each_server(
        tcfl.server_c.servers, _user_list, cli_args,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)

    # so now result is a dictionary of SERVER: ( DATA, EXCEPTION ),
    # where DATA is dictionaries of USERNAME: USERDATA
    #
    # we are going to rearrange it by user, and sort it, so it becomes
    # USER: { SERVER: USERDATA } and also report errors

    r_unsorted = collections.defaultdict(dict)
    for server_name in sorted(result.keys()):
        data, e = result[server_name]
        if e:
            logging.error("%s: can't get users: %s",
                          server_name, e)
            continue
        for userid, user_data in data.items():
            r_unsorted[userid][server_name] = user_data

    # sort the usernames, without taking case into account
    r = {}
    for userid in sorted(r_unsorted.keys(),
                         key = str.casefold):
        r[userid] = r_unsorted[userid]

    verbosity = cli_args.verbosity - cli_args.quietosity
    if verbosity < 0:
        print("\n".join(r.keys()))
    elif verbosity == 0:
        import tabulate
        headers = [
            "UserID",
            "Server",
        ]
        table = []
        for userid, servers in r.items():
            table.append([ userid, "\n".join(servers.keys()) ])
        print(tabulate.tabulate(table, headers = headers))
    elif cli_args.verbosity == 1:
        import tabulate
        headers = [
            "UserID",
            "Server",
            "Roles",
        ]
        table = []
        for userid, servers in r.items():
            for server_name, user_data in servers.items():
                rolel = []
                for role, state in user_data.get('roles', {}).items():
                    if state == False:
                        rolel.append(role + " (dropped)")
                    else:
                        rolel.append(role)
                table.append([
                    userid, server_name, "\n".join(rolel) ])
        print(tabulate.tabulate(table, headers = headers))
    elif cli_args.verbosity == 2:
        # This format uses periods to separate dictionary keys, so we
        # need to make safe (period less) the username and the
        # hostname, somehow. The username is already part of the data
        # structure anyway, but for the server name we need to add a
        # new field
        #
        # We can lose some info like this in the (unlikely) even that
        # we have a user called hello@domain.com and another
        # hello.domain.com...thou shall use JSON. FIXME: workaround by
        # adding a 'seen' set and appending a counter if
        # seen. Framework it.
        r_safe = {}
        for userid, servers in r.items():
            userid_safe = commonl.name_make_safe(userid)
            r_safe[userid_safe] = {}
            for server_name, user_data in servers.items():
                server_safe = commonl.name_make_safe(server_name)
                r_safe[userid_safe][server_safe] = user_data
                r_safe[userid_safe][server_safe]['url'] = server_name
        commonl.data_dump_recursive(r_safe)
    elif cli_args.verbosity == 3:
        import pprint
        pprint.pprint(r, indent = True)
    elif cli_args.verbosity >= 4:
        json.dump(r, sys.stdout,
                  skipkeys = True, indent = True)



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
        "--serialize",
        action = "store_const", dest = "parellization_factor", const = 1,
        help = "Serialize (don't parallelize) the operation on"
        " multiple targets")
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
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


    ap = arg_subparser.add_parser(
        "role-gain",
        help = "Gain access to a role which has been dropped")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "-u", "--username", action = "store", default = "self",
        help = "ID of user whose role is to be dropped"
        " (optional, defaults to yourself)")
    ap.add_argument(
        "--serialize",
        action = "store_const", dest = "parellization_factor", const = 1,
        help = "Serialize (don't parallelize) the operation on"
        " multiple targets")
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "role", action = "store",
        help = "Role to gain")
    ap.set_defaults(func = _cmdline_role_gain)


    ap = arg_subparser.add_parser(
        "role-drop",
        help = "Drop access to a role")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "-u", "--username", action = "store", default = "self",
        help = "ID of user whose role is to be dropped"
        " (optional, defaults to yourself)")
    ap.add_argument(
        "--serialize",
        action = "store_const", dest = "parellization_factor", const = 1,
        help = "Serialize (don't parallelize) the operation on"
        " multiple targets")
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument(
        "role", action = "store",
        help = "Role to drop")
    ap.set_defaults(func = _cmdline_role_drop)


    ap = arg_subparser.add_parser(
        "user-ls",
        help = "List users known to the server (note you need "
        "admin role privilege to list users others than your own)")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "--serialize",
        action = "store_const", dest = "parellization_factor", const = 1,
        help = "Serialize (don't parallelize) the operation on"
        " multiple targets")
    ap.add_argument(
        "--parallelization-factor",
        action = "store", type = int, default = -4,
        help = "(advanced) parallelization factor")
    ap.add_argument("userid", action = "store",
                    default = None, nargs = "*",
                    help = "Users to list (default all)")
    ap.set_defaults(func = _cmdline_user_list)
