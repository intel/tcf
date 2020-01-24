#! /usr/bin/python2
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

import commonl
import ttbl
import ttbl.capture
import ttbl.dhcp
import ttbl.pc
import ttbl.pc_ykush
import ttbl.rsync
import ttbl.socat
import ttbl.usbrly08b


class vlan_pci(ttbl.power.impl_c):
    """Power controller to implement networks on the server side.

    Supports:

    - connecting the server to a physical net physical networks with
      physical devices (normal or VLAN networks)

    - creating internal virtual networks with `macvtap
      http://virt.kernelnewbies.org/MacVTap` so VMs running in the
      host can get into said networks.

      When a physical device is also present, it is used as the upper
      device (instead of a bridge) so traffic can flow from physical
      targets to the virtual machines in the network.

    - *tcpdump* capture of network traffic

    This behaves as a power control implementation that when turned:

    - on: sets up the interfaces, brings them up, start capturing

    - off: stops all the network devices, making communication impossible.


    **Capturing with tcpdump**

    Can be enabled setting the target's property *tcpdump*::

      $ tcf property-set TARGETNAME tcpdump FILENAME

    this will have the target dump all traffic capture to a file
    called *FILENAME* in the daemon file storage area for the user who
    owns the target. The file can then be recovered with::

      $ tcf store-download FILENAME

    *FILENAME* must be a valid file name, with no directory
    components.

    .. note:: Note this requires the property *tcpdump* being
              registered in the configuration with
    
              >>> ttbl.test_target.properties_user.add('tcpdump')

              so normal users can set/unset it.

    Example configuration (see :ref:`naming networks <bp_naming_networks>`):

    >>> target = ttbl.test_target("nwa")
    >>> target.interface_add("power", ttbl.power.interface(vlan_pci()))
    >>> ttbl.config.interconnect_add(
    >>>     target,
    >>>     tags = {
    >>>         'ipv4_addr': '192.168.97.1',
    >>>         'ipv4_prefix_len': 24,
    >>>         'ipv6_addr': 'fc00::61:1',
    >>>         'ipv6_prefix_len': 112,
    >>>         'mac_addr': '02:61:00:00:00:01:',
    >>>     })

    Now QEMU targets (for example), can declare they are part of this
    network and upon start, create a tap interface for themselves::

      $ ip link add link _bnwa name tnwaTARGET type macvtap mode bridge
      $ ip link set tnwaTARGET address 02:01:00:00:00:IC_INDEX up

    which then is given to QEMU as an open file descriptor::

      -net nic,model=virtio,macaddr=02:01:00:00:00:IC_INDEX
      -net tap,fd=FD

    (targets implemented by
    :func:`conf_00_lib_pos.target_qemu_pos_add` and
    :py:func:`conf_00_lib_mcu.target_qemu_zephyr_add` with VMs
    implement this behaviour).

    Notes:

    - keep target names short, as they will be used to generate
      network interface names and those are limited in size (usually to
      about 12 chars?), eg tnwaTARGET comes from *nwa* being the
      name of the network target/interconnect, TARGET being the target
      connected to said interconnect.

    - IC_INDEX: is the index of the TARGET in the interconnect/network;
      it is recommended, for simplicty to make them match with the mac
      address, IP address and target name, so for example:

      - targetname: pc-04
      - ic_index: 04
      - ipv4_addr: 192.168.1.4
      - ipv6_addr: fc00::1:4
      - mac_addr: 02:01:00:00:00:04

    If a tag named *mac_addr* is given, containing the MAC address
    of a physical interface in the system, then it will be taken over
    as the point of connection to external targets. Connectivity from
    any virtual machine in this network will be extended to said
    network interface, effectively connecting the physical and virtual
    targets.

    .. warning:: DISABLE Network Manager's (or any other network
                 manager) control of this interface, otherwise it will
                 interfere with it and network will not operate.

                 Follow :ref:`these steps <howto_nm_disable_control>`

    System setup:

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
      >>>         'ipv6_addr': 'fc00::61:1',
      >>>         'ipv6_prefix_len': 112,
      >>>         'mac_addr': "a0:ce:c8:00:18:73",
      >>>     })

      or for an existing network (such as the configuration's default
      *nwa*):

      .. code-block:: python

         # eth dongle mac 00:e0:4c:36:40:b8 is assigned to NWA
         ttbl.config.targets['nwa'].tags_update(dict(mac_addr = '00:e0:4c:36:40:b8'))

      Furthermore, default networks *nwa*, *nwb* and *nwc* are defined
      to have a power control rail (versus an individual power
      controller), so it is possible to add another power controller
      to, for example, power on or off a network switch:

      .. code-block:: python

         ttbl.config.targets['nwa'].pc_impl.append(
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
      >>>         'ipv6_addr': 'fc00::61:1',
      >>>         'ipv6_prefix_len': 112,
      >>>         'mac_addr': "a0:ce:c8:00:18:73",
      >>>         'vlan': 30,
      >>>     })

      in this case, all packets in the interface described by MAC addr
      *a0:ce:c8:00:18:73* with tag *30*.

    - lastly, for each target connected to that network, update it's
      tags to indicate it:

      .. code-block:: python

         ttbl.config.targets['TARGETNAME-NN'].tags_update(
             {
               'ipv4_addr': "192.168.10.30",
               'ipv4_prefix_len': 24,
               'ipv6_addr': "fc00::10:30",
               'ipv4_prefix_len': 112,
             },
             ic = 'nwc')

    By convention, the server is .1, the QEMU Linux virtual machines
    are set from .2 to .10 and the QEMU Zephyr virtual machines from
    .30 to .45. Physical targets are set to start at 100.

    Note the networks for targets and infrastructure :ref:`have to be
    kept separated <separated_networks>`.

    """
    def __init__(self):
        ttbl.power.impl_c.__init__(self)

    @staticmethod
    def _if_rename(target):
        if 'mac_addr' in target.tags:
            # We do have a physical device, so we are going to first,
            # rename it to match the IC's name (so it allows targets
            # to find it to run IP commands to attach to it)
            ifname = commonl.if_find_by_mac(target.tags['mac_addr'])
            if ifname == None:
                raise ValueError("Cannot find network interface with MAC '%s'"
                                 % target.tags['mac_addr'])
            if ifname != target.id:
                subprocess.check_call("ip link set %s down" % ifname,
                                      shell = True)
                subprocess.check_call("ip link set %s name b%s"
                                      % (ifname, target.id), shell = True)

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
        # Bring up the lower network interface; lower is called
        # whatever (if it is a physical device) or _bNAME; bring it
        # up, make it promiscuous
        mode = self._get_mode(target)
        if mode == 'vlan':
            # our lower is a physical device, our upper is a device
            # which till tag for eth vlan %(vlan)
            ifname = commonl.if_find_by_mac(target.tags['mac_addr'],
                                            physical = True)
            commonl.if_remove_maybe("b%(id)s" % target.kws)
            kws = dict(target.kws)
            kws['ifname'] = ifname
            subprocess.check_call(
                "/usr/sbin/ip link add"
                " link %(ifname)s name b%(id)s"
                " type vlan id %(vlan)s"
                #" protocol VLAN_PROTO"
                #" reorder_hdr on|off"
                #" gvrp on|off mvrp on|off loose_binding on|off"
                % kws, shell = True)
            subprocess.check_call(	# bring lower up
                "/usr/sbin/ip link set dev %s up promisc on" % ifname,
                shell = True)
        elif mode == 'physical':
            ifname = commonl.if_find_by_mac(target.tags['mac_addr'])
            subprocess.check_call(	# bring lower up
                "/usr/sbin/ip link set dev %s up promisc on" % ifname,
                shell = True)
            self._if_rename(target)
        elif mode == 'virtual':
            # We do not have a physical device, a bridge, to serve as
            # lower
            commonl.if_remove_maybe("_b%(id)s" % target.kws)
            subprocess.check_call(
                "/usr/sbin/ip link add"
                "  name _b%(id)s"
                "  type bridge"
                % target.kws, shell = True)
            subprocess.check_call(
                "/usr/sbin/ip link add"
                "  link _b%(id)s name b%(id)s"
                "  type macvlan mode bridge; "
                % target.kws, shell = True)
            subprocess.check_call(	# bring lower up
                "/usr/sbin/ip link set"
                "  dev _b%(id)s"
                "  up promisc on"
                % target.kws, shell = True)
        else:
            raise AssertionError("Unknown mode %s" % mode)

        # Configure the IP addresses for the top interface
        subprocess.check_call(		# clean up existing address
            "/usr/sbin/ip add flush dev b%(id)s "
            % target.kws, shell = True)
        subprocess.check_call(		# add IPv6
            # if this fails, check Network Manager hasn't disabled ipv6
            # sysctl -a | grep disable_ipv6 must show all to 0
            "/usr/sbin/ip addr add"
            "  %(ipv6_addr)s/%(ipv6_prefix_len)s dev b%(id)s "
            % target.kws, shell = True)
        subprocess.check_call(		# add IPv4
            "/usr/sbin/ip addr add"
            "  %(ipv4_addr)s/%(ipv4_prefix_len)d"
            "  dev b%(id)s" % target.kws, shell = True)

        # Bring up the top interface, which sets up ther outing
        subprocess.check_call(
            "/usr/sbin/ip link set dev b%(id)s up promisc on"
            % target.kws, shell = True)

        target.fsdb.set('power_state', 'on')

        # Start tcpdump on the network?
        #
        # The value of the tcpdump property, if not None, is the
        # filename we'll capture to.
        tcpdump = target.fsdb.get('tcpdump')
        if tcpdump:
            assert not os.path.sep in tcpdump \
                and tcpdump != "" \
                and tcpdump != os.path.pardir \
                and tcpdump != os.path.curdir, \
                "Bad filename for TCP dump capture '%s' specified as " \
                " value to property *tcpdump*: must not include" % tcpdump
            # per ttbd:make_ticket(), colon splits the real username
            # from the ticket
            owner = target.owner_get().split(":")[0]
            assert owner, "BUG? target not owned on power on?"
            capfile = os.path.join(target.files_path, owner, tcpdump)
            # Because it is in the user's area,
            # we assume the user knows what he is doing to overwrite it,
            # so we'll remove any first
            commonl.rm_f(capfile)
            pidfile = os.path.join(target.state_dir, "tcpdump.pid")
            logfile = os.path.join(target.state_dir, "tcpdump.log")
            cmdline = [
                "/usr/sbin/tcpdump", "-U",
                "-i", "_b%(id)s" % target.kws,
                "-w", capfile
            ]
            try:
                logf = open(logfile, "a")
                target.log.info("Starting tcpdump with: %s", " ".join(cmdline))
                p = subprocess.Popen(
                    cmdline, shell = False, cwd = target.state_dir,
                    close_fds = True, stdout = logf,
                    stderr = subprocess.STDOUT)
            except OSError as e:
                raise RuntimeError("tcpdump failed to start: %s" % e)
            ttbl.daemon_pid_add(p.pid)	# FIXME: race condition if it died?
            with open(pidfile, "w") as pidfilef:
                pidfilef.write("%d" % p.pid)

            pid = commonl.process_started(		# Verify it started
                pidfile, "/usr/sbin/tcpdump",
                verification_f = os.path.exists,
                verification_f_args = ( capfile, ),
                timeout = 20, tag = "tcpdump", log = target.log)
            if pid == None:
                raise RuntimeError("tcpdump failed to start after 5s")


    def off(self, target, component):
        # Kill tcpdump, if it was started
        pidfile = os.path.join(target.state_dir, "tcpdump.pid")
        commonl.process_terminate(pidfile, tag = "tcpdump",
                                  path = "/usr/sbin/tcpdump")
        # remove the top level device
        mode = self._get_mode(target)
        if mode == 'physical':
            # bring down the lower device
            ifname = commonl.if_find_by_mac(target.tags['mac_addr'])
            subprocess.check_call(
                # flush the IP addresses, bring it down
                "/usr/sbin/ip add flush dev %s; "
                "/usr/sbin/ip link set dev %s down promisc off"
                % (ifname, ifname),
                shell = True)
        elif mode == 'vlan':
            commonl.if_remove_maybe("b%(id)s" % target.kws)
            # nothing; we killed the upper and on the lwoer, a
            # physical device we do nothing, as others might be using it
            pass
        elif mode == 'virtual':
            commonl.if_remove_maybe("b%(id)s" % target.kws)
            # remove the lower we created
            commonl.if_remove_maybe("_b%(id)s" % target.kws)
        else:
            raise AssertionError("Unknown mode %s" % mode)

        target.fsdb.set('power_state', 'off')


    def get(self, target, _component):
        # we know we have created an interface named bNWNAME, so let's
        # check it is there
        if not os.path.isdir("/sys/class/net/b" + target.id):
            return False

        mode = self._get_mode(target)
        # FIXME: check bNWNAME exists and is up
        if mode == 'vlan':
            pass
        elif mode == 'physical':
            pass
        elif mode == 'virtual':
            # check _bNWNAME exists
            if not os.path.isdir("/sys/class/net/_b" + target.id):
                return False
        else:
            raise AssertionError("Unknown mode %s" % mode)

        # FIXME: check IP addresses are assigned, if is up, until then
        # return None, as we can't ensure the config is properly set
        # so it has to be reset
        return None


# FIXME: replace tcpdump with a interconnect capture interface
# declare the property we normal users to be able to set
ttbl.test_target.properties_user.add('tcpdump')
