#! /usr/bin/python3
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
import numbers
import os
import pprint
import subprocess
import time

import commonl
import ttbl.power
import ttbl.console

class pci(ttbl.power.impl_c):
    """
    Power controller to turn on/off a server via IPMI

    Same as :class:`pci`, but executing *ipmitool* in the shell
    instead of using a Python library.

    :param str hostname: BMC location
      *[USERNAME[:PASSWORD]]@hostname.com*; note *PASSWORD* can be the
      bare password or a string that indicates how to get it; refer to
      the argument *password* for :func:`commonl.password_get`.

    :param int ipmi_timeout: seconds to wait for IPMI response (will be
      passed to *ipmitool*'s *-N* option
    :param int ipmi_retries: times to retry the IPMI operation (will be
      passed to *ipmitool*'s *-R* option.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, bmc_hostname, ipmi_timeout = 10, ipmi_retries = 3,
                 extra_ipmitool_cmdline = None,
                 **kwargs):
        ttbl.power.impl_c.__init__(self, paranoid = True, **kwargs)
        user, password, hostname \
            = commonl.split_user_pwd_hostname(bmc_hostname)
        commonl.assert_none_or_list_of_strings(
            extra_ipmitool_cmdline, "extra_ipmitool_cmdline",
            "command line option")
        self.hostname = hostname
        self.user = user
        self.bmc = None
        self.env = dict()
        # If I change the argument order, -E doesn't work ok and I get
        # password asked in the command line
        self.cmdline = [
            "ipmitool",
            "-N", "%d" % ipmi_timeout,
            "-R", "%d" % ipmi_retries,
            "-H", hostname
        ]
        if user:
            self.cmdline += [ "-U", user ]
        self.cmdline += [ "-E", "-I", "lanplus" ]
        if extra_ipmitool_cmdline:
            self.cmdline += extra_ipmitool_cmdline
        if password:
            self.env['IPMI_PASSWORD'] = password
        self.paranoid_get_samples = 3
        self.timeout = 30
        self.wait = 2

    def _run(self, target, command):
        try:
            result = subprocess.check_output(
                self.cmdline + command, env = self.env, shell = False,
                stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            msg = "ipmitool %s failed: %s" % (
                " ".join(command), e.output)
            target.log.error(msg)
            raise self.error_e(msg)
        return result.rstrip()	# remove trailing NLs


    def on(self, target, _component):
        self._run(target, [ "chassis", "power", "on" ])

    def off(self, target, _component):
        self._run(target, [ "chassis", "power", "off" ])

    def get(self, target, component):
        result = self._run(target, [ "chassis", "power", "status" ])
        if b'Chassis Power is on' in result:
            return True
        elif b'Chassis Power is off' in result:
            return False
        target.log.error("%s: ipmtool state returned unknown message: %s"
                         % (component, result))
        return None

    def pre_power_pos_setup(self, target):
        """
        If target's *pos_mode* is set to *pxe*, tell the BMC to boot
        off the network.

        This is meant to be use as a pre-power-on hook (see
        :class:`ttbl.power.interface` and
        :data:`ttbl.test_target.power_on_pre_fns`).
        """
        # we use bootparam/set/bootflag since it is working much
        # better, because we seem not to be able to get the system to
        # acknowledge the BIOS boot order
        if target.fsdb.get("pos_mode") == 'pxe':
            target.log.error("POS boot: telling system to boot network")
            # self._run(target, [ "chassis", "bootdev", "pxe" ])
            self._run(target, [ "chassis", "bootparam",
                                "set", "bootflag", "force_pxe" ])
        else:
            self._run(target, [ "chassis", "bootparam",
                                "set", "bootflag", "force_disk" ])

pci_ipmitool = pci

class pos_mode_c(ttbl.power.impl_c):
    """
    Power controller to redirect a machine's boot to network upon ON

    This can be used in the power rail of a machine that can be
    provisioned with :ref:`Provisioning OS <provisioning_os>`, instead
    of using pre power-on hooks (such as
    :meth:`pci.pre_power_pos_setup`).

    When the target is being powered on, this will be called, and
    based if the value of the *pos_mode* property is *pxe*, the IPMI
    protocol will be used to tell the BMC to order the target to boot
    off the network with::

      $ ipmitool chassis bootparam set bootflag force_pxe

    otherwise, it'll force to boot off the local disk with::

      $ ipmitool chassis bootparam set bootflag force_disk

    Note that for this to be succesful and remove the chance of race
    conditions, this has to be previous to the component that powers
    on the machine via the BMC.

    :param str hostname: BMC location
      *[USERNAME[:PASSWORD]]@hostname.com*; note *PASSWORD* can be the
      bare password or a string that indicates how to get it; refer to
      the argument *password* for :func:`commonl.password_get`.

    :param int ipmi_timeout: seconds to wait for IPMI response (will be
      passed to *ipmitool*'s *-N* option
    :param int ipmi_retries: times to retry the IPMI operation (will be
      passed to *ipmitool*'s *-R* option.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, hostname, ipmi_timeout = 10, ipmi_retries = 3,
                 **kwargs):
        assert isinstance(hostname, str)
        assert isinstance(ipmi_timeout, numbers.Real)
        assert isinstance(ipmi_retries, int)
        ttbl.power.impl_c.__init__(self, paranoid = True, **kwargs)
        self.power_on_recovery = True
        self.paranoid_get_samples = 1
        user, password, hostname = commonl.split_user_pwd_hostname(hostname)
        self.hostname = hostname
        self.user = user
        self.bmc = None
        self.env = dict()
        # If I change the argument order, -E doesn't work ok and I get
        # password asked in the command line
        self.cmdline = [
            "ipmitool",
            "-v", "-v", "-v",
            "-N", "%d" % ipmi_timeout,
            "-R", "%d" % ipmi_retries,
            "-H", hostname
        ]
        if user:
            self.cmdline += [ "-U", user ]
        self.cmdline += [ "-E", "-I", "lanplus" ]
        if password:
            self.env['IPMI_PASSWORD'] = password
        self.timeout = 20
        self.wait = 0.1
        self.paranoid_get_samples = 1

    def _run(self, target, command):
        try:
            result = subprocess.check_output(
                self.cmdline + command, env = self.env, shell = False,
                stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error("ipmitool %s failed: %s",
                             " ".join(command), e.output)
            raise
        return result.rstrip()	# remove trailing NLs


    def on(self, target, _component):
        # we use bootparam/set/bootflag since it is working much
        # better, because we seem not to be able to get the system to
        # acknowledge the BIOS boot order
        if target.fsdb.get("pos_mode") == 'pxe':
            # self._run(target, [ "chassis", "bootdev", "pxe" ])
            self._run(target, [ "chassis", "bootparam",
                                "set", "bootflag", "force_pxe" ])
        else:
            self._run(target, [ "chassis", "bootparam",
                                "set", "bootflag", "force_disk" ])

    def off(self, target, _component):
        pass

    def get(self, target, component):
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

    :params str hostname: *USER[:PASSWORD]@HOSTNAME* of where the IPMI BMC is
      located

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
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         sol0_pc,
    >>>         ...
    >>>     )
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         sol0 = sol0_pc,
    >>>         default = "sol0",
    >>>     )
    >>> )


    :param str hostname: BMC location
      *[USERNAME[:PASSWORD]]@hostname.com*; note *PASSWORD* can be the
      bare password or a string that indicates how to get it; refer to
      the argument *password* for :func:`commonl.password_get`.

    :param int ipmi_timeout: seconds to wait for IPMI response (will be
      passed to *ipmitool*'s *-N* option
    :param int ipmi_retries: times to retry the IPMI operation (will be
      passed to *ipmitool*'s *-R* option.
    """
    def __init__(self, hostname,
                 precheck_wait = 0.5,
                 chunk_size = 5, interchunk_wait = 0.1,
                 ipmi_timeout = 10, ipmi_retries = 3):
        assert isinstance(hostname, str)
        assert isinstance(ipmi_timeout, numbers.Real)
        assert isinstance(ipmi_retries, int)
        ttbl.console.generic_c.__init__(self, chunk_size = chunk_size,
                                        interchunk_wait = interchunk_wait,
                                        crlf = "\n")
        ttbl.power.socat_pc.__init__(
            self,
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            "EXEC:'/usr/bin/ipmitool -N %(ipmi_timeout)s -R %(ipmi_retries)s"
            " -H %(hostname)s -U %(username)s -E"
            " -I lanplus sol activate',sighup,sigint,sigquit",
            precheck_wait = precheck_wait,
        )
        user, password, hostname = commonl.split_user_pwd_hostname(hostname)
        # pass those fields to the socat_pc templating engine
        self.kws['hostname'] = hostname
        self.kws['username'] = user
        self.kws['password'] = password
        self.kws['ipmi_timeout'] = ipmi_timeout
        self.kws['ipmi_retries'] = ipmi_retries
        self.ipmi_timeout = ipmi_timeout
        self.ipmi_retries = ipmi_retries
        if password:
            self.env_add['IPMITOOL_PASSWORD'] = password
        self.re_enable = True

    def on(self, target, component):
        # if there is someone leftover reading, kick them out, there can
        # be only one
        env = dict(os.environ)
        env.update(self.env_add)
        subprocess.call(	# don't check, we don't really care
            [
                "/usr/bin/ipmitool",
                "-N", str(self.ipmi_timeout),
                "-R", str(self.ipmi_retries),
                "-H", self.kws['hostname'],
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
        ttbl.console.generation_set(target, component)
        ttbl.console.generic_c.enable(self, target, component)

    def off(self, target, component):
        ttbl.console.generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    # console interface
    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)


class sol_ssh_console_pc(ttbl.console.ssh_pc):
    """
    IPMI SoL over SSH console

    This augments :class:`ttbl.console.ssh_pc` in that it will first
    disable the SOL connection to avoid conflicts with other users.

    This forces the input into the SSH channel to the BMC to be
    chunked each five bytes with a 0.1 second delay in between. This
    seems to gives most BMCs a breather re flow control.

    :params str hostname: *USER[:PASSWORD]@HOSTNAME* of where the IPMI BMC is
      located

    :param str hostname: BMC location
      *[USERNAME[:PASSWORD]]@hostname.com*; note *PASSWORD* can be the
      bare password or a string that indicates how to get it; refer to
      the argument *password* for :func:`commonl.password_get`.

    :param int ipmi_timeout: seconds to wait for IPMI response (will be
      passed to *ipmitool*'s *-N* option
    :param int ipmi_retries: times to retry the IPMI operation (will be
      passed to *ipmitool*'s *-R* option.
    """
    def __init__(self, hostname, ssh_port = 22,
                 chunk_size = 5, interchunk_wait = 0.1,
                 ipmi_timeout = 10, ipmi_retries = 3):
        assert isinstance(ipmi_timeout, numbers.Real)
        assert isinstance(ipmi_retries, int)
        ttbl.console.ssh_pc.__init__(
            self, hostname, port = ssh_port,
            chunk_size = chunk_size, interchunk_wait = interchunk_wait)
        _user, password, _hostname = commonl.split_user_pwd_hostname(hostname)
        self.ipmi_timeout = ipmi_timeout
        self.ipmi_retries = ipmi_retries
        if password:
            self.env_add['IPMITOOL_PASSWORD'] = password
        self.paranoid_get_samples = 1
        self.re_enable = True

    def on(self, target, component):
        # if there is someone leftover reading, kick them out, there can
        # be only one
        env = dict(os.environ)
        env.update(self.env_add)
        subprocess.call(	# don't check, we don't really care
            [
                "/usr/bin/ipmitool",
                "-N", str(self.ipmi_timeout),
                "-R", str(self.ipmi_retries),
                "-H", self.kws['hostname'],
                "-U", self.kws['username'], "-E",
                "-I", "lanplus", "sol", "deactivate",
            ],
            stderr = subprocess.STDOUT,
            env = env,
        )
        ttbl.console.ssh_pc.on(self, target, component)
