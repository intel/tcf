#! /usr/bin/python3
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
from . import msgid_c


class extension(tc.target_extension_c):
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

      $ tcf fastboot-ls TARGETNAME
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
        self.target.report_info("%s: running" % command_name, dlevel = 2)
        r = self.target.ttbd_iface_call(
            "fastboot", "run", method = "PUT",
            parameters = [ command_name ] + list(args))
        self.target.report_info("%s: ran" % (command_name),
                                { 'diagnostics': r['diagnostics']},
                                dlevel = 1)

    def list(self):
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call("fastboot", "list", method = "GET")
        self.target.report_info("listed: %s" % r['commands'],
                                { 'diagnostics': r['diagnostics'] })
        return r['commands']
