#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Flash the target with fastboot
------------------------------

"""

import json

from . import tc
from . import ttb_client

def _rest_tb_target_fastboot_run(rtb, rt, parameters, ticket = ''):
    return rtb.send_request("POST", "targets/%s/fastboot/run" % rt['id'],
                            data = {
                                'parameters': json.dumps(parameters),
                                'ticket': ticket
                            })

def _rest_tb_target_fastboot_list(rtb, rt, ticket = ''):
    return rtb.send_request("GET", "targets/%s/fastboot/list" % rt['id'],
                            data = { 'ticket': ticket })

class fastboot(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run fastboot commands
    on the target via the server.

    Use :func:`run` to execute a command on the target:

    >>> target.fastboot.run("flash_pos", "partition_boot",
    >>>                     "/home/ttbd/partition_boot.pos.img")

    a target with the example configuration described in
    :class:`ttbl.fastboot.interface` would run the command::

      $ fastboot -s SERIAL flash partition_boot /home/ttbd/partition_boot.pos.img

    on the target.

    Note that which fastboot commands are allowed in the target is
    meant to be severily restricted via target-specific configuration
    to avoid compromising the system's security without compromising
    flexibility.

    You can list allowed fastboot commands with (from the example above)::

      $ tcf fastboot-list TARGETNAME
      flash: flash partition_boot ^(.+)$
      flash_pos: flash_pos partition_boot /home/ttbd/partition_boot.pos.img

    """

    def __init__(self, target):
        if not 'fastboot' in target.rt.get('interfaces', []):
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

    def run(self, command_name, *args):
        count = 0
        for arg in args:
            assert isinstance(arg, str), \
                "arg #%d to '%s' has to be a string, got %s" \
                % (count, command_name, type(arg).__name__)
            count += 1
        parameters = [ command_name ] + list(args)
        self.target.report_info("%s: running" % command_name, dlevel = 2)
        r = _rest_tb_target_fastboot_run(self.target.rtb, self.target.rt,
                                         parameters,
                                         ticket = self.target.ticket)
        self.target.report_info("%s: ran" % (command_name),
                                { 'diagnostics': r['diagnostics']},
                                dlevel = 1)

    def list(self):
        self.target.report_info("listing", dlevel = 1)
        r = _rest_tb_target_fastboot_list(
            self.target.rtb, self.target.rt, ticket = self.target.ticket)
        self.target.report_info("listed: %s" % r['commands'],
                                { 'diagnostics': r['diagnostics'] })
        return r['commands']


def cmdline_fastboot(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    _rest_tb_target_fastboot_run(rtb, rt,
                                 [ args.command_name ] + args.parameters,
                                 ticket = args.ticket)

def cmdline_fastboot_list(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    r = _rest_tb_target_fastboot_list(rtb, rt, ticket = args.ticket)
    for command, params in r['commands'].items():
        print("%s: %s" % (command, params))


def cmdline_setup(argsp):
    ap = argsp.add_parser("fastboot", help = "Run a fastboot command")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("command_name", metavar = "COMMAND", action = "store",
                    type = str, help = "Name of the command to run")
    ap.add_argument("parameters", metavar = "PARAMETERS", action = "store",
                    nargs = "*", default = [],
                    help = "Parameters to the fastboot command")
    ap.set_defaults(func = cmdline_fastboot)

    ap = argsp.add_parser("fastboot-list", help = "List allowed fastboot "
                          "commands")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = cmdline_fastboot_list)
