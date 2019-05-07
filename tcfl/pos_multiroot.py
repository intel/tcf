#! /usr/bin/python2
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
"""
import operator
import os
import random
import re

import Levenshtein

import commonl
import pos
import tc

# FIXME: deprecate that _device
def _disk_partition(target):
    # we assume we are going to work on the boot device
    device_basename = target.kws['pos_boot_dev']
    device = "/dev/" + device_basename
    device_basename = os.path.basename(device)	    # /dev/BLAH -> BLAH
    target.shell.run('swapoff -a || true')	    # in case we autoswapped

    # find device size (FIXME: Linux specific)
    output = target.shell.run(
        'cat /sys/block/%s/size /sys/block/%s/queue/physical_block_size'
        % (device_basename, device_basename), output = True)
    regex = re.compile("^(?P<blocks>[0-9]+)\n"
                       "(?P<block_size>[0-9]+)$", re.MULTILINE)
    m = regex.search(output)
    if not m:
        raise tc.blocked_e(
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
    root_part_dev, score, seed = pos.image_seed_match(partl, image)
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

def _mkfs(target, dev, fstype, mkfs_opts):
    target.report_info("POS: formatting %s (mkfs.%s %s)"
                       % (dev, fstype, mkfs_opts), dlevel = 1)
    target.shell.run("mkfs.%s %s %s" % (fstype, mkfs_opts, dev))
    target.report_info("POS: formatted rootfs %s as %s" % (dev, fstype))

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
            target.pos._fsinfo_load()
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
    pos_reinitialize = target.property_get("pos_reinitialize", False)
    if pos_reinitialize:
        # Need to reinit the partition table (we were told to by
        # setting pos_repartition to anything
        target.report_info("POS: repartitioning per pos_reinitialize "
                           "property")
        for tag in target.rt.keys():
            # remove pos_root_*, as they don't apply anymore
            if tag.startswith("pos_root_"):
                target.property_set(tag, None)
        _disk_partition(target)
        target.property_set('pos_reinitialize', None)

    root_part_dev = _rootfs_guess(target, image, boot_dev)
    # save for other functions called later
    target.root_part_dev = root_part_dev
    root_part_dev_base = os.path.basename(root_part_dev)
    image_prev = target.property_get("pos_root_" + root_part_dev_base,
                                     "nothing")
    target.report_info("POS: will use %s for root partition (had %s before)"
                       % (root_part_dev, image_prev))

    # fsinfo looks like described in target.pos._fsinfo_load()
    dev_info = None
    for blockdevice in target.pos.fsinfo.get('blockdevices', []):
        for child in blockdevice.get('children', []):
            if child['name'] == root_part_dev_base:
                dev_info = child
    if dev_info == None:
        # it cannot be we might have to repartition because at this
        # point *we* have partitoned.
        raise tc.error_e(
            "Can't find information for root device %s in FSinfo array"
            % root_part_dev_base,
            dict(fsinfo = target.pos.fsinfo))

    # what format does it currently have?
    current_fstype = dev_info.get('fstype', 'ext4')

    # What format does it have to have?
    #
    # Ok, here we need to note that we can't have multiple root
    # filesystems with the same UUID or LABEL, so the image can't rely
    # on UUIDs
    #
    img_fss = target.pos.metadata.get('filesystems', {})
    if '/' in img_fss:
        # a common origin is ok because the YAML schema forces both
        # fstype and mkfs_opts to be specified
        origin = "image's /.tcf.metadata.yaml"
        fsdata = img_fss.get('/', {})
    else:
        origin = "defaults @" + commonl.origin_get(0)
        fsdata = {}
    fstype = fsdata.get('fstype', 'ext4')
    mkfs_opts = fsdata.get('mkfs_opts', '-Fj')

    # do they match?
    if fstype != current_fstype:
        target.report_info(
            "POS: reformatting %s because current format is '%s' and "
            "'%s' is needed (per %s)"
            % (root_part_dev, current_fstype, fstype, origin))
        _mkfs(target, root_part_dev, fstype, mkfs_opts)
    else:
        target.report_info(
            "POS: no need to reformat %s because current format is '%s' and "
            "'%s' is needed (per %s)"
            % (root_part_dev, current_fstype, fstype, origin), dlevel = 1)

    for try_count in range(3):
        target.report_info("POS: mounting root partition %s onto /mnt "
                           "to image [%d/3]" % (root_part_dev, try_count))

        # don't let it fail or it will raise an exception, so we
        # print FAILED in that case to look for stuff; note the
        # double apostrophe trick so the regex finder doens't trip
        # on the command
        output = target.shell.run(
            "mount %s /mnt || echo FAI''LED" % root_part_dev,
            output = True)
        # What did we get?
        if 'FAILED' in output:
            if 'special device ' + root_part_dev \
               + ' does not exist.' in output:
                _disk_partition(target)
            elif 'mount: /mnt: wrong fs type, bad option, ' \
               'bad superblock on ' + root_part_dev + ', missing ' \
               'codepage or helper program, or other error.' in output:
                # ok, this means probably the partitions are not
                # formatted; FIXME: support other filesystemmakeing?
                _mkfs(target, root_part_dev, fstype, mkfs_opts)
            else:
                raise tc.blocked_e(
                    "POS: Can't recover unknown error condition: %s"
                    % output, dict(target = target, output = output))
        else:
            target.report_info("POS: mounted %s onto /mnt to image"
                               % root_part_dev)
            return root_part_dev	# it worked, we are done
        # fall through, retry
    else:
        raise tc.blocked_e(
            "POS: Tried to mount too many times and failed",
            dict(target = target))
