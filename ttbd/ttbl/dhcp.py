#! /usr/bin/python2
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import pwd
import shutil
import stat
import subprocess

import commonl
import ttbl
import ttbl.config

#: Directory where the TFTP tree is located
tftp_dir = "/var/lib/tftpboot"
#: Directory where the syslinux tree is located
syslinux_path = "/usr/share/syslinux"

tftp_prefix = "ttbd" + ttbl.config.instance_suffix

class pci(ttbl.tt_power_control_impl):

    class error_e(Exception):
        pass

    class start_e(error_e):
        pass

    dhcpd_path = "/usr/sbin/dhcpd"

    """

    This class implements a power control unit that can be made part
    of a power rail for a network interconnect.

    When turned on, it would starts DHCP to provide on
    the network.

    With a configuration such as::

      import ttbl.dhcp

      ttbl.config.targets['nwa'].pc_impl.append(
          ttbl.dhcp.pci("fc00::61:1", "fc00::61:0", 112,
                        "fc00::61:2", "fc00::61:fe", ip_mode = 6)
      )

    It would start a DHCP IPv6 server on fc00::61:1, network
    fc0)::61:0/112 serving IPv6 address from :2 to :fe.
    """

    def __init__(self,
                 if_addr,
                 if_net,
                 if_len,
                 ip_addr_range_bottom,
                 ip_addr_range_top,
                 mac_ip_map = None,
                 allow_unmapped = False,
                 debug = False,
                 ip_mode = 4):
        assert ip_mode in (4, 6)
        ttbl.tt_power_control_impl.__init__(self)
        self.allow_unmapped = allow_unmapped
        if mac_ip_map == None:
            self._mac_ip_map = {}
        else:
            self._mac_ip_map = mac_ip_map

        # FIXME: move to power_on_do, to get this info from target's tags
        self._params = dict(
            tftp_prefix = tftp_prefix,
            if_net = if_net,
            if_addr = if_addr,
            if_len = if_len,
            ip_addr_range_bottom = ip_addr_range_bottom,
            ip_addr_range_top = ip_addr_range_top,
        )

        self.ip_mode = ip_mode
        if ip_mode == 4:
            self._params['if_netmask'] = commonl.ipv4_len_to_netmask_ascii(if_len)

        if allow_unmapped:
            self._params["allow_known_clients"] = "allow known clients;"
        else:
            self._params["allow_known_clients"] = "# all clients allowed"


        self.debug = debug
        self.log = None
        self.target = None	# we find this when power_*_do() is called
        self.state_dir = None
        self.pxe_dir = None
        self.dhcpd_pidfile = None

    def _dhcp_conf_write_ipv4(self, f):
        # generate the ipv4 part
        self.log.info("%s: IPv4 net/mask %s/%s",
                      self._params['if_name'], self._params['if_net'],
                      self._params['if_netmask'])
        # We only do PXE over ipv4
        f.write("""\
option space pxelinux;
option pxelinux.magic code 208 = string;
option pxelinux.configfile code 209 = text;
option pxelinux.pathprefix code 210 = text;
option pxelinux.reboottime code 211 = unsigned integer 32;
# To be used in the pxeclients class
option architecture-type code 93 = unsigned integer 16;

""")
        # FIXME: make it so using pxelinux is a configuratio template
        # (likewise on the tftp side, so we can switch to EFI boot or
        # whatever we want)
        f.write("""\
subnet %(if_net)s netmask %(if_netmask)s {
        pool {
                %(allow_known_clients)s
                range %(ip_addr_range_bottom)s  %(ip_addr_range_top)s;
        }
        class "pxeclients" {
                match if substring (option vendor-class-identifier, 0, 9) = "PXEClient";
                # http://www.syslinux.org/wiki/index.php?title=PXELINUX#UEFI
                if option architecture-type = 00:00 {
                        filename "%(tftp_prefix)s/lpxelinux.0";
                } elsif option architecture-type = 00:09 {
                        filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
                } elsif option architecture-type = 00:07 {
                        filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
                } elsif option architecture-type = 00:06 {
                        filename "%(tftp_prefix)s/efi-x86/syslinux.efi";
                } else {
                        filename "%(tftp_prefix)s/lpxelinux.0";
                }
                # Point to the TFTP server, which is the same as this
                next-server %(if_addr)s;
        }
}
""" % self._params)

        # Now, enumerate the targets that are in this local
        # configuration and figure out what's their IP address in
        # this network; create a hardcoded entry for them.
        #
        # FIXME: This leaves a gap, as targets in other servers could
        # be connected to this network. Sigh.
        for target_id, target in ttbl.config.targets.iteritems():
            interconnects = target.tags.get('interconnects', {})
            for ic_id, interconnect in interconnects.iteritems():
                if ic_id != self.target.id:
                    continue
                mac_addr = interconnect.get('mac_addr', None)
                ipv4_addr = interconnect.get('ipv4_addr', None)
                if ipv4_addr and mac_addr:
                    f.write("""\
host %s {
        hardware ethernet %s;
        fixed-address %s;
        option host-name "%s";
        # note how we are forcing NFSv3, as it might default to v2
        # FIXME: parameter?
        # Also UDP, more resilient for our use and soft so we can
        # recover in some cases more easily
        option root-path "%s:%s,udp,soft,nfsvers=3";
}
""" % (target_id, mac_addr, ipv4_addr, target_id,
       self._params['pos_nfs_server'], self._params['pos_nfs_path']))


    def _dhcp_conf_write_ipv6(self, f):
        # generate the ipv6 part -- we only use it to assign
        # addresses; PXE is done only over ipv4
        self.log.info("%(if_name)s: IPv6 net/len %(if_addr)s/%(if_len)s" %
                      self._params)
        f.write("""\
# This one line must be outside any bracketed scope
option architecture-type code 93 = unsigned integer 16;

subnet6 %(if_net)s/%(if_len)s {
        range6 %(ip_addr_range_bottom)s  %(ip_addr_range_top)s;

        class "pxeclients" {
                match if substring (option vendor-class-identifier, 0, 9) = "PXEClient";
                # http://www.syslinux.org/wiki/index.php?title=PXELINUX#UEFI
                if option architecture-type = 00:00 {
                        filename "%(tftp_prefix)s/lpxelinux.0";
                } elsif option architecture-type = 00:09 {
                        filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
                } elsif option architecture-type = 00:07 {
                        filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
                } elsif option architecture-type = 00:06 {
                        filename "%(tftp_prefix)s/efi-x86/syslinux.efi";
                } else {
                        filename "%(tftp_prefix)s/lpxelinux.0";
                }
                # Point to the TFTP server, which is the same as this
#                next-server %(if_addr)s;
        }
}
""" % self._params)

        # Now, enumerate the targets that are in this local
        # configuration and figure out what's their IP address in
        # this network; create a hardcoded entry for them.
        #
        # FIXME: This leaves a gap, as targets in other servers could
        # be connected to this network. Sigh.
        for target_id, target in ttbl.config.targets.iteritems():
            interconnects = target.tags.get('interconnects', {})
            for ic_id, interconnect in interconnects.iteritems():
                if ic_id != self.target.id:
                    continue
                mac_addr = interconnect.get('mac_addr', None)
                ipv6_addr = interconnect.get('ipv6_addr', None)
                if ipv6_addr and mac_addr:
                    f.write("""\
host %s {
        hardware ethernet %s;
        fixed-address6 %s;
        option host-name "%s";
        option root-path "";
        # note how we are forcing NFSv3, as it might default to v2
        # FIXME: parameter?
        # Also UDP, more resilient for our use and soft so we can
        # recover in some cases more easily
        option root-path "%s:%s,udp,soft,nfsvers=3";
}
""" % (target_id, mac_addr, ipv6_addr, target_id,
       self._params['pos_nfs_server'], self._params['pos_nfs_path']))

    def _dhcp_conf_write(self):
        # Write DHCPD configuration
        with open(os.path.join(self.state_dir, "dhcpd.conf"),
                  "wb") as f:
            if self.ip_mode == 4:
                self._dhcp_conf_write_ipv4(f)
            else:
                self._dhcp_conf_write_ipv6(f)

    def _dhcpd_start(self):
        # Fire up the daemons
        dhcpd_leases_name = os.path.join(self.state_dir, "dhcpd.leases")
        # Create the leases file if it doesn't exist
        with open(dhcpd_leases_name, 'a'):
            # touch the access/modify time to now
            os.utime(dhcpd_leases_name, None)
        if self.ip_mode == 4:
            ip_mode = "-4"
        else:
            ip_mode = "-6"
        args = [
            # Requires CAP_NET_BIND_SERVICE CAP_NET_ADMIN
            #"strace", "-f", "-s2048", "-o/tmp/kk.log",
            "dhcpd", "-d", "-q",
            # Run it in foreground, so the process group owns it and
            # kills it when exiting
            "-f",
            ip_mode,
            "-cf", os.path.join(self.state_dir, "dhcpd.conf"),
            "-lf", dhcpd_leases_name,
            "-pf", self.dhcpd_pidfile,
            self._params['if_name'],
        ]
        logfile_name = os.path.join(self.state_dir, "dhcpd.log")
        so = open(logfile_name, "wb")
        try:
            subprocess.Popen(args, shell = False, cwd = self.state_dir,
                             close_fds = True,
                             stdout = so, stderr = subprocess.STDOUT)
        except OSError as e:
            raise self.start_e("DHCPD failed to start: %s", e)
        pid = commonl.process_started(
            self.dhcpd_pidfile, self.dhcpd_path,
            verification_f = os.path.exists,
            verification_f_args = (self.dhcpd_pidfile,),
            tag = "dhcpd", log = self.log)
        # systemd might complain with
        #
        # Supervising process PID which is not our child. We'll most
        # likely not notice when it exits.
        #
        # Can be ignored
        if pid == None:
            raise self.start_e("dhcpd failed to start")
        ttbl.daemon_pid_add(pid)	# FIXME: race condition if it died?


    def _init_for_process(self, target):
        # These are the entry points we always need to initialize, we
        # might be in a different process
        if self.log == None:
            self.log = target.log
            self.state_dir = os.path.join(target.state_dir,
                                          "dhcpd-%d" % self.ip_mode)
            self.pxe_dir = os.path.join(tftp_dir, tftp_prefix)
            self.dhcpd_pidfile = os.path.join(self.state_dir, "dhcpd.pid")

            # These are self._params we might not know at the
            # beginning (when the object was created) as tags with
            # information we need might have been created later
            self._params['pos_nfs_server'] = target.tags['pos_nfs_server']
            self._params['pos_nfs_path'] = target.tags['pos_nfs_path']

    def power_on_do(self, target):
        """
        Start DHCPd servers on the network interface
        described by `target`
        """
        if self.target == None:
            self.target = target
        else:
            assert self.target == target
        # FIXME: detect @target is an ipv4 capable network, fail otherwise
        self._init_for_process(target)
        # Create runtime directory where we place everything
        shutil.rmtree(self.state_dir, ignore_errors = True)
        os.makedirs(self.state_dir)
        # TFTP setup
        shutil.rmtree(os.path.join(self.pxe_dir, "pxelinux.cfg"), ignore_errors = True)
        os.makedirs(os.path.join(self.pxe_dir, "pxelinux.cfg"))
        commonl.makedirs_p(os.path.join(self.pxe_dir, "efi-x86_64"))
        os.chmod(os.path.join(self.pxe_dir, "pxelinux.cfg"), 0o0775)
        shutil.copy(os.path.join(syslinux_path, "lpxelinux.0"), self.pxe_dir)
        shutil.copy(os.path.join(syslinux_path, "ldlinux.c32"), self.pxe_dir)
        # FIXME: Depends on package syslinux-efi64
        subprocess.call([ "rsync", "-a", "--delete",
                          # add that postfix / to make sure we sync
                          # the dir and not create another subdir
                          os.path.join(syslinux_path, "efi64") + "/.",
                          os.path.join(self.pxe_dir, "efi-x86_64") ])
        # We use always the same configurations; because the rsync
        # above will remove the symlink, we re-create it
        # We use a relative symlink so in.tftpd doesn't nix it
        os.symlink("../pxelinux.cfg",
                   os.path.join(self.pxe_dir, "efi-x86_64", "pxelinux.cfg"))

        # We set the parameters in a dictionary so we can use it to
        # format strings
        # FUGLY; relies on ttbl.conf_00_lib.vlan_pci renaming the
        # network interfaces like this.
        self._params['if_name'] = "b" + target.id

        # FIXME: if we get the parameters from the network here, we
        # have target -- so we don't need to set them on init
        self._dhcp_conf_write()

        # FIXME: before start, filter out leases file, anything in the
        # leases dhcpd.leases file that has a "binding state active"
        # shall be kept ONLY if we still have that client in the
        # configuration...or sth like that.
        # FIXME: rm old leases file, overwrite with filtered one

        self._dhcpd_start()

    def power_off_do(self, target):
        if self.target == None:
            self.target = target
        else:
            assert self.target == target
        self._init_for_process(target)
        commonl.process_terminate(self.dhcpd_pidfile,
                                  path = self.dhcpd_path, tag = "dhcpd")

    def power_get_do(self, target):
        if self.target == None:
            self.target = target
        else:
            assert self.target == target
        self._init_for_process(target)
        dhcpd_pid = commonl.process_alive(self.dhcpd_pidfile, self.dhcpd_path)
        if dhcpd_pid != None:
            return True
        else:
            return False


def power_on_pre_pos_setup(target):

    pos_mode = target.fsdb.get("pos_mode")
    if pos_mode == None:
        target.log.info("POS boot: ignoring, pos_mode property not set")
        return
    # We only care if mode is set to pxe or local -- local makes us
    # tell the thing to go boot local disk
    if pos_mode != "pxe" and pos_mode != "local":
        target.log.info("POS boot: ignoring, pos_mode set to %s "
                        "(vs PXE or local)" % pos_mode)
        return

    boot_ic = target.tags.get('pos_boot_interconnect', None)
    if boot_ic == None:
        raise RuntimeError('no "pos_boot_interconnect" tag/property defined, '
                           'can\'t boot off network')
    if not boot_ic in target.tags['interconnects']:
        raise RuntimeError('this target does not belong to the '
                           'boot interconnect "%s" defined in tag '
                           '"pos_boot_interconnect"' % boot_ic)

    interconnect = target.tags['interconnects'][boot_ic]
    # FIXME: at some point, for ic-less POS-PXE boot we could get this
    # from pos_mac_addr and default to ic['mac_addr']
    mac_addr = interconnect['mac_addr']

    if pos_mode == "pxe":
        # now this is dirty -- we kinda hacking here but otherwise, how do
        # we get to the pos_* kws?
        boot_ic_tags = ttbl.config.targets[boot_ic].tags

        # The service
        kws = dict(target.tags)
        kws.update(dict(
            ipv4_addr = interconnect['ipv4_addr'],
            ipv4_gateway = interconnect.get('ipv4_gateway', ""),
            ipv4_netmask = commonl.ipv4_len_to_netmask_ascii(
                interconnect['ipv4_prefix_len']),
            mac_addr = mac_addr,
            name = target.id,
            pos_http_url_prefix = boot_ic_tags['pos_http_url_prefix'],
            pos_nfs_server = boot_ic_tags['pos_nfs_server'],
            pos_nfs_path = boot_ic_tags['pos_nfs_path'],
        ))

        # generate configuration for the target to boot the POS's linux
        # kernel with the root fs over NFS
        # FIXME: the name of the pos image and the command line extras
        # should go over configuration and the target's configuration
        # should be able to say which image it wants (defaulting everyone
        # to whichever).
        kws['extra_kopts'] = ""
        kws['pos_image'] = 'tcf-live'
        kws['root_dev'] = '/dev/nfs'
        # no 'single' so it force starts getty on different ports
        # nfsroot: note we defer to whatever we are given over DHCP
        kws['extra_kopts'] += \
            "initrd=%(pos_http_url_prefix)sinitramfs-%(pos_image)s " \
            "rd.live.image selinux=0 audit=0 ro " \
            "rd.luks=0 rd.lvm=0 rd.md=0 rd.dm=0 rd.multipath=0 " \
            "plymouth.enable=0 "

        # Generate the PXE linux configuration
        #
        # note the syslinux/pxelinux format supports no long line
        # breakage, so we use Python's \ for clearer, shorter lines which
        # will be pasted all together
        #
        # FIXME: move somewhere else more central?
        #
        # IP specification is needed so the kernel acquires an IP address
        # and can syslog/nfsmount, etc Note we know the fields from the
        # target's configuration, as they are pre-assigned
        #
        # ip=DHCP so we get always the same IP address and NFS root
        # info (in option root-path when writing the DHCP config file)
        config = """\
say TCF Network boot to Service OS
#serial 0 115200
default boot
prompt 0
label boot
  # boot to %(pos_image)s
  linux %(pos_http_url_prefix)svmlinuz-%(pos_image)s
  append console=tty0 console=%(linux_serial_console_default)s,115200 \
    ip=dhcp \
    root=%(root_dev)s %(extra_kopts)s
"""
        # if there are substitution fields in the config text,
        # replace them with the keywords; repeat until there are none left
        # (as some of the keywords might bring in new substitution keys).
        #
        # Stop after ten iterations
        count = 0
        while '%(' in config:
            config = config % kws
            count += 1
            if count > 9:
                raise RuntimeError('after ten iterations could not resolve '
                                   'all configuration keywords')
    else:
        # pos_mode is local
        config = """\
say TCF Network boot redirecting to local boot
serial 0 115200
default localboot
prompt 0
label localboot
  localboot 0
"""

    # Write the TFTP configuration  -- when the target boots and does
    # a DHCP request, DHCP daemon will send it a DHCP address and also
    # tell it to boot off TFTP with a pxelinux bootloader; it'll load
    # that bootloader, which will look for different configuration
    # files off TFTP_DIR/TFTP_PREFIX/pxelinux.cfg/ in a given order,
    # one of us being 01-ITSMACADDR
    #
    # It will find this one we are now making and boot to the POS for
    # provisioning or to local boot.

    tftp_config_file_name = os.path.join(
        tftp_dir, tftp_prefix, "pxelinux.cfg",
        # 01- is the ARP type 1 for ethernet; also note the PXE client
        # asks with the hex digits in lower case.
        "01-" + mac_addr.replace(":", "-").lower())
    with open(tftp_config_file_name, "w") as tf:
        tf.write(config)
        tf.flush()
        # We know the file exists, so it is safe to chmod like this
        os.chmod(tf.name, 0o644)
