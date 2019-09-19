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
import ttbl.cm_serial
import ttbl.dhcp
import ttbl.flasher
import ttbl.pc
import ttbl.pc_ykush
import ttbl.rsync
import ttbl.socat
import ttbl.tt
import ttbl.tt_qemu
import ttbl.tt_qemu2
import ttbl.usbrly08b


def qemu_pos_add(target_name,
                 nw_name,
                 mac_addr,
                 ipv4_addr,
                 ipv6_addr,
                 consoles = None,
                 disk_size = "30G",
                 mr_partsizes = "1:4:5:5",
                 sd_iftype = 'virtio',
                 extra_cmdline = "",	# pylint: disable = unused-argument
                 ram_megs = 2048):
    """Add a QEMU virtual machine capable of booting over Provisioning OS.

    This target supports a serial console (*ttyS0*) and a single hard
    drive that gets fully reinitialized every time the server is
    restarted.

    Note this target uses a UEFI bios *and* defines UEFI storage
    space; this is needed so the right boot order is maintained.

    Add to a server configuration file ``/etc/ttbd-*/conf_*.py``

    >>> target = qemu_pos_add("qemu-x86-64-05a"
    >>>                       "nwa",
    >>>                       mac_addr = "02:61:00:00:00:05",
    >>>                       ipv4_addr = "192.168.95.5",
    >>>                       ipv6_addr = "fc00::61x:05")

    Extra paramenters can be added by using the *extra_cmdline*
    arguments, such as for example, to add VNC display:

    >>>                       extra_cmdline = "-display vnc=0.0.0.0:0",

    Adding to other networks:

    >>> ttbl.config.targets['nuc-43'].add_to_interconnect(
    >>>     'nwb', dict(
    >>>         mac_addr = "02:62:00:00:00:05",
    >>>         ipv4_addr = "192.168.98.5", ipv4_prefix_len = 24,
    >>>         ipv6_addr = "fc00::62:05", ipv6_prefix_len = 112)

    
    :param str target_name: name of the target to create

    :param str nw_name: name of the network to which this target will
      be connected that provides Provisioning OS services.

    :param str mac_addr: MAC address for this target (fake one). Will
      be given to the virtual device created and can't be the same as
      any other MAC address in the system or the networks. It is
      recommended to be in the format:

      >>> 02:HX:00:00:00:HY

      where HX and HY are two hex digits

    :param str disk_size: (optional) size specification for the
      target's hard drive, as understood by QEMU's qemu-img create
      program.

    :param list(str) consoles: serial consoles to create (defaults to
      just one, which is also the minimum).

    :param int ram_megs: (optional) size of memory in megabytes

    :param str mr_partsizes: (optional) specification for partition
      sizes for the multiroot Provisoning OS environment. FIXME:
      document link

    :param str extra_cmdline: a string with extra command line to add;
      %(FIELD)s supported (target tags).


    """
    if consoles == None or consoles == []:
        consoles = [ 'ttyS0' ]
    assert isinstance(target_name, basestring)
    assert isinstance(consoles, list) \
        and all([ isinstance(console, basestring) for console in consoles ])
    assert len(consoles) >= 1
    assert ram_megs > 0

    if sd_iftype == 'virtio':
        pos_boot_dev = 'vda'
    elif sd_iftype == 'scsi':
        pos_boot_dev = 'sda'
    elif sd_iftype == 'ide':
        pos_boot_dev = 'sda'
    else:
        raise AssertionError("Don't know dev name for disk iftype %s"
                             % sd_iftype)

    target =  ttbl.tt_qemu2.tt_qemu(
        target_name,
        """\
/usr/bin/qemu-system-x86_64 \
  -enable-kvm \
  -drive if=pflash,format=raw,readonly,file=/usr/share/edk2/ovmf/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=%%(path)s/OVMF_VARS.fd \
  -m %(ram_megs)s \
  -drive file=%%(path)s/hd.qcow2,if=%(sd_iftype)s,aio=threads \
  -boot order=nc \
  %(extra_cmdline)s \
""" % locals(),
        consoles = consoles,
        _tags = dict(
            bsp_models = { 'x86_64': None },
            bsps = dict(
                x86_64 = dict(console = 'x86_64', linux = True),
            ),
            ssh_client = True,
            pos_capable = dict(
                boot_to_pos = 'pxe',
                boot_config = 'uefi',
                boot_to_normal = 'pxe',
                mount_fs = 'multiroot',
            ),
            pos_boot_interconnect = nw_name,
            pos_boot_dev = pos_boot_dev,
            pos_partsizes = mr_partsizes,
            linux_serial_console_default = consoles[0],
        )
    )
    # set up the consoles
    target.power_on_pre_fns.append(target._power_on_pre_consoles)
    # Setup the network hookups (requires vlan_pci)
    target.power_on_pre_fns.append(target._power_on_pre_nw)
    # tell QEMU to start the VM once we have it all setup
    target.power_on_post_fns.append(target._qmp_start)
    target.power_off_post_fns.append(target._power_off_post_nw)
    target.power_on_pre_fns.append(ttbl.dhcp.power_on_pre_pos_setup)

    # Create an HD for this guy -- we do it after creating the
    # target so the state path is created -- double check if the
    # drive already exists so not to override it? nah, screw
    # it--it is supposed to be all throwaway
    subprocess.check_call([
        "qemu-img", "create", "-q", "-f", "qcow2",
        "%s/hd.qcow2" % (target.state_dir),
        disk_size
    ])
    # reinitialize also the EFI vars storage
    shutil.copy("/usr/share/OVMF/OVMF_VARS.fd", target.state_dir)
    ttbl.config.target_add(target, target_type = "qemu-uefi-x86_64")
    target.add_to_interconnect(
        nw_name,
        dict(
            ipv4_addr = ipv4_addr, ipv4_prefix_len = 24,
            ipv6_addr = ipv6_addr, ipv6_prefix_len = 112,
            mac_addr = mac_addr,
        )
    )




class vlan_pci(ttbl.tt_power_control_impl):
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

      $ tcf broker-file-download FILENAME

    *FILENAME* must be a valid file name, with no directory
    components.

    .. note:: Note this requires the property *tcpdump* being
              registered in the configuration with
    
              >>> ttbl.test_target.properties_user.add('tcpdump')

              so normal users can set/unset it.

    Example configuration (see :ref:`naming networks <bp_naming_networks>`):

    >>> ttbl.config.interconnect_add(
    >>>     ttbl.tt.tt_power("nwa", vlan_pci()),
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

   (:py:class:`ttbl.tt_qemu2.tt_qemu` and
   :py:class:`Zephyr <conf_00_lib_mcu.tt_qemu_zephyr>` VMs already
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

      .. code-block:: python

         ttbl.config.target_add(
             ttbl.tt.tt_power('nwc', vlan_pci()),
             tags = dict(
                 mac_addr = "a0:ce:c8:00:18:73",
                 ipv6_addr = 'fc00::13:1',
                 ipv6_prefix_len = 112,
                 ipv4_addr = '192.168.13.1',
                 ipv4_prefix_len = 24,
             )
         )
         ttbl.config.targets['NAME'].tags['interfaces'].append('interconnect_c')

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

      .. code-block:: python

         ttbl.config.inteconnect_add(
             ttbl.tt.tt_power('nwc', vlan_pci()),
             tags = dict(
                 mac_addr = "a0:ce:c8:00:18:73",
                 vlan = 30,
                 ipv6_addr = 'fc00::13:1',
                 ipv6_prefix_len = 112,
                 ipv4_addr = '192.168.13.1',
                 ipv4_prefix_len = 24))

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
        ttbl.tt_power_control_impl.__init__(self)

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

    def power_on_do(self, target):
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


    def power_off_do(self, target):
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

    def power_get_do(self, target):

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

        # FIXME: check IP addresses are assigned, if is up
        return True

# declare the property we normal users to be able to set
ttbl.test_target.properties_user.add('tcpdump')


#: A capturer to take screenshots from VNC
#:
#: Note the fields are target's tags and others specified in
#: :class:`ttbl.capture.generic_snapshot` and
#: :class:`ttbl.capture.generic_stream`.
capture_screenshot_vnc = ttbl.capture.generic_snapshot(
    "%(id)s VNC @localhost:%(vnc_port)s",
    # need to make sure vnc_port is defined in the target's tags
    # needs the .png, otherwise it balks at guessing extensions
    # don't do -q, otherwise when it fails, it fails silently
    "gvnccapture localhost:%(vnc_port)s %(output_file_name)s",
    mimetype = "image/png",
    extension = ".png"
)

vnc_port_count = 0

def nw_default_targets_add(letter, pairs = 5):
    """
    Add the default targets to a configuration

    This adds a configuration which consists of a network and @pairs
    pairs of QEMU Linux VMs (one without upstream NAT connection, one with).

    The network index nw_idx will be used to assign IP addresses
    (192.168.IDX.x and fc00::IDX:x)

    IP address assignment:
    - .1         is the server (this machine)
    - .2 - 10    Virtual Linux machines
    - .30 - 45   Virtual Zephyr machines
    - .100- 255  Real HW targets

    """
    assert isinstance(letter, basestring)
    assert len(letter) == 1

    nw_idx = ord(letter)
    nw_name = "nw" + letter

    # Add the network target
    ttbl.config.interconnect_add(
        ttbl.tt.tt_power(nw_name, [ vlan_pci() ]),
        tags = dict(
            ipv6_addr = 'fc00::%02x:1' % nw_idx,
            ipv6_prefix_len = 112,
            ipv4_addr = '192.168.%d.1' % nw_idx,
            ipv4_prefix_len = 24,
        ),
        ic_type = "ethernet"
    )
    
    global vnc_port_count
    count = 0
    # Add QEMU Fedora Linux targets with addresses .4+.5, .6+.7, .7+.8...
    # look in TCF's documentation for how to generate tcf-live.iso
    for pair in range(pairs + 1):
        v = pair + 4
        target_name = "qu%02d" % v + letter
        qemu_pos_add(target_name,
                     nw_name,
                     # more distros support ide than virtio/scsi with
                     # generic kernels
                     sd_iftype = 'ide',
                     mr_partsizes = "1:4:5:8",
                     mac_addr = "02:%02x:00:00:00:%02x" % (nw_idx, v),
                     ipv4_addr = "192.168.%d.%d" % (nw_idx, v),
                     ipv6_addr = "fc00::%02x:%02x" % (nw_idx, v),
                     extra_cmdline = "-cpu host" \
                     " -display vnc=0.0.0.0:%d" % vnc_port_count)
        target = ttbl.config.targets[target_name]
        target.tags_update(dict(vnc_port = vnc_port_count))
        target.interface_add("capture", ttbl.capture.interface(
            # capture screenshots from VNC, return a PNG
            screen = "vnc0",
            vnc0 = capture_screenshot_vnc,
        ))
        vnc_port_count += 1
