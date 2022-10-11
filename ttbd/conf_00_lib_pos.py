#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
TTBD configuration library to add targets that use Provisioning OS to
flash OS images
---------------------------------------------------------------------

"""
import re
import shutil
import string
import subprocess

import ttbl
import ttbl.qemu
import ttbl.dnsmasq

def nw_indexes(nw_name):
    """Return the network indexes that correspond to a one or two letter
    network name.

    :param str nw_name: a one or two letter network name in the set
      *a-zA-Z*.

    :returns: x, y, vlan_id; x and y are meant to be used for creating
      IP addresses (IPv4 192.x.y.0/24, IPv6 fd:x:y::0/104)

      (yes, 192.x.y/0.24 with x != 168 is not private, but this is
      supposed to be running inside a private network anyway, so you
      won't be able to route there).

    """
    assert isinstance(nw_name, str) \
        and len(nw_name) in [ 1, 2 ] \
        and all(i in string.ascii_lowercase + string.ascii_uppercase
                for i in nw_name), \
        "nw_name must be one or two letters in the set [a-zA-Z], " \
        "got '%s'" % nw_name
    if len(nw_name) == 1:	# old style
        # vlan IDs 65 (A) -> 122 (z)
        return 168, ord(nw_name), ord(nw_name)
    else:
        x = ord(nw_name[0])
        y = ord(nw_name[1])
        # there are 57 characters from A to z in ASCII, we'll ignore
        # the seven between Z and a.
        # So our digits are the index of the letter in ASCII
        #
        # letter: A  B  C  D  E ....  a  b  c  d  e     ... z
        # index:  0  1  2  3  4 ....  32 33 34 35 36 ...... 57
        #
        # so, for example, cE will be 34 * 57 + 4 = 1942
        #
        # However, we see collisions between at the boundry of the
        # first character. More precisely, <char>z and <char+1>A shares
        # the same VLAN. For example, Cz = DA because
        #    Cz = 2 * 57 + 57 = 171
        # and
        #    DA = 3 * 57 +  0 = 171
        # To correct for this, we add a linearly increasing offset, i.e.
        # the index of first letter. As such,
        #    Cz = (2 * 57 + 2) + 57 = 173
        # but
        #    DA = (3 * 57 + 3) +  0 = 174
        #
        # For completeness, cE = (34 * 57 + 34) + 4 = 1976
        #
        # Now, because in the one letter system we used A-Za-z and our
        # maximum vlan ID was thus ASCII(z) [122], we offset up to
        # that, so cE will be 1976 + 122  = 2098
        #
        # Unfortunately, the formula we used above has a collision of 
        # network z with AA. 
        #    z = 122
        # and
        #   AA = (0 * 57 + 0) + 0 + 122 = 122 
        #
        # To take care of this, we introduce an constant offset of 1.
        # As such, 
        #   AA = (0 * 57 + 0) + 0 + 1 + 122 = 123
        #
        # Note the highest number will be for zz (57 * 57 + 57 + 57 + 1 + 122),
        # 3486, still well below the most conservative VLAN ID limit.
        #
        # Formula is (x-A) * 57 + (x-A) + (y-A) + 1 + z, 
        # which can be simplified to
        #
        vlan_id = (x - ord('A')) * 58 + (y - ord('A')) + 1 + ord('z')
        return x, y, vlan_id


def nw_pos_add(nw_name, power_rail = None,
               mac_addr = None, vlan = None,
               ipv4_prefix_len = 24,
               ipv6_prefix_len = 104):
    """Adds configuration for a network with :ref:`Provisioning OS
    <provisioning_os>` support.

    This setups the network with the power rails needed for targets
    that can boot Provisioning OS to deploy images to their hard
    drives.

    For example, to add *nwb*, *192.168.98.0/24* with the server on
    *192.168.98.1* adding proxy port redirection from the isolated network
    to that upstream the server:

    >>> x, y, _ = nw_indexes('b')
    >>> interconnect = nw_pos_add(
    >>>     'b', mac_addr = '00:50:b6:27:4b:77',
    >>>     power_rail = [
    >>>         ttbl.pc.dlwps7('http://admin:1234@sp7/4'),
    >>>         # disable the proxy redirection, using tinyproxy
    >>>         # running on :8888
    >>>         # Mirrors of Clear and other stuff, see distro_mirrors below
    >>>         ttbl.socat.pci('tcp', "192.%d.%d.1" % (x, y), 1080,
    >>>                        'linux-ftp.jf.intel.com', 80),
    >>>         ttbl.socat.pci('tcp', "192.%d.%d.1" % (x, y), 1443,
    >>>                        'linux-ftp.jf.intel.com', 443),
    >>>     ])
    >>>
    >>> interconnect.tags_update(dict(
    >>>     # implemented by tinyproxy running in the server
    >>>     ftp_proxy = "http://192.%d.%d.1:8888" % (x, y),
    >>>     http_proxy = "http://192.%d.%d.1:8888" % (x, y),
    >>>     https_proxy = "http://192.%d.%d.1:8888" % (x, y),

    Note how first we calculate, from the network names the nibbles
    we'll use for IP addresses. This is only needed because we are
    adding extras to the basic configuration.

    :param str nw_name: network name, which must be one or two ASCII
      letters, uppwer or lowercase; see :ref:`best naming practices
      <bp_naming_networks>`.

      >>> letter = "aD"

      would yield a network called *nwAD*.

    :param str mac_addr: (optional) if specified, this is connected to
      the physical network adapter in the server with the given MAC
      address in six 16-bit hex digits (*hh:hh:hh:hh:hh:hh*).

      Note the TCF server will take over said interface, bring it up,
      down, remove and add IP address etc, so it cannot be shared with
      any interface being used for other things.

    :param int vlan: (optional) use Ethernet VLANs

      - None: do not use vlans (default)
      - 0: configure this network to use a VLAN on the physical
        interface; the VLAN ID is calculated from the network
        name.
      - N > 0: the number is used as the VLAN ID.

    :param list power_rail: (optional) list of
      :class:`ttbl.power.impl_c` objects that control power
      to this network.

      This can be used to power on/off switches, start daemons, etc
      when the network is started:

      >>> power_rail = [
      >>>     # power on the network switch plugged to PDU sp7, socket 4
      >>>     ttbl.pc.dlwps7('http://admin:1234@sp7/4'),
      >>>     # start two port redirectors to a proxy
      >>>     ttbl.socat.pci('tcp', "192.168.%d.1" % nw_idx, 1080,
      >>>                    'proxy-host.domain', 80),
      >>>     ttbl.socat.pci('tcp', "192.168.%d.1" % nw_idx, 1443,
      >>>                    'proxy-host.domain', 443),
      >>> ]

    :returns: the interconect object added
    """
    assert vlan == None or vlan >= 0
    assert vlan == None or isinstance(mac_addr, str)

    if power_rail == None:
        power_rail = []
    # we don't check the power_rail, since ttb.power.interface() will
    # do for us.

    x, y, _vlan_id = nw_indexes(nw_name)
    nw_name = "nw" + nw_name

    # Create the network target
    interconnect = ttbl.test_target(nw_name)

    interconnect.interface_add(
        "power",
        ttbl.power.interface(
            *		# yeah, asterisk, so this is converted to *args...
            # Virtual networking inside the server, for the VMs
            [ ( "vlan setup", vlan_pci() ) ]
            # Power rails passed by the user, to power on switches or whatever
            + power_rail
            # the rest of the components we need
            + [
                ( "rsync", ttbl.rsync.pci("192.%d.%d.1" % (x, y), 'images',
                                          '/home/ttbd/images') ),
                ( "dnsmasq", ttbl.dnsmasq.pc() ),
            ]))

    # Consoles to read misc log files
    interconnect.interface_add(
        "console",
        ttbl.console.interface(**{
            "log-dnsmasq": ttbl.console.logfile_c("dnsmasq.log")
        })
    )

    tags = dict(
        ipv6_addr = 'fd:%02x:%02x::1' % (x, y),
        ipv6_prefix_len = ipv6_prefix_len,
        ipv4_addr = '192.%d.%d.1' % (x, y),
        ipv4_prefix_len = ipv4_prefix_len,
        # implemented by tinyproxy running in the server
        ftp_proxy = "http://192.%d.%d.1:8888" % (x, y),
        http_proxy = "http://192.%d.%d.1:8888" % (x, y),
        https_proxy = "http://192.%d.%d.1:8888" % (x, y),
        # Provisioning OS support to boot off PXE on nfs root
        pos_http_url_prefix = "http://192.%d.%d.1/ttbd-pos/%%(bsp)s/" % (x, y),
        # FIXME: have the daemon hide the internal path?
        pos_nfs_server = "192.%d.%d.1" % (x, y),
        pos_nfs_path = "/home/ttbd/images/tcf-live/%(bsp)s",
        # implemented by ttbl.rsync above
        pos_rsync_server = "192.%d.%d.1::images" % (x, y)
    )

    if mac_addr:
        tags['mac_addr'] = mac_addr
    if vlan == None:
        pass
    elif vlan == 0:
        tags['vlan'] = _vlan_id
    elif vlan > 0:
        tags['vlan'] = vlan

    ttbl.config.interconnect_add(interconnect, tags = tags,	# add it
                                 ic_type = "ethernet")
    return interconnect


_target_name_regex = re.compile(
    "(?P<type>[0-9a-zA-Z_]+)"
    "-(?P<index>[0-9]+)"
    "(?P<network>[a-zA-Z]+)")
_target_type_regex = re.compile("^[-0-9a-zA-Z_]+$")
_target_type_long_regex = re.compile("^[- 0-9a-zA-Z_]+$")
_target_index_regex = re.compile("^[0-9]+$")
_target_network_regex = re.compile("^[a-zA-Z]+$")

_partsizes_regex = re.compile("^[0-9]+:[0-9]+:[0-9]+:[0-9]+$")
_linux_serial_console_regex = re.compile("^tty[^/]+$")


def pos_target_name_split(name):
    _target_name_regex = re.compile(
        "(?P<type>[0-9a-zA-Z_]+)"
        "-(?P<index>[0-9]+)"
        "(?P<network>[0-9a-zA-Z]+)")
    m = _target_name_regex.search(name)
    if not m:
        raise RuntimeError(
            "%s: target name doesn't meet POS naming convention"
            " TYPENAME-99NW" % name)
    gd = m.groupdict()
    return gd['type'], int(gd['index']), gd['network']


def target_pos_setup(target,
                     nw_name,
                     pos_boot_dev,
                     linux_serial_console_default,
                     pos_nfs_server = None,
                     pos_nfs_path = None,
                     pos_rsync_server = None,
                     boot_config = None,
                     boot_config_fix = None,
                     boot_to_normal = None,
                     boot_to_pos = None,
                     mount_fs = None,
                     pos_http_url_prefix = None,
                     pos_image = None,
                     pos_partsizes = None):
    """Given an existing target, add to it metadata used by the
    Provisioning OS mechanism.

    :param str nw_name: name of the network target that provides
      POS services to this target

    :param str pos_boot_dev: which is the boot device to use,
      where the boot loader needs to be installed in a boot
      partition. e.g.: ``sda`` for */dev/sda* or ``mmcblk01`` for
      */dev/mmcblk01*.

    :param str linux_serial_console_default: which device **the
      target** sees as the system's serial console connected to TCF's
      boot console.

      If *DEVICE* (eg: ttyS0) is given, Linux will be booted with the
      argument *console=DEVICE,115200*.

    :param str pos_nfs_server: (optional) IPv4 address of the NFS
      server that provides the Provisioning OS root filesystem

      e.g.: *192.168.0.6*

      Default is *None*, and thus taking from what the boot
      interconnect declares in the same metadata.

    :param str pos_nfs_path: path in the NFS server for the
      Provisioning OS root filesystem.

      Normally this is set from the information exported by the
      network *nw_name*.

      e.g.: */home/ttbd/images/tcf-live/x86_64/*.

      Default is *None*, and thus taking from what the boot
      interconnect declares in the same metadata.

    :param str pos_rsync_server: (optional) RSYNC URL where the
      Provisioning OS images are available.

      eg: *192.168.0.6::images*

      Default is *None*, and thus taking from what the boot
      interconnect declares in the same metadata.

    :param str boot_config: (optional) :data:`capability
      <tcfl.pos.capability_fns>` to configure the boot
      loader.

      e.g.: :func:`*uefi* <tcfl.pos_uefi.boot_config_multiroot>` (default)

    :param str boot_config_fix: (optional) :data:`capability
      <tcfl.pos.capability_fns>` to fix the boot
      loader configuration.

      e.g.: :func:`*uefi* <tcfl.pos_uefi.boot_config_fix>` (default)

    :param str boot_to_normal: (optional) :data:`capability
      <tcfl.pos.capability_fns>` to boot the system in normal (non
      provisioning) mode

      e.g.: :func:`*pxe* <tcfl.pos.target_power_cycle_to_normal_pxe>` (default)

    :param str boot_to_pos: (optional) :data:`capability
      <tcfl.pos.capability_fns>` to boot the system in provisioning
      mode.

      e.g.: :func:`*pxe* <tcfl.pos.target_power_cycle_to_pos_pxe>` (default)

    :param str mount_fs: (optional) :data:`capability
      <tcfl.pos.capability_fns>` to partition, select and mount the root
      filesystem during provisioning mode

      e.g.: :func:`*multiroot* <tcfl.pos_multiroot>` (default)

    :param str pos_http_url_prefix: (optional) prefix to give to the
      kernel/initrd for booting over TFTP or HTTP. Note: you want a
      trailing slash:

      e.g.: *http://192.168.0.6/ttbd-pos/x86_64/* for HTTP boot

      e.g.: *subdir* for TFTP boot from the *subdir* subdirectory

      Default is *None*, and thus taking from what the boot
      interconnect declares in the same metadata.

    :param str pos_image: (optional) name of the Provisioning image to
      use, which will be used for the kernel name, initrd name and NFS
      root path:

      - kernel: vmlinuz-POS-IMAGE
      - initrd: initrd-POS-IMAGE
      - root-path: POS-IMAGE/ARCHITECTURE

      e.g.: *tcf-live* (default)

    :part str pos_partsizes: (optional) sizes of the different
      partitions when using the :ref:`multiroot <pos_multiroot>`
      system to manage the target's disk; see
      :ref:`pos_multiroot_partsizes`.

      e.g.: *"1:10:30:20"* (default)

    """
    if not boot_config:
        boot_config = 'uefi'
    if not boot_config_fix:
        boot_config_fix = 'uefi'
    if not boot_to_normal:
        boot_to_normal = 'pxe'
    if not boot_to_pos:
        boot_to_pos = 'pxe'
    if not mount_fs:
        mount_fs = 'multiroot'
    if not pos_image:
        pos_image = 'tcf-live'
    if not pos_partsizes:
        pos_partsizes = "1:10:30:20"

    tags = dict(
        linux_serial_console_default = linux_serial_console_default,
        pos_boot_interconnect = nw_name,
        pos_boot_dev = pos_boot_dev,
        pos_capable = dict(
            boot_config = boot_config,
            boot_config_fix = boot_config_fix,
            boot_to_normal = boot_to_normal,
            boot_to_pos = boot_to_pos,
            mount_fs = mount_fs,
        ),
        pos_image = pos_image,
        pos_partsizes = pos_partsizes,
    )
    if pos_nfs_server:
        tags['pos_nfs_server'] = pos_nfs_server
    if pos_nfs_path:
        tags['pos_nfs_path'] = pos_nfs_path
    if pos_rsync_server:
        tags['pos_rsync_server'] = pos_rsync_server
    if pos_http_url_prefix:
        tags['pos_http_url_prefix'] = pos_http_url_prefix
    target.tags_update(tags)



def pos_target_add(
        name,			# TTYPE-INDEX
        mac_addr,		# HH:HH:HH:HH:HH:HH
        power_rail,	 	# spX/N
        boot_disk,		# "sda",
        pos_partsizes,		# "1:20:50:35",
        linux_serial_console,	# 'ttyUSB0'
        target_type = None,	# eg "NUC5i",
        target_type_long = None,# eg "Intel NUC5i5425OU",
        index = None,		# 3, 4, ... formatted as %02
        network = None,		# 'a', "AB", etc...
        power_on_pre_hook = None,
        extra_tags = None,
        pos_nfs_server = None,
        pos_nfs_path = None,
        pos_rsync_server = None,
        boot_config = None,
        boot_config_fix = None,
        boot_to_normal = None,
        boot_to_pos = None,
        mount_fs = None,
        pos_http_url_prefix = None,
        pos_image = None,
        ipv4_prefix_len = 24,
        ipv6_prefix_len = 104,
        serial_console_name = "serial0",
        tags = None):
    """
    Add a PC-class target that can be provisioned using Provisioning
    OS.

    :param str name: target's name, following the convention
      :ref:`*TYPE-NNNETWORK* <bp_naming_targets>`:

      - *TYPE* is the target's short type that describes targets that
        are generally the same
      - *NN* is a number 2 to 255
      - *NETWORK* is the name of the network it is connected to (the
        network target is actuall called *nwNETWORK*), see :ref:`naming
        *networks <bp_naming_networks>`.

      >>> pos_target_add('nuc5-02a', ..., target_type = "Intel NUC5i5U324")

    :param str mac_addr: MAC address for this target on its connection
      to network *nwNETWORK*.

      Can't be the same as any other MAC address in the system or that
      network. It shall be in the standard format of six hex digits
      separated by colons:

      >>> pos_target_add('nuc5-02a', 'c0:3f:d5:67:07:81', ...)

    :param ttbl.power.impl_c power_rail: Power control instance
      to power switch this target, eg:

      >>> pos_target_add('nuc5-02a', 'c0:3f:d5:67:07:81',
      >>>                ttbl.pc.dlwps7("http://admin:1234@POWERSWITCHANEM/3"),
      >>>                ...)

      This can also be a list of these if multiple components need to
      be powered on/off to power on/off the target.

      >>> pos_target_add('nuc5-02a', 'c0:3f:d5:67:07:81',
      >>>                [
      >>>                    ttbl.pc.dlwps7("http://admin:1234@POWERSWITCHANEM/3"),
      >>>                    ttbl.pc.dlwps7("http://admin:1234@POWERSWITCHANEM/4"),
      >>>                    ttbl.ipmi.pci("BMC_HOSTNAME")
      >>>                ],
      >>>                ...)
      >>>

    :param str power_rail: Address of the :class:`Digital Logger Web
      Power Switch <ttbl.pc.dlwps7>` in the form
      *[USER:PASSWORD@]HOSTNAME/PLUGNUMBER*.

      **LEGACY**

      eg: for a target *nuc5-02a* connected to plug #5 of a DLWPS7 PDU
      named *sp10*

      >>> pos_target_add('nuc5-02a', power_rail_dlwps = 'sp10/5', ...)

      Note there has to be at least one power spec given

    :param str boot_disk: base name of the disk (as seen by Linux)
      from which the device will boot to configure it as a boot loader
      and install a root filesystem on it

      eg for *nuc5-02a*:

      >>> pos_target_add("nuc5-2a", MAC, POWER, 'sda')

      Note */dev/* is not needed.

    :param str pos_partsizes: sizes of the partitions to create; this is a
      list of four numbers with sizes in gigabytes for the boot, swap,
      scratch and root partitions.

      eg:

      >>> pos_target_add("nuc5-2a", ..., pos_partsizes = "1:4:10:5")

      will create in this target a boot partition 1 GiB in size, then
      a swap partition 4 GiB, a scratch partition 10 GiB and then
      multiple root filesystem partitons of 5 GiB each (until the disk
      is exhausted).

    :param str linux_serial_console: name of the device that Linux
      sees when it boots as a serial console

      eg:

      >>> pos_target_add("nuc5-02a", ... linux_serial_console = "ttyS0"...)
      >>> pos_target_add("nuc6-03b", ... linux_serial_console = "ttyUSB0"...)

      Note */dev/* is not needed and that this is the device the
      **target** sees, not the server.

    :param str target_type: (optional) override target's type (guessed
      from the name), which will be reported in the *type* target
      metadata; eg, for *Intel NUC5i5*:

      >>> pos_target_add("nuc5-02a", ..., target_type = "Intel NUC5i5U324")

      The HW usually has many different types that are extremely
      similar; when such is the case, the *type* can be set to a
      common prefix and the tag *type_long* then added to contain the
      full type name (this helps simplifying the setup); see
      *target_type_long* and *extra_tags* below.

    :param str target_type_long: (optional) long version of the target
      type (see above). Defaults to the same as *target_type*

    :param int index: (optional) override the target's index guessed
      from the name with a (between 2 and 254); in the name it will be
      formatted with at least two decimal digits.

      >>> pos_target_add("nuc5-02a", index = 3, ...)

      In this case, trget *nuc-02a* will be assigned a default IP
      address of 192.168.97.3 instead of 192.168.97.2.

    :param str network: (optional) override the network name guessed
      from the target's name.

      This is one or two ASCII letters, uppwer or lowercase; see
      :ref:`best naming practices <bp_naming_networks>`.

      eg for *nuc5-02c*:

      >>> pos_target_add("nuc5-02c", network = 'a', ...)

      The network naming convention *nwa* of the example help keep
      network names short, needed for internal interface name
      limitation in Linux (for example). Note the IP addresses for nwX
      are *192.168.ascii(X).0/24*; thus for *nuc5-02a* in the example,
      it's IP address will be *192.168.168.65.2*.

      If the network were, for example, *Gk*, the IP address would be
      *192.71.107.2* (71 being ASCII(G), 107 ASCII(k)).

    :param dict extra_tags: extra tags to add to the target for information

      eg:

      >>> pos_target_add(name_prefix = "nuc5", ..., dict(
      >>>    fixture_usb_disk = "4289273ADF334",
      >>>    fixture_usb_disk = "4289273ADF334"
      >>> ))

    :param power_on_pre_hook: (optional) function the server
      calls before powering on the target so so it boots Provisioning
      OS mode or normal mode.

      This might be configuring the DHCP server to offer a TFTP file
      or configuring the TFTP configuration file a bootloader will
      pick, etc; for examples, look at:

      - :func:`ttbl.dhcp.power_on_pre_pos_setup`
      - :meth:`ttbl.ipmi.pci.pre_power_pos_setup`

      Default is :func:`ttbl.dhcp.power_on_pre_pos_setup`.

    For other parameters possible to control the POS settings, please
    look at :func:`target_pos_setup`

    """

    assert isinstance(name, str), \
        "name must be a string; got: %s %s" % (type(name).__name__, name)
    assert isinstance(mac_addr, str), \
        "mac_addr must be a string HH:HH:HH:HH:HH:HH; got: %s %s" \
        % (type(name).__name__, name)
    if power_rail:
        # FIXME: move to ttlb.power.validate_spec
        if isinstance(power_rail, ttbl.power.impl_c):
            pass
        elif isinstance(power_rail, str):
            # compat, a descriptor that gets transformed to a pc_dlwps7
            pass
        elif isinstance(power_rail, list):
            count = -1
            for pc in power_rail:
                count += 1
                if isinstance(pc, ttbl.power.impl_c):
                    continue
                if isinstance(pc, (tuple, list)):
                    # list of NAME, IMPL
                    if len(pc) != 2:
                        raise AssertionError(
                            "power rail #%d: list of %d items given;"
                            " expect 2 (NAME, IMPL)" % (count, len(pc)))
                    pc_name = pc[0]
                    pc_impl = pc[1]
                    if not isinstance(pc_name, str):
                        raise AssertionError(
                            "power rail #%d: first element must be a string; got %s"
                            % (count, type(pc_name)))
                    if not isinstance(pc_impl, ttbl.power.impl_c):
                        raise AssertionError(
                            "power rail #%d: second element must be a ttbl.power.impl_c; got %s"
                            % (count, type(pc_impl)))
        else:
            raise AssertionError(
                "power rail must be a power rail spec (ttbl.power.impl_c"
                " or list of them), see doc; got %s" % power_rail)
    assert isinstance(boot_disk, str) \
        and not '/' in boot_disk, \
        'boot_disk is the base name of the disk from which ' \
        'the device boots, eg "sda"; got: %s' % boot_disk
    assert isinstance(pos_partsizes, str) \
        and _partsizes_regex.search(pos_partsizes), \
        "pos_partsizes must match %s; got: %s" \
        % (_partsizes_regex.pattern, pos_partsizes)
    assert isinstance(linux_serial_console, str) \
        and _linux_serial_console_regex.search(linux_serial_console), \
        "linux_serial_console must be astring matching %s; got: %s" \
        % (_linux_serial_console_regex.pattern, linux_serial_console)

    assert target_type == None \
        or isinstance(target_type, str) \
        and _target_type_regex.match(target_type), \
        "target_type must match %s; got %s" \
        % (_target_type_regex.pattern, target_type)
    assert target_type_long == None \
        or isinstance(target_type_long, str) \
        and _target_type_long_regex.match(target_type_long), \
        "target_type_long must match %s; got %s" \
        % (_target_type_long_regex.pattern, target_type_long)
    assert index == None or index >= 2 and index < 255, \
        "target index has to be between 2 and 255; got %d" % index
    assert network == None or isinstance(network, str), \
        "network has to be a string; got %s" % network
        # nw_indexes() does the real checks
    # FIXME: tag verification? done by target_add, but we need a
    # check in commonl that can work for both client and server
    assert extra_tags == None or isinstance(extra_tags, dict), \
        "extra_tags has to be a dictionary of tags; got %s" % network

    if not power_on_pre_hook:
        power_on_pre_hook = ttbl.dhcp.power_on_pre_pos_setup
    else:
        assert callable(power_on_pre_hook)

    # from the name given, following convention TYPE-NNNETWORK, guess
    # the target type, target index and network name.
    _target_type, _index, _network = pos_target_name_split(name)
    # do we override them from the arguments?
    if target_type == None:
        target_type = _target_type
    if index == None:
        index = _index
        assert index >= 2 and index < 255, \
            "target index has to be between 2 and 255; got %d" % index
    if network == None:
        network = _network
    # FIXME: allow this to come from arguments?
    nw_name = "nw" + network
    x, y, _ = nw_indexes(network)

    target = ttbl.test_target(name)		# create the target object
    if tags == None:
        tags = {				# bake in base tags
            'linux': True,
            'bsp_models': { 'x86_64': None },
            'bsps': {
                'x86_64': {
                    'linux': True,
                    'console': 'x86_64',
                }
            },
        }
    else:
        assert isinstance(tags, dict)
    if target_type_long:
        tags['type_long'] = target_type_long
    else:
        tags['type_long'] = target_type
    if extra_tags:			# add/modify tags?
        tags.update(extra_tags)

    # Consoles
    #
    # serial_pc defaults to open /dev/tty-TARGETNAME; we need to
    # create the object because we'll need to start it upon power on
    pcl = [ ]
    consoles = dict(
        ssh0 = ttbl.console.ssh_pc("root@" + '192.%d.%d.%d' % (x, y, index)),
        default = "ssh0"
    )
    if serial_console_name:
        serial_console = ttbl.console.serial_pc()
        consoles[serial_console_name] = serial_console
        consoles['default'] = serial_console_name
        pcl.append(( serial_console_name, serial_console ))
    target.interface_add("console", ttbl.console.interface(**consoles))


    # Power Rail
    #
    if isinstance(power_rail, str):
        # legacy support for URLs for dlwps7
        # remove user/pasword
        _name = re.sub(r"^([^\s]+:)?([^\s]+@)?", "", power_rail)
        if "@" in power_rail:	# use given user password
            pcl.append(( "AC", ttbl.pc.dlwps7("http://%s" % power_rail) ))
        else:				# use default password
            pcl.append(
                ( "AC", ttbl.pc.dlwps7("http://admin:1234@%s" % power_rail) ))
    elif isinstance(power_rail, ttbl.power.impl_c):
        # already asserted above
        pcl.append(power_rail)
    elif isinstance(power_rail, list):
        # FIXME: do this in tuple
        # already asserted above
        pcl = power_rail
    else:
        raise AssertionError()	# we checked we'd never get here anyway
    target.interface_add("power", ttbl.power.interface(*pcl))

    # POS support
    #
    target_pos_setup(
        target, nw_name, boot_disk, linux_serial_console,
        pos_nfs_server = pos_nfs_server, pos_nfs_path = pos_nfs_path,
        pos_rsync_server = pos_rsync_server,
        boot_config = boot_config, boot_config_fix = boot_config_fix,
        boot_to_normal = boot_to_normal, boot_to_pos = boot_to_pos,
        mount_fs = mount_fs,
        pos_http_url_prefix = pos_http_url_prefix,
        pos_image = pos_image,
        pos_partsizes = pos_partsizes)
    # hook up PXE/POS control before powering on
    target.power_on_pre_fns.append(power_on_pre_hook)

    # Add the target to the system
    ttbl.config.target_add(target, tags = tags, target_type = target_type)
    target.add_to_interconnect(    	# Add target to the interconnect
        nw_name, dict(
            mac_addr = mac_addr,
            ipv4_addr = '192.%d.%d.%d' % (x, y, index),
            ipv4_prefix_len = ipv4_prefix_len,
            ipv6_addr = 'fd:%02x:%02x::%02x' % (x, y, index),
            ipv6_prefix_len = ipv6_prefix_len)
        )
    return target

#: Map QEMU's hard drive interfaces to how Provisioning OS sees them
#: as their boot device
#:
#: Can be extended in configuration with:
#:
#: >>> qemu_iftype_to_pos_boot_dev['NEWIFTYPE'] = 'xka1'
qemu_iftype_to_pos_boot_dev = {
    'virtio': 'vda',
    'scsi': 'sda',
    'ide': 'sda',
}

def target_qemu_pos_add(target_name,
                        nw_name,
                        mac_addr,
                        ipv4_addr,
                        ipv6_addr,
                        consoles = None,
                        disk_size = "30G",
                        mr_partsizes = "1:2:2:10",
                        # more distros support ide than virtio/scsi with
                        # generic kernels
                        sd_iftype = 'ide',
                        extra_cmdline = "",
                        ram_megs = 3072):
    """Add a QEMU virtual machine capable of booting over Provisioning OS.

    This target supports one or more serial consoles, a graphics
    interface exported via VNC and a single hard drive using
    :class:`ttbl.qemu.pc` as backend.

    Note this target uses a UEFI bios *and* defines UEFI storage
    space; this is needed so the right boot order is maintained.

    Add to a server configuration file ``/etc/ttbd-*/conf_*.py``

    >>> nw_pos_add("nwa")
    >>> target = target_qemu_pos_add("qu-05a"
    >>>                              "nwa",
    >>>                              mac_addr = "02:61:00:00:00:05",
    >>>                              ipv4_addr = "192.168.95.5",
    >>>                              ipv6_addr = "fd:00:61::05")

    See an example usage in :func:`conf_06_default.nw_default_targets_add`
    to create default targets.

    Extra paramenters can be added by using the *extra_cmdline*
    arguments, such as for example, to add another drive:

    >>> extra_cmdline = "-drive file=%%(path)s/hd-extra.qcow2,if=virtio,aio=threads"

    Adding to other networks:

    >>> target.add_to_interconnect(
    >>>     'nwb', dict(
    >>>         mac_addr = "02:62:00:00:00:05",
    >>>         ipv4_addr = "192.168.98.5",
    >>>         ipv6_addr = "fd:00:62::05")


    :param str target_name: name of the target to create

    :param str nw_name: name of the network to which this target will
      be connected that provides Provisioning OS services.

    :param str mac_addr: MAC address for this target (for QEMU usually
      a fake one).

      Will be given to the virtual device created and can't be the
      same as any other MAC address in the system or the networks. It
      is recommended to be in the format:

      >>> 02:HX:00:00:00:HY

      where *HX* and *HY* are two hex digits; *02:...* is a valid ethernet
      space. To simplify, it is recommended *HX* is the same for all
      the machines connected to the same network and *HY* matches some
      index in the target's name (eg *04* if target is called *q04*).

    :param str ipv4_addr: IPv4 Address (32bits, *DDD.DDD.DDD.DDD*, where
      *DDD* are decimal integers 0-255) that will be assigned to this
      target in the network.

    :param str ipv6_addr: IPv6 Address (128bits, standard ipv6 colon
      format) that will be assigned to this target in the network.

    :param list(str) consoles: (optional) names of serial consoles to
      create (defaults to just one, *ttyS0*). E.g:

      >>> consoles = [ "ttyS0", "ttyS1", "com3" ]

      these names are used to create the internal QEMU name and how
      the TCF daemon will refer to them as console names. In the
      machine, they will be standard serial ports in that order.

    :param str disk_size: (optional) size specification for the
      target's hard drive, as understood by QEMU's qemu-img create
      program. Defaults to:

      >>> disk_size = "30G"

    :param str mr_partsizes: (optional) sizes of the different
      partitions when using the :ref:`multiroot <pos_multiroot>`
      system to manage the target's disk; see
      :ref:`pos_multiroot_partsizes`.

      e.g.: *"1:10:30:20"* (default)

    :param str sd_iftype: (optional) interface to use for the disks
      (defaults to *ide* as is the one most Linux distro support off
      the bat). Available types are (per QEMU -drive option: ide,
      scsi, sd, mtd, floppy, pflash, virtio)

    :param int ram_megs: (optional) size of memory in megabytes
      (defaults to 2048)

    :param str extra_cmdline: a string with extra command line to add;
      %(FIELD)s supported (target tags).

    **Notes**

    - The hardrive gets fully reinitialized every time the server is
      restarted (the backend file gets wiped and re-created).

      It is still possible to force a re-partitioning of the backend
      by setting POS property :ref:`pos_reinitialize <pos_reinitialize>`.

    """
    assert isinstance(target_name, str)
    if consoles == None or consoles == []:
        consoles = [ 'ttyS0' ]
    else:
        assert isinstance(consoles, list) \
            and all([ isinstance(console, str)
                      for console in consoles ])
        assert len(consoles) >= 1
    assert ram_megs > 0
    # rest of parameters are checked by other functions we call

    target = ttbl.test_target(target_name)	# create the target object

    # Figure out the HD type
    pos_boot_dev = qemu_iftype_to_pos_boot_dev.get(sd_iftype, None)
    if pos_boot_dev == None:
        raise AssertionError("Don't know dev name for disk iftype %s"
                             % sd_iftype)

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
    # this is a very ugly hack to be able to override the BIOS image
    # used by QEMU
    target.fsdb.set('qemu-image-bios', '/usr/share/edk2/ovmf/OVMF_CODE.fd')

    # QEMU object
    #
    # Note this object exposes many interface implementations, we'll
    # hook them up later.
    cmdline = [
        "/usr/bin/qemu-system-x86_64",
        "-enable-kvm",
        "-cpu", "host", "-smp", "cpus=2",
        "-m", str(ram_megs),
        # FIXME: do VNC tunneling so clients can access
        #
        # VNC ports for accessing remotely and the capture interface
        # (ttbd/conf_00_lib_capture.capture_screenshot_vnc)
        # - share=force-shared: cannot be enabled, otherwise gvnccapture
        #   gets resource unavailable 3
        # - we cannot use unix:PATH fro VNC path, otherwise
        #   gvnccapture can't find it. We can't socat it into a port
        #   because QEMU removes the UNIX socket once closed.
        "-display", "vnc=localhost:%(vnc.vnc0.port)s",
        # EFI BIOS
        "-drive", "if=pflash,format=raw,readonly,file=%(qemu-image-bios)s",
        "-drive", "if=pflash,format=raw,file=%(path)s/OVMF_VARS.fd",
        # Storage
        "-drive", "file=%%(path)s/hd.qcow2,if=%s,aio=threads" % sd_iftype,
        "-boot", "order=nc",	# for POS over PXE
    ]
    # Create as many consoles as directed
    consolel = []
    for console in consoles:
        # record using socat as a separate process --
        # ttbl.qemu.pc() detects we are powering on PTY consoles
        # and upon power on, will symlink
        # STATE_DIR/console-CONSOLE.write to /dev/pts/WHATEVER so
        # ttbl.console_general_pc() can write to it and read from it.
        cmdline += [
            "-chardev", f"pty,id={console}",
            "-serial", f"chardev:{console}"
        ]
        console_pc = ttbl.console.general_pc(chunk_size = 8,
                                             interchunk_wait = 0.15)
        console_pc.crlf = "\r"
        consolel.append(( console, console_pc ))

    cmdline += extra_cmdline.split()
    qemu_pc = ttbl.qemu.pc(qemu_cmdline = cmdline)

    # The QEMU object exposes a power control interface to start/stop
    power_rail = []
    if nw_name:			# got networking?
        power_rail.append(( "tuntap-" + nw_name, ttbl.qemu.network_tap_pc() ))
    power_rail.append(( "AC", qemu_pc ))
    for console in consoles:
        # turn on recording from the console when we turn on the
        # machine FIXME: we might loose a wee bit, we shall be able to
        # do it before, but the problem is before the PTY
        # device/socket for the console does not exist
        power_rail.append(( console, console_pc ))
    target.interface_add("power", ttbl.power.interface(*power_rail))

    # The QEMU object exposes an image setting interface
    target.interface_add("images", ttbl.images.interface(
        ( "kernel", qemu_pc ),
        ( "bios", qemu_pc ),
        ( "initrd", qemu_pc ),
    ))

    # Serial console interface: add all the consoles declared in the
    # command line; the generic object console_pc can read from any of
    # them as it takes as parameter the console name to read off/write
    # the QEMU generated cmdline in
    # STATE_DIR/console-NAME.{read,write}
    ssh_pc = ttbl.console.ssh_pc("root@" + ipv4_addr)
    upid = dict(qemu_pc.upid)
    del upid['name_long']
    ssh_pc.upid_set(qemu_pc.name, **upid)
    consolel = []
    for console in consoles:
        consolel.append(
            ( console, console_pc )
        )
    consolel += [
        ( "ssh0", ssh_pc ),
        ( "default",  consolel[0][0] ),
        ( "preferred",  "ssh0" ),
    ]
    target.interface_add("console", ttbl.console.interface(*consolel))
    # store interface needed for adding the capture interface
    target.interface_add("store", ttbl.config._iface_store)
    target.interface_add("capture", ttbl.capture.interface(
        vnc0_screenshot = capture_screenshot_vnc,
        screen = "vnc0_screenshot",
    ))

    target.interface_add("debug", ttbl.debug.interface(
        ( "x86_64", qemu_pc )
    ))

    ttbl.config.target_add(		# add the trget
        target,
        target_type = "qemu-uefi-x86_64",
        tags = dict(
            bsp_models = { 'x86_64': None },
            bsps = dict(
                x86_64 = dict(linux = True),
            ),
        )
    )

    target.add_to_interconnect(		# Network support
        nw_name,
        dict(
            ipv4_addr = ipv4_addr, ipv4_prefix_len = 24,
            ipv6_addr = ipv6_addr, ipv6_prefix_len = 104,
            mac_addr = mac_addr,
        )
    )

    target_pos_setup(target, nw_name,	# POS setup
                     pos_boot_dev, consoles[0],
                     boot_config = 'uefi',
                     boot_config_fix = None,
                     boot_to_normal = 'normal',
                     boot_to_pos = 'pxe',
                     mount_fs = 'multiroot',
                     pos_partsizes = mr_partsizes)
    # make TFTP force PXE boot when pos_mode == pxe
    target.power_on_pre_fns.append(ttbl.dhcp.power_on_pre_pos_setup)
    return target
