#! /usr/bin/python3
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Power control module to start DHCP daemon when a network is powered on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import os
import pwd
import shutil
import stat
import subprocess

import commonl
import ttbl
import ttbl.config
import ttbl.power
import ttbl.pxe

#: Directory where the TFTP tree is located
tftp_dir = "/var/lib/tftpboot"
tftp_prefix = "ttbd" + ttbl.config.instance_suffix

def template_rexpand(text, kws):
    """
    Expand Python keywords in a template repeatedly until none are
    left.

    if there are substitution fields in the config text,
    replace them with the keywords; repeat until there are none left
    (as some of the keywords might bring in new substitution keys).

    Stop after ten iterations
    """
    assert isinstance(text, str)
    assert isinstance(kws, dict)
    count = 0
    while '%(' in text:
        text = text % kws
        count += 1
        if count > 9:
            raise RuntimeError('after ten iterations could not resolve '
                               'all configuration keywords')
    return text


def _tag_get_from_ic_target(kws, tag, ic, target, default = ""):
    # get first from the target
    if tag in target.tags:
        value = target.tags[tag]
    elif tag in ic.tags:
        value = ic.tags[tag]
    else:
        value = default
    kws[tag] = value % kws


# FIXME: use daemon_pc
class pci(ttbl.power.impl_c):

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

      ttbl.test_target.get('nwa').pc_impl.append(
          ttbl.dhcp.pci("fd:00:61::1", "fd:00:61::0", 24,
                        "fd:00:61::2", "fd:00:61::fe", ip_mode = 6)
      )

    It would start a DHCP IPv6 server on fd:00:61::1, network
    fc:00:61::0/24 serving IPv6 address from :2 to :fe.
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
        ttbl.power.impl_c.__init__(self)
        self.allow_unmapped = allow_unmapped
        if mac_ip_map == None:
            self._mac_ip_map = {}
        else:
            self._mac_ip_map = mac_ip_map

        # FIXME: move to power_on_do, to get this info from target's tags
        self._params = dict(
            ip_mode = ip_mode,
            tftp_prefix = tftp_prefix,
            if_net = if_net,
            if_addr = if_addr,
            if_len = if_len,
            ip_addr_range_bottom = ip_addr_range_bottom,
            ip_addr_range_top = ip_addr_range_top,
            dhcp_architecture_types = self._mk_pxe_arch_type_config(),
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

    @staticmethod
    def _mk_pxe_arch_type_config():
        # Given information in the ttbl.pxe.architecture member of this
        # class, generate a block of DHCP config language that looks
        # like:
        #
        #   if option architecture-type = 00:00 {
        #         filename "%(tftp_prefix)s/lpxelinux.0";
        #   } elsif option architecture-type = 00:09 {
        #         filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
        #   } elsif option architecture-type = 00:07 {
        #         filename "%(tftp_prefix)s/efi-x86_64/syslinux.efi";
        #   } elsif option architecture-type = 00:06 {
        #         filename "%(tftp_prefix)s/efi-x86/syslinux.efi";
        #   } else {
        #         filename "%(tftp_prefix)s/lpxelinux.0";
        #   }
        first = True
        res = ""
        for arch_name, arch_data in ttbl.pxe.architectures.items():
            if first:
                if_s = "if"
                first = False
            else:
                if_s = "} elsif"
            rfc_code = arch_data['rfc_code']
            boot_filename = arch_data['boot_filename']
            res += """\
                %s option architecture-type = %s {
                    filename "%s/%s/%s";
""" %  (if_s, rfc_code, tftp_prefix, arch_name, boot_filename)
        res += """\
                } else {
                      filename "%s/lpxelinux.0";
                }
""" % tftp_prefix
        return res


    def _dhcp_conf_write(self, f):
        kws = dict(self._params)
        # generate DHCP configuration file based on hackish templating
        self.log.info(
            "%(if_name)s: IPv%(ip_mode)d addr/net/mask "
            "%(if_addr)s/%(if_net)s/%(if_len)s", self._params)
        if self.ip_mode == 4:
            # We only do PXE over ipv4
            # FIXME: make it so using pxelinux is a configuratio template
            # (likewise on the tftp side, so we can switch to EFI boot or
            # whatever we want)
            # %(dhcp_architecture_types)s is the output of
            # _mk_pxe_arch_type_config()
            f.write("""\
option space pxelinux;
option pxelinux.magic code 208 = string;
option pxelinux.configfile code 209 = text;
option pxelinux.pathprefix code 210 = text;
option pxelinux.reboottime code 211 = unsigned integer 32;
# To be used in the pxeclients class
option architecture-type code 93 = unsigned integer 16;

subnet %(if_net)s netmask %(if_netmask)s {
        pool {
                %(allow_known_clients)s
                range %(ip_addr_range_bottom)s  %(ip_addr_range_top)s;
        }
        class "pxeclients" {
                match if substring (option vendor-class-identifier, 0, 9) = "PXEClient";
                # http://www.syslinux.org/wiki/index.php?title=PXELINUX#UEFI
%(dhcp_architecture_types)s
                # Point to the TFTP server, which is the same as this
                next-server %(if_addr)s;
        }
}
""" % self._params)
        else:
            f.write("""\
# This one line must be outside any bracketed scope
option architecture-type code 93 = unsigned integer 16;

subnet6 %(if_net)s/%(if_len)s {
        range6 %(ip_addr_range_bottom)s %(ip_addr_range_top)s;

        class "pxeclients" {
                match if substring (option vendor-class-identifier, 0, 9) = "PXEClient";
                # http://www.syslinux.org/wiki/index.php?title=PXELINUX#UEFI
%(dhcp_architecture_types)s
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
        for target in ttbl.test_target.known_targets():
            interconnects = target.tags.get('interconnects', {})
            ic = self.target

            boot_ic = target.tags.get('pos_boot_interconnect', None)
            if boot_ic == None:
                ic.log.info('%s: target has no "pos_boot_interconnect" '
                            'tag/property defined, ignoring' % target.id)
                continue
            # FIXME: these two checks shall be consistency done when
            # the target is being added
            if not boot_ic in target.tags['interconnects']:
                raise RuntimeError('%s: target does not belong to the '
                                   'boot interconnect "%s" defined in tag '
                                   '"pos_boot_interconnect"'
                                   % (target.id, boot_ic))
            boot_ic_target = ttbl.test_target(boot_ic)
            if boot_ic_target == None:
                raise RuntimeError('%s: this target\'s boot interconnect %s '
                                   'defined in "pos_boot_interconnect" tag '
                                   'is not available in this server'
                                   % (target.id, boot_ic))

            if not 'bsp' in target.tags:
                bsps = list(target.tags.get('bsps', {}).keys())
                if bsps:
                    kws['bsp'] = sorted(bsps)[0]
            kws.update(dict(
                ipv4_gateway = ic.tags.get('ipv4_gateway', ""),
                ipv4_netmask = commonl.ipv4_len_to_netmask_ascii(
                    ic.tags['ipv4_prefix_len']),
                name = target.id,
            ))

            # There might be a prefix to the path to the boot kernel and
            # initrd; we let the target override it and default to the
            # network's or nothing
            # FIXME: need v6 nfs_server and http_url
            _tag_get_from_ic_target(kws, 'pos_http_url_prefix', ic, target)
            _tag_get_from_ic_target(kws, 'pos_nfs_server', ic, target)
            _tag_get_from_ic_target(kws, 'pos_nfs_path', ic, target)

            for ic_id, interconnect in list(interconnects.items()):
                if '#' in ic_id:
                    real_ic_id, instance = ic_id.split("#", 1)
                    kws['hostname'] = target.id + "-" + instance
                else:
                    real_ic_id = ic_id
                    kws['hostname'] = target.id
                if real_ic_id != self.target.id:
                    continue
                kws['mac_addr'] = interconnect.get('mac_addr', None)
                kws['ipv4_addr'] = interconnect.get('ipv4_addr', None)
                kws['ipv6_addr'] = interconnect.get('ipv6_addr', None)

                if self.ip_mode == 4:
                    config = """\
host %(hostname)s {
        hardware ethernet %(mac_addr)s;
        fixed-address %(ipv4_addr)s;
        option host-name "%(hostname)s";
        # note how we are forcing NFSv3, as it might default to v2
        # FIXME: parameter?
        # Also UDP, more resilient for our use and soft so we can
        # recover in some cases more easily
        option root-path "%(pos_nfs_server)s:%(pos_nfs_path)s,soft,nfsvers=4";
}
"""
                else:
                    config = """\
host %(hostname)s {
        hardware ethernet %(mac_addr)s;
        fixed-address6 %(ipv6_addr)s;
        option host-name "%(hostname)s";
        # note how we are forcing NFSv3, as it might default to v2
        # FIXME: parameter?
        # Also UDP, more resilient for our use and soft so we can
        # recover in some cases more easily
        # FIXME: pos_nfs_server6?
        option root-path "%(pos_nfs_server)s:%(pos_nfs_path)s,soft,nfsvers=4";
}
"""
                f.write(template_rexpand(config, kws))



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

    def on(self, target, _component):
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
        # Create runtime directories where we place everything based
        # on the infomation in ttbl.pxe.architectures
        shutil.rmtree(self.state_dir, ignore_errors = True)
        os.makedirs(self.state_dir)
        ttbl.pxe.setup_tftp_root(os.path.join(tftp_dir, tftp_prefix))

        # We set the parameters in a dictionary so we can use it to
        # format strings
        # FUGLY; relies on ttbl.conf_00_lib.vlan_pci renaming the
        # network interfaces like this.
        self._params['if_name'] = "b" + target.id

        # FIXME: if we get the parameters from the network here, we
        # have target -- so we don't need to set them on init
        with open(os.path.join(self.state_dir, "dhcpd.conf"), "wb") as f:
            self._dhcp_conf_write(f)

        # FIXME: before start, filter out leases file, anything in the
        # leases dhcpd.leases file that has a "binding state active"
        # shall be kept ONLY if we still have that client in the
        # configuration...or sth like that.
        # FIXME: rm old leases file, overwrite with filtered one

        self._dhcpd_start()

    def off(self, target, _component):
        if self.target == None:
            self.target = target
        else:
            assert self.target == target
        self._init_for_process(target)
        commonl.process_terminate(self.dhcpd_pidfile,
                                  path = self.dhcpd_path, tag = "dhcpd")

    def get(self, target, _component):
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


# power_on_pre_pos_setup has moved!
def power_on_pre_pos_setup(target):
    target.log.warning(
        "UPDATE configuration: power_on_pre_pos_setup has moved to ttbl.pxe")
    ttbl.pxe.power_on_pre_pos_setup(target)
