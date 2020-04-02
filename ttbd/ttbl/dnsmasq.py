#! /usr/bin/python
"""
Power control module to start a dnsmasq daemon
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A DNSMASQ daemon is created that can be attached to a network
interface to resolve DNS requests for all the targets attached to a
test network.

"""
import os
import shutil

import commonl
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
            "--no-hosts",				# only files in...
            "--hostsdir=%(path)s/dnsmasq.hosts",	# ..this dir
            #"--expand-hosts",	# FIXME: domain name?
            "-2",	# No DHCP/TFTP (FIXME: will move to use it)
            # serve only on the in the interface for this network
            "--listen-address=%(ipv4_addr)s",
            "--interface=b%(id)s",	# FIXME: hardcoded
            # need to use --bind-interfaces so we only bind to our
            # interface and we can run multiple dnsmasqa and coexists
            # with whichever are in the system
            "--bind-interfaces",
            "--except-interface=lo",
            # if a plain name (w/o domain name) is not found in the
            # local database, do not forward it upstream
            "--domain-needed",
            # Needs an A record "%(ipv4_addr)s %(id)s", created in on()
            "--auth-server=%(id)s,"
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

        # Create an A record for the network, needed for --auth-server
        with open(os.path.join(dirname, ic.id), "w+") as f:
            f.write("%s\t%s\n" % (ic.tags['ipv4_addr'], ic.id))

        # Find the targets that connect to this interconnect
        # FIXME: parallelize for many
        for target in ttbl.config.targets.values():
            interconnects = target.tags.get('interconnects', {})
            # iterate interconnects this thing connects to
            for interconnect_id, interconnect in interconnects.iteritems():
                if interconnect_id != ic.id:
                    continue
                addrs = []
                if 'ipv4_addr' in interconnect:
                    addrs.append(interconnect['ipv4_addr'])
                if 'ipv6_addr' in interconnect:
                    addrs.append(interconnect['ipv6_addr'])
                if addrs:
                    # Create a record for each target that will connect to
                    # this interconnect
                    with open(os.path.join(dirname, target.id), "w+") as f:
                        for addr in addrs:
                            f.write("%s\t%s.%s %s\n" % (addr,
                                                        target.id,
                                                        ic.id, target.id))

        # note the rename we did target -> ic
        ttbl.power.daemon_c.on(self, ic, _component)
