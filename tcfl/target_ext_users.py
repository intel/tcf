#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Utilities to see user's information
-----------------------------------

"""
from __future__ import print_function
import concurrent.futures
import json
import logging
import pprint
import urllib3

import requests
import tabulate

import commonl
import tcfl
from . import tc
from . import ttb_client
from . import msgid_c


def _user_list(rtb, userids):
    result = {}
    if userids:
        for userid in userids:
            try:
                result.update(rtb.send_request("GET", "users/" + userid))
            except Exception as e:
                logging.error("%s: error getting user's info: %s", userid, e)
    else:
        try:
            result.update(rtb.send_request("GET", "users/"))
        except Exception as e:
            logging.error("error getting all user info: %s", e)
    return result


def _cmdline_user_list(args):
    with msgid_c("cmdline"):
        threads = {}
        tp = ttb_client._multiprocessing_pool_c(
            processes = len(ttb_client.rest_target_brokers))
        if not ttb_client.rest_target_brokers:
            logging.error("E: no servers available, did you configure?")
            return
        for rtb in sorted(ttb_client.rest_target_brokers.values(), key = str):
            threads[rtb] = tp.apply_async(_user_list, (rtb, args.userid))
        tp.close()
        tp.join()

        result = {}
        for rtb, thread in threads.items():
            result[rtb.aka] = thread.get()

    if args.verbosity == 0:
        headers = [
            "Server",
            "UserID",
        ]
        table = []
        for rtb, r in result.items():
            for userid, data in r.items():
                table.append([ rtb, userid ])
        print((tabulate.tabulate(table, headers = headers)))
    elif args.verbosity == 1:
        headers = [
            "Server",
            "UserID",
            "Roles",
        ]
        table = []
        for rtb, r in result.items():
            for userid, data in r.items():
                rolel = []
                for role, state in data.get('roles', {}).items():
                    if state == False:
                        rolel.append(role + " (dropped)")
                    else:
                        rolel.append(role)
                table.append([
                    rtb, userid, "\n".join(rolel) ])
        print((tabulate.tabulate(table, headers = headers)))
    elif args.verbosity == 2:
        commonl.data_dump_recursive(result)
    elif args.verbosity == 3:
        pprint.pprint(result)
    elif args.verbosity >= 4:
        print(json.dumps(result, skipkeys = True, indent = 4))


def _cmdline_logout(args):
    """
    Logout user from all the servers
    """
    rtbs = ttb_client.rest_target_brokers.values()
    with concurrent.futures.ThreadPoolExecutor(len(rtbs)) as executor:
        rs = executor.map(
            lambda rtb: rtb.logout(args.username),
            rtbs)


def _user_role(rtb, username, action, role):
    try:
        return rtb.send_request(
            "PUT", "users/" + username + "/" + action + "/" + role)
    except ttb_client.requests.exceptions.HTTPError as e:
        logging.error(f"{rtb.aka}: {e} (ignored)")


def _cmdline_role_gain(args):
    rtbs = ttb_client.rest_target_brokers.values()
    with concurrent.futures.ThreadPoolExecutor(len(rtbs)) as executor:
        rs = executor.map(
            lambda rtb: _user_role(rtb, args.username, "gain", args.role),
            rtbs)
    for r in rs:	# wait until complete by reading the values
        try:
            _ = rs[r]
        except Exception as e:
            logging.warning(f"ignoring error {e}")


def _cmdline_role_drop(args):
    rtbs = ttb_client.rest_target_brokers.values()
    with concurrent.futures.ThreadPoolExecutor(len(rtbs)) as executor:
        rs = executor.map(
            lambda rtb: _user_role(rtb, args.username, "drop", args.role),
            rtbs)
    for r in rs:	# wait until complete by reading the values
        try:
            _ = rs[r]
        except Exception as e:
            logging.warning(f"ignoring error {e}")



def _cmdline_servers(args):
    # collect data in two structures, makes it easier to print at
    # different verbosity levels...yah, lazy
    r = []
    d = {}
    rtbs = {}		# COMPAT
    servers = {}	# new stuff

    if args.targets:
        rtb_list = {}
        for target_name in args.targets:
            try:
                target = tc.target_c.create_from_cmdline_args(
                    args, target_name, extensions_only = [])
                rtb_list[target.rtb.aka] = target.rtb
                server = tcfl.server_c.servers[target.rtb.parsed_url.geturl()]
                servers[server.url] = server
            except IndexError as e:
                logging.error("%s: invalid target" % target_name)
    else:
        rtb_list = ttb_client.rest_target_brokers
        servers = tcfl.server_c.servers

    for name, rtb in rtb_list.items():
        username = "n/a"
        try:
            if args.verbosity >= 0:
                # FIXME: this should be parallelized
                # we don't need this if verbosity < 0 and it takes time
                username = rtb.logged_in_username()
        # FIXME: we need a base exception for errors from the API
        except (
                requests.exceptions.ConnectionError,
                ttb_client.requests.HTTPError,
                urllib3.exceptions.MaxRetryError,
                RuntimeError
        ) as e:
            logging.warning("%s: can't reach server: %s", name, e)
            username = "n/a"
        server = servers[rtb.parsed_url.geturl()]
        r.append(( rtb.aka, str(rtb), username, server.origin ))
        d[rtb.aka] = dict(url = str(rtb), username = username,
                          origin = server.origin)
        rtbs[rtb.aka] = rtb

    verbosity = args.verbosity - args.quietosity

    if verbosity < -1:
        for aka in d:
            print(aka)
    elif verbosity == -1:
        for rtb in rtbs.values():
            print(rtb.parsed_url.hostname)
    elif verbosity == 0:
        for aka, url, username, _origin in r:
            print(aka, url, username)
    elif verbosity in ( 1, 2 ):
        headers = [
            "Server",
            "URL",
            "UserID",
            "Origin"
        ]
        print(tabulate.tabulate(r, headers = headers))
    elif verbosity == 3:
        commonl.data_dump_recursive(d)
    elif verbosity == 4:
        pprint.pprint(d)
    elif verbosity >= 5:
        print(json.dumps(d, skipkeys = True, indent = 4))


def _cmdline_servers_flush(_args):
    log_sd = logging.getLogger("server-discovery")
    log_sd.setLevel(logging.INFO)
    tcfl.server_c.flush()


def _cmdline_servers_discover(args):
    # adjust logging level of server-discovery
    # -qqqq -vvvvvv -> -vvv
    verbosity = args.verbosity - args.quietosity
    levels = [ logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG ]
    # now translate that to logging's module format
    # server-discovery -> tcfl.log_sd
    log_sd = logging.getLogger("server-discovery")
    if verbosity >= len(levels):
        verbosity = len(levels) - 1
    log_sd.setLevel(levels[verbosity])

    if args.flush:
        log_sd.warning("flushing cached server list (--flush given)")
        tcfl.server_c.flush()
    else:
        log_sd.warning("keeping cached server list (--flush not given)")
    current_server_count = len(tcfl.server_c.servers)
    log_sd.warning(f"starting with {current_server_count} server/s")
    if log_sd.isEnabledFor(logging.DEBUG):
        count = 0
        for url, _server in tcfl.server_c.servers.items():
            log_sd.debug(f"starting server[{count}]: {url}")
            count += 1

    tcfl.server_c.discover(
        ssl_ignore = args.ssl_ignore,
        seed_url = args.items,
        seed_port = args.port,
        herds_exclude = args.herd_exclude,
        herds_include = args.herd_include,
        loops_max = args.iterations,
        max_cache_age = 0,	        # force discoverying all known servers
        ignore_cache = args.flush,
        zero_strikes_max = args.zero_strikes_max,
        origin = "command line",
    )
    log_sd.warning(f"found {len(tcfl.server_c.servers)} server/s")


def _cmdline_setup(arg_subparsers):
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

    ap = arg_subparsers.add_parser(
        "logout",
        help = "Log user out of the servers brokers")
    ap.add_argument(
        "username", nargs = '?', action = "store", default = None,
        help = "User to logout (defaults to current); to logout others "
        "*admin* role is needed")
    ap.set_defaults(func = _cmdline_logout)

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
        "servers",
        help = "List configured/discovered servers")
    commonl.argparser_add_aka(arg_subparsers, "servers", "server-ls")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q list of shortname, url and username, "
        "-qq the hostnames, -qqq the shortnames"
        "; all one per line")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 1,
        help = "Increase verbosity of information to display "
        "(none is a table, -v table with more details, "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.add_argument(
        "targets", metavar = "TARGETNAMES", nargs = "*",
        action = "store", default = None,
        help = "List of targets for which we want to find server"
        " information (optional; defaults to all)")
    ap.set_defaults(func = _cmdline_servers)

    ap = arg_subparsers.add_parser(
        "servers-flush",
        help = "Flush currently cached/known servers")
    ap.set_defaults(func = _cmdline_servers_flush)

    ap = arg_subparsers.add_parser(
        "servers-discover",
        help = "Discover servers")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q list of shortname, url and username, "
        "-qq the hostnames, -qqq the shortnames"
        "; all one per line")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 1,
        help = "Increase verbosity of progress info [%(default)d] ")
    ap.add_argument(
        "--iterations", "-e", type = int, metavar = "MAX_LOOPS",
        action = "store", default = 10,
        help = "Maximum number of iterations [%(default)d]")
    ap.add_argument(
        "--zero-strikes-max", "-z", type = int, metavar = "MAX",
        action = "store", default = 4,
        help = "Stop after this many iterations [%(default)d] finding"
        " no new servers")
    ap.add_argument(
        "--flush", "-f", action = 'store_true', default = False,
        help = "Flush existing cached entries before")
    ap.add_argument(
        "--ssl-ignore", "-s", action = 'store_false', default = True,
        help = "Default to ignore SSL validation [False]")
    ap.add_argument(
        "--port", "-p", action = 'store', type = int, default = 5000,
        help = "Default port when none specified %(default)s")
    ap.add_argument(
        "--herd-exclude", "-x", metavar = "HERDNAME", action = 'append',
        default = [], help = "Exclude herd (can be given multiple times)")
    ap.add_argument(
        "--herd-include", "-i", metavar = "HERDNAME", action = 'append',
        default = [], help = "Include herd (can be given multiple times)")
    ap.add_argument(
        "items", metavar = "HOSTNAME|URL", nargs = "*",
        action = "store", default = [],
        help = "List of URLs or hostnames to seed discovery"
        f" [{' '.join(tcfl.server_c._seed_default.keys())}]")
    ap.set_defaults(func = _cmdline_servers_discover)
