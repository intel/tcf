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

import codecs
import collections
import hashlib
import json
import os
import subprocess
import time

import serial

import commonl
import ttbl


class impl_c(ttbl.tt_interface_impl_c):
    """Driver interface for flashing with :class:`interface`

    Power control on different components can be done before and after
    flashing; the process is executed in the folowing order:

    - pre power off components
    - pre power cycle components
    - flash
    - post power off components
    - power power cycle components

    :param list(str) power_cycle_pre: (optional) before flashing,
      power cycle the target. Argument is a list of power rail
      component names.

      - *None* (default) do not power cycle
      - *[]*: power cycle all components
      - *[ *COMP*, *COMP* .. ]*: list of power components to power
        cycle

      From this list, anything in :data:power_exclude will be
      excluded.

    :param list(str) power_off_pre: (optional) before flashing, power
      off the given list of components; same specification as for
      :data:power_cycle_pre.

    :param list(str) power_cycle_post: (optional) after flashing, power
      cycle the given list of components; same specification as for
      :data:power_cycle_pre.

    :param list(str) power_off_post: (optional) after flashing, power
      off the given list of components; same specification as for
      :data:power_cycle_pre.

    :param list(str) power_exclude: (optional) list of power component
      names to exclude from any of the pre or post power cycle
      operations; this is useful when they are given as the default
      power rail (*[]*), but some components need to be excluded.

    :param list(str) console_disable: (optional) before flashing,
      disable consoles and then re-enable them. Argument is a list of
      console names that need disabling and then re-enabling.

    :param int estimated_duration: (optional; default 60) seconds the
      imaging process is believed to take. This can let the client
      know how long to wait for before declaring it took too long due
      to other issues out of server's control (eg: client to server
      problems).
    """
    def __init__(self,
                 power_cycle_pre = None,
                 power_off_pre = None,
                 power_cycle_post = None,
                 power_off_post = None,
                 power_exclude = None,
                 consoles_disable = None,
                 estimated_duration = 60):
        assert isinstance(estimated_duration, int)
        commonl.assert_none_or_list_of_strings(
            power_cycle_pre, "power_cycle_pre", "power component name")

        commonl.assert_none_or_list_of_strings(
            power_off_pre, "power_off_pre", "power component name")

        commonl.assert_none_or_list_of_strings(
            power_cycle_post, "power_cycle_post", "power component name")

        commonl.assert_none_or_list_of_strings(
            power_off_post, "power_off_post", "power component name")

        commonl.assert_none_or_list_of_strings(
            power_exclude, "power_exclude", "power component name")

        commonl.assert_none_or_list_of_strings(
            consoles_disable, "consoles_disable", "console name")

        self.power_cycle_pre = power_cycle_pre
        self.power_off_pre = power_off_pre
        self.power_cycle_post = power_cycle_post
        self.power_off_post = power_off_post
        self.power_exclude = power_exclude
        if consoles_disable == None:
            consoles_disable = []
        self.consoles_disable = consoles_disable
        self.estimated_duration = estimated_duration
        ttbl.tt_interface_impl_c.__init__(self)

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
    """Interface to flash a list of images (OS, BIOS, Firmware...) that
    can be uploaded to the target server and flashed onto a target.

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

    Whenever an image is flashed in a target's flash destination, a
    SHA512 hash of the file flashed is exposed in metadata
    *interfaces.images.DESTINATION.last_sha512*. This can be used to
    determine if we really want to flash (if you want to assume the
    flash doesn't change) or to select where do we want to run
    (because you want an specific image flashed).

    """
    def __init__(self, *impls, **kwimpls):
        ttbl.tt_interface.__init__(self)
        self.impls_set(impls, kwimpls, impl_c)

    def _target_setup(self, target, iface_name):
        for name, impl in self.impls.iteritems():
            target.fsdb.set(
                "interfaces.images." + name + ".estimated_duration",
                impl.estimated_duration)

    def _release_hook(self, target, _force):
        pass

    @staticmethod
    def _power_cycle(target, components, exclude):
        # power cycle the power rail components needed to flash
        #
        # Only if the implementation says it needs it and it supports
        # the power interface.
        if components == None:
            return
        if not hasattr(target, "power"):
            return
        args = {}
        if components:
            args['components'] = components
        if exclude:
            args['components_exclude'] = exclude
        target.power.put_cycle(target, ttbl.who_daemon(), args, None, None)

    @staticmethod
    def _power_off(target, components, exclude):
        # power off the power rail components needed to flash
        #
        # Only if the implementation says it needs it and it supports
        # the power interface.
        if components == None:
            return
        if not hasattr(target, "power"):
            return
        args = {}
        if components:
            args['components'] = components
        if exclude:
            args['components_exclude'] = exclude
        target.power.put_off(target, ttbl.who_daemon(), args, None, None)


    def _impl_flash(self, impl, target, img_type, subimages):
        self._power_off(target, impl.power_off_pre, impl.power_exclude)
        self._power_cycle(target, impl.power_cycle_pre, impl.power_exclude)
        try:
            # in some flashers, the flashing occurs over a
            # serial console we might be using, so we can
            # disable it -- we'll renable on exit--or not.
            # This has to be done after the power-cycle, as it might
            # be enabling consoles
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s: disabling console %s to allow flasher to work"
                    % (img_type, console_name))
                target.console.put_disable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)
            impl.flash(target, subimages)
            for image_type, name in subimages.items():
                # if succesful, update MD5s of the images we flashed,
                # so we can use this to select where we want to run
                #
                # Why not the name? because the name can change, but
                # the content never
                #
                # note this gives the same result as:
                #
                ## $ sha512sum FILENAME
                ho = commonl.hash_file(hashlib.sha512(), name)
                target.fsdb.set(
                    "interfaces.images." + image_type + ".last_sha512",
                    ho.hexdigest()
                )

            # note in case of flashing failure we don't
            # necessarily power on the components, since
            # things might be a in a bad state--we let the
            # user figure it out.
        finally:
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s: enabling console %s after flashing"
                    % (img_type, console_name))
                target.console.put_enable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)
        # note this might seem counterintuitive; the
        # configuration might specify some components are
        # switched off while others are power cycled, or none
        self._power_off(target, impl.power_off_post, impl.power_exclude)
        self._power_cycle(target, impl.power_cycle_post, impl.power_exclude)


    def put_flash(self, target, who, args, _files, user_path):
        images = self.arg_get(args, 'images', dict)
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
                v[img_type_real][img_type] = commonl.maybe_decompress(
                    os.path.join(user_path, img_name))
            target.timestamp()
            # iterate over the real implementations only
            for img_type, subimages in v.iteritems():
                impl = self.impls[img_type]
                self._impl_flash(impl, target, img_type, subimages)
            return {}

    # FIXME: save the names of the last flashed in fsdb so we can
    # query them? relative to USERDIR or abs to system where allowed
    def get_list(self, _target, _who, _args, _files, _user_path):
        return dict(
            aliases = self.aliases,
            result = self.aliases.keys() + self.impls.keys())


class arduino_cli_c(impl_c):
    """Flash with the `Arduino CLI <https://www.arduino.cc/pro/cli>`

    For example:

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-arm": ttbl.images.arduino_cli_c(),
    >>>         "kernel": "kernel-arm",
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str sketch_fqbn: (optional) name of FQBN to be used to
      program the board (will be passed on the *--fqbn* arg to
      *arduino-cli upload*).

    Other parameters described in :class:ttbl.images.impl_c.

    *Requirements*

    - Needs a connection to the USB programming port, represented as a
      serial port (TTY)

    .. _arduino_cli_setup:

    - *arduino-cli* has to be available in the path variable :data:`path`.

      To install Arduino-CLI::

        $ wget https://downloads.arduino.cc/arduino-cli/arduino-cli_0.9.0_Linux_64bit.tar.gz
        # tar xf arduino-cli_0.9.0_Linux_64bit.tar.gz  -C /usr/local/bin

      The boards that are going to be used need to be pre-downloaded;
      thus, if the board FQBN *XYZ* will be used and the daemon will
      be running as user *ttbd*::

        # sudo -u ttbd arduino-cli core update-index
        # sudo -u ttbd arduino-cli core install XYZ

      Each user that will compile for such board needs to do the same

    - target declares *sketch_fqbn* in the tags/properties for the BSP
      corresponding to the image. Eg; for *kernel-arm*::

        $ ~/t/alloc-tcf.git/tcf get arduino-mega-01 -p bsps
        {
            "bsps": {
                "arm": {
                    "sketch_fqbn": "arduino:avr:mega:cpu=atmega2560"
                }
            }
        }

      Corresponds to a configuration in the:

      .. code-block:: python

         target.tags_update(dict(
             bsps = dict(
                 arm = dict(
                     sketch_fqbn = "arduino:avr:mega:cpu=atmega2560",
                 ),
             ),
         ))

    - TTY devices need to be properly configured permission wise for
      the flasher to work; it will tell the *console* subsystem to
      disable the console so it can have exclusive access to the
      console to use it for flashing.

        SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "95730333937351308131", \
          SYMLINK += "tty-arduino-mega-01"

    """
    def __init__(self, serial_port = None, sketch_fqbn = None,
                 **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert sketch_fqbn == None or isinstance(sketch_fqbn, basestring)
        self.serial_port = serial_port
        self.sketch_fqbn = sketch_fqbn
        impl_c.__init__(self, **kwargs)
        self.upid_set("Arduino CLI Flasher", serial_port = serial_port)

    #: Path to *arduino-cli*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.arduino_cli_c.path = "/usr/local/bin/arduino-cli"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.arduino_cli_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/arduino-cli"
    path = "/usr/local/bin/arduino-cli"

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

        # remember this only handles one image type
        bsp = images.keys()[0].replace("kernel-", "")
        sketch_fqbn = self.sketch_fqbn
        if sketch_fqbn == None:
            # get the Sketch FQBN from the tags for the BSP
            sketch_fqbn = target.tags.get('bsps', {}).get(bsp, {}).get('sketch_fqbn', None)
            if sketch_fqbn == None:
                raise RuntimeError(
                    "%s: configuration error, needs to declare a tag"
                    " bsps.BSP.sketch_fqbn for BSP %s or a sketch_fqbn "
                    "to the constructor"
                    % (target.id, bsp))

        # Arduino Dues and others might need a flash erase
        if sketch_fqbn in [ "arduino:sam:arduino_due_x_dbg" ]:
            # erase the flash by opening the serial port at 1200bps
            target.log.debug("erasing the flash")
            with serial.Serial(port = serial_port, baudrate = 1200):
                time.sleep(0.25)
            target.log.info("erased the flash")

        # now write it
        cmdline = [
            self.path,
            "upload",
            "--port", serial_port,
            "--fqbn", sketch_fqbn,
            "--verbose",
            "--input", image_name
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
        target.log.info("flashed image")




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

    Other parameters described in :class:ttbl.images.impl_c.

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
    def __init__(self, serial_port = None, console = None, **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self, **kwargs)
        self.serial_port = serial_port
        self.console = console
        self.upid_set("bossac jtag", serial_port = serial_port)

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

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None, None)
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
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
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

    Other parameters described in :class:ttbl.images.impl_c.

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

    def __init__(self, usb_serial_number, **kwargs):
        assert usb_serial_number == None \
            or isinstance(usb_serial_number, basestring)
        impl_c.__init__(self, **kwargs)
        self.usb_serial_number = usb_serial_number
        self.upid_set("USB DFU flasher", usb_serial_number = usb_serial_number)

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
        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)

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
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
        target.log.info("flashed image")


class fake_c(impl_c):
    """
    Fake flashing driver (mainly for testing the interfaces)

    >>> flasher = ttbl.images.fake_c()
    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-BSP1": flasher,
    >>>         "kernel-BSP2": flasher,
    >>>         "kernel": "kernel-BSPNAME"
    >>>     })
    >>> )

    Parameters like :class:ttbl.images.impl_c.
    """
    def __init__(self, **kwargs):
        impl_c.__init__(self, **kwargs)
        self.upid_set("Fake test flasher", _id = str(id(self)))

    def flash(self, target, images):
        for image_type, image in images.items():
            target.log.info("%s: flashing %s" % (image_type, image))
            time.sleep(self.estimated_duration)
            target.log.info("%s: flashed %s" % (image_type, image))
        target.log.info("%s: flashing succeeded" % image_type)



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

    Other parameters described in :class:ttbl.images.impl_c.

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
    def __init__(self, serial_port = None, console = None, **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self, **kwargs)
        self.serial_port = serial_port
        self.console = console
        self.upid_set("ESP JTAG flasher", serial_port = serial_port)

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

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None, None)
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
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
        target.log.info("%s: flashing succeeded" % image_type)


class sf100linux_c(impl_c):
    """Flash Dediprog SF100 and SF600 with *dpcmd* from
    https://github.com/DediProgSW/SF100Linux

    :param str dediprog_id: ID of the dediprog to use (when multiple
      are available); this can be found by running *dpdmd --detect* with
      super user privileges (ensure they are connected)::

        # dpcmd
        DpCmd Linux 1.11.2.01 Engine Version:
        Last Built on May 25 2018

        Device 1 (SF611445):    detecting chip
        By reading the chip ID, the chip applies to [ MX66L51235F ]
        MX66L51235F chip size is 67108864 bytes.

      in here, *Device 1* has ID  *SF611445*. It is recommended to do
      this step only on an isolated machine to avoid confusions with
      other devices connected.

    :param int timeout: (optional) seconds to give the flashing
      process to run; if exceeded, it will raise an exception. This
      usually depends on the size of the binary being flashed and the
      speed of the interface.

    :param str mode: (optional; default "--batch") flashing mode, this
      can be:

      - *--prog*: programs without erasing
      - *--auto*: erase and update only sectors that changed
      - *--batch*: erase and program
      - *--erase*: erase

    :param dict args: dictionary of extra command line options to
      *dpcmd*; these are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>`:

      .. code-block:: python

         args = {
             # extra command line arguments for dpcmd
             'dediprog:id': 435,
         }

    Other parameters described in :class:ttbl.images.impl_c.

    **System setup**

    *dpcmd* is not packaged by most distributions, needs to be
    manuallly built and installed.

    1. build and install *dpcmd*::

         $ git clone https://github.com/DediProgSW/SF100Linux sf100linux.git
         $ make -C sf100linux.git
         $ sudo install -o root -g root \
             sf100linux.git/dpcmd sf100linux.git/ChipInfoDb.dedicfg \
             /usr/local/bin

       Note *dpcmd* needs to always be invoked with the full path
       (*/usr/local/bin/dpmcd*) so it will pick up the location of its
       database; otherwise it will fail to list, detect or operate.

    2. (optionally, if installed in another location) configure the
       path of *dpcmd* by setting :data:`path`.
    """
    def __init__(self, dediprog_id, args = None, name = None, timeout = 60,
                 mode = "--batch", **kwargs):
        assert isinstance(dediprog_id, basestring)
        assert isinstance(timeout, int)
        assert mode in [ "--batch", "--auto", "--prog", "--erase" ]
        commonl.assert_none_or_dict_of_strings(args, "args")

        if args:
            self.args = args
        else:
            self.args = {}
        self.dediprog_id = dediprog_id
        self.timeout = timeout
        self.mode = mode
        impl_c.__init__(self, **kwargs)
        if name == None:
            name = "Dediprog SF[16]00 " + dediprog_id
        self.upid_set(name, dediprog_id = dediprog_id)

    #: Path to *dpcmd*
    #:
    #: We need to use an ABSOLUTE PATH, as *dpcmd* relies on it to
    #: find its database.
    #:
    #: Change by setting, in a :ref:`server configuration file
    #: <ttbd_configuration>`:
    #:
    #: >>> ttbl.images.sf100linux_c.path = "/usr/local/bin/dpcmd"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.sf100linux_c.path(...)
    #: >>> imager.path =  "/opt/bin/dpcmd"
    path = "/usr/local/bin/dpcmd"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.iteritems()))
        image_name = images.values()[0]
        cmdline = [
            self.path,
            "--device", self.dediprog_id,
            "--silent",
            "--log", image_name + ".log",
            self.mode, image_name,
        ]
        for key, value in self.args.iteritems():
            cmdline += [ key, value % target.kws ]
        target.log.info("flashing image with: %s" % " ".join(cmdline))
        ts0 = time.time()
        ts = ts0
        try:
            p = subprocess.Popen(cmdline, stdin = None, cwd = "/tmp",
                                 stderr = subprocess.STDOUT)
            while ts - ts0 < self.timeout:
                returncode = p.poll()
                if returncode != None:
                    break		# process completed
                target.timestamp()	# timestamp so we don't idle...
                time.sleep(5)		# ...snooze
            else:
                msg = "flashing with %s failed: timedout after %ds" \
                    % (" ".join(cmdline), self.timeout)
                p.kill()
                raise RuntimeError(msg)
            target.log.info("ran %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (" ".join(cmdline),
                                e.returncode, e.output))
            raise
        # verify the logfile
        with codecs.open(image_name + ".log", errors = 'ignore') as logf:
            for line in logf:
                if 'Fail' in line:
                    logf.seek(0)
                    msg = "flashing with %s failed, issues in logfile: %s" \
                        % (" ".join(cmdline), logf.read())
                    target.log.error(msg)
                    raise RuntimeError(msg)
        target.log.info("flashed image")
