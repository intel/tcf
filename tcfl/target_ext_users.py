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
import json
import logging
import pprint

import tabulate

from . import commonl
from . import ttb_client
from . import msgid_c

def _user_list(rtb, userids):
    result = {}
    if userids:
        for userid in userids:
            try:
                result.update(rtb.send_request("GET", "users/" + userid))
            except Exception as e:
                logging.error("%s: error getting info: %s", userid, e)
    else:
        result.update(rtb.send_request("GET", "users/"))
    return result

def _cmdline_user_list(args):
    with msgid_c("cmdline"):
        threads = {}
        tp = ttb_client._multiprocessing_pool_c(
            processes = len(ttb_client.rest_target_brokers))
        for rtb in sorted(ttb_client.rest_target_brokers.values()):
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
                for role, state in list(data['roles'].items()):
                    if state == "False":
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
    for rtb in ttb_client.rest_target_brokers.values():
        rtb.logout(args.username)

def _user_role(rtb, username, action, role):
    return rtb.send_request(
        "PUT", "users/" + username + "/" + action + "/" + role)

def _cmdline_role_gain(args):
    for rtb in ttb_client.rest_target_brokers.values():
        _user_role(rtb, args.username, "gain", args.role)

def _cmdline_role_drop(args):
    for rtb in ttb_client.rest_target_brokers.values():
        _user_role(rtb, args.username, "drop", args.role)

def _cmdline_setup(arg_subparsers):
    ap = arg_subparsers.add_parser(
        "user-list",
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
        help = "User to logout (defaults to current); to logout outhers "
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
