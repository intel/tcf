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

    openvpn_path = "/usr/sbin/openvpn"

    """This class implements a power control that can be used to start an
    OpenVPN endpoint to access a private network.


    :param str ip_protocol: (optional, default *udp*) the IP protocol
      to use for OpenVPN; can be *udp* or *tcp*; UDP is more efficient
      and reliable, TCP allows hopping firewalls.

      Note the client needs to be configured to do one or the other

    :param str tap_suffix: (*optional*, default *tap*)



    With a configuration such as::

      import ttbl.openvpn

      nwx = ttbl.test_target.get('nwx')
      # ... assumes the power and console interfaces are already made
      # (e.g.) with target_vlan_add()
      nwx.interface_impl_add("power", "netif", ttbl.vlan.netif_c())
      nwx.property_set("interfaces.power.netif.vlan_taps", "tcp udp")

      nwx.interface_impl_add(
          "power", "openvpn_udp",
          ttbl.openvpn.server_c(openvpn_port = 3456,
                                ip_protocol = "udp", tap_suffix = "udp"))
      nwx.interface_impl_add(
           "console", "log-openvpn-udp",
           ttbl.console.logfile_c("openvpn-openvpn_udp.log"))

      nwx.interface_impl_add(
          "power", "openvpn_udp",
          ttbl.openvpn.server_c(openvpn_port = 3456,
                                ip_protocol = "tcp", tap_suffix = "tcp"))
      nwx.interface_impl_add(
           "console", "log-openvpn-tcp",
           ttbl.console.logfile_c("openvpn-openvpn_tcp.log"))


    It creates two L2 bridges using TAP, one over TCP, another over
    UDP; then it adds two OpenVPN endpoints (over TCP and UDP) that
    can be used to connect with an OpenVPN Client. Note it requires
    the :class:`ttbl.vlan.netif_c` driver running before in the power
    rail to create the network interfaces that are needed (a bridge
    called *nwx*, an associated network interface called *nwx.tap*)

    1. download the certificates for the network (every time the
       allocation changes this needs to be done)::

         $ tcf certs-get nwx -s ca openvpn
         downloaded root-of-trust certificate -> nwx.ca.cert
         downloaded client certificate key -> nwx.openvpn.{key,cert}

    2. connect the VPN::

         $ /usr/bin/openvpn --client --dev tap --proto udp4 --remote SERVER 3456 \
            --ca nwx.ca.cert --cert nwx.openvpn.cert --key nwx.openvpn.key \
            --verb 1
         ...
         2026-04-17 14:28:11 TUN/TAP device tap0 opened
         2026-04-17 14:28:11 Initialization Sequence Completed


    3. Get an IP address from the NUT's DHCP server for *tap0* (from
       the *TUN/TAP device tap0 opened* message from OpenVPN.

       - with systemd-networkd (recommended):

         a. generate a configuration file::

              $ sudo tee /run/systemd/network/90-tap0.network <<EOF
              [Match]
              Name=tap0

              [Network]
              DHCP=yes
              EOF

         b. tell system-network to reload and configure *tap0*::

              $ sudo networkctl reload
              $ sudo networkctl reconfigure tap0

         c. verify configuration was obtained and DNS too::

              $ networkctl status tap0
              . 132: tap0
                                 Link File: /usr/lib/systemd/network/99-default.link
                              Network File: /run/systemd/network/90-tap0.network
                                     State: routable (configured)
                              Online state: online
                                            ...
                                      Type: ether
                                      Kind: tun
                                    Driver: tun
                          Hardware Address: c2:5b:0e:31:c1:fa
                                   Address: 192.2.213.56 (DHCPv4 via 192.2.80.1)
                                            fe80::c05b:eff:fe31:c1fa
                                       DNS: 192.2.80.1
                                            ....

              $ resolvectl status tap0
              Link 132 (tap0)
                  Current Scopes: DNS LLMNR/IPv4 LLMNR/IPv6
                       Protocols: +DefaultRoute LLMNR=resolve -mDNS -DNSOverTLS DNSSEC=no/unsupported
              Current DNS Server: 192.2.80.1
                     DNS Servers: 192.2.80.1
                   Default Route: yes

       - with dhclient::

           $ dhclient -i tap0

         Note depending on what script integrations your version of
         dhclient has (usually in */usr/bin/dhclient-script*), it
         might alter the DNS configuration in ways that might affect
         your system's configuration.

       (the device might change)

    """

    def __init__(self, openvpn_port: int = 1194, openvpn_path: str = None,
                 ip_protocol: str = "udp", tap_suffix: str = "tap"):
        assert ip_protocol in [ "udp", "tcp" ], \
            f"ip_protocol: expected *udp* or *tcp*; got {ip_protocol}"
        assert isinstance(openvpn_port, int) \
            and openvpn_port > 2 and openvpn_port < 65536, \
            f"openvpn_port: expected int 2-65536, got [{type(openvpn_port)}] '{openvpn_port}'"

        if openvpn_path == None:
            self.openvpn_path = self.openvpn_path
        else:
            self.openvpn_path = openvpn_path
        self.openvpn_port = openvpn_port
        self.ip_protocol = ip_protocol
        cmdline = [
            self.openvpn_path,
            "--daemon", "openvpn-%(id)s-%(component)s",
            # so we capture it to the .stderr file we can stream over
            # console interface
            "--log", "%(path)s/openvpn-%(component)s.log",
            # Listen on all the network interfaces
            # FIXME: how do do it so it doesn't listen on the NUTs --
            # doesn't really matter, we need the certs
            "--local", "0.0.0.0",
            # we need one port per NUT
            "--port", str(self.openvpn_port),
            # UDP: more efficient and reliable
            # TCP: allows hopping firewalls
            "--proto", ip_protocol,
            # we use a TAP device so we can do DHCP; the tap device is
            # created by ttbl.conf_00_lib.vlan_setup; tap_ifname in
            # target.kws is set by vlan_pci if we create a tap device
            "--dev-type", "tap",
            "--dev", f"%(bridge_ifname)s.{tap_suffix}",
            "--server-bridge",	# bridge: so we can do DHCP and L2 routing
            "--ca", "%(path)s/certificates/ca.cert",
            "--cert", "%(path)s/certificates/server.cert",
            "--key", "%(path)s/certificates/server.key",
            "--dh", "%(path)s/certificates/dh.pem",
            "--writepid", "%(path)s/openvpn-%(component)s.pid",
            # otherwise log files get wild
            # FIXME: get from inventory intefaces.power.component.openvpn_verbosity
            "--verb", "2",
        ]
        ttbl.power.daemon_c.__init__(
            self, cmdline, precheck_wait = 0.5, mkpidfile = False,
            pidfile = "%(path)s/openvpn-%(component)s.pid")
        self.upid_set(
            f"OpenVPN server on {ip_protocol}#{openvpn_port} server",
            ip_protocol = ip_protocol,
            openvpn_port = openvpn_port)



    def target_setup(self, target, iface_name, component):
        target.property_set(f"interfaces.{iface_name}.{component}.openvpn_protocol",
                            self.ip_protocol)
        target.property_set(f"interfaces.{iface_name}.{component}.openvpn_port",
                            self.openvpn_port)



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
