#! /usr/bin/python
"""
Power control module to start a dnsmasq daemon
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A DNSMASQ daemon is created that can be attached to a network
interface to:

- resolve DNS requests for all the targets attached to a test network 
- serves DHCP requests to hosts in the interconnect's network
- serves TFTP files from TARGETDIR/tftp.root

Note this will conflict with other DHCP or TFTP servers running in the
same hosts, but it will *only* serve in the interface it is associated
to the interconnect target it is made a power rail of.

Pending:
- IPv6 support not very tested.
- allow to switch which functionalities are needed
  - tftp on/off
  - default route on/off
- allowing adding more names/IP-addresses to the database at will
"""
import collections
import ipaddress
import os
import shutil

import commonl
import ttbl.pxe
import ttbl.power

class pc(ttbl.power.daemon_c):
    """Start / stop a dnsmasq daemon to resolve DNS requests to a given
    network interface

    This is meant to be used in the power rail of an interconnect
    target that represents a network to which the server is physically
    connected.

    Upon power on, it collects the list of targets connecte to the
    interconnect and creates IPv4 and IPv6 address records for them
    (short form *TARGETNAME*, longform *TARGETNAME.INTERCONNECTNAME*);
    the dnsmasq daemon will then resolve those names from queries from
    the targets.

    For example: the server configures the interconnect *nwa*, to
      which it has physical access on a given interface on IP address
      192.168.97.1 (as configured in the interconnect's tags)::

        $ tcf list -vv nwa
        server/nwa
          id: nwa
          ipv4_addr: 192.168.97.1
          ...

      Target *qu-90a* is connected to network *nwa*, and thus it
      declares in its tags *interconnects.nwa*::

        $ tcf list -vv qu-90a
        server/qu-90a
          id: qu-90a
          interconnects.nwa.ipv4_addr: 192.168.97.90

      DNSMASQ (on 192.168.97.1#53) will resolve *qu-90a.nwa* when
      queried from inside the network *nwa* to 192.168.97.90.

    Use in the cpower rail to an interconnect, it won't work with a
    target that does not define tags *ipv4_addr*.

    .. code-block::
       interconnect.interface_add(
           "power",
           ttbl.power.interface(
               ...
               ( "dnsmasq", ttbl.dnsmasq.pc() ),
           ))

    FIXME/PENDING:
     - ipv6 address binding.
     - interface name for --interface is hardcoded; need to obtain
       automatically from the IP address
    """
    def __init__(self, path = "/usr/sbin/dnsmasq"):
        cmdline = [
            path,
            "--keep-in-foreground",
            "--pid-file=%(path)s/dnsmasq.pid",
            "--conf-file=%(path)s/dnsmasq.conf",
        ]
        ttbl.power.daemon_c.__init__(self, cmdline, precheck_wait =
                                     0.5, mkpidfile = False,
                                     pidfile = "%(path)s/dnsmasq.pid")
        self.upid_set(
            "dnsmasq daemon",
            # if multiple virtual machines are created associated to a
            #   target, this shall generate a different ID for
            #   each...in most cases
            serial_number = commonl.mkid(" ".join(cmdline))
        )

    def verify(self, target, component, _cmdline_expanded):
        return os.path.exists(os.path.join(target.state_dir, "dnsmasq.pid"))

    def on(self, target, _component):
        ic = target	# Note the rename (target -> ic)

        # Create records for each target that we know will connect to
        # this interconnect, place them in the directory TARGET/dnsmasq.hosts
        dirname = os.path.join(ic.state_dir, "dnsmasq.hosts")
        shutil.rmtree(dirname, ignore_errors = True)
        commonl.makedirs_p(dirname)
        tftp_dirname = os.path.join(ic.state_dir, "tftp.root")
        shutil.rmtree(tftp_dirname, ignore_errors = True)
        commonl.makedirs_p(tftp_dirname, 0o0775)
        ttbl.pxe.setup_tftp_root(tftp_dirname)	# creates the dir

        # Find the targets that connect to this interconnect and
        # collect their IPv4/6/MAC addresses to create the record and
        # DHCP info; in theory we wouldn't need to create the host
        # info, as the DHCP host info would do it--doesn't hurt
        # FIXME: parallelize for many
        dhcp_hosts = collections.defaultdict(dict)
        for target in ttbl.config.targets.values():
            interconnects = target.tags.get('interconnects', {})
            # iterate interconnects this thing connects to
            for interconnect_id, interconnect in interconnects.items():
                if interconnect_id != ic.id:
                    continue
                addrs = []
                mac_addr = interconnect.get('mac_addr', None)
                if mac_addr:
                    dhcp_hosts[target]['mac_addr'] = mac_addr
                ipv4_addr = interconnect.get('ipv4_addr', None)
                if ipv4_addr:
                    dhcp_hosts[target]['ipv4_addr'] = ipv4_addr
                    addrs.append(ipv4_addr)
                ipv6_addr = interconnect.get('ipv6_addr', None)
                if ipv6_addr:
                    dhcp_hosts[target]['ipv6_addr'] = ipv6_addr
                    addrs.append(ipv6_addr)
                if addrs:
                    # Create a file for each target that will connect to
                    # this interconnect
                    with open(os.path.join(dirname, target.id), "w+") as f:
                        for addr in addrs:
                            f.write("%s\t%s %s.%s\n" % (addr,
                                                        target.id,
                                                        target.id, ic.id))
        # Create a configuration file
        #
        # configl has all the options with template values which we
        # expand later.
        with open(os.path.join(ic.state_dir, "dnsmasq.conf"), "w+") as f:

            configl = [
                "no-hosts",				# only files in...
                "hostsdir=%(path)s/dnsmasq.hosts",	# ..this dir
                # we are defining a domain .NETWORKNAME
                "domain=%(id)s",
                "local=/%(id)s/",
                # serve only on the in the interface for this network;
                # listen-address not needed since we specify
                # interface--having a hard time making listen-address
                # only work anyway
                # FIXME: hardcoded to knowing the network interface
                #        name is called bTARGET
                "interface=b%(id)s",
                # need to use this so we only bind to our
                # interface and we can run multiple dnsmasqa and coexists
                # with whichever are in the system
                "bind-interfaces",
                "except-interface=lo",
                # if a plain name (w/o domain name) is not found in the
                # local database, do not forward it upstream
                "domain-needed",
                # Needs an A record "%(ipv4_addr)s %(id)s", created in on()
                # DISABLED: unknown why, this messes up resolution of
                # plain names
                # auth-server=%(id)s,b%(id)s",
                "auth-zone=%(id)s,b%(id)s",
                "dhcp-authoritative",
                # Enable TFTP server to STATEDIR/tftp.root
                "enable-tftp",
                "tftp-root=%(path)s/tftp.root",
                # all files TFTP is to send have to be owned by the
                # user running it (the same one running this daemon)
                "tftp-secure",
            ]

            # Add stuff based on having ipv4/6 support
            #
            # dhcp-range activates the DHCP server
            # host-record creates a record for the host that
            # represents the domain zone; but not sure it is working
            # all right.
            addrs = []
            ic_ipv4_addr = ic.kws.get('ipv4_addr', None)
            if ic_ipv4_addr:
                addrs.append(ic_ipv4_addr)
                # IPv4 server address so we can do auth-server
                configl.append("host-record=%(id)s,%(ipv4_addr)s")
                # we let DNSMASQ figure out the range from the
                # configuration of the network interface and we only
                # allow (static) the ones set below with dhcp-host
                configl.append("dhcp-range=%(ipv4_addr)s,static")

            ic_ipv6_addr = ic.kws.get('ipv6_addr', None)
            if ic_ipv6_addr:
                addrs.append(ic_ipv6_addr)
                # IPv6 server address so we can do auth-server
                configl.append("host-record=%(id)s,[%(ipv6_addr)s]")
                # FIXME: while this is working, it is still not giving
                # the IPv6 address we hardcoded in the doc :/
                ipv6_prefix_len = ic.kws['ipv6_prefix_len']
                network = ipaddress.IPv6Network(unicode(
                    ic_ipv6_addr + "/" + str(ipv6_prefix_len)), strict = False)
                configl.append("dhcp-range=%s,%s,%s" % (
                    ic_ipv6_addr, network.broadcast_address, ipv6_prefix_len))

            # Create A record for the server/ domain
            # this is a separat file in DIRNAME/dnsmasq.hosts/NAME
            if addrs:
                configl.append("listen-address=" + ",".join(addrs))
                with open(os.path.join(dirname, ic.id), "w+") as hf:
                    for addr in addrs:
                        hf.write("%s\t%s\n" % (addr, ic.id))


            for config in configl:
                f.write(config % ic.kws + "\n")

            # For each target we know can connect, create a dhcp-host entry
            for target, data in dhcp_hosts.items():
                infol = [
                    # we set a tag after the host name to match a
                    # host-specific dhcp-option line to it
                    "set:" + target.id,
                    data['mac_addr']
                ]
                if 'ipv4_addr' in data:
                    infol.append(data['ipv4_addr'])
                if 'ipv6_addr' in data:
                    # IPv6 addr in [ADDR] format, per man page
                    infol.append("[" + data['ipv6_addr'] + "]")
                infol.append(target.id)
                infol.append("infinite")
                f.write("dhcp-host=" + ",".join(infol) + "\n")
                # next fields can be in the target or fall back to the
                # values from the interconnect
                kws = target.kws
                bsps = target.tags.get('bsps', {}).keys()
                if bsps:
                    # take the first BSP in sort order...yeah, not a
                    # good plan
                    bsp = sorted(bsps)[0]
                    kws['bsp'] = bsp
                ttbl.pxe.tag_get_from_ic_target(kws, 'pos_http_url_prefix', ic, target)
                ttbl.pxe.tag_get_from_ic_target(kws, 'pos_nfs_server', ic, target)
                ttbl.pxe.tag_get_from_ic_target(kws, 'pos_nfs_path', ic, target)

                f.write(
                    "dhcp-option=tag:%(id)s,option:root-path,%(pos_nfs_server)s:%(pos_nfs_path)s,udp,soft,nfsvers=3\n"
                    % kws)

                # If the target declares a BSP (at this point of the
                # game, it should), figure out which architecture is
                # so we can point it to the right file.
                if bsp:
                    # try ARCH or efi-ARCH
                    # override with anything the target declares in config
                    arch = None
                    boot_filename = None
                    if 'pos_tftp_boot_filename' in target.tags:
                        boot_filename = target.tags['pos_tftp_boot_filename']
                    elif bsp in ttbl.pxe.architectures:
                        arch = ttbl.pxe.architectures[bsp]
                        arch_name = bsp
                        boot_filename = arch_name + "/" + arch.get('boot_filename', None)
                    elif "efi-" + bsp in ttbl.pxe.architectures:
                        arch_name = "efi-" + bsp
                        arch = ttbl.pxe.architectures[arch_name]
                        boot_filename = arch_name + "/" + arch.get('boot_filename', None)                        
                    if boot_filename:
                        f.write(
                            "dhcp-option=tag:%(id)s," % kws
                            + "option:bootfile-name," + boot_filename + "\n")
                    if ic_ipv4_addr:
                        f.write(
                            "dhcp-option=tag:%(id)s," % kws
                            + "option:tftp-server," + ic_ipv4_addr + "\n")
                    if ic_ipv6_addr:
                        f.write(
                            "dhcp-option=tag:%(id)s," % kws
                            + "option:tftp-server," + ic_ipv4_addr + "\n")
                    else:
                        raise RuntimeError(
                            "%s: TFTP/PXE boot mode selected, but no boot"
                            " filename can be guessed for arch/BSP %s/%s;"
                            " declare tag pos_tftp_boot_filename?"
                            % (target.id, arch_name, bsp))

        # note the rename we did target -> ic
        ttbl.power.daemon_c.on(self, ic, _component)
