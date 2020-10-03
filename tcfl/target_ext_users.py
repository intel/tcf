#! /usr/bin/python2
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
import json
import logging
import pprint

import tabulate

import commonl
import tc
import ttb_client
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
        for rtb in sorted(ttb_client.rest_target_brokers.itervalues()):
            threads[rtb] = tp.apply_async(_user_list, (rtb, args.userid))
        tp.close()
        tp.join()

        result = {}
        for rtb, thread in threads.iteritems():
            result[rtb.aka] = thread.get()

    if args.verbosity == 0:
        headers = [
            "Server",
            "UserID",
        ]
        table = []
        for rtb, r in result.iteritems():
            for userid, data in r.iteritems():
                table.append([ rtb, userid ])
        print(tabulate.tabulate(table, headers = headers))
    elif args.verbosity == 1:
        headers = [
            "Server",
            "UserID",
            "Roles",
        ]
        table = []
        for rtb, r in result.iteritems():
            for userid, data in r.iteritems():
                rolel = []
                for role, state in data['roles'].items():
                    if state == False:
                        rolel.append(role + " (dropped)")
                    else:
                        rolel.append(role)
                table.append([
                    rtb, userid, "\n".join(rolel) ])
        print(tabulate.tabulate(table, headers = headers))
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
    for rtb in ttb_client.rest_target_brokers.itervalues():
        rtb.logout(args.username)

def _user_role(rtb, username, action, role):
    return rtb.send_request(
        "PUT", "users/" + username + "/" + action + "/" + role)

def _cmdline_role_gain(args):
    for rtb in ttb_client.rest_target_brokers.itervalues():
        _user_role(rtb, args.username, "gain", args.role)

def _cmdline_role_drop(args):
    for rtb in ttb_client.rest_target_brokers.itervalues():
        _user_role(rtb, args.username, "drop", args.role)


def _cmdline_servers(args):
    # collect data in two structures, makes it easier to print at
    # different verbosity levels...yah, lazy
    r = []
    d = {}
    rtbs = {}

    if args.targets:
        rtb_list = {}
        for target_name in args.targets:
            try:
                target = tc.target_c.create_from_cmdline_args(
                    args, target_name, extensions_only = [])
                rtb_list[target.rtb.aka] = target.rtb
            except IndexError as e:
                logging.error("%s: invalid target" % target_name)
    else:
        rtb_list = ttb_client.rest_target_brokers

    for name, rtb in rtb_list.items():
        username = "n/a"
        try:
            if args.verbosity >= 0:
                # FIXME: this should be parallelized
                # we don't need this if verbosity < 0 and it takes time
                username = rtb.logged_in_username()
        # FIXME: we need a base exception for errors from the API
        except ( ttb_client.requests.HTTPError, RuntimeError):
            username = "n/a"
        r.append(( rtb.aka, str(rtb), username ))
        d[rtb.aka] = dict(url = str(rtb), username = username)
        rtbs[rtb.aka] = rtb

    verbosity = args.verbosity - args.quietosity

    if verbosity < -1:
        for aka in d:
            print(aka)
    elif verbosity == -1:
        for rtb in rtbs.values():
            print(rtb.parsed_url.hostname)
    elif verbosity == 0:
        for aka, url, username in r:
            print(aka, url, username)
    elif verbosity in ( 1, 2 ):
        headers = [
            "Server",
            "URL",
            "UserID",
        ]
        print(tabulate.tabulate(r, headers = headers))
    elif verbosity == 3:
        commonl.data_dump_recursive(d)
    elif verbosity == 4:
        pprint.pprint(d)
    elif verbosity >= 5:
        print(json.dumps(d, skipkeys = True, indent = 4))


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
        help = "List configured servers")
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
