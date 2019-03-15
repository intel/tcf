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

import inspect
import operator
import os
import random
import re
import traceback

import distutils.version
import Levenshtein

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
    target.report_info("Setting target not to PXE boot Provisioning OS")
    target.property_set("pos_mode", "local")
    target.power.cycle()


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

    This is normally given to :func:`target.pos.deploy_image
    <tcfl.pos.extension.deploy_image>` as:

    >>> target.kw_set("pos_deploy_linux_kernel", SOMELOCALLOCATION)
    >>> target.pos.deploy_image(ic, IMAGENAME,
    >>>                         extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

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
    :func:`tcfl.pos.deploy_image <tcfl.pos.extension.deploy_image>` is
    asked to call this function.

    The client will rsync the tree from the local machine to the
    persistent space using :meth:`target.pos.rsync <extension.rsync>`,
    which also caches it in a persistent area to speed up multiple
    transfers.

    """
    if not '' in _kws:
        target.report_info("not deploying linux kernel because "
                           "*pos_deploy_linux_kernel_tree* keyword "
                           "has not been set for the target", dlevel = 2)
        return
    target.report_info("rsyncing boot image to target")
    target.pos.rsync("%(pos_deploy_linux_kernel_tree)s/boot" % target.kws,
                     "/boot")
    target.report_info("rsyncing lib/modules to target")
    target.pos.rsync("%(pos_deploy_linux_kernel_tree)s/lib/modules"
                     % target.kws,
                     "/lib/modules")
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
    #: Post-deploy functions to run
    extra_deploy = dict(),
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


class extension(tc.target_extension_c):
    """

    Extension to :py:class:`tcfl.tc.target_c` to handle Provisioning
    OS capabilities.
    """

    def __init__(self, target):
        if 'pos_capable' not in target.rt:
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

        pos_capable = target.kws['pos_capable']
        if isinstance(pos_capable, bool):
            if pos_capable == False:
                raise tc.blocked_e("target is not POS capable",
                                   dict(target = target))
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

    def _boot_dev_guess(self, boot_dev):
        target = self.target
        # What is our boot device?
        if boot_dev:
            assert isinstance(boot_dev, basestring), \
                'boot_dev must be a string'
            target.report_info("POS: boot device %s (from arguments)"
                               % boot_dev, dlevel = 3)
        else:
            boot_dev = target.kws.get('pos_boot_dev', None)
            if boot_dev == None:
                raise tc.blocked_e(
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
                inspect.getsourcefile(capability_fn), capability_fn.__name__))
        return capability_fn


    _regex_waiting_for_login = re.compile(r".*\blogin:\s*$")

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

        for tries in range(3):
            target.report_info("POS: rebooting into Provisioning OS [%d/3]"
                               % tries)
            boot_to_pos_fn(target)

            # Sequence for TCF-live based on Fedora
            if pos_prompt:
                target.shell.linux_shell_prompt_regex = pos_prompt
            try:
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
                target.report_error("POS: unexpected console output, retrying")
                self._unexpected_console_output_try_fix(output, target)
                continue
            target.report_info("POS: got Provisioning OS shell")
            break
        else:
            raise tc.blocked_e(
                "POS: tried too many times to boot, without signs of life",
                { "console output": target.console.read(), 'target': target })


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

        self.target.shell.run("lsblk")
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
          area in the target, defaults to `/persistent.tcf.d`.
        """
        target = self.target
        target.shell.run("mkdir -p /mnt/%s" % persistent_dir)
        # upload the directory to the persistent area
        if persistent_name == None:
            assert src != None, \
                "no `src` parameter is given, `persistent_name` must " \
                "then be specified"
            persistent_name = os.path.basename(src)
        if src != None:
            target.report_info(
                "rsyncing %s to target's persistent area /mnt%s/%s"
                % (src, persistent_dir, persistent_name))
            target.shcmd_local(
                # don't be verbose, makes it too slow and timesout when
                # sending a lot of files
                "time rsync -aAX --numeric-ids --delete"
                " --port %%(rsync_port)s "
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


    def rsync_np(self, src, dst, option_delete = True):
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
        target.shell.run("mkdir -p /%s" % dst)
        target.report_info(
            "rsyncing %s to target's /mnt/%s"
            % (src, dst), dlevel = -1)
        if option_delete:
            _delete = "--delete"
        else:
            _delete = ""
        target.shcmd_local(
            # don't be verbose, makes it too slow and timesout when
            # sending a lot of files
            "time sudo rsync -vvvaAX --numeric-ids %s"
            " --inplace --exclude='/persistent.tcf.d/*'"
            " --port %%(rsync_port)s  %s/. %%(rsync_server)s::rootfs/%s/."
            % (_delete, src, dst))
        target.testcase._targets_active()
        target.report_info(
            "rsynced %s to target's /%s"
            % (src, dst))

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
        target.shell.run("kill -9 `cat /tmp/rsync.pid`")
        # remove the runnel we created to the rsync server and the
        # keywords to access it
        target.tunnel.remove(int(target.kws['rsync_port']))
        target.kw_unset('rsync_port')
        target.kw_unset('rsync_server')


    def deploy_image(self, ic, image,
                     boot_dev = None, root_part_dev = None,
                     partitioning_fn = None,
                     extra_deploy_fns = None,
                     # mkfs has to have -F to avoid it asking questions
                     mkfs_cmd = "mkfs.ext4 -Fj %(root_part_dev)s",
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
        boot_dev = self._boot_dev_guess(boot_dev)
        with msgid_c("POS"):

            self.boot_to_pos(pos_prompt = pos_prompt, timeout = timeout,
                             boot_to_pos_fn = target_power_cycle_to_pos)
            testcase.targets_active()
            kws = dict(
                rsync_server = ic.kws['pos_rsync_server'],
                image = image,
                boot_dev = boot_dev,
            )
            kws.update(target.kws)

            original_timeout = testcase.tls.expecter.timeout
            try:
                testcase.tls.expecter.timeout = 800

                # List the available images and decide if we have the
                # one we are asked to install, autocomplete missing
                # fields and get us a good match if there is any.
                image_list_output = target.shell.run(
                    "rsync %(rsync_server)s/" % kws, output = True)
                images_available = image_list_from_rsync_output(
                    image_list_output)
                image_final_tuple = image_select_best(image, images_available,
                                                      target)
                image_final = ":".join(image_final_tuple)
                kws['image'] = image_final

                testcase.targets_active()
                root_part_dev = self.mount_fs(image_final, boot_dev)
                kws['root_part_dev'] = root_part_dev

                target.report_info("POS: rsyncing %(image)s from "
                                   "%(rsync_server)s to /mnt" % kws,
                                   dlevel = -1)
                target.shell.run("time rsync -aAX --numeric-ids --delete"
                                 " --inplace --exclude='/persistent.tcf.d/*'"
                                 " %(rsync_server)s/%(image)s/. /mnt/." % kws)
                target.report_info("POS: rsynced %(image)s from "
                                   "%(rsync_server)s to /mnt" % kws)

                # did the user provide an extra function to deploy stuff?
                _extra_deploy_fns = []
                more = self.cap_fn_get('extra_deploy')
                if more:
                    _extra_deploy_fns += more
                if extra_deploy_fns:
                    _extra_deploy_fns += extra_deploy_fns
                if _extra_deploy_fns:
                    self.rsyncd_start(ic)
                    for extra_deploy_fn in _extra_deploy_fns:
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

                testcase.tls.expecter.timeout = timeout_sync
            except Exception as e:
                target.report_info(
                    "BUG? exception %s: %s %s" %
                    (type(e).__name__, e, traceback.format_exc()))
                raise
            finally:
                testcase.tls.expecter.timeout = original_timeout
                # FIXME: document
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
    for part_name, seed in lp.iteritems():
        score = 0
        seedl = image_spec_to_tuple(str(seed))

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


def deploy_tree(_ic, target, _kws):
    """
    Rsync a local tree to the target after imaging

    This is normally given to :func:`target.pos.deploy_image
    <tcfl.pos.extension.deploy_image>` as:

    >>> target.kw_set("pos_deploy_linux_kernel", SOMELOCALLOCATION)
    >>> target.pos.deploy_image(ic, IMAGENAME,
    >>>                         extra_deploy_fns = [ tcfl.pos.deploy_linux_kernel ])

    """
    source_tree = target.getattr("deploy_tree_src", None)
    if source_tree == None:

        target.report_info("not deploying local tree because "
                           "*target.deploy_tree_src* is missing or None ",
                           dlevel = 2)
        return
    target.report_info("rsyncing tree %s -> target:/" % source_tree,
                       dlevel = 1)
    target.testcase._targets_active()
    target.pos.rsync_np(source_tree, "/")
    target.testcase._targets_active()
    target.report_pass("rsynced tree %s -> target:/" % source_tree)



import pos_multiroot	# pylint: disable = wrong-import-order,wrong-import-position,relative-import
import pos_uefi		# pylint: disable = wrong-import-order,wrong-import-position,relative-import
capability_register('mount_fs', 'multiroot', pos_multiroot.mount_fs)
capability_register('boot_to_pos', 'pxe', target_power_cycle_to_pos_pxe)
capability_register('boot_to_normal', 'pxe', target_power_cycle_to_normal_pxe)
capability_register('boot_config', 'uefi', pos_uefi.boot_config_multiroot)
capability_register('boot_config_fix', 'uefi', pos_uefi.boot_config_fix)
