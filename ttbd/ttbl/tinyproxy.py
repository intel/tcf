#! /usr/bin/python3
#
# Copyright (c) 2026 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Power control module to start TinyProxy HTTP server when a network is powered on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import datetime
import os

import commonl
import ttbl.power

class server_c(ttbl.power.daemon_c):
    """This class implements a power controller that starts a HTTP/S
    proxy server with *tinyproxy attached to an specific IP address in
    the system, normally to the interface serving a test network (NUT)

    The proxy is configured to block any request by default and those
    to be permitted need to be enabled with an allow list.

    The allow list is generated from configuration files in the system
    called:

    - CFGFILES_PREFIX-global.urls
    - CFGFILES_PREFIX-NETWORKNAME.urls

    and the configuration from files named:

    - CFGFILES_PREFIX-global.conf
    - CFGFILES_PREFIX-NETWORKNAME.conf

    if a change is made to this file, this component has to be power
    cycled so the new configuration settings take place.

    A way this can be added to an existing network:

    >>> lan_target.interface_impl_add(
    >>>     "power",
    >>>     "tinyproxy",
    >>>     ttbl.tinyproxy.server_c(
    >>>         port = 8080,
    >>>         cfgfiles_prefix = "/etc/ttbd-production/tinyproxy",
    >>>         off_on_release = True)
    >>> )

    a log monitor console can be added with

    >>> lan_target.interface_impl_add(
    >>>     "console",
    >>>     "log-tinyproxy",
    >>>     ttbl.console.logfile_c("tinyproxy-tinyproxy.log"))

    the inventory property *interfaces.power.COMPONENTNAME.log_level*
    can be set to any of the log levels especified in the man page for
    *tinyproxy.conf* an upon component power cycle, it will reflect
    said change.

    :param int port: (optional default *8080*) TCP port on which
      the server will listen for HTTP proxy requests; must be a
      valid TCP port number between 1 and 65535.

    :param str ipv4_addr: (optional; default *None*) IPv4 address of
      the interface in the server to serve proxy requests on; if
      *None* (default) will listen on the IPv4 address described by
      the *ipv4_addr* property of the network object this object is
      attached to.

    :param int ipv4_prefix_len: (optional; default *None*) IPv4
      address prefix length of the interface in the server interface
      where to serve requests on. As with *ipv4_addr*, if not
      specified it will be taken from the *ipv4_prefix_len* inventory
      property of the network object this is attached to.

    :param str cfgfiles_prefix: (optional; default *none*) Prefix of
      configuration files to include in the TinyProxy configuration.

      See *tinyproxy.conf*'s man page for more details on the format
      of the .conf and .urls files and examples below.

      >>> cfgfiles_prefix = "/etc/ttbd-production/tinyproxy"


    **Examples for configuration and URLs files**

    Inside an intranet,a */etc/ttbd-production/tinyproxy-global.conf*::

      # do no upstream access to machine1 and machine2
      upstream none "machine1.intranet.com"
      upstream none "machine2.intranet.com"
      # go to our proxy for the rest
      upstream http proxy.intranet.com:8080

    And an allow list for that upstream
    */etc/ttbd-production/tinyproxy-global.urls* in BRE (basic regular expressions)::

       # allow the following hosts to be proxied
       .*\.github\.com
       .*\.ubuntu\.com

    """

    tinyproxy_path = "/usr/bin/tinyproxy"

    def __init__(self, port: int = 8080,
                 ipv4_addr: str = None,
                 ipv4_prefix_len: int = None,
                 cfgfiles_prefix: str = None,
                 tinyproxy_path: str = None,
                 **kwargs):
        assert isinstance(port, int) and port > 0 and port < 65536, \
            f"port: invalid for tinyproxy; expected a TCP port number" \
            f" between 1 and 65535; got {type(port)} '{port}'"
        self.port = port

        assert isinstance(ipv4_addr, str) or ipv4_addr == None, \
            f"ipv4_addr: expected a string with an IPv4 address or None;" \
            f" got {type(ipv4_addr)} '{ipv4_addr}'"
        self.ipv4_addr = ipv4_addr

        assert isinstance(ipv4_prefix_len, int) or ipv4_prefix_len == None, \
            f"ipv4_prefix_len: expected an integer or None;" \
            f" got {type(ipv4_prefix_len)} '{ipv4_prefix_len}'"
        self.ipv4_prefix_len = ipv4_prefix_len

        assert isinstance(cfgfiles_prefix, str) or cfgfiles_prefix == None, \
            f"cfgfiles_prefix: expected a string file name prefix;" \
            f" got {type(cfgfiles_prefix)} '{cfgfiles_prefix}'"
        self.cfgfiles_prefix = cfgfiles_prefix

        if tinyproxy_path == None:
            self.tinyproxy_path = self.tinyproxy_path
        else:
            self.tinyproxy_path = tinyproxy_path
        cmdline = [
            self.tinyproxy_path,
            "-d", # do not become a daemon
            "-c", "%(path)s/tinyproxy-%(component)s.conf",
        ]
        ttbl.power.daemon_c.__init__(
            self, cmdline, precheck_wait = 0.5, mkpidfile = False,
            pidfile = "%(path)s/tinyproxy-%(component)s.pid",
            **kwargs)
        self.upid_set(
            "Tinyproxy HTTP proxy server")



    def target_setup(self, target, iface_name, component):
        # log_level is specific to the user; clear it after allocation
        # is complete
        target.properties_user.add(
            f"interfaces.{iface_name}.{component}.log_level")



    def verify(self, target, component, cmdline_expanded):
        return commonl.process_alive(
            f"{target.state_dir}/tinyproxy-{component}.pid",
            self.tinyproxy_path)
        # FIXME: and commonl.tcp_port_busy(self.tcp_port) -> only on the right interface, need to add to the tcp_port_busy interface



    def _on_config_file_make(self, target, component: str):
        ipv4_addr = self.ipv4_addr
        if ipv4_addr == None:
            ipv4_addr = target.property_get("ipv4_addr", None)
        if ipv4_addr == None:
            raise RuntimeError(
                f"{target.id}/{component}: tinyproxy: no IPv4 address defined"
                " in configuration or in inventory *ipv4_addr*; cannot start")

        ipv4_prefix_len = self.ipv4_prefix_len
        if ipv4_prefix_len == None:
            ipv4_prefix_len = target.property_get("ipv4_prefix_len", None)
        if ipv4_prefix_len == None:
            raise RuntimeError(
                f"{target.id}/{component}: tinyproxy: no IPv4 prefix length"
                " in configuration or in inventory *ipv4_prefix_len*; cannot start")
        assert isinstance(ipv4_prefix_len, int) \
            and ipv4_prefix_len > 1 and ipv4_prefix_len < 32 , \
            f"{target.id}/{component}: tinyproxy: ipv4_prefix_len expected" \
            f" an integer between 1 an 32; got [{type(ipv4_prefix_len)}]" \
            f" {ipv4_prefix_len}"

        log_level = target.property_get(f"interfaces.power.{component}.log_level", "Notice")
        log_level_valid = ( "Critical""Error""Warning", "Notice", "Connect", "Info" )
        if log_level not in log_level_valid:
            raise RuntimeError(
                f"interfaces.power.{component}.log_level:"
                f" set to invalid '{log_level}';"
                " expected on of {', '.join(log_level_valid)}")
        with open(f"{target.state_dir}/tinyproxy-{component}.conf", "w") as f:
            f.write(f"""
# Generated by {__file__}
# upon power on of target {target.id}, component {component}
# on {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC

Port {self.port}
PidFile "{target.state_dir}/tinyproxy-{component}.pid"
LogFile "{target.state_dir}/tinyproxy-{component}.log"
LogLevel {log_level}

# listen only to connections from the NUT we are attached to, given by
# the IP address in the inventory
Listen {ipv4_addr}

# no need to allow/deny; tinyproxy only binds to the interface that
# connects us to the private network where we have to serve,
# so it assumes anything in there has to be served.

# Don't proxy the local network
upstream none "{ipv4_addr}/{ipv4_prefix_len}"

# We do a very restrictive setting --only what is configured as
# allowed can go through; these are composed with the contents of
# - {self.cfgfiles_prefix}-global.urls
# - {self.cfgfiles_prefix}-{target.id}.urls
FilterDefaultDeny Yes
Filter "{target.state_dir}/tinyproxy-{component}.urls"
""")
            for filename in [
                    f"{self.cfgfiles_prefix}-global.conf",
                    f"{self.cfgfiles_prefix}-{target.id}.conf",
            ]:
                try:
                    with open(filename) as f_itr:
                        f.write(f"\n\n# This is file {filename}\n\n")
                        f.write(f_itr.read())
                except FileNotFoundError:
                    pass

        with open(f"{target.state_dir}/tinyproxy-{component}.urls", "w") as f:
            f.write(f"""
# Generated by {__file__}
# upon power on of target {target.id}, component {component}
# on {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC
""")
            if self.cfgfiles_prefix:
                for filename in [
                        f"{self.cfgfiles_prefix}-global.urls",
                        f"{self.cfgfiles_prefix}-{target.id}.urls",
                ]:
                    try:
                        with open(filename) as f_itr:
                            f.write(f"\n\n# This is file {filename}\n\n")
                            f.write(f_itr.read())
                    except FileNotFoundError:
                        pass



    def on(self, target, component):
        self._on_config_file_make(target, component)
        ttbl.power.daemon_c.on(self, target, component)
