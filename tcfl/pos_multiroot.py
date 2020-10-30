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
.. _pos_multiroot:

Provisioning OS: partitioning schema for multiple root FSs per device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Provisioning OS multiroot methodology partitions a system with
multiple root filesystems; different OSes are installed in each root
so it is fast to switch from one to another to run things in
automated fashion.

The key to the operation is that the server maintains a list of OS
images available to be rsynced to the target's filesystem. rsync can
copy straight or transmit only the minimum set of needed changes.

This also speeds up deployment of an OS to the root filesystems, as by
picking a root filesystem that has already installed one similar to
the one to be deployed (eg: a workstation vs a server version), the
amount of data to be transfered is greatly reduced.

Like this, the following scenario sorted from more to less data
transfer (and thus slowest to fastest operation):

- can install on an empty root filesystem: in this case a full
  installation is done

- can refresh an existing root fileystem to the destination: some
  things might be shared or the same and a partial transfer can be
  done; this might be the case when:

  - moving from a distro to another
  - moving from one version to another of the same distro
  - moving from one spin of one distro to another
  
- can update an existing root filesystem: in this case very little
  change is done and we are just verifying nothing was unduly
  modified.

.. _pos_multiroot_partsizes:

Partition Size specification
----------------------------

To simplify setup of targets, a string such as *"1:4:10:50"* is given
to denote the sizes of the different partitions:

- 1 GiB for /boot
- 4 GiB for swap
- 10 GiB for scratch (can be used for whatever the script wants, needs
  to be formated/initialized before use)
- 50 GiB for multiple root partitions (until the disk size is exhausted)

"""
import operator
import os
import pprint
import random
import re

import Levenshtein

from . import commonl
from . import pos
from . import tc

# FIXME: deprecate that _device
def _disk_partition(target):
    # we assume we are going to work on the boot device
    device_basename = target.kws['pos_boot_dev']
    device = "/dev/" + device_basename
    target.shell.run('swapoff -a || true')	    # in case we autoswapped

    # find device size (FIXME: Linux specific)
    dev_info = target.pos.fsinfo_get_block(device_basename)
    size_gb = int(dev_info['size']) / 1024 / 1024 / 1024
    target.report_info("POS: %s is %d GiB in size" % (device, size_gb),
                       dlevel = 2)

    partsizes = target.kws.get('pos_partsizes', None)
    if partsizes == None:
        raise tc.blocked_e(
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
    # Note we set the name of the boot partition; we use that later to
    # detect the disk has a partitioning scheme we support. See above.
    cmdline = """parted -a optimal -ms %(device)s unit GiB \
mklabel gpt \
mkpart primary fat32 0%% %(boot_size)s \
set 1 boot on \
name 1 %(boot_label_name)s \
mkpart primary linux-swap %(boot_size)s %(swap_end)s \
name 2 TCF-swap \
mkpart primary ext4 %(swap_end)s %(scratch_end)s \
name 3 TCF-scratch \
""" % dict(
    boot_label_name = target._boot_label_name,
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
    target.pos.fsinfo_read(target._boot_label_name)
    # format quick
    for root_dev in root_devs:
        target.property_set('pos_root_' + root_dev, "EMPTY")


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


def _rootfs_guess_by_image(target, image, boot_dev):

    # Gave a None partition, means pick our own based on a guess. We
    # know what image we want to install, so we will scan the all the
    # target's root partitions (defined in tags/properties
    # pos_root_XYZ) to see who has installed the most similar thing to
    # image and use that (so it is faster to rsync it).

    partl = {}
    empties = []
    # refresh target information FIXME: need a better method
    target.rt = target.rtb.rest_tb_target_update(target.id)
    for tag, value in target.rt.items():
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
                                     for i in list(partl.items()) ])),
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
    root_part_dev, score, check_empties, seed = pos.image_seed_match(partl, image)
    if score == 0:
        # none is a good match, find an empty one...if there are
        # non empty, just any
        if empties:
            root_part_dev = random.choice(empties)
            target.report_info("POS: picked up empty root partition %s"
                               % root_part_dev, dlevel = 2)
        else:
            root_part_dev = random.choice(list(partl.keys()))
            target.report_info(
                "POS: picked up random partition %s, because none of the "
                "existing installed ones was a good match and there "
                "are no empty ones" % root_part_dev, dlevel = 2)
    elif check_empties and empties:
        # This is for the case where image and seed have the same distro
        # but different spin. We want to check our luck if there is an empty
        # partition. If there isn't, we will just take the given one from
        # pos.image_seed_match.
        root_part_dev = random.choice(empties)
        target.report_info("POS: picked up empty root partition %s"
                            % root_part_dev, dlevel = 2)
    else:
        target.report_info("POS: picked up root partition %s for %s "
                           "due to a %.02f similarity with %s"
                           % (root_part_dev, seed, score, seed), dlevel = 2)
    return root_part_dev

def _rootfs_guess(target, image, boot_dev):
    reason = "unknown issue"
    for tries in range(3):
        tries += 1
        try:
            target.report_info("POS: guessing partition device [%d/3]" % tries)
            root_part_dev = _rootfs_guess_by_image(target, image, boot_dev)
            if root_part_dev != None:
                return root_part_dev
            # we couldn't find a root partition device, which means the
            # thing is trashed
            target.report_info("POS: repartitioning because couldn't find "
                               "root partitions")
            _disk_partition(target)
            target.pos.fsinfo_read(target._boot_label_name)
        except Exception as e:
            reason = str(e)
            if tries < 3:
                target.report_info("POS: failed to guess a root partition, "
                                   "retrying: %s" % reason)
                continue
            else:
                raise
    raise tc.blocked_e(
        "Tried too much to reinitialize the partition table to "
        "pick up a root partition? is there enough space to "
        "create root partitions?",
        dict(target = target, reason = reason,
             partsizes = target.kws.get('pos_partsizes', None)))


def mount_fs(target, image, boot_dev):
    """
    Boots a root filesystem on /mnt

    The partition used as a root filesystem is picked up based on the
    image that is going to be installed; we look for one that has the
    most similar image already installed and pick that.

    :returns: name of the root partition device
    """
    # does the disk have a partition scheme we recognize?
    pos_partsizes = target.rt['pos_partsizes']
    # the name we'll give to the boot partition; see
    # _disk_partition(); if we can't find it, we assume the things
    # needs to be repartitioned. Note it includes the sizes, so if we
    # change the sizes in the config it reformats automatically.  #
    # TCF-multiroot-NN:NN:NN:NN
    target._boot_label_name = "TCF-multiroot-" + pos_partsizes
    pos_reinitialize_force = True
    boot_dev_base = os.path.basename(boot_dev)
    child = target.pos.fsinfo_get_child_by_partlabel(boot_dev_base,
                                                     target._boot_label_name)
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
        for tag in list(target.rt.keys()):
            # remove pos_root_*, as they don't apply anymore
            if tag.startswith("pos_root_"):
                target.property_set(tag, None)
        _disk_partition(target)
        target.pos.fsinfo_read(target._boot_label_name)
        target.property_set('pos_reinitialize', None)

    root_part_dev = _rootfs_guess(target, image, boot_dev)
    # save for other functions called later
    target.root_part_dev = root_part_dev
    root_part_dev_base = os.path.basename(root_part_dev)
    image_prev = target.property_get("pos_root_" + root_part_dev_base,
                                     "nothing")
    target.report_info("POS: will use %s for root partition (had %s before)"
                       % (root_part_dev, image_prev))

    pos.mount_root_part(target, root_part_dev, _disk_partition)
    return root_part_dev
