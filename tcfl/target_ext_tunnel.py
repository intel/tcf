#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

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
        if self.ip_addr:
            return self.ip_addr
        ip_addr = self.target.rt.get(
            'ipv4_addr', self.target.rt.get('ipv6_addr', None))
        if ip_addr:
            return ip_addr
        raise RuntimeError(
            "Cannot identify any IPv4 or IPv6 address to use; "
            "please set it in `TARGET.tunnel.ip_addr` or pass "
            "it explicitly")


    def add(self, port, ip_addr = None, proto = None):
        """
        Setup a TCP/UDP/SCTP v4 or v5 tunnel to the target

        A local port of the given protocol in the server is fowarded
        to the target's port. Teardown with :meth:`remove`.

        If the tunnel already exists, it is not recreated, but the
        port it uses is returned.

        :param int port: port to redirect to
        :param str ip_addr: (optional) target's IP address to use (it
          must be listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param str proto: (optional) Protocol to tunnel:
          {udp,sctp,tcp}[{4,6}] (defaults to v4 and to TCP)
        :returns int local_port: port in the server where to connect
          to in order to access the target.
        """
        if proto == None:
            proto = 'tcp'
        else:
            assert isinstance(proto, basestring)
        assert isinstance(port, int)
        target = self.target
        ip_addr = self._ip_addr_get(ip_addr)

        r = target.rtb.rest_tb_target_ip_tunnel_add(
            target.rt, ip_addr, port, proto, ticket = target.ticket)
        return r

    def remove(self, port, ip_addr = None, proto = None):
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
        if proto == None:
            proto = 'tcp'
        else:
            assert isinstance(proto, basestring)
        assert isinstance(port, int)
        ip_addr = self._ip_addr_get(ip_addr)

        target = self.target
        target.rtb.rest_tb_target_ip_tunnel_remove(
            target.rt, ip_addr, port, proto, ticket = target.ticket)

    def list(self):
        """
        List existing IP tunnels

        :returns: list of tuples (protocol, target-ip-address, port,
          port-in-server)
        """
        target = self.target
        return target.rtb.rest_tb_target_ip_tunnel_list(target.rt,
                                                        ticket = target.ticket)

# FIXME: work out tcf creating target_c instances, so it is easier to
# automate creating cmdline wrappers

def cmdline_tunnel_add(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    port = rtb.rest_tb_target_ip_tunnel_add(rt, args.ip_addr,
                                            args.port, args.protocol,
                                            ticket = args.ticket)
    print "%s:%d" % (rtb.parsed_url.hostname, port)

def cmdline_tunnel_remove(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    rtb.rest_tb_target_ip_tunnel_remove(rt, args.ip_addr,
                                        args.port, args.protocol,
                                        ticket = args.ticket)

def cmdline_tunnel_list(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    tunnels = rtb.rest_tb_target_ip_tunnel_list(rt, ticket = args.ticket)
    for tunnel in tunnels:
        print "%s %s:%s %s:%s" % (tunnel[0],
                                  rtb.parsed_url.hostname, tunnel[3],
                                  tunnel[1], tunnel[2])

def cmdline_setup(argsp):
    ap = argsp.add_parser("tunnel-add", help = "create an IP tunnel")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("port", metavar = "PORT", action = "store", type = int,
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to tcp and to IPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = cmdline_tunnel_add)

    ap = argsp.add_parser("tunnel-remove",
                          help = "remove an existing IP tunnel")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("port", metavar = "PORT", action = "store",
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to tcp and to IPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = cmdline_tunnel_remove)

    ap = argsp.add_parser("tunnel-list", help = "List existing IP tunnels")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = cmdline_tunnel_list)
