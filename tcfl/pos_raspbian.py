#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# FIXME:
#
# - command line method to discover installed capabiltiies; print
#   each's __doc__
#
# - do not pass device--each function should gather it from target's
#   tags
"""
.. _pos_raspbian:

Provisioning OS: client side support for provisioning Raspberry PI
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


"""
import os

import tcfl.pos

# FIXME: deprecate that _device
def _partition_p12(target):
    # we assume we are going to work on the boot device
    device_basename = target.kws['pos_boot_dev']
    device = "/dev/" + device_basename
    target.shell.run('swapoff -a || true')	    # in case we autoswapped

    # find device size (FIXME: Linux specific)
    dev_info = target.pos.fsinfo_get_block(device_basename)
    size_gb = int(dev_info['size']) / 1024 / 1024 / 1024
    target.report_info("POS: %s is %d GiB in size" % (device, size_gb),
                       dlevel = 2)

    boot_size = 256

    # note we set partition #0 as boot
    # Note we set the name of the boot partition; we use that later to
    # detect the disk has a partitioning scheme we support. See above.
    cmdline = """\
parted -a optimal -ms %(device)s unit MiB \
mklabel msdos \
mkpart primary fat32 0%% %(boot_size)s \
set 1 boot on \
mkpart primary ext4 %(boot_size)s 100%% \
""" % dict(device = device, boot_size = boot_size)

    target.shell.run(cmdline)
    target.pos.fsinfo_read(p1_key = 'name', p1_value = 'mmcblk0p1')

    # now format filesystems
    #
    # note we only format the system boot partition (1), the linux
    # swap(2) and the linux scratch space (3)
    boot_dev = device + target.kws['p_prefix'] + "1"
    root_dev = device + target.kws['p_prefix'] + "2"
    # Note: use FAT vs VFAT: vfat name translation creates issues when
    # doing long file names; fat32 does not have that problem.
    target.shell.run("mkfs.fat -F32 -n boot " + boot_dev)
    target.shell.run("mkfs.ext4 -FqL rootfs " + root_dev)


def _mkfs(target, dev, fstype, mkfs_opts):
    # FIXME: move to pos.py
    target.report_info("POS: formatting %s (mkfs.%s %s)"
                       % (dev, fstype, mkfs_opts), dlevel = 1)
    target.shell.run("mkfs.%s %s %s" % (fstype, mkfs_opts, dev))
    target.report_info("POS: formatted rootfs %s as %s" % (dev, fstype))

def _boot_config(_target, _boot_dev, _image):
    # nothing needed here, since all the boot happens driven by the
    # network
    pass

def _mount_fs(target, _image, boot_dev):
    """
    Mounts a dest partition in /mnt

    Possibly repartitions

    Rapsbian setup:

    - partition1 /boot ~256M
    - parititon2 /

    :returns: name of the root partition device
    """
    pos_reinitialize_force = True
    boot_dev_base = os.path.basename(boot_dev)
    child = target.pos.fsinfo_get_child_by_label(boot_dev_base,
                                                 "boot")
    if child:
        pos_reinitialize_force = False
    else:
        target.report_info("POS: repartitioning due to different"
                           " partition schema")

    pos_reinitialize = target.property_get("pos_reinitialize", False)
    if pos_reinitialize:
        target.report_info("POS: repartitioning per pos_reinitialize "
                           "property")
    if pos_reinitialize or pos_reinitialize_force:
        # Need to reinit the partition table (we were told to by
        # setting pos_repartition to anything or we didn't recognize
        # the existing partitioning scheme)
        _partition_p12(target)
        target.pos.fsinfo_read("mmcblk0p1", p1_key = "name")
        target.property_set('pos_reinitialize', None)

    root_part_dev = "/dev/mmcblk0p2"
    tcfl.pos.mount_root_part(target, root_part_dev, _partition_p12)
    # we don't mount /dev/mmcblk0p1 because the bootcode is quite
    # resilient and will over recover and refuse to NW boot again.
    return root_part_dev

tcfl.pos.capability_register('boot_config', 'raspberry_pi', _boot_config)
tcfl.pos.capability_register('mount_fs', 'raspbian', _mount_fs)
