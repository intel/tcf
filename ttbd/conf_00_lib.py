#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import copy
import errno
import logging
import os
import random
import re
import shutil
import subprocess
import time

import ipaddress
import netifaces

import commonl
import ttbl
import ttbl.router


# FIXME: this should be in ttbl
class vlan_pci(ttbl.power.impl_c):
    """Power controller to implement networks on the server side.

    This allows to:

    - connect a server to a test network (NUT) to provide services
      suchs as DHCP, HTTP, network tapping, proxying between NUT and
      upstream networking, etc

    - connect virtual machines running inside virtual networks in the
      server to physical virtual networks.

    This behaves as a power control implementation that when turned:

    - on: sets up the interfaces, brings them up, start capturing

    - off: stops all the network devices, making communication impossible.

    :param str bridge_ifname: Name for the network interface in
       the server that will represent a connection to the VLAN.

       This is normally set to the target name, but if it is too
       long (more than 16 characters), it will fail. This allows to
       set it to anything else.

       >>> bridge_ifname = "nw30"

    **Configuration**

    Example configuration (see :ref:`naming networks <bp_naming_networks>`):

    >>> target = ttbl.test_target("nwa")
    >>> target.interface_add("power", ttbl.power.interface(vlan_pci()))
    >>> ttbl.config.interconnect_add(
    >>>     target,
    >>>     tags = {
    >>>         'ipv4_addr': '192.168.97.1',
    >>>         'ipv4_prefix_len': 24,
    >>>         'ipv6_addr': 'fd:99:61::1',
    >>>         'ipv6_prefix_len': 104,
    >>>         'mac_addr': '02:61:00:00:00:01:',
    >>>     })

    Now QEMU targets (for example), can declare they are part of this
    network and upon start, create a tap interface for themselves::

      $ ip tuntap add IFNAME mode tap
      $ ip link set IFNAME up master bnwa
      $ ip link set IFNAME promisc on up

    which then is given to QEMU as::

      -device virtio-net-pci,netdev=nwa,mac=MACADDR,romfile=
      -netdev tap,id=nwa,script=no,if_name=IFNAME

    (targets implemented by
    :func:`conf_00_lib_pos.target_qemu_pos_add` and
    :py:func:`conf_00_lib_mcu.target_qemu_zephyr_add` with VMs
    implement this behaviour).

    If a tag named *mac_addr* is given, containing the MAC address
    of a physical interface in the system, then it will be taken over
    as the point of connection to external targets. Connectivity from
    any virtual machine in this network will be extended to said
    network interface, effectively connecting the physical and virtual
    targets.

    .. warning:: PHYSICAL mode (mac_addr) not re-tested

    .. warning:: DISABLE Network Manager's (or any other network
                 manager) control of this interface, otherwise it will
                 interfere with it and network will not operate.

                 Follow :ref:`these steps <howto_nm_disable_control>`

    **System setup**

    - *ttbd* must be ran with CAP_NET_ADMIN so it can create network
       interfaces. For that, either add to systemd's
       ``/etc/systemd/system/ttbd@.service``::

         CapabilityBoundingSet = CAP_NET_ADMIN
         AmbientCapabilities = CAP_NET_ADMIN

      or as root, give ttbd the capability::

        # setcap cap_net_admin+pie /usr/bin/ttbd

    - *udev*'s */etc/udev/rules.d/ttbd-vlan*::

        SUBSYSTEM == "macvtap", ACTION == "add", DEVNAME == "/dev/tap*", \
            GROUP = "ttbd", MODE = "0660"

      This is needed so the tap devices can be accessed by user
      *ttbd*, which is the user that runs the daemon.

      Remember to reload *udev*'s configuration with `udevadm control
      --reload-rules`.

      This is already taken care by the RPM installation.

    **Fixture setup**

    - Select a network interface to use (it can be a USB or PCI
      interface); find out it's MAC address with *ip link show*.

    - add the tag *mac_addr* with said address to the tags of the
      target object that represents the network to which which said
      interface is to be connected; for example, for a network called
      *nwc*

      >>> target = ttbl.test_target("nwa")
      >>> target.interface_add("power", ttbl.power.interface(vlan_pci()))
      >>> ttbl.config.interconnect_add(
      >>>     target,
      >>>     tags = {
      >>>         'ipv4_addr': '192.168.97.1',
      >>>         'ipv4_prefix_len': 24,
      >>>         'ipv6_addr': 'fd:00:61::1',
      >>>         'ipv6_prefix_len': 104,
      >>>         'mac_addr': "a0:ce:c8:00:18:73",
      >>>     })

      or for an existing network (such as the configuration's default
      *nwa*):

      .. code-block:: python

         # eth dongle mac 00:e0:4c:36:40:b8 is assigned to NWA
         ttbl.test_target.get('nwa').tags_update(dict(mac_addr = '00:e0:4c:36:40:b8'))

      Furthermore, default networks *nwa*, *nwb* and *nwc* are defined
      to have a power control rail (versus an individual power
      controller), so it is possible to add another power controller
      to, for example, power on or off a network switch:

      .. code-block:: python

         ttbl.test_target.get('nwa').pc_impl.append(
             ttbl.pc.dlwps7("http://USER:PASSWORD@sp5/8"))

      This creates a power controller to switch on or off plug #8 on
      a Digital Loggers Web Power Switch named *sp5* and makes it part
      of the *nwa* power control rail. Thus, when powered on, it will
      bring the network up up and also turn on the network switch.

    - add the tag *vlan* to also be a member of an ethernet VLAN
      network (requires also a *mac_addr*):

      >>> target = ttbl.test_target("nwa")
      >>> target.interface_add("power", ttbl.power.interface(vlan_pci()))
      >>> ttbl.config.interconnect_add(
      >>>     target,
      >>>     tags = {
      >>>         'ipv4_addr': '192.168.97.1',
      >>>         'ipv4_prefix_len': 24,
      >>>         'ipv6_addr': 'fd:00:61::1',
      >>>         'ipv6_prefix_len': 104,
      >>>         'mac_addr': "a0:ce:c8:00:18:73",
      >>>         'vlan': 30,
      >>>     })

      in this case, all packets in the interface described by MAC addr
      *a0:ce:c8:00:18:73* with tag *30*.

    - lastly, for each target connected to that network, update it's
      tags to indicate it:

      .. code-block:: python

         ttbl.test_target.get('TARGETNAME-NN').tags_update(
             {
               'ipv4_addr': "192.168.10.30",
               'ipv4_prefix_len': 24,
               'ipv6_addr': "fd:00:10::30",
               'ipv6_prefix_len': 104,
             },
             ic = 'nwc')

    By convention, the server is .1, the QEMU Linux virtual machines
    are set from .2 to .10 and the QEMU Zephyr virtual machines from
    .30 to .45. Physical targets are set to start at 100.

    Note the networks for targets and infrastructure :ref:`have to be
    kept separated <separated_networks>`.

    """
    def __init__(self, bridge_ifname = None):
        if bridge_ifname != None:
            assert isinstance(bridge_ifname, str) \
                and len(bridge_ifname) <= self.IFNAMSIZ, \
                "bridge_ifname: expected string of at most" \
                f" {self.IFNAMSIZ} characters; got {type(bridge_ifname)}" \
                f" {bridge_ifname}"
            commonl.verify_str_safe(bridge_ifname,
                                    name = "network interface name")
        self.bridge_ifname = bridge_ifname
        ttbl.power.impl_c.__init__(self)


    # linux/include/if.h
    IFNAMSIZ = 16


    def _if_rename(self, target):
        if self.bridge_ifname:
            bridge_ifname = self.bridge_ifname
        else:
            bridge_ifname = target.id

        if 'mac_addr' in target.tags:
            # We do have a physical device, so we are going to first,
            # rename it to match the IC's name (so it allows targets
            # to find it to run IP commands to attach to it)
            ifname = commonl.if_find_by_mac(target.property_get('mac_addr'))
            if ifname == None:
                raise ValueError("Cannot find network interface with MAC '%s'"
                                 % target.property_get('mac_addr'))
            if ifname != bridge_ifname:
                subprocess.check_call("ip link set %s down" % ifname,
                                      shell = True)
                subprocess.check_call("ip link set %s name b%s"
                                      % (ifname, bridge_ifname), shell = True)



    @staticmethod
    def _get_mode(target):
        if 'vlan' in target.tags and 'mac_addr' in target.tags:
            # we are creating ethernet vlans, so we do not own the
            # device exclusively and will create new links
            return 'vlan'
        elif 'vlan' in target.tags and 'mac_addr' not in target.tags:
            raise RuntimeError("vlan ID specified without a mac_addr")
        elif 'mac_addr' in target.tags:
            # we own the device exclusively
            return 'physical'
        else:
            return 'virtual'



    def on(self, target, _component):
        if self.bridge_ifname != None:
            bridge_ifname = self.bridge_ifname
        else:
            bridge_ifname = "b" + target.id
        # Bring up the lower network interface; lower is called
        # whatever (if it is a physical device) or _bNAME; bring it
        # up, make it promiscuous
        mode = self._get_mode(target)
        if mode == 'vlan':
            vlan_id = target.property_get(
                "vlan_id",
                target.property_get("vlan"))

            # our lower is a physical device, our upper is a device
            # which till tag for eth vlan %(vlan)
            ifname = commonl.if_find_by_mac(target.property_get('mac_addr'),
                                            physical = True)
            if not commonl.if_present(bridge_ifname):
                # Do create the new interface only if not already
                # created, otherwise daemons that are already running
                # will stop operating
                # This function might be being called to restablish a
                # half baked operating state.
                subprocess.check_call(
                    "/usr/sbin/ip link add"
                    f" link {ifname} name {bridge_ifname}"
                    f" type vlan id {vlan_id}",
                    #" protocol VLAN_PROTO"
                    #" reorder_hdr on|off"
                    #" gvrp on|off mvrp on|off loose_binding on|off"
                    shell = True)
                subprocess.check_call(	# bring lower up
                    f"/usr/sbin/ip link set dev {ifname} up promisc on",
                    shell = True)
        elif mode == 'physical':
            ifname = commonl.if_find_by_mac(target.property_get('mac_addr'))
            subprocess.check_call(	# bring lower up
                f"/usr/sbin/ip link set dev {ifname} up promisc on",
                shell = True)
            self._if_rename(target)
        elif mode == 'virtual':
            # We create a bridge, to serve as lower
            if not commonl.if_present(bridge_ifname):
                # Do create the new interface only if not already
                # created, otherwise daemons that are already running
                # will stop operating
                # This function might be being called to restablish a
                # half baced operating state.
                commonl.if_remove_maybe(bridge_ifname)
                subprocess.check_call(
                    f"/usr/sbin/ip link add name {bridge_ifname} type bridge",
                    shell = True)
                subprocess.check_call(	# bring lower up
                    f"/usr/sbin/ip link set dev {bridge_ifname} up promisc on",
                    shell = True)
        else:
            raise AssertionError("Unknown mode %s" % mode)

        # Configure the IP addresses for the top interface
        subprocess.check_call(		# clean up existing address
            f"/usr/sbin/ip add flush dev {bridge_ifname}", shell = True)
        subprocess.check_call(		# add IPv6
            # if this fails, check Network Manager hasn't disabled ipv6
            # sysctl -a | grep disable_ipv6 must show all to 0
            "/usr/sbin/ip addr add"
            f"  {target.kws['ipv6_addr']}/{target.kws['ipv6_prefix_len']}"
            f" dev {bridge_ifname}",
            shell = True)
        subprocess.check_call(		# add IPv4
            "/usr/sbin/ip addr add"
            f"  {target.kws['ipv4_addr']}/{target.kws['ipv4_prefix_len']}"
            f"  dev {bridge_ifname}", shell = True)

        # Bring up the top interface, which sets up ther outing
        subprocess.check_call(
            f"/usr/sbin/ip link set dev {bridge_ifname} up promisc on",
            shell = True)



    def off(self, target, component):
        if self.bridge_ifname != None:
            bridge_ifname = self.bridge_ifname
        else:
            bridge_ifname = "b" + target.id
        # remove the top level device
        mode = self._get_mode(target)
        if mode == 'physical':
            # bring down the lower device
            ifname = commonl.if_find_by_mac(target.property_get('mac_addr'))
            subprocess.check_call(
                # flush the IP addresses, bring it down
                f"/usr/sbin/ip add flush dev {ifname}; "
                f"/usr/sbin/ip link set dev {ifname} down promisc off",
                shell = True)
        elif mode == 'vlan':
            commonl.if_remove_maybe(bridge_ifname)
            # nothing; we killed the upper and on the lwoer, a
            # physical device we do nothing, as others might be using it
            pass
        elif mode == 'virtual':
            commonl.if_remove_maybe(bridge_ifname)
        else:
            raise AssertionError("Unknown mode %s" % mode)

        target.fsdb.set('power_state', 'off')	# FIXME: COMPAT/remove



    @staticmethod
    def _find_addr(addrs, addr):
        for i in addrs:
            if i['addr'] == addr:
                return i
        return None



    def get(self, target, _component):
        if self.bridge_ifname != None:
            bridge_ifname = self.bridge_ifname
        else:
            bridge_ifname = "b" + target.id
        # we know we have created an interface named bNWNAME, so let's
        # check it is there
        if not os.path.isdir("/sys/class/net/" + bridge_ifname):
            return False

        mode = self._get_mode(target)
        # FIXME: check bNWNAME exists and is up
        if mode == 'vlan':
            pass
        elif mode == 'physical':
            pass
        elif mode == 'virtual':
            pass
        else:
            raise AssertionError("Unknown mode %s" % mode)

        # Verify IP addresses are properly assigned
        addrs = netifaces.ifaddresses(bridge_ifname)
        if 'ipv4_addr' in target.kws:
            addrs_ipv4 = addrs.get(netifaces.AF_INET, None)
            if addrs_ipv4 == None:
                target.log.info(
                    "vlan_pci/%s: off because no ipv4 addresses are assigned"
                    % bridge_ifname)
                return False	                # IPv4 address not set
            addr = self._find_addr(addrs_ipv4, target.kws['ipv4_addr'])
            if addr == None:
                target.log.info(
                    "vlan_pci/%s: off because ipv4 address %s not assigned"
                    % (bridge_ifname, target.kws['ipv4_addr']))
                return False	                # IPv4 address mismatch
            prefixlen = ipaddress.IPv4Network(
                str('0.0.0.0/' + addr['netmask'])).prefixlen
            if prefixlen != target.kws['ipv4_prefix_len']:
                target.log.info(
                    "vlan_pci/%s: off because ipv4 prefix is %s; expected %s"
                    % (bridge_ifname, prefixlen, target.kws['ipv4_prefix_len']))
                return False	                # IPv4 prefix mismatch

        if 'ipv6_addr' in target.kws:
            addrs_ipv6 = addrs.get(netifaces.AF_INET6, None)
            if addrs_ipv6 == None:
                target.log.info(
                    "vlan_pci/%s: off because no ipv6 address is assigned"
                    % bridge_ifname)
                return False	                # IPv6 address not set
            addr = self._find_addr(addrs_ipv6, target.kws['ipv6_addr'])
            if addr == None:
                target.log.info(
                    "vlan_pci/%s: off because ipv6 address %s not assigned"
                    % (bridge_ifname, target.kws['ipv6_addr']))
                return False	                # IPv6 address mismatch
            prefixlen = ipaddress.IPv6Network(str(addr['netmask'])).prefixlen
            if prefixlen != target.kws['ipv6_prefix_len']:
                target.log.info(
                    "vlan_pci/%s: off because ipv6 prefix is %s; expected %s"
                    % (bridge_ifname, prefixlen, target.kws['ipv6_prefix_len']))
                return False	                # IPv6 prefix mismatch

        return True



def target_vlan_add(nw_name: str,
                    switch_target: ttbl.test_target,
                    mac_addr: str, vlan_id: int,
                    ipv4_addr: str, ipv4_prefix_len: int,
                    ipv6_addr: str, ipv6_prefix_len: int,
                    switch_class: ttbl.router.router_c = ttbl.router.cisco_c,
                    bridge_ifname: str = None,
                    tftp: bool = True):
    """
    Creates a target that implements an interconnect/network using 802.1Q VLAN

    It is recommended to use low VLAN ids (eg: 2-9) since:

    - they are the same in hexadecimal, decimal (so both IPv4 and
      IPv6 look the same)

    - under 256 (so they can be used straight in IPv6 and IPv4
      addreses

    - So they work on most switches (0 is reserved by the spec, 1
      is reserved in Cisco)

    Thus, VLAN X yields 192.X.0.0/16 and fd:99:X::1/104.

    :param str nw_name: name for the target representing this network

    :param ttbl.test_target switch_target: target which represents
      the switch on which we'll be creating the VLAN

    :param ttbl.router.router_c switch_class: class (derivative of
      router_c) that implements the details of each router
      model/make

      >>> switch_class = ttbl.router.cisco_c

    :param str mac_addr: MAC address of the interface in the
      server that is connected to the switch. (six hex bytes
      separated by colons)

      >> mac_addr = "00:11:22:33:44:55"

    :param int vlan_id: integer representing the 802.1Q VLAN ID;
      valid numbers depend on the switch; the standard allows
      1-4096; it is recommended to use 2-254 to be able to use the
      same in IP ranges.

      >> vlan_id = 4

    :param str ipv4_addr: IPv4 address of the server in the VLAN;
      normally we use .1 for the server and the second nibble (4
      in the example) matches the VLAN:

      >>> ipv4_addr = f"192.4.0.1"


    :param int ipv4_prefix_len: IPv4 address prefix; (0-32) used to
      determine the network mask; most common: 8, 16, 24.

      Building on the previous example:

      >>> ipv4_prefix_len = 16

      Would assing to this VLAN an IPv4 range of 65k IP addresses,
      with a server/router 192.4.0.1, a network address 192.4.0.0
      and a broadcast 192.4.255.255.

    :param str ipv4_addr: same as ipv4_addr, but for IPv6 addresses:

      >>> ipv6_addr = f"fd:99:4::1"

    :param int ipv6_prefix_len: same as ipv4_prefix_len, but for
      IPv6 addresses.

      Building on the previous example:

      >>> ipv6_prefix_len = 104

    :param str bridge_ifname: Name for the network interface in
      the server that will represent a connection to the VLAN.

      This is normally set to the target name, but if it is too
      long (more than 16 characters), it will fail. This allows to
      set it to anything else.

      >>> bridge_ifname = "nw30"

    :param bool tftp: (optional; default *True*) enable TFTP
      services in the VLAN

    **Example**

    Create six VLANs

    >>> vlan_ids = [ 2, 3, 4, 5, 6, 7 ]

    >>> for vlan_id in vlan_ids:
    >>>     target_vlan_add(
    >>>         f"nw{vlan_id}",
    >>>         switch_target,
    >>>         mac_addr = "78:ac:44:6d:0b:19",  # server's NIC connected to switch
    >>>         vlan_id = vlan_id,
    >>>         ipv4_addr = f"192.{vlan_id}.0.1", ipv4_prefix_len = 16,
    >>>         ipv6_addr = f'fd:99:{vlan_id:02x}::1', ipv6_prefix_len = 104)


    **Requirements**

    - *ttbd* server must be able to connect to the switch to configure it

    - *ttbd* server must have a network connection to the switch
      to be able to serve DHCP, DNS, TFTP and others and to
      capture network traffic

    **Implementation Details**

    There are a set of top level inventory field in the inventory
    that are used by the different components:

    - mac_addr: MAC address of the interface that is connected to the switch

    - vlan: the ID of the 802.1Q VLAN

    - ipv4_addr, ipv4_prefix_len: IPv4 address of the server host in that
      network; off the network mask it generates the network address +
      bcast

    - ipv6_addr,ipv6_prefix_len: Same, for IPv6

    This network target, when powered on:

    - configures the switch to enable the VLAN and allow only the
      targets in the allocation to access it
      (:class:`ttbl.router.vlan_manager_c`).

      Refer to the this class' documentation to understand the
      flow.

    - configures a network interface in the server that can
      connect to the now created VLAN in the switch
      (:class:`conf_00_lib.vlan_pci`).

    - starts DHCP, DNS and TFTP services on said interface
      (:class:`ttbl.dnsmasq.pc`).

    """
    assert isinstance(nw_name, str)
    assert isinstance(switch_target, ttbl.test_target), \
        "switch_target: expected ttbl.test_target describing the" \
        " switch, got {type(switch_target)}"
    assert issubclass(switch_class, ttbl.router.router_c), \
        "switch_class: expected subclass of ttbl.router.router_c; " \
        f" got {switch_class}"


    assert isinstance(mac_addr, str), \
        "mac_addr: expected string with six hex bytes as HH:HH:HH:HH:HH:HH; got: %s %s" \
        % (type(mac_addr), mac_addr)
    assert isinstance(vlan_id, int) and 1 < vlan_id < 4096, \
        "vlan_id: expected integer between 1 and 4096;" \
        f" got {type(vlan_id)} {vlan_id}"

    assert isinstance(ipv4_addr, str), \
        "ipv4_addr: expected IPv4 address A.B.C.D; " \
        f" got {type(ipv4_addr)} {ipv4_addr}"
    assert isinstance(ipv4_prefix_len, int) \
        and 0 < ipv4_prefix_len < 32, \
        "ipv4_prefix_len: expected integer between 1 and 31;" \
        f" got {type(ipv4_prefix_len)} {ipv4_prefix_len}"

    assert isinstance(ipv6_addr, str), \
        "ipv6_addr: expected IPv6 address A:B:...:1; " \
        f" got {type(ipv6_addr)} {ipv6_addr}"
    assert isinstance(ipv6_prefix_len, int) \
        and 1 < ipv6_prefix_len < 128, \
        "ipv6_prefix_len: expected integer between 1 and 128;" \
        f" got {type(ipv6_prefix_len)} {ipv6_prefix_len}"

    assert isinstance(tftp, bool), \
        f"tftp: expected bool; got {type(tftp)} {tftp}"


    # Port is a global variable in the server that indicates what
    # is the port the server is listening on; note is far from
    # good (FIXME) since if we modify via cmdlineargs, it gets
    # updated after the config files are parsed :/
    if args.ssl:		# FIXME: this is very fugly
        server_url = f"https://{ipv4_addr}:{port}"
        server_url6 = f"https://{ipv6_addr}:{port}"
    else:
        server_url = f"http://{ipv4_addr}:{port}"
        server_url6 = f"http://{ipv6_addr}:{port}"

    # create vlans on power-on
    # destroy vlans on power-off, release -> power interface powers off on
    # release if off_on_release is defined
    ic = ttbl.interconnect_c(
        nw_name,
        _type = "eth_network_vlan",
        _tags = {
            # FIXME: add bitrate info
            "mac_addr": mac_addr,
            "vlan": vlan_id,
            "ipv4_addr": ipv4_addr,
            "ipv4_prefix_len": ipv4_prefix_len,
            'ipv6_addr': ipv6_addr,
            'ipv6_prefix_len': ipv6_prefix_len,
            'server': {
                "url": server_url,
                "url6": server_url6,
            }
        }
    )

    ic.interface_add("power", ttbl.power.interface(
        # when powered on, tells the switch to create vlan vlan_id
        switch_vlan_setup = ttbl.router.vlan_manager_c(
            switch_target = switch_target,
            switch_class = switch_class),
        # configure a network interface to the vlan on mac_addr
        netif = vlan_pci(bridge_ifname = bridge_ifname),
        # setup a DHCP/DNS server on the network interface we just
        # setup; it finds it by the ipv4_addr; uses it's network
        # parameters to attach.
        dhcp = ttbl.dnsmasq.pc(ifname = bridge_ifname,
                               allow_other_macs = True,
                               tftp = True),
    ))

    ic.interface_add("console", ttbl.console.interface(
        **{ "log-dnsmasq": ttbl.console.logfile_c("dnsmasq.log") }))

    ttbl.config.interconnect_add(ic)

    return ic



def target_add_to_vlan_interconnects(
        target: ttbl.test_target,
        vlan_targets: list[ttbl.test_target],
        mac_addr: str,
        switch_port_spec: str,
        nibble: int = None,
        vlan_id_set: bool = False,
        tunnel_allow_lan: bool = None,
        tags_extra = None):
    """
    Add a target to a list of VLAN networks

    Given a target, update its interconnect information to ensure that
    it lists the ability to connect to a list of VLAN networks.

    :param ttbl.test_target target: target on which to operate

    :param list[ttbl.interconnect_c] vlan_targets: list of targets,
      each describing a VLAN-based interconnect.

      >>> vlan_targets = []
      >>> for vlan_id in vlan_ids:
      >>>     vlan_target = target_vlan_add(
      >>>         f"nw{vlan_id}",
      >>>         switch_target,
      >>>         mac_addr = "87:ca:44:d6:0b:91",
      >>>         vlan_id = vlan_id,
      >>>         ipv4_addr = f"192.{vlan_id}.0.1", ipv4_prefix_len = 16,
      >>>         ipv6_addr = f'fd:99:{vlan_id:02x}::1', ipv6_prefix_len = 104)
      >>>     vlan_targets.append(vlan_target)

    :param str mac_addr: MAC address of the interface in the target
      that connects to the switch where the VLAN network is
      implemented (six hex bytes separated by colons):

      >> mac_addr = "00:11:22:33:44:55"

    :param str switch_port_spec: specification of the port (in switch
      specific format) in which the cable for the interface with MAC
      address given in *mac_addr* argument is connectde into the switch.

      This is used to allow those ports to access the VLAN when
      created.

      E.g.: for a Cisco switch

      >> switch_port_spec = "Eth1/43"

    :param int nibble: what number to give this machine in the IP
      address allocation for each VLAN.

      The allocation of IP numbers is automated by looking at the IP
      range from the VLAN network target (eg: 192.30.0.1/16 for VLAN
      #30); the last nibble .1 is replaced with the nibble argument,
      which has to be between 2 and 254.

      >>> nibble = 3

    :param bool vlan_id_set: (optional, default *False*) set the
       *interconnects.NETWORK.vlan_id* property with the 801.1Q VLAN
       id.

       This means that the target needs to configure the network
       interface with VLAN tagging and it has to be done by the client
       scripting.

       If the switch is configured to allow untagged traffic, this can
       be left unset, as the traffic will be routed without tagging.

    :param dict tags_extra: (optional, default *None*) dictionary of
       extra key/values to add to the tags for this interconnect

       >>> tags_extra = { "default_router": False, nibble = "%(nibble)s" }

    :param bool tunnel_allow_lan: (optional, default *None*) if
      specified, set the *tunnel_allow_lan* field in the target's
      interconnect inventory (see :mod:`ttbl.tunnel`).
    """
    assert isinstance(target, ttbl.test_target), \
        f"target: expected ttbl.test_target; got {type(target)} {target}"

    assert all(isinstance(i, ttbl.interconnect_c) for i in vlan_targets), \
        "vlan_targets: all items need to be ttbl.interconnect_c"

    assert isinstance(nibble, int) and 1 < nibble < 255, \
        "nibble: expected an integer > 1 and < 255 for the last part" \
        f" of the IP address; got {type(nibble)} {nibble}"

    # FIXME: verify vlan_ids (1, 254)
    # FIXME: this needs to be made more generic--since we need to be
    # able to link against the name of an existing vlan target which
    # might be in another server anwyay

    for vlan_target in vlan_targets:
        vlan_id = vlan_target.property_get(
            "vlan_id",
            vlan_target.property_get("vlan"))
        # get the IP address prefixes -- kinda hack it
        #
        # 192.{vlan_id}.0.1 -> prefix 192.{vlan_id}.0.
        # fd:99:{vlan_id:02x}::{nibble:02x} -> fd:99:{vlan_id:02x}::
        #
        #
        ipv4_prefix = ".".join(vlan_target.property_get('ipv4_addr').split('.')[:-1])
        # IPv6 addresses might have consecutive :, so use re.split()
        ipv6_prefix = ":".join(re.split(":+", vlan_target.property_get('ipv6_addr'))[:-1])
        tags = dict(
            # this is the SUT's MAC addr of the card that is connected to
            # the high speed switch -- we found it with 'ip l', who
            # has LOWER_UP and no IP address
            mac_addr = mac_addr,
            switch_port = switch_port_spec,
            # We take the network parameters from the vlan_target
            #
            # The IP address is the same, but replace the .1 -> COUNT
            # (or ::1 with ::COUNT in hex)
            # The prefix len is the same as the network's
            ipv4_addr = f"{ipv4_prefix}.{nibble}",
            ipv4_prefix_len = vlan_target.property_get('ipv4_prefix_len'),
            ipv6_addr = f'{ipv6_prefix}::{nibble:02x}',
            ipv6_prefix_len = vlan_target.property_get('ipv6_prefix_len'),
        )
        if tunnel_allow_lan != None:
            assert isinstance(tunnel_allow_lan, bool)
            tags['tunnel_allow_lan'] = tunnel_allow_lan
        if vlan_id_set:
            # depending on how we decide to configure the switch, if
            # it needs tagging or not, we add the vlan_id field
            tags['vlan_id'] = vlan_id
        if tags_extra != None:
            commonl.assert_dict_key_strings(tags_extra, "tags_extra")
            # yep, format with tags, we have most of th einfo there
            kws = dict(tags).update({
                "nibble": nibble,
                "id": target.id,
            })
            for k, v in tags_extra.items():
                if isinstance(v, str):
                    tags[k] = v % kws
                else:
                    tags[k] = v

        target.add_to_interconnect(vlan_target.id, tags)
