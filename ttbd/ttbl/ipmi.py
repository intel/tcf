#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import os
import time

import usb.core
import usb.util

import commonl
import commonl.requirements
import ttbl
import pyghmi.ipmi.command

class pci(ttbl.tt_power_control_impl):

    class notfound_e(ValueError):
        pass

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
    >>>              ttbl.ipmi.pci("server1.internal.net", "bmc_admin", "secret"),
    >>>              ttbl.pc.delay(5),
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
        # setup for this process
        if self.bmc == None:
            self.bmc = pyghmi.ipmi.command.Command(self.bmc_hostname,
                                                   self.user, self.password)

    def power_on_do(self, target):
        self._setup()
        result = self.bmc.set_power('on', wait = True)
        target.log.error("DEBUG: off returned %s" % result)

    def power_off_do(self, target):
        self._setup()
        result = self.bmc.set_power('off', wait = True)
        target.log.error("DEBUG: off returned %s" % result)

    def power_get_do(self, target):
        self._setup()
        data = self.bmc.get_power()
        state = data.get('power_state', None)
        if state == 'on':
            return True
        elif state == 'off':
            return False
        else:
            target.log.error("IPMI get_power() call returned no state")
            return None
