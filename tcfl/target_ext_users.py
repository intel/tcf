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


def _cmdline_setup_advanced(arg_subparsers):
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



def _cmdline_setup(arg_subparsers):
    pass
