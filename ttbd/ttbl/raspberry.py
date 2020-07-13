#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Support for the Raspberry Pi, in file raspberry.py,
# hahah...hah....uh...I need help...#covid19
"""Raspberry Pi Provisioning OS support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some parts of the system use PXE and this contains the
implementations.


.. _pos_rpi_bootloader_setup:

Setup:

1. download the Raspberry bootloader::

     $ wget https://downloads.raspberrypi.org/raspbian/boot.tar.xz

2. extract the bootloader::

     # install -o ttbd -g ttbd -m 0775 -d /usr/local/share/raspberry/bootloader
     # tar xf boot.tar.xz -C /usr/local/share/raspberry/bootloader

3. configure it (this location is set as the default, so unless to
   change to another path, there is no need to do this step)::

     $ echo "ttbl.raspberry.bootloader_path = '/usr/local/share/raspberry/bootloader'" \
         >> /etc/ttbd-production/conf_00_raspberry.py

4. setup the *lite* RaspBian image which TCF will use as Provisioning OS:

   a. download the *lite* image::

        # yum install unzip
        $ wget https://downloads.raspberrypi.org/raspbian_lite/images/raspbian_lite-2020-02-14/2020-02-13-raspbian-buster-lite.zip
        $ unzip 2020-02-13-raspbian-buster-lite.zip

   b. extract::

        # BOOT_PARTITION=1 ROOT_PARTITION=2 /usr/share/tcf/tcf-image-setup.sh \
          /home/ttbd/images/tcf-live/rpi 2020-02-13-raspbian-buster-lite.img

      this creates ``/home/ttbd/images/tcf-live/rpi``, which will be
      NFS served for RPIs booting over NFS.

      This has setup a few things in the image:

      - setup the *fstab*; since we will not mount local filesystems
        and will need a writeable */tmp* (NFS root is mounted read only)::

          $ cd /home/ttbd/images/tcf-live/rpi/etc
          $ sudo sed 's/PARTUUID/#PARTUUID/' -i fstab
          $ echo "none /tmp tmpfs defaults 0 0" | sudo tee -a fstab

      - configure SSH access; allow login with no root password (default
        in the image) and enable the SSH server to start when the system
        powers up.

   c. configure the POS image (be careful with the paths here, **they
      are relative**, don't modify the system's).

      Setup the SSH host keys::

        # cd /home/ttbd/images/tcf-live/rpi/etc
        $ for v in rsa ecdsa ed25519; do \
                sudo ssh-keygen -f ssh/ssh_host_${v}_key -q -t $v -C '' -N ''; done

      Make the Provisioning OS print *TCF test node* when booting and
      login, so we can use it to tell if we are up::

        $ echo "TCF test node" | sudo tee etc/issue
        $ echo "TCF test node" | sudo tee etc/motd

   d. configure NFS to export POS::

        # echo '/home/ttbd/images/tcf-live/rpi *(ro,no_root_squash)' >> /etc/exports.d/ttbd-pos.exports
        # systemctl reload nfs-server

5. setup the *full* RaspBian image to deploy in the target::

     $ wget https://downloads.raspberrypi.org/raspbian_full/images/raspbian_full-2020-02-14/2020-02-13-raspbian-buster-full.zip
     $ unzip 2020-02-13-raspbian-buster-full.zip
     $ BOOT_PARTITION=1 ROOT_PARTITION=2 /usr/share/tcf/tcf-image-setup.sh \
          /home/ttbd/images/raspbian:full:2020-02-13::armhf 2020-02-13-raspbian-buster-lite.img

"""

import os
import subprocess

import commonl
import ttbl.pxe


# Because RPI3 doesn't obey DHCP's offer's bootfile path, it always
# asks for bootcode.bin
#
# https://github.com/raspberrypi/firmware/issues/1370
#
# So we have to have bootcode.bin always there at the root
ttbl.pxe.architectures.setdefault('root', {}).setdefault('copy_files', []).append(
    '/usr/local/share/raspberry/bootloader/bootcode.bin'
)

#: Path to where the raspberry bootloader partition has been
#: extracted.
#:
#: See :ref:`here <pos_rpi_bootloader_setup>` for installation
#: instructions.
#:
bootloader_path = '/usr/local/share/raspberry/bootloader'

def pre_tftp_pos_setup(target):
    pos_mode = target.fsdb.get("pos_mode")
    # we always run, as we have set the RPI3 to always depend on
    # network boot to control it

    assert 'raspberry_serial_number' in target.tags, \
        "%s: configuration error: target configured to pre-power" \
        " up with ttbl.raspberry.pre_tftp_pos_setup() but no" \
        " raspberry_serial_number tag specified"

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

    # we need the interconnect object to get some values
    ic = ttbl.test_target.get(boot_ic)

    raspberry_serial_number = target.tags['raspberry_serial_number']

    # rsync the bootloader to TFTPROOT/SERIALNUMBER/. -- this way we
    # just override only what needs overriding
    #
    # then we will configure the bootmode in there.
    # HACK, this should be an internal tag of the ic
    tftp_dirname = os.path.join(ic.state_dir, "tftp.root", raspberry_serial_number)
    commonl.makedirs_p(tftp_dirname)
    cmdline = [ "rsync", "-a", "--delete",
                bootloader_path + "/.", tftp_dirname ]
    subprocess.check_output(cmdline, shell = False, stderr = subprocess.STDOUT)

    # now generate the cmdline we want to send and put it in
    # TFTPROOT/SERIALNUMBER/cmdline.txt.
    #
    # For POS boot, we NFS root it to whatever is in tcf-live -- the
    # root-path is given by DHCP (see dnsmasq.py/dhcp.py, look for
    # root-path) from the {pos_nfs_path,pos_nfs_root,pos_image}
    # keywords.
    #
    # For local boot, we take the default from the bootloader
    if pos_mode == "pxe":
        with open(os.path.join(tftp_dirname, "cmdline.txt"), "w") as f:
            f.write(
                "console=serial0,115200 console=tty1"
                " rootwait quiet splash plymouth.ignore-serial-consoles"
                " ip=dhcp"
                " root=/dev/nfs"		# we are NFS rooted
                # no exotic storage options
                " ro"				# we are read only
                #" plymouth.enable=0 "		# No installer to run
                # kernel, be quiet to avoid your messages polluting the serial
                # terminal
                #" loglevel=2"
                " netconsole=@/eth0,6666@192.168.98.1/")
    else:
        with open(os.path.join(tftp_dirname, "cmdline.txt"), "w") as f:
            f.write(
                "console=serial0,115200"
                " console=tty1"
                " root=/dev/mmcblk0p2"
                " rootfstype=ext4"
                " elevator=deadline"
                " fsck.repair=yes"
                " rootwait"
                " quiet"
                #" init=/usr/lib/raspi-config/init_resize.sh"
                " splash"
                " plymouth.ignore-serial-consoles")
