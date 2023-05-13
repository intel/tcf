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
