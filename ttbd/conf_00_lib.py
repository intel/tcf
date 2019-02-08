#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import copy
import errno
import logging
import os
import random
import re
import shutil
import subprocess
import time

import commonl
import ttbl
import ttbl.cm_serial
import ttbl.flasher
import ttbl.pc
import ttbl.usbrly08b
import ttbl.pc_ykush
import ttbl.tt

# OpenOCD paths -- multiple versions
sdk_path = os.path.join(
    os.environ.get("ZEPHYR_SDK_INSTALL_DIR", "/opt/zephyr-sdk-0.9.5"),
    "sysroots/x86_64-pokysdk-linux")
# From the Zephyr SDK
openocd_sdk_path = os.path.join(sdk_path, "usr/bin/openocd")
openocd_sdk_scripts = os.path.join(sdk_path, "usr/share/openocd/scripts")

# System installed 0.10
openocd_path = "/usr/bin/openocd"
openocd_scripts = "/usr/share/openocd/scripts"

def arduino101_add(name = None,
                   fs2_serial = None,
                   serial_port = None,
                   ykush_url = None,
                   ykush_serial = None,
                   variant = None,
                   openocd_path = openocd_sdk_path,
                   openocd_scripts = openocd_sdk_scripts,
                   debug = False,
                   build_only = False):
    """**Configure an Arduino 101 for the fixture described below**

    This Arduino101 fixture includes a Flyswatter2 JTAG which allows
    flashing, debugging and a YKUSH power switch for power control.

    Add to a server configuration file:

    .. code-block:: python

       arduino101_add(
         name = "arduino101-NN",
         fs2_serial = "arduino101-NN-fs2",
         serial_port = "/dev/tty-arduino101-NN",
         ykush_url = "http://USER:PASSWORD@HOST/SOCKET",
         ykush_serial = "YKXXXXX")

    restart the server and it yields::

      $ tcf list
      local/arduino101-NN

    :param str name: name of the target

    :param str fs2_serial: USB serial number for the FlySwatter2 (defaults
      to *TARGETNAME-fs2*

    :param str serial_port: name of the serial port  (defaults to
      ``/dev/tty-TARGETNAME``)

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub.

    :param str ykush_url: (optional) URL for the DLWPS7 power controller
      to the YKUSH. If *None*, the YKUSH is considered always on. See
      :py:func:`dlwps7_add`.

      FIXME: take a PC object so something different than a DLWPS7 can be
      used.

    **Overview**

    To power on the target, first we power the YKUSH, then the
    Flyswatter, then the serial port and then the board itself. And thus
    we need to wait for each part to correctly show up in the system
    after we power it up (or power off). Then the system starts OpenOCD
    to connect it (via the JTAG) to the board.

    Powering on/off the YKUSH is optional, but highly recommended.

    See the :ref:`rationale <arduino101_rationale>` for this complicated
    setup.

    **Bill of materials**

    - an available port on a DLWPS7 power switch (optional)

    - a Yepkit YKUSH power-switching hub (see bill of materials in
      :py:func:`ykush_targets_add`

    - an Arduino101 (note it must have original firmware; if you need
      to reset it, follow :ref:`these instructions
      <a101_fw_upgrade>`).

    - a USB A-Male to B-female for power to the Arduino 101

    - a USB-to-TTL serial cable for the console (power)

    - three M/M jumper cables

    - A Flyswatter2 for flashing and debugging

    3. Flash a new serial number on the Flyswatter2 following the
       :ref:`instructions <fs2_serial_update>`.

    - a USB A-Male to B-female for connecting the Flyswatter to the YKush
      (power and data)

    - An ARM-JTAG 20-10 adapter miniboard and flat ribbon cable
      (https://www.olimex.com/Products/ARM/JTAG/ARM-JTAG-20-10/) to
      connect the JTAG to the Arduino101's jtag port.

    **Connecting the test target fixture**

    1. connect the Arduino's USB port to the YKUSH downstream port 3

    2. Flyswatter2 JTAG:

      a. connect the USB port to the YKUSH downstream port 1

      b. flash a new serial number on the Flyswatter2 following the
         :ref:`instructions <fs2_serial_update>`.

         This is needed to distinguish multiple Flyswatter2 JTAGs
         connected in the same system, as they all come flashed with
         the same number (*FS20000*).

      c. connect the ARM-JTAG 20-10 adapter cable to the FlySwatter2 and
         to the Arduino101.

         Note the flat ribbon cable has to be properly aligned; the
         red cable indicates pin #1. The board connectors might have a
         dot, a number *1* or some sort of marking indicating where
         pin #1 is.

         If your ribbon cable has no red cable, just choose one end as
         one and align it on both boards to be pin #1.

    3. connect the USB-to-TTY serial adapter to the YKUSH downstream
       port 2

    4. connect the USB-to-TTY serial adapter to the Arduino 101 with the
       M/M jumper cables:

       - USB FTDI Black (ground) to Arduino101's serial ground pin
       - USB FTDI White (RX) to the Arduino101' TX
       - USB FTDI Green (TX) to Arduino101's RX.
       - USB FTDI Red (power) is left open, it has 5V.

    5. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *arduino101-NN* (where NN is a
       number)

    2. Find the YKUSH's serial number *YKNNNNN* [plug it and run *dmesg*
       for a quick find], see :py:func:`ykush_targets_add`.

    3. Configure *udev* to add a name for the serial device that
       represents the USB-to-TTY dongle connected to the target so we can
       easily find it at ``/dev/tty-TARGETNAME``. Different options for
       USB-to-TTY dongles :ref:`with <usb_tty_serial>` or :ref:`without
       <usb_tty_sibling>` a USB serial number.

    """
    if variant == None:
        _variant = ""
    elif variant == 'factory':
        _variant = "_factory"
    else:
        raise ValueError("variant '%s' not recognized" % variant)

    tags = {
        'bsp_models': {
            'x86+arc': [ 'x86', 'arc' ],
            'x86': None,
            'arc': None
        },
        'bsps' : {
            "x86":  dict(zephyr_board = "arduino_101" + _variant,
                         zephyr_kernelname = 'zephyr.bin',
                         kernelname = 'zephyr.bin',
                         board = "arduino_101" + _variant,
                         kernel = [ "unified", "micro", "nano" ],
                         console = ""),
            "arc": dict(zephyr_board = "arduino_101_sss" + _variant,
                        zephyr_kernelname = 'zephyr.bin',
                        board = "arduino_101_sss" + _variant,
                        kernelname = 'zephyr.bin',
                        console = "",
                        kernel = [ "unified", "nano" ])
        },
        'quark_se_stub': "yes",
        # How long to let this guy rest if we need to power cycle when
        # the JTAG gets all confused
        'hard_recover_rest_time': 7,
    }
    if build_only:
        tags['build_only'] = True
        ttbl.config.target_add(
            ttbl.test_target(name),
            tags = tags,
            target_type = "arduino101")
        return

    if fs2_serial == None:
        fs2_serial = name + "-fs2"
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c("arduino_101" + _variant, fs2_serial,
                                     openocd_path, openocd_scripts, debug)
    if ykush_url == None:
        pc_ykush = []
    else:
        pc_ykush = [
            ttbl.pc.dlwps7(ykush_url)
        ]
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, 3)
    pc_serial = ttbl.pc_ykush.ykush(ykush_serial, 2)
    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = pc_ykush + [
                ttbl.pc.delay_til_usb_device(serial = ykush_serial),
                ttbl.pc_ykush.ykush(ykush_serial, 1),	# Flyswatter2
                # delay power-on until the flyswatter2 powers up as a
                # USB device
                ttbl.pc.delay_til_usb_device(serial = fs2_serial),
                ttbl.pc.delay(2),			# JTAG powers up

                # The dongles fail a lot to get the serial port
                # plugged to UDEV, dunno why -- so if it fails, power
                # cycle the serial port dongle
                pc_serial,				# serial port
                ttbl.pc.delay_til_file_appears(
                    serial_port, poll_period = 4, timeout = 25,
                    action = pc_serial.power_cycle_raw,
                    action_args = (1,)
                ),
                ttbl.cm_serial.pc(),		# plug serial ports
                pc_board,			# board
                ttbl.pc.delay(1),		# board powers up...
                flasher                 	# Start / stop OpenOCD
            ]
        ),
        tags = tags,
        target_type = "arduino101")

def a101_dfu_add(name,
                 serial_number,
                 ykush_serial,
                 ykush_port_board,
                 ykush_port_serial = None,
                 serial_port = None):
    """\
    **Configure an Arduino 101**

    This is an Arduino101 fixture that uses an YKUSH hub for power
    control, with or without a serial port (via external USB-to-TTY
    serial adapter) and requires no JTAG, using DFU mode for
    flashing. It allows flashing the BLE core.

    Add to a server configuration file (eg:
    ``/etc/ttbd-production/conf_10_targets.py:``):

    .. code-block:: python

       a101_dfu_add("a101-NN", "SERIALNUMBER", "YKNNNNN", PORTNUMBER,
                    [ykush_port_serial = PORTNUMBER2,]
                    [serial_port = "/dev/tty-a101-NN"])

    restart the server and it yields::

      $ tcf list
      local/arduino101-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the Arduino 101

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub used for power control

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board is connected.

    :param int ykush_port_serial: (optional) number of the YKUSH
       downstream port where the board's serial port is connected. If
       not specified, it will be considered there is no serial port.

    :param str serial_port: (optional) name of the serial port
      (defaults to ``/dev/tty-NAME``)


    **Overview**

    The Arduino 101 is powered via the USB connector. The Arduino 101
    does not export a serial port over the USB connector--applications
    loaded onto it might create a USB serial port, but this is not
    necessarily so all the time.

    Thus, for ease of use this fixture connects an optional external
    USB-to-TTY dongle to the TX/RX/GND lines of the Arduino 101 that
    allows a reliable serial console to be present.

    When the serial dongle is in use, the power rail needs to first
    power up the serial dongle and then the board.

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    This fixture uses :class:`ttbl.tt.tt_dfu` to implement the target;
    refer to it for implementation details.


    **Bill of materials**

    - two available ports on an YKUSH power switching hub (serial
      *YKNNNNN*); only one if the serial console will not be used.
    - an Arduino 101 board
    - a USB A-Male to micro-B male cable (for board power)
    - (optional) a USB-to-TTY serial port dongle
    - (optional) three M/M jumper cables

    **Connecting the test target fixture**

    1. (if not yet connected), connect the YKUSH to the server system
       and to power as described in :py:func:`ykush_targets_add`

    2. connect the Arduino 101's USB port to the YKUSH downstream port
       *PORTNUMBER*

    3. (if a serial console will be connected) connect the USB-to-TTY
       serial adapter to the YKUSH downstream port *PORTNUMBER2*

    3. (if a serial console will be connected) connect the USB-to-TTY
       serial adapter to the Arduino 101 with the M/M jumper cables:

       - USB FTDI Black (ground) to Arduino 101's serial ground pin
         (fourth pin from the bottom)
       - USB FTDI White (RX) to the Arduino 101's TX.
       - USB FTDI Green (TX) to Arduino 101's RX.
       - USB FTDI Red (power) is left open, it has 5V.

    **Configuring the system for the fixture**

    1. Choose a name for the target: *a101-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`.

       Note these boards, when freshly plugged in, will only stay in
       DFU mode for *five seconds* and then boot Zephyr (or whichever
       OS they have), so the USB device will dissapear. You need to
       run the lsusb or whichever command you are using quick (or
       monitor the kernel output with *dmesg -w*).

    4. Configure *udev* to add a name for the serial device that
       represents the USB-to-TTY dongle connected to the target so we can
       easily find it at ``/dev/tty-a101-NN``. Different options for
       USB-to-TTY dongles :ref:`with <usb_tty_serial>` or :ref:`without
       <usb_tty_sibling>` a USB serial number.

    5. Add to the configuration file (eg:
       ``/etc/ttbd-production/conf_10_targets.py``):

       .. code-block:: python

          a101_dfu_add("a101-NN", "SERIALNUMBER", "YKNNNNN", PORTNUMBER,
                       ykush_port_serial = PORTNUMBER2,
                       serial_port = "/dev/tty-a101-NN")
    """
    if ykush_port_serial:
        if serial_port == None:
            serial_port = "/dev/tty-" + name
        power_rail = [
            ttbl.pc_ykush.ykush(ykush_serial, ykush_port_serial),
            ttbl.pc.delay_til_file_appears(serial_port),
            ttbl.cm_serial.pc()
        ]
    else:
        power_rail = []
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    power_rail += [
        pc_board,
        ttbl.pc.delay_til_usb_device(serial_number)
    ]

    ttbl.config.target_add(
        ttbl.tt.tt_dfu(name, serial_number, power_rail, pc_board,
                       serial_ports = [
                           "pc",
                           dict(port = serial_port, baudrate = 115200)
                       ]),
        tags = {
            'bsp_models': {
                'x86+arc+arm': ['x86', 'arc', 'arm'],
                'x86+arc': ['x86', 'arc'],
                'x86+arm': ['x86', 'arm'],
                'arc+arm': ['arc', 'arm'],
                'x86': None,
                'arm': None,
                'arc': None
            },
            "quark_se_stub": 'yes',
            'bsps' : {
                "x86":  dict(zephyr_board = "arduino_101",
                             zephyr_kernelname = 'zephyr.bin',
                             dfu_interface_name = "x86_app",
                             console = ""),
                "arm":  dict(zephyr_board = "arduino_101_ble",
                             zephyr_kernelname = 'zephyr.bin',
                             dfu_interface_name = "ble_core",
                             console = ""),
                "arc": dict(zephyr_board = "arduino_101_sss",
                            zephyr_kernelname = 'zephyr.bin',
                            dfu_interface_name = 'sensor_core',
                            console = "")
            },
        },
        target_type = "arduino101_dfu"
    )


def esp32_add(name,
              serial_number,
              ykush_serial,
              ykush_port_board,
              serial_port = None):
    """\
    **Configure an ESP-32 MCU board**

    The ESP-32 is an Tensillica based MCU, implementing two Xtensa
    CPUs. This fixture uses an YKUSH hub for power control with a
    serial power over the USB cable which is also used to flash using
    ``esptool.py`` from the ESP-IDF framework.

    See instructions in :class:`ttbl.tt.tt_esp32` to install and
    configure prerequisites in the server.

    Add to a server configuration file (eg:
    ``/etc/ttbd-production/conf_10_targets.py:``):

    .. code-block:: python

       esp32_add("esp32-NN", "SERIALNUMBER", "YKNNNNN", PORTNUMBER)

    restart the server and it yields::

      $ tcf list
      local/esp32-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the *esp32*

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub used for power control

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board is connected.

    :param str serial_port: (optional) name of the serial port
      (defaults to ``/dev/tty-NAME``)


    **Overview**

    The ESP32 offers the same USB connector for serial port and flashing.

    **Bill of materials**

    - one available port on an YKUSH power switching hub (serial
      *YKNNNNN*)
    - an ESP32 board
    - a USB A-Male to micro-B male cable

    **Connecting the test target fixture**

    1. (if not yet connected), connect the YKUSH to the server system
       and to power as described in :py:func:`ykush_targets_add`

    2. connect the esp32's USB port to the YKUSH downstream port
       *PORTNUMBER*

    **Configuring the system for the fixture**

    0. See instructions in :class:`ttbl.tt.tt_esp32` to install and
       configure prerequisites in the server.

    1. Choose a name for the target: *esp32-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`.

       Note these boards usually have a serial number of *001*; it can
       be updated easily to a unique serial number following
       :ref:`these steps  <cp210x_serial_update>`.

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)

    ttbl.config.target_add(
        ttbl.tt.tt_esp32(name, serial_number,
                         power_control = [
                             pc_board,
                             # delay until the board powers up and
                             # it's built in flasher comes online as a
                             # USB device -- if it doesn't come up,
                             # power cycle it
                             ttbl.pc.delay_til_usb_device(serial_number),
                             # No need to delay until the serial port file
                             # appears, let the console logger figure that
                             # out, as it retries a few times
                             ttbl.cm_serial.pc(),
                         ],
                         serial_port = serial_port),
        tags = {
            'bsp_models': {
                'xtensa': None,
            },
            'bsps' : {
                "xtensa":  dict(zephyr_board = "esp32",
                                zephyr_kernelname = 'zephyr.elf',
                                console = ""),
            },
        },
        target_type = "esp32"
    )


def mv_add(name = None,
           fs2_serial = None,
           serial_port = None,
           ykush_serial = None,
           ykush_port_board = None,
           ykush_port_serial = None,
           openocd_path = openocd_sdk_path,
           openocd_scripts = openocd_sdk_scripts,
           debug = False):
    """**Configure a Quark D2000 for the fixture described below.**

    The Quark D2000 development board includes a Flyswatter2 JTAG which allows
    flashing, debugging; it requires two upstream connections to
    a YKUSH power-switching hub for power and JTAG and another for serial
    console.

    Add to a server configuration file:

    .. code-block:: python

       mv_add(name = "mv-NN",
              fs2_serial = "mv-NN-fs2",
              serial_port = "/dev/tty-mv-NN",
              ykush_serial = "YKXXXXX",
              ykush_port_board = N1,
              ykush_port_serial = N2)

    restart the server and it yields::

      $ tcf list
      local/mv-NN

    :param str name: name of the target

    :param str fs2_serial: USB serial number for the FlySwatter2 (should
      be *TARGETNAME-fs2* [FIXME: default to that]

    :param str serial_port: name of the serial port  [FIXME: default to
      /dev/tty-TARGETNAME]

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    :param int ykush_port_serial: number of the YKUSH downstream port
      where the board's serial port is connected.

    **Overview**

    The Quark D2000 board comes with a builtin JTAG / Flyswatter, whose
    port can be programmed. The serial port is externally provided via a
    USB-to-TTY dongle.

    However, because of this, to power the test target up the power rail
    needs to first power up the serial dongle and then the board. There
    is a delay until the internal JTAG device we can access it, thus we
    need a delay before the system starts OpenOCD to connect it (via the
    JTAG) to the board.

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - two available ports on an YKUSH power switching hub (serial *YKNNNNN*)
    - a Quark D2000 reference board
    - a USB A-Male to micro-B male cable (for board power)
    - a USB-to-TTY serial port dongle
    - three M/M jumper cables

    **Connecting the test target fixture**

    1. connect the Quark D2000's USB-ATP port with the USB A-male to
       B-micro to YKUSH downstream port *N1* for powering the board

    2. connect the USB-to-TTY serial adapter to the YKUSH downstream
       port *N2*

    3. connect the USB-to-TTY serial adapter to the Quark D2000 with the
       M/M jumper cables:

       - USB FTDI Black (ground) to board's serial ground pin
       - USB FTDI White (RX) to the board's serial TX ping
       - USB FTDI Green (TX) to board's serial RX pin
       - USB FTDI Red (power) is left open, it has 5V.

    4. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *mv-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Flash a new serial number on the Flyswatter2 following the
       :ref:`instructions <fs2_serial_update>`.

    4. Configure *udev* to add a name for the serial device that
       represents the USB-to-TTY dongle connected to the target so we can
       easily find it at ``/dev/tty-TARGETNAME``. Different options for
       USB-to-TTY dongles :ref:`with <usb_tty_serial>` or :ref:`without
       <usb_tty_sibling>` a USB serial number.

    6. Ensure the board is flashed with the Quark D2000 ROM (as
       described :ref:`here <fw_update_d2000>`).

    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c("quark_d2000_crb_v8", fs2_serial,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    pc_serial = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_serial)

    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            # FIXME: note the serial number does not match the device name
            flasher = flasher,
            power_control = [
                # The MVs fail a lot to get the serial port plugged to
                # UDEV, dunno why -- so if it fails, power cycle the
                # serial port dongle
                pc_serial,				# serial port
                ttbl.pc.delay_til_file_appears(
                    serial_port, poll_period = 4, timeout = 25,
                    action = pc_serial.power_cycle_raw,
                    action_args = (1,)
                ),
                ttbl.cm_serial.pc(),			# plug serial ports
                pc_board,				# board
                # give the board some time to come up
                ttbl.pc.delay(on = 2),
                # delay until the board powers up and it's built in flasher
                # comes online as a USB device -- if it doesn't come
                # up, power cycle it
                ttbl.pc.delay_til_usb_device(
                    fs2_serial,
                    poll_period = 10,
                    action = pc_board.power_cycle_raw,
                    # must be a sequence!
                    action_args = (2,)
                ),
                # Start/kill OpenOCD as needed when the board is powered
                flasher,
            ]
        ),
        tags = {
            'bsp_models': { 'x86': None },
            'bsps' : {
                'x86': dict(zephyr_board = 'quark_d2000_crb',
                            zephyr_kernelname = 'zephyr.bin',
                            board = 'quark_d2000_crb',
                            kernelname = 'zephyr.bin',
                            kernel = [ "unified", "nano" ],
                            console=''),
            },
            'quark_se_stub': "no",
            # Flashes really slow, give it more time
            'slow_flash_factor': 5,
        },
        target_type = "mv")


def nrf5x_add(name,
              serial_number,
              family,
              serial_port = None,
              ykush_serial = None,
              ykush_port_board = None,
              openocd_path = openocd_path,
              openocd_scripts = openocd_scripts,
              debug = False):
    """**Configure a NRF51 board for the fixture described below**

    The NRF51 is an ARM M0-based development board. Includes a builting
    JTAG which allows flashing, debugging; it only requires one upstream
    connection to a YKUSH power-switching hub for power, serial console
    and JTAG.

    Add to a server configuration file:

    .. code-block:: python

       nrf5x_add(name = "nrf51-NN",
                 serial_number = "SERIALNUMBER",
                 ykush_serial = "YKXXXXX",
                 ykush_port_board = N)

    restart the server and it yields::

      $ tcf list
      local/nrf51-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the board

    :param str family: Family of the board (*nrf51_blenano*,
        *nrf51_pca10028*, *nrf52840_pca10056*, *nrf52_blenano2*,
        *nrf52_pca10040*)
    :param str serial_port: (optional) name of the serial port, which
      defaults to ``/dev/tty-TARGETNAME``.

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - a nrf51 board
    - a USB A-Male to micro-B male cable (for board power, JTAG and console)
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. connect the FRDM's USB port with the USB A-male to B-micro to
       YKUSH downstream port *N*

    2. ensure the battery is disconnected

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *nrf51-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.
    """
    assert isinstance(family, basestring) \
        and family in [ "nrf51_blenano",
                        "nrf51_pca10028",
                        "nrf52840_pca10056",
                        "nrf52_blenano2",
                        "nrf52_pca10040" ]
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c(family, serial_number,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)

    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                pc_board,		# power switch for the board
                # delay until device comes up
                ttbl.pc.delay_til_usb_device(serial_number, poll_period = 5,
                                             timeout = 30),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25),
                ttbl.cm_serial.pc(),	# Connect serial ports
                flasher,            	# Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models' : { 'arm': None },
            'bsps' : {
                "arm":  dict(zephyr_board = family,
                             zephyr_kernelname = 'zephyr.hex',
                             kernelname = 'zephyr.hex',
                             board = family,
                             console = ""),
            },
            # Flash verification is really slow, give it more time
            'slow_flash_factor': 5,
            'flash_verify': 'False',
        },
        target_type = family)


def frdm_add(name = None,
             serial_number = None,
             serial_port = None,
             ykush_serial = None,
             ykush_port_board = None,
             openocd_path = openocd_path,
             openocd_scripts = openocd_scripts,
             debug = False):
    """**Configure a FRDM board for the fixture described below**

    The FRDM k64f is an ARM-based development board. Includes a builting
    JTAG which allows flashing, debugging; it only requires one upstream
    connection to a YKUSH power-switching hub for power, serial console
    and JTAG.

    Add to a server configuration file:

    .. code-block:: python

       frdm_add(name = "frdm-NN",
                serial_number = "SERIALNUMBER",
                serial_port = "/dev/tty-frdm-NN",
                ykush_serial = "YKXXXXX",
                ykush_port_board = N)

    restart the server and it yields::

      $ tcf list
      local/frdm-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the FRDM board

    :param str serial_port: name of the serial port  [FIXME: default to
      /dev/tty-TARGETNAME]

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - a FRDM k64f board
    - a USB A-Male to micro-B male cable (for board power, JTAG and console)
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. connect the FRDM's OpenSDA port with the USB A-male to B-micro to
       YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *frdm-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    .. warning::

        Ugly magic here. The FRDMs sometimes boot into some bootloader
        upload mode (with a different USB serial number) from which the
        only way to get them out is by power-cycling it.

        So the power rail for this thing is set with a Power Controller
        object that does the power cycle itself (pc_board) and then
        another that looks for a USB device with the right serial number
        (serial_number). If it fails to find it, it executes an action
        and waits for it to show up. The action is power cycling the USB
        device with the pc_board power controller. Lastly, in the power
        rail, we have the glue that opens the serial ports to the device
        and the flasher object that start/stops OpenOCD.

        Yup, I dislike computers too.
    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c("frdm_k64f", serial_number,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)

    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                pc_board,		# power switch for the board
                # delay until device comes up
                ttbl.pc.delay_til_usb_device(
                    serial_number,
                    poll_period = 5,
                    timeout = 30,
                    action = pc_board.power_cycle_raw,
                    # must be a sequence!
                    action_args = (4,)
                ),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25,
                ),
                ttbl.cm_serial.pc(),	# Connect serial ports
                flasher,            	# Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models' : { 'arm': None },
            'bsps' : {
                "arm":  dict(zephyr_board = "frdm_k64f",
                             zephyr_kernelname = 'zephyr.bin',
                             kernelname = 'zephyr.bin',
                             board = "frdm_k64f",
                             kernel = [ "unified", "micro", "nano" ],
                             console = ""),
            },
            'quark_se_stub': "no",
            # Flash verification is really slow, give it more time
            'slow_flash_factor': 5,
            'flash_verify': 'False',
        },
        target_type = "frdm_k64f")

def arduino2_add(name = None,
                 serial_number = None,
                 serial_port = None,
                 ykush_serial = None,
                 ykush_port_board = None,):
    """**Configure an Arduino Due board for the fixture described below**

    The Arduino Due an ARM-based development board. Includes a builtin
    flasher that requires the bossac tool. Single wire is used for
    flashing, serial console and power.

    Add to a server configuration file:

    .. code-block:: python

       arduino2_add(name = "arduino2-NN",
                    serial_number = "SERIALNUMBER",
                    serial_port = "/dev/tty-arduino2-NN",
                    ykush_serial = "YKXXXXX",
                    ykush_port_board = N)

    restart the server and it yields::

      $ tcf list
      local/arduino2-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the board

    :param str serial_port: name of the serial port (defaults to
      /dev/tty-TARGETNAME).

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - an Arduino Due board
    - a USB A-Male to micro-B male cable (for board power, flashing
      and console)
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. connect the Arduino Due's OpenSDA (?) port with the USB A-male
       to B-micro to YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *arduino2-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.
    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    ttbl.config.target_add(
        ttbl.tt.tt_arduino2(
            name,
            serial_port = serial_port,
            power_control = [
                pc_board,
                # delay until the board powers up and it's built in
                # flasher comes online as a USB device -- if it
                # doesn't come up, power cycle it
                ttbl.pc.delay_til_usb_device(
                    serial_number,
                    poll_period = 10,
                    action = pc_board.power_cycle_raw,
                    # must be a sequence!
                    action_args = (2,)
                    ),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25,
                ),
                ttbl.cm_serial.pc(),
            ],
            bossac_cmd = "bossac"),
        tags = {
            'bsp_models': { 'arm': None },
            'bsps' : {
                "arm": dict(zephyr_board = "arduino_due",
                            zephyr_kernelname = 'zephyr.bin',
                            sketch_fqbn = "sam:1.6.9:arduino_due_x_dbg",
                            sketch_kernelname = "sketch.ino.bin",
                            board = "arduino_due",
                            kernelname = 'zephyr.bin',
                            console = "",
                            kernel = [ "unified", "micro", "nano" ] )
            },
            'quark_se_stub': "no",
        },
        target_type = "arduino2")

def ma_add(name = None,
           serial_number = None,
           serial_port = None,
           ykush_serial = None,
           ykush_port_board = None,
           openocd_path = openocd_sdk_path,
           openocd_scripts = openocd_sdk_scripts,
           debug = False):
    quark_c1000_add(name, serial_number, serial_port,
                    ykush_serial, ykush_port_board,
                    openocd_path, openocd_scripts, debug,
                    variant = "qc10000_crb")

def quark_c1000_add(name = None,
                    serial_number = None,
                    serial_port = None,
                    ykush_serial = None,
                    ykush_port_board = None,
                    openocd_path = openocd_sdk_path,
                    openocd_scripts = openocd_sdk_scripts,
                    debug = False,
                    variant = "qc10000_crb", target_type = "ma"):
    """**Configure a Quark C1000 for the fixture described below**

    The Quark C1000 development board has a built-in JTAG which allows
    flashing, debugging, thus it only requires an upstream connection
    to a YKUSH power-switching hub for power, serial console and JTAG.

    This board has a USB serial number and should not require any
    flashing of the USB descriptors for setup.

    Add to a server configuration file:

    .. code-block:: python

       quark_c1000_add(name = "qc10000-NN",
                       serial_number = "SERIALNUMBER",
                       ykush_serial = "YKXXXXX",
                       ykush_port_board = N)

    restart the server and it yields::

      $ tcf list
      local/qc10000-NN

    earlier versions of these boards can be added with the *ma_add()* and
    *ah_add()* versions of this function.

    :param str name: name of the target

    :param str serial_number: USB serial number for the Quark C1000 board

    :param str serial_port: name of the serial port  [FIXME: default to
      /dev/tty-TARGETNAME]

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    :param str variant: variant of ROM version and address map as
      defined in (FIXME) flasher configuration.

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)
    - a Quark C1000 reference board
    - a USB A-Male to micro-B male cable (for board power, JTAG and console)

    **Connecting the test target fixture**

    1. connect the Quark C1000's FTD_USB port with the USB A-male to
       B-micro to YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *qc10000-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

       Note, **however** that these boards might present two serial
       ports to the system, one of which later converts to another
       interface. So in order to avoid configuration issues, the right
       port has to be explicitly specified with `ENV{ID_PATH} == "*:1.1"`::

         # Force second interface, first is for JTAG/update
         SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "IN0521621", \
           ENV{ID_PATH} == "*:1.1", \
           SYMLINK += "tty-TARGETNAME"


    """
#
# FIXME: re-add once verified to work
#
#    5. Ensure the board is flashed with the Quark C1000 ROM. This can be
#       obtained from https://github.com/quark-mcu/qm-bootloader.
#
#       Use the command, once the target is added to the system::
#
#         $ tcf acquire qc10000-NN
#         $ tcf images-upload-set qc10000-NN rom:quark_se_rom.bin
#
    if serial_port == None:
        serial_port = "/dev/tty-" + name
    flasher = ttbl.flasher.openocd_c(variant, serial_number,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                pc_board,			# Board control
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25,
                    action = pc_board.power_cycle_raw,
                    action_args = (1,)
                ),
                ttbl.cm_serial.pc(),		# plug serial ports
                ttbl.pc.delay(2),		# JTAG+board powers up...
                flasher                 	# Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models': {
                'x86+arc': [ 'x86', 'arc' ],
                'x86': None,
                'arc': None
            },
            'bsps' : {
                "x86":  dict(zephyr_board = "quark_se_c1000_devboard",
                             zephyr_kernelname = 'zephyr.bin',
                             board = "quark_se_c1000_devboard",
                             kernelname = 'zephyr.bin',
                             kernel = [ "unified", "micro", "nano" ],
                             console = ""),
                "arc": dict(zephyr_board = "quark_se_c1000_ss_devboard",
                            zephyr_kernelname = 'zephyr.bin',
                            board = "quark_se_c1000_ss_devboard",
                            kernelname = 'zephyr.bin',
                            console = "",
                            kernel = [ "unified", "nano" ])
            },
            'quark_se_stub': "yes",
        },
        target_type = target_type)


def nios2_max10_add(name,
                    device_id,
                    serial_port_serial_number,
                    pc_board,
                    serial_port = None):
    """**Configure an Altera MAX10 NIOS-II**

    The `Altera MAX10
    <https://www.altera.com/products/fpga/max-series/max-10/overview.html>`_
    is used to implement a NIOS-II CPU; it has a serial port, JTAG for
    flashing and power control.

    The USB serial port is based on a FTDI chipset with a serial
    number, so it requires no modification. However, the JTAG
    connector has no serial number and can be addressed only path.

    Add to a server configuration file:

    .. code-block:: python

       nios2_max10_add("max10-NN",
                       "CABLEID",
                       "SERIALNUMBER",
                       ttbl.pc.dlwps7("http://admin:1234@HOST/PORT"))

    restart the server and it yields::

      $ tcf list
      local/max10-NN

    :param str name: name of the target

    :param str cableid: identification of the JTAG for the board; this
      can be determined using the *jtagconfig* tool from the Quartus
      Programming Tools; make sure only a single board is connected to
      the system and powered on and run::

        $ jtagconfig
        1) USB-BlasterII [2-2.1]
          031050DD   10M50DA(.|ES)/10M50DC

      Note *USB-BlasterII [2-2.1]* is the cable ID for said board.

      .. warning:: this cable ID is path dependent. Moving any of the
                   USB cables (including the upstream hubs), including
                   changing the ports to which the cables are
                   connected, will change the *cableid* and will
                   require re-configuration.

    :param str serial_number: USB serial number for the serial port of
      the MAX10 board.

    :param str serial_port: name of the serial port  [defaults to
      /dev/tty-TARGETNAME]

    :param ttbl.tt_power_control_impl pc: power controller to switch
      on/off the MAX10 board.

    **Bill of materials**

    - Altera MAX10 reference board

    - Altera MAX10 power brick

    - a USB A-Male to mini-B male cable (for JTAG)

    - a USB A-Male to mini-B male cable (for UART)

    - an available power socket in a power controller like the :class:`Digital
      Loggers Web Power Switch <ttbl.pc.dlwps7>`

    - two USB ports leading to the server

    **Connecting the test target fixture**

    1. connect the power brick to the MAX10 board

    2. connect the power plug to port N of the power controller
       POWERCONTROLLER

    3. connect a USB cable to the UART connector in the MAX10; connect
       to the server

    4. connect a USB cable to the JTAG connector in the MAX10; connect
       to the server

    5. ensure the DIP SW2 (back of board) are all OFF except for 3
       that has to be on and that J7 (front of board next to coaxial
       connectors) is open.

    **Configuring the system for the fixture**

    1. Ensure the system is setup for MAX10 boards:

       - Setup :data:`ttbl.tt.tt_max10.quartus_path`
       - Setup :data:`ttbl.tt.tt_max10.input_sof`

    2. Choose a name for the target: *max10-NN* (where NN is a number)

    3. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*; e.g.::

         SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "AC0054PT", \
           SYMLINK += "tty-max10-46"

    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    ttbl.config.target_add(
        ttbl.tt.tt_max10(
            name,
            device_id,
            [
                pc_board,
                # delay until the board powers up and it's built in
                # flasher comes online as a USB device -- if it
                # doesn't come up, power cycle it
                ttbl.pc.delay_til_usb_device(serial_port_serial_number),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 1, timeout = 25,
                ),
                ttbl.cm_serial.pc(),
            ],
            serial_port = serial_port,
        ),

        tags = {
            'bsp_models': { 'nios2': None },
            'bsps' : {
                'nios2': dict(zephyr_board = "altera_max10",
                              zephyr_kernelname = 'zephyr.hex',
                              console = "")
            },
        },
        target_type = "max10")

#
# Configurations settings for STM32
#
# FIXME: move to conf_00_lib_stm32.py for clarity?
#

stm32_models = dict()

ttbl.flasher.openocd_c._addrmaps['unneeded'] = dict(
    # FIXME: we need this so the mappings in flasher.c don't get all
    # confused
    arm = dict()
)


ttbl.flasher.openocd_c._boards['disco_l475_iot1'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f2x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/disco_l475_iot1/support/openocd.cfg
#
source [find interface/stlink.cfg]

transport select hla_swd
hla_serial "%(serial_string)s"

source [find target/stm32l4x.cfg]

reset_config srst_only
""")


ttbl.flasher.openocd_c._boards['nucleo_f103rb'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f2x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/nucleo_f103rb/support/openocd.cfg
#
source [find board/st_nucleo_f103rb.cfg]
hla_serial "%(serial_string)s"
# From https://sourceforge.net/p/openocd/tickets/178/, makes reset work ok
reset_config srst_only connect_assert_srst

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}
"""
)


ttbl.flasher.openocd_c._boards['nucleo_f207zg'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f2x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/nucleo_f207zg/support/openocd.cfg
#
source [find interface/stlink-v2-1.cfg]
hla_serial "%(serial_string)s"
source [find target/stm32f2x.cfg]
# From https://sourceforge.net/p/openocd/tickets/178/, makes reset work ok
reset_config srst_only connect_assert_srst

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}

"""
)


ttbl.flasher.openocd_c._boards['nucleo_f429zi'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f4x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/nucleo_f429zi/support/openocd.cfg
#
source [find board/st_nucleo_f4.cfg]
hla_serial "%(serial_string)s"

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}
"""
)


ttbl.flasher.openocd_c._boards['nucleo_f746zg'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f7x.cpu' },
    write_command = "flash write_image erase %(file)s %(address)s",
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/nucleo_f746zg/support/openocd.cfg
#
source [find board/st_nucleo_f7.cfg]
hla_serial "%(serial_string)s"

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}
"""
)


ttbl.flasher.openocd_c._boards['nucleo_l073rz'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f2x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/nucleo_l073rz/support/openocd.cfg
#
# This is an ST NUCLEO-L073RZ board with single STM32L073RZ chip.
# http://www.st.com/en/evaluation-tools/nucleo-l073rz.html
source [find interface/stlink.cfg]

transport select hla_swd
hla_serial "%(serial_string)s"

set WORKAREASIZE 0x2000

source [find target/stm32l0.cfg]

# Add the second flash bank.
set _FLASHNAME $_CHIPNAME.flash1
flash bank $_FLASHNAME stm32lx 0 0 0 0 $_TARGETNAME

# There is only system reset line and JTAG/SWD command can be issued when SRST
reset_config srst_only

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}
""")


ttbl.flasher.openocd_c._boards['stm32f3_disco'] = dict(
    addrmap = 'unneeded',	# unneeded
    targets = [ 'arm' ],
    target_id_names = { 0: 'stm32f2x.cpu' },
    write_command = "flash write_image erase %(file)s",
    # FIXME: until we can set a verify_command that doesn't do
    # addresses, we can't enable this
    verify = False,
    config = """\
#
# openocd.cfg configuration from zephyr.git/boards/arm/stm32f3_disco/support/openocd.cfg
#
source [find board/stm32f3discovery.cfg]
hla_serial "%(serial_string)s"

$_TARGETNAME configure -event gdb-attach {
        echo "Debugger attaching: halting execution"
        reset halt
        gdb_breakpoint_override hard
}

$_TARGETNAME configure -event gdb-detach {
        echo "Debugger detaching: resuming execution"
        resume
}
""")


def stm32_add(name = None,
              serial_number = None,
              serial_port = None,
              ykush_serial = None,
              ykush_port_board = None,
              openocd_path = openocd_path,
              openocd_scripts = openocd_scripts,
              model = None,
              zephyr_board = None,
              debug = False):
    """**Configure an Nucleo/STM32 board**

    The Nucleo / STM32 are ARM-based development board. Includes a
    builting JTAG which allows flashing, debugging; it only requires
    one upstream connection to a YKUSH power-switching hub for power,
    serial console and JTAG.

    Add to a server configuration file:

    .. code-block:: python

       stm32_add(name = "stm32f746-67",
                 serial_number = "066DFF575251717867114355",
                 ykush_serial = "YK23406",
                 ykush_port_board = 3,
                 model = "stm32f746")

    restart the server and it yields::

      $ tcf list
      local/stm32f746-67

    :param str name: name of the target

    :param str serial_number: USB serial number for the board

    :param str serial_port: (optional) name of the serial port
      (defaults to /dev/tty-TARGETNAME).

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board is connected.

    :param str openocd_path: (optional) path to where the OpenOCD
      binary is installed (defaults to system's).

      .. warning:: Zephyr SDK 0.9.5's version of OpenOCD is not able
                   to flash some of these boards.

    :param str openocd_scripts: (optional) path to where the OpenOCD
      scripts are installed (defaults to system's).

    :param str model: String which describes this model to the OpenOCD
      configuration. This matches the model of the board in the
      packaging. E.g:

      - stm32f746
      - stm32f103

      see below for the mechanism to add more via configuration

    :param str zephyr_board: (optional) string to configure as the
      board model used for Zephyr builds. In most cases it will be
      inferred automatically.

    :param bool debug: (optional) operate in debug mode (more verbose
      log from OpenOCD) (defaults to false)

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - one STM32* board
    - a USB A-Male to micro-B male cable (for board power, flashing
      and console)
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. connect the STM32 micro USB port with the USB A-male
       to B-micro to YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *stm32MODEL-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    5. Add the configuration block described at the top of this
       documentation and restart the server

    **Extending configuration for new models**

    Models not supported by current configuration can be expanded by
    adding a configuration block such as:

    .. code-block:: python

       import ttbl.flasher
       ttbl.flasher.openocd_c._addrmaps['stm32f7'] = dict(
           arm = dict(load_addr = 0x08000000)
       )

       ttbl.flasher.openocd_c._boards['stm32f746'] = dict(
           addrmap = 'stm32f7',
           targets = [ 'arm' ],
           target_id_names = { 0: 'stm32f7x.cpu' },
           write_command = "flash write_image erase %(file)s %(address)s",
           config = \"\""\
       #
       # openocd.cfg configuration from zephyr.git/boards/arm/stm32f746g_disco/support/openocd.cfg
       #
       source [find board/stm32f7discovery.cfg]

       $_TARGETNAME configure -event gdb-attach {
	echo "Debugger attaching: halting execution"
	reset halt
	gdb_breakpoint_override hard
       }

       $_TARGETNAME configure -event gdb-detach {
	echo "Debugger detaching: resuming execution"
	resume
       }

       \"\"\"
       )

       stm32_models['stm32f746'] = dict(zephyr = "stm32f746g_disco")


    """
    if model in (
            "nucleo_f746zg",
            # OpenOCD complains
            # Warn : Cannot identify target as a STM32L4 family.
            # Error: auto_probe failed
            'disco_l475_iot1',
            # OpenOCD complains
            # Error: open failed
            # in procedure 'init'
            # in procedure 'ocd_bouncer'
            'stm32f3_disco',
    ):
        logging.error("WARNING! %s not configuring as this board is still "
                      "not supported" % name)
        return

    if serial_port == None:
        serial_port = "/dev/tty-" + name

    if zephyr_board == None:
        # default to the same as model if there is no entry in the
        # dict or no 'zephyr' tag on it
        zephyr_board = stm32_models.get(model, {}).get('zephyr', model)
    flasher = ttbl.flasher.openocd_c(model, serial_number,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)

    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                pc_board,		# power switch for the board
                # delay until device comes up
                ttbl.pc.delay_til_usb_device(
                    serial_number,
                    poll_period = 1,
                    timeout = 30,
                    action = pc_board.power_cycle_raw,
                    # must be a sequence!
                    action_args = (4,)
                ),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 1, timeout = 25,
                ),
                ttbl.cm_serial.pc(),	# Connect serial ports
                flasher,            	# Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models' : { 'arm': None },
            'bsps' : {
                "arm":  dict(zephyr_board = zephyr_board,
                             # STM32 loads, in most cases, with no
                             # destination address; they are obtained
                             # from the ELF file, so we use the ELF file.
                             zephyr_kernelname = 'zephyr.elf',
                             soc = "stm32",
                             console = ""),
            },
            'power_cycle_wait': 0.5,
        },
        target_type = model)
    # We still don't have the nucleos fully supported
    ttbl.config.targets[name].disable('')


def nucleo_add(name = None,
               serial_number = None,
               serial_port = None,
               ykush_serial = None,
               ykush_port_board = None,
               openocd_path = openocd_path,
               openocd_scripts = openocd_scripts,
               debug = False):
    """
    **Configure an Nucleo F10 board**

    This is a backwards compatiblity function, please use :func:`stm32_add`.
    """
    stm32_add(name,
              serial_number,
              serial_port,
              ykush_serial,
              ykush_port_board,
              openocd_path,
              openocd_scripts,
              "nucleo_f103rb",
              "nucleo_f103rb",
              debug)


def ykush_targets_add(ykush_serial, pc_url, powered_on_start = None):
    """Given the :ref:`serial number <ykush_serial_number>` for an YKUSH
    hub connected to the system, set up a number of targets to
    manually control it.

    - (maybe) one target to control the whole hub

    - One target per port *YKNNNNN-1* to *YKNNNNN-3* to control the three
      ports individually; this is used to debug powering up different
      parts of a target.

    .. code-block:: python

       ykush_targets_add("YK34567", "http://USER:PASSWD@HOST/4")

    yields::

      $ tcf list
      local/YK34567
      local/YK34567-base
      local/YK34567-1
      local/YK34567-2
      local/YK34567-3

    To use then the YKUSH hubs as power controllers, create instances of
    :py:class:`ttbl.pc_ykush.ykush`:

    .. code-block:: python

       ttbl.pc_ykush.ykush("YK34567", PORT)

    where *PORT* is 1, 2 or 3.

    :param str ykush_serial: USB Serial Number of the hub
      (:ref:`finding <ykush_serial_number>`).

    :param str pc_url: Power Control URL

     - A DLPWS7 URL (:py:class:`ttbl.pc.dlwps7`), if given, will create a
       target *YKNNNNN* to power on or off the whole hub and wait for it
       to connect to the system.

       It will also create one called *YKNNNN-base* that allows to power
       it off or on, but will not wait for the USB device to show up in
       the system (useful for poking the power control to the hub when it
       is failing to connect to the system)

     - If None, no power control targets for the whole hub will be
       created. It will just be expected the hub is connected permanently
       to the system.

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are

      - *False*: power them off

      - *True*: power them on

    **Bill of materials**

    - YKUSH hub and it's :ref:`serial number <ykush_serial_number>`

      Note the hub itself has no serial number, but an internal device
      connected to its downstream port number 4 does have the *YK34567*
      serial number.

    - a male to mini-B male cable for power

    - a USB brick for power

      - (optional) a DLWPS7 power switch to control the hub's power

      - or an always-on connection to a power plug

    - a male to micro-B male cable for upstream USB connectivity

    - an upstream USB B-female port to the server (in a hub or root hub)

    Note the *YKNNNNN* targets are always tagged *idle_poweroff = 0*
    (so they are never automatically powered off) but not
    *skip_cleanup*; the later would never release them when idle and
    if a recovery fails somewhere, then none would be able to
    re-acquire it to recover.

    """
    assert isinstance(ykush_serial, basestring)
    if pc_url != None:
        assert isinstance(pc_url, basestring)
    if powered_on_start != None:
        assert isinstance(powered_on_start, bool)

    # First add the base target, with no expectations in case it
    # doesn't show in USB, so wec an manipulate it to diagnose
    if pc_url == "manual":
        pc_base = ttbl.pc.manual(ykush_serial)
    elif pc_url == None:
        pc_base = ttbl.pc.delay_til_usb_device(serial = ykush_serial)
    else:
        pc_base = ttbl.pc.dlwps7(pc_url)

    ttbl.config.target_add(
        ttbl.tt.tt_power(ykush_serial + "-base",
                         power_control = pc_base,
                         power = True),
        # Always keep them on, unless we decide otherwise--we need
        # them to control other components
        tags = dict(idle_poweroff = 0))
    ttbl.config.targets[ykush_serial + "-base"].disable("")

    # Now try to add the one that expects to find the USB device; this
    # can fail if the USB device doesn't show up for whichever reason
    if pc_url == "manual":
        pc = [
            ttbl.pc.manual(ykush_serial),
            ttbl.pc.delay_til_usb_device(serial = ykush_serial),
        ],
    elif pc_url == None:
        pc = ttbl.pc.delay_til_usb_device(serial = ykush_serial)
    else:
        pc = [
            ttbl.pc.dlwps7(pc_url),
            ttbl.pc.delay_til_usb_device(serial = ykush_serial,
                                         timeout = 5, poll_period = 1),
        ]

    ttbl.config.target_add(
        ttbl.tt.tt_power(ykush_serial,
                         power_control = pc,
                         power = True),
        # Always keep them on, unless we decide otherwise--we need
        # them to control other components
        tags = dict(idle_poweroff = 0))
    ttbl.config.targets[ykush_serial].disable("")

    for _port in [ 1, 2, 3]:
        ttbl.config.target_add(
            ttbl.tt.tt_power("%s-%d" % (ykush_serial, _port),
                             ttbl.pc_ykush.ykush(ykush_serial, _port),
                             power = powered_on_start),
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(idle_poweroff = 0))
        ttbl.config.targets["%s-%d" % (ykush_serial, _port)].disable("")

def usbrly08b_targets_add(serial_number, target_name_prefix = None,
                          power = False):
    """Set up individual power control targets for each relay of a
    `Devantech USB-RLY08B
    <https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm>`_

    See below for configuration steps

    :param str serial_number: USB Serial Number of the relay board
      (:ref:`finding <usbrly08b_serial_number>`).

    :param str target_name_prefix: (optional) Prefix for the target
      names (which defaults to *usbrly08b-SERIALNUMBER-*)

    **Bill of materials**

    - A Devantech USB-RLY08B USB relay controller
      (https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm)

    - a USB A-Male to B-female to connect it to the server

    - an upstream USB A-female port to the server (in a hub or root hub)

    **Connecting the relay board to the system**

    1. Connect the USB A-Male to the free server USB port

    2. Connect the USB B-Male to the relay board

    **Configuring the system for the fixture**

    1. Choose a prefix name for the target (eg: *re00*) or let it be
       the default (*usbrly08b-SERIALNUMBER*).

    2. Find the relay board's :ref:`serial number
       <usbrly08b_serial_number>` (:ref:`more methods <find_usb_info>`)

    3. Ensure the device node for the board is accessible by the user
       or groups running the daemon. See
       :py:class:`ttbl.usbrly08b.pc` for details.

    3. To create individual targets to control each individual relay,
       add in a configuration file such as
       ``/etc/ttbd-production/conf_10_targets.py``:

       .. code-block:: python

          usbrly08b_targets_add("00023456")

       which yields, after restarting the server::

         $ tcf list -a
         local/usbrly08b-00023456-01
         local/usbrly08b-00023456-02
         local/usbrly08b-00023456-03
         local/usbrly08b-00023456-04
         local/usbrly08b-00023456-05
         local/usbrly08b-00023456-06
         local/usbrly08b-00023456-07

       To use the relays as power controllers on a power rail for
       another target, create instances of
       :py:class:`ttbl.usbrly08b.pc`:

       .. code-block:: python

          ttbl.usbrly08b.pc("0023456", RELAYNUMBER)

       where *RELAYNUMBER* is 1 - 8, which matches the number of the
       relay etched on the board.

    """
    if target_name_prefix == None:
        target_name_prefix = "usbrly08b-" + serial_number
    for relay in range(1, 9):
        name = "%s-%02d" % (target_name_prefix, relay)
        ttbl.config.target_add(
            ttbl.tt.tt_power(name,
                             ttbl.usbrly08b.pc(serial_number, relay),
                             power = power),
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(idle_poweroff = 0))

def emsk_add(name = None,
             serial_number = None,
             serial_port = None,
             brick_url = None,
             ykush_serial = None,
             ykush_port = None,
             openocd_path = openocd_sdk_path,
             openocd_scripts = openocd_sdk_scripts,
             debug = False,
             model = None):
    """Configure a Synposis EM Starter Kit (EMSK) board configured for a
    EM* SOC architecture, with a power brick and a YKUSH USB port
    providing power control.

    The board includes a builting JTAG which allows flashing,
    debugging; it only requires one upstream connection to a YKUSH
    power-switching hub for power, serial console and JTAG.

    Add to a server configuration file:

    .. code-block:: python

       emsk_add(name = "emsk-NN",
                serial_number = "SERIALNUMBER",
                ykush_serial = "YKXXXXX",
                ykush_port_board = N,
                model = "emsk7d")

    restart the server and it yields::

      $ tcf list
      local/emsk-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the board

    :param str serial_port: name of the serial port (defaults to
      /dev/tty-TARGETNAME).

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    :param str brick_url: URL for the power switch to which the EMSK's
      power brick is connected (this assumes for now you are using a
      DLWPS7 for power, so the url witll be in the form
      http://user:password@hostname/port.

    :param str model: SOC model configured in the board with the blue
      DIP switches (from *emsk7d* [default], *emsk9d*, *emsk11d*).

      ==== ==== ==== ==== =====
      DIP1 DIP2 DIP3 DIP4 Model
      ==== ==== ==== ==== =====
      off  off            em7d
      on   off            em9d
      off  on             em11d
      ==== ==== ==== ==== =====

      (*on* means DIP down, towards the board)

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - a EM Starter Kit board and its power brick
    - a USB A-Male to micro-B male cable (for board power, flashing
      and console)
    - one available port on a switchable power hub
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. connect the EMSK's micro USB port with the USB A-male
       to B-micro to YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    3. Connect the power brick to the EMSK's power barrel

    4. Connect the power brick to the available power in the power switch

    **Configuring the system for the fixture**

    1. Choose a name for the target: *emsk-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    """
    zephyr_boards = dict(
        emsk7d_v22 = 'em_starterkit_em7d_v22',
        emsk7d = 'em_starterkit_em7d',
        emsk11d = 'em_starterkit_em11d',
        emsk9d = 'em_starterkit'
    )
    assert model in zephyr_boards, \
        "Please specify a model (%s) as per the DIP configuration " \
        "and firmware loaded" % ", ".join(zephyr_boards.keys())
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c("snps_em_sk", serial_number,
                                     openocd_path, openocd_scripts, debug)
    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                ttbl.pc.dlwps7(brick_url),
                ttbl.pc_ykush.ykush(ykush_serial, ykush_port),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25,
                ),
                ttbl.cm_serial.pc(),		# plug serial ports
                # delay power-on until the flyswatter2 powers up as a
                # USB device
                ttbl.pc.delay_til_usb_device(serial = serial_number),
                ttbl.pc.delay(1),		# board powers up...
                flasher                 	# Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models': { 'arc': None},
            'bsps' : {
                "arc": dict(zephyr_board = zephyr_boards[model],
                            zephyr_kernelname = 'zephyr.elf',
                            console = "")
            },
            'quark_se_stub': "no",
            # How long to let this guy rest if we need to power cycle when
            # the JTAG gets all confused
            'hard_recover_rest_time': 7,
        },
        target_type = model)

def dlwps7_add(hostname, powered_on_start = None,
               user = "admin", password = "1234"):
    """Add test targets to individually control each of a DLWPS7's sockets

    The DLWPS7 needs to be setup and configured; this function exposes
    the different targets for to expose the individual sockets for debug.

    Add to a configuration file
    ``/etc/ttbd-production/conf_10_targets.py`` (or similar):

    .. code-block:: python

       dlwps7_add("sp6")

    yields::

      $ tcf list
      local/sp6-1
      local/sp6-2
      local/sp6-3
      local/sp6-4
      local/sp6-5
      local/sp6-6
      local/sp6-7
      local/sp6-8

    Power controllers for targets can be implemented instantiating an
    :py:class:`ttbl.pc.dlwps7`:

    .. code-block:: python

       pc = ttbl.pc.dlwps7("http://admin:1234@spM/O")

    where *O* is the outlet number as it shows in the physical unit and
    *spM* is the name of the power switch.

    :param str hostname: Hostname of the switch

    :param str user: User name for HTTP Basic authentication

    :param str password: password for HTTP Basic authentication

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are

      - *False*: power them off

      - *True*: power them on

    **Overview**

    **Bill of materials**

    - a DLWPS7 unit and power cable connected to power plug

    - a network cable

    - a connection to a network switch to which the server is also
      connected (*nsN*)

    **Connecting the power switch**

    1. Ensure you have configured an class C *192.168.X.0/24*,
       configured with static IP addresses, to which maybe only this
       server has access to connect IP-controlled power
       switches.

       Follow :ref:`these instructions <internal_network>` to create a
       network.

       You might need a new Ethernet adaptor to connect to said
       network (might be PCI, USB, etc).

    2. connect the power switch to said network

    3. assign a name to the power switch and add it along its IP
       address in ``/etc/hosts``; convention is to call them *spY*,
       where X is a number and *sp* stands for *Switch; Power*.

       .. warning:: if your system uses proxies, you need to add *spY*
          also to the *no_proxy* environment varible in
          :file:`/etc/bashrc` to avoid the daemon trying to access the
          power switch through the proxy, which will not work.

    4. with the names ``/etc/hosts``, refer to the switches by name
       rather than by IP address.

    **Configuring the system**

    1. Choose a name for the power switch (*spM*), where *M* is a number

    2. The power switch starts with IP address *192.168.0.100*; it needs
       to be changed to *192.168.X.M*:

       a. Connect to *nsN*

       b. Ensure the server access to *192.168.0.100* by adding this
          routing hack::

            # ifconfig nsN:2 192.168.0.0/24

       c. With lynx or a web browser, from the server, access the
          switch's web control interface::

          $ lynx http://192.168.0.100

       d. Enter the default user *admin*, password *1234*, select *ok*
          and indicate *A* to always accept cookies

          .. warning: keep the default user and password at
                      *admin*/*1234*, the default configuration relies
                      on it. It makes no sense to change it anyway as
                      you will have to write them down in the
                      configuration. Limitations of HTTP Basic Auth

       e. Hit enter to refresh link redirecting to
          *192.168.0.100/index.htm*, scroll down to *Setup*,
          select. On all this steps, make sure to hit submit for each
          individual change.

          1. Lookup setup of IP address, change to *192.168.N.M* (where *x*
             matches *spM*), gateway *192.168.N.1*; hit the *submit* next to
             it.

          2. Disable the security lockout in section *Delay*

             Set *Wrong password lockout* set to zero minutes

          3. Turn on setting power after power loss:

             *Power Loss Recovery Mode > When recovering after power
             loss* select *Turn all outlets on*

          4. Extra steps needed for newer units
             (https://dlidirect.com/products/new-pro-switch)

             The new refreshed unit looks the same, but has wifi
             connectivity and pleny of new features, some of which
             need tweaking; login to the setup page again and for each
             of this, set the value/s and hit *submit* before going to
             the next one:

             - Access setings (quite important, as this allows the
               driver to access the same way for the previous
               generation of the product too):

               ENABLE: *allow legacy plaintext login methods*

               Note in (3) below it is explained why this is not a
               security problem in this kind of deployments.

       g. remove the routing hack::

            # ifconfig nsN:2 down

    3. The unit's default admin username and password are kept per
       original (admin, 1234):

       - They are deployed in a dedicated network switch that is internal
         to the server; none has access but the server users (targets run
         on another switch).

       - they use HTTP Basic Auth, they might as well not use
         authentication

    4. Add an entry in ``/etc/hosts`` for *spM* so we can refer to the
       DLWPS7 by name instead of IP address::

         192.168.4.X	spM

    """
    for i in range(1, 9):
        name = "%s-%d" % (hostname, i)
        pc_url = "http://%s:%s@%s/%d" % (user, password, hostname, i)
        ttbl.config.target_add(
            ttbl.tt.tt_power(name, ttbl.pc.dlwps7(pc_url),
                             power = powered_on_start),
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(idle_poweroff = 0))
        ttbl.config.targets[name].disable("")

class vlan_pci(ttbl.tt_power_control_impl):
    """Fake power controller to implement networks using macvtap
    for virtual machines and bridges for physical devices.

    This behaves as a power control implementation that when turned:

    - on: starts an internal network a `macvtap
      http://virt.kernelnewbies.org/MacVTap` Linux device that allows
      virtual machines to talk to each other and to the outside. When
      a physical device is also present, it is used as the upper
      device (instead of a bridge) so traffic can flow from physical
      targets to the virtual machines in the network.

    - off: stops all the network devices, making communication impossible.

    This also supports capturing network traffic with *tcpdump*, which
    can be enabled setting the target's property *tcpdump*::

      $ tcf property-set TARGETNAME tcpdump FILENAME

    this will have the target dump all traffic capture to a file
    called *FILENAME* in the daemon file storage area for the user who
    owns the target. The file can then be recovered with::

      $ tcf broker-file-download FILENAME

    *FILENAME* must be a valid file name, with no directory
    components. Note this requires the property *tcpdump* being listed
    in :data:`ttbl.test_target.user_properties`, which is added after
    this class declaration.

    Example configuration:

    >>> ttbl.config.target_add(
    >>>     ttbl.tt.tt_power("nw01", vlan_pci()),
    >>>     tags = {
    >>>         'ipv6_addr': 'fc00::1:1',
    >>>         'ipv4_addr': '192.168.1.1',
    >>>         'ipv4_prefix_len': 24,
    >>>         'mac_addr': '02:01:01:00:00:24:',
    >>>     })
    >>> ttbl.config.targets['nw01'].tags.['interfaces'].append('interconnect_c')

    Now QEMU targets (for example), can declare they are part of this
    network and upon start, create a tap interface for themselves::

      $ ip link add link _bnw01 name tnw01TARGET type macvtap mode bridge
      $ ip link set tnw01TARGET address 02:01:00:00:00:IC_INDEX up

    which then is given to QEMU as an open file descriptor::

      -net nic,model=virtio,macaddr=02:01:00:00:00:IC_INDEX
      -net tap,fd=FD

   (:py:class:`Linux <tt_qemu_linux>` and
   :py:class:`Zephyr <tt_qemu_zephyr>` VMs already
   implement this behaviour).

    Notes:

    - keep target names short, as they will be used to generate
      network interface names and those are limited in size (usually to
      about 12 chars?), eg tnw01TARGET comes from *nw01* being the
      name of the network target/interconnect, TARGET being the target
      connected to said interconnect.

    - IC_INDEX: is the index of the TARGET in the interconnect/network;
      it is recommended, for simplicty to make them match with the mac
      address, IP address and target name, so for example:

      - targetname: pc-04
      - ic_index: 04
      - ipv4_addr: 192.168.1.4
      - ipv6_addr: fc00::1:4
      - mac_addr: 02:01:00:00:00:04

    If a tag named *mac_addr* is given, containing the MAC address
    of a physical interface in the system, then it will be taken over
    as the point of connection to external targets. Connectivity from
    any virtual machine in this network will be extended to said
    network interface, effectively connecting the physical and virtual
    targets.

    .. warning:: DISABLE Network Manager's (or any other network
                 manager) control of this interface, otherwise it will
                 interfere with it and network will not operate.

                 Follow :ref:`these steps <howto_nm_disable_control>`

    System setup:

    - *ttbd* must be ran with CAP_NET_ADMIN so it can create network
       interfaces. For that, either add to systemd's
       ``/etc/systemd/system/ttbd@.service``::

         CapabilityBoundingSet = CAP_NET_ADMIN
         AmbientCapabilities = CAP_NET_ADMIN

      or as root, give ttbd the capability::

        # setcap cap_net_admin+pie /usr/bin/ttbd

    - *udev*'s */etc/udev/rules.d/ttbd-vlan*::

        SUBSYSTEM == "macvtap", ACTION == "add", DEVNAME == "/dev/tap*", \
            GROUP = "ttbd", MODE = "0660"

      This is needed so the tap devices can be accessed by user
      *ttbd*, which is the user that runs the daemon.

      Remember to reload *udev*'s configuration with `udevadm control
      --reload-rules`.

      This is already taken care by the RPM installation.

    **Fixture setup**

    - Select a network interface to use (it can be a USB or PCI
      interface); find out it's MAC address with *ip link show*.

    - add the tag *mac_addr* with said address to the tags of the
      target object that represents the network to which which said
      interface is to be connected; for example, for a network called
      *nwc*

      .. code-block:: python

         ttbl.config.target_add(
             ttbl.tt.tt_power('nwc', vlan_pci()),
             tags = dict(
                 mac_addr = "a0:ce:c8:00:18:73",
                 ipv6_addr = 'fc00::13:1',
                 ipv6_prefix_len = 112,
                 ipv4_addr = '192.168.13.1',
                 ipv4_prefix_len = 24,
             )
         )
         ttbl.config.targets['NAME'].tags['interfaces'].append('interconnect_c')

      or for an existing network (such as the configuration's default
      *nwa*):

      .. code-block:: python

         # eth dongle mac 00:e0:4c:36:40:b8 is assigned to NWA
         ttbl.config.targets['nwa'].tags_update(dict(mac_addr = '00:e0:4c:36:40:b8'))

      Furthermore, default networks *nwa*, *nwb* and *nwc* are defined
      to have a power control rail (versus an individual power
      controller), so it is possible to add another power controller
      to, for example, power on or off a network switch:

      .. code-block:: python

         ttbl.config.targets['nwa'].pc_impl.append(
             ttbl.pc.dlwps7("http://USER:PASSWORD@sp5/8"))

      This creates a power controller to switch on or off plug #8 on
      a Digital Loggers Web Power Switch named *sp5* and makes it part
      of the *nwa* power control rail. Thus, when powered on, it will
      bring the network up up and also turn on the network switch.

    - lastly, for each target connected to that network, update it's
      tags to indicate it:

      .. code-block:: python

         ttbl.config.targets['TARGETNAME-NN'].tags_update(
             {
               'ipv4_addr': "192.168.10.30",
               'ipv4_prefix_len': 24,
               'ipv6_addr': "fc00::10:30",
               'ipv4_prefix_len': 112,
             },
             ic = 'nwc')

    By convention, the server is .1, the QEMU Linux virtual machines
    are set from .2 to .10 and the QEMU Zephyr virtual machines from
    .30 to .45. Physical targets are set to start at 100.

    Note the networks for targets and infrastructure :ref:`have to be
    kept separated <separated_networks>`.

    """

    @staticmethod
    def _if_rename(target):
        if 'mac_addr' in target.tags:
            # We do have a physical device, so we are going to first,
            # rename it to match the IC's name (so it allows targets
            # to find it to run IP commands to attach to it)
            ifname = commonl.if_find_by_mac(target.tags['mac_addr'])
            if ifname == None:
                raise ValueError("Cannot find network interface with MAC '%s'"
                                 % target.tags['mac_addr'])
            if ifname != target.id:
                subprocess.check_call("ip link set %s down" % ifname,
                                      shell = True)
                subprocess.check_call("ip link set %s name _b%s"
                                      % (ifname, target.id), shell = True)

    def power_on_do(self, target):
        if 'mac_addr' in target.tags:
            self._if_rename(target)
        else:
            # We do not have a physical device, a bridge, to serve as
            # lower
            commonl.if_remove_maybe("_b%(id)s" % target.kws)
            subprocess.check_call(
                "/usr/sbin/ip link add name _b%(id)s type bridge"
                % target.kws, shell = True)

        # Add an interface called bICNAME which will get the IP
        # addressing.
        subprocess.check_call(
            "/usr/sbin/ip link add"
            "  link _b%(id)s name b%(id)s"
            "  type macvlan mode bridge; "
            "/usr/sbin/ip addr add"
            "  %(ipv6_addr)s/%(ipv6_prefix_len)s dev b%(id)s; "
            "/usr/sbin/ip addr add"
            "  %(ipv4_addr)s/%(ipv4_prefix_len)d"
            "  dev b%(id)s" % target.kws, shell = True)

        target.fsdb.set('power_state', 'on')

        # Bring them both up
        subprocess.check_call(
            "/usr/sbin/ip link set dev _b%(id)s up promisc on; "
            "/usr/sbin/ip link set dev b%(id)s up promisc on"
            % target.kws, shell = True)

        # Start tcpdump on the network?
        #
        # The value of the tcpdump property, if not None, is the
        # filename we'll capture to.
        tcpdump = target.fsdb.get('tcpdump')
        if tcpdump:
            assert not os.path.sep in tcpdump \
                and tcpdump != "" \
                and tcpdump != os.path.pardir \
                and tcpdump != os.path.curdir, \
                "Bad filename for TCP dump capture '%s' specified as " \
                " value to property *tcpdump*: must not include" % tcpdump
            # per ttbd:make_ticket(), colon splits the real username
            # from the ticket
            owner = target.owner_get().split(":")[0]
            assert owner, "BUG? target not owned on power on?"
            capfile = os.path.join(target.files_path, owner, tcpdump)
            # Because it is in the user's area,
            # we assume the user knows what he is doing to overwrite it,
            # so we'll remove any first
            commonl.rm_f(capfile)
            pidfile = os.path.join(target.state_dir, "tcpdump.pid")
            logfile = os.path.join(target.state_dir, "tcpdump.log")
            cmdline = [
                "/usr/sbin/tcpdump", "-U",
                "-i", "_b%(id)s" % target.kws,
                "-w", capfile
            ]
            try:
                logf = open(logfile, "a")
                target.log.info("Starting tcpdump with: %s", " ".join(cmdline))
                p = subprocess.Popen(
                    cmdline, shell = False, cwd = target.state_dir,
                    close_fds = True, stdout = logf,
                    stderr = subprocess.STDOUT)
            except OSError as e:
                raise RuntimeError("tcpdump failed to start: %s" % e)
            ttbl.daemon_pid_add(p.pid)	# FIXME: race condition if it died?
            with open(pidfile, "w") as pidfilef:
                pidfilef.write("%d" % p.pid)

            pid = commonl.process_started(		# Verify it started
                pidfile, "/usr/sbin/tcpdump",
                verification_f = os.path.exists,
                verification_f_args = ( capfile, ),
                timeout = 20, tag = "tcpdump", log = target.log)
            if pid == None:
                raise RuntimeError("tcpdump failed to start after 5s")


    def power_off_do(self, target):
        # Kill tcpdump, if it was started
        pidfile = os.path.join(target.state_dir, "tcpdump.pid")
        commonl.process_terminate(pidfile, tag = "tcpdump",
                                  path = "/usr/sbin/tcpdump")

        if 'mac_addr' in target.tags:
            # We might have powered up in the middle and the state
            # might be a wee confusing
            self._if_rename(target)

        commonl.if_remove_maybe("b%(id)s" % target.kws)
        if 'mac_addr' in target.tags:
            # We do have a physical device, just bring it down
            subprocess.check_call(
                "ip link set dev _b%(id)s down promisc off" % target.kws,
                shell = True)
        else:
            # We do not have a physical device, we made a bridge, so
            # we will just remove it
            commonl.if_remove_maybe("_b%(id)s" % target.kws)

        target.fsdb.set('power_state', 'off')

    def power_get_do(self, target):
        r = target.fsdb.get('power_state')
        if r == None:
            # First run, we assume it's off
            return False
        elif r == 'on':
            return True
        elif r == 'off':
            return False
        else:
            raise AssertionError("r is %s" % r)

# declare the property we normal users to be able to set
ttbl.test_target.user_properties.add('tcpdump')

class tt_qemu_linux(ttbl.tt_qemu.tt_qemu):
    """QEMU x86-64 test target that can run Linux cloud images
    (Fedora, Clear and other) with serial port control.

    Supports power control, serial console and image flashing
    interfaces, as well as networking in between images and to the
    upstream host's network.

    Note that the disk assigned to this images is transient,
    implemented in a couple of ways:

    - if a QCOW image is given, a copy-on-write disk is created when
      the machine powers up and then discarded when it powers off. The
      original image is never modified. A property (*persist*) can be
      set to non-false to allow keeping the transient disk.

    - if an ISO image is given, it is considered to be a LIVE image
      and a transient disk with serial number TCF-home is created,
      that can be used to write to.

      TCF provides a Fedora Kickstarter configuration to generate
      images that are used for testing:

      - remove root's password

      - autologin the console to a root shell

      - configure the IP address (if networking is setup)

      - enable SSH access to the root account with no password


    Add to your configuration file ``/etc/ttbd-production/conf_10_targets.py``:

    .. code-block:: python

       ttbl.config.target_add(
           tt_qemu_linux("qlNAME",
                         dict(
                             ram_megs = 1024,
                             qemu_ro_image = '/var/lib/ttbd/tcf-live.iso',
                             qemu_bios_image = '/usr/share/qemu/bios.bin',
                         )),
           target_type = "qemu-linux-TYPE-x86_64",
           tags = dict(more tags...)
       )

    Where:
     - ``qemu_ro_image``: file path of the virtual disk image to use
       as base (see below for configuring the image)
       Note this has to be given mandatorily to the tt_qemu_linux
       constructor, cannot be added after the fact
     - ``qemu_image_size``: Size in gigs (eg: 10G) of the virtual disk
       image size; when the virtual disk image is created referring to
       the base, it will be made to be this size.
     - ``qemu_bios_image``: path the BIOS file to use; depending on
       the image, one or another will be needed.
     - ``ram_megs``: Megabytes of RAM to use; for bigger Linux
       distros, you want to start with 1024.
     - ``TYPE``: *fedora*, *clear*, ...
     - ``NAME``: name for the virtual machine; it is recommend to
       begin with *ql* (QEMU Linux) and a letter matching the type
       (eg: *qlf03* for QEMU Linux Fedora #3).

    Restart the server and it yields::

      $ tcf list
      local/qlNAME

    **Bill of materials**

    - QEMU installed in the server (``dnf install -y qemu``)

    - (optional) Fedora 25 cloud image deployed to the server's
      ``/var/lib/ttbd`` or any location specified in *ro_image*.

    **Setting up for the fixture**

    Note that due to the size of the images, it is not possible to
    upload them to the server's repository using *tcf images*. They
    have to be uploaded to the server via other methods and then the
    images can be configured.

    To create the ``tcf-live.iso`` image:

    - use a Fedora system, with access to any repositories you will
      require RPMs from (setup proxies, etc)

    - create a work directory *MYWORKDIR*::

        $ mkdir -p MYWORKDIR
        $ cd $MYWORKDIR

    - if any specific RPM packages are needed, create files
      *tcf-live-ANYNAME.pkgs* in *MYWORKDIR*::

        $ echo RPM1 > tcf-live-01-list.pkgs
        $ echo RPM2 > tcf-live-04-list.pkgs

      one RPM per line, multiple lines per file, see
      :download:`/usr/share/tcf/live/tcf-live-02-core.pkgs
      <../ttbd/live/tcf-live-02-core.pkgs>` for examples.

    - if any extra kickstarter configuration is needed, add in
      *tcf-live-extra-*.ks* files

    - invoke */usr/share/tcf/live/mk-liveimg.sh*, for which you need
      *sudo* rights::

        $ /usr/share/tcf/live/mk-liveimg.sh .
        ...
        frags = 20
        Setting supported flag to 0

      note this creates a cache in *MYWORDIR/tcf-live/cache* with
      downloaded RPMs and others; if you re-run again from within the
      same workdir, the cache will be reused.

    - Move the image to its default location on /var/lib/ttbd::

        $ mv tcf-live/tcf-live.iso /var/lib/ttbd/

      obviously, other names and locations can be used, as long as
      they are then configured when invoking :class:`tt_qemu_linux`
      with the *qemu_ro_image* variable

    **Configuring the system for the fixture**

    Once the image file ``tcf-live.iso`` has been setup and
    distributed to the server, add to each server's
    ``conf_10_targets.py`` configuration files with:

    .. code-block:: python

       ttbl.config.target_add(
           tt_qemu_linux("qlfNN",
                         tags = dict(
                             ram_megs = 1024,
                             qemu_ro_image = '/var/lib/ttbd/tcf-live.iso',
                             qemu_bios_image = '/usr/share/qemu/bios.bin',
                         )),
           target_type = "qemu-linux-fedora-x86_64",
           tags = dict(
               ... more tags as neeed
           )
       )

    Note the default location for images is ``/var/lib/ttbd``, but it
    can be anywhere the daemon has access to.

    **Network configuration**

    Network is supported in various ways:

    - NAT is currently broken!!!

      To have the VM connect to the host's upstream network via NAT,
      connect it to the interconnect *nat_host* (last lines) by adding
      a tag *nat_host* set to *True*:

      >>> ttbl.config.target_add(
      >>>     ...
      >>>     tags = dict(
      >>>         ...
      >>>         nat_host = True,
      >>>         ...
      >>>     ))

      Alternatively, once created:

      >>> ttbl.config.targets['qlfNAME'].add_to_interconnect('nat_host', {})

      The *nat_host* interconnect, albeit doesn't really exist, makes
      teh *tt_qemu_linux* class create a network interface that will
      be configured to NAT on the upstream connection of the host.

      .. warning:: this will get you potentially to the open Internet
         or whatever is available from the host.

    - Connecting to *ttbd* internal test networks is accomplished by
      using QEMU and *macvtap* to a *TTBD interconnect* as
      :class:`vlan_pci` added to any target that supports power
      switching.

      >>> ttbl.config.targets['qlfNN'].add_to_interconnect(
      >>>     'nwXX',
      >>>     dict(ipv4_addr = "192.168.XX.NN",
      >>>          ipv4_prefix_len = 24,
      >>>          ipv6_addr = "fc00::X:NN",
      >>>          ipv6_prefix_len = 112,
      >>>          mac_addr = "02:XX:00:00:00:%NN",
      >>>     ))

      For that, the target's tags need to define in their
      interconnects dictionary an entry named after the interconnect's
      name with (eg: to add *qlfNAMEXX* to interconnect *XX*, append
      after the target definition):

      >>> ttbl.config.targets['qlNAMEXX'].tags_update(
      >>>     dict(
      >>>        ipv4_addr = "192.168.XX.NN",
      >>>        ipv4_addr_len = 24,
      >>>        ipv6_addr = "fc00::XX:NN",
      >>>        ipv4_addr_len = 112,
      >>>        mac_addr = "02:XX:00:00:00:NN",
      >>>     ),
      >>>     ic = "XX")

      - Network number (*XX*) -- try have your networks named in a way
        that calls for easy numbering numbered (eg: a -> 10, b -> 11,
        c -> 12...)  so those numbers can be used to assign IP
        addresses (eg: for letter A, number 10 (0x0A), IPv4 prefix can
        be 192.168.X.Y and MAC address prefix can be 02:0A:00:00:00:YY

      - *mac_addr*: is the MAC address to give the target; note it has
        to be different for all targets (so if we use proper network and
        target indexes, they shall all end up being different).

    **Troubleshooting notes**

    - If *cloud-init* seems not to be working, make sure
      ``/var/lib/cloud/sem/user-scripts*`` in the image is removed

    """
    # Ugly implementation notes
    #
    # - We need to pass an open file descriptor to the TAP interface;
    #   because we have Python close all the FDs when calling QEMU (and
    #   it closes all but stdin/out/err), we use FD0...anyway, the input
    #   is redirected to nothing, as it is a daemon. So
    #   qemu_preefec_fn() [called ny tt_qemu.power_on_do()] will open
    #   and attach to FD0, so it gets passed then as the cmd line
    #   option '-net tap,fd0".
    #   Yeah, it is a hack, but there is no way to ask
    #   subprocess.POpen() to avoid closing *some* FDs.
    #   And it works.
    def __init__(self, _id, tags, qemu_cmdline_append = ""):
        assert isinstance(tags, dict)
        assert 'qemu_ro_image' in tags
        bsp = 'x86_64'

        # Only one BSP-Model (for one BSP, x86_64)
        _tags = dict(tags)
        _tags['bsps'] = {
            'x86_64': dict(console = 'x86_64', linux = True),
        }
        _tags['bsp_models'] = dict(x86_64 = None)
        ttbl.tt_qemu.tt_qemu.__init__(self, _id, [ bsp ], _tags)

        self.kws.update(
            bsp = bsp,		# The BSP is hardcoded in this one
            ram_megs = tags.get("ram_megs", 256),
        )
        # power_on_pre will add more to this for each supported
        # network interface
        self.power_on_pre_fns.append(self._image_power_on_pre)
        # Actually tell QEMU to start once we are done starting
        # support daemons and whatever; othewise the guest might start
        # using the network before it is setup
        self.power_on_post_fns.append(self._qmp_start)
        self.power_off_post_fns.append(self._image_power_off_post)
        self.qemu_cmdline_append = qemu_cmdline_append

        tags.setdefault('qemu_image_size', '10G')
        # Specify the command line we need
        # Note we also add a random number generator--otherwise we
        # might run out of randomness and the system takes forever to
        # start.
        #strace -f -s 1024 -o %(path)s/%(bsp)s.strace.log
        qemu_cmdline = """\
/usr/bin/qemu-system-x86_64
 -enable-kvm
 -bios %(qemu_bios_image)s
 -m %(ram_megs)d
 -vga none -nographic
 -usb
 -chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read
 -serial chardev:ttyS0
 -object rng-random,id=objrng0,filename=/dev/urandom -device virtio-rng-pci,rng=objrng0,id=rng0,bus=pci.0,addr=0x7
 """
        qemu_ro_image = tags['qemu_ro_image']
        if qemu_ro_image.endswith(".iso"):
            # Use a ISO as live file system; it will do a COW image
            # itself for updates and we'll mount a /home over a
            # physical/virtual disk that has a serial number TCF-home
            # or a partition labeled TCF-home
            qemu_cmdline += """\
 -drive file=%(qemu_ro_image)s,if=virtio,aio=threads,media=cdrom \
 -drive file=%(path)s/%(bsp)s-home.qcow2,serial=TCF-home,if=virtio,aio=threads \
 -drive file=%(path)s/%(bsp)s-swap.qcow2,serial=TCF-swap,if=virtio,aio=threads \
 """
        else:
            # Use a QCOW image as original; we'll do a COW file which
            # will carry the updates.
            # Note we bring up two different ISO files, for
            # cloud-init. They are different in that they have a different
            # label, as different cloud images take one or the other. See
            # comments on _image_power_on_pre()
            # This is being deprecated
            qemu_cmdline += """\
 -drive file=%(path)s/%(bsp)s-hd.qcow2,if=virtio,aio=threads
 -drive file=%(path)s/%(bsp)s-init-cidata.iso,if=virtio,aio=threads,format=raw
 -drive file=%(path)s/%(bsp)s-init-config_2.iso,if=virtio,aio=threads,format=raw
 """
        qemu_cmdline += self.qemu_cmdline_append
        # Keep the command lines in a separate array, which we will
        # extend later in _image_power_on_pre for executing them
        self._qemu_cmdlines = { 'x86_64': qemu_cmdline }

    def qemu_preexec_fn(self):
        # This is called by subprocess.Popen after spawning to run
        # qemu from tt_qemu.power_on_do() right before spawning Qemu
        # for us.
        # See doc block on top for why file descriptor 0.
        # We will find out which is the index of the TAP device
        # assigned to this, created on _image_power_on_pre and open
        # file desctriptor 0 to it, then leave it open for Qemu to
        # tap into it.
        for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
            if not 'ipv4_addr' in ic_kws and not 'ipv6_addr' in ic_kws:
                continue
            kws = dict(ic_kws)
            kws.update(self.kws)
            kws['ic_name'] = ic_name
            if not commonl.if_present("_b%s" % ic_name):
                self.log.warning("network %s powered off? networking "
                                 "disabled" % ic_name)
                # If the network is not powered up, skip it
                # FIXME: replace with it calling vlan_pci.something()
                # that brings up the basic interface (_bICNAME) so
                # that once we power the network, it works
                continue

            tapindex = commonl.if_index("t%(ic_name)s%(id)s" % kws)
            assign = 0
            # Need to wait for udev to reconfigure this for us to have
            # access; this is done by a udev rule installed
            # (/usr/lib/udev/rules.d/80-ttbd.rules)
            tapdevname = "/dev/tap%d" % tapindex
            count = 1
            top = 4
            while not os.access(tapdevname, os.R_OK | os.W_OK):
                if count >= top:
                    msg = "%s: timed out waiting for udev to set " \
                        "permissions in /usr/lib/udev/rules.d/80-ttbd.rules" \
                        % tapdevname
                    self.log.error(msg)
                    raise RuntimeError(msg)
                time.sleep(0.25)
                count += 1
            fd = os.open("/dev/tap%d" % tapindex, os.O_RDWR, 0)
            if fd != assign:
                # there, reassign it to fd @assign
                os.dup2(fd, assign)
                os.close(fd)
                # leave fd assign open for QEMU!

    @staticmethod
    def _cloud_init_mkfile_systemd_network_if(
            mac_addr,
            dhcp = False,
            ipv4_addr = None, ipv4_prefix_len = None,
            ipv6_addr = None, ipv6_prefix_len = None):
        #
        # Create a systemd network config file for an interface as per
        # https://www.freedesktop.org/software/systemd/man/systemd.network.html
        # in the format described by
        # http://cloudinit.readthedocs.io/en/latest/topics/modules.html#write-files
        ci_text = """\
- content: |
    [Match]
    MACAddress = %s

    [Network]
""" % mac_addr
        if dhcp == True:
            ci_text += "    DHCP = yes\n"
        if ipv4_addr:
            ci_text += "    Address = %s" % ipv4_addr
            if ipv4_prefix_len:
                ci_text += "/%s" % ipv4_prefix_len
            ci_text += "\n"
        if ipv6_addr:
            ci_text += "    Address = %s" % ipv6_addr
            if ipv6_prefix_len:
                ci_text += "/%s" % ipv6_prefix_len
            ci_text += "\n"
        ci_text += """\
  path: /etc/systemd/network/%s.network
  permissions: 0644
  owner: root:root
""" % mac_addr
        return ci_text

    _r_ident = re.compile('[^a-z0-9A-Z]+')

    def _image_power_on_pre(self):
        # Note __init__ has initialized self._qemu_cmdlines[[x86_64']
        # *and* here we are going to add to it into
        # self.qemu_cmdlines, which we'll constantly re-init, as
        # different options might be used before tt_qemu.power_on_do()
        # actuall uses it to call _qemu_launch().

        # We need them to be different because each power-up
        # might have diffferent command line options depending on the
        # networks that are active or not.

        # We need the __init__ part doing it earlier because remember,
        # these might be running different processes, and the basic
        # self.qemu_cmdlines array has to be initialized so we can
        # find the actual binary being used.
        kws = dict(self.kws)
        self.qemu_cmdlines = copy.deepcopy(self._qemu_cmdlines)
        # Get fresh values for these keys
        for key in self.fsdb.keys():
            if key.startswith("qemu-"):
                kws[key] = self.fsdb.get(key)


        ci_files = []
        # Setup network stuff, create virtual tap interfaces
        for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
            if 'ipv4_addr' in ic_kws or 'ipv6_addr' in ic_kws:
                _kws = dict(kws)
                _kws.update(ic_kws)
                _kws['ic_name'] = ic_name
                # QEMU device ident only allows a-zA-Z0-9-, starting
                # with letter
                _kws['ident'] = "id" + self._r_ident.sub("", _kws['mac_addr'])
                # CAP_NET_ADMIN is 12 (from /usr/include/linux/prctl.h
                if not commonl.prctl_cap_get_effective() & 1 << 12:
                    # If we don't have network setting privilege,
                    # don't even go there
                    self.log.warning("daemon lacks CAP_NET_ADMIN: unable to "
                                     "add networking capabilities ")
                    continue

                if not commonl.if_present("_b%s" % ic_name):
                    self.log.warning("network %s powered off? networking "
                                     "disabled" % ic_name)
                    # If the network is not powered up, skip it
                    # FIXME: replace with it calling vlan_pci.something()
                    # that brings up the basic interface (_bICNAME) so
                    # that once we power the network, it works
                    continue

                commonl.if_remove_maybe("t%s%s" % (ic_name, self.id))
                subprocess.check_call(
                    "ip link add "
                    "  link _b%(ic_name)s "
                    "  name t%(ic_name)s%(id)s"
                    "  address %(mac_addr)s"
                    "  up"
                    "  type macvtap mode bridge; "
                    "ip link set t%(ic_name)s%(id)s"
                    "  promisc on "
                    "  up" % _kws, shell = True)

                # Add to the command line
                self.qemu_cmdlines['x86_64'] += \
                    " -net nic,id=%(ident)s,model=virtio,macaddr=%(mac_addr)s" \
                    " -net tap,fd=0,name=%(ident)s" % _kws
                # Add cloud init systemd configuration
                ci_files.append(self._cloud_init_mkfile_systemd_network_if(
                    _kws['mac_addr'],
                    ipv4_addr = ic_kws.get('ipv4_addr', None),
                    ipv4_prefix_len = ic_kws.get('ipv4_prefix_len', None),
                    ipv6_addr = ic_kws.get('ipv6_addr', None),
                    ipv6_prefix_len = ic_kws.get('ipv6_prefix_len', None),
                    dhcp = False
                ))

            # Add a nat/host interface?
            if ic_name == 'nat_host':
                raise RuntimeError("NAT configuration is currently broken")
                # we hardcode the MAC address of the NAT ethernet
                # interface, which we'll also add in the configuration
                # for systemd-network in /etc/systemd/network for it
                # to do DHCP. There is only one of those interfaces
                # per virtual host, so it will never conflict with
                # anything and we don't use the form of addressing in
                # any MAC we generate.
                mac_addr = "02:01:01:01:01:01"
                self.qemu_cmdlines['x86_64'] += \
                    " -net nic,name=nat_host,model=virtio,macaddr=%s" \
                    " -net user,id=nat_host,net=192.168.200.0/24,dhcpstart=192.168.200.10 " \
                     % mac_addr
                # Add cloud init systemd configuration
                ci_files.append(self._cloud_init_mkfile_systemd_network_if(
                    mac_addr, dhcp = True))

        # If no network interfaces we added, remove the default
        # networking QEMU does
        if "-net" not in self.qemu_cmdlines['x86_64']:
            self.qemu_cmdlines['x86_64'] += "-net none "

        qemu_ro_image = self.tags['qemu_ro_image']
        # Do we want to persist the existing images?
        if self.fsdb.get("persist") == None \
           or self.fsdb.get("persist", "").lower() == 'false':
            if qemu_ro_image.endswith(".iso"):
                commonl.rm_f("%(path)s/%(bsp)s-home.qcow2" % kws)
                commonl.rm_f("%(path)s/%(bsp)s-swap.qcow2" % kws)
            else:
                commonl.rm_f("%(path)s/%(bsp)s-hd.qcow2" % kws)
                commonl.rm_f("%(path)s/%(bsp)s-init-cidata.iso" % kws)
                commonl.rm_f("%(path)s/%(bsp)s-init-config_2.iso" % kws)

            if qemu_ro_image.endswith(".iso"):
                # TCF live image is configured to mount as /home any
                # drive with serial number TCF-home or a GPT partition
                # with label TCF-home
                if not os.path.exists("%(path)s/%(bsp)s-home.qcow2" % kws):
                    subprocess.check_call(
                        [ "qemu-img", "create", "-q", "-f", "qcow2",
                          "%(path)s/%(bsp)s-home.qcow2" % kws,
                          self.tags.get('qemu_image_size', "10G") ])
                # TCF live image is configured to swap to any
                # drive with serial number TCF-swap or a GPT partition
                # with label TCF-swap
                commonl.rm_f("%(path)s/%(bsp)s-swap.qcow2" % kws)
                subprocess.check_call(
                    [ "qemu-img", "create", "-q", "-f", "qcow2",
                      "%(path)s/%(bsp)s-swap.qcow2" % kws,
                      self.tags.get('qemu_image_size', "10G") ])
            else:
                # Create a QCOW (copy on write) hard drive of the provided
                # image for this target to use; it can be modified and
                # whichever and then it will be discarded on power off.
                #
                # Create a disk drive overlay, so the
                # original image is untouched
                if not os.path.exists("%(path)s/%(bsp)s-hd.qcow2" % kws):
                    subprocess.check_call(
                        [ "qemu-img", "create", "-q", "-f", "qcow2",
                          "-b", qemu_ro_image,
                          "%(path)s/%(bsp)s-hd.qcow2" % kws,
                          self.tags.get('qemu_image_size', '10G') ])

        if not os.path.exists("%(path)s/%(bsp)s-init-cidata.iso" % kws):
            # Create a BSP-init.iso file for cloud-init to detect and do
            # local initialization
            #
            # The crux of the matters is to drop config files in a
            # volume that has a label "config-2", subdirectory
            # openstack/latest.
            #
            # http://cloudinit.readthedocs.io/en/latest/topics/datasources/configdrive.html#version-2
            config_2_dir = os.path.join(self.state_dir, "config-2")
            shutil.rmtree(config_2_dir, ignore_errors = True)
            latest_dir = os.path.join(config_2_dir, "openstack", "latest")
            os.makedirs(os.path.join(latest_dir))
            # The files are meta_data.json and user_data
            with open(os.path.join(latest_dir, "meta_data.json"), "w") as f:
                f.write("""\
{
    "hostname": "%(id)s"
}
""" % kws)
            # This is for Fedora's cloud-init
            with open(os.path.join(config_2_dir, "meta-data"), "w") as f:
                f.write("""\
hostname: %(id)s
""" % kws)
            # https://cloudinit.readthedocs.io/en/latest/topics/format.html#cloud-config-data
            with open(os.path.join(latest_dir, "user_data"), "w") as f:
                f.write("""\
#cloud-config
""")
                # write files before we run commands, as some of those
                # commands will need the files
                if ci_files:
                    # Each item in the ci_files list is a cloud-init
                    # description for a while to write, in the form
                    # described in
                    # http://cloudinit.readthedocs.io/en/latest/topics/modules.html#write-files
                    # We use this to add config file to systemd to
                    # configure network interfaces, for example
                    f.write("write_files:\n")
                    for ci_file in ci_files:
                        f.write(ci_file)
                # these VMs are only accessible from within the testing
                # network and we need a console into the system to
                # interact with other nodes, so we just have it give us
                # root by:
                #
                # - Have agetty autologin root into all the consoles
                #   (reloading systemctl for the change to take effect
                #
                # - removing the root (Fedora's password doesn't take --quiet)
                #
                # - We also set PS1 to give a sequence of commands
                #   executed, so we can verify against it.
                #
                # Note:
                # - the file has to start with #cloud-config, hence the
                #   \ after """
                # - multiple `runcmd:` commands work for Clearlinux,
                #   not for Fedora. Multiple commands are appended
                #   straight up after the hyphen, hence the semicolon
                #   at the end.
                # - to debug, you can always get into the vm and run,
                #   as root:
                #   $ cloud-init --openstack-config-drive /dev/vdb
                # - hostname: seems not to always work, so writing
                #   /etc/hostname.
                f.write(r"""
hostname: %(id)s
runcmd:
 - echo %(id)s > /etc/hostname; hostname %(id)s;
 - sed -i 's|bin/agetty|bin/agetty --autologin root|' /usr/lib/systemd/system/getty@.service;
 - sed -i 's|bin/agetty|bin/agetty --autologin root|' /usr/lib/systemd/system/serial-getty@.service;
 - systemctl daemon-reload;
 - systemctl restart serial-getty@ttyS0.service;
 - passwd --delete root;
 - echo "PermitRootLogin yes" >> /etc/ssh/sshd_config;
 - echo "PermitEmptyPasswords yes" >> /etc/ssh/sshd_config;
 - echo "TCF test node @ \l" > /etc/issue;
 - echo "export PS1=' \# \$ '" >> /etc/profile;
 - set -x;
""" % kws)
                # If we have written network configuration, restart
                # the network service so it is picked up
                #
                # NOTE: in theory Clear can do a "services:" section,
                # but I cannot get it to work on Fedora, so we run a
                # command.
                #
                # Note the --no-block, we don't want to interrupt the
                # boot process, so just queue it.
                #
                # FIXME: document assumption networkd has been enabled
                if any('path: /etc/systemd/network' in ci_file
                       for ci_file in ci_files):
                    f.write("""\
 - systemctl --no-block restart systemd-networkd;
 - systemctl --no-block restart systemd-resolved;
""")

            # Some distros like - (clear?), some like _ (Fedora)? some
            # like the root dir (Fedora, I've seen), some the latest
            # dir (Clear Linux)
            # So this is for Fedora: ISO's root dir, using hyphens
            shutil.copyfile(os.path.join(latest_dir, "user_data"),
                            os.path.join(config_2_dir, "user-data"))
            # Generate the ISO we pass the image that gets fed to cloud-init
            # This one is for Clear, because they like the volume ID
            # be config-2 (from the spec?)
            subprocess.check_call(
                ("/usr/bin/genisoimage -quiet -joliet -rock "
                 "-output %(path)s/%(bsp)s-init-config_2.iso "
                 "-volid config-2 %(path)s/config-2" % kws).split())
            # This one is for Fedora, because they like the volume ID
            # be cidata
            subprocess.check_call(
                ("/usr/bin/genisoimage -quiet -joliet -rock "
                 "-output %(path)s/%(bsp)s-init-cidata.iso "
                 "-volid cidata %(path)s/config-2" % kws).split())
            shutil.rmtree("%(path)s/config-2" % kws)


    def _image_power_off_post(self):
        # Tear down network stuff
        for ic_name, _ in self.tags.get('interconnects', {}).iteritems():
            commonl.if_remove_maybe("t%s%s" % (ic_name, self.id))

        qemu_ro_image = self.tags['qemu_ro_image']
        if self.fsdb.get("persist") == None \
           or self.fsdb.get("persist", "").lower() == 'false':
            # QEMU keeps it open until done with them anyway
            if qemu_ro_image.endswith(".iso"):
                commonl.rm_f("%(path)s/%(bsp)s-home.qcow2" % self.kws)
                commonl.rm_f("%(path)s/%(bsp)s-swap.qcow2" % self.kws)
            else:
                commonl.rm_f("%(path)s/%(bsp)s-hd.qcow2" % self.kws)
                commonl.rm_f("%(path)s/%(bsp)s-init-cidata.iso" % self.kws)
                commonl.rm_f("%(path)s/%(bsp)s-init-config-2.iso" % self.kws)



class tt_qemu_zephyr(ttbl.tt_qemu.tt_qemu):
    """
    Implement a QEMU test target that can run Zephyr kernels
    and display the output over a serial port.

    Supports power control, serial console and image flashing
    interfaces.

    """
    def __init__(self, id, bsps, tags = {}):
        # With all the supported BSPs, create a list of supported
        # models; each individual BSP and then one of all at the same
        # time.
        bsp_models = {}
        for bsp in bsps:
            bsp_models[bsp] = None
        bsp_models["+".join(bsps)] = bsps
        tags_bsp =  {
            'x86': dict(zephyr_board = 'qemu_x86',
                        zephyr_kernelname = 'zephyr.elf',
                        board = 'qemu_x86',
                        kernelname = 'zephyr.elf',
                        console = 'x86', quark_se_stub = False),
            'arm': dict(zephyr_board = 'qemu_cortex_m3',
                        zephyr_kernelname = 'zephyr.elf',
                        board = 'qemu_cortex_m3',
                        kernelname = 'zephyr.elf',
                        console = 'arm', quark_se_stub = False),
            'nios2': dict(zephyr_board = 'qemu_nios2',
                          zephyr_kernelname = 'zephyr.elf',
                          board = 'qemu_nios2',
                          kernelname = 'zephyr.elf',
                          console = 'nios2', quark_se_stub = False),
            'riscv32': dict(zephyr_board = 'qemu_riscv32',
                            zephyr_kernelname = 'zephyr.elf',
                            board = 'qemu_riscv32',
                            kernelname = 'zephyr.elf',
                            console = 'riscv32', quark_se_stub = False),
            'xtensa': dict(zephyr_board = 'qemu_xtensa',
                           zephyr_kernelname = 'zephyr.elf',
                           board = 'qemu_xtensa',
                           kernelname = 'zephyr.elf',
                           console = 'xtensa', quark_se_stub = False),
        }
        _tags = dict(tags)
        _tags['bsps'] = {}
        # List only the BSPs we have activated
        for bsp in bsps:
            _tags['bsps'][bsp] = tags_bsp[bsp]
        _tags['bsp_models'] = bsp_models

        ttbl.tt_qemu.tt_qemu.__init__(self, id, bsps, _tags = _tags)
        # On pre power up, we'll complete these command lines by
        # adding the networking interface information, depending on
        # what the tag say on _slip_pty_pre_on()
        self._qemu_cmdlines = dict(
            x86 = \
            "/opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux"
            "/usr/bin/qemu-system-i386 "
            "-m 8 -cpu qemu32,+nx,+pae "
	    "-device isa-debug-exit,iobase=0xf4,iosize=0x04 "
            "-no-reboot "
            "-nographic -vga none -display none -net none "
            "-clock dynticks -no-acpi -balloon none "
            "-L /usr/share/qemu -bios bios.bin "
            "-machine type=pc-0.14 "
            # Serial console tt_qemu.py can grok
            "-chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read "
            "-serial chardev:ttyS0 "
            # Zephyr kernel boot
            "-kernel %(qemu-image-kernel-x86)s "
            "-nodefaults ",
            arm = \
            "/opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux"
            "/usr/bin/qemu-system-arm "
            "-cpu cortex-m3 "
            "-machine lm3s6965evb -display none "
            # Serial console tt_qemu.py can grok
            "-chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read "
            "-serial chardev:ttyS0 "
            # Zephyr kernel boot
            "-kernel %(qemu-image-kernel-arm)s "
            "-nodefaults -net none ",
            nios2 = \
            "/opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux"
            "/usr/bin/qemu-system-nios2 "
            "-machine altera_10m50_zephyr -display none "
            # Serial console tt_qemu.py can grok
            "-chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read "
            "-serial chardev:ttyS0 "
            # Zephyr kernel boot
            "-kernel %(qemu-image-kernel-nios2)s "
            "-nodefaults -net none ",
            riscv32 = \
            "/opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux"
            "/usr/bin/qemu-system-riscv32 "
            "-machine sifive -nographic -m 32 "
            # Serial console tt_qemu.py can grok
            "-chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read "
            "-serial chardev:ttyS0 "
            # Zephyr kernel boot
            "-kernel %(qemu-image-kernel-riscv32)s "
            "-nodefaults -net none ",
            xtensa = \
            "/opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux"
            "/usr/bin/qemu-system-xtensa "
            "-cpu sample_controller -machine sim -semihosting -nographic "
            # Serial console tt_qemu.py can grok
            "-chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read "
            "-serial chardev:ttyS0 "
            "-kernel %(qemu-image-kernel-xtensa)s "
            "-nodefaults -net none ",
        )
        # This is so tt_qemu._power_get_bsps() can do its thing
        self.qemu_cmdlines = copy.deepcopy(self._qemu_cmdlines)
        self.power_on_pre_fns.append(self._slip_power_on_pre)
        self.power_on_post_fns.append(self._slip_power_on_post)
        # Actually tell QEMU to start once we are done starting
        # support daemons and whatever; othewise the guest might start
        # using the network before it is setup
        self.power_on_post_fns.append(self._qmp_start)
        self.power_off_pre_fns.append(self._slip_power_off_pre)


    def _qmp_chardev_pty(self, ic_name, bsp):
        """Connect to the Qemu Monitor and ask what is the PTY assigned to
        the SLIP interface.

        :param str ic_name: Name of the interconnect this PTY is
          assigned to
        :param str bsp: Name of the BSP in the over all target this
          PTY is assigned to
        :returns str: path to PTY assigned to the SLIP interface
        :raises: anything on errors
        """
        try:
            with ttbl.tt_qemu.qmp_c(self.pidfile[bsp] + ".qmp") as qmp:
                r = qmp.command("query-chardev")
                for chardev in r:
                    # this  looks kindof like:
                    # { u'frontend-open': True, u'label': u'slip-pty-IC_NAME',
                    #   u'filename': u'pty:/dev/pts/4' }
                    # We take 'filename'
                    if chardev['label'] == 'slip-pty-%s' % ic_name:
                        # We assume it's pty:FILENAME
                        return chardev['filename'].split(':', 1)[1]
                return None
        except IOError as e:
            if e.errno == errno.ENOENT:
                return None
            raise

    def _slip_power_on_pre(self):
        kws = dict(self.kws)
        # Get fresh values for these keys
        for key in self.fsdb.keys():
            if key.startswith("qemu-"):
                kws[key] = self.fsdb.get(key)

        # Zephyr does QEMU networking with SLIP interfaces; for each
        # interconnect we are plugged to, we create an SLIP interface
        # to it. _slip_power_on_post() will, after firing up QEMU,
        # fire off TUNSLIP daemons to implement the actual networking
        # into a bridge.
        count = 0
        for bsp in self.bsps:
            # For each interconnect this thing is hooked up to, we
            # have created an slip-pty-ic_name device in QEMU
            self.qemu_cmdlines[bsp] = self._qemu_cmdlines[bsp]
            for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
                if not 'ipv4_addr' in ic_kws and not 'ipv6_addr' in ic_kws:
                    continue

                # CAP_NET_ADMIN is 12 (from /usr/include/linux/prctl.h
                if not commonl.prctl_cap_get_effective() & 1 << 12:
                    # If we don't have network setting privilege,
                    # don't even go there
                    self.log.warning("daemon lacks CAP_NET_ADMIN: will not "
                                     "add networking capabilities ")
                    continue

                if not commonl.if_present("_b%s" % ic_name):
                    self.log.warning("network %s powered off? networking "
                                     "disabled" % ic_name)
                    # If the network is not powered up, skip it
                    # FIXME: replace with it calling vlan_pci.something()
                    # that brings up the basic interface (_bICNAME) so
                    # that once we power the network, it works
                    continue

                # Zephyr networking using SLIP on UART1
                self.qemu_cmdlines[bsp] += \
                    "-chardev pty,id=slip-pty-%s " \
                    "-serial chardev:slip-pty-%s " %  (ic_name, ic_name)
            count += 1

    def _slip_power_on_post(self):
        kws = dict(self.kws)
        # Get fresh values for these keys
        for key in self.fsdb.keys():
            if key.startswith("qemu-"):
                kws[key] = self.fsdb.get(key)

        # Zephyr can do QEMU networking with SLIP interfaces; for it
        # we need to fire up a TUN daemon to do the routing, so after
        # we power up, we start it.
        count = 0
        for bsp in self.bsps:
            # For each interconnect this thing is hooked up to, we
            # have created an slip-pty-ic_name device in QEMU
            for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
                if not 'ipv4_addr' in ic_kws and not 'ipv6_addr' in ic_kws:
                    continue
                _kws = dict(kws)
                _kws.update(ic_kws)
                _kws['ic_name'] = ic_name
                _kws['bsp_count'] = count

                # network interface name; we need it short, otherwise
                # it is rejected by the kernel; hash the target name
                # and the BSP count to generate a two-letter id.
                ifname = ic_name + commonl.mkid(self.id + "%d" % count, l = 2)
                _kws['ifname' ] = ifname
                # This helps to identify which is our interface name
                self.fsdb.set("ifname", ifname)

                # Start tunslip on the PTY + TAP devices created by
                # QEMU and _slip_power_on_pre
                slip_pty = self._qmp_chardev_pty(ic_name, bsp)
                if slip_pty == None:
                    return

                # Create the TAP interface
                commonl.if_remove_maybe("t%s%s%d" % (ic_name, self.id, count))
                subprocess.check_call(
                    "ip link add "
                    "  link _b%(ic_name)s "
                    "  name %(ifname)s"
                    "  address %(mac_addr)s"
                    "  up"
                    "  type macvtap mode bridge; "
                    "ip link set %(ifname)s"
                    "  promisc on "
                    "  up" % _kws, shell = True)

                # The tap device we create has a number instead of a
                # BSP name, otherwise it will grow too long
                time.sleep(0.5)	# If we start too fast, QEMU replies -EIO
                tapindex = commonl.if_index("%(ifname)s" % _kws)
                p = subprocess.Popen(
                    [
                        # "strace", "-o", "tunslip.strace",
                        "/usr/bin/tunslip6", "-N", "-x",
                        "-t", "/dev/tap%d" % tapindex,
                        "-T", "-s", slip_pty
                    ],
                    shell = False, cwd = self.state_dir,
                    close_fds = True)
                # FIXME: ugly, this is racy -- need a way to determine if
                # this was succesfully run
                time.sleep(0.5)
                if p.returncode != None:
                    raise RuntimeError("QEMU %s: tunslip6 exited with %d"
                                       % (bsp, p.returncode))
                ttbl.daemon_pid_add(p.pid)	# FIXME: race condition if it died?
                self.fsdb.set("tunslip-%s-pid" % bsp, str(p.pid))

            count += 1

    def _slip_power_off_pre(self):
        # Before powering off the VM, kill the tun daemon if we
        # started it
        count = 0
        for bsp in self.bsps:
            for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
                if not 'ipv4_addr' in ic_kws and not 'ipv6_addr' in ic_kws:
                    continue
                tunslip_pids = self.fsdb.get("tunslip-%s-pid" % bsp)
                if tunslip_pids != None and commonl.process_alive(tunslip_pids):
                    tunslip_pid = int(tunslip_pids)
                    commonl.process_terminate(
                        tunslip_pid, tag = "QEMU's tunslip [%s]: " % bsp)
                self.fsdb.set("ifname", None)
                ifname = ic_name + commonl.mkid(self.id + "%d" % count, l = 2)
                commonl.if_remove_maybe(ifname)

def sam_xplained_add(name = None,
                     serial_number = None,
                     serial_port = None,
                     ykush_serial = None,
                     ykush_port_board = None,
                     openocd_path = openocd_path,
                     openocd_scripts = openocd_scripts,
                     debug = False,
                     target_type = "sam_e70_xplained"):

    """**Configure a SAM E70/V71 boards for the fixture described below**

    The SAM E70/V71 xplained is an ARM-based development
    board. Includes a builtin JTAG which allows flashing, debugging;
    it only requires one upstream connection to a YKUSH
    power-switching hub for power, serial console and JTAG.

    Add to a server configuration file:

    .. code-block:: python

       sam_xplained_add(
           name = "sam-e70-NN",
           serial_number = "SERIALNUMBER",
           serial_port = "/dev/tty-same70-NN",
           ykush_serial = "YKXXXXX",
           ykush_port_board = N,
           target_type = "sam_e70_xplained") # or sam_v71_xplained

    restart the server and it yields::

      $ tcf list
      local/sam-e70-NN
      local/sam-v71-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the SAM board

    :param str serial_port: (optional) name of the serial port (defaults to
      ``/dev/tty-TARGETNAME``)

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub where it is connected to
      for power control.

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board power is connected.

    :param str target_type: the target type "sam_e70_xplained"
      or "sam_v71_xplained"

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - a SAM E70 or V71 xplained board
    - a USB A-Male to micro-B male cable (for board power, JTAG and console)
    - one available port on an YKUSH power switching hub (serial *YKNNNNN*)

    **Connecting the test target fixture**

    1. Ensure the SAM E70 is properly setup:

       Using Atmel's *SAM-BA* In-system programmer, change the boot
       sequence and reset the board in case there is a bad image;
       this utility can be also used to recover the board in case
       it gets stuck.

       A. Download from `Atmel's website
          <http://www.atmel.com/tools/atmelsam-bain-systemprogrammer.aspx>`_
          (registration needed) and install.

          .. note:: This is **not** open source software

       B. Close the erase jumper *erase* (in SAMEv70 that's J200 and
          in SAMEv71 it is J202; in both cases, it is located above the
          CPU when you rotate the board so you can read the CPU's
          labeling in a normal orientation).

       C. Connect the USB cable to the taget's *target USB* port (the
          one next to the Ethernet connector) and to a USB port that
          is known to be powered on.

          Ensure power is on by verifying the orange led lights on on
          the Ethernet RJ-45 connector.

       D. Wait 10 seconds

       E. Open the erase jumper J202 to stop erasing

       F. Open *SAM-BA* 2.16

          Note on Fedora 25 you need to run *sam-ba_64* from the
          SAM-BA package.

       G. Select which serial port is that of the SAM e70 connected to
          the system. Use *lsusb.py -ciu* to locate the *tty/ttyACM*
          device assigned to your board::

            $ lsusb.py -ciu
            ...
            2-1      03eb:6124 02  2.00  480MBit/s 100mA 2IFs (Atmel Corp. at91sam SAMBA bootloader)
             2-1:1.0   (IF) 02:02:00 1EP  (Communications:Abstract (modem):None) cdc_acm tty/ttyACM2
             2-1:1.1   (IF) 0a:00:00 2EPs (CDC Data:) cdc_acm
            ...

          (in this example ``/dev/tty/ttyACM2``).

       H. Select board *at91same70-explained*, click connect.

       I. chose the flash tab and in the scripts
          drop down menu, choose *boot from Flash (GPNVM1)* and then
          *execute*.

       J. Exit *SAM-BA*

    2. connect the SAM E70/V71's *Debug USB* port with the USB
       A-male to B-micro to YKUSH downstream port *N*

    3. connect the YKUSH to the server system and to power as
       described in :py:func:`ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *sam-e70-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the board's *serial number*.

    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name

    flasher = ttbl.flasher.openocd_c(target_type, serial_number,
                                     openocd_path, openocd_scripts, debug)
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)


    ttbl.config.target_add(
        ttbl.tt.tt_flasher(
            name,
            serial_ports = [
                "pc",
                dict(port = serial_port, baudrate = 115200)
            ],
            flasher = flasher,
            power_control = [
                pc_board,       # power switch for the board
                # delay until device comes up
                ttbl.pc.delay_til_usb_device(
                    serial_number,
                    poll_period = 5,
                    timeout = 30,
                    action = pc_board.power_cycle_raw,
                    # must be a sequence!
                    action_args = (4,)
                ),
                ttbl.pc.delay_til_file_appears(	# Serial port comes up
                    serial_port, poll_period = 4, timeout = 25,
                ),
                ttbl.cm_serial.pc(),    # Connect serial ports
                flasher,                # Start / stop OpenOCD
            ]
        ),
        tags = {
            'bsp_models' : { 'arm': None },
            'bsps' : {
                # SAM V71 is not officialy part of zephyr,
                # We should compile E70 image and flash it on the V71 board
                "arm":  dict(zephyr_board = "sam_e70_xplained",
                             zephyr_kernelname = 'zephyr.elf',
                             kernelname = 'zephyr.elf',
                             board = "sam_e70_xplained",
                             console = ""),
            },
            'quark_se_stub': "no",
            # Flash verification is really slow, give it more time
            'slow_flash_factor': 5,
            'flash_verify': 'False',
        },
        target_type = target_type)


#: Commmands to configure Simics to run a simulation for Zephyr by
#: default
#:
#: :data:`Fields available <ttbl.tt.simics.simics_vars>` via string
#: formatting ``%(FIELD)L``
simics_zephyr_cmds = """\
$disk_image = "%(simics_hd0)s"
$cpu_class = "pentium-pro"
$text_console = TRUE
run-command-file "%%simics%%/targets/x86-440bx/x86-440bx-pci-system.include"
create-telnet-console-comp $system.serconsole %(simics_console_port)d
connect system.serconsole.serial cnt1 = system.motherboard.sio.com[0]
instantiate-components
system.serconsole.con.capture-start "%(simics_console)s"
c
"""

def simics_zephyr_add(name, simics_cmds = simics_zephyr_cmds):
    """Configure a virtual Zephyr target running inside Simics

    Simics is a platform simulator available from Wind River Systems;
    it can be used to implement a virtual machine environment that
    will be treated as a target.

    Add to your configuration file
    ``/etc/ttbd-production/conf_10_targets.py``:

    .. code-block:: python

       simics_zephyr_add("szNN")

    restart the server and it yields::

      $ tcf list
      local/szNN


    :param str name: name of the target (:ref:`naming
       best practices <bp_naming_targets>`).

    **Overview**

    A Simics invocation in a standalone workspace will be created by
    the server to run for earch target when it is powered on. This
    driver currently supports only booting an ELF target and console
    output support (no console input or debugging). For more details,
    see :class:`ttbl.tt.simics`.

    Note the default Simics settings for Zephyr are defined in
    :data:`simics_zephyr_cmds` and you can create target which use a
    different Simics configuration by specifying it as a string in
    parameter *simics_cmd*.

    **Bill of materials**

    - Simics installed in your server machine

    - :class:`ttbl.tt.simics` expects a global environment variable
      SIMICS_BASE_PACKAGE defined to point to where Simics (and its
      extension packages) have been installed; e.g.::

        SIMICS_BASE_PACKAGE=/opt/simics/5.0/simics-5.0.136

    """
    ttbl.config.target_add(
        ttbl.tt.simics(name, simics_cmds = simics_cmds),
        tags = dict(
            bsp_models = { 'x86' : None },
            bsps = {
                'x86': {
                    'zephyr_board': 'qemu_x86_nommu',
                    'zephyr_kernelname': 'zephyr.elf'
                }
            }
        ),
        target_type = "simics-zephyr-x86")

def tinytile_add(name,
                 serial_number,
                 ykush_serial,
                 ykush_port_board,
                 ykush_port_serial = None,
                 serial_port = None):
    """**Configure a tinyTILE for the fixture described below.**

    The tinyTILE is a miniaturization of the Arduino/Genuino 101 (see
    https://www.zephyrproject.org/doc/boards/x86/tinytile/doc/board.html).

    The fixture used by this configuration uses a YKUSH hub for power
    switching, no debug/JTAG interface and allows for an
    optional external serial port using an USB-to-TTY serial adapter.

    Add to a server configuration file:

    .. code-block:: python

       tinytile_add("ti-NN", "SERIALNUMBER", "YKNNNNN", PORTNUMBER,
                    [ykush_port_serial = N2,]
                    [serial_port = "/dev/tty-NAME"])

    restart the server and it yields::

      $ tcf list
      local/ti-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the tinyTILE

    :param str ykush_serial: :ref:`USB serial number
      <ykush_serial_number>` of the YKUSH hub

    :param int ykush_port_board: number of the YKUSH downstream port
      where the board is connected.

    :param int ykush_port_serial: (optional) number of the YKUSH
       downstream port where the board's serial port is connected.

    :param str serial_port: (optional) name of the serial port
      (defaults to ``/dev/tty-NAME``)


    **Overview**

    The tinyTILE is powered via the USB connector. The tinyTILE does
    not export a serial port over the USB connector--applications
    loaded onto it might create a USB serial port, but this is not
    necessarily so all the time.

    Thus, for ease of use this fixture connects an optional external
    USB-to-TTY dongle to the TX/RX/GND lines of the tinyTILE that
    allows a reliable serial console to be present. To allow for
    proper MCU board reset, this serial port has to be also power
    switched on the same YKUSH hub (to avoid ground derivations).

    For the serial console output to be usableq, the Zephyr Apps
    configuration has to be altered to change the console to said
    UART. The client side needs to be aware of that (via
    configuration, for example, to the Zephyr App Builder).

    When the serial dongle is in use, the power rail needs to first
    power up the serial dongle and then the board.

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    This fixture uses :class:`ttbl.tt.tt_dfu` to implement the target;
    refer to it for implementation details.

    **Bill of materials**

    - two available ports on an YKUSH power switching hub (serial
      *YKNNNNN*); only one if the serial console will not be used.
    - a tinyTILE board
    - a USB A-Male to micro-B male cable (for board power)
    - a USB-to-TTY serial port dongle
    - three M/M jumper cables

    **Connecting the test target fixture**

    1. (if not yet connected), connect the YKUSH to the server system
       and to power as described in :py:func:`ykush_targets_add`

    2. connect the Tiny Tile's USB port to the YKUSH downstream port
       N1

    3. (if a serial console will be connected) connect the USB-to-TTY
       serial adapter to the YKUSH downstream port N2

    3. (if a serial console will be connected) connect the USB-to-TTY
       serial adapter to the Tiny Tile with the M/M jumper cables:

       - USB FTDI Black (ground) to Tiny Tile's serial ground pin
         (fourth pin from the bottom)
       - USB FTDI White (RX) to the Tiny Tile's TX.
       - USB FTDI Green (TX) to Tiny Tile's RX.
       - USB FTDI Red (power) is left open, it has 5V.

    **Configuring the system for the fixture**

    1. Choose a name for the target: *ti-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`.

       Note these boards, when freshly plugged in, will only stay in
       DFU mode for *five seconds* and then boot Zephyr (or whichever
       OS they have), so the USB device will dissapear. You need to
       run the lsusb or whichever command you are using quick (or
       monitor the kernel output with *dmesg -w*).

    4. Configure *udev* to add a name for the serial device that
       represents the USB-to-TTY dongle connected to the target so we can
       easily find it at ``/dev/tty-TARGETNAME``. Different options for
       USB-to-TTY dongles :ref:`with <usb_tty_serial>` or :ref:`without
       <usb_tty_sibling>` a USB serial number.

    """
    if ykush_port_serial:
        if serial_port == None:
            serial_port = "/dev/tty-" + name
        power_rail = [
            ttbl.pc_ykush.ykush(ykush_serial, ykush_port_serial),
            ttbl.pc.delay_til_file_appears(serial_port),
            ttbl.cm_serial.pc()
        ]
    else:
        power_rail = []
    pc_board = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    power_rail += [
        pc_board,
        ttbl.pc.delay_til_usb_device(serial_number)
    ]

    ttbl.config.target_add(
        ttbl.tt.tt_dfu(name, serial_number, power_rail, pc_board,
                       serial_ports = [
                           "pc",
                           dict(port = serial_port, baudrate = 115200)
                       ]),
        tags = {
            'bsp_models': {
                'x86+arc+arm': ['x86', 'arc', 'arm'],
                'x86+arc': ['x86', 'arc'],
                'x86+arm': ['x86', 'arm'],
                'arc+arm': ['arc', 'arm'],
                'x86': None,
                'arm': None,
                'arc': None
            },
            'bsps' : {
                "x86":  dict(zephyr_board = "tinytile",
                             zephyr_kernelname = 'zephyr.bin',
                             dfu_interface_name = "x86_app",
                             console = ""),
                "arm":  dict(zephyr_board = "arduino_101_ble",
                             zephyr_kernelname = 'zephyr.bin',
                             dfu_interface_name = "ble_core",
                             console = ""),
                "arc": dict(zephyr_board = "arduino_101_sss",
                            zephyr_kernelname = 'zephyr.bin',
                            dfu_interface_name = 'sensor_core',
                            console = "")
            },
        },
        target_type = "tinytile"
    )


def nw_default_targets_add(letter, pairs = 1):
    """
    Add the default targets to a configuration

    This adds a configuration which consists of a network and @pairs
    pairs of QEMU Linux VMs (one without upstream NAT connection, one with).

    The network index nw_idx will be used to assign IP addresses
    (192.168.IDX.x and fc00::IDX:x)

    IP address assignment:
    - .1         is the server (this machine)
    - .2 - 10    Virtual Linux machines
    - .30 - 45   Virtual Zephyr machines
    - .100- 255  Real HW targets

    """
    assert isinstance(letter, basestring)
    assert len(letter) == 1

    nw_idx = ord(letter)
    nw_name = "nw" + letter

    # Add the network target
    ttbl.config.interconnect_add(
        ttbl.tt.tt_power(nw_name, [ vlan_pci() ]),
        tags = dict(
            ipv6_addr = 'fc00::%02x:1' % nw_idx,
            ipv6_prefix_len = 112,
            ipv4_addr = '192.168.%d.1' % nw_idx,
            ipv4_prefix_len = 24,
        ),
        ic_type = "ethernet"
    )

    # Add QEMU Fedora Linux targets with addresses .4+.5, .6+.7, .7+.8...
    # look in TCF's documentation for how to generate tcf-live.iso
    for pair in range(pairs):
        # Add two QEMU Fedora Linux targets on the network
        # qlf04LETTER .2 has only access to the test network
        v = 2 * pair + 4
        ttbl.config.target_add(
            # Note tt_qemu_linux needs those basic tags fed to the constructor
            tt_qemu_linux("qlf%02d" % v + letter,
                          tags = dict(
                              qemu_ro_image = '/var/lib/ttbd/tcf-live.iso',
                              qemu_bios_image = '/usr/share/qemu/bios.bin',
                              ram_megs = 1024,
                              )),
            target_type = "qemu-linux-fedora-x86_64",
            tags = dict(
                ssh_client = True,
                interconnects = {
                    nw_name: dict(
                        ipv4_addr = "192.168.%d.%d" % (nw_idx, v),
                        ipv4_prefix_len = 24,
                        ipv6_addr = "fc00::%02x:%02x" % (nw_idx, v),
                        ipv6_prefix_len = 112,
                        mac_addr = "02:%02x:00:00:00:%02x" % (nw_idx, v),
                    )
                }
            ))
        if False:
            # FIXME: NAT is currently broken
            # qlf05LETTERH .5 has access to the test network and
            # upstream via NAT
            v = 2 * pair + 5
            ttbl.config.target_add(
                # note tt_qemu_linux needs those basic tags fed to the
                # constructor
                tt_qemu_linux("qlf%02d" % v + letter + "H",
                              tags = dict(
                                  qemu_ro_image = '/var/lib/ttbd/tcf-live.iso',
                                  qemu_bios_image = '/usr/share/qemu/bios.bin',
                                  ram_megs = 1024,
                                  )),
                target_type = "qemu-linux-fedora-x86_64",
                tags = dict(
                    ssh_client = True,
                    nat_host = True,
                    ram_megs = 2048,	# Needed for dnf updates to work
                    interconnects = {
                        nw_name: dict(
                            ipv4_addr = "192.168.%d.%d" % (nw_idx, v),
                            ipv4_prefix_len = 24,
                            ipv6_addr = "fc00::%02x:%02x" % (nw_idx, v),
                            ipv6_prefix_len = 112,
                            mac_addr = "02:%02x:00:00:00:%02x" % (nw_idx, v),
                        ),
                        'nat_host': {},
                    }))


class minnowboard_EFI_boot_grub_pc(ttbl.tt_power_control_impl):
    """A power control interface that directs EFI to boot grub

    When something (with a serial console that can access EFI) is
    powering up, this looks at the output. If it takes us to the EFI
    shell, then it runs fs0:\\EFI\\BOOT\bootx64 manually, which shall
    launch the automatic grub process.

    It relies on :download:`../ttbd/setup-efi-grub2-elf.sh`
    making *grub2* print a banner ``TCF Booting kernel-HEXID.elf``.

    Intended for Minnowboard and to be placed in the power rail of
    anything right after powering up the anything.
    """
    def __init__(self, console_name = None):
        ttbl.tt_power_control_impl.__init__(self)
        self.console_name = console_name

    def power_on_do(self, target):	# pylint = disable:missing-docstring
        index, matched_text, offset = target.expect(
            [
                # Booted right!
                re.compile(r"TCF Booting kernel-.*\.elf"),
                # Booted into EFI Shell, no mappings found
                # -> power-cycle
                re.compile('(Cannot find required map name|No mapping found)',
                           re.MULTILINE | re.DOTALL),
                # Booted into EFI Shell -- note different versions of
                # the EFI bios print different stuff...
                # -> coerce
                re.compile('.*Shell>',
                           re.MULTILINE | re.DOTALL),
                # EFI most likely didn't find the USB drive
                # -> let's try a power cycle
                re.compile("bootx64.* is not recognized as an internal "
                           "or external command, operable program, or "
                           "batch file", re.MULTILINE | re.DOTALL),
                # Grub couldn't find the USB drive
                # -> let's try a power cycle
                re.compile("error: disk .* not found.*"
                           "error: you need to load the kernel first.*"
                           "grub>", re.MULTILINE | re.DOTALL),
            ],
            timeout = 50,
            what = "waiting for console traces of boot")
        if index == 0:
            target.log.info("Boot sequence: booted off grub2")
            return
        # Error handling -- something failed, so we will
        # have the power rail control sequence power
        # everything off (disconnecting the USB drive from
        # the target), wait half a second and power it up
        # again. Maybe this time the boot drive will be
        # properly detected.
        elif index == 2:
            target.log.info("Boot sequence: USB boot drive not set "
                            "as default; asking EFI to boot off fs0:")
            try:
                target.expect_sequence(
                    [ {
                        "send": "fs0:\\EFI\\BOOT\\bootx64\r\n",
                        "receive": re.compile(r"TCF Booting kernel-.*\.elf"),
                        "fail": re.compile(
                            "(Invalid mapping name"
                            "|Cannot find mapped device"
                            "|is not recognized as an internal or external command.*)"),
                        "wait": 1,
                        # delay .3 seconds between characters,
                        # otherwise minnowboard might loose some
                        "delay": 0.3,
                    } ],
                    offset = offset)
                target.log.info("Boot sequence: booted off grub2 after "
                                "EFI coercion")
            except target.expect_e as e:
                target.log.warning("Boot sequence: EFI coercion failed; "
                                   "power-cycling and retrying: %s" % e)
                raise self.retry_all_e(0.5)
        elif index == 1 or index == 2:
            target.log.warning("Boot sequence: EFI didn't find the USB "
                               "boot drive? power-cycling and retrying: %s"
                               % matched_text)
            raise self.retry_all_e(0.5)
        elif index == 3:
            target.log.warning("Boot sequence: Grub didn't find the USB "
                               "boot drive? power-cycling and retrying: %s"
                               % matched_text)
            raise self.retry_all_e(0.5)
        else:
            raise AssertionError("Boot sequence: landed at unknown "
                                 "index %s" % index)

    def power_off_do(self, _target):
        pass

    def reset_do(self, _target):
        pass

    def power_get_do(self, _target):
        return True


def minnowboard_add(name, power_controller, usb_drive_serial,
                    usbrly08b_serial, usbrly08b_bank, serial_port = None):
    """**Configure a Minnowboard for use with Zephyr**

    The `Minnowboard <https://minnowboard.org/>`_ is an open hardware
    board that can be used to run Linux, Zephyr and other OSes. This
    configuration supports power control, a serial console and image
    flashing.

    Add to a server configuration file (note the serial numbers and
    paths are examples that you need to adapt to your configuration):

    .. code-block:: python

       ttbl.config.target_add(ttbl.tt.tt_power(
           "minnowboard-NN-disk",
           power_control = [ ttbl.usbrly08b.plugger("00023456", 0) ],),
           tags = { 'skip_cleanup': True }
       )
       ttbl.config.targets['minnowboard-56-disk'].disable('')
       minnowboard_add("minnowboard-NN",
                       power_controller = ttbl.pc.dlwps7("http://admin:1234@sp06/6"),
                       usb_drive_serial = "76508A8E",
                       usbrly08b_serial = "00023456", usbrly08b_bank = 0)

    .. notes:
       - adding the disk target allows to access the disk easily
         (power it off to connect it to the server, on to the target).
       - ensure the disk is not in the cleanups (*skip_cleanup* is
         True), otherwise it will be powered off in the middle of the
         minnowboard operation.
       - ensure it is disabled, so it is not picked up by most runs.

    restart the server and it yields::

      $ tcf list
      local/minnowboard-NN

    :param str name: name of the target

    :param ttbl.tt_power_control_impl power_controller: an
      implementation of a power controller than can power off or on
      the Minnowboard, for example a DLWPS7::

        ttbl.pc.dlwps7("http://admin:1234@sp06/6")

    :param str usb_drive_serial: USB Serial number for the USB boot
      drive that is multiplexed to the Minnowboard and the server
      host as per the *Overview* below.

    :param str usbrly08b_serial: USB Serial number for the USBRLY8b
      board that is going to be used to multiplex the USB boot drive
      from the minnowboard to the server host.

    :param int usbrly08b_bank: relay bank number (#0 will use relays
      1, 2, 3 and 4, #1 will use 5, 6, 7 and 8).

    :param str serial_port: (optional) name of the serial port
      (defaults to ``/dev/tty-NAME``)

    **Overview**

    The Minnowboard provides a serial port which is used to control
    the BIOS (when needed) and to access the OS. Any AC power controller
    can be used to power on/off the Minnowboard's power brick.

    The target type implemented here can only boot ELF kernels and is
    implemented using the :class:`grub2 loader <ttbl.tt.grub2elf>`. In
    summary, a USB drive is used as a boot drive that is multiplexed
    using a USBRLY8b relay bank from the Minnowboard to the
    server:

     - when the Minnowboard is off, the USB drive is connected to the
       server, so it can be setup / partitioned / formatted / flashed

     - when Minnowboard is on, the USB drive is connected to it.

    **Bill of materials**

    - A Minnowboard and its power brick

    - An open socket on an AC power switch, like the :class:`Digital
      Logger Web Power Switch 7 <ttbl.pc.dlwps7>`

    - A USB serial cable terminated with 6 way header (eg:
      https://www.amazon.com/Converter-Terminated-Galileo-BeagleBone-Minnowboard/dp/B06ZYPLFNB)
      preferibly with a serial number (easier to configure)

    - a USB drive (any size will do)

    - four relays on a USBRLY08b USB relay bank
      (https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm)
      [either 1, 2, 3 and 4 or 5, 6, 7 and 8]

    - One USB Type A female to male cable, one USB Type A male cable

    - Two USB ports into the server

    **Connecting the test target fixture**

    1. connect the Minnowboard's power trick to the socket in the AC
       power switch and to the board DC input

    2. connect the USB serial cable to the Minnowboard's TTY
       connection and to the server

    3. Cut and the USB-A male-to-female cable and separate the four
       lines on each end; likewise, cut and separate the four lines on
       the other USB-A male cable; follow the detailed instructions in
       :class:`ttbl.usbrly08b.plugger` where:

       - Ensure the USBRLY8B is properly connected and setup as per
         :class:`ttbl.usbrly08b.rly08b`

       - *DUT* is the USB-A female where we'll connect the USB drive,
         plug the USB drive to it. Label as *minnowboard-NN boot*

       - *Host A1/ON/NO* is the USB-A male connector we'll connect to
         the Minnowboard's USB 2.0 port -- label as
         *minnowboard-NN ON* and plug to the board

       - *Host A2/OFF/NC* is the USB-A make connector we'll connect to
         the server's USB port -- label as *minnowboard-NN OFF* and
         plug to the server.

       Note tinning the cables for better contact will reduce the
       chance of the USB device misbehaving.

       It is critical to get this part right; the cable connected to
       the NC terminals has to be what is connected to the server when
       the target is *off*.

       It is recommended to test this thoroughly in a separate system
       first.

    4. Ensure the Minnowboard MAX is flashed with *64 bit* firmware,
       otherwise it will fail to boot.

       To update it, connect it to a solid power (so TCF doesn't power
       it off in the middle), download the images from
       https://firmware.intel.com/projects/minnowboard-max (0.97 as of
       writing this) and follow the instructions.

    **Configuring the system for the fixture**

    1. Choose a name for the target: *minnowboard-NNx* (see :ref:`naming
       best practices <bp_naming_targets>`).

    2. Find the serial number of the USB drive, blank it to ensure it
       is properly initialized; example, in this case being
       */dev/sdb*::

         $ lsblk -nro NAME,TRAN,SERIAL | grep USB-DRIVE-SERIAL
         sdb usb USB-DRIVE-SERIAL
         $ dd if=/dev/zero of=/dev/sdb

    3. Find the serial number of the USBRLY8b and determine the relay
       bank to use; bank 0 for relays 1, 2, 3 and bank 1 for relays 4
       or 5, 6, 7 and 8.

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the serial dongle's *serial number*; e.g.::

         SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "AC0054PT", \\
           SYMLINK += "tty-minnowboard-NN"

    5. Connect the Minnowboard to a display [vs the serial port, to
       make it easier] and with a keyboard, plug the USB drive
       directly and boot into the BIOS.

       a. Enter into the *Boot Options Manager*, ensure *EFI USB
          Device* is enabled; otherwise, add the option.

          Depending on the BIOS revision, the save/commit mechanism
          might be tricky to get right, so double check it by
          rebooting and entering the BIOS again to verify that *EFI
          booting from USB* is enabled.

       b. In the same *Boot Options Manager*, change the boot order to
          consider the *EFI booting from USB* option to be the first
          thing booted.

          Note that the EFI Bios tends to reset the boot drive order
          if at some point it fails to detect it, so a boot coercer
          like :class:`minnowboard_EFI_boot_grub_pc` is needed. This
          will workaound the issue.


    FIXME:
     - FIXME: need to have it re-plug the dongle if the server
       doesn't see it

    Troubleshooting:

     - UEFI keeps printing::

         map: Cannot find required map name.

       Make sure:

        - the USB relay plugger is properly connected and the drive is
          re-directed to the target when powered on, to the server
          when off

        - the drive is not DOS formatted, it needs a GPT
          partition table. Wipe it hard and re-deploy (eg: running tcf
          run) so it will be re-flashed from the ground up::

            # dd if=/dev/zero of=/dev/DEVICENODE bs=$((1024 * 1024)) count=100

        - Minnowboard is picky and some drives are faulty for it, even
          if they work ok in any other machine; replace the drive?

    - UEFI will do nothing when *BOOTX64* is executed::

        Shell> fs0:\EFI\BOOT\bootx64
        Shell>

      Double check the Minnowboard is flashed with a 64 bit firmware;
      see above in **Connecting the test target fixture**.

    """
    if serial_port == None:
        serial_port = "/dev/tty-" + name
    ttbl.config.target_add(
        ttbl.tt.grub2elf(name, power_controller, usb_drive_serial,
                         usbrly08b_serial, usbrly08b_bank,
                         serial_port,
                         boot_coercer = minnowboard_EFI_boot_grub_pc()),
        tags = {
            'bsp_models': { 'x86': None },
            'bsps': {
                'x86': dict(zephyr_board = 'minnowboard',
                            zephyr_kernelname = 'zephyr.strip',
                            console = "")
            },
        },
        target_type = "minnowboard-max")
