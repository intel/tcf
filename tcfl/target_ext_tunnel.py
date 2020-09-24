#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Create and remove network tunnels to the target via the server
--------------------------------------------------------------

"""

import pprint

from . import msgid_c
import commonl
import tc
import ttb_client

class tunnel(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to create IP tunnels to
    targets with IP connectivity.

    Use by indicating a default IP address to use for interconnect
    *ic* or explicitly indicating it in the :meth:`add` function:

    >>> target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
    >>> target.tunnel.add(PORT)
    >>> target.tunnel.remove(PORT)
    >>> target.tunnel.list()

    Note that for tunnels to work, the target has to be acquired and
    IP has to be up on it, which might requires it to be connected to
    some IP network (it can be a TCF interconnect or any other
    network).
    """

    def __init__(self, target):
        self.target = target
        # Tunnels can always be added, even the target is not in an
        # interconnect
        self.ip_addr = None

    def _ip_addr_get(self, ip_addr):
        # FIXME: this shall validate the IP address using python-ipaddress
        if ip_addr:
            return ip_addr
        target = self.target
        interconnects = target.rt.get('interconnects', {}).keys()
        boot_ic = target.rt.get('pos_boot_interconnect', None)
        if boot_ic:
            # if the boot interconnect is available in the list of
            # interconnect, arrange the list so it is the first one we
            # try
            if boot_ic in interconnects:
                interconnects.remove(boot_ic)
            interconnects = [ boot_ic ] + interconnects
        for ic_name in interconnects:
            ic = target.rt['interconnects'][ic_name]
            ipv4_addr = ic.get('ipv4_addr', None)
            if ipv4_addr:
                return ipv4_addr
            ipv6_addr = ic.get('ipv6_addr', None)
            if ipv6_addr:
                return ipv6_addr
        raise RuntimeError(
            "Cannot identify any IPv4 or IPv6 address to use; "
            "please set it in "
            "`TARGET.tunnel.ip_addr = TARGET.addr_get(ic, \"ipv4\")` "
            "or pass it explicitly")


    def add(self, port, ip_addr = None, protocol = None):
        """
        Setup a TCP/UDP/SCTP v4 or v5 tunnel to the target

        A local port of the given protocol in the server is forwarded
        to the target's port. Teardown with :meth:`remove`.

        If the tunnel already exists, it is not recreated, but the
        port it uses is returned.

        Example: redirect target's TCP4 port 3000 to a port in the server
          that provides ``target`` (target.kws['server']).

          >>> server_port = target.tunnel.add(3000)
          >>> server_name = target.rtb.parsed_url.hostname
          >>> server_name = target.kws['server']    # alternatively

        Now connecting to ``server_name:server_port`` takes you to the
        target's port 3000.

        :param int port: port to redirect to
        :param str ip_addr: (optional) target's IP address to use (it
          must be listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param str protocol: (optional) Protocol to tunnel:
          {udp,sctp,tcp}[{4,6}] (defaults to TCP v4)
        :returns int local_port: port in the server where to connect
          to in order to access the target.
        """
        if protocol == None:
            protocol = 'tcp'
        else:
            assert isinstance(protocol, basestring), \
                "protocol shall be a string; got %s" % type(protocol)
        assert port > 0
        target = self.target
        ip_addr = self._ip_addr_get(ip_addr)

        r = self.target.ttbd_iface_call("tunnel", "tunnel",
                                        ip_addr = ip_addr,
                                        protocol = protocol,
                                        port = port,
                                        method = "PUT")
        server_port = r['result']
        if isinstance(server_port, basestring):
            # COMPAT: work around server with unfixed bug
            server_port = int(server_port)
        self.target.report_info(
            "%s tunnel added from %s:%d to %s:%d" % (
                protocol,
                target.rtb.parsed_url.hostname, server_port,
                ip_addr, port)
        )
        return server_port


    def remove(self, port, ip_addr = None, protocol = None):
        """
        Teardown a TCP/UDP/SCTP v4 or v5 tunnel to the target
        previously created with :meth:`add`.

        :param int port: port to redirect to
        :param str ip_addr: (optional) target's IP address to use (it
          must be listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param str proto: (optional) Protocol to tunnel:
          {udp,sctp,tcp}[{4,6}] (defaults to v4 and to TCP)
        """
        if protocol == None:
            protocol = 'tcp'
        else:
            assert isinstance(protocol, basestring), \
                "protocol shall be a string; got %s" % type(protocol)
        assert isinstance(port, int)
        ip_addr = self._ip_addr_get(ip_addr)

        self.target.ttbd_iface_call("tunnel", "tunnel",
                                    ip_addr = ip_addr,
                                    protocol = protocol,
                                    port = port,
                                    method = "DELETE")


    def list(self):
        """
        List existing IP tunnels

        :returns: dictionary keyed by server port of each existing
          tunnels:

          .. code-block:: python

             {
                 SERVER-PORT1: {
                     "protocol": 'tcp',   # tcp, udp, sctp, ...
                     "ip_addr": "A.B.C.D",
                     "port": NNN
                 },
                 ...
             }

          *SERVER-PORT* is the same port returned by the :meth:`add`
          call, so that the endpoint for the tunnel would be the
          server's hostname (available at
          *target.rtb.parsed_hostname*) and the *SERVER-PORT*.
        """
        d = dict()
        r = self.target.properties_get("interfaces.tunnel")
        # we get: interfaces: { tunnel: { LOCALPORT: { DATA },
        # LOCALPORT: { DATA }...}
        r = r.get("interfaces", {}).get("tunnel", {})
        for local_port, data in r.items():
            try:
                # we get local_port as a string because it is a field
                # name in the database (versus a value)
                d[int(local_port)] = dict(
                    protocol = data['protocol'],
                    ip_addr = data['ip_addr'],
                    port = data['port']
                )
            except KeyError as e:
                pass	# ignore, bad data stored
        if not d: # COMPAT
            # if didn't found anything in the inventory, maybe this is
            # an old style server, try calling the old deprecated
            # method
            try:
                r = self.target.ttbd_iface_call("tunnel", "list", method = "GET")
                for protocol, ip_addr, port, local_port in r['result']:
                    d[int(local_port)] = dict(
                        protocol = protocol,
                        ip_addr = ip_addr,
                        port = int(port))
                return d
            except tc.error_e as e:
                if not 'unsupported' in e:
                    raise
        return d


    def _healthcheck(self):
        target= self.target
        interconnects = target.rt.get('interconnects', {})
        if interconnects == {}:
            target.report_skip("skipping tunnel healthcheck,"
                               " no IP connectivity in configuration, ")
            return
        target = self.target
        tunnels = target.tunnel.list()
        for protocol, ip_address, target_port, server_port in tunnels:
            target.report_info(
                "removing existing tunnel %s %s -> %s:%s"
                % (protocol, server_port, ip_address, target_port))
            target.tunnel.remove(target_port, ip_address, protocol)

        server_port_22 = target.tunnel.add(22)
        target.report_pass("added tunnel to port 22")

        tunnels = target.tunnel.list()
        if len(tunnels) != 1:
            raise tc.failed_e(
                "list() lists %d tunnels; expected 1" % len(tunnels),
                dict(tunnels = tunnels))
        target.report_pass("list() lists only one tunnel")
        if server_port_22 not in tunnels \
           or tunnels[server_port_22].get("port", None) != 22:
            raise tc.failed_e(
                "list() didn't report target port as 22 as requested",
                dict(tunnels = tunnels))
        target.report_pass("list() reports tunnel to 22 as requested")

        server_port_23 = target.tunnel.add(23)
        target.report_pass("added tunnel to port 23")

        tunnels = target.tunnel.list()

        if len(tunnels) != 2:
            raise tc.failed_e(
                "list() lists %d tunnels; expected 2" % len(tunnels),
                dict(tunnels = tunnels))
        target.report_pass("list() lists two tunnels")
        if server_port_22 not in tunnels \
           or tunnels[server_port_22].get("port", None) != 22:
            raise tc.failed_e(
                "list() didn't report target port as 22 as requested",
                dict(tunnels = tunnels))
        if server_port_23 not in tunnels \
           or tunnels[server_port_23].get("port", None) != 23:
            raise tc.failed_e(
                "list() didn't report target port as 23 as requested",
                dict(tunnels = tunnels))
        target.report_pass("list() reports tunnel to 22 and 23 as requested")

        target.tunnel.remove(22)
        target.report_pass("removed tunnel to port 22")
        tunnels = target.tunnel.list()
        if len(tunnels) != 1:
            raise tc.failed_e(
                "list() lists %d tunnels; expected 1" % len(tunnels),
                dict(tunnels = tunnels))

        # leftover tunnel is the one to port 23
        if server_port_23 not in tunnels \
           or tunnels[server_port_23].get("port", None) != 23:
            raise tc.failed_e(
                "list() didn't report target port as 23 as requested",
                dict(tunnels = tunnels))
        target.report_pass("list() lists only tunnel to port 23")
        target.tunnel.remove(23)
        target.report_pass("removed tunnel to port 23")
        tunnels = target.tunnel.list()
        if len(tunnels) != 0:
            raise tc.failed_e(
                "list() reports %d tunnels; expected none" % len(tunnels),
                dict(tunnels = tunnels))
        target.report_pass("no tunnels listed after removing all")

        # can't really test the tunnel because we don't know if the
        # target is listening, has a real IP interface, etc...this is
        # a very basic healhcheck on the server side

def _cmdline_tunnel_add(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "tunnel")
        server_port = target.tunnel.add(args.port, args.ip_addr, args.protocol)
        print "%s:%d" % (target.rtb.parsed_url.hostname, server_port)

def _cmdline_tunnel_remove(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "tunnel")
        target.tunnel.remove(args.port, args.ip_addr, args.protocol)


def _cmdline_tunnel_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "tunnel")
        for local_port, data in  target.tunnel.list().items():
            print "%s %s:%s %s:%s" % (
                data['protocol'],
                target.rtb.parsed_url.hostname, local_port,
                data['ip_addr'], data['port']
            )


def cmdline_setup(argsp):
    ap = argsp.add_parser("tunnel-add", help = "create an IP tunnel")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("port", metavar = "PORT", action = "store", type = int,
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to TCPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = _cmdline_tunnel_add)

    ap = argsp.add_parser("tunnel-rm",
                          help = "remove an existing IP tunnel")
    commonl.argparser_add_aka(argsp, "tunnel-rm", "tunnel-remove")
    commonl.argparser_add_aka(argsp, "tunnel-rm", "tunnel-delete")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("port", metavar = "PORT", action = "store", type = int,
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to tcp and to IPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = _cmdline_tunnel_remove)

    ap = argsp.add_parser("tunnel-ls", help = "List existing IP tunnels")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = _cmdline_tunnel_list)
