#! /usr/bin/env python3
#
# (C) 2026 Intel Corporation
#
# SPDX-License-Header Apache 2.0
#
"""
Utilities to map ports between networks
---------------------------------------

"""
import collections
import psutil
import socket
import typing



def nic_ips_list(exclude_lo: bool = True,
                 afs: typing.Set[int] = { socket.AF_INET }) \
        -> typing.Dict[str, typing.Set[str]]:
    """
    List IPs and the interfaces they are assigned to.

    :param exclude_lo: if True, exclude the loopback interface
    :param afs: address families to include (default: socket.AF_INET)
    :return: dictionary mapping IP addresses to sets of interface names
    """
    iface_by_ip = collections.defaultdict(set)
    for iface, addrs in psutil.net_if_addrs().items():
        if iface == 'lo' and exclude_lo:
            continue
        for a in addrs:
            if a.family in afs:
                iface_by_ip[a.address].add(iface)

    return iface_by_ip



host_port_map_default = {}



def translate(host: str = None, ip_protocol: str = "tcp", port: int = None,
              nic_ips: dict = None, host_port_map: dict = None,
              raise_if_missing: bool = False) \
              -> typing.Tuple[str, int, dict]:
    """
    Translate a host and port to the external IP and port for the
    environment the server is running in.

    This is helpful when the server runs in a NAT environment and the
    internal IPs and ports are not accessible from the outside. The
    NAT public network connection exposes some of the internal ports
    in a different port and/or IP address. This mapping information
    allows the software to place the translations in the right places.

    :param host: (optional) internal host to translate; if not
      specified it will try the IP addresses assigned to this host

    :param ip_protocol: (optional) protocol to use for port
      translation; default "tcp"; has to be "tcp" or "udp"

    :param port: (optional) internal port to translate; if not
      specified it will just translate the host name.

    :param dict host_port_map: dictionary mapping internal hosts
      to external hosts and ports, keyed by hostname/IPaddress; values
      are:

      - a string: a translation to another entry

      - a dictionary: translation and host information

        *port_map*: a dictionary mapping internal ports to tuples of
        external IP or names and external port

        >>> "port_map": {
	>>>     # ( protocol, internal_port: (  external_IP, external_port )
        >>>     ( tcp,   22 ):   ( "145.185.5.3", 826 ),
        >>>     ( tcp, 5000 ): ( "192.185.5.3", 827 ),
        >>> }

        Other fields left open for being used by the caller.

      If no mapping is found, the orignal host and port will be
      returned unless *raise_if_missing* is True, in which case a
      ValueError will be raised.

    :return: external host and port and the full data collection for host
    """
    assert isinstance(host, str) or host is None, \
        f"host: expected a string or None; got {type(host)}"
    assert ip_protocol in ("tcp", "udp"), \
        f"ip_protocol: expected 'tcp' or 'udp'; got {ip_protocol}"
    assert isinstance(port, int) or port is None, \
        f"port: expected an int or None; got {type(port)}"
    assert isinstance(host_port_map, dict) or host_port_map is None, \
        f"host_port_map: expected a dict or None; got {type(host_port_map)}"

    if host_port_map == None:
        host_port_map = host_port_map_default

    host_info = None

    def translate_host_info_get(host) -> dict:
        """
        Get the translation information for a given host.

        :param host: internal host to translate
        :return: translation information dictionary or None if not found
        """
        seen = [ host ]
        host_itr = host
        while True:
            d = host_port_map.get(host_itr, None)
            if isinstance(d, str):
                if d in seen:
                    raise RuntimeError(
                        f"circular reference detected for host {host}:"
                        f" {'->'.join(seen)}->{d}")
                seen.append(d)
                host_itr = d
                continue
            if isinstance(d, dict):
                return d
            if d == None:
                return None
            raise RuntimeError(f"BUG! unknown value type {type(d)};"
                               " expected str, dict")

    if host != None:
        host_info = translate_host_info_get(host)
    else:
        if nic_ips == None:
            nic_ips = nic_ips_list()
        for addr in nic_ips:
            host_info = translate_host_info_get(addr)
            if host_info:
                host = addr
                break

    if host_info == None:
        host_info = host_port_map.get("default", None)

    if host_info == None:
        if raise_if_missing:
            raise ValueError(
                f"no translation found for host {host}/{ip_protocol}/{port}"
                f" in host_port_map and no defaults present")
        return host, port, {}

    if port == None:
        return host_info.get("name", host), None, host_info

    port_map = host_info.get("port_map", {})
    if not port_map or not ( ip_protocol, port ) in port_map:
        if raise_if_missing:
            raise ValueError(
                f"no translation found for host {host}/{ip_protocol}/{port}"
                f" in host_port_map")
        return host_info.get("name", host), port, host_info
    _port_map = port_map[( ip_protocol, port )]
    return _port_map[0], _port_map[1], host_info
