#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Power control module to start a socat daemon when a network is powered-on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This socat daemon can provide tunneling services to allow targets to
access outside isolated test networks via the server.
"""

import os
import subprocess

import commonl
import ttbl
import ttbl.config

class pci(ttbl.tt_power_control_impl):

    class error_e(Exception):
        pass

    class start_e(error_e):
        pass

    path = "/usr/bin/socat"

    """
    This class implements a power control unit that can forward ports
    in the server to other places in the network.

    It can be used to provide for access point in the NUTs (Network
    Under Tests) for the testcases to access.

    For example, given a NUT represented by ``NWTARGET`` which has an
    IPv4 address of 192.168.98.1 in the ttbd server, a port
    redirection from port 8080 to an external proxy server
    *proxy-host.in.network:8080* would be implemented as:

    >>> ttbl.config.targets[NWTARGET].pc_impl.append(
    >>>     ttbl.socat.pci('tcp',
    >>>                    '192.168.98.1', 8080,
    >>>                    'proxy-host.in.network', 8080))

    Then to facilitate the work of test scripts, it'd make sense to
    export tags that explain where the proxy is:

    >>> ttbl.config.targets[NWTARGET].tags_update({
    >>>     'ftp_proxy': 'http://192.168.98.1:8080',
    >>>     'http_proxy': 'http://192.168.98.1:8080',
    >>>     'https_proxy': 'http://192.168.98.1:8080',
    >>> })
    """

    def __init__(self, proto,
                 local_addr, local_port,
                 remote_addr, remote_port):
        ttbl.tt_power_control_impl.__init__(self)
        assert proto in [ 'udp', 'tcp', 'sctp',
                          'udp4', 'tcp4', 'sctp4',
                          'udp6', 'tcp6', 'sctp6' ]
        self.proto = proto
        self.local_addr = local_addr
        self.local_port = local_port
        self.remote_addr = remote_addr
        self.remote_port = remote_port
        self.tunnel_id = "%s-%s:%d-%s:%d" % (
            self.proto, self.local_addr, self.local_port,
            self.remote_addr, self.remote_port)

    def power_on_do(self, target):
        pidfile = os.path.join(target.state_dir,
                               "socat-" + self.tunnel_id + ".pid")
        cmdline = [
            self.path,
            "-ly", "-lp", self.tunnel_id,
            "%s-LISTEN:%d,bind=%s,fork,reuseaddr" % (
                self.proto, self.local_port, self.local_addr),
            "%s:%s:%s" % (self.proto, self.remote_addr, self.remote_port)
        ]
        try:
            p = subprocess.Popen(cmdline, shell = False,
                                 cwd = target.state_dir,
                                 close_fds = True, stderr = subprocess.STDOUT)
            with open(pidfile, "w+") as pidf:
                pidf.write("%s" % p.pid)
        except OSError as e:
            raise self.start_e("socat failed to start: %s", e)
        pid = commonl.process_started(
            pidfile, self.path,
            verification_f = commonl.tcp_port_busy,
            verification_f_args = (self.local_port,),
            tag = "socat", log = target.log)
        # systemd might complain with
        #
        # Supervising process PID which is not our child. We'll most
        # likely not notice when it exits.
        #
        # Can be ignored
        if pid == None:
            raise self.start_e("socat failed to start")
        ttbl.daemon_pid_add(pid)	# FIXME: race condition if it died?

    def power_off_do(self, target):
        pidfile = os.path.join(target.state_dir,
                               "socat-" + self.tunnel_id + ".pid")
        commonl.process_terminate(pidfile, path = self.path, tag = "socat")

    def power_get_do(self, target):
        pidfile = os.path.join(target.state_dir,
                               "socat-" + self.tunnel_id + ".pid")
        pid = commonl.process_alive(pidfile, self.path)
        if pid != None:
            return True
        return False
