#! /usr/bin/python2
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Different utilities for PXE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some parts of the system use PXE and this contains the
implementations.
"""

import logging
import os
import subprocess

import commonl
import ttbl
import ttbl.config
import ttbl.power

#: Directory where the TFTP tree is located
tftp_dir = "/var/lib/tftpboot"


# FIXME: move to commonl?
def tag_get_from_ic_target(kws, tag, ic, target, default = ""):
    # get 'tag' from the target; if missing, from the interconnect, if
    # missing, do the default
    if tag in target.tags:
        value = target.tags[tag]
    elif tag in ic.tags:
        value = ic.tags[tag]
    else:
        value = default
    kws[tag] = value % kws

# FIXME: move to commonl
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

#:
#: List of PXE architectures we support
#:
#: This is a dictionary keyed by architecture name (ARCHNAME); the
#: value is a dictionary keyed by the following keywords
#:
#: - ``rfc_code`` (str) a hex string in the format "HH:HH",
#:   documenting a PXE architecture as described in
#:   https://datatracker.ietf.org/doc/rfc4578/?include_text=1 (section 2.1).
#:
#:   This is used directly for the ISC DHCP configuration of the
#:   *option architecture-type*::
#:
#:     Code  Arch Name   Description
#:     ----- ----------- --------------------
#:     00:00 x86         Intel x86PC
#:     00:01             NEC/PC98
#:     00:02             EFI Itanium
#:     00:03             DEC Alpha
#:     00:04             Arc x86
#:     00:05             Intel Lean Client
#:     00:06             EFI IA32
#:     00:07 efi-bc      EFI BC	 (byte code)
#:     00:08             EFI Xscale
#:     00:09 efi-x86_64  EFI x86-64
#:
#: - ``boot_filename`` (str): name of the file sent over PXE to a
#:   target when it asks what to boot. This will be converted to
#:   TFTP path ``/ttbd-INSTANCE/ARCHNAME/BOOT_FILENAME`` which will be
#:   requested by the target.
#:
#: - ``copy_files`` (list of str): list of files or directories that
#:   have to copy/rsynced to ``TFTPDIR/ttbd-INSTANCE/ARCHNAME``;
#:   everything needed for the client to boot ``BOOT_FILENAME`` has to
#:   be listed here for them to be copied and made available over TFTP.
#:
#:   This allows to patch this in runtime based on the site
#:   configuration and Linux distribution
#:
#: The DHCP driver, when powered on, will create
#: ``TFTPDIR/ttbd-INSTANCE/ARCHNAME``, rsync the files or trees in
#: ``copy_files`` to it and then symlink
#: ``TFTPDIR/ttbd-INSTANCE/ARCHNAME/pxelinux.cfg`` to
#: ``TFTPDIR/ttbd-INSTANCE/pxelinux.cfg`` (as the configurations are
#: common to all the architectures).
#:
#:
#: To extend in the system configuration, add to any server
#: configuration file in ``/etc/ttbd-INSTANCE/conf_*.py``; for
#: example, to use another bootloader for eg, ``x86``:
#:
#: >>> import ttbl.dhcp
#: >>> ...
#: >>> ttbl.pxe.architectures['x86']['copy_files'].append(
#: >>>     '/usr/local/share/syslinux/lpxelinux1.0`)
#: >>> ttbl.pxe.architectures['x86']['boot_file'] = 'lpxelinux1.0`
#:
architectures = {
    'x86': dict(
        rfc_code = "00:00",
        # lpxe can load HTTP
        boot_filename = 'lpxelinux.0',
        copy_files = [
            "/usr/share/syslinux/lpxelinux.0",
            "/usr/share/syslinux/ldlinux.c32",
        ]
    ),
    'efi-bc': dict(
        # apparently sometimes it is misused by some vendors for
        # x86_64, so we make it do the same
        # https://www.syslinux.org/wiki/index.php?title=PXELINUX#UEFI
        rfc_code = "00:07",
        boot_filename = 'syslinux.efi',
        copy_files = [
            "/usr/share/syslinux/efi64/",
            "/home/ttbd/public_html/x86_64/vmlinuz-tcf-live",
            "/home/ttbd/public_html/x86_64/initramfs-tcf-live",
        ]
    ),
    'efi-x86_64': dict(
        rfc_code = "00:09",
        boot_filename = 'syslinux.efi',
        copy_files = [
            "/usr/share/syslinux/efi64/",
            "/home/ttbd/public_html/x86_64/vmlinuz-tcf-live",
            "/home/ttbd/public_html/x86_64/initramfs-tcf-live",
        ]
    ),
}


def setup_tftp_root(tftp_rootdir):
    """
    [DESTRUCTIVELY!!!] Sets up a TFTP root to work

    It will wipe anything in some parts of there with 'rsync --delete'
    """

    def _rsync_files(dest, files):
        try:
            commonl.makedirs_p(dest, 0o0775)
            cmdline = [ "rsync", "-a", "--delete" ] + files + [ dest ]
            subprocess.check_output(cmdline, shell = False, stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            logging.error("PXE setup: root::%s: can't copy files %s "
                          " (do they exist?)\n%s" % (
                              dest, " ".join(files), e.output))
            raise
    # TFTP setup
    commonl.makedirs_p(os.path.join(tftp_rootdir, "pxelinux.cfg"), 0o0775)
    if 'root' in architectures:
        arch_data = architectures['root']
        _rsync_files(tftp_rootdir, arch_data['copy_files'])
    for arch_name, arch_data in architectures.items():
        if arch_name == 'root':		# skip, we handled it ...
            continue			# ... differently
        tftp_arch_dir = os.path.join(tftp_rootdir, arch_name)
        _rsync_files(tftp_arch_dir, arch_data['copy_files'])
        # We use always the same configurations; because the rsync
        # above might remove the symlink, we re-create it
        # We use a relative symlink so in.tftpd doesn't nix it
        commonl.symlink_f("../pxelinux.cfg",
                          os.path.join(tftp_arch_dir, "pxelinux.cfg"))


#: List of strings with Linux kernel command options to be passed by
#: the bootloader
#:
#: These are mapped to the *pos_image* attribute on a target; this is
#: configured by the system administrator as different targets might
#: need different command line arguments.
pos_cmdline_opts = {
    'tcf-live':  [
        # no 'single' so it force starts getty on different ports
        # this needs an initrd
        "initrd=%(pos_http_url_prefix)sinitramfs-%(pos_image)s ",
        # needed by Fedora running as live FS hack
        "rd.live.image",
        # We need SELinux disabled--otherwise some utilities (eg:
        # rsync) can't operate properly on the SELinux attributes they need to
        # move around without SELinux itself getting on the way.
        "selinux=0", "audit=0",
        # ip=dhcp so we get always the same IP address and NFS root
        # info (in option root-path when writing the DHCP config file
        # a few lines above in _dhcp_conf_write()); thus nfsroot
        # defers to whatever we are given over DHCP, which has all the
        # protocol and version settings
        #
        # IP specification is needed so the kernel acquires an IP address
        # and can syslog/nfsmount, etc Note we know the fields from the
        # target's configuration, as they are pre-assigned
        "ip=dhcp",
        # The path to this is obtained if not given here (which we
        # also can) from the DHCP root-path option given by the DHCP
        # server -- look into dnsmasq.py or dhcp.py for root-path.
        "root=/dev/nfs",		# we are NFS rooted
        # no exotic storage options
        "rd.luks=0", "rd.lvm=0", "rd.md=0", "rd.dm=0", "rd.multipath=0",
        "ro",				# we are read only
        "plymouth.enable=0 ",		# No installer to run
	# kernel, be quiet to avoid your messages polluting the serial
        # terminal
        "loglevel=2",
    ]
}

def power_on_pre_pos_setup(target):
    """
    Hook called before power on to setup TFTP to boot a target in
    Provisioning Mode

    The DHCP server started by :mod:`ttbl.dnsmasq` or :mod:`ttbl.dhcp`
    are configured to direct a target to PXE boot *syslinux*; this
    will ask the TFTP server for a config file for the target's MAC
    address.

    This function is called before powering on the target to create
    said configuration file; based on the value of the target's
    *pos_mode* property, a config file that boots the Provisioning OS
    or that redirects to the local disk will be created.
    """
    pos_mode = target.fsdb.get("pos_mode")
    if pos_mode == None:
        target.log.info("POS boot: ignoring, pos_mode property not set")
        return
    # We only care if mode is set to pxe or local -- local makes us
    # tell the thing to go boot local disk
    # if none, we assume go local
    if pos_mode != "pxe" and pos_mode != "local":
        pos_mode = "local"

    boot_ic = target.tags.get('pos_boot_interconnect', None)
    if boot_ic == None:
        raise RuntimeError("CONFIG ERROR: no 'pos_boot_interconnect'"
                           " tag defined, can't boot off network")
    if not boot_ic in target.tags['interconnects']:
        raise RuntimeError("CONFIG ERROR: this target does not belong to"
                           " the boot interconnect '%s' defined in tag "
                           "'pos_boot_interconnect'" % boot_ic)

    interconnect = target.tags['interconnects'][boot_ic]
    # FIXME: at some point, for ic-less POS-PXE boot we could get this
    # from pos_mac_addr and default to ic['mac_addr']
    mac_addr = interconnect['mac_addr']

    # we need the interconnect object to get some values
    ic = ttbl.test_target.get(boot_ic)

    if pos_mode == "local":
        # pos_mode is local
        config = """\
say TCF Network boot redirecting to local boot
serial 0 115200
default localboot
prompt 0
label localboot
  localboot
"""
    else:
	# PXE mode

        # get some values we need to generate the Syslinux config file

        kws = dict(target.tags)
        if not 'bsp' in target.tags:
            bsps = target.tags.get('bsps', {}).keys()
            if bsps:
                kws['bsp'] = sorted(bsps)[0]
        kws.update(dict(
            ipv4_addr = interconnect['ipv4_addr'],
            ipv4_gateway = interconnect.get('ipv4_gateway', ""),
            ipv4_netmask = commonl.ipv4_len_to_netmask_ascii(
                interconnect['ipv4_prefix_len']),
            mac_addr = mac_addr,
            name = target.id,
        ))

        # There might be a prefix to the path to the boot kernel and
        # initrd; we let the target override it and default to the
        # network's or nothing
        tag_get_from_ic_target(kws, 'pos_http_url_prefix', ic, target)
        tag_get_from_ic_target(kws, 'pos_nfs_server', ic, target)
        tag_get_from_ic_target(kws, 'pos_nfs_path', ic, target)
        tag_get_from_ic_target(kws, 'pos_image', ic, target, 'tcf-live')

        # generate configuration for the target to boot the POS's linux
        # kernel with the root fs over NFS
        kws['extra_kopts'] = " ".join(pos_cmdline_opts[kws['pos_image']])

        # Generate the PXE linux configuration
        #
        # note the syslinux/pxelinux format supports no long line
        # breakage, so we use Python's \ for clearer, shorter lines which
        # will be pasted all together
        #
        # Most of the juicy stuff comes from the pos_cmdline_opts for
        # each image (see, eg: tcf-live's) which is filled in
        # extra_opts a few lines above
        #
        ## serial 0 115200
        config = """\
say TCF Network boot to Provisioning OS
default boot
prompt 0
label boot
  linux %(pos_http_url_prefix)svmlinuz-%(pos_image)s
  append console=tty0 console=%(linux_serial_console_default)s,115200 \
    %(extra_kopts)s
"""
        config = template_rexpand(config, kws)

    # Write the TFTP configuration  -- when the target boots and does
    # a DHCP request, DHCP daemon will send it a DHCP address and also
    # tell it to boot off TFTP with a pxelinux bootloader; it'll load
    # that bootloader, which will look for different configuration
    # files off TFTP_ROOT/pxelinux.cfg/ in a given order,
    # one of us being 01-ITSMACADDR
    #
    # It will find this one we are now making and boot to the POS for
    # provisioning or to local boot.

    tftp_root_ic = os.path.join(ic.state_dir, "tftp.root")
    if os.path.isdir(tftp_root_ic):
        # the configuration has one TFTP root per interconnect, drop
        # it there (eg: when using ttbl.dnsmasq)
        tftp_root = tftp_root_ic
        pxelinux_cfg_dir = os.path.join(tftp_root, "pxelinux.cfg")
    else:
        # One global TFTP (eg: when using the system's global tftp
        # daemon)
        tftp_prefix = "ttbd" + ttbl.config.instance_suffix
        pxelinux_cfg_dir = os.path.join(
            tftp_dir, tftp_prefix, "pxelinux.cfg")

    # config file is named 01-MACADDR
    tftp_config_file_name = os.path.join(
        pxelinux_cfg_dir,
        # 01- is the ARP type 1 for ethernet; also note the PXE client
        # asks with the hex digits in lower case.
        "01-" + mac_addr.replace(":", "-").lower())
    with open(tftp_config_file_name, "w") as tf:
        tf.write(config)
    # We know the file exists, so it is safe to chmod like this
    os.chmod(tftp_config_file_name, 0o644)
