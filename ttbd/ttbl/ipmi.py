#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Controlling targets via IPMI
----------------------------

This module implements multiple objects that can be used to control a
target's power or serial console via IPMI.

"""

import logging
import os
import pprint
import subprocess
import time

import commonl
import commonl.requirements
import ttbl

import pyghmi.ipmi.command

class pci(ttbl.tt_power_control_impl):

    """
    Power controller to turn on/off a server via IPMI

    :param str bmc_hostname: host name or IP address of the BMC
      controller for the host whose power is to be controller.
    :param str user: (optional) username to use to login
    :param str password: (optional) password to use to login

    This is normally used as part of a power rail setup, where an
    example configuration in /etc/ttbd-production/conf_*.py that would
    configure the power switching of a machine that also has a serial
    port would look like:

    >>> ttbl.config.target_add(
    >>>      ttbl.tt.tt_serial(
    >>>          "machine1",
    >>>          power_control = [
    >>>              ttbl.cm_serial.pc(),
    >>>              ttbl.ipmi.pci("server1.internal.net", 
    >>>                            "bmc_admin", "secret"),
    >>>          ],
    >>>          serial_ports = [
    >>>              "pc",
    >>>              { "port": "/dev/tty-machine1", "baudrate": 115200 },
    >>>          ]),
    >>>     tags = {
    >>>         'linux': True,
    >>>         'bsp_models': { 'x86_64': None },
    >>>         'bsps': {
    >>>             'x86_64': {
    >>>                 'linux': True,
    >>>                 'console': 'x86_64',
    >>>             }
    >>>         },
    >>>     },
    >>>     target_type = "Brand Model")

    .. warning:: putting BMCs on an open network is not a good idea;
                 it is recommended they are only exposed to an
                  :ref:`infrastructure network <separated_networks>`

    """
    def __init__(self, bmc_hostname, user = None, password = None):
        ttbl.tt_power_control_impl.__init__(self)
        self.bmc_hostname = bmc_hostname
        self.user = user
        self.password = password
        self.bmc = None

    def _setup(self):
        # this can run in multiple processes, so make sure this is
        # setup for this process each time we connect, because we
        # don't know how long this is going to be open and the session
        # expires
        self.bmc = pyghmi.ipmi.command.Command(self.bmc_hostname,
                                               self.user, self.password)

    def power_on_do(self, target):
        self._setup()
        result = self.bmc.set_power('on', wait = True)
        target.log.info("ipmi %s@%s on returned %s"
                        % (self.user, self.bmc_hostname, result))

    def power_off_do(self, target):
        self._setup()
        result = self.bmc.set_power('off', wait = True)
        target.log.info("ipmi %s@%s off returned %s"
                        % (self.user, self.bmc_hostname, result))

    def power_get_do(self, target):
        self._setup()
        data = self.bmc.get_power()
        target.log.info("ipmi %s@%s get_power returned %s"
                        % (self.user, self.bmc_hostname,
                           pprint.pformat(data)))
        state = data.get('powerstate', None)
        if state == 'on':
            return True
        elif state == 'off':
            return False
        else:
            target.log.info("ipmi %s@%s get_power returned no state: %s"
                            % (self.user, self.bmc_hostname,
                               pprint.pformat(data)))
            return None

class pci_ipmitool(ttbl.tt_power_control_impl):
    """
    Power controller to turn on/off a server via IPMI

    Same as :class:`pci`, but executing *ipmitool* in the shell
    instead of using a Python library.

    """
    def __init__(self, bmc_hostname, user = None, password = None):
        ttbl.tt_power_control_impl.__init__(self)
        self.bmc_hostname = bmc_hostname
        self.bmc = None
        self.env = dict()
        # If I change the argument order, -E doesn't work ok and I get
        # password asked in the command line
        self.cmdline = [
            "ipmitool",
            "-H", bmc_hostname
        ]
        if user:
            self.cmdline += [ "-U", user ]
        self.cmdline += [ "-E", "-I", "lanplus" ]
        if password:
            self.env['IPMI_PASSWORD'] = password

    def _run(self, target, command):
        try:
            result = subprocess.check_output(
                self.cmdline + command, env = self.env, shell = False,
                stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error("ipmitool %s failed: %s"
                             % (" ".join(command), e.output))
            raise
        return result

    def power_on_do(self, target):
        result = self._run(target, [ "chassis", "power", "on" ])
        target.log.info("on returned %s" % result)

    def power_off_do(self, target):
        result = self._run(target, [ "chassis", "power", "off" ])
        target.log.info("off returned %s" % result)

    def power_get_do(self, target):
        result = self._run(target, [ "chassis", "power", "status" ])
        target.log.info("status returned %s" % result)
        if 'Chassis Power is on' in result:
            return True
        elif 'Chassis Power is off' in result:
            return False
        target.log.error("ipmtool state returned unknown message: %s"
                         % result)
        return None
