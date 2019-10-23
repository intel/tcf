#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging

import commonl
import tcfl
from . import msgid_c

def healthcheck_power_old(rtb, rt):
    print "Powering off"
    rtb.rest_tb_target_power_off(rt)
    print "Powered off"

    print "Querying power status"
    power = rtb.rest_tb_target_power_get(rt)
    if power != 0:
        msg = "Power should be 0, reported %d" % power
        raise Exception(msg)
    print "Power is reported correctly as %d" % power

    print "Powering on"
    rtb.rest_tb_target_power_on(rt)
    print "Powered on"

    print "Querying power status"
    power = rtb.rest_tb_target_power_get(rt)
    if power == 0:
        msg = "Power should be !0, reported %d" % power
        raise Exception(msg)
    print "Power is reported correctly as %d" % power

    print "power test passed"

def healthcheck_power(_rtb, rt):
    with msgid_c("cmdline"):
        class args_c(object):
            ticket = ''

        target = tcfl.tc.target_c.create_from_cmdline_args(args_c(), rt['id'])

        print "Powering off"
        target.power.off()
        print "Powered off"

        print "Querying power status"
        power = target.power.get()
        if power != False:
            msg = "Power should be False, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Powering on"
        target.power.on()
        print "Powered on"

        print "Querying power status"
        power = target.power.get()
        if power != True:
            msg = "Power should be True, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Power cycling"
        target.power.cycle()
        print "Power cycled"

        print "Power conmponents: listing"
        components = target.power.list()
        print "Power components: listed %s" \
            % " ".join("%s:%s" % (k, v) for k, v in components)

        print "Querying power status"
        power = target.power.get()
        if power != True:
            msg = "Power should be True, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Powering off"
        target.power.off()
        print "Powered off"

        print "Querying power status"
        power = target.power.get()
        if power != False:
            msg = "Power should be False, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "power test passed"


def healthcheck(args):
    rtb, rt = tcfl.ttb_client._rest_target_find_by_id(args.target)

    print "Acquiring"
    rtb.rest_tb_target_acquire(rt)
    print "Acquired"
    try:
        if 'power' in rt['interfaces']:
            healthcheck_power(rtb, rt)
        elif 'tt_power_control_mixin' in rt['interfaces']:
            healthcheck_power_old(rtb, rt)
    finally:
        print "Releasing"
        rtb.rest_tb_target_release(rt)
        print "Released"
    print "%s: healthcheck completed" % rt['id']

def argp_setup(arg_subparsers):
    ap = arg_subparsers.add_parser("healthcheck",
                                   help = "Do a very basic health check")
    commonl.cmdline_log_options(ap)
    ap.set_defaults(level = logging.ERROR)
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = healthcheck)
