#! /usr/bin/python3
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Power control module to start OpenVPN services when a network is powered on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import subprocess

import ttbl.power

class server_c(ttbl.power.daemon_c):

    openvpn_path = "/usr/bin/openvpn"

    """This class implements a power control that can be used to start an
    OpenVPN endpoint to access a private network.

    With a configuration such as::

      import ttbl.openvpn

      ttbl.test_target.get('nwx').power.impl_add("openvpn", ttbl.openvpn.server_c())

    It creates an L2 bridge using tap the private network has a

    OpenVPN Client:

      $ tcf certs-get nwx -s openvpn
      downloaded client certificate key -> nwx.openvpn.{key,cert}
      $ tcf certs-get nwx -s ca
      downloaded root-of-trust certificate -> nwx.ca.cert
      $ /usr/bin/openvpn --client --dev tap --proto udp4 --remote SERVERIP 1194 \
          --ca nwx.ca.cert --cert nwx.openvpn.cert --key nwx.openvpn.key \
          --verb 4
    """

    def __init__(self, openvpn_port: int = 1194, openvpn_path: str = None):
        if openvpn_path == None:
            self.openvpn_path = self.openvpn_path
        else:
            self.openvpn_path = openvpn_path
        self.openvpn_port = openvpn_port
        cmdline = [
            self.openvpn_path,
            "--daemon", "openvpn-%(id)s-%(component)s",
            # so we capture it to the .stderr file we can stream over
            # console interface
            #"--errors-to-stderr",
            "--log", "/dev/stderr",
            #"--log", "%(path)s/openvpn-%(component)s.log",
            # in our convention, IC -- networks -- have the ipv4_addr as a top level record
            "--local", "%(ipv4_addr)s",
            # we need one port per NUT
            "--port", str(self.openvpn_port),
            "--proto", "udp",	# UDP: more efficient and reliable
            "--dev", "tap",	# tap: un dynamic tap device, so we can do DHCP
            "--server-bridge",	# bridge: so we can do DHCP and L2 routing
            "--ca", "%(path)s/certificates/ca.cert",
            "--cert", "%(path)s/certificates/server.cert",
            "--key", "%(path)s/certificates/server.key",
            "--dh", "%(path)s/certificates/dh.pem",
            "--writepid", "%(path)s/openvpn-%(component)s.pid"
        ]
        ttbl.power.daemon_c.__init__(
            self, cmdline, precheck_wait = 0.5, mkpidfile = False,
            pidfile = "%(path)s/openvpn-%(component)s.pid")
        self.upid_set("OpenVPN server")



    def verify(self, target, component, cmdline_expanded):
        # we know this is up if we can connect to the OpenVPN
        # port--but since we use UDP we don't really know if it is
        # rolling -- sigh --
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("localhost", 1194))
            sock.send(b"ping")
            target.log.info(f"{component}: OpenVPN server seems up")
            return True
        except Exception as e:
            # if connection refused, server is not up
            target.log.info(f"{component}: OpenVPN server is not up: {e}")
            return False



    def on(self, target, component):
        # ensure the SSL certificate support has been enabled, since
        # it is only done so on demand.  We do it by requesting a
        # certificate for openvpn--this will force the server cert and
        # dh.pem and all to be created; clients can then download the
        # openvpn certificate to connect
        iface_cert = getattr(target, "certs", None)
        if iface_cert == None:
            raise RuntimeError(
                f"{target.id}: does not support SSL certificates! BUG?")
        iface_cert.put_certificate(target, ttbl.who_daemon(),
                                   { "name": "openvpn" }, None, None)
        ttbl.power.daemon_c.on(self, target, component)
