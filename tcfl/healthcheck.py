#! /usr/bin/env python3
#
# Copyright (c) 2017-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import argparse
import traceback

import tcfl.tc

def _healthcheck(target, cli_args):

    if cli_args.interfaces == []:
        # no interface list give; scan the list of interfaces the
        # target exposes, starting with "power" (always)
        cli_args.interfaces.append("power")

        # list extensions/interfaces w/ healthcheck
        for attr, value in target.__dict__.items():
            if isinstance(value, tcfl.tc.target_extension_c) \
               and hasattr(value, "_healthcheck") \
               and attr != "power":	# we did this first
                cli_args.interfaces.append(attr)


    for interface_name in cli_args.interfaces:
        interface = getattr(target, interface_name, None)
        if interface == None:
            target.report_blck("%s: non-existing interface" % interface_name)
            continue
        if not isinstance(interface, tcfl.tc.target_extension_c):
            target.report_blck(
                "%s: interface not a real interface (type %s)"
                % (interface_name, type(interface)))
            continue

        if interface == "power" and not hasattr(target, "power"):
            target.report_info("WARNING: No power control interface")

        target.report_info(
            "HEALTHCHECK for %s interface" % interface_name, level = 0)
        try:
            interface._healthcheck()
        except Exception as e:
            target.report_blck(
                "HEALTHCHECK for %s: exception" % interface_name,
                dict(exception = e, trace = traceback.format_exc()),
                alevel = 0)

    target.report_pass("HEALTHCHECK completed")


def _target_healthcheck(target, cli_args: argparse.Namespace):
    tcfl.tc.report_driver_c.add(		# FIXME: hack console driver
        tcfl.report_console.driver(0, None),
        name = "console")

    # FIXME: this needs to be moved (when the orchestrator is improved
    # done) to just run with tcf run
    allocid = None
    try:
        if cli_args.allocid == None:
            target.report_info("allocating")
            allocid, _state, _group_allocated = \
                tcfl.target_ext_alloc._alloc_targets(
                    target.rtb, { "group": [ target.id ] },
                    preempt = cli_args.preempt,
                    queue = False, priority = cli_args.priority,
                    reason = "healthcheck")
            target.report_pass("allocated %s" % allocid)
        else:
            target.report_info("using existing allocation")
        _healthcheck(target, cli_args)
    finally:
        if allocid:
            tcfl.target_ext_alloc._delete(target.rtb, allocid)
