#! /usr/bin/python
#
# Copyright (c) 2017-20 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""IP Tunneling interface
----------------------

This interface allows the server to tunnel connections from its public
IP interfaces to targets present in internal test networks
(:term:`NUT`) which are isolated from the public ones.

Tunnels can only be created by the target's owner and are deleted when
the target is released.

Scripts can use the client API to:

- meth:`target.tunnel.add <tcfl.target_ext_tunnel.extension.add>`
- meth:`target.tunnel.remove <tcfl.target_ext_tunnel.extension.add>`
- meth:`target.tunnel.list <tcfl.target_ext_tunnel.extension.list>`

or call the HTTP interface:

- GET PREFIX/ttb-v1/targets/TARGETNAME/tunnel/list
- PUT PREFIX/ttb-v1/targets/TARGETNAME/tunnel/add
- DELETE PREFIX/ttb-v1/targets/TARGETNAME/tunnel/remove

"""

import ipaddress
import subprocess

import commonl
import ttbl

class interface(ttbl.tt_interface):

    def __init__(self):
        ttbl.tt_interface.__init__(self)

    def _target_setup(self, target, iface_name):
        # wipe all leftover tunnels info, when we start there shall be none
        for tunnel_id in target.fsdb.keys("interfaces.tunnel.*.protocol"):
            prefix = tunnel_id[:-len(".protocol")]
            target.fsdb.set(prefix + ".__id", None)
            target.fsdb.set(prefix + ".ip_addr", None)
            target.fsdb.set(prefix + ".protocol", None)
            target.fsdb.set(prefix + ".port", None)
        pass


    def _release_hook(self, target, _force):
        # remove all active tunnels
        for tunnel_id in target.fsdb.keys("interfaces.tunnel.*.protocol"):
            local_port = tunnel_id[len("interfaces.tunnel."):-len(".protocol")]
            self._delete_tunnel(target, local_port)


    def _ip_addr_validate(self, target, _ip_addr):
        # validate ip_addr is a valid IP address to create a tunnel
        # to, it is properly written, the server can actually reach
        # it, etc
        ip_addr = ipaddress.ip_address(unicode(_ip_addr))
        for ic_data in target.tags.get('interconnects', {}).itervalues():
            if not ic_data:
                continue
            for key, value in ic_data.iteritems():
                if not key.endswith("_addr"):
                    continue
                if not key.startswith("ip"):
                    # this has to be an IP address...
                    continue
                itr_ip_addr = ipaddress.ip_address(unicode(value))
                if ip_addr == itr_ip_addr:
                    return
        # if this is an interconnect, the IP addresses are at the top level
        for key, value in target.tags.iteritems():
            if not key.endswith("_addr"):
                continue
            itr_ip_addr = ipaddress.ip_address(unicode(value))
            if ip_addr == itr_ip_addr:
                return
        raise ValueError('Cannot setup tunnel to IP "%s" which is '
                         'not owned by this target' % ip_addr)

    valid_protocols = (
        # valid protocols we can tunnel to (at the target's end)
        'tcp', 'udp', 'sctp',
        'tcp4', 'udp4', 'sctp4',
        'tcp6', 'udp6', 'sctp6'
    )


    def _check_args(self, ip_addr, port, protocol):
        # check the ip address, port and protocol arguments, converting
        # the port to numeric if specified as string
        if isinstance(port, basestring):
            port = int(port)
        assert port >= 0 and port < 65536
        assert isinstance(protocol, basestring)
        protocol = protocol.lower()
        assert protocol in self.valid_protocols, \
            "unsupported protocol '%s' (must be " % protocol \
            + " ".join(self.valid_protocols) + ")"
        # this format is also used down in get() # COMPAT
        tunnel_id = "%s__%s__%d" % (protocol, ip_addr.replace(".", "_"), port)
        return ( ip_addr, port, protocol, tunnel_id )


    def put_tunnel(self, target, who, args, _files, _user_path):
        """
        Setup a TCP/UDP/SCTP v4 or v5 tunnel to the target

        Parameters are same as :meth:`ttbl.tt_interface.request_process`

        Parameters specified in the *args* dictionary from the HTTP
        interface:

        :param str ip_addr: target's IP address to use (it must be
          listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param int port: port to redirect to
        :param str protocol: Protocol to tunnel: {udp,sctp,tcp}[{4,6}]

        :returns dict: dicionary with a single key *result* set ot the
          *local_port* where to TCP connect to reach the tunnel.
        """
        ip_addr, port, protocol, tunnel_id = self._check_args(
            self.arg_get(args, 'ip_addr', basestring),
            self.arg_get(args, 'port', int),
            self.arg_get(args, 'protocol', basestring),
        )
        self._ip_addr_validate(target, ip_addr)
        with target.target_owned_and_locked(who):
            for tunnel_id in target.fsdb.keys("interfaces.tunnel.*.protocol"):
                prefix = tunnel_id[:-len(".protocol")]
                _ip_addr = target.fsdb.get(prefix + ".ip_addr")
                _protocol = target.fsdb.get(prefix + ".protocol")
                _port = target.fsdb.get(prefix + ".port")
                _pid = target.fsdb.get(prefix + ".__id")
                _lport = prefix[len("interfaces.tunnel."):]
                if _ip_addr == ip_addr \
                   and _protocol == protocol \
                   and _port == port \
                   and commonl.process_alive(_pid, "/usr/bin/socat"):
                    # there is already an active tunnel for this port
                    # and it is alive, so use that
                    return dict(result = int(_lport))

            local_port = commonl.tcp_port_assigner(
                port_range = ttbl.config.tcp_port_range)
            ip_addr = ipaddress.ip_address(unicode(ip_addr))
            if isinstance(ip_addr, ipaddress.IPv6Address):
                # beacause socat (and most others) likes it like that
                ip_addr = "[%s]" % ip_addr
            # this could be refactored using daemon_c, but it'd be
            # harder to follow the code and it is not really needed.
            p = subprocess.Popen(
                [
                    "/usr/bin/socat",
                    "-ly", "-lp", tunnel_id,
                    "%s-LISTEN:%d,fork,reuseaddr" % (protocol, local_port),
                    "%s:%s:%s" % (protocol, ip_addr, port)
                ],
                shell = False, cwd = target.state_dir,
                close_fds = True)

            pid = commonl.process_started(
                p.pid, "/usr/bin/socat",
                verification_f = commonl.tcp_port_busy,
                verification_f_args = ( local_port, ),
                tag = "socat-" + tunnel_id, log = target.log)
            if p.returncode != None:
                raise RuntimeError("TUNNEL %s: socat exited with %d"
                                   % (tunnel_id, p.returncode))
            ttbl.daemon_pid_add(p.pid)	# FIXME: race condition if it # died?
            target.fsdb.set("interfaces.tunnel.%s.__id" % local_port, p.pid)
            target.fsdb.set("interfaces.tunnel.%s.ip_addr" % local_port, str(ip_addr))
            target.fsdb.set("interfaces.tunnel.%s.protocol" % local_port, protocol)
            target.fsdb.set("interfaces.tunnel.%s.port" % local_port, port)
            return dict(result = local_port)

    @staticmethod
    def _delete_tunnel(target, local_port, pid = None):
        if pid == None:
            pid = target.fsdb.get("interfaces.tunnel.%s.__id" % local_port)
        try:
            if isinstance(pid, int):
                if commonl.process_alive(pid, "/usr/bin/socat"):
                    commonl.process_terminate(
                        pid, tag = "socat's tunnel [%s]: " % local_port)
        finally:
            # whatever happens, just wipe all info about it because
            # this might be a corrupted entry
            prefix = "interfaces.tunnel.%s" % local_port
            target.fsdb.set(prefix + ".__id", None)
            target.fsdb.set(prefix + ".ip_addr", None)
            target.fsdb.set(prefix + ".protocol", None)
            target.fsdb.set(prefix + ".port", None)

    def delete_tunnel(self, target, who, args, _files, _user_path):
        """
        Teardown a TCP/UDP/SCTP v4 or v6 tunnel to the target
        previously created with :meth:`put_tunnel`.

        Parameters are same as
        :meth:`ttbl.tt_interface.request_process`. Parameters
        specified in the *args* dictionary from the HTTP interface:

        :param str ip_addr: target's IP address to use (it must be
          listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param int port: port to redirect to
        :param str protocol: Protocol to tunnel: {udp,sctp,tcp}[{4,6}]

        :returns dict: emtpy dictionary

        """
        ip_addr, port, protocol, tunnel_id = self._check_args(
            self.arg_get(args, 'ip_addr', basestring),
            self.arg_get(args, 'port', int),
            self.arg_get(args, 'protocol', basestring),
        )
        with target.target_owned_and_locked(who):
            for tunnel_id in target.fsdb.keys("interfaces.tunnel.*.protocol"):
                prefix = tunnel_id[:-len(".protocol")]
                _ip_addr = target.fsdb.get(prefix + ".ip_addr")
                _protocol = target.fsdb.get(prefix + ".protocol")
                _port = target.fsdb.get(prefix + ".port")
                _pid = target.fsdb.get(prefix + ".__id")
                _lport = prefix[len("interfaces.tunnel."):]
                if _ip_addr == ip_addr \
                   and _protocol == protocol \
                   and _port == port:
                    self._delete_tunnel(target, _lport, _pid)
        return dict()


    @staticmethod
    def get_list(target, who, _args, _files, _user_path):	# COMPAT
        """
        List existing tunnels

        :returns: a dictionary with a key *result* containing a list
          of tuples representing current active tunnels in form::

            (protocol, target-ip-address, port, port-in-server)
        """
        with target.target_owned_and_locked(who):
            tunnels = []
            for tunnel_id in target.fsdb.keys("interfaces.tunnel.*.protocol"):
                local_port = tunnel_id[len("interfaces.tunnel."):-len(".protocol")]
                ip_addr = target.fsdb.get("interfaces.tunnel.%s.ip_addr" % local_port)
                protocol = target.fsdb.get("interfaces.tunnel.%s.protocol" % local_port)
                port = target.fsdb.get("interfaces.tunnel.%s.port" % local_port)
                ip_addr = ip_addr.replace("_", ".")
                tunnels.append(( protocol, ip_addr, port, local_port ))
            return dict(result = tunnels)
