#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""This module provides capabilities to configure the boot of a UEFI
system with the Provisioning OS.

One of the top level call is :func:`boot_config_multiroot` which is
called by :meth:`tcfl.pos.deploy_image
<tcfl.pos.extension.deploy_image>` to configure the boot for a target
that just got an image deployed to it using the multiroot methodology.

"""

import os
import pprint
import re

from . import tc
from . import tl

boot_entries_ignore = [
    # RHEL / Fedora
    re.compile('(rescue|recovery mode)'),
    # Android does this
    re.compile('Debug'),
]

def _ignore_boot_entry(target, name, origin):
    count = 0
    for regex in boot_entries_ignore:
        m = regex.search(name)
        if m:
            target.report_info(
                "POS: ignoring boot entry '%s' @%s as it matched configured "
                "regex #%d [%s] in tcfl.pos_uefi.boot_entries_ignore"
                % (name, origin, count, regex.pattern))
            return True
        count += 1
    return False


def _linux_boot_guess_from_lecs(target, _image):
    """
    Setup a Linux kernel to boot using Gumniboot
    """
    # ignore errors if it does not exist
    lecs = target.shell.run(
        r"find /mnt/boot/loader/entries -type f -iname \*.conf || true",
        output = True)
    # this returns something like
    #
    # find /mnt/boot/loader/entries -type f -iname \*.conf
    # /mnt/boot/loader/entries/Clear-linux-native-4.18.13-644.conf
    # /mnt/boot/loader/entries/Something-else.conf
    # 10 $
    #
    # Filter just the output we care for
    lecl = []
    for lec in lecs.split("\n"):
        lec = lec.strip()
        if not lec.startswith("/mnt/boot/loader/entries/"):
            continue
        if _ignore_boot_entry(target, os.path.basename(lec),
                              os.path.dirname(lec)):
            continue
        lecl.append(lec)
        target.report_info("Loader Entry found: %s" % lec, dlevel = 1)
    if len(lecl) > 1:
        raise tc.blocked_e(
            "multiple loader entries in /boot, do not "
            "know which one to use: " + " ".join(lecl),
            dict(target = target))
    elif len(lecl) == 0:
        return None, None, None
    # fallthrough, only one entry
    lec = lecl[0]
    output = target.shell.run('cat %s' % lec, output = True)
    kernel = None
    initrd = None
    options = None
    # read a loader entry, extract the kernel, initramfs and options
    # thanks Loader Entry Specification for making them single liners...
    dibs_regex = re.compile(r"^\s*(?P<command>linux|initrd|efi|options)\s+"
                            "(?P<value>[^\n]+)\n?")
    for line in output.splitlines():
        m = dibs_regex.match(line)
        if not m:
            continue
        d = m.groupdict()
        command = d['command']
        value = d['value']
        if command == 'linux':
            kernel = value
        elif command == 'efi':
            kernel = value
        elif command == 'initrd':
            initrd = value
        elif command == 'options':
            options = value

    # note we assume the LEC entries are in [/mnt]/boot because LEC
    # specifies them relateive to the filesystem
    if kernel:
        kernel = "/boot/" + kernel
    if initrd:
        initrd = "/boot/" + initrd
    return kernel, initrd, options


_grub_var_regex = re.compile(r"\${[^}]+}")
_grub_menuentry_regex = re.compile(
    "^[ \t]*(menuentry[ \t]+'(?P<name1>[^']+)'|title[ \t]+(?P<name2>.+)$)")
_grub_linux_initrd_entry_regex = re.compile(
    "^[ \t]*("
    r"(kernel|linux)[ \t]+(?P<linux>\S+)[ \t]+(?P<linux_args>.*)"
    "|"
    r"initrd[ \t]+(?P<initrd>\S+)"
    ")$")



def _linux_boot_guess_from_grub_cfg(target, _image):
    """
    Extract kernel, initrd, kernel args from grub configuration

    Parses a grub config file to extract which boot entries are
    available, with their kernel and initrd files, the command line
    options and the manu entry names.

    Eliminate recovery and default, we shall be left with only one
    that is the main boot option, the one that always has to be booted
    that we will replicate.

    A grub.cfg looks like a lot of configuration stuff, but at the
    end, it boils down to entries like::

      menuentry 'SLED 15-SP1'  --class sled --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-simple-6bfcca25-0f4b-4d6c-87a0-c3bb25e5d512' {
      	load_video
      	set gfxpayload=keep
      	insmod gzio
      	insmod part_gpt
      	insmod btrfs
      	set root='hd0,gpt2'
      	if [ x$feature_platform_search_hint = xy ]; then
      	  search --no-floppy --fs-uuid --set=root --hint-bios=hd0,gpt2 --hint-efi=hd0,gpt2 --hint-baremetal=ahci0,gpt2 --hint='hd0,gpt2'  6bfcca25-0f4b-4d6c-87a0-c3bb25e5d512
      	else
      	  search --no-floppy --fs-uuid --set=root 6bfcca25-0f4b-4d6c-87a0-c3bb25e5d512
      	fi
      	echo	'Loading Linux 4.12.14-110-default ...'
      	linux	/boot/vmlinuz-4.12.14-110-default root=UUID=6bfcca25-0f4b-4d6c-87a0-c3bb25e5d512  ${extra_cmdline} splash=silent resume=/dev/disk/by-id/ata-QEMU_HARDDISK_QM00001-part3 quiet crashkernel=173M,high
      	echo	'Loading initial ramdisk ...'
      	initrd	/boot/initrd-4.12.14-110-default
      }

    There is also the older style::

      default=0
      timeout=6
      splashimage=/grub/android-x86.xpm.gz
      root (hd0,0)

      title Android-x86 7.1-r2
      	kernel /android-7.1-r2/kernel quiet root=/dev/ram0 androidboot.selinux=permissive vmalloc=192M buildvariant=userdebug SRC=/android-7.1-r2
      	initrd /android-7.1-r2/initrd.img

      title Android-x86 7.1-r2 (Debug mode)
      	kernel /android-7.1-r2/kernel root=/dev/ram0 androidboot.selinux=permissive vmalloc=192M buildvariant=userdebug DEBUG=2 SRC=/android-7.1-r2
      	initrd /android-7.1-r2/initrd.img

      title Android-x86 7.1-r2 (Debug nomodeset)
      	kernel /android-7.1-r2/kernel nomodeset root=/dev/ram0 androidboot.selinux=permissive vmalloc=192M buildvariant=userdebug DEBUG=2 SRC=/android-7.1-r2
      	initrd /android-7.1-r2/initrd.img

      title Android-x86 7.1-r2 (Debug video=LVDS-1:d)
      	kernel /android-7.1-r2/kernel video=LVDS-1:d root=/dev/ram0 androidboot.selinux=permissive vmalloc=192M buildvariant=userdebug DEBUG=2 SRC=/android-7.1-r2
      	initrd /android-7.1-r2/initrd.img

    We ignore all but menuentry, linux, initrd; initrd might be missing

    """
    # ignore errors if it does not exist
    grub_cfg_path = target.shell.run(
        # /mnt/grub|menu.lst is android ISO x86
        # /mnt/boot|grub.cfg most other distros
        # ignore failures if the find process errors out
        "find /mnt/grub /mnt/boot"
        # redirect erros to /dev/null so they don't pollute the output we need
        " -iname grub.cfg -o -iname menu.lst 2> /dev/null"
        " || true",
        output = True, trim = True)
    grub_cfg_path = grub_cfg_path.strip()
    if grub_cfg_path == "":	# no grub.cfg to rely on
        target.report_info("POS/uefi: found no grub config")
        return None, None, None
    target.report_info("POS/uefi: found grub config at %s" % grub_cfg_path)
    # read grub in, but only the parts we care for--it's faster
    grub_cfg = target.shell.run(
        r" grep --color=never -w '\(menuentry\|title\|kernel\|linux\|initrd\)' %s"
        % grub_cfg_path,
        output = True, trim = True)

    # a grub entry
    class _entry(object):
        name = None
        linux = None
        linux_args = None
        initrd = None

    # we use a dictionary to remove duplicate entries
    #
    # we key the entries by the initrd, linux kernel and kernel args they
    # use; if they are the same, it will be overriden and we won't have to
    # pick one.
    target._grub_entries = {}
    entry = _entry()

    def _entry_record():
        entry_id = \
            (entry.linux if entry.linux else "" ) \
            + (entry.initrd if entry.initrd else "") \
            + (entry.linux_args if entry.linux_args else "")
        if entry_id != "":	# record existing
            target._grub_entries[entry_id] = entry

    entry_count = 0
    for line in grub_cfg.splitlines():
        # match menuentry lines and save name, flushing previous data
        # if any
        m = _grub_menuentry_regex.search(line)
        if m:
            # new entry!, close the previous
            _entry_record()
            entry = _entry()
            gd = m.groupdict()
            # the entries will always exist because that's the regex
            # search output, but we need to check they are not empty
            if gd['name1']:
                entry.name = gd['name1']
            elif gd['name2']:
                entry.name = gd['name2']
            else:
                entry.name = "entry #%d" % entry_count
            entry_count += 1
            continue

        # match linux/initrd lines and extract values
        m = _grub_linux_initrd_entry_regex.search(line)
        if not m:
            continue
        gd = m.groupdict()
        linux = gd.get('linux', None)
        if linux:
            entry.linux = linux
        linux_args = gd.get('linux_args', None)
        if linux:
            # remove any ${SUBST} from the command line
            linux_args = re.sub(_grub_var_regex, "", linux_args)
            entry.linux_args = linux_args
        initrd = gd.get('initrd', None)
        if initrd:
            entry.initrd = initrd

    _entry_record()	# record last entry

    # delete recovery / rescue stuff, we don't use it
    for entry_id in list(target._grub_entries.keys()):
        entry = target._grub_entries[entry_id]
        if _ignore_boot_entry(target, entry.name,
                              grub_cfg_path.replace("/mnt", "")):
            del target._grub_entries[entry_id]

    if len(target._grub_entries) > 1:
        entries = pprint.pformat([ i.__dict__
                                   for i in list(target._grub_entries.values()) ])
        raise tc.blocked_e(
            "more than one Linux kernel entry; I don't know "
            "which one to use",
            dict(target = target, entries = entries))

    if not target._grub_entries:		# can't find?
        del target._grub_entries		# need no more
        return None, None, None
    entry = list(target._grub_entries.values())[0]
    del target._grub_entries			# need no more
    return entry.linux, entry.initrd, entry.linux_args


def _linux_boot_guess_from_boot(target, image):
    """
    Given a list of files (normally) in /boot, decide which ones are
    Linux kernels and initramfs; select the latest version
    """
    # guess on the mounted filesystem, otherwise we get the POS!
    os_release = tl.linux_os_release_get(target, prefix = "/mnt")
    distro = os_release.get('ID', None)

    output = target.shell.run("ls -1 /mnt/boot", output = True)
    kernel_regex = re.compile("(initramfs|initrd|bzImage|vmlinuz)(-(.*))?")
    kernel_versions = {}
    initramfs_versions = {}
    for line in output.split('\n'):
        m = kernel_regex.match(line)
        if not m:
            continue
        file_name = m.groups()[0]
        kver = m.groups()[1]
        if kver == None:
            kver = "default"
        if kver and ("rescue" in kver or "kdump" in kver):
            # these are usually found on Fedora
            continue
        elif file_name in ( "initramfs", "initrd" ):
            if kver.endswith(".img"):
                # remove .img extension that has been pegged to the version
                kver = os.path.splitext(kver)[0]
            initramfs_versions[kver] = line
        else:
            kernel_versions[kver] = line

    if len(kernel_versions) > 1 and 'default' in kernel_versions:
        del kernel_versions['default']

    if len(kernel_versions) == 1:
        kver = list(kernel_versions.keys())[0]
        options = ""
        # image is atuple of (DISTRO, SPIN, VERSION, SUBVERSION, ARCH)
        if distro in ("fedora", "debian", "ubuntu") and 'live' in image:
            # Live distros needs this to boot, unknown exactly why;
            # also add console=tty0 to ensure it is not lost
            target.report_info("Linux Live hack: adding 'rw' to cmdline",
                               dlevel = 2)
            options = "console=tty0 rw"
        kernel = kernel_versions[kver]
        if kernel:
            kernel = "/boot/" + kernel
        initrd = initramfs_versions.get(kver, None)
        if initrd:
            initrd = "/boot/" + initrd
        return kernel, initrd, options
    elif len(kernel_versions) > 1:
        raise tc.blocked_e(
            "more than one Linux kernel in /boot; I don't know "
            "which one to use: " + " ".join(kernel_versions),
            dict(target = target, output = output))
    else:
        return None, None, ""

def _linux_boot_guess(target, image):
    """
    Scan the boot configuration and extract it, so we can replicate it
    """
    # systemd-boot
    kernel, initrd, options = _linux_boot_guess_from_lecs(target, image)
    if kernel:
        return kernel, initrd, options
    kernel, initrd, options = _linux_boot_guess_from_grub_cfg(target, image)
    if kernel:
        return kernel, initrd, options
    # from files listed in /boot
    kernel, initrd, options = _linux_boot_guess_from_boot(target, image)
    if kernel:
        target.report_info("POS: guessed kernel from /boot directory: "
                           "kernel %s initrd %s options %s"
                           % (kernel, initrd, options))
        return kernel, initrd, options
    return None, None, None


pos_boot_names = [
    # UEFI: PXE IP[46].*
    # UEFI PXEv[46].*
    re.compile(r"^UEFI:?\s+PXE[v ](IP)?[46].*$"),
    # UEFI: IP4 Intel(R) Ethernet Connection I354
    # UEFI : LAN : IP[46] Intel(R) Ethernet Connection (\(3\))? I218-V
    # UEFI : LAN : IP[46] Realtek PCIe GBE Family Controller
    # UEFI : LAN : PXE IP[46] Intel(R) Ethernet Connection (2) I219-LM
    re.compile(r"^UEFI\s?:( LAN :)? (IP|PXE IP)[46].*$"),
]

local_boot_names = [
    # TCF Localboot v2
    re.compile("^TCF Localboot v2$"),
    # UEFI : INTEL SSDPEKKW010T8 : PART 0 : OS Bootloader
    # UEFI : SATA : PORT 0 : INTEL SSDSC2KW512G8 : PART 0 : OS Bootloader
    # UEFI : M.2 SATA :INTEL SSDSCKJF240A5 : PART 0 : OS Bootloader
    re.compile("^UEFI : .* PART [0-9]+ : OS Bootloader$"),
]

def _name_is_pos_boot(name):
    for regex in pos_boot_names:
        if regex.search(name):
            return True
    return False

def _name_is_local_boot(name):
    for regex in local_boot_names:
        if regex.search(name):
            return True
    return False

_boot_order_regex = re.compile(
    r"^BootOrder: (?P<boot_order>[0-9a-fA-F,]+)$", re.MULTILINE)

_entry_regex = re.compile(
    r"^Boot(?P<entry>[0-9A-F]{4})\*? (?P<name>.*)$", re.MULTILINE)

def _efibootmgr_output_parse(target, output):

    boot_order_match = _boot_order_regex.search(output)
    if not boot_order_match:
        raise tc.error_e("can't extract boot order",
                         attachments = dict(target = target, output = output))
    boot_order = boot_order_match.groupdict()['boot_order'].split(',')

    entry_matches = re.findall(_entry_regex, output)
    # returns a list of [ ( HHHH, ENTRYNAME ) ], HHHH hex digits, all str

    boot_entries = []
    for entry in entry_matches:
        if _name_is_pos_boot(entry[1]):
            section = 0		# POS (PXE, whatever), boot first
        elif _name_is_local_boot(entry[1]):
            section = 10	# LOCAL, boot after
        else:
            section = 20	# others, whatever
        try:
            boot_index = boot_order.index(entry[0])
            boot_entries.append(( entry[0], entry[1], section, boot_index ))
        except ValueError:
            # if the entry is not in the boot order, that is fine,
            # ignore it
            pass

    return boot_order, boot_entries

efi_entries_to_remove = [
    "Linux bootloader",
    "ACRN",
    "debian",
]

def _efibootmgr_ponder(target, output):
    boot_order, boot_entries = _efibootmgr_output_parse(target, output)

    # boot_entries has been sorted as it is in the current
    # efibootmanager, and classified each entry in [2] as POS, LOCAL
    # or leftover. We want POS, then LOCAL, then the rest.

    # We want the same order being kept--why? Because some EFIs keep
    # rearranging it, unknown why and if we keep updating they end up
    # hitting some limit and crapping on themselves when we try to
    # update (eg: they keep putting IPv6 PXE next to IPv4 PXE even if
    # we put localboot after PXE IPv4).

    # So we stop fighting it, maintain the order they want but make
    # sure there is some kind of localboot after the POS entries
    # section. Our PXEBOOTe controller will always redirect to
    # localboot, be it IPv4 or IPv6.

    tcf_local_boot_seen = False
    boot_order_needed = []
    # sorted does stable sorts; e[3] has current boot order, e[2] has
    # 'section' order--we still enforce it, to be double sure
    for entry in sorted(boot_entries, key = lambda e: (e[2], e[3])):
        if entry[1] == "TCF Localboot v2" and tcf_local_boot_seen:
            # excess TCF Localboot v2 entries, remove
            target.shell.run("efibootmgr -b %s -B" % entry[0])
            continue
        elif entry[1] == "TCF Localboot v2" and not tcf_local_boot_seen:
            tcf_local_boot_seen = True	# will be added in the passwhtrough
        elif entry[1] == "TCF Localboot":	# old stuff, remove
            target.shell.run("efibootmgr -b %s -B" % entry[0])
            continue
        elif entry[1] in efi_entries_to_remove:	# old stuff, remove
            target.shell.run("efibootmgr -b %s -B" % entry[0])
            continue
        # fallthrough
        boot_order_needed.append(entry)

    _boot_order_needed = [ e[0] for e in boot_order_needed ]
    target.report_info("POS/EFI: current boot order: "
                       + " ".join(boot_order),
                       dict(boot_entries = pprint.pformat(boot_entries)),
                       dlevel = 1)
    target.report_info("POS/EFI: boot order needed: "
                       + " ".join(_boot_order_needed),
                       dict(boot_entries = pprint.pformat(_boot_order_needed)),
                       dlevel = 1)

    return boot_order, _boot_order_needed, not tcf_local_boot_seen


def _efibootmgr_setup(target, boot_dev, partition):
    """
    Ensure EFI Boot Manager boots first to what we consider our
    Provisioning OS sections (mostly PXE boot), then to a localboot
    entry (local bootloader or 'TCF Localboot v2').

    We do this because the configuration file the server drops in TFTP
    for syslinux to pick up for the MAC address of the target will
    tell it if the target boots to POS mode or to local boot. So we
    don't have to mess with BIOS menus.

    General efibootmgr output::

      $ efibootmgr
      BootCurrent: 0006
      Timeout: 0 seconds
      BootOrder: 0000,0006,0004,0005
      Boot0000* TCF Localboot
      Boot0004* UEFI : Built-in EFI Shell
      Boot0005* UEFI : LAN : IP6 Intel(R) Ethernet Connection (3) I218-V
      Boot0006* UEFI : LAN : IP4 Intel(R) Ethernet Connection (3) I218-V

    Note the server can configure :ref:`how the UEFI network entry
    looks over the defaults <uefi_boot_manager_ipv4_regex>`.

    Note we only touch the boot order once we have the local boot
    entry created.
    """

    # ok, get current EFI bootloader status
    output = target.shell.run("efibootmgr", output = True)
    boot_order, boot_order_needed, need_to_add = \
        _efibootmgr_ponder(target, output)
    if need_to_add:
        # Create the TCF Localboot entry; we make it boot the local
        # default (BOOTX64) which in our case is installed by
        # boot_config_multiroot() running bootctl. No altering boot
        # order, we'll do it later atomically to make sure IPv4 PXE is
        # always first.
        output = target.shell.run(
            "efibootmgr -c -d /dev/%s -p %d -L 'TCF Localboot v2'"
            # Python backslashes \\ -> \, so \\\\ becomes \\ that the
            # shell convers to a single \. Yes, it was a very good
            # idea to use as directory separator the same character
            # everyone uses for escaping. Grunt.
            # https://blogs.msdn.microsoft.com/larryosterman/2005/06/24/why-is-the-dos-path-character/
            " -l \\\\EFI\\\\BOOT\\\\BOOTX64.EFI" % (boot_dev, partition),
            output = True)
        # yeah, lame, but simple...
        boot_order, boot_order_needed, need_to_add = \
            _efibootmgr_ponder(target, output)
        assert need_to_add == False

    if boot_order != boot_order_needed:
        target.report_info(
            "POS: updating EFI boot order to %s from %s"
            % (",".join(boot_order_needed), ",".join(boot_order)))
        target.shell.run("efibootmgr -o " + ",".join(boot_order_needed))
    else:
        target.report_info("POS: maintaining EFI boot order %s"
                           % ",".join(boot_order))

    # We do not set the next boot order to be our system; why?
    # multiple times, the system gets confused when it has to do
    # So we use syslinux to always control it; also, seems that if we
    # access too frequently, the BIOS API gets corrupted

def boot_config_multiroot(target, boot_dev, image):
    """
    Configure the target to boot using the multiroot
    """
    boot_dev = target.kws['pos_boot_dev']
    # were we have mounted the root partition
    root_dir = "/mnt"

    linux_kernel_file, linux_initrd_file, linux_options = \
        _linux_boot_guess(target, image)
    if linux_kernel_file == None:
        raise tc.blocked_e(
            "Cannot guess a Linux kernel to boot",
            dict(target = target))
    # remove absolutization (some specs have it), as we need to copy from
    # mounted filesystems
    if os.path.isabs(linux_kernel_file):
        linux_kernel_file = linux_kernel_file[1:]
    if linux_initrd_file and os.path.isabs(linux_initrd_file):
        linux_initrd_file = linux_initrd_file[1:]

    if linux_options == None or linux_options == "":
        target.report_info("WARNING! can't figure out Linux cmdline "
                           "options, taking defaults")
        # below we'll add more stuff
        linux_options = "console=tty0 root=SOMEWHERE"

    # MULTIROOT: indicate which image has been flashed to this
    # partition
    # saved by pos_multiroot.mountfs
    root_part_dev = target.root_part_dev
    root_part_dev_base = os.path.basename(root_part_dev)
    target.property_set('pos_root_' + root_part_dev_base, image)
    # /boot EFI system partition is always /dev/DEVNAME1 (first
    # partition), we partition like that
    # FIXME: we shouldn't harcode this
    boot_part_dev = boot_dev + target.kws['p_prefix'] + "1"

    kws = dict(
        boot_dev = boot_dev,
        boot_part_dev = boot_part_dev,
        root_part_dev = root_part_dev,
        root_part_dev_base = root_part_dev_base,
        root_dir = root_dir,
        linux_kernel_file = linux_kernel_file,
        linux_kernel_file_basename = os.path.basename(linux_kernel_file),
        linux_initrd_file = linux_initrd_file,
        linux_options = linux_options,
    )
    if linux_initrd_file:
        kws['linux_initrd_file_basename'] = os.path.basename(linux_initrd_file)
    else:
        kws['linux_initrd_file_basename'] = None

    kws.update(target.kws)

    if linux_options:
        #
        # Maybe mess with the Linux boot options
        #
        target.report_info("linux cmdline options: %s" % linux_options)
        # FIXME: can this come from config?
        linux_options_replace = {
            # we want to use hard device name rather than LABELS/UUIDs, as
            # we have reformated and those will have changed
            "root": "/dev/%(root_part_dev_base)s" % kws,
            # we have created this in pos_multiroot and will only
            # replace it if the command line option is present.
            "resume": "/dev/disk/by-label/tcf-swap",
        }

        # FIXME: can this come from config?
        # We harcode a serial console on the device where we know the
        # framework is listening
        linux_options_append = \
            "console=%(linux_serial_console_default)s,115200n8" % kws

        linux_options_append += " " + target.rt.get('linux_options_append', "")

        linux_options += " " + linux_options_append

        for option, value in linux_options_replace.items():
            regex = re.compile(r"\b" + option + r"=\S+")
            if regex.search(linux_options):
                linux_options = re.sub(
                    regex,
                    option + "=" + linux_options_replace[option],
                    linux_options)
            else:
                linux_options += " " + option + "=" + value

        kws['linux_options'] = linux_options
        target.report_info("linux cmdline options (modified): %s"
                           % linux_options)

    # Now generate the UEFI system partition that will boot the
    # system; we always override it, so we don't need to decide if it
    # is corrupted or whatever; we'll mount it in /boot (which now is
    # the POS /boot)

    #
    # Mount the /boot fs
    #
    # Try to assume it is ok, try to repair it if not; rsync the
    # kernels in there, it is faster for repeated operation/
    #
    target.report_info("POS/EFI: checking %(boot_part_dev)s" % kws)
    output = target.shell.run(
        "fsck.fat -aw /dev/%(boot_part_dev)s || true" % kws,
        output = True, trim = True)

    # FIXME: parse the output to tell if there was a problem; when bad
    # but recovered, we'll see
    #
    # 0x41: Dirty bit is set. Fs was not properly unmounted and some data may be corrupt.
    #  Automatically removing dirty bit.
    # Performing changes.
    # /dev/sda1: 11 files, 4173/261372 clusters

    # When ok
    #
    ## $ sudo fsck.vfat -wa /dev/nvme0n1p1
    ## fsck.fat 4.1 (2017-01-24)
    ## /dev/sda1: 39 files, 2271/33259 clusters

    # When really hosed it won't print the device line, so we look for
    # that
    #
    ## $ fsck.vfat -wa /dev/trash
    ## fsck.fat 4.1 (2017-01-24)
    ## Logical sector size (49294 bytes) is not a multiple of the physical sector size.
    good_regex = re.compile("^/dev/%(boot_part_dev)s: [0-9]+ files, "
                            "[0-9]+/[0-9]+ clusters$" % kws, re.MULTILINE)
    if not good_regex.search(output):
        target.report_info(
            "POS/EFI: /dev/%(boot_part_dev)s: formatting EFI "
            "filesystem, fsck couldn't fix it"
            % kws, dict(output = output))
        target.shell.run("mkfs.fat -F32 /dev/%(boot_part_dev)s; sync" % kws)
    target.report_info(
        "POS/EFI: /dev/%(boot_part_dev)s: mounting in /boot" % kws)
    target.shell.run(" mount /dev/%(boot_part_dev)s /boot; "
                     " mkdir -p /boot/loader/entries " % kws)

    # Do we have enough space? if not, remove the oldest stuff that is
    # not the file we are looking for
    # This prints
    ## $ df --output=pcent /boot
    ## Use%
    ##   6%
    output = target.shell.run("df --output=pcent /boot", output = True)
    regex = re.compile(r"^\s*(?P<percent>[\.0-9]+)%$", re.MULTILINE)
    match = regex.search(output)
    if not match:
        raise tc.error_e("Can't determine the amount of free space in /boot",
                         dict(output = output))
    used_space = float(match.groupdict()['percent'])
    if used_space > 75:
        target.report_info(
            "POS/EFI: /dev/%(boot_part_dev)s: freeing up space" % kws)
        # List files in /boot, sort by last update (when we rsynced
        # them)
        ## 2018-10-29+08:48:48.0000000000	84590	/boot/EFI/BOOT/BOOTX64.EFI
        ## 2018-10-29+08:48:48.0000000000	84590	/boot/EFI/systemd/systemd-bootx64.efi
        ## 2019-05-14+13:25:06.0000000000	7192832	/boot/vmlinuz-4.12.14-110-default
        ## 2019-05-14+13:25:08.0000000000	9688340	/boot/initrd-4.12.14-110-default
        ## 2019-05-14+13:25:14.0000000000	224	/boot/loader/entries/tcf-boot.conf
        ## 2019-05-14+13:25:14.0000000000	54	/boot/loader/loader.conf
        output = target.shell.run(
            # that double \\ needed so the shell is the one using it
            # as a \t, not python converting to a sequence
            "find /boot/ -type f -printf '%T+\\t%s\\t%p\\n' | sort",
            output = True, trim = True)
        # delete the first half entries over 300k except those that
        # match the kernels we are installing
        to_remove = []
        _linux_initrd_file = kws.get("linux_initrd_file", "%%NONE%%")
        if linux_initrd_file == None:
            _linux_initrd_file = "%%NONE%%"
        for line in output.splitlines():
            _timestamp, size_s, path = line.split(None, 3)
            size = int(size_s)
            if size > 300 * 1024 \
               and not kws['linux_kernel_file_basename'] in path \
               and not _linux_initrd_file in path:
                to_remove.append(path)
        # get older half and wipe it--this means the first half, as we
        # sort from older to newer
        to_remove = to_remove[:len(to_remove)//2]
        for path in to_remove:
            # we could do them in a single go, but we can exceed the
            # command line length -- lazy to optimize it
            target.shell.run("rm -f %s" % path)

    # Now copy all the files needed to boot to the root of the EFI
    # system partition mounted in /boot; remember they are in /mnt/,
    # our root partition
    target.shell.run(
        "time -p rsync --force --inplace /mnt/%(linux_kernel_file)s"
        " /boot/%(linux_kernel_file_basename)s" % kws)
    if kws.get("linux_initrd_file", None):
        target.shell.run(
            "time -p rsync --force --inplace /mnt/%(linux_initrd_file)s"
            " /boot/%(linux_initrd_file_basename)s" % kws)
    # we are the only one who cuts the cod here (yeah, direct Spanish
    # translation for the reader's entertainment), and if not wipe'm to
    # eternity; otherwise systemd will boot something prolly in
    # alphabetical order, not what we want
    target.shell.run("/usr/bin/rm -rf /boot/loader/entries/*.conf")
    # remember paths to the bootloader are relative to /boot
    # merge these two
    tcf_boot_conf = """\
cat <<EOF > /boot/loader/entries/tcf-boot.conf
title TCF-driven local boot
linux /%(linux_kernel_file_basename)s
options %(linux_options)s
"""
    if kws.get("linux_initrd_file", None):
        tcf_boot_conf += "initrd /%(linux_initrd_file_basename)s\n"
    tcf_boot_conf += "EOF\n"
    target.shell.run(tcf_boot_conf % kws)

    # Install new -- we wiped the /boot fs new anyway; if there are
    # multiple options already, bootctl shall be able to handle it.
    # Don't do variables in the any casewe will poke with them later
    # on anyway. Why? Because there is space for a race condition that
    # will leave us with the system booting off the localdisk vs the
    # network for PXE--see efibootmgr_setup()
    target.shell.run("bootctl update --no-variables"
                     " || bootctl install --no-variables;"
                     " sync")

    # Now mess with the EFIbootmgr
    # FIXME: make this a function and a configuration option (if the
    # target does efibootmgr)
    _efibootmgr_setup(target, boot_dev, 1)
    # umount only if things go well
    # Shall we try to unmount in case of error? nope, we are going to
    # have to redo the whole thing anyway, so do not touch it, in case
    # we are jumping in for manual debugging
    target.shell.run("umount /dev/%(boot_part_dev)s" % kws)


def boot_config_fix(target):
    # when the system was supposed to boot into Provisioning OS, it
    # didn't, but seems it booted some other OS.
    #
    # In the case of UEFI systems, this booted into a OS because the
    # EFI bootmgr order got munged, so let's try to get that fixed
    # (IPv4 and IPv6 boot first).
    try:
        prompt_original = target.shell.linux_shell_prompt_regex
        target.shell.linux_shell_prompt_regex = tl.linux_root_prompts
        target.shell.up(user = 'root')
        _efibootmgr_setup(target, target.kws['pos_boot_dev'], 1)
    finally:
        target.shell.linux_shell_prompt_regex = prompt_original
