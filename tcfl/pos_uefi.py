#! /usr/bin/python2
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
import re

import tc
import tl


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
        if 'rescue' in lec:
            target.report_info("POS: ignoring rescue loader entry %s" % lec)
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

    return kernel, initrd, options

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
        kver = kernel_versions.keys()[0]
        options = ""
        # image is atuple of (DISTRO, SPIN, VERSION, SUBVERSION, ARCH)
        if distro in ("fedora", "debian", "ubuntu") and 'live' in image:
            # Live distros needs this to boot, unknown exactly why;
            # also add console=tty0 to ensure it is not lost
            target.report_info("Linux Live hack: adding 'rw' to cmdline",
                               dlevel = 2)
            options = "console=tty0 rw"
        return kernel_versions[kver], \
            initramfs_versions.get(kver, None), \
            options
    elif len(kernel_versions) > 1:
        raise tc.blocked_e(
            "more than one Linux kernel in /boot; I don't know "
            "which one to use: " + " ".join(kernel_versions),
            dict(target = target, output = output))
    else:
        return None, None, ""

def _linux_boot_guess(target, image):
    """
    Setup a Linux kernel to boot using Gumniboot
    """
    kernel, initrd, options = _linux_boot_guess_from_lecs(target, image)
    if kernel:
        return kernel, initrd, options
    kernel, initrd, options = _linux_boot_guess_from_boot(target, image)
    if kernel:
        target.report_info("POS: guessed kernel from /boot directory: "
                           "kernel %s initrd %s options %s"
                           % (kernel, initrd, options))
        return kernel, initrd, options
    return None, None, None


def efibootmgr_setup(target):
    """
    Ensure EFI Boot Manager boots first to IPv4 and then to an entry
    we are creating called Linux Boot Manager.

    We do this because the configuration file the server drops in TFTP
    for syslinux to pick up for the MAC address of the target will
    tell it if the target boots to POS mode or to local boot. So we
    don't have to mess with BIOS menus.

    General efibootmgr output::

      $ efibootmgr
      BootCurrent: 0006
      Timeout: 0 seconds
      BootOrder: 0000,0006,0004,0005
      Boot0000* Linux Boot Manager
      Boot0004* UEFI : Built-in EFI Shell
      Boot0005* UEFI : LAN : IP6 Intel(R) Ethernet Connection (3) I218-V
      Boot0006* UEFI : LAN : IP4 Intel(R) Ethernet Connection (3) I218-V

    Note the server can configure :ref:`how the UEFI network entry
    looks over the defaults <uefi_boot_manager_ipv4_regex>`.
    """
    # this allows getting metadata from the target that tells us what
    # to look for in the UEFI thing
    uefi_bm_ipv4_entries = [
        "U?EFI Network.*$",
        "UEFI PXEv4.*$",
        ".*IPv?4.*$",
    ]
    # FIXME: validate better
    if 'uefi_boot_manager_ipv4_regex' in target.kws:
        uefi_bm_ipv4_entries.append(target.kws["uefi_boot_manager_ipv4_regex"])
    ipv4_regex = re.compile(
        # PXEv4 is QEMU's UEFI
        # .*IPv4 are some NUCs I've found
        "(" + "|".join(uefi_bm_ipv4_entries) + ")",
        re.MULTILINE)

    # ok, get current EFI bootloader status
    output = target.shell.run("efibootmgr", output = True)
    
    boot_order_regex = re.compile(
        r"^BootOrder: (?P<boot_order>[0-9a-fA-F,]+)$", re.MULTILINE)
    boot_order_match = boot_order_regex.search(output)
    if not boot_order_match:
        raise tc.error_e("can't extract boot order",
                         attachments(target = target, output = output))
    boot_order_original = boot_order_match.groupdict()['boot_order'].split(',')

    # this respects the current bootorder besides just
    # adding ipv4 and putting the local one first
    entry_regex = re.compile(
        r"^Boot(?P<entry>[0-9A-F]{4})\*? (?P<name>.*)$", re.MULTILINE)
    matches = re.findall(entry_regex, output)
    boot_order = [ ]
    local_boot_order = [ ]
    network_boot_order = [ ]
    seen = False
    for entry, name in matches:
        if name in [ 'Linux Boot Manager', 'Linux bootloader' ]:
            # delete repeated entries
            if seen:
                target.report_info("removing repeated EFI boot entry %s (%s)"
                                   % (entry, name))
                target.shell.run("efibootmgr -b %s -B" % entry)
                continue	# don't add it to the boot order
            seen = True
            local_boot_order.append(entry)
        elif ipv4_regex.search(name):
            # Ensure ipv4 boot is first
            network_boot_order.append(entry)
        elif entry in boot_order_original:
            boot_order.append(entry)
        else:
            # if the entry wasn't in the original boot order, ignore it
            pass
    target.shell.run("efibootmgr -o " + ",".join(
        network_boot_order + local_boot_order + boot_order))
    
    # We do not set the next boot order to be our system; why?
    # multiple times, the system gets confused when it has to do
    # So we use syslinux to always control it

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
            "root": "/dev/%(root_part_dev_base)s" % kws
        }

        # FIXME: can this come from config?
        # We harcode a serial console on the device where we know the
        # framework is listening
        linux_options_append = \
            "console=%(linux_serial_console_default)s,115200n8" % kws

        linux_options_append += " " + target.rt.get('linux_options_append', "")

        linux_options += " " + linux_options_append

        for option, value in linux_options_replace.iteritems():
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

    # mkfs.vfat /boot, mount it
    target.report_info("mounting %(boot_part_dev)s in /boot" % kws)
    target.shell.run(
        "mkfs.fat -F32 /dev/%(boot_part_dev)s; "
        " sync;"
        " mount /dev/%(boot_part_dev)s /boot; "
        " mkdir -p /boot/loader/entries; "
        """\
cat <<EOF > /boot/loader/entries/README
This boot configuration was written by TCF's AFAPLI client hack; it is
meant to boot multiple Linux distros coexisting in the
same drive.

Uses systemd-boot/gumniboot; partition one is /boot (EFI System
Partition), where this file is located. Partition 2 is dedicated to
swap. Partition 3 is dedicated to home/scratch, which can be wiped
and reset everytime a new test is run.

Partitions 4-on are different root filesystems which can be reused by
the system as needed for booting different images (aka: distros
configured in particular ways).
EOF
""" % kws)

    # Now copy all the files needed to boot to the root of the EFI
    # system partition mounted in /boot; remember they are in /mnt/,
    # our root partition
    # use dd instead of cp, it won't ask to override random params and such
    target.shell.run("dd if=/mnt/boot/%(linux_kernel_file)s "
                     "of=/boot/%(linux_kernel_file_basename)s" % kws)
    # remember paths to the bootloader are relative to /boot
    target.shell.run("""\
cat <<EOF > /boot/loader/entries/tcf-boot.conf
title TCF-driven local boot
linux /%(linux_kernel_file_basename)s
options %(linux_options)s
EOF
""" % kws)
    if kws.get("linux_initrd_file", None):
        target.shell.run("dd if=/mnt/boot/%(linux_initrd_file)s "
                         "of=/boot/%(linux_initrd_file_basename)s" % kws)
    # remember paths to the bootloader are relative to /boot
        target.shell.run("""\
cat <<EOF >> /boot/loader/entries/tcf-boot.conf
initrd /%(linux_initrd_file_basename)s
EOF
""" % kws)

    # Install new or update existing
    # don't do variables in the update case, as we will poke with them
    # later on anyway
    target.shell.run("bootctl update --no-variables"
                     " || bootctl install;"
                     " sync")

    # Now mess with the EFIbootmgr
    # FIXME: make this a function and a configuration option (if the
    # target does efibootmgr)
    efibootmgr_setup(target)
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
        efibootmgr_setup(target)
    finally:
        target.shell.linux_shell_prompt_regex = prompt_original
