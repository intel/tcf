#! /usr/bin/python3
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

Note configuration entries for DNSMASQ follow the command line names
(without the leading --) and the source for DNSMASQ is at
http://www.thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html.
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

    :param str ifname: (optional; default target's name) name of the
      network interface to attach dnsmasq to.

    :param bool tftp: (optional; default *True*) enable TFTP

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

    .. code-block:: python

       interconnect.interface_add(
           "power",
           ttbl.power.interface(
               ...
               ( "dnsmasq", ttbl.dnsmasq.pc() ),
           ))

    A console can be configured to see all the log messages reported
    by *dnsmasq* with the following:

    .. code-block:: python

       target.interface_impl_add(
           "console", "log-dnsmasq",
           ttbl.console.logfile_c("dnsmasq.log")
       )

    (this works because :class:`ttbl.console.logfile_c` will read a
    called *dnsmasq.log* in the target's state directory); running::

      $ tcf console-read TARGETNAME -c log-dnsmasq

    reads the log file; while::

      $ tcf console-setup TARGETNAME -c log-dnsmasq

    wipes the log file


    **Inventory fields**

    These will be taken in the following order:

    - *TARGET.interconnects.ICNAME.FIELD*
    - *IC.FIELD*

    The following are recognized:

    - *default_route*: bool, string: (optional; default *True*)

      - *True*: a default route will be sent by the DHCP server with
        .1 being the gateway

      - *False*: no default route will be sent by the DHCP server

      - *value*: a default route will be set and the gateway will be
        *value*, which shall be an IP address in the right range.

    - *default_route6*: same as *default_route*, but for IPv6.

    FIXME/PENDING:
     - ipv6 address binding.
     - interface name for --interface is hardcoded; need to obtain
       automatically from the IP address

    """
    def __init__(self, path = "/usr/sbin/dnsmasq", ifname = None,
                 allow_other_macs: bool = False,
                 tftp: bool = True):
        assert isinstance(allow_other_macs, bool), \
            f"allow_other_macs: expected bool; got {type(allow_other_macs)}"

        if ifname != None:
            assert isinstance(ifname, str) \
                and len(ifname) <= self.IFNAMSIZ, \
                "ifname: expected string of at most" \
                f" {self.IFNAMSIZ} characters; got {type(ifname)}" \
                f" {ifname}"
            commonl.verify_str_safe(ifname,
                                    name = "network interface name")
        self.ifname = ifname
        self.allow_other_macs = allow_other_macs

        cmdline = [
            path,
            "--auth-server",
            "--keep-in-foreground",
            "--pid-file=%(path)s/dnsmasq.pid",
            "--dhcp-leasefile=%(path)s/dnsmasq.leases",
            "--conf-file=%(path)s/dnsmasq.conf",
        ]
        ttbl.power.daemon_c.__init__(self, cmdline, precheck_wait =
                                     0.5, mkpidfile = False,
                                     pidfile = "%(path)s/dnsmasq.pid")
        self.tftp = tftp
        self.upid_set(
            "dnsmasq daemon",
            # if multiple virtual machines are created associated to a
            #   target, this shall generate a different ID for
            #   each...in most cases
            serial_number = commonl.mkid(" ".join(cmdline))
        )


    # linux/include/if.h
    IFNAMSIZ = 16

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
        commonl.rm_f(os.path.join(ic.state_dir, "dnsmasq.log"))

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

            if self.ifname:
                ifname = self.ifname
            else:
                ifname = "b" + ic.id
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
                f"interface={ifname}",
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
                f"auth-zone=%(id)s,{ifname}",
                "dhcp-authoritative",
                # logging -- can be accessed with a console, see class doc
                "log-dhcp",
                "log-facility=%(path)s/dnsmasq.log",
            ]

            if self.tftp:
                configl += [
                    # Enable TFTP server to STATEDIR/tftp.root
                    "enable-tftp",
                    "tftp-root=%(path)s/tftp.root",
                    # all files TFTP is to send have to be owned by the
                    # user running it (the same one running this daemon)
                    "tftp-secure"
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
                ipv4_prefix_len = ic.kws['ipv4_prefix_len']
                network = ipaddress.IPv4Network(str(
                    ic_ipv4_addr + "/" + str(ipv4_prefix_len)), strict = False)
                # we let DNSMASQ figure out the range from the
                # configuration of the network interface and we only
                # allow (static) the ones set below with dhcp-host
                if self.allow_other_macs:
                    configl.append(
                        f"dhcp-range={ipv4_addr},{network.broadcast_address},"
                        f"{ipv4_prefix_len}")
                else:
                    configl.append("dhcp-range=%(ipv4_addr)s,static")

            ic_ipv6_addr = ic.kws.get('ipv6_addr', None)
            if ic_ipv6_addr:
                addrs.append(ic_ipv6_addr)
                # IPv6 server address so we can do auth-server
                configl.append("host-record=%(id)s,[%(ipv6_addr)s]")
                # FIXME: while this is working, it is still not giving
                # the IPv6 address we hardcoded in the doc :/
                ipv6_prefix_len = ic.kws['ipv6_prefix_len']
                network = ipaddress.IPv6Network(str(
                    ic_ipv6_addr + "/" + str(ipv6_prefix_len)), strict = False)
                configl.append("dhcp-range=%s,%s,%s" % (
                    ic_ipv6_addr, network.broadcast_address, ipv6_prefix_len))

            # Create A record for the server/ domain
            # this is a separat file in DIRNAME/dnsmasq.hosts/NAME
            if addrs:
                configl.append("listen-address=" + ",".join(addrs))
                with open(os.path.join(dirname, ic.id), "w+") as hf:
                    hf.write(f"""\
# This file is generated by ttbl.dnsmasq.pc.on()
# each time target {ic.id} is powered on
#
# source at {__file__}
#
# The source for the information:
#
#  - IP addresses: inventory fields: ipv4_addr and ipv6_addr
#  - alias hostnames: inventory field ip_hostnames
""")
                    # ip_hostnames is a space separated list of
                    # hostnames this can be identified with in the
                    # internal network--you can use this to shadow names
                    hostnamep = ic.property_get("ip_hostnames", "")
                    hostnamel = [ ic.id ] \
                        + ic.property_get("ip_hostnames", "").split()
                    hostnames = " ".join(hostnamel)
                    for addr in addrs:
                        hf.write("%s\t%s\n" % (addr, hostnames))


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

                # FIXME: this is very confusing here, since it is what
                # ttbl.pxe.pos_cmdline_opts is relaying on in a way
                # and we'd need a way to make it machine specific too;
                # as well, in some places like for pos_mode==pxe this
                # is all set in the server sides, while the client in
                # tcfl.pos has a lot of it in the client side; we need
                # a unified source.

                f.write(
                    "dhcp-option=tag:%(id)s,option:root-path,%(pos_nfs_server)s:%(pos_nfs_path)s,soft,nfsvers=4\n"
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

                    # Control default routes
                    default_route = ttbl.pxe.tag_get_from_ic_target(
                        kws, 'default_route', ic, target, True)
                    if default_route == False:
                        # this means NO default route
                        f.write("dhcp-option=tag:%(id)s," % kws
                                + "option:router\n")
                    elif default_route == True:
                        pass		# default router behaviour
                    else:
                        f.write("dhcp-option=tag:%(id)s," % kws
                                + f"option:router,{default_route}\n")

                    default_route6 = ttbl.pxe.tag_get_from_ic_target(
                        kws, 'default_route6', ic, target, True)
                    if default_route6 == False:
                        # this means NO default route
                        f.write("dhcp-option=tag:%(id)s," % kws
                                + "option6:router\n")
                    elif default_route6 == True:
                        pass		# default router behaviour
                    else:
                        f.write("dhcp-option=tag:%(id)s," % kws
                                + f"option:router6,{default_route6}\n")

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
                            + "option:tftp-server," + ic_ipv6_addr + "\n")
                    else:
                        raise RuntimeError(
                            "%s: TFTP/PXE boot mode selected, but no boot"
                            " filename can be guessed for arch/BSP %s/%s;"
                            " declare tag pos_tftp_boot_filename?"
                            % (target.id, arch_name, bsp))

        # note the rename we did target -> ic
        ttbl.power.daemon_c.on(self, ic, _component)
