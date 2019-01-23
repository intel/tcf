#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
This module provides tools to image devices with a Provisioning OS.

The general operation mode for this is instructing the device to boot
the :term:`Provisioning OS <POS>`; at this point, the test script (or
via the *tcf* client line) can interact with the POS over the serial
console.

Then the device can be partitioned, formatted, etc with general Linux
command line. As well, we can provide an :mod:`rsync server
<ttbl.rsync>` to provide OS images that can be flashed

Booting to POS can be accomplished:

- by network boot and root over NFS
- by a special boot device pre-configured to always boot POS
- any other

Server side modules used actively by this system:

- DHCP server :mod:`ttbl.dhcp`: provides dynamic IP address
  assignment; it can be configured so a pre-configured IP address is
  always assigned to a target and will provide also PXE/TFTP boot
  services to boot into POS mode (working in conjunction with a HTTP,
  TFTP and NFS servers).

- rsync server :mod:`ttbl.rsync`: provides access to images to rsync
  into partitions (which is way faster than some other imaging methods
  when done over a 1Gbps link).

- port redirector :mod:`ttbl.socat`: not strictly needed for POS, but
  useful to redirect ports out of the :term:`NUT` to the greater
  Internet. This comes handy if as part of the testing external
  software has to be installed or external services acccessed.

Note installation in the server side is needed, as described in
:ref:`POS setup <pos_setup>` (FIXME: this link is not taking to the
right spot).
"""

import operator
import os
import random
import re
import traceback

import distutils.version
import Levenshtein

import tcfl.tc

def target_rsyncd_start(ic, target):
    """
    Start an *rsync* server on a target running Provisioning OS

    This can be used to receive deployment files from any location
    needed to execute later in the target. The server is attached to
    the ``/mnt`` directory and the target is upposed to mount the
    destination filesystems there.

    This is usually called automatically for the user by the likes of
    :func:`deploy_image` and others.

    It will create a tunnel from the server to the target's port where
    the rsync daemon is listening. A client can then connect to the
    server's port to stream data over the rsync protocol. The server
    address and port will be stored in the *target*'s keywords
    *rsync_port* and *rsync_server* and thus can be accessed with:

    >>> print target.kws['rsync_server'], target.kws['rsync_port']

    :param tcfl.tc.interconnect_c ic: interconnect (network) to which
      the target is connected.
    """
    target.shell.run("""\
cat > /tmp/rsync.conf <<EOF
[rootfs]
use chroot = true
path = /mnt/
read only = false
timeout = 60
uid = root
gid = root
EOF""")
    # start rsync in the background, save it's PID file as rsync makes
    # no pids and we might not have killall in the POS
    target.shell.run(
        "rsync --port 3000 --daemon --no-detach --config /tmp/rsync.conf & "
        "echo $! > /tmp/rsync.pid")
    # Tell the tunneling interface which IP address we want to use
    target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
    target.kw_set('rsync_port', target.tunnel.add(3000))
    target.kw_set('rsync_server', target.rtb.parsed_url.hostname)

def target_rsync(target, src = None, dst = None,
                 persistent_name = None,
                 persistent_dir = '/persistent.tcf.d'):
    """
    rsync data from the local machine to a target

    The local machine is the machine executing the test script (where
    *tcf run* was called).

    This function will first rsync data to a location in the target
    (persistent storage ``/persistent.tcd.d``) that will not be
    overriden when flashing images. Then it will rsync it from there
    to the final location.

    This allows the content to be cached in between testcase execution
    that reimages the target. Thus, the first run, the whole source
    tree is transferred to the persistent area, but subsequent runs
    will already find it there even when if the OS image has been
    reflashed (as the reflashing will not touch the persistent
    area). Of course this assumes the previous executions didn't wipe
    the persistent area or the whole disk was not corrupted.

    This function can be used, for example, when wanting to deploy
    extra data to the target when using :func:`deploy_image`:

    >>> @tcfl.tc.interconnect("ipv4_addr")
    >>> @tcfl.tc.target("pos_capable")
    >>> class _test(tcfl.tc.tc_c)
    >>>     ...
    >>>
    >>>     @staticmethod
    >>>     def _deploy_mygittree(_ic, target, _kws):
    >>>         tcfl.pos.target_rsync(target,
    >>>                               os.path.expanduser("~/somegittree.git"),
    >>>                               dst = '/opt/somegittree.git')
    >>>
    >>>     def deploy(self, ic, target):
    >>>         ic.power.on()
    >>>         tcfl.pos.deploy_image(
    >>>             ic, target, "fedora::29",
    >>>             extra_deploy_fns = [ self._deploy_mygittree ])
    >>>
    >>>     ...


    In this example, the user has a cloned git tree in
    ``~/somegittree.git`` that has to be flashed to the target into
    ``/opt/somegittree.git`` after ensuring the root file system is
    flashed with *Fedora 29*. :func:`deploy_image` will start the rsync
    server and then call *_deploy_mygittree()*  which will use
    :func:`target_rsync` to rsync from the user's machine to the
    target's persistent location (in
    ``/mnt/peristent.tcf.d/somegittree.git``) and from there to the
    final location of ``/mnt/opt/somegittree.git``. When the system
    boots it will be of course in ``/opt/somegittree.git``

    :param tcfl.tc.target_c target: target to which rsync; it must
      describe the rsync destination in keywords:

       >>> target.kws['rsync_server']
       >>> target.kws['rsync_port']

      as setup by calling :func:target_rsyncd_start on the
      target. Functions such as :func:`deploy_image` do this for you.

    :param str src: (optional) source tree/file in the local machine
      to be copied to the target's persistent area. If not specified,
      nothing is copied to the persistent area.

    :param str dst: (optional) destination tree/file in the target
      machine; if specified, the file is copied from the persistent
      area to the final destination. If not specified,
      nothing is copied from the persistent area to the final
      destination.

    :param str persistent_name: (optional) name for the file/tree in
      the persistent area; defaults to the basename of the source file
      specification.

    :param str persistent_dir: (optional) name for the persistent
      area in the target, defaults to `/persistent.tcf.d`.
    """
    target.shell.run("mkdir -p /mnt/%s" % persistent_dir)
    # upload the directory to the persistent area
    if persistent_name == None:
        assert src != None, \
            "no `src` parameter is given, `persistent_name` must " \
            "then be specified"
        persistent_name = os.path.basename(src)
    if src != None:
        target.report_info("rsyncing %s to target's persistent area %s/%s"
                           % (src, persistent_dir, persistent_name))
        target.shcmd_local(
            # don't be verbose, makes it too slow and timesout when
            # sending a lot of files
            "time rsync -aAX --numeric-ids --delete --port %%(rsync_port)s "
            " %s/. %%(rsync_server)s::rootfs/%s/%s"
            % (src, persistent_dir, persistent_name))
    target.testcase._targets_active()
    if dst != None:
        # There is a final destination specified, so now, in the
        # target, make a copy from the persistent area to the final
        # destination
        parent_dirs = os.path.dirname(dst)
        if parent_dirs != '':
            target.shell.run("mkdir -p /mnt/%s" % parent_dirs)
        target.shell.run(
            # don't be verbose, makes it too slow and timesout when
            # sending a lot of files
            "time rsync -aAX --delete /mnt/%s/%s/. /mnt/%s"
            % (persistent_dir, persistent_name, dst))

def target_rsyncd_stop(target):
    """
    Stop an *rsync* server on a target running Provisioning OS

    A server was started with :func:`target_rsyncd_start`; kill it
    gracefully.
    """
    # Use sh syntax rather than bash's $(</tmp/rsync.pid) to avoid
    # surprises if the shall changes; ideally we'd use killall, but we
    # don't know if it is installed in the POS
    target.shell.run("kill -9 `cat /tmp/rsync.pid`")
    # remove the runnel we created to the rsync server and the
    # keywords to access it
    target.tunnel.remove(int(target.kws['rsync_port']))
    target.kw_unset('rsync_port')
    target.kw_unset('rsync_server')

def partition(target, device):
    # /dev/SOMETHING to -> SOMETHING
    device_basename = os.path.basename(device)

    # in case we autoswapped on anything
    target.shell.run('swapoff -a || true')

    output = target.shell.run(
        'cat /sys/block/%s/size /sys/block/%s/queue/physical_block_size'
        % (device_basename, device_basename), output = True)
    regex = re.compile("^(?P<blocks>[0-9]+)\n"
                       "(?P<block_size>[0-9]+)$", re.MULTILINE)
    m = regex.search(output)
    if not m:
        raise tcfl.tc.blocked_e(
            "can't find block and physical blocksize",
            { 'output': output, 'pattern': regex.pattern,
              'target': target }
        )
    blocks = int(m.groupdict()['blocks'])
    block_size = int(m.groupdict()['block_size'])
    size_gb = blocks * block_size / 1024 / 1024 / 1024
    target.report_info("POS: %s is %d GiB in size" % (device, size_gb),
                       dlevel = 2)

    partsizes = target.kws.get('pos_partsizes', None)
    if partsizes == None:
        raise tcfl.tc.blocked_e(
            "Can't partition target, it doesn't "
            "specify pos_partsizes tag",
            { 'target': target } )
    partsize_l = partsizes.split(":")
    partsize_l = [ int(_partsize) for _partsize in partsize_l ]
    boot_size = partsize_l[0]
    swap_size = partsize_l[1]
    scratch_size = partsize_l[2]
    root_size = partsize_l[3]

    # note we set partition #0 as boot
    cmdline = """parted -a optimal -ms %(device)s unit GiB \
mklabel gpt \
mkpart primary fat32 0%% %(boot_size)s \
set 1 boot on \
mkpart primary linux-swap %(boot_size)s %(swap_end)s \
mkpart primary ext4 %(swap_end)s %(scratch_end)s \
""" % dict(
    device = device,
    boot_size = boot_size,
    swap_end = boot_size + swap_size,
    scratch_end = boot_size + swap_size + scratch_size,
)
    offset = boot_size + swap_size + scratch_size
    root_devs = []	# collect the root devices
    pid = 4
    while offset + root_size < size_gb:
        cmdline += ' mkpart primary ext4 %d %d' % (offset, offset + root_size)
        offset += root_size
        root_devs.append(device_basename + target.kws['p_prefix']
                         + "%d" % pid)
        pid += 1

    target.shell.run(cmdline)
    # Now set the root device information, so we can pick stuff to
    # format quick
    for root_dev in root_devs:
        target.property_set('pos_root_' + root_dev, "EMPTY")

    # Re-read partition tables
    target.shell.run('partprobe %s' % device)

    # now format filesystems
    #
    # note we only format the system boot partition (1), the linux
    # swap(2) and the linux scratch space (3)
    boot_dev = device + target.kws['p_prefix'] + "1"
    swap_dev = device + target.kws['p_prefix'] + "2"
    home_dev = device + target.kws['p_prefix'] + "3"
    # Note: use FAT vs VFAT: vfat name translation creates issues when
    # doing long file names; fat32 does not have that problem.
    target.shell.run("mkfs.fat -F32 -n TCF-BOOT " + boot_dev)
    target.shell.run("mkswap -L tcf-swap " + swap_dev)
    target.shell.run("mkfs.ext4 -FqL tcf-scratch " + home_dev)

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
        lecl.append(lec)
        target.report_info("Loader Entry found: %s" % lec, dlevel = 1)
    if len(lecl) > 1:
        raise tcfl.tc.blocked_e(
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
    os_release = tcfl.tl.linux_os_release_get(target, prefix = "/mnt")
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
        raise tcfl.tc.blocked_e(
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

def _efibootmgr_setup(target):
    # Now make sure the new entry is after IPv4, as we use IPv4's boot
    # to redirect to the POS or to localboot
    #
    # $ efibootmgr
    # BootCurrent: 0006
    # Timeout: 0 seconds
    # BootOrder: 0000,0006,0004,0005
    # Boot0000* Linux Boot Manager
    # Boot0004* UEFI : Built-in EFI Shell
    # Boot0005* UEFI : LAN : IP6 Intel(R) Ethernet Connection (3) I218-V
    # Boot0006* UEFI : LAN : IP4 Intel(R) Ethernet Connection (3) I218-V
    output = target.shell.run("efibootmgr", output = True)
    bo_regex = re.compile(r"^BootOrder: "
                          "(?P<boot_order>([a-fA-F0-9]{4},)*[a-fA-F0-9]{4})$",
                          re.MULTILINE)
    # this one we added before calling this function with "bootctl
    # install"
    lbm_regex = re.compile(r"^Boot(?P<entry>[a-fA-F0-9]{4})\*? "
                           "(?P<name>Linux Boot Manager$)", re.MULTILINE)
    ipv4_regex = re.compile(r"^Boot(?P<entry>[a-fA-F0-9]{4})\*? "
                            # PXEv4 is QEMU's UEFI
                            # .*IPv4 are some NUCs I've found
                            "(?P<name>(UEFI PXEv4|.*IPv?4).*$)", re.MULTILINE)
    bom_m = bo_regex.search(output)
    if bom_m:
        boot_order = bom_m.groupdict()['boot_order'].split(",")
    else:
        boot_order = []
    target.report_info("current boot_order: %s" % boot_order)
    lbm_m = lbm_regex.search(output)
    if not lbm_m:
        raise tcfl.tc.blocked_e(
            "Cannot find 'Linux Boot Manager' EFI boot entry",
            dict(target = target, output = output))
    lbm = lbm_m.groupdict()['entry']
    lbm_name = lbm_m.groupdict()['name']

    ipv4_m = ipv4_regex.search(output)
    if not ipv4_m:
        raise tcfl.tc.blocked_e(
            # FIXME: improve message to be more helpful and point to docz
            "Cannot find IPv4 boot entry, enable manually",
            dict(target = target, output = output))
    ipv4 = ipv4_m.groupdict()['entry']
    ipv4_name = ipv4_m.groupdict()['name']

    # the first to boot has to be ipv4, then linux boot manager

    if lbm in boot_order:
        boot_order.remove(lbm)
    if ipv4 in boot_order:
        boot_order.remove(ipv4)
    boot_order = [ ipv4, lbm ] + boot_order
    target.report_info("Changing boot order to %s followed by %s"
                       % (ipv4_name, lbm_name))
    target.shell.run("efibootmgr -o " + ",".join(boot_order))
    # Next time we reboot we want to go straight to our deployment
    target.report_info("Setting next boot to be Linux Boot Manager")
    target.shell.run("efibootmgr -n " + lbm)


def boot_config(target, root_part_dev, image,
                linux_kernel_file = None,
                linux_initrd_file = None,
                linux_options = None):
    boot_dev = target.kws['pos_boot_dev']
    # were we have mounted the root partition
    root_dir = "/mnt"

    # If we didn't specify a Linux kernel, try to guess
    if linux_kernel_file == None:
        linux_kernel_file, _linux_initrd_file, _linux_options = \
            _linux_boot_guess(target, image)
    if linux_initrd_file == None:
        linux_initrd_file = _linux_initrd_file
    if linux_options == None:
        linux_options = _linux_options
    if linux_kernel_file == None:
        raise tcfl.tc.blocked_e(
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

    # /boot EFI system partition is always /dev/DEVNAME1 (first
    # partition), we partition like that
    # FIXME: we shouldn't harcode this
    boot_part_dev = boot_dev + target.kws['p_prefix'] + "1"

    kws = dict(
        boot_dev = boot_dev,
        boot_part_dev = boot_part_dev,
        root_part_dev = root_part_dev,
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
            "root": "/dev/%(root_part_dev)s" % kws
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
    target.shell.run("mkfs.fat -F32 /dev/%(boot_part_dev)s" % kws)
    target.shell.run("sync")
    target.shell.run("mount /dev/%(boot_part_dev)s /boot" % kws)
    target.shell.run("mkdir -p /boot/loader/entries")
    target.shell.run("""\
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
    """)

    # Now copy all the files needed to boot to the root of the EFI
    # system partition mounted in /boot; remember they are in /mnt/,
    # our root partition
    # use dd instead of cp, it won't ask to override and such
    target.shell.run("dd if=/mnt/boot/%(linux_kernel_file)s "
                     "of=/boot/%(linux_kernel_file_basename)s" % kws)
    # remember paths to the bootloader are relative to /boot
    target.shell.run("""\
cat <<EOF > /boot/loader/entries/tcf-boot.conf
title TCF-driven local boot
linux /%(linux_kernel_file_basename)s
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
    target.shell.run("""\
cat <<EOF >> /boot/loader/entries/tcf-boot.conf
options %(linux_options)s
EOF
""" % kws)

    # Cleanup previous install of the bootloader, setup new one
    # we don't care if we fail to remote, maybe not yet installed
    target.shell.run("bootctl remove || true")
    target.shell.run("bootctl install")

    # Now mess with the EFIbootmgr
    # FIXME: make this a function and a configuration option (if the
    # target does efibootmgr)
    _efibootmgr_setup(target)
    # umount only if things go well
    # Shall we try to unmount in case of error? nope, we are going to
    # have to redo the whole thing anyway, so do not touch it, in case
    # we are jumping in for manual debugging
    target.shell.run("umount /dev/%(boot_part_dev)s" % kws)


def _entry_to_tuple(i):
    distro = ""
    spin = ""
    version = ""
    pl = ""
    arch = ""
    il = i.split(":")
    if len(il) > 0:
        distro = il[0]
    if len(il) > 1:
        spin = il[1]
    if len(il) > 2:
        version = il[2]
    if len(il) > 3:
        pl = il[3]
    if len(il) > 4:
        arch = il[4]
    return distro, spin, version, pl, arch


def _seed_match(lp, goal):
    """
    Given two image/seed specifications, return the most similar one

    >>> lp = {
    >>>     'part1': 'clear:live:25550::x86-64',
    >>>     'part2': 'fedora:workstation:28::x86',
    >>>     'part3': 'rtk::91',
    >>>     'part4': 'rtk::90',
    >>>     'part5': 'rtk::114',
    >>> }
    >>> _seed_match(lp, "rtk::112")
    >>> ('part5', 0.933333333333, 'rtk::114')

    """

    goall = _entry_to_tuple(goal)
    scores = {}
    for part_name, seed in lp.iteritems():
        score = 0
        seedl = _entry_to_tuple(str(seed))

        if seedl[0] == goall[0]:
            # At least we want a distribution match for it to be
            # considered
            scores[part_name] = Levenshtein.seqratio(goall, seedl)
        else:
            scores[part_name] = 0
    if scores:
        selected, score = max(scores.iteritems(), key = operator.itemgetter(1))
        return selected, score, lp[selected]
    return None, 0, None


def image_list_from_rsync_output(output):
    imagel = []
    # drwxrwxr-x          4,096 2018/10/19 00:41:04 .
    # drwxr-xr-x          4,096 2018/10/11 06:24:44 clear:live:25550
    # dr-xr-xr-x          4,096 2018/04/24 23:10:02 fedora:cloud-base-x86-64:28
    # drwxr-xr-x          4,096 2018/10/11 20:52:34 rtk::114
    # ...
    # so we parse for 5 fields, take last
    for line in output.splitlines():
        tokens = line.split(None, 5)
        if len(tokens) != 5:
            continue
        image = tokens[4]
        if not ':' in image:
            continue
        imagel.append(_entry_to_tuple(image))
    return imagel


def image_select_best(image, available_images, arch_default):
    image_spec = _entry_to_tuple(image)

    arch = image_spec[4]
    if arch == "":
        arch = arch_default

    # filter which images have arch or no arch spec
    available_images = filter(lambda x: x[4] == arch, available_images)
    if not available_images:
        raise tcfl.tc.blocked_e(
            "can't find image for architecture %s "
            "in list of available image" % arch,
            dict(images_available = \
                 "\n".join([ ":".join(i) for i in available_images ]))
        )

    # filter first based on the distro (first field)
    distro = image_spec[0]
    if distro == "":
        distro_images = available_images
    else:
        distro_images = filter(lambda x: x[0] == distro, available_images)

    # now filter based on the distro spin; if none, well, pick one at random
    spin = image_spec[1]
    if spin == "":
        spin_images = distro_images
    else:
        spin_images = filter(lambda x: x[1] == spin, distro_images)

    if not spin_images:
        raise tcfl.tc.blocked_e(
            "can't find match for image %s on available images" % image,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in available_images ]))
        )

    # now filter based on version -- rules change here -- if there is
    # no version specified, pick what seems to be the most recent
    # (highest)
    version = image_spec[2]
    if version == "":
        versions = sorted([
            (distutils.version.LooseVersion(i[2]) if i[2] != ""
             else distutils.version.LooseVersion('0'))
            for i in spin_images
        ])
        version = versions[-1]
    else:
        version = distutils.version.LooseVersion(version)
    version_images = filter(
        lambda x: (
            distutils.version.LooseVersion(x[2] if x[2] != "" else '0')
            == version
        ),
        spin_images)
    if not version_images:
        raise tcfl.tc.blocked_e(
            "can't find image match for version %s "
            "in list of available images" % version,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in version_images ]))
        )

    # now filter based on subversion -- rules change here -- if there is
    # no subversion specified, pick what seems to be the most recent
    # (highest)
    subversion = image_spec[3]
    if subversion == "":
        subversions = sorted([
            (distutils.version.LooseVersion(i[3]) if i[3] != ""
             else distutils.version.LooseVersion('0'))
            for i in version_images
        ])
        subversion = subversions[-1]
    else:
        subversion = distutils.version.LooseVersion(subversion)
    subversion_images = filter(
        lambda x: (
            distutils.version.LooseVersion(x[3] if x[3] != "" else '0')
            == subversion
        ),
        version_images)
    if not subversion_images:
        raise tcfl.tc.blocked_e(
            "can't find image match for sub-version %s "
            "in list of available images" % subversion,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in subversion_images ]))
        )
    # we might have multiple image choices if distro or live image
    # weren't specified, so pick one
    return random.choice(subversion_images)


def _root_part_select(target, image, boot_dev, root_part_dev):
    # what is out root device?
    if root_part_dev != None:
        # A root partition device was given, let's do some basic
        # checks, as it if it is NAME it needs to be in the target's
        # tags/properties on pos_root_NAME
        assert isinstance(root_part_dev, basestring), \
            'root_part_dev must be a string'
        if not 'pos_root_' + root_part_dev in target.kws:
            # specified a root partition that is not known
            raise tcfl.tc.blocked_e(
                'POS: asked to use root partition "%s", which is unknown; '
                '(the target contains no "pos_root_%s" tag/property)'
                % (root_part_dev, root_part_dev),
                dict(target = target))
        return root_part_dev

    # Gave a None partition, means pick our own based on a guess. We
    # know what image we want to install, so we will scan the all the
    # target's root partitions (defined in tags/properties
    # pos_root_XYZ) to see who has installed the most similar thing to
    # image and use that (so it is faster to rsync it).

    partl = {}
    empties = []
    # refresh target information FIXME: need a better method
    target.rt = target.rtb.rest_tb_target_update(target.id)
    for tag, value in target.rt.iteritems():
        if not tag.startswith("pos_root_"):
            continue
        dev_basename = tag.replace("pos_root_", "")
        dev_name = "/dev/" + dev_basename
        if value == 'EMPTY':
            empties.append(dev_name)
        else:
            partl[dev_name] = value
    target.report_info("POS: %s: empty partitions: %s"
                       % (boot_dev, " ".join(empties)), dlevel = 2)
    target.report_info("POS: %s: imaged partitions: %s"
                       % (boot_dev,
                          " ".join([ i[0] + "|" + i[1]
                                     for i in partl.items() ])),
                       dlevel = 2)
    if not partl and not empties:
        # there were no pos_root_XYZ entries, so that means we are not
        # initialized properly, reinit
        target.report_info("POS: %s: no root partitions known, uninitialized?"
                           % boot_dev, dlevel = 1)
        return None

    # We don't have empties to spare, so choose one that is the most
    # similar, to improve the transfer rate
    #
    # This prolly can be made more efficient, like collect least-used
    # partition data? to avoid the situation where two clients keep
    # imaging over each other when they could have two separate images
    root_part_dev, score, seed = _seed_match(partl, image)
    if score == 0:
        # none is a good match, find an empty one...if there are
        # non empty, just any
        if empties:
            root_part_dev = random.choice(empties)
            target.report_info("POS: picked up empty root partition %s"
                               % root_part_dev, dlevel = 2)
        else:
            root_part_dev = random.choice(partl.keys())
            target.report_info(
                "POS: picked up random partition %s, because none of the "
                "existing installed ones was a good match and there "
                "are no empty ones" % root_part_dev, dlevel = 2)
    else:
        target.report_info("POS: picked up root partition %s for %s "
                           "due to a %.02f similarity with %s"
                           % (root_part_dev, seed, score, seed), dlevel = 2)
    return root_part_dev

def deploy_image(ic, target, image,
                 boot_dev = None, root_part_dev = None,
                 partitioning_fn = partition,
                 extra_deploy_fns = None,
                 # mkfs has to have -F to avoid it asking questions
                 mkfs_cmd = "mkfs.ext4 -Fj %(root_part_dev)s",
                 pos_prompt = None,
                 # plenty to boot to an nfsroot, hopefully
                 timeout = 60):

    """Deploy an image to a target using the Provisioning OS

    :param tcfl.tc.tc_c ic: interconnect off which we are booting the
      Provisioning OS and to which ``target`` is connected.

    :param tcfl.tc.tc_c target: target which we are provisioning.

    :param str image: name of an image available in an rsync server
      specified in the interconnect's ``pos_rsync_server`` tag. Each
      image is specified as ``IMAGE:SPIN:VERSION:SUBVERSION:ARCH``, e.g:

      - fedora:workstation:28::x86_64
      - clear:live:25550::x86_64
      - yocto:core-image-minimal:2.5.1::x86

      Note that you can specify a partial image name and the closest
      match to it will be selected. From the previous example, asking
      for *fedora* would auto select *fedora:workstation:28::x86_64*
      assuming the target supports the *x86_64* target.

    :param str boot_dev: (optional) which is the boot device to use,
      where the boot loader needs to be installed in a boot
      partition. e.g.: ``sda`` for */dev/sda* or ``mmcblk01`` for
      */dev/mmcblk01*.

      Defaults to the value of the ``pos_boot_dev`` tag.

    :param str root_part_dev: (optional) which is the device to use
      for the root partition. e.g: ``mmcblk0p4`` for
      */dev/mmcblk0p4* or ``hda5`` for */dev/hda5*.

      If not specified, the system will pick up one from all the
      different root partitions that are available, trying to select
      the one that has the most similar to what we are installing to
      minimize the install time.

    :param extra_deploy_fns: list of functions to call after the
      image has been deployed. e.g.:

      >>> def deploy_linux_kernel(ic, target, kws, kernel_file = None):
      >>>     ...

      the function will be passed keywords which contain values found
      out during this execution

    :returns str: name of the image that was deployed (in case it was
      guessed)

    FIXME:
     - fix to autologing serial console?
     - do a couple retries if fails?
     - increase in property bd.stats.client.sos_boot_failures and
       bd.stats.client.sos_boot_count (to get a baseline)
     - tag bd.stats.last_reset to DATE

    Note: you might want the interconnect power cycled

    """
    assert isinstance(ic, tcfl.tc.target_c), \
        "ic must be an instance of tcfl.tc.target_c, but found %s" \
        % type(ic).__name__
    assert isinstance(target, tcfl.tc.target_c), \
        "target must be an instance of tcfl.tc.target_c, but found %s" \
        % type(target).__name__
    assert isinstance(image, basestring)

    testcase = target.testcase

    # What is our boot device?
    if boot_dev:
        assert isinstance(boot_dev, basestring), 'boot_dev must be a string'
        target.report_info("POS: boot device %s (from arguments)"
                           % boot_dev)
    else:
        boot_dev = target.kws.get('pos_boot_dev', None)
        if boot_dev == None:
            raise tcfl.tc.blocked_e(
                "Can't guess boot_dev (no `pos_boot_dev` tag available)",
                { 'target': target } )
        target.report_info("POS: boot device %s (from pos_boot_dev tag)"
                           % boot_dev)
    boot_dev = "/dev/" + boot_dev
    # HACK: /dev/[hs]d* do partitions as /dev/[hs]dN, where as mmc and
    # friends add /dev/mmcWHATEVERpN. Seriously...
    if boot_dev.startswith("/dev/hd") \
       or boot_dev.startswith("/dev/sd") \
       or boot_dev.startswith("/dev/vd"):
        target.kw_set('p_prefix', "")
    else:
        target.kw_set('p_prefix', "p")


    # FIXME: check ic is powered on?
    for tries in range(3):
        target.report_info("rebooting into POS for flashing [%d/3]" % tries)
        target.property_set("pos_mode", "pxe")
        target.power.cycle()

        # Sequence for TCF-live based on Fedora
        if pos_prompt:
            target.shell.linux_shell_prompt_regex = pos_prompt
        try:
            target.shell.up(timeout = timeout)
        except tcfl.tc.error_e as e:
            outputf = e.attachments_get().get('console output', None)
            if outputf:
                output = open(outputf.name).read()
            if output == None or output == "" or output == "\x00":
                target.report_error("POS: no console output, retrying")
                continue
            target.report_error("POS: unexpected console output")
            raise
        break
    else:
        raise tcfl.tc.blocked_e(
            "POS: tried too many times to boot, without signs of life",
            { "console output": target.console.read(), 'target': target })

    # Ok, we might be accessing the target here to repartition and
    # such, so let's first select a root partition
    if target.property_get('pos_repartition'):
        # Need to reinit the partition table (we were told to by
        # setting pos_repartition to anything
        target.report_info("POS: repartitioning per pos_repartition property")
        partitioning_fn(target, boot_dev)
        target.property_set('pos_repartition', None)

    for tries in range(3):
        target.report_info("POS: guessing partition device [%d/3] "
                           "(defaulting to %s)" % (tries, root_part_dev))
        root_part_dev = _root_part_select(target, image,
                                          boot_dev, root_part_dev)
        if root_part_dev != None:
            target.report_info("POS: will use %s for root partition"
                               % root_part_dev)
            break
        # we couldn't find a root partition device, which means the
        # thing is trashed
        target.report_info("POS: repartitioning because couldn't find "
                           "root partitions")
        partitioning_fn(target, boot_dev)
    else:
        output = target.shell.run("fdisk -l " + boot_dev, output = True)
        raise tcfl.tc.blocked_e(
            "Tried too much to reinitialize the partition table to "
            "pick up a root partition? is there enough space to "
            "create root partitions?",
            dict(target = target, fdisk_l = output,
                 partsizes = target.kws.get('pos_partsizes', None)))

    root_part_dev_base = os.path.basename(root_part_dev)
    kws = dict(
        rsync_server = ic.kws['pos_rsync_server'],
        image = image,
        boot_dev = boot_dev,
        root_part_dev = root_part_dev,
        root_part_dev_base = root_part_dev_base,
    )
    kws.update(target.kws)

    # FIXME: verify root partitioning is the right one and recover if
    # not
    try:
        # FIXME: act on failing, just reformat and retry, then
        # bail out on failure
        for try_count in range(3):
            target.report_info("POS: mounting root partition %s onto /mnt "
                               "to image [%d/3]" % (root_part_dev, try_count))
            # don't let it fail or it will raise an exception, so we
            # print FAILED in that case to look for stuff; note the
            # double apostrophe trick so the regex finder doens't trip
            # on the command
            output = target.shell.run(
                "mount %(root_part_dev)s /mnt || echo FAI''LED" % kws,
                output = True)
            # What did we get?
            if 'FAILED' in output:
                if 'mount: /mnt: special device ' + root_part_dev \
                   + ' does not exist.' in output:
                    partitioning_fn(target, boot_dev)
                elif 'mount: /mnt: wrong fs type, bad option, ' \
                   'bad superblock on ' + root_part_dev + ', missing ' \
                   'codepage or helper program, or other error.' in output:
                    # ok, this means probably the partitions are not
                    # formatted; FIXME: support other filesystemmakeing?
                    target.report_info(
                        "POS: formating root partition %s with `%s`"
                        % (root_part_dev, mkfs_cmd % kws))
                    target.shell.run(mkfs_cmd % kws)
                else:
                    raise tcfl.tc.blocked_e(
                        "POS: Can't recover unknown error condition: %s"
                        % output, dict(target = target, output = output))
            else:
                target.report_info("POS: mounted %s onto /mnt to image"
                                   % root_part_dev)
                break	# it worked, we are done
            # fall through, retry
        else:
            raise tcfl.tc.blocked_e(
                "POS: Tried to mount too many times and failed",
                dict(target = target))

        if image:
            original_timeout = testcase.tls.expecter.timeout
            try:
                image_list_output = target.shell.run(
                    "rsync %(rsync_server)s/" % kws, output = True)
                images_available = image_list_from_rsync_output(
                    image_list_output)
                # Do we have that image? autocomplete missing fields
                # and get us a good match if so
                image_final = image_select_best(image, images_available,
                                                target.bsp_model)
                kws['image'] = ":".join(image_final)
                target.report_info("POS: rsyncing %(image)s from "
                                   "%(rsync_server)s to /mnt" % kws,
                                   dlevel = -1)

                testcase.tls.expecter.timeout = 800
                target.shell.run(
                    "time rsync -aAX --numeric-ids --delete "
                    "--exclude='/persistent.tcf.d/*' "
                    "%(rsync_server)s/%(image)s/. /mnt/."
                    % kws)
                target.property_set('pos_root_' + root_part_dev_base, image)
            finally:
                testcase.tls.expecter.timeout = original_timeout
            target.report_info("POS: rsynced %(image)s from "
                               "%(rsync_server)s to /mnt" % kws)

            # did the user provide an extra function to deploy stuff?
            if extra_deploy_fns:
                target_rsyncd_start(ic, target)

                for extra_deploy_fn in extra_deploy_fns:
                    target.report_info("POS: running extra deploy fn %s"
                                       % extra_deploy_fn, dlevel = 2)
                    extra_deploy_fn(ic, target, kws)
                target_rsyncd_stop(target)

            # Configure the bootloader
            #
            # We do it by hand -- with shell commands, so it is
            # easy to reproduce by a user typing them

            # FIXME: we are EFI only for now, way easier
            # Make sure we have all the entries for systemd-loader
            target.report_info("POS: configuring bootloader")
            boot_config(target, root_part_dev_base, image_final)
        target.shell.run("sync")
        # Kill any processes left over here
        target.shell.run("which lsof && kill -9 `lsof -Fp  /home | sed -n '/^p/{s/^p//;p}'`")
        # leave /mnt
        target.shell.run("cd /")
        target.shell.run("umount /mnt")
        # Now setup the local boot loader to boot off that
        target.property_set("pos_mode", "local")
    except Exception as e:
        target.report_info("BUG? exception %s: %s %s" %
                           (type(e).__name__, e, traceback.format_exc()))
        raise
    finally:
        # don't fail if this fails, as it'd trigger another exception
        # and hide whatever happened that make us fail. Just make a
        # good hearted attempt at cleaning up
        target.shell.run("umount -l /mnt || true")

    target.report_info("POS: deployed %(image)s to %(root_part_dev)s" % kws)
    return kws['image']


def mk_persistent_tcf_d(target, subdirs = None):
    if subdirs == None:
        dirs = [ '/mnt/persistent.tcf.d' ]
    else:
        dirs = [ '/mnt/persistent.tcf.d/' + subdir for subdir in subdirs ]

    # just create / recreate all the thirs
    target.shell.run('mkdir -p ' + " ".join(dirs))

    # Ensure there is a README -- this is slow, so don't do it if
    # already there
    output = target.shell.run(
        'test -f /mnt/persistent.tcf.d/README || echo N""O' ,
        output = True)
    if 'NO' in output:
        target.shell.run("""\
cat <<EOF > /mnt/persistent.tcf.d/README
This directory has been created by TCF's Provisioning OS to store files to
be provisioned in the root file system.

When flashing a new image to this partition, the contents in this tree
will not be removed/replaced. It is then faster to rsync things in
from the client machine.
EOF""")


def deploy_linux_kernel(ic, target, _kws):
    """Deploy a linux kernel tree in the local machine to the target's
    root filesystem

    This is normally given to :func:`tcfl.pos.deploy_image` as:

    >>> target.kw_set("pos_deploy_linux_kernel", SOMELOCALLOCATION)
    >>> tcfl.pos.deploy_image(ic, target, IMAGENAME,
    >>>                       extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

    as it expects ``kws['pos_deploy_linux_kernel']`` which points to a
    local directory in the form::

      - boot/*
      - lib/modules/KVER/*

    all those will be rsynced to the target's persistent root area
    (for speed) and from there to the root filesystem's /boot and
    /lib/modules. Anything else in the ``/boot/`` and
    ``/lib/modules/`` directories will be replaced with what comes
    from the *kernel tree*.

    **Low level details**

    When the target's image has been flashed in place,
    :func:`tcfl.pos.deploy_image` is asked to call this function.

    The client will rsync the tree from the local machine to the
    persistent space in the target's selected root partition (which is
    not overriden by :func:`tcfl.pos.deploy_image`). For that it needs
    to establish a TCPv4 tunnel to the target; the target is then made
    to serve rsync over that tunnel for the client to transfer the
    tree.

    The tree is first transferred to the persistent space so if there
    are multiple flashings done for the same versions, then the
    transfers will be way faster in the subsequent times.

    After there, the client will have the target rsync from the
    persistant space to the final destination (which is overriden by
    :func:`tcfl.pos.deploy_image`).

    """
    if not '' in _kws:
        target.report_info("not deploying linux kernel because "
                           "*pos_deploy_linux_kernel_tree* keyword "
                           "has not been set for the target", dlevel = 2)
        return
    target.report_info("deploying linux kernel")

    # The target is running the Provisioning OS
    # Start rsync in the target to receive the stuff we want to send to it
    # folders that have root-only weird permissions; detach it
    target.shell.run("""\
cat > /tmp/rsync.conf <<EOF
[rootfs]
use chroot = true
path = /mnt/
read only = false
timeout = 60
uid = root
gid = root
EOF""")
    target.shell.run("rsync --port 3000 --daemon --no-detach --config /tmp/rsync.conf &")
    # rsync makes no pids and we might not have killall in the POS
    target.shell.run("echo $! > /tmp/rsync.pid")
    target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
    target.kw_set('rsync_port', target.tunnel.add(3000))
    target.kw_set('rsync_server', target.rtb.parsed_url.hostname)
    # Now we rsync from here (clienting) to the target (serving)
    # because heck no we are not making this test runner the
    # server so we can open up to attack from the target.
    #
    # Note we sync with --delete to remove anything from /boot
    # and /lib/modules/. we are not sending; this allows later the
    # boot configuration code to find only one kernel and boot
    # that.
    target.report_info("rsyncing boot/ to target")
    # make sure we have spots in the persistent are where we'll put
    # out stuff so it is faster to upload repeatedly
    mk_persistent_tcf_d(target, [ 'boot', 'lib/modules' ])

    # upload the kernel to the persistent area
    target.shcmd_local(
        "time rsync -aAX --numeric-ids --delete --port %(rsync_port)s "
        "-vv %(pos_deploy_linux_kernel_tree)s/boot/. "
        "%(rsync_server)s::rootfs/persistent.tcf.d/boot/.")
    target.testcase._targets_active()
    target.report_info("rsyncing lib/modules to target")
    target.shcmd_local(
        "time rsync -aAX --numeric-ids --delete --port %(rsync_port)s "
        "-vv %(pos_deploy_linux_kernel_tree)s/lib/modules/. "
        "%(rsync_server)s::rootfs/persistent.tcf.d/lib/modules/.")
    # remember we started rsync in the target? we can kill it now
    target.shell.run("kill -9 $(cat /tmp/rsync.pid)")
    # Now move it from the persistent area to its final location,
    target.testcase._targets_active()
    target.shell.run(
        "rsync -vvaAX --delete /mnt/persistent.tcf.d/boot/. /mnt/boot/.")
    target.testcase._targets_active()
    target.shell.run(
        "rsync -vvaAX --delete /mnt/persistent.tcf.d/lib/modules/. "
        "/mnt/lib/modules/.")
    target.testcase._targets_active()
    target.report_pass("linux kernel transferred")
