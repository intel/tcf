#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""Galileo2 targets with serial console
====================================

This decribes how to hook up a default Galileo 2 board into TCF for
running Tiny Mountain tests with the following features:

 - serial console is available
 - power control is available
 - image flashing is supported via serial console

Bill of materials:

 - A Galileo2 board and it's serial cable
 - A USB disk
 - A supported remote control power switch and available outlet

A default Galileo2 has a *Poky 9.0.2 (Yocto Project 1.4 Reference
Distro) 1.4.2 clanton* in SPI, including a Grub 0.9 bootloader spawned
by EFI automatically.

This system is set up so we can boot Viper kernels using:

 - a USB hard drive to store utilities and the kernels to boot
 - a Xmodem file transfer utility to transfer files over the serial
   console
 - a Grub2 EFI bootloader to boot the transferred kernel
 - SPI builtin Grub 0.9 to boot the SPI flashed Linux image.


Theory of operation
-------------------

We will use the USB disk as permanent storage for the Galileo2
Platform.

The Test Target Broker daemon connects to the Galileo2 using a serial
port. We use the Python *pexpect* module to execute a expect/send
sequence of commands to the serial console that allow us to control
the EFI shell, grub and the Linux OS (through it's serial console).

When we want to flash a new kernel, the :term:`ttbd` boots the
galileo2 into the builtin Linux image by directing the builtin Grub
0.9 to boot the default Linux image. It then uses the *Xmodem*
receiving utility in the USB disk to receive a new kernel image that
is stored in the USB disk's path ``/efi/boot/kernel.file``; in the
:term:`ttbd` side, the Pyhton :py:mod:`xmodem` module is used to
transfer the file.

.. note:: the file transfer happens using the Xmodem serial file
          transfer protocol over the serial console, no network is
          needed.

The USB disk is then unmounted and the target is powered off.

When it is time to power up the target into normal operation, the
serial console is used to stop default Grub 0.9 boot, exiting to it's
command line and quitting into the EFI Boot Menu; from there the EFI
shell is selected to load the Grub 2 bootloader, which supports
loading the Viper images.

When grub2.efi starts, we point it to the ``/efi/boot/kernel.file`` in
the USB disk and boot it.

It seems complex, but it is simpler than setting it up with network
boot (which is not supported by Galileo2's default firmware). The main
inconvenience is that the Xmodem file transfer is slowy.

The :class:`tm_galileo` implements the image flashing support and then
brings in a stock serial console port using
:class:`ttbl.cm_serial.cm_serial`.

In the code, we add the :func:`power_on_post_galileo` method of to
take over the serial port from the console after boot and tell the
bootloader what to do depending on if we have an image to burn or
not. The serial port interaction happens with
:py:class:`pexpect.fdpexpect` in a expect/send sequences that are
detailed in the class.

Prepare the USB disk
--------------------

Partition and format the first partition as FAT-FS; mount at
``MNTPOINT`` and create the following directory structure::

  efi
  efi/boot
  utils

Xmodem serial transfer support for the Galileo2
-----------------------------------------------

For the Galileo2

1. Download the Galileo2 SDK from
   https://downloadcenter.intel.com/download/24355/Intel-Arduino-IDE-1-6-0
   and install it::

     $ sudo tar xf IntelArduino-1.6.0-Linux32.txz -C /opt
     $ sudo mkdir -p /opt/clanton-tiny
     $ sudo ln -sf \
           /opt/arduino-1.6.0+Intel/hardware/tools/i586/ \
           /opt/clanton-tiny/1.4.2

   Note you need this SDK to compile code that will work in the
   Galileo2 board, including the ucLibc bindings.

2. Format the USB disk with ext3::

     $ sudo su -
     # umount /dev/DEVICE
     # mkfs.vfat /dev/DEVICE
     # mount /dev/DEVICE /mnt
     # mkdir /mnt/utils

2. Download *lrzsz*'s source from
   https://ohse.de/uwe/software/lrzsz.html and build it:

   .. code-block:: bash

      . /opt/clanton-tiny/1.4.2/environment-setup-i586-poky-linux-uclibc
      tar xf lrzsz-0.12.20.tar.gz
      cd lrzsz-0.12.20
      CFLAGS="-m32" ./configure --enable-static  --disable-shared
      make clean all

   transfer it to the USB disk::

     $ sudo install -m 0755 src/lrz /mnt/utils/

3. Download Grub 2's source and compile it; note we are not
   cross-compiling, thus don't reuse the session where lrzsz was
   compiled.

   .. code-block:: bash

      # Ensure your system has bison, flex and some other tools the
      # compilation process might complain about if missing

      wget ftp://ftp.gnu.org/gnu/grub/grub-2.00.tar.xz
      tar xf grub-2.00.tar.xz
      ./autogen.sh
      CFLAGS="-w -march=i586 -m32" \
      ./configure --with-platform=efi --target=i386 \
          --program-prefix="" --disable-grub-mkfont
      make
      cd grub-core
      ../grub-mkimage -O i386-efi -d . -o grub.efi -p "" part_gpt \
      part_msdos fat ext2 normal chain boot configfile linux multiboot \
      help serial terminal elf efi_gop efi_uga terminfo

   Deploy it to the USB storage::

     install grub.efi -D /mnt/efi/boot/grub.efi

4. Unmount the disk::

     umount /dev/DEVICE

XModem support for the TCF's TTBD server
----------------------------------------

The host running the TTBD server needs to have the Python XModem
library installed system-wide (or user wide):

#. Download from https://pypi.python.org/pypi/xmodem

#. Install with::

     pip install --user xmodem


Debugging tips
--------------

When the serial port is opened by another application, this will just
fail--make sure you have absolute control of the serial port. Use
``lsof``::

  sudo lsof /dev/ttyUSB0
  <should be empty>

if other processes are there, kill them.

FIXME: serial console

FIXME: notes
------------

- Serial port should work with no RTS/CTS

- pointers into the code for each phase

- BSP supported: quark

"""
import pexpect
try:
    import pexpect.spawnbase
    expect_base = pexpect.spawnbase.SpawnBase
except:
    import pexpect.fdpexpect
    expect_base = pexpect.spawn
import ttbl.target
import ttbl
import ttbl.cm_serial
import xmodem

class tt_galileo(
        ttbl.test_target,
        ttbl.test_target_images_mixin,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial):
    """Implements Galileo2 targets with serial console

    :param power_control: (optional) an instance of an implementation
      of the power_control_mixin used to implement power control for
      the target. Use ttbx.pc.manual() for manual power control that
      requires user interaction.
    """

    def __init__(self, id, serial_ports, _tags = None, power_control = None):
        ttbl.test_target.__init__(self, id, _tags = _tags)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.cm_serial.cm_serial.__init__(self, self.state_dir, serial_ports)
        self.image_name = None
        self.power_on_post_fns.append(tt_galileo.power_on_post_galileo)

    def image_do_set(self, image_type, image_name):
        """Take file *image_name* from target-broker storage for the
        current user and write it to the target as *image-type*.

        :param string image_type: Type of the image supported (only
          *kernel* is supported)
        :param string image_name: Name of image file in the daemon
          storage space for the user
        :raises: Any exception on failure

        This function has to be specialized for each target type. Upon
        finishing, it has to leave the target in the powered off state.

        """
        if image_type != "kernel" and image_type != "kernel-x86":
            raise Exception("%s: image type not supported (only "
                            "'kernel[-x86]')")

        self.log.info("rebooting to flash image %s:%s " \
                      % (image_type, image_name))
        # So here is the trick: we reboot the target--but by setting
        # `self.image_name` to a file name, the post-power up sequence
        # implemented by power_on_do_post() is redirected to do the
        # upload sequence and then we power off.
        try:
            self.image_name = image_name
            self.power_cycle(self.owner_get())
            self.image_name = None
        except:
            self.image_name = None
            raise
        self.log.info("powering off after flashing image %s:%s " \
                      % (image_type, image_name))
        self.power_off(self.owner_get())

    def images_do_set(self, images):
        pass

    def power_on_post_galileo(self):
        if self.image_name == None:
            self.power_on_post_boot()
        else:
            self.power_on_post_upload(self.image_name)

    def power_on_post_upload(self, image_name):
        """
        Power the target on, taking over the console to drive the
        galileo2 board to boot the Linux kernel file and upload a new
        TM kernel to the USB disk
        """
        self.log.info("post-power-up for flashing image %s" % image_name)
        # At this point we take control over the serial console, so
        # the ttbl.cm_serial.cm_serial has to stop reading for
        # us.
        with self.console_takeover() as (descr, log):
            e = pexpect.fdpexpect.fdspawn(descr, logfile = log, timeout = 20)
            ttbl.target.expect_send_sequence(
                self.log, e, self.kernel_upload_setup_cmd_list)

            log.write("\n[XMODEM file transfer of '%s' happened here]\n\n"
                      % image_name)
            self.log.info("xmodem-sending image %s" % image_name)
            xm = xmodem.XMODEM(
                lambda size, timeout = 1: descr.read(size),
                lambda data, timeout = 1: descr.write(data)
            )
            with file(image_name, 'rb') as f:
                xm.send(f)
                del xm

            ttbl.target.expect_send_sequence(
                self.log, e, self.kernel_upload_finish_cmd_list)

    def power_on_post_boot(self):
        """
        Power the target on, taking over the console to drive the
        galileo2 board to boot the kernel file flashed in the USB disk
        """
        self.log.info("post-power-up for boot to flashed image")
        with self.console_takeover() as (descr, log):
            e = pexpect.fdpexpect.fdspawn(descr, logfile = log, timeout = 20)
            ttbl.target.expect_send_sequence(
                self.log, e, self.kernel_boot_cmd_list)
        # From here on, the console returns to normal

    kernel_upload_setup_cmd_list = [
        # Wait for BIOS boot, speed through it
        ('Press [F7]    to show boot menu options.',
         "\r\n"),

        # Boot default grub 0.9 into Yocto Linux
        # FIXME: reduce 1 to 0.1?
        ('The highlighted entry will be booted automatically in ',
         "\r\n", 1),

        # Wait for Linux to bootup and login as default root
        ('clanton login:',
         "root\r\n"),

        # Give some time to the /dev/sda1 filesystem to be automounted and
        # then CD into the kernel directory
        # FIXME: while ! [ -d /media/sda1/kernel ]; do sleep 1s; done
        ('root@clanton:~# ',
         "sleep 4s; cd /media/sda1/efi/boot\r\n"),

        # Launch Xmodem receive
        ('root@clanton:/media/sda1/efi/boot# ',
         "../../utils/lrz -X kernel.file\r\n"),

        # Wait for Xmodem receive to be ready to start
        ('lrz: ready to receive kernel.file'),
    ]

    kernel_upload_finish_cmd_list = [
        # sync and umount the storage file system
        ('root@clanton:/media/sda1/efi/boot# ',
         "cd && sync && umount /media/sda1\r\n"),
        ('root@clanton:~# '),
    ]

    kernel_boot_cmd_list = [
        # Wait for BIOS boot, speed through it
        ('Press [F7]    to show boot menu options.',
         "\r\n"),

        # Exit to grub 0.9 command line, giving it some time to settle
        ('The highlighted entry will be booted automatically in ',
         "c\r\n", 0.1),

        # Exit grub 0.9 into EFI boot menu
        ('grub> ',
         "quit\r\n"),

        # At the EFI boot menu, scroll down to the Shell entry
        ('ESC to exit',
         # So we send three ESC[B commands (three arrow down) to
         # position the selection on the EFI Payload of the menu
         '\x1b[B\x1b[B\x1b[B\r\n',
         # Give time for the menu to print fully
         0.1),

        # FIXME: from EFI with available devices and option to skip
        # startup.nsh; just hit enter so it doesn't wait five seconds
        #('any other key to continue',
        # '\r\n'),

        # At the EFI shell, select device fs0: (the USB drive)
        ('Shell> ',
         "fs0:\r\n"),

        # Change into the efi\boot directory
        # FIXME: remove this and just run efi\boot\grub.efi directly
        ('fs0:\\> ',
         "cd efi\\boot\r\n"),

        # FIXME: Run grub straight up fs0:\efi\boot\grub.efi. Note
        # abolsute calling launches the menu in the current setup that
        # hasn't been cleaned up
        #('fs0:\\> ',
        # "efi\\boot\\grub.efi\r\n"),

        ('fs0:\\efi\\boot> ',
         "grub.efi\r\n"),

        # grub2 needs slowed down input, otherwise chars are lost of
        # misplaced -- not sure grub2 is at fault or another piece on
        # the chain, but onlt it seems affected
        # FIXME: add "; boot" and remove the last one
        ('grub> ',
         "multiboot (hd0,msdos1)/efi/boot/kernel.file; boot\r\n",
         0, 0.05),
    ]
