#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging

from . import commonl
import tcfl


def healthcheck_power(rtb, rt):
    print("Powering off")
    rtb.rest_tb_target_power_off(rt)
    print("Powered off")

    print("Querying power status")
    power = rtb.rest_tb_target_power_get(rt)
    if power != 0:
        msg = "Power should be 0, reported %d" % power
        raise Exception(msg)
    print("Power is reported correctly as %d" % power)

    print("Powering on")
    rtb.rest_tb_target_power_on(rt)
    print("Powered on")

    print("Querying power status")
    power = rtb.rest_tb_target_power_get(rt)
    if power == 0:
        msg = "Power should be !0, reported %d" % power
        raise Exception(msg)
    print("Power is reported correctly as %d" % power)

    print("power test passed")


def healthcheck(args):
    rtb, rt = tcfl.ttb_client._rest_target_find_by_id(args.target)

    print("Acquiring")
    rtb.rest_tb_target_acquire(rt)
    print("Acquired")
    try:
        healthcheck_power(rtb, rt)
    finally:
        print("Releasing")
        rtb.rest_tb_target_release(rt)
        print("Released")
    print("%s: healthcheck completed" % rt['id'])

def argp_setup(arg_subparsers):
    ap = arg_subparsers.add_parser("healthcheck",
                                   help = "List testcases")
    commonl.cmdline_log_options(ap)
    ap.set_defaults(level = logging.ERROR)
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = healthcheck)
