#! /usr/bin/env python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to deal with targets

import concurrent.futures
import logging

import tcfl.testcase
import tcfl.report_console
import tcfl.report_jinja2


def _target_release(target, force = False):
    server, rt = tcfl.target_c.get_server_rt_by_id(target)
    server.target_release(rt['id'], force)

def _cmdline_target_release(args):

    with concurrent.futures.ThreadPoolExecutor(len(args.target)) as ex:
        futures = {
            ex.submit(_target_release, target): target
            for target in args.target
        }
        for future in concurrent.futures.as_completed(futures):
            target = futures[future]
            try:
                _r = future.result()	# ignored, here for the exception
                logging.info("%s: released", target)
            except Exception as e:
                logging.critical("%s: error releasing: %s", target, e)
                continue


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "release", help = "Release ownership of a target")
    ap.add_argument(
        "-f", "--force", action = "store_true", default = False,
        help = "Force release of a target you don't own (only admins)")
    ap.add_argument(
        "target", metavar = "TARGET", action = "store", default = None,
        nargs = "+", help = "Target's name")
    ap.set_defaults(func = _cmdline_target_release)
