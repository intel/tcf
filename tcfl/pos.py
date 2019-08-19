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

"""
Core Provisioning OS functionality
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
:ref:`POS setup <pos_setup>`.
"""

import collections
import inspect
import json
import logging
import operator
import os
import pprint
import random
import re
import traceback
import subprocess
import time

import distutils.version
import Levenshtein

import commonl
import commonl.yamll
import tc
import tl
from . import msgid_c

def image_spec_to_tuple(i):
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
        imagel.append(image_spec_to_tuple(image))
    return imagel


def image_select_best(image, available_images, target):
    arch_default = target.bsp_model
    image_spec = image_spec_to_tuple(image)

    arch = image_spec[4]
    if arch == "":
        arch = arch_default
    if arch == None or arch == "":
        image_spec2 = list(image_spec)
        image_spec2[4] = "ARCHITECTURE"
        raise tc.blocked_e(
            "no architecture specified (image %s), neither it could not be "
            "guessed from the target's BSP model (%s); try specifying the "
            "image as %s"
            % (image, target.bsp_model, ":".join(image_spec2)))
    target.report_info("POS: goal image spec: %s" % list(image_spec), dlevel = 2)

    for available_image in available_images:
        target.report_info("POS: available images: %s" % list(available_image),
                           dlevel = 2)
    # filter which images have arch or no arch spec
    available_images = filter(lambda x: x[4] == arch, available_images)
    if not available_images:
        raise tc.blocked_e(
            "can't find image for architecture %s "
            "in list of available image" % arch,
            dict(images_available = \
                 "\n".join([ ":".join(i) for i in available_images ]))
        )
    for available_image in available_images:
        target.report_info("POS: available images (filtered arch %s): %s"
                           % (arch, list(available_image)), dlevel = 2)

    # filter first based on the distro (first field)
    distro = image_spec[0]
    if distro == "":
        distro_images = available_images
    else:
        distro_images = filter(lambda x: x[0] == distro, available_images)
    for available_image in distro_images:
        target.report_info("POS: available images (filtered distro %s): %s"
                           % (distro, list(available_image)), dlevel = 2)

    # now filter based on the distro spin; if none, well, pick one at random
    spin = image_spec[1]
    if spin == "":
        spin_images = distro_images
    else:
        spin_images = filter(lambda x: x[1] == spin, distro_images)

    if not spin_images:
        raise tc.blocked_e(
            "can't find match for image %s on available images" % image,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in available_images ]))
        )
    for available_image in spin_images:
        target.report_info("POS: available images (filtered spin %s): %s"
                           % (spin, list(available_image)), dlevel = 2)

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
        raise tc.blocked_e(
            "can't find image match for version %s "
            "in list of available images" % version,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in version_images ]))
        )
    for available_image in version_images:
        target.report_info("POS: available images (filtered version %s): %s"
                           % (spin, list(available_image)), dlevel = 2)

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
        raise tc.blocked_e(
            "can't find image match for sub-version %s "
            "in list of available images" % subversion,
            dict(images_available =
                 "\n".join([ ":".join(i) for i in subversion_images ]))
        )
    for available_image in subversion_images:
        target.report_info("POS: available images (filtered subversion %s): %s"
                           % (spin, list(available_image)), dlevel = 2)
    # we might have multiple image choices if distro or live image
    # weren't specified, so pick one
    return random.choice(subversion_images)

# FIXME: what I don't like about this is that we have no info on the
# interconnect -- this must require it?
def target_power_cycle_to_pos_pxe(target):
    target.report_info("POS: setting target to PXE boot Provisioning OS")
    target.property_set("pos_mode", "pxe")
    target.power.cycle()
    # Now setup the local boot loader to boot off that
    target.property_set("pos_mode", "local")

# FIXME: what I don't like about this is that we have no info on the
# interconnect -- this must require it?
def target_power_cycle_to_normal_pxe(target):
    target.report_info("POS: setting target not to PXE boot Provisioning OS")
    target.property_set("pos_mode", "local")
    target.power.cycle()

#: Name of the directory created in the target's root filesystem to
#: cache test content
#:
#: This is maintained by the provisioning process, althought it might
#: be cleaned up to make room.
persistent_tcf_d = '/persistent.tcf.d'

def mk_persistent_tcf_d(target, subdirs = None):
    if subdirs == None:
        dirs = [ '/mnt' + persistent_tcf_d ]
    else:
        dirs = [ '/mnt' + persistent_tcf_d + subdir for subdir in subdirs ]

    # just create / recreate all the thirs
    target.shell.run('mkdir -p ' + " ".join(dirs))

    # Ensure there is a README -- this is slow, so don't do it if
    # already there
    output = target.shell.run(
        'test -f /mnt' + persistent_tcf_d + '/README || echo N""O' ,
        output = True)
    if 'NO' in output:
        target.shell.run("""\
cat <<EOF > /mnt%s/README
This directory has been created by TCF's Provisioning OS to store files to
be provisioned in the root file system.

When flashing a new image to this partition, the contents in this tree
will not be removed/replaced. It is then faster to rsync things in
from the client machine.
EOF""" % persistent_tcf_d)

def deploy_linux_kernel(ic, target, _kws):
    """Deploy a linux kernel tree in the local machine to the target's
    root filesystem (:ref:`example <example_linux_kernel>`).

    A Linux kernel can be built and installed in a separate root
    directory in the following form::

      - ROOTDIR/boot/*
      - ROOTDIR/lib/modules/*

    all those will be rsync'ed to the target's */boot* and
    */lib/modules* (caching on the target's persistent rootfs area for
    performance) after flashing the OS image. Thus, it will overwrite
    whatever kernels where in there.

    The target's */boot/EFI* directories will be kept, so that the
    bootloader configuration can pull the information to configure the
    new kernel using the existing options.

    Build the Linux kernel from a *linux* source directory to a
    *build* directory::

      $ mkdir -p build
      $ cp CONFIGFILE build/.config
      $ make -C PATH/TO/SRC/linux O=build oldconfig
      $ make -C build all

    (or your favourite configuration and build mechanism), now it can
    be installed into the root directory::

      $ mkdir -p root
      $ make -C build INSTALLKERNEL=ignoreme \
          INSTALL_PATH=root/boot INSTALL_MOD_PATH=root \
          install modules_install

    The *root* directory can now be given to
    :func:`target.pos.deploy_image <tcfl.pos.extension.deploy_image>`
    as:

    >>> target.deploy_linux_kernel_tree = ROOTDIR
    >>> target.pos.deploy_image(ic, IMAGENAME,
    >>>                         extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

    or if using the :class:`tcfl.pos.tc_pos_base` test class template,
    it can be done such as:

    >>> class _test(tcfl.pos.tc_pos_base):
    >>>     ...
    >>>
    >>>     def deploy_00(self, ic, target):
    >>>         rootdir = ROOTDIR
    >>>         target.deploy_linux_kernel_tree = rootdir
    >>>         self.deploy_image_args = dict(extra_deploy_fns = [
    >>>             tcfl.pos.deploy_linux_kernel ])

    *ROOTDIR* can be hardcoded, but remember if given relative, it is
    relative to the directory where *tcf run* was executed from, not
    where the testcase source is.

    **Low level details**

    When the target's image has been flashed in place,
    :func:`tcfl.pos.deploy_image <tcfl.pos.extension.deploy_image>` is
    asked to call this function.

    The client will rsync the tree from the local machine to the
    persistent space using :meth:`target.pos.rsync <extension.rsync>`,
    which also caches it in a persistent area to speed up multiple
    transfers. From there it will be rsynced to its final
    location.

    """
    kernel_tree = getattr(target, "deploy_linux_kernel_tree", None)
    if kernel_tree == None:
        target.report_info("not deploying linux kernel because "
                           "*pos_deploy_linux_kernel_tree* attribute "
                           "has not been set for the target", dlevel = 2)
        return
    target.report_info("rsyncing boot image to target")
    target.pos.rsync("%s/boot" % kernel_tree, "/", path_append = "",
                     rsync_extra = "--exclude '*efi/'")
    target.testcase._targets_active()
    target.report_info("rsyncing lib/modules to target")
    target.pos.rsync("%s/lib/modules" % kernel_tree, "/lib", path_append = "")
    target.testcase._targets_active()
    target.report_pass("linux kernel transferred")



#:
#: Functions to boot a target into POS
#:
#: Different target drivers can be loaded and will add members to
#: these dictionaries to extend the abilities of the core system to
#: put targets in Provisioning OS mode.
#:
#: This then allows a single test script to work with multiple target
#: types without having to worry about details.
capability_fns = dict(
    #: Function to call to power cycle the target and have it boot the
    #: Provisioning OS.
    #:
    #: This shall be a one shot thing; the following power cycle shall
    #: boot the target normally
    #:
    #: Arguments:
    #: - tcfl.tc.target_c target: target to boot in POS mode
    boot_to_pos = dict(),
    #: Function to call to power cycle the target and have it boot the
    #: installed OS (not the Provisioning OS).
    #:
    #: Arguments:
    #: - tcfl.tc.target_c target: target to boot in normal mode
    boot_to_normal = dict(),
    #: Function to call to configure the boot loader once the system
    #: has been provisoned.
    #:
    #: Arguments:
    #: - tcfl.tc.target_c target: target who's boot has to be configured
    #: - str root_part_dev: root device
    #: - str image: image specification
    boot_config = dict(),
    #: Function to call to fix the boot loader from a system that
    #: might have booted, we have something like a login prompt on the
    #: serial console
    #:
    #: Arguments:
    #: - tcfl.tc.target_c target: target who's boot has to be configured
    boot_config_fix = dict(),
    #: Function to use to partition the target's storage
    #:
    #: Will be called when the target has a property *pos_repartition*
    #: set or when the system things the partition table is trashed
    #: and needs reinitialization.
    #:
    #: Arguments:
    #: - tcfl.tc.target_c target: target who's storage we are
    #:   partitioning
    #: - str boot_dev: device used to boot
    #:
    #: returns: nothing, but sets target.root_part_dev, where the rootfs is
    #:
    mount_fs = dict(),
)


_pos_capable_defaults = dict(
    # backwards compat
    boot_to_pos = 'pxe',
    boot_to_normal = 'pxe',
    boot_config = 'uefi',
    mount_fs = 'multiroot',
    partition = 'default',
)

def capability_register(capability, value, fns):
    assert capability in capability_fns.keys(), \
        "capability %s is not one of: %s" \
        % (capability, " ".join(capability_fns.keys()))
    assert isinstance(value, basestring), \
        "capability value must be a string, got %s" % type(value).__name__
    assert callable(fns) \
        or (
            isinstance(fns, list)
            and all([ callable(i) for i in fns ])
        ), \
        "fns %s is not a callable or list of callables" % fns
    capability_fns.setdefault(capability, {})[value] = fns


# initialized at the bottom, when this is parsed
_metadata_schema_yaml = None

def _metadata_schema_yaml_load():
    global _metadata_schema_yaml
    # this has to be done only once we are all initialized
    if _metadata_schema_yaml:	# already loaded
        return
    schema_path = commonl.ttbd_locate_helper("img-metadata.schema.yaml",
                                             logging, "tcfl")
    _metadata_schema_yaml = commonl.yamll.load(schema_path)
    logging.info("POS: loaded image YAML schema from %s", schema_path)


class extension(tc.target_extension_c):
    """

    Extension to :py:class:`tcfl.tc.target_c` to handle Provisioning
    OS capabilities.
    """

    def __init__(self, target):
        if 'pos_capable' not in target.rt:
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

        pos_capable = target.kws.get('pos_capable', None)
        if pos_capable == None or pos_capable == False:
            raise self.unneeded("target is not POS capable",
                                dict(target = target))
        elif pos_capable == True:
            target.report_info("WARNING! target's pos_capable is still old "
                               "style, update your config--taking "
                               "defaults")
            self.capabilities = _pos_capable_defaults
        elif isinstance(pos_capable, dict):
            self.capabilities = pos_capable
        else:
            raise tc.blocked_e("Target's 'pos_capable' target is "
                               "not a dictionary of POS capabilities",
                               dict(target = self.target))
        self.umount_list = [ '/mnt' ]
        self.fsinfo = {}
        self.metadata = {}	# FIXME: ren to image_metadata

    def _boot_dev_guess(self, boot_dev):
        target = self.target
        # What is our boot device?
        if boot_dev:
            assert isinstance(boot_dev, basestring), \
                'boot_dev must be a string'
            target.report_info("POS: boot device %s (from arguments)"
                               % boot_dev, dlevel = 4)
        else:
            boot_dev = target.kws.get('pos_boot_dev', None)
            if boot_dev == None:
                raise tc.blocked_e(
                    "Can't guess boot_dev (no `pos_boot_dev` tag available)",
                    { 'target': target } )
            target.report_info("POS: boot device %s (from pos_boot_dev tag)"
                               % boot_dev, dlevel = 4)
        boot_dev = "/dev/" + boot_dev
        # HACK: /dev/[hs]d* do partitions as /dev/[hs]dN, where as mmc and
        # friends add /dev/mmcWHATEVERpN. Seriously...
        if boot_dev.startswith("/dev/hd") \
           or boot_dev.startswith("/dev/sd") \
           or boot_dev.startswith("/dev/vd"):
            target.kw_set('p_prefix', "")
        else:
            target.kw_set('p_prefix', "p")
        return boot_dev



    # FIXME: make this return fn and a description saying
    # "capability %s/%s @ %s.%s()" so we can use it to feed to messages such as
    # "rebooting into Provisioning OS [0/3] with capability %s/%s @ %s.%s()"
    def cap_fn_get(self, capability, default = None):
        """
        Return a target's POS capability.

        :param str capability: name of the capability, as defined in
          the target's tag :ref:`*pos_capable* <pos_capable>`.

        :param str default: (optional) default to use if not
          specified; DO NOT USE! WILL BE DEPRECATED!
        """
        if capability not in capability_fns:
            raise tc.blocked_e("Unknown POS capability '%s'; maybe "
                               "needs to be configured in "
                               "tcfl.pos.capability_fns?" %
                               capability, dict(target = self.target))
        if capability not in self.capabilities:
            self.target.report_info("WARNING! target's pos_capable "
                                    "doesn't list '%s'; defaulting to '%s'"
                                    % (capability, default))
        capability_value = self.capabilities.get(capability, default)
        if capability_value == None:	# this means not needed/supported
            self.target.report_info(
                "POS: capability %s resolves to no-action" % capability)
            return None
        if capability_value not in capability_fns[capability]:
            raise tc.blocked_e(
                "target defines '%s' method for '%s' that is unknown to "
                "the Provisioning OS library; maybe configuration for it "
                "is not loaded?" % (capability_value, capability),
                attachments = dict(target = self.target,
                                   capability = capability,
                                   value = capability_value)
            )
        capability_fn = capability_fns[capability][capability_value]
        modname = capability_fn.__module__
        self.target.report_info(
            "POS: capability %s/%s by %s.%s" % (
                capability, capability_value,
                inspect.getsourcefile(capability_fn), capability_fn.__name__),
            dlevel = 1)
        return capability_fn


    # can't add $ at the end because sometimes there are spurious
    # messages after it...
    _regex_waiting_for_login = re.compile(r".*\blogin:\s+")

    def _unexpected_console_output_try_fix(self, output, target):
        # so when trying to boot POS we got unexpected console output;
        # let's see what can we do about it.
        if output == None:
            # nah, can't do much
            return

        # looks like a login prompt? Maybe we can login and munge
        # things around
        if self._regex_waiting_for_login.search(output):
            boot_config_fix_fn = target.pos.cap_fn_get('boot_config_fix',
                                                       'uefi')
            if boot_config_fix_fn:
                target.report_info("POS: got an unexpected login "
                                   "prompt, will try to fix the "
                                   "boot configuration")
                boot_config_fix_fn(target)
            else:
                target.report_error(
                    "POS: seems we got a login prompt that is not POS, "
                    "but I don't know how to fix it; target does not "
                    "declare capability `boot_config_fix`",
                    attachments = dict(output = output))

    def boot_to_pos(self, pos_prompt = None,
                    # plenty to boot to an nfsroot, hopefully
                    timeout = 60,
                    boot_to_pos_fn = None):
        target = self.target
        if boot_to_pos_fn == None:
            # None specified, let's take from the target config
            boot_to_pos_fn = self.cap_fn_get('boot_to_pos', 'pxe')

        bios_boot_time = int(target.kws.get("bios_boot_time", 30))

        # FIXME: this is a hack because now the expecter has a
        # maximum timeout set that can't be overriden--the
        # re-design of the expect sequences will fix this, but
        # for now we have to make sure the maximum is also set
        # here, so in case the bios_boot_time setting in
        # boot_to_pos is higher, it still can go.
        # bios_boot_time has to be all encapsulated in
        # boot_to_pos(), as it can be called from other areas
        testcase = target.testcase
        timeout_original = testcase.tls.expect_timeout
        try:
            testcase.tls.expect_timeout = bios_boot_time + timeout
            for tries in range(3):
                target.report_info("POS: rebooting into Provisioning OS [%d/3]"
                                   % tries)

                # Sequence for TCF-live based on Fedora
                try:
                    boot_to_pos_fn(target)
                    # POS prints this when it boots before login
                    target.expect("TCF test node", timeout =
                                  bios_boot_time + timeout)
                    target.shell.up(timeout = timeout)
                except tc.error_e as e:
                    outputf = e.attachments_get().get('console output', None)
                    if outputf:
                        output = open(outputf.name).read()
                    if output == None or output == "" or output == "\x00":
                        target.report_error("POS: no console output, retrying")
                        continue
                    # sometimes the BIOS has been set to boot local directly,
                    # so we might as well retry
                    target.report_error("POS: unexpected console output, retrying",
                                        attachments = dict(output = output))
                    self._unexpected_console_output_try_fix(output, target)
                    continue
                target.report_info("POS: got Provisioning OS shell")
                break
            else:
                raise tc.blocked_e(
                    "POS: tried too many times to boot, without signs of life",
                    { "console output": target.console.read(), 'target': target })
        finally:
            testcase.tls.expect_timeout = timeout_original

    def boot_normal(self, boot_to_normal_fn = None):
        """
        Power cycle the target (if neeed) and boot to normal OS (vs
        booting to the Provisioning OS).
        """
        target = self.target
        if boot_to_normal_fn == None:
            # None specified, let's take from the target config
            boot_to_normal_fn = self.cap_fn_get('boot_to_normal')

        boot_to_normal_fn(target)


    def mount_fs(self, image, boot_dev):
        """Mount the target's filesystems in /mnt

        When completed, this function has (maybe)
        formatted/reformatted and mounted all of the target's
        filesystems starting in /mnt.

        For example, if the final system would have filesystems */boot*,
        */* and */home*, this function would mount them on:

        - / on /mnt/
        - /boot on /mnt/boot
        - /home on /mnt/home

        This allows :meth:`deploy_image` to rysnc content into the
        final system.

        :param str image: name of the image we are going to deploy in
          this target
        :param str boot_dev: device name the system will use to boot
        """
        assert isinstance(image, basestring)
        assert isinstance(boot_dev, basestring)

        mount_fs_fn = self.cap_fn_get("mount_fs")
        return mount_fs_fn(self.target, image, boot_dev)


    def rsyncd_start(self, ic):
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

        :param tcfl.tc.target_c ic: interconnect (network) to which
          the target is connected.
        """
        target = self.target
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
            "rsync --port 3000 --daemon --no-detach --config /tmp/rsync.conf &"
            "echo $! > /tmp/rsync.pid")
        # Tell the tunneling interface which IP address we want to use
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
        target.kw_set('rsync_port', target.tunnel.add(3000))
        target.kw_set('rsync_server', target.rtb.parsed_url.hostname)


    def rsync(self, src = None, dst = None,
              persistent_name = None,
              persistent_dir = persistent_tcf_d, path_append = "/.",
              rsync_extra = "", skip_local = False):
        """
        rsync data from the local machine to a target

        The local machine is the machine executing the test script (where
        *tcf run* was called).

        This function will first rsync data to a location in the target
        (persistent storage ``/persistent.tcd.d``) that will not be
        overriden when flashing images. Then it will rsync it from there
        to the final location.

        Note this cache directory can accumulate and grow too big;
        :func:`target.pos.deploy_image
        <tcfl.pos.extension.deploy_image>` will cap it to a top size
        by removing the oldest files.

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
        >>>         tcfl.pos.rsync(os.path.expanduser("~/somegittree.git"),
        >>>                        dst = '/opt/somegittree.git')
        >>>
        >>>     def deploy(self, ic, target):
        >>>         ic.power.on()
        >>>         target.pos.deploy_image(
        >>>             ic, "fedora::29",
        >>>             extra_deploy_fns = [ self._deploy_mygittree ])
        >>>
        >>>     ...


        In this example, the user has a cloned git tree in
        ``~/somegittree.git`` that has to be flashed to the target into
        ``/opt/somegittree.git`` after ensuring the root file system is
        flashed with *Fedora 29*. :func:`deploy_image` will start the rsync
        server and then call *_deploy_mygittree()*  which will use
        :meth:`target.pos.rsync <rsync>` to rsync from the user's
        machine to the target's persistent location (in
        ``/mnt/persistent.tcf.d/somegittree.git``) and from there to the
        final location of ``/mnt/opt/somegittree.git``. When the system
        boots it will be of course in ``/opt/somegittree.git``

        Because :meth:`target.pos.rsyncd_start <rsyncd_start>`
        has been called already, we have now these keywords available
        that allows to know where to connect to.

           >>> target.kws['rsync_server']
           >>> target.kws['rsync_port']

          as setup by calling :meth:`target.pos.rsyncd_start
          <rsyncd_start>` on the target. Functions such as
          :meth:`target.pos.deploy_image <deploy_image>` do this for
          you.

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
          area in the target, defaults to :data:`persistent_tcf_d`.
        """
        target = self.target
        target.shell.run("mkdir -p /mnt/%s" % persistent_dir)
        # upload the directory to the persistent area
        if persistent_name == None:
            assert src != None, \
                "no `src` parameter is given, `persistent_name` must " \
                "then be specified"
            # when we are not given a name, rsync will take the
            # source's name; this allows it to override files of
            # different types in the cache
            persistent_name = ""
            _persistent_name = os.path.basename(src)
        else:
            assert isinstance(persistent_name, basestring) \
                and not os.path.sep in persistent_name, \
                "persistent_name  can't be a subdirectory" \
                " and has to be a string"
            _persistent_name = persistent_name
        # We don't want to transfer from local machine if skip_local is True
        # If skip_local is true, we proceed to make a copy from persistent
        # area to final destination
        if not skip_local and src != None:
            target.report_info(
                "rsyncing %s to target's persistent area /mnt%s/%s"
                % (src, persistent_dir, persistent_name))
            target.shcmd_local(
                # don't be verbose, makes it too slow and timesout when
                # sending a lot of files
                "time -p rsync -cHaAX %s --force --numeric-ids --delete"
                " --port %%(rsync_port)s "
                " %s%s %%(rsync_server)s::rootfs/%s/%s"
                % (rsync_extra, src, path_append, persistent_dir,
                   persistent_name))
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
                "time -p rsync -cHaAX %s --delete /mnt/%s/%s%s /mnt/%s"
                % (rsync_extra, persistent_dir, _persistent_name, path_append,
                   dst))


    def rsync_np(self, src, dst, option_delete = False, path_append = "/.",
                 rsync_extra = ""):
        """rsync data from the local machine to a target

        The local machine is the machine executing the test script (where
        *tcf run* was called).

        Unlike :meth:`rsync`, this function will rsync data straight
        from the local machine to the target's final destination, but
        without using the persistent storage ``/persistent.tcd.d``.

        This function can be used, for example, to flash a whole
        distribution from the target--however, because that would be
        very slow, :meth:`deploy_image` is used to transfer a distro
        as a seed from the server (faster) and then from the local
        machine, just whatever changed (eg: some changes being tested
        in some package):

        >>> @tcfl.tc.interconnect("ipv4_addr")
        >>> @tcfl.tc.target("pos_capable")
        >>> class _test(tcfl.tc.tc_c)
        >>>     ...
        >>>
        >>>     def deploy_tree(_ic, target, _kws):
        >>>         target.pos.rsync_np("/SOME/DIR/my-fedora-29", "/")
        >>>
        >>>     def deploy(self, ic, target):
        >>>         ic.power.on()
        >>>         target.pos.deploy_image(
        >>>             ic, "fedora::29",
        >>>             extra_deploy_fns = [ self.deploy_tree ])
        >>>
        >>>     ...

        In this example, the target will be flashed to whatever fedora
        29 is available in the server and then
        ``/SOME/DIR/my-fedora-29`` will be rsynced on top.

        :param str src: (optional) source tree/file in the local machine
          to be copied to the target's persistent area. If not specified,
          nothing is copied to the persistent area.

        :param str dst: (optional) destination tree/file in the target
          machine; if specified, the file is copied from the persistent
          area to the final destination. If not specified,
          nothing is copied from the persistent area to the final
          destination.

        :param bool option_delete: (optional) Add the ``--delete``
          option to delete anything in the target that is not present
          in the source (%(default)s).

        """
        target = self.target
        target.shell.run("mkdir -p /mnt/%s	# create dest for rsync_np" % dst)
        if option_delete:
            _delete = "--delete"
        else:
            _delete = ""
        # don't be verbose, makes it too slow and timesout when
        # sending a lot of files
        cmdline = \
            "time sudo rsync -cHaAX %s --numeric-ids %s" \
            " --inplace" \
            " --exclude=%s --exclude='%s/*'" \
            " --port %%(rsync_port)s %s%s %%(rsync_server)s::rootfs/%s%s" \
            % (rsync_extra, _delete,
               persistent_tcf_d, persistent_tcf_d,
               src, path_append, dst, path_append)
        target.report_info(
            "POS: rsyncing %s to target's %s" % (src, dst), dlevel = -1,
            attachments = dict(cmdline = cmdline))
        output = target.shcmd_local(cmdline)
        target.testcase._targets_active()
        target.report_info(
            "rsynced %s to target's /%s"
            % (src, dst),
            attachments = dict(cmdline = cmdline, output = output))

    def rsyncd_stop(self):
        """
        Stop an *rsync* server on a target running Provisioning OS

        A server was started with :meth:`target.pos.rsyncd_start
        <rsyncd_start>`; kill it gracefully.
        """
        target = self.target
        # Use sh syntax rather than bash's $(</tmp/rsync.pid) to avoid
        # surprises if the shall changes; ideally we'd use killall, but we
        # don't know if it is installed in the POS
        # set -b: notify immediatelly so we get the Killed message
        # and it does not clobber the output of the next command.
        target.shell.run("set -b")
        target.send("kill -9 `cat /tmp/rsync.pid`")
        # this message comes asynchronous, maybe before or after the
        # prompt...hence why we don't use target.shell.run()
        target.expect(re.compile(r"Killed\s+rsync"))
        # remove the runnel we created to the rsync server and the
        # keywords to access it
        target.tunnel.remove(int(target.kws['rsync_port']))
        target.kw_unset('rsync_port')
        target.kw_unset('rsync_server')

    def _metadata_load(self, target, kws):
        # copy and parse image metadata
        target.shell.run(
            # ensure we remove any possibly existing one
            "rm -f /tmp/tcf.metadata.yaml;"
            # rsync the metadata file to target's /tmp
            " time -p rsync -cHaAX --numeric-ids --delete --inplace -L -vv"
            # don't really complain if there is none
            " --ignore-missing-args"
            " %(rsync_server)s/%(image)s/.tcf.metadata.yaml"
            " /tmp/tcf.metadata.yaml" % kws)
        # if there was one, cat it
        self.metadata = {}
        output = target.shell.run("[ -r /tmp/tcf.metadata.yaml ] "
                                  "&& cat /tmp/tcf.metadata.yaml",
                                  output = True, trim = True)
        if output.strip():
            _metadata_schema_yaml_load()
            self.metadata = commonl.yamll.parse_verify(
                output, _metadata_schema_yaml)
            if self.metadata == None:
                self.metadata = {}

    def _post_flash_setup(self, target, root_part_dev, image_final):
        # Run post setup scripts from the image's metadata
        post_flash_script = self.metadata.get('post_flash_script', "")
        if post_flash_script:
            target.report_info("POS: executing post flash script from "
                               "%s:.tcf.metadata.yaml" % image_final)
            target.shell.run(
                "export ROOTDEV=%s" % root_part_dev
                + " ROOT=/mnt"
                + " ")
        line_acc = ""
        for line in post_flash_script.split('\n'):
            if not line:
                continue
            if line[-1] == "\\":
                line_acc += line[:-1]
            else:
                target.shell.run(line_acc + line)
                line_acc = ""

    def fsinfo_get_block(self, name):
        target = self.target
        for blockdevice in target.pos.fsinfo.get('blockdevices', []):
            if blockdevice['name'] == name:
                return blockdevice
        raise tc.error_e(
            "POS: can't find information about block device '%s' -- is "
            "the right pos_boot_device set in the configuration?"
            % name,
            dict(fsinfo = pprint.pformat(target.pos.fsinfo)))

    def fsinfo_get_child(self, child_name):
        target = self.target
        for blockdevice in target.pos.fsinfo.get('blockdevices', []):
            for child in blockdevice.get('children', []):
                if child['name'] == child_name:
                    return child
        return None

    def fsinfo_get_child_by_partlabel(self, blkdev, partlabel):
        target = self.target
        for blockdevice in target.pos.fsinfo.get('blockdevices', []):
            if blockdevice['name'] != blkdev:
                continue
            for child in blockdevice.get('children', []):
                if child['partlabel'] == partlabel:
                    return child
        return None

    def _fsinfo_load(self):
        # Query filesystem information -> self.fsinfo
        # call partprobe first; we want to make sure the system is
        # done reading the partition tables for slow devices in the
        # system (eg: we booted off somewhere else) -- hence the sleep
        # 3s too ..have to wait a wee or lsblk reports empty; wish
        # there was a way to sync partprobe?
        # WARNING: don't print anything other than lsblk's output!
        # will confuse the json loader
        output = self.target.shell.run(
            "sync;"
            " partprobe;"
            " sleep 3s; "
            " lsblk --json -bni -o NAME,SIZE,TYPE,FSTYPE,UUID,PARTLABEL,LABEL,MOUNTPOINT 2> /dev/null",
            output = True, trim = True)
        # this output will be
        #
        ## {
        ##   "blockdevices": [
        ##     {"name": "sr0", "size": "1073741312", "type": "rom",
        ##      "fstype": null, "mountpoint": null},
        ##     {"name": "vda", "size": "32212254720", "type": "disk",
        ##      "fstype": null, "mountpoint": null,
        ##      "children": [
        ##        {"name": "vda1", "size": "1072693248", "type": "part",
        ##         "fstype": "vfat", "mountpoint": null},
        ##        {"name": "vda2", "size": "4294967296", "type": "part",
        ##         "fstype": "swap", "mountpoint": null},
        ##        ...
        ##        {"name": "vda6", "size": "5368709120", "type": "part",
        ##         "fstype": "ext4", "mountpoint": null}
        ##      ]
        ##    }
        ##  ]
        ## }
        try:
            self.fsinfo = json.loads(output)
        except Exception as e:
            raise tc.blocked_e("can't parse JSON: %s" % e,
                               dict(output = output,
                                    trace = traceback.format_exc()))


    def fsinfo_read(self, boot_partlabel = None,
                    raise_on_not_found = True, timeout = None):
        """
        Re-read the target's partition tables, load the information

        Internal API for POS drivers

        This will load the partition table, ensuring the information
        is loaded and that there is at least an entry in the partition
        table for the boot partition of the device the trget's
        describes as POS boot device (target's *pos_boot_dev*).

        :param str boot_partlabel: (optional) label of the partition
          we need to be able to find while scanning; will retry a few
          times up to a minute forcing a scan; defaults to nothing
          (won't look for it).
        :param bool raise_on_not_found: (optional); raise a blocked
          exception if the partition label is not found after
          retrying; default *True*.
        :param int timeout: (optional) seconds to wait for the
          partition tables to be re-read; defaults to 30s (some HW
          needs more than others and there is no way to make a good
          determination) or whatever is specified in target
          tag/property :ref:`pos_partscan_timeout`. 
        """
        assert timeout == None or timeout > 0, \
            "timeout must be None or a positive number of seconds; " \
            "got %s" % timeout
        target = self.target
        if timeout == None:
            timeout = int(target.kws.get('pos_partscan_timeout', 30))
        # Re-read partition tables
        ts0 = time.time()
        ts = ts0
        device_basename = target.kws['pos_boot_dev']
        while ts - ts0 < timeout:
            ts = time.time()
            target.pos._fsinfo_load()
            boot_part = target.pos.fsinfo_get_child(
                # lookup partition one; if found properly, the info has loaded
                device_basename + target.kws['p_prefix'] + "1")
            if boot_part == None:
                target.report_info(
                    "POS/multiroot: boot partition still not found by lsblk "
                    "after %.1fs/%.1fs; retrying after 3s"
                    % (ts - ts0, timeout))
                time.sleep(3)
                continue
            if boot_partlabel and boot_part['partlabel'] != boot_partlabel:
                target.report_info(
                    "POS/multiroot: boot partition with label %s still "
                    "not found by lsblk after %.1fs/%.1fs; retrying after 3s"
                    % (target._boot_label_name, ts - ts0, timeout))
                time.sleep(3)
                continue
            break
        else:
            if raise_on_not_found:
                raise tc.blocked_e(
                    "POS/multiroot: new partition info not found by lsblk " \
                    "after %.1fs" % (timeout),
                    dict(fsinfo = str(target.pos.fsinfo)))
                # Now set the root device information, so we can pick stuff to


    #:
    #: List of directories to clean up when trying to make up space in
    #: the root filesystem.
    #:
    #: Before an image can be flashed, we need some space so rsync can
    #: do its job. If there is not enough, we start cleaning
    #: directories from files that can be easily ignored or we know
    #: are going ot be wiped.
    #:
    #: This list can be manipulated to fit the specific use case, for
    #: example, from the deploy methods before calling
    #: meth:`deploy_image`:
    #:
    #: >>> self.pos.rootfs_make_room_candidates.insert(0, "/mnt/opt")
    #:
    #: to this we will add the cache locations from
    #: data:`cache_locations_per_distro`
    rootfs_make_room_candidates =  [
        "/mnt/tmp/",
        "/mnt/var/tmp/",
        "/mnt/var/log/",
        "/mnt/var/cache/",
        "/mnt/var/lib/systemd",
        "/mnt/var/lib/spool",
        # do this last, the caches is important...
        # after this we'd add the cache locations; one
    ]

    #: Dictionary of locations we cache for each distribution
    #:
    #: keyed by the beginning of the distro name, this allows us to
    #: respect the space where content has been previousloy downloaded, so
    #: future executions don't have to download it again. This can heavily
    #: cut test setup time.
    cache_locations_per_distro = {
        'clear': [
            # we try to keep the downloaded content across
            # re-flashings, so we don't have to re-download it.
            '/var/lib/swupd',
        ],
        'fedora': [
            "/var/lib/rpm",
        ],
        'rhel': [
            "/var/lib/rpm",
        ],
    }

    def _rootfs_make_room(self, target, cache_locations, minimum_megs):
        # rsync needs have *some* space to work, otherwise it will
        # fail
        #
        # ensure we have at least megs available in the root partition
        # before trying to rsyncing in a new image; start wiping
        # things that are not so critical and most likely will be
        # deleted or brough it clean by the new image; for each
        # candidate to wipe we check if there is enough space,
        # otherwise wipe that candidate; check again, wipe next
        # candidate, etc..

        dlevel = 2	# initially don't care too much
        for candidate in self.rootfs_make_room_candidates + cache_locations:
            output = target.shell.run(
                "df -BM --output=avail /mnt   # got enough free space?",
                output = True, trim = True)
            avail_regex = re.compile("(?P<avail>[0-9]+)M", re.MULTILINE)
            m = avail_regex.search(output)
            if not m:
                target.report_error(
                    "POS: rootfs: unable to verify available space, can't"
                    "parse df output", dict(output = output))
                return
            available_megs = int(m.groupdict()['avail'])
            if available_megs >= minimum_megs:
                target.report_info(
                    "POS: rootfs: %dM free (vs minimum %dM)"
                    % (available_megs, minimum_megs), dlevel = dlevel)
                return

            dlevel = 0		# we wiped, now I need to know
            target.report_info(
                "POS: rootfs: only %dM free vs minimum %dM, wiping %s"
                % (available_megs, minimum_megs, candidate))
            # wipe like this because the dir structure won't really
            # cost that much in terms of size; as well, this is way
            # fast for large trees vs 'rm -rf' [now, perl is really
            # fast, but we can't be sure is installed]
            # || true -> we don't really care if the directory exists or not
            target.shell.run("find %s -type f -delete || true" % candidate)

        # fall through means we couldn't wipe enough stuff


    def _rootfs_cache_manage(self, target, root_part_dev,
                             cache_locations_mnt):
        # Figure out how much space is being consumed by the
        # TCF persistent cache, we might have to clean up
        du_regex = re.compile(r"^(?P<megs>[0-9]+)M\s+total$",
                              re.MULTILINE)
        # we don't care if the dir doesn't exist; -c makes it 0
        du_output = target.shell.run(
            "du -BM -sc %s 2> /dev/null || true"
            " # how much cached space; cleanup?"
            % " ".join(cache_locations_mnt), output = True)
        match = du_regex.search(du_output)
        if not match:
            # if it doesn't exist, we still shall be able to parse
            # that it is 0M and that's it -- so this might be a sign
            # of something really wrong
            raise tc.error_e("can't parse cache space measurement",
                             dict(output = du_output))
        megs = int(match.groupdict()['megs'])
        # report it for general info
        target.report_data(
            "TCF persistant cache usage",
            "%s:%s" % (target.fullid, root_part_dev), megs)
        # FIXME: initial hardcoding for deployment testing, 3GiB
        megs_top = 3 * 1024
        if megs < megs_top:
            target.report_skip("POS: cache uses %d/%dM: skipping cleanup" %
                               (megs, megs_top))
        else:
            for location in cache_locations_mnt:
                tl.linux_rsync_cache_lru_cleanup(target, location,
                                                 megs_top * 1024)


    def deploy_image(self, ic, image,
                     boot_dev = None, root_part_dev = None,
                     partitioning_fn = None,
                     extra_deploy_fns = None,
                     pos_prompt = None,
                     # plenty to boot to an nfsroot, hopefully
                     timeout = 60,
                     # When flushing to USB drives, it can be slow
                     timeout_sync = 240,
                     target_power_cycle_to_pos = None,
                     boot_config = None):
        """Deploy an image to a target using the Provisioning OS

        :param tcfl.tc.tc_c ic: interconnect off which we are booting the
          Provisioning OS and to which ``target`` is connected.

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
         - increase in property bd.stats.client.sos_boot_failures and
           bd.stats.client.sos_boot_count (to get a baseline)
         - tag bd.stats.last_reset to DATE

        Note: you might want the interconnect power cycled

        """
        assert isinstance(ic, tc.target_c), \
            "ic must be an instance of tc.target_c, but found %s" \
            % type(ic).__name__
        assert isinstance(image, basestring)
        target = self.target
        testcase = target.testcase
        if not pos_prompt:
            # soft prompt until we login and update it
            _pos_prompt = re.compile(r' [0-9]+ \$ ')
        else:
            _pos_prompt = pos_prompt
        boot_dev = self._boot_dev_guess(boot_dev)
        with msgid_c("POS"):

            original_timeout = testcase.tls.expect_timeout
            original_prompt = target.shell.shell_prompt_regex
            original_console_default = target.console.default
            try:
                # ensure we use the POS prompt
                target.shell.shell_prompt_regex = _pos_prompt
                # FIXME: this is a hack because now the expecter has a
                # maximum timeout set that can't be overriden--the
                # re-design of the expect sequences will fix this, but
                # for now we have to make sure the maximum is also set
                # here, so in case the bios_boot_time setting in
                # boot_to_pos is higher, it still can go.
                # bios_boot_time has to be all encapsulated in
                # boot_to_pos(), as it can be called from other areas
                bios_boot_time = int(target.kws.get("bios_boot_time", 30))
                testcase.tls.expect_timeout = bios_boot_time + timeout

                self.boot_to_pos(pos_prompt = _pos_prompt, timeout = timeout,
                                 boot_to_pos_fn = target_power_cycle_to_pos)
                target.console.select_preferred(user = 'root')
                if not pos_prompt:
                    # Adopt a harder to false positive prompt regex;
                    # the TCF-HASHID is set by target.shell.up() after
                    # we logged in; so if no prompt was specified, use
                    # this.
                    target.shell.shell_prompt_regex = \
                        _pos_prompt = re.compile(r'TCF-%s: [0-9]+ \$ '
                                                 % testcase.kws['tc_hash'])

                testcase.targets_active()
                kws = dict(
                    rsync_server = ic.kws['pos_rsync_server'],
                    image = image,
                    boot_dev = boot_dev,
                )
                kws.update(target.kws)


                # keep console more or less clean, so we can easily
                # parse it, otherwise kernel drivers loading deferred
                # will randomly "corrupt" our output. Note kernel
                # panics still will go through.
                target.shell.run("dmesg -n alert")
                # don't raise if not found, as if it is an
                # uninitialized disk we'll have to initialize it on
                # mount_fs() below.
                target.pos.fsinfo_read(raise_on_not_found = False)

                # List the available images and decide if we have the
                # one we are asked to install, autocomplete missing
                # fields and get us a good match if there is any.
                output = target.shell.run(
                    "rsync %(rsync_server)s/" % kws, output = True)
                images = image_list_from_rsync_output(output)
                image_final_tuple = image_select_best(image, images, target)
                image_final = ":".join(image_final_tuple)
                kws['image'] = image_final

                self._metadata_load(target, kws)
                testcase.targets_active()
                root_part_dev = self.mount_fs(image_final, boot_dev)
                kws['root_part_dev'] = root_part_dev

                # Keep a lid on how big is the cached content
                cache_locations = [ persistent_tcf_d ]
                for distro, locations in self.cache_locations_per_distro.items():
                    if image_final_tuple[0].startswith(distro):
                        cache_locations += locations
                cache_locations_mnt = []
                for location in cache_locations:
                    # reroot relative to where it is mounted
                    cache_locations_mnt.append(os.path.join(
                        "/mnt",
                        # make the path relative to / so join() joins
                        # it correctly and doesn't throw away the
                        # prefix
                        os.path.relpath(location, os.path.sep)))
                self._rootfs_cache_manage(target, root_part_dev,
                                          cache_locations_mnt)
                self._rootfs_make_room(target, cache_locations_mnt, 150)
                target.report_info("POS: rsyncing %(image)s from "
                                   "%(rsync_server)s to %(root_part_dev)s"
                                   % kws,
                                   dlevel = -2)

                # generate what we will exclude from wiping by rsync;
                # this is basically /persistent.tcf.d and any other
                # directories that are specific to each distro and
                # contain downloaded content (like RPMs and such), to
                # speed things up.
                target.shell.run("""\
cat > /tmp/deploy.ex
%s
%s/*
%s
\x04""" % (persistent_tcf_d, persistent_tcf_d, '\n'.join(cache_locations)))
                # DO NOT use --inplace to sync the image; this might
                # break certain installations that rely on hardlinks
                # to share files and then updating one pushes the same
                # content to all.
                output = target.shell.run(
                    "time -p rsync -acHAX --numeric-ids --delete "
                    " --exclude-from=/tmp/deploy.ex"
                    " %(rsync_server)s/%(image)s/. /mnt/." % kws,
                    # 500s bc rsync takes a long time, but FIXME, we need
                    # to break this up and just increase timeout on the
                    # rsyncs -- and maybe guesstimate from the image size?
                    timeout = 500, output = True)
                # see above on time -p
                kpi_regex = re.compile(r"^real[ \t]+(?P<seconds>[\.0-9]+)$",
                                       re.MULTILINE)
                m = kpi_regex.search(output)
                if not m:
                    raise tcfl.tc.error_e(
                        "Can't find regex %s in output" % kpi_regex.pattern,
                        dict(output = output))
                target.report_data("Deployment stats image %(image)s" % kws,
                                   "image rsync to %s (s)" % target.fullid,
                                   float(m.groupdict()['seconds']))
                target.report_info("POS: rsynced %(image)s from "
                                   "%(rsync_server)s to %(root_part_dev)s"
                                   % kws)

                self._post_flash_setup(target, root_part_dev, image_final)

                # did the user provide an extra function to deploy stuff?
                if extra_deploy_fns:
                    self.rsyncd_start(ic)
                    for extra_deploy_fn in extra_deploy_fns:
                        target.report_info("POS: running extra deploy fn %s"
                                           % extra_deploy_fn, dlevel = 2)
                        testcase.targets_active()
                        extra_deploy_fn(ic, target, kws)
                    self.rsyncd_stop()

                # Configure the bootloader: by hand with shell
                # commands, so it is easy to reproduce by a user
                # typing them
                testcase.targets_active()
                target.report_info("POS: configuring bootloader")
                boot_config_fn = target.pos.cap_fn_get('boot_config', 'uefi')
                if boot_config_fn:
                    # maybe something, maybe nothing
                    boot_config_fn(target, boot_dev, image_final)

            except Exception as e:
                target.report_info(
                    "BUG? exception %s: %s %s" %
                    (type(e).__name__, e, traceback.format_exc()))
                raise
            else:
                # run this only when we are doing a clean exit
                # sync, kill any processes left over in /mnt, unmount it
                # don't fail if this fails, as it'd trigger another exception
                # and hide whatever happened that make us fail. Just make a
                # good hearted attempt at cleaning up
                target.shell.run(
                    "sync; "
                    "which lsof"
                    " && kill -9 `lsof -Fp  /home | sed -n '/^p/{s/^p//;p}'`; "
                    "cd /; "
                    "for device in %s; do umount -l $device || true; done"
                    % " ".join(reversed(target.pos.umount_list)))
            finally:
                target.console.default = original_console_default
                target.shell.shell_prompt_regex = original_prompt
                testcase.tls.expect_timeout = original_timeout

            target.report_info("POS: deployed %(image)s" % kws)
            return kws['image']

def image_seed_match(lp, goal):
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

    goall = image_spec_to_tuple(str(goal))
    scores = {}
    check_empties = {}
    for part_name, seed in lp.iteritems():
        score = 0
        check_empties[part_name] = None
        seedl = image_spec_to_tuple(str(seed))

        if seedl[0] == goall[0]:
            # At least we want a distribution match for it to be
            # considered
            scores[part_name] = Levenshtein.seqratio(goall, seedl)

            # Here, we are checking if spin for image and seed are equal.
            # If the spin are not equal, we should check if there is
            # an empty one to reduce time; therefore, we enable a 
            # flag to check empties.
            if seedl[1] != goall[1]:
                check_empties[part_name] = True
        else:
            scores[part_name] = 0
    if scores:
        selected, score = max(scores.iteritems(), key = operator.itemgetter(1))
        return selected, score, check_empties[selected], lp[selected]
    return None, 0, None, None


def deploy_tree(_ic, target, _kws):
    """
    Rsync a local tree to the target after imaging

    This is normally given to :func:`target.pos.deploy_image
    <tcfl.pos.extension.deploy_image>` as:

    >>> target.deploy_tree_src = SOMELOCALLOCATION
    >>> target.pos.deploy_image(ic, IMAGENAME,
    >>>                         extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

    """
    source_tree = getattr(target, "deploy_tree_src", None)
    if source_tree == None:
        target.report_info("not deploying local tree because "
                           "*target.deploy_tree_src* is missing or None ",
                           dlevel = 2)
        return
    target.report_info("rsyncing tree %s -> target:/" % source_tree,
                       dlevel = 1)
    target.testcase._targets_active()
    target.pos.rsync_np(source_tree, "/", option_delete = True)
    target.testcase._targets_active()
    target.report_pass("rsynced tree %s -> target:/" % source_tree)


def deploy_path(ic, target, _kws, cache = True):
    """
    Rsync a local tree to the target after imaging

    This is normally given to :func:`target.pos.deploy_image
    <tcfl.pos.extension.deploy_image>` as:

    >>> target.deploy_path_src = self.kws['srcdir'] + "/collateral/movie.avi"
    >>> target.deploy_path_dest = "/root"   # optional,defaults to /
    >>> target.pos.deploy_image(ic, IMAGENAME,
    >>>                         extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

    """
    source_path = getattr(target, "deploy_path_src", None)
    dst_path = getattr(target, "deploy_path_dest", "/")
    rsync_extra = getattr(target, "deploy_rsync_extra", "")
    skip_local = getattr(target, "deploy_skip_local", False)
    if source_path == None:
        target.report_info("not deploying local path because "
                           "*target.deploy_path_src is missing or None ",
                           dlevel = 2)
        return

    if isinstance(source_path, basestring):
        source_path = [ source_path ]
    elif isinstance(source_path, collections.Iterable):
        pass
    else:
        raise AssertionError(
            "argument source_path needs to be a string or a "
            "list of such, got a %s" % type(source_path).__name__)

    # try to sync first from the server cache
    for src in source_path:
        cache_name = os.path.basename(src)

        local_type = None
        # FIXME: Should we check file type if we skip local transfer?
        if not skip_local:
            # Get local file type - regular file / directory
            local_type = subprocess.check_output([
                "/usr/bin/stat", "-c%F", src]).strip()

        # Get remote file type - regular file / directory / doesn't exist
        remote_type = target.shell.run(
                    "/usr/bin/stat -c%%F /mnt/persistent.tcf.d/%s 2> "
                    "/dev/null || echo missing" % cache_name,
                    output = True, trim = True).strip()

        # Remove cache if file exists and the types are different
        # A 'regular file' could be a 'directory' in prev life
        if remote_type != 'missing' and local_type != remote_type:
            target.shell.run("rm -rf /mnt/persistent.tcf.d/%s\n"
                              % cache_name)

        # Seed from server's cache if it is a directory
        if local_type == "directory":
            target.shell.run("mkdir -p /mnt/persistent.tcf.d/%s\n"
                    "# trying to seed %s from the server's cache"
                    % (cache_name, cache_name))

        rsync_server = ic.kws['pos_rsync_server']
        target.report_info("POS: rsyncing %s from %s "
                           "to /mnt/persistent.tcf.git/%s"
                           % (cache_name, rsync_server, cache_name),
                           dlevel = -1)
        target.shell.run("time rsync --numeric-ids --delete --inplace "
                         " -cHaAX %s %s/misc/%s /mnt/persistent.tcf.d/"
                         " || true # ignore failures, might not be cached"
                         % (rsync_extra, rsync_server,
                            cache_name),
                         # FIXME: hardcoded
                         timeout = 300)
        target.report_info("POS: rsynced %s from %s "
                           "to /mnt/persistent.tcf.d/%s"
                           % (cache_name, rsync_server, cache_name))

    def _rsync_path(_source_path, dst_path):
        # this might take some time, so be slightl more verbose when
        # we start, so we know what it this waiting for
        target.report_info("POS: rsyncing %s -> target:%s"
                           % (_source_path, dst_path), dlevel = -1)
        target.testcase._targets_active()
        if cache:
            # FIXME: do we need option_delete here too? option_delete = True
            target.pos.rsync(_source_path, dst_path, path_append = "",
                             rsync_extra = rsync_extra, skip_local = skip_local)
        else:
            target.pos.rsync_np(_source_path, dst_path, option_delete = True,
                                path_append = "", rsync_extra = rsync_extra)
        target.testcase._targets_active()
        target.report_pass("POS: rsynced %s -> target:%s"
                           % (_source_path, dst_path))

    for _source_path in source_path:
        _rsync_path(_source_path, dst_path)

# FIXME: when tc.py's import hell is fixed, this shall move to tl.py?

class tc_pos0_base(tc.tc_c):
    """
    A template for testcases that install an image in a target that
    can be provisioned with Provisioning OS.

    Unlike :class:`tc_pos_base`, this class needs the targets being
    declared and called *ic* and *target*, such as:

    >>> @tc.interconnect("ipv4_addr")
    >>> @tc.target('pos_capable')
    >>> class my_test(tcfl.tl.tc_pos0_base):
    >>>     def eval(self, ic, target):
    >>>         target.shell.run("echo Hello'' World",
    >>>                          "Hello World")

    Please refer to :class:`tc_pos_base` for more information.
    """


    #: Image we want to install in the target
    #:
    #: Note this can be specialized in a subclass such as
    #:
    #: >>> class my_test(tcfl.tl.tc_pos_base):
    #: >>>
    #: >>>     image_requested = "fedora:desktop:29"
    #: >>>
    #: >>>     def eval(self, ic, target):
    #: >>>         ...
    image_requested = os.environ.get("IMAGE", None)

    #: Once the image was deployed, this will be set with the name of
    #: the image that was selected.
    image = "image-not-deployed"

    #: extra parameters to the image deployment function
    #: :func:`target.pos.deploy_image
    #: <tcfl.pos.extension.deploy_image>`
    #:
    #: >>> class my_test(tcfl.tl.tc_pos_base):
    #: >>>
    #: >>>     deploy_image_args = dict(
    #: >>>         timeout = 40,
    #: >>>         extra_deploy_fns = [
    #: >>>             tcfl.tl.deploy_tree,
    #: >>>             tcfl.tl.deploy_linux_ssh_root_nopwd
    #: >>>         ]
    #: >>>     )
    #: >>> ...

    deploy_image_args = {}

    #: Which user shall we login as
    login_user = 'root'

    #: How many seconds to delay before login in once the login prompt
    #: is detected
    delay_login = 0

    def deploy_50(self, ic, target):
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        if not self.image_requested:
            raise tc.blocked_e(
                "No image to install specified, set envar IMAGE "
                "or self.image_requested")
        self.image = target.pos.deploy_image(ic, self.image_requested,
                                             **self.deploy_image_args)
        target.report_pass("deployed %s" % self.image)

    def start_50(self, ic, target):
        ic.power.on()
        # fire up the target, wait for a login prompt
        target.pos.boot_normal()
        target.shell.up(user = self.login_user, delay_login = self.delay_login)

    def teardown_50(self):
        tl.console_dump_on_failure(self)


@tc.interconnect("ipv4_addr")
@tc.target('pos_capable')
class tc_pos_base(tc_pos0_base):
    """
    A template for testcases that install an image in a target that
    can be provisioned with Provisioning OS.

    This basic template deploys an image specified in the environment
    variable ``IMAGE`` or in *self.requested_image*, power cycles into
    it and waits for a prompt in the serial console.

    This forcefully declares this testcase needs:

    - a network that supports IPv4 (for provisioning over it)
    - a target that supports Provisioning OS

    if you want more control over said conditions, use
    class:`tc_pos0_base`, for which the targets have to be
    declared. Also, more knobs are available there.

    To use:

    >>> class my_test(tcfl.tl.tc_pos_base):
    >>>     def eval(self, ic, target):
    >>>         target.shell.run("echo Hello'' World",
    >>>                          "Hello World")

    All the methods (deploy, start, teardown) defined in the class are
    suffixed ``_50``, so it is easy to do extra tasks before and
    after.

    >>> class my_test(tcfl.tl.tc_pos_base):
    >>>     def start_60(self, ic):
    >>>         ic.release()    # we don't need the network after imaging
    >>>
    >>>     def eval(self, ic, target):
    >>>         target.shell.run("echo Hello'' World",
    >>>                          "Hello World")

    """
    pass


def cmdline_pos_capability_list(args):
    if not args.target:
        for name, data in capability_fns.iteritems():
            for value, fn in data.iteritems():
                print "%s: %s @%s.%s()" % (
                    name, value, inspect.getsourcefile(fn), fn.__name__)
    else:
        for target in args.target:
            _rtb, rt = tc.ttb_client._rest_target_find_by_id(target)
            pos_capable = rt.get('pos_capable', {})
            if isinstance(pos_capable, bool):
                # backwards compat
                pos_capable = {}
            unknown_caps = set(pos_capable.keys())
            for cap_name in capability_fns:
                cap_value = pos_capable.get(cap_name, None)
                cap_fn = capability_fns[cap_name].get(cap_value, None)
                if cap_name in unknown_caps:
                    unknown_caps.remove(cap_name)
                if cap_value:
                    print"%s.%s: %s @%s.%s" % (
                        target, cap_name, cap_value,
                        inspect.getsourcefile(cap_fn), cap_fn.__name__)
                else:
                    print "%s.%s: NOTDEFINED @n/a" % (target, cap_name)
            if unknown_caps:
                print "%s: unknown capabilities defined: %s" % (
                    target, " ".join(unknown_caps))

def cmdline_setup(argsp):
    ap = argsp.add_parser("pos-capability-list", help = "List available "
                          "POS capabilities or those each target exports")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    nargs = "*", default = None, help = "Target's name")
    ap.set_defaults(func = cmdline_pos_capability_list)


import pos_multiroot	# pylint: disable = wrong-import-order,wrong-import-position,relative-import
import pos_uefi		# pylint: disable = wrong-import-order,wrong-import-position,relative-import
capability_register('mount_fs', 'multiroot', pos_multiroot.mount_fs)
capability_register('boot_to_pos', 'pxe', target_power_cycle_to_pos_pxe)
capability_register('boot_to_normal', 'pxe', target_power_cycle_to_normal_pxe)
capability_register('boot_config', 'uefi', pos_uefi.boot_config_multiroot)
capability_register('boot_config_fix', 'uefi', pos_uefi.boot_config_fix)
