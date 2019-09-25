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


class sol_console_pc(ttbl.power.socat_pc, ttbl.console.generic_c):
    """
    Implement a serial port over IPMI's Serial-Over-Lan protocol

    This class implements two interfaces:

    - power interface: to start an IPMI SoL recorder in the
      background as soon as the target is powered on.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder and to pass data to the serial port
      from the read file. It is configured to to start *ipmitool* with
      the *sol activate* arguments which leaves it fowarding traffic
      back and forth.

      Anything read form the serial port is written to the
      *console-NAME.read* file and anything written to it is written
      to *console-NAME.write* file, which is sent to the serial port.

    - console interface: interacts with the console interface by
      exposing the data recorded in *console-NAME.read* file and
      writing to the *console-NAME.write* file.

    :params str hostname: name of the host where the IPMI BMC is
      located
    :params str username: username to login into the BMC
    :params str password: password to login into the BMC

    Look at :class:`ttbl.console.generic_c` for a description of
    *chunk_size* and *interchunk_wait*. This is in general needed when
    whatever is behind SSH is not doing flow control and we want the
    server to slow down sending things.

    For example, create an IPMI recoder console driver and insert it 
    into the power rail (its interface as power control makes it be 
    called to start/stop recording when the target powers on/off) and
    then it is also registered as the target's console:

    >>> sol0_pc = ttbl.console.serial_pc(console_file_name)
    >>>
    >>> ttbl.config.targets[name].interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         sol0_pc,
    >>>         ...
    >>>     )
    >>> ttbl.config.targets[name].interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         sol0 = sol0_pc,
    >>>         default = "sol0",
    >>>     )
    >>> )

    """
    def __init__(self, hostname, username, password, precheck_wait = 0.5,
                 chunk_size = 5, interchunk_wait = 0.1):
        assert isinstance(hostname, basestring)
        assert isinstance(username, basestring)
        assert isinstance(password, basestring)
        ttbl.console.generic_c.__init__(self, chunk_size = chunk_size,
                                        interchunk_wait = interchunk_wait)
        ttbl.power.socat_pc.__init__(
            self,
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            "EXEC:'/usr/bin/ipmitool -H %(hostname)s -U %(username)s -E"
            " -I lanplus sol activate',sighup,sigint,sigquit",
            precheck_wait = precheck_wait,
        )
        # pass those fields to the socat_pc templating engine
        self.kws['hostname'] = hostname
        self.kws['username'] = username
        self.kws['password'] = password
        self.env_add['IPMITOOL_PASSWORD'] = password

    def on(self, target, component):
        # if there is someone leftover reading, kick them out, there can
        # be only one
        env = dict(os.environ)
        env.update(self.env_add)
        subprocess.call(	# don't check, we don't really care
            [
                "/usr/bin/ipmitool", "-H", self.kws['hostname'],
                "-U", self.kws['username'], "-E",
                "-I", "lanplus", "sol", "deactivate",
                #"-N", "10", "usesolkeepalive" # dies frequently
            ],
            stderr = subprocess.STDOUT,
            bufsize = 0,
            shell = False,
            universal_newlines = False,
            env = env,
        )
        ttbl.power.socat_pc.on(self, target, component)

    def enable(self, target, component):
        return self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)
