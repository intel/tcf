#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Flash binaries/images into the target
-------------------------------------

Interfaces and drivers to flash blobs/binaries/anything into targets;
most commonly these are firmwares, BIOSes, configuration settings that
are sent via some JTAG or firmware upgrade interface.

Interface implemented by :class:`ttbl.images.interface <interface>`,
drivers implemented subclassing :class:`ttbl.images.impl_c <impl_c>`.

"""

import collections
import json
import os
import subprocess
import time

import serial

import ttbl


class impl_c(object):
    """
    Driver interface for flashing with :class:`interface`
    """
    def __init__(self):
        pass

    def flash(self, target, images):
        """
        Flash *images* onto *target*

        :param ttbl.test_target target: target where to flash

        :param dict images: dictionary keyed by image type of the
          files (in the servers's filesystem) that have to be
          flashed.

        The implementation assumes, per configuration, that this
        driver knows how to flash the images of the given type (hence
        why it was configured) and shall abort if given an unknown
        type.

        If multiple images are given, they shall be (when possible)
        flashed all at the same time.
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(images, dict)
        raise NotImplementedError


class interface(ttbl.tt_interface):
    """
    Interface to flash a list of images (OS, BIOS, Firmware...) that
    can be uploaded to the target broker and flashed onto a target.

    Any image type can be supported, it is up to the configuration to
    set the image types and the driver that can flash them. E.g.:

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface({
    >>>         "kernel-x86": ttbl.openocd.pc(),
    >>>         "kernel-arc": "kernel-x86",
    >>>         "rom": ttbl.images.dfu_c(),
    >>>         "bootloader": ttbl.images.dfu_c(),
    >>>     })
    >>> )

    Aliases can be specified that will refer to the another type; in
    that case it is implied that images that are aliases will all be
    flashed in a single call. Thus in the example above, trying to
    flash an image of each type would yield three calls:

    - a single *ttbl.openocd.pc.flash()* call would be done for images
      *kernel-x86* and *kernel-arc*, so they would be flashed at the
      same time.
    - a single *ttbl.images.dfu_c.flash()* call for *rom*
    - a single *ttbl.images.dfu_c.flash()* call for *bootloader*

    If *rom* were an alias for *bootloader*, there would be a single
    call to *ttbl.images.dfu_c.flash()*.

    The imaging procedure might take control over the target, possibly
    powering it on and off (if power control is available). Thus,
    after flashing no assumptions shall be made and the safest one is
    to call (in the client) :meth:`target.power.cycle
    <tcfl.target_ext_power.extension.cycle>` to ensure the right
    state.

    """
    def __init__(self, **kwimpls):
        ttbl.tt_interface.__init__(self)
        self.impls_set([], kwimpls, impl_c)

    def _target_setup(self, target):
        target.tags_update(dict(images = self.impls.keys()))

    def _release_hook(self, target, _force):
        pass

    def put_flash(self,target, who, args, user_path):
        images = json.loads(self._arg_get(args, "images"))
        with target.target_owned_and_locked(who):
            # do a single call to one flasher with everything that
            # resolves to the same implementation from the aliases with
            # all those images
            v = collections.defaultdict(dict)
            for img_type, img_name in images.iteritems():
                # validate image types (from the keys) are valid from
                # the components and aliases
                _, img_type_real = self.impl_get_by_name(img_type,
                                                         "image type")
                v[img_type_real][img_type] = os.path.join(user_path, img_name)
            target.timestamp()
            # iterate over the real implementations only
            for img_type, subimages in v.iteritems():
                impl = self.impls[img_type]
                impl.flash(target, subimages)
            return {}

    # FIXME: save the names of the last flashed in fsdb so we can
    # query them? relative to USERDIR or abs to system where allowed
    def get_list(self, _target, _who, _args, _user_path):
        return dict(
            aliases = self.aliases,
            result = self.aliases.keys() + self.impls.keys())




class bossac_c(impl_c):
    """Flash with the `bossac <https://github.com/shumatech/BOSSA>`_ tool

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-arm": ttbl.images.bossac_c(),
    >>>         "kernel": "kernel-arm",
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str console: (optional) name of the target's console tied
       to the serial port; this is needed to disable it so this can
       flash. Defaults to *serial0*.

    *Requirements*

    - Needs a connection to the USB programming port, represented as a
      serial port (TTY)

    - *bossac* has to be available in the path variable :data:`path`.

    - (for Arduino Due) uses the bossac utility built on the *arduino*
      branch from https://github.com/shumatech/BOSSA/tree/arduino::

        $ git clone https://github.com/shumatech/BOSSA.git bossac.git
        $ cd bossac.git
        $ make -k
        $ sudo install -o root -g root bin/bossac /usr/local/bin

    - TTY devices need to be properly configured permission wise for
      bossac to work; for such, choose a Unix group which can get
      access to said devices and add udev rules such as::

        # Arduino2 boards: allow reading USB descriptors
        SUBSYSTEM=="usb", ATTR{idVendor}=="2a03", ATTR{idProduct}=="003d", \
          GROUP="GROUPNAME", MODE = "660"

        # Arduino2 boards: allow reading serial port
        SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "SERIALNUMBER", \
          GROUP = "GROUPNAME", MODE = "0660", \
          SYMLINK += "tty-TARGETNAME"

    For Arduino Due and others, the theory of operation is quite
    simple. According to
    https://www.arduino.cc/en/Guide/ArduinoDue#toc4, the Due will
    erase the flash if you open the programming port at 1200bps and
    then start a reset process and launch the flash when you open the
    port at 115200. This is not so clear in the URL above, but this is
    what expermientation found.

    So for flashing, we'll take over the console, set the serial
    port to 1200bps, wait a wee bit and then call bossac.

    """
    def __init__(self, serial_port = None, console = None):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self)
        self.serial_port = serial_port
        self.console = console

    #: Path to *bossac*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.bossac_c.path = "/usr/local/bin/bossac"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.bossac_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/bossac"
    path = "/usr/bin/bossac"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.items()))
        image_name = images.values()[0]

        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port
        if self.console == None:
            console = "serial0"
        else:
            console = self.console

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None)
        # erase the flash by opening the serial port at 1200bps
        target.log.debug("erasing the flash")
        with serial.Serial(port = serial_port, baudrate = 1200):
            time.sleep(0.25)
        target.log.info("erased the flash")

        # now write it
        cmdline = [
            self.path,
            "-p", os.path.basename(serial_port),
            "-e",       # Erase current
            "-w",	# Write a new one
            "-v",	# Verify,
            "-b",	# Boot from Flash
            image_name
        ]
        target.log.info("flashing image with: %s" % " ".join(cmdline))
        try:
            subprocess.check_output(
                cmdline, stdin = None, cwd = "/tmp",
                stderr = subprocess.STDOUT)
            target.log.info("ran %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (" ".join(cmdline),
                                e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None)
        target.log.info("flashed image")


class dfu_c(impl_c):
    """Flash the target with `DFU util <http://dfu-util.sourceforge.net/>`_

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-x86": ttbl.images.dfu_c(),
    >>>         "kernel-arc": "kernel-x86",
    >>>         "kernel": "kernel-x86",
    >>>     })
    >>> )

    :param str usb_serial_number: target's USB Serial Number

    *Requirements*

    - Needs a connection to the USB port that exposes a DFU
      interface upon boot

    - Uses the dfu-utils utility, available for most (if not all)
      Linux distributions

    - Permissions to use USB devices in */dev/bus/usb* are needed;
      *ttbd* usually roots with group *root*, which shall be
      enough.

    - In most cases, needs power control for proper operation, but
      some MCU boards will reset on their own afterwards.

    Note the tags to the target must include, on each supported
    BSP, a tag named *dfu_interface_name* listing the name of the
    *altsetting* of the DFU interface to which the image for said
    BSP needs to be flashed.

    This can be found, when the device exposes the DFU interfaces
    with the *lsusb -v* command; for example, for a tinyTILE
    (output summarized for clarity)::

      $ lsusb -v
      ...
      Bus 002 Device 110: ID 8087:0aba Intel Corp.
      Device Descriptor:
        bLength                18
        bDescriptorType         1
        ...
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update...
            iInterface              4 x86_rom
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update...
            iInterface              5 x86_boot
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              6 x86_app
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              7 config
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              8 panic
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              9 events
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             10 logs
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             11 sensor_core
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             12 ble_core

    In this case, the three cores available are x86 (x86_app), arc
    (sensor_core) and ARM (ble_core).

    *Example*

    A Tiny Tile can be connected, without exposing a serial console:

    >>> target = ttbl.test_target("ti-01")
    >>> target.interface_add(
    >>>     "power",
    >>>     ttbl.power.interface({
    >>>         ( "USB present",
    >>>           ttbl.pc.delay_til_usb_device("5614010001031629") ),
    >>>     })
    >>> )
    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-x86": ttbl.images.dfu_c("5614010001031629"),
    >>>         "kernel-arm": "kernel-x86",
    >>>         "kernel-arc": "kernel-x86",
    >>>         "kernel": "kernel-x86"
    >>>     })
    >>> )
    >>> ttbl.config.target_add(
    >>>     target,
    >>>     tags = {
    >>>         'bsp_models': { 'x86+arc': ['x86', 'arc'], 'x86': None, 'arc': None},
    >>>         'bsps' : {
    >>>             "x86":  dict(zephyr_board = "tinytile",
    >>>                          zephyr_kernelname = 'zephyr.bin',
    >>>                          dfu_interface_name = "x86_app",
    >>>                          console = ""),
    >>>             "arm":  dict(zephyr_board = "arduino_101_ble",
    >>>                          zephyr_kernelname = 'zephyr.bin',
    >>>                          dfu_interface_name = "ble_core",
    >>>                          console = ""),
    >>>             "arc": dict(zephyr_board = "arduino_101_sss",
    >>>                         zephyr_kernelname = 'zephyr.bin',
    >>>                         dfu_interface_name = 'sensor_core',
    >>>                         console = "")
    >>>         },
    >>>     },
    >>>     target_type = "tinytile"
    >>> )
    """

    def __init__(self, usb_serial_number):
        assert usb_serial_number == None \
            or isinstance(usb_serial_number, basestring)
        impl_c.__init__(self)
        self.usb_serial_number = usb_serial_number

    #: Path to the dfu-tool
    #:
    #: Change with
    #:
    #: >>> ttbl.images.dfu_c.path = "/usr/local/bin/dfu-tool"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.dfu_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/dfu-tool"
    path = "/usr/bin/dfu-tool"

    def flash(self, target, images):
        cmdline = [ self.path, "-S", self.usb_serial_number ]
        # for each image we are writing to a different interface, we
        # add a -a IFNAME -D IMGNAME to the commandline, so we can
        # flash multiple images in a single shot
        for image_type, image_name in images.iteritems():
            # FIXME: we shall make sure all images are like this?
            if not image_type.startswith("kernel-"):
                raise RuntimeError(
                    "Unknown image type '%s' (valid: kernel-{%s})"
                    % (image_type, ",".join(target.tags['bsps'].keys())))
            bsp = image_type.replace("kernel-", "")
            tags_bsp = target.tags.get('bsps', {}).get(bsp, None)
            if tags_bsp == None:
                raise RuntimeError(
                    "Unknown BSP %s from image type '%s' (valid: %s)"
                    % (bsp, image_type, " ".join(target.tags['bsps'].keys())))
            dfu_if_name = tags_bsp.get('dfu_interface_name', None)
            if dfu_if_name == None:
                raise RuntimeError(
                    "Misconfigured target: image type %s (BSP %s) has "
                    "no 'dfu_interface_name' key to indicate which DFU "
                    "interface shall it flash"
                    % (image_type, bsp))
            cmdline += [ "-a", dfu_if_name, "-D", image_name ]

        # Power cycle the board so it goes into DFU mode; it then
        # stays there for five seconds (FIXME: all of them?)
        target.power.put_cycle(target, ttbl.who_daemon(), {}, None)

        # let's do this
        try:
            target.log.info("flashing image with: %s" % " ".join(cmdline))
            subprocess.check_output(cmdline, cwd = "/tmp",
                                    stderr = subprocess.STDOUT)
            target.log.info("flashed with %s: %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s" %
                             (" ".join(cmdline), e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None)
        target.log.info("flashed image")


class esptool_c(impl_c):
    """
    Flash a target using Tensilica's *esptool.py*

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-xtensa": ttbl.images.esptool_c(),
    >>>         "kernel": "kernel-xtensa"
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str console: (optional) name of the target's console tied
       to the serial port; this is needed to disable it so this can
       flash. Defaults to *serial0*.

    *Requirements*

    - The ESP-IDF framework, of which ``esptool.py`` is used to
      flash the target; to install::

        $ cd /opt
        $ git clone --recursive https://github.com/espressif/esp-idf.git

      (note the ``--recursive``!! it is needed so all the submodules
      are picked up)

      configure path to it globally by setting
      :attr:`path` in a /etc/ttbd-production/conf_*.py file:

      .. code-block:: python

         import ttbl.tt
         ttbl.images.esptool_c.path = "/opt/esp-idf/components/esptool_py/esptool/esptool.py"

    - Permissions to use USB devices in */dev/bus/usb* are needed;
      *ttbd* usually roots with group *root*, which shall be
      enough.

    - Needs power control for proper operation; FIXME: pending to
      make it operate without power control, using ``esptool.py``.

    The base code will convert the *ELF* image to the required
    *bin* image using the ``esptool.py`` script. Then it will
    flash it via the serial port.
    """
    def __init__(self, serial_port = None, console = None):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self)
        self.serial_port = serial_port
        self.console = console

    #: Path to *esptool.py*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.esptool_c.path = "/usr/local/bin/esptool.py"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.esptool_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/esptool.py"
    path = "__unconfigured__ttbl.images.esptool_c.path__"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.items()))
        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port
        if self.console == None:
            console = "serial0"
        else:
            console = self.console

        cmdline_convert = [
            self.path,
            "--chip", "esp32",
            "elf2image",
        ]
        cmdline_flash = [
            self.path,
            "--chip", "esp32",
            "--port", serial_port,
            "--baud", "921600",
            "--before", "default_reset",
	    # with no power control, at least it starts
            "--after", "hard_reset",
            "write_flash", "-u",
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "detect",
            "0x1000",
        ]

        image_type = 'kernel'
        image_name = images.values()[0]
        image_name_bin = image_name + ".bin"
        try:
            cmdline = cmdline_convert + [ image_name,
                                          "--output", image_name_bin ]
            target.log.info("%s: converting with %s"
                            % (image_type, " ".join(cmdline)))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error("%s: converting image with %s failed: (%d) %s"
                             % (image_type, " ".join(cmdline),
                                e.returncode, e.output))
            raise

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None)
        try:
            cmdline = cmdline_flash + [ image_name_bin ]
            target.log.info("%s: flashing with %s"
                            % (image_type, " ".join(cmdline)))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
            target.log.info("%s: flashed with %s: %s"
                            % (image_type, " ".join(cmdline), s))
        except subprocess.CalledProcessError as e:
            target.log.error("%s: flashing with %s failed: (%d) %s"
                             % (image_type, " ".join(cmdline),
                                e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None)
        target.log.info("%s: flashing succeeded" % image_type)
