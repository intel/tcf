#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
.. _conf_00_lib_mcu:

Configuration API for MCUs used with the Zephyr OS and others
-------------------------------------------------------------
"""

import copy
import errno
import logging
import os
import re
import subprocess
import time

import commonl
import ttbl
import ttbl.debug
import ttbl.images
import ttbl.openocd
import ttbl.pc
import ttbl.pc_ykush
import ttbl.rsync
import ttbl.socat
import ttbl.usbrly08b

zephyr_sdk_path = os.path.join(
    os.environ.get("ZEPHYR_SDK_INSTALL_DIR", "/opt/zephyr-sdk-0.10.0"),
    "sysroots/x86_64-pokysdk-linux")

# From the Zephyr SDK
openocd_sdk_path = os.path.join(zephyr_sdk_path, "usr/bin/openocd")
openocd_sdk_scripts = os.path.join(zephyr_sdk_path, "usr/share/openocd/scripts")

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
      :py:func:`conf_00_lib_pdu.dlwps7_add`.

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
      :py:func:`conf_00_lib_pdu.ykush_targets_add`

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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *arduino101-NN* (where NN is a
       number)

    2. Find the YKUSH's serial number *YKNNNNN* [plug it and run *dmesg*
       for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Configure *udev* to add a name for the serial device that
       represents the USB-to-TTY dongle connected to the target so we can
       easily find it at ``/dev/tty-TARGETNAME``. Different options for
       USB-to-TTY dongles :ref:`with <usb_tty_serial>` or :ref:`without
       <usb_tty_sibling>` a USB serial number.

    """
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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
       and to power as described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

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
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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


arduino_fqbns = {
    # $ arduino-cli core update-index
    # $ arduino-cli core install arduino:avr
    "arduino:avr:mega": 'hex',
    # $ arduino-cli core install arduino:sam
    "arduino:sam:arduino_due_x_dbg": "bin",
}

def arduino_add(name, usb_serial_number, fqbn,
                power_rail = None, serial_port = None):
    """**Configure an Arduino board that can be flashed with Arduino-CLI**

    The Arduinos are boards that include builtin flashers which the
    :ref:`*arduino-cli* tool <installing>` can use.

    This configuration allows to add multiple models of Arduino (for
    which a FQBN mapping is known) with:

    - basic power control
    - console interface
    - image flashing

    For example, to power-control using a ykush power-switching hub,
    add to a server configuration file:

    .. code-block:: python

       arduino_add(name = "arduino-mega-NN", "mega",
                   usb_serial_number = "SERIALNUMBER",
                   power_rail = [ ttbl.pc_ykush.pc("YKXXXXX", 2) ])

    restart the server and it yields::

      $ tcf list
      local/arduino-mega-NN

    :param str name: name of the target

    :param str serial_number: USB serial number for the board

    :param str fqbn: model of the board. This is a string listed in
      :data:`conf_00_lib_mcu.arduino_fqbns` which indicates a few
      needed parameters.

      - Arduino Due: arduino:sam:arduino_due_x_dbg
      - Arduino Mega: arduino:avr:mega

      To find your board's FQBN, plug to your machine and run::

        $ arduino-cli board list
        Port         Type              Board Name                     FQBN                          Core
        /dev/ttyACM0 Serial Port (USB) Arduino Mega or Mega 2560      arduino:avr:mega              arduino:avr
        /dev/ttyACM1 Serial Port (USB) Arduino Due (Programming Port) arduino:sam:arduino_due_x_dbg arduino:sam

      And you will need to install the Core support with::

        $ arduino-cli core update-index
        $ arduino-cli core install COREPACKAGE

      for the user running the daemon as well as for any user building
      with the client.

    :param str serial_port: name of the serial port (defaults to
      /dev/tty-TARGETNAME).

    :param list power_rail: power rail to power on/off the board,
      which will be passed to :class:`ttbl.power.interface`.

    **Overview**

    Per this :ref:`rationale <arduino101_rationale>`, current leakage and
    full power down needs necesitate of this setup to cut all power to
    all cables connected to the board (power and serial).

    **Bill of materials**

    - an Arduino Mega board

    - a USB A-Male to B male cable (for board power, flashing and
      console)

    - (for full on power control) one available port on an YKUSH power
      switching hub (serial *YKNNNNN*) or other control

      None connecting the barrel power supply and the USB cable would
      still require a way to shut off power to the USB power supply,
      otherwise the board will not reset.

    **Connecting the test target fixture**

    Using a YKUSH:

    1. connect the Arduino USB B to the YKUSH downstream port *N*

    2. connect the YKUSH to the server system and to power as
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    Without a YKUSH:

    1. connect the Arduino USB B to a server's USB port

    **Configuring the system for the fixture**

    Ensure the steps to setup an :ref:`*Arduino CLI*
    <arduino_cli_setup>` flasher have been run.

    1. Choose a name for the target: *arduino-mega-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it
       and run *dmesg* for a quick find], see
       :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    """
    assert isinstance(name, str)
    assert fqbn in arduino_fqbns, \
        "FQBN %s not known in conf_00_lib_mcu.arduino_fqbns" % fqbn

    if usb_serial_number:
        assert isinstance(usb_serial_number, str)
    else:
        serial_port = name
    if serial_port:
        assert isinstance(serial_port, str)
    else:
        serial_port = "/dev/tty-" + name

    target = ttbl.test_target(name)
    ttbl.config.target_add(
        target,
        tags = dict(
            bsp_models = dict(
                arm = None,
            ),
            bsps = dict(
                arm = dict(
                    sketch_fqbn = fqbn,
                    sketch_extension = arduino_fqbns[fqbn],
                ),
            ),
        ),
        target_type = commonl.name_make_safe(fqbn))

    console_file_name = "/dev/tty-%s" % name
    serial0_pc = ttbl.console.serial_pc(console_file_name)

    if power_rail == None:
        power_rail = []
    target.interface_add(
        "power",
        ttbl.power.interface(
            *
            power_rail +
            [
                (
                    "USB device present",
                    ttbl.pc.delay_til_usb_device(usb_serial_number)
                ),
                (
                    "TTY file present",
                    ttbl.pc.delay_til_file_appears(
                        console_file_name, poll_period = 1, timeout = 25,
                    )
                ),
                ( "serial0", serial0_pc )
            ]
        )
    )

    target.interface_add(
        "console",
        ttbl.console.interface(
            serial0 = serial0_pc,
            default = "serial0",
        )
    )

    target.interface_add(
        "images",
        ttbl.images.interface(**{
            # The ARM BSP refers to an arduino_cli_c
            "kernel-arm": ttbl.images.arduino_cli_c(
                # power cycle all components before flashing
                power_cycle_pre = [ ],
                # power off everyhing after flashing
                power_off_post = [ ],
                # disable the serial0 console so flasher can user that port
                consoles_disable = [ 'serial0' ],
            ),
            "kernel": "kernel-arm"
        })
    )

    return target


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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    3. Connect the power brick to the EMSK's power barrel

    4. Connect the power brick to the available power in the power switch

    **Configuring the system for the fixture**

    1. Choose a name for the target: *emsk-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    """
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
    zephyr_boards = dict(
        emsk7d_v22 = 'em_starterkit_em7d_v22',
        emsk7d = 'em_starterkit_em7d',
        emsk11d = 'em_starterkit_em11d',
        emsk9d = 'em_starterkit'
    )
    assert model in zephyr_boards, \
        "Please specify a model (%s) as per the DIP configuration " \
        "and firmware loaded" % ", ".join(list(zephyr_boards.keys()))
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



def esp32_add(name,
              usb_serial_number = None,
              ykush_serial = None,
              ykush_port_board = None,
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

    :param str usb_serial_number: (optional) USB serial number for the
      *esp32*; defaults to same as the target

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
       and to power as described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    2. connect the esp32's USB port to the YKUSH downstream port
       *PORTNUMBER*

    **Configuring the system for the fixture**

    0. See instructions in :class:`ttbl.tt.tt_esp32` to install and
       configure prerequisites in the server.

    1. Choose a name for the target: *esp32-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`.

       Note these boards usually have a serial number of *001*; it can
       be updated easily to a unique serial number following
       :ref:`these steps  <cp210x_serial_update>`.

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.

    """
    if usb_serial_number == None:
        usb_serial_number = name
    if serial_port == None:
        serial_port = "/dev/tty-" + name
    if ykush_serial and ykush_port_board:
        power_rail = ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
    else:
        # FIXME: add a fake power rail that resets the board on on() with
        # esptool.py --after hard_reset read_mac
        power_rail = []

    target = ttbl.test_target(name)
    ttbl.config.target_add(
        target,
        tags = dict(
            bsp_models = dict(
                xtensa = None,
            ),
            bsps = dict(
                xtensa = dict(
                    zephyr_board = "esp32",
                    zephyr_kernelname = 'zephyr.elf',
                    console = ""),
            ),
        ),
        target_type = "esp32")

    console_file_name = "/dev/tty-%s" % name
    serial0_pc = ttbl.console.serial_pc(console_file_name)

    target.interface_add(
        "power",
        ttbl.power.interface(
            *
            power_rail +
            [
                ( "USB device present",
                  ttbl.pc.delay_til_usb_device(usb_serial_number) ),
                ( "TTY file present",
                  ttbl.pc.delay_til_file_appears(
                      console_file_name, poll_period = 1, timeout = 25,
                  )),
                ( "serial0", serial0_pc )
            ]
        )
    )

    target.interface_add(
        "console",
        ttbl.console.interface(
            serial0 = serial0_pc,
            default = "serial0",
        )
    )

    target.interface_add(
        "images",
        ttbl.images.interface(**{
            "kernel": ttbl.images.esptool_c(),
            "kernel-xtensa": "kernel"
        })
    )



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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *frdm-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *mv-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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

    :param ttbl.power.impl_c pc: power controller to switch
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
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *nrf51-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the boards' *serial number*.
    """
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
    assert isinstance(family, str) \
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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *qc10000-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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


#: QEMU Zephyr target descriptors
#:
#: Dictionary describing the supported BSPs for QEMU targets and what
#: Zephyr board and commandline they map to.
#:
#: The *key* is the TCF *BSP* which maps to the binary
#: *qemu-system-BSP*. If the field *zephyr_board* is present, it
#: refers to how that BSP is known to the Zephyr OS.
#:
#: New entries can be added with:
#:
#: >>> target_qemu_zephyr_desc['NEWBSP'] = dict(
#: >>>     cmdline = [
#: >>>         '/usr/bin/qemu-system-NEWBSP',
#: >>>         'arg1', 'arg2', ...
#: >>>     ],
#: >>>     zephyr_board = 'NEWBSPZEPHYRNAME'
#: >>> )
target_qemu_zephyr_desc = {
    # from zephyr.git/boards/ARCH/TYPE/board.cmake
    'arm': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-arm",
            "-cpu", "cortex-m3",
            "-machine", "lm3s6965evb",
            "-nographic",
            "-vga", "none",
        ],
        zephyr_board = 'qemu_cortex_m3',
    ),

    'nios2': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-nios2",
            "-machine", "altera_10m50_zephyr",
            "-nographic",
        ],
    ),

    'riscv32': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-riscv32",
            "-nographic",
            "-machine", "sifive_e",
        ],
    ),

    'x86': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-i386",
            "-m", "8",
            "-cpu", "qemu32,+nx,+pae",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
            "-nographic",
            "-no-acpi",
        ],
    ),

    'x86_64': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-x86_64",
            "-nographic",
        ],
    ),

    'xtensa': dict(
        cmdline = [
            zephyr_sdk_path + "/usr/bin/qemu-system-xtensa",
	    "-machine", "sim",
            "-semihosting",
            "-nographic",
            "-cpu", "sample_controller"
        ],
    ),
}



def target_qemu_zephyr_add(
        name,
        bsp = None, zephyr_board = None, target_type = None,
        nw_name = None,
        cmdline = None):
    """
    Add a QEMU target that can run the `Zephyr OS <http://zephyrproject.org>`_.

    :param str name: target's :ref:`name <bp_naming_targets>`.

    :param str bsp: what architecture the target shall implement;
      shall be available in :data:`target_qemu_zephyr_desc`.

    :param str zephyr_board: (optional) type of this target's BSP for
      the Zephyr OS; defaults to whatever :data:`target_qemu_zephyr_desc`
      declares or *BSP* if none.

    :param str target_type: (optional) what type the target shall
      declare; defaults to *qz-BSP*.

    :param str nw_name: (optional) name of network/interconnect to
      which the target is connected. Note that the configuration code
      shall manually configure the network metadata as this serves
      only to ensure a TAP device is created before the QEMU daemon is
      started. E.g.::

      >>> target = target_qemu_zephyr_add("qzx86-36a", 'x86', nw_name = "nwa")
      >>> x, y, _ = nw_indexes('a')
      >>> index = 36
      >>> target.add_to_interconnect(    	# Add target to the interconnect
      >>>     "nwa", dict(
      >>>         mac_addr = "02:%02x:00:00:%02x:%02x" % (x, y, index),
      >>>         ipv4_addr = '192.%d.%d.%d' % (x, y, index),
      >>>         ipv4_prefix_len = 24,
      >>>         ipv6_addr = 'fd:%02x:%02x::%02x' % (x, y, index),
      >>>         ipv6_prefix_len = 104)
      >>> )

    :param str target_type: (optional) what type the target shall
      declare; defaults to *qz-BSP*.

    :param str cmdline: (optional) command line to start this QEMU
      virtual machine; defaults to whatever :data:`target_qemu_zephyr_desc`
      declares.

      Normally you *do not need* to set this; see
      :class:`ttbl.qemu.pc` for details on the command line
      specification if you think you do.
    """
    assert bsp == None or isinstance(bsp, str)
    assert nw_name == None or isinstance(nw_name, str)
    assert zephyr_board == None or isinstance(zephyr_board, str)
    assert target_type == None or isinstance(target_type, str)
    assert cmdline == None or isinstance(cmdline, list) \
        and all(isinstance(i, str) for i in cmdline)

    if bsp == None:
        raise AssertionError("FIXME: auto bsp extraction from name pending")
    else:
        assert bsp in list(target_qemu_zephyr_desc.keys()), \
            "Unknown BSP %s (not found in " \
            "conf_00_lib_mcu.target_qemu_zephyr_desc)"
    if not zephyr_board:
        zephyr_board = target_qemu_zephyr_desc[bsp].get("zephyr_board",
                                                        "qemu_" + bsp)
    if not target_type:
        target_type = "qz-" + bsp
    if not cmdline:
        cmdline = target_qemu_zephyr_desc[bsp]['cmdline']

    cmdline_zephyr = [

        # Consoles: add one serial port
        #
        # for each console called NAME, QEMU writes data received to
        # console-NAME.read, TCF writes data to send to
        # console-NAME.write; we later add a consoles interface
        # implemented with the ttbl.console.generic_c object that can
        # read/write into the files created by QEMU.
        #
        "-chardev", "socket,id=serial0,server,nowait,path=%(path)s/console-serial0.write,logfile=%(path)s/console-serial0.read",
        "-serial", "chardev:serial0",
    ]

    target = ttbl.test_target(name)
    ttbl.config.target_add(target, target_type = target_type,
                           tags = {
                               'bsp_models': { bsp: None },
                               'bsps': {
                                   bsp: dict(
                                       zephyr_board = zephyr_board,
                                       zephyr_kernelname = 'zephyr.elf',
                                   )
                               }
                           })

    # The QEMU object exposes a power control interface for starting /
    # stopping, image flashing and debug setings, we'll add them below.
    qemu_pc = ttbl.qemu.pc(cmdline + cmdline_zephyr, nic_model = "e1000")

    # The QEMU object exposes an image setting interface for specifying a
    # bios / kernel / initrd file
    target.interface_add(
        "images",
        ttbl.images.interface(**{
            "kernel": qemu_pc,
            # needed because Zephyr layer sends as kernel-BSP and
            # otherwise the images interface will not even send it our way
            "kernel-" + bsp: "kernel",
            "bios": qemu_pc,
            "initrd": qemu_pc,
        })
    )
    power_rail = []
    if nw_name:
        power_rail.append((
            "tuntap-" + nw_name, ttbl.qemu.network_tap_pc()
        ))
    power_rail.append(( "main_power", qemu_pc ))
    target.interface_add("power", ttbl.power.interface(*power_rail))
    target.interface_add(
        "console",
        ttbl.console.interface(
            # this object is only needed to read/write to
            # console-COMPONENT.{read,write}, which QEMU creates
            serial0 = ttbl.console.generic_c(chunk_size = 8,
                                             interchunk_wait = 0.15),
            default = "serial0",
        )
    )
    target.interface_add("debug", ttbl.debug.interface(**{ bsp: qemu_pc }))
    return target



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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *sam-e70-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

    3. Find the board's :ref:`serial number <find_usb_info>`

    4. Configure *udev* to add a name for the serial device for the
       board's serial console so it can be easily found at
       ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
       <usb_tty_serial>` using the board's *serial number*.

    """
    raise NotImplementedError("Needs porting to new openocd code in branch openocd")
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
    raise NotImplementedError("Needs porting to new interface style")
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


# relies on settings from conf_00_lib_mcu_stm32.py
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
       described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

    **Configuring the system for the fixture**

    1. Choose a name for the target: *stm32MODEL-NN* (where NN is a number)

    2. (if needed) Find the YKUSH's serial number *YKNNNNN* [plug it and
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
            #'disco_l475_iot1',
            # OpenOCD complains
            # Error: open failed
            # in procedure 'init'
            # in procedure 'ocd_bouncer'
            'stm32f3_disco',
    ):
        logging.error("WARNING! %s not configuring as this board is still "
                      "not supported", name)
        return

    if serial_port == None:
        serial_port = "/dev/tty-" + name

    if zephyr_board == None:
        # default to the same as model if there is no entry in the
        # dict or no 'zephyr' tag on it
        # this comes from conf_00_lib_mcu_stm32.stm32_models, which is
        # read before we use this function
        zephyr_board = stm32_models.get(model, {}).get('zephyr', model)

    target = ttbl.test_target(name)
    openocd_pc = ttbl.openocd.pc(serial_number, model, debug,
                                 openocd_path, openocd_scripts)
    serial0_pc = ttbl.console.serial_pc(serial_port)

    power_rail = []
    if ykush_serial and ykush_port_board:
        power_rail.append((
            "%s/%s main power" % (ykush_serial, ykush_port_board),
            ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board)
        ))
    elif ykush_serial == None and ykush_port_board == None:
        pass
    else:
        raise ValueError(
            "ykush_serial and ykush_port_board have to be"
            " both specified or both omitted")

    power_rail += [
        (
            "%s USB device present" % serial_number,
            ttbl.pc.delay_til_usb_device(serial_number,
                                         poll_period = .2, timeout = 5)
        ),
        (			# delay until serial port comes up
            "%s TTY present" % serial_port,
            ttbl.pc.delay_til_file_appears(serial_port,
                                           poll_period = .2, timeout = 5)
        ),
        ( "serial0", serial0_pc ),
        ( "OpenOCD", openocd_pc ),
    ]

    target.interface_add("power", ttbl.power.interface(*power_rail))

    target.interface_add("console", ttbl.console.interface(**{
        "serial0": serial0_pc
    }))

    target.interface_add("images", ttbl.images.interface(**{
        "kernel-arm": openocd_pc,
        "kernel": "kernel-arm",
    }))

    target.interface_add("debug", ttbl.debug.interface(**{
        "arm": openocd_pc,
    }))

    ttbl.config.target_add(
        target,
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


def tinytile_add(name,
                 usb_serial_number,
                 ykush_serial = None,
                 ykush_port_board = None,
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

    :param str usb_serial_number: USB serial number for the tinyTILE

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
       and to power as described in :py:func:`conf_00_lib_pdu.ykush_targets_add`

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
       run *dmesg* for a quick find], see :py:func:`conf_00_lib_pdu.ykush_targets_add`.

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
    if usb_serial_number == None:
        usb_serial_number = name
    if serial_port == None:
        serial_port = "/dev/tty-" + name
    serial0_pc = ttbl.console.serial_pc()

    target = ttbl.test_target(name)

    power_rail = []
    if ykush_serial and ykush_port_board:
        power_rail.append((
            "%s/%s main power" % (ykush_serial, ykush_port_board),
            ttbl.pc_ykush.ykush(ykush_serial, ykush_port_board) ))
    power_rail.append((
        "%s USB device present" % usb_serial_number,
        ttbl.pc.delay_til_usb_device(usb_serial_number) ))
    if ykush_port_serial:
        power_rail.append((
            "%s/%s TTY power" % (ykush_serial, ykush_port_serial),
            ttbl.pc_ykush.ykush(ykush_serial, ykush_port_serial) ))
    power_rail += [
        ( "%s TTY present" % serial_port,
          ttbl.pc.delay_til_file_appears(serial_port) ),
        ( "serial0", serial0_pc ),
    ]

    target.interface_add("power", ttbl.power.interface(*power_rail))

    target.interface_add("console",
                         ttbl.console.interface(serial0 = serial0_pc,
                                                default = "serial0"))

    target.interface_add("images",
                         ttbl.images.interface(**{
                             "kernel": ttbl.images.dfu_c(),
                             "kernel-x86": "kernel",
                             "kernel-arc": "kernel"
                         }))

    ttbl.config.target_add(
        target,
        tags = {
            'bsp_models': {
                #'x86+arc+arm': ['x86', 'arc', 'arm'],
                'x86+arc': ['x86', 'arc'],
                #'x86+arm': ['x86', 'arm'],
                #'arc+arm': ['arc', 'arm'],
                'x86': None,
                #'arm': None,
                'arc': None
            },
            'bsps' : {
                "x86":  dict(zephyr_board = "tinytile",
                             zephyr_kernelname = 'zephyr.bin',
                             dfu_interface_name = "x86_app",
                             console = ""),
                #"arm":  dict(zephyr_board = "arduino_101_ble",
                #             zephyr_kernelname = 'zephyr.bin',
                #             dfu_interface_name = "ble_core",
                #             console = ""),
                "arc": dict(zephyr_board = "arduino_101_sss",
                            zephyr_kernelname = 'zephyr.bin',
                            dfu_interface_name = 'sensor_core',
                            console = "")
            },
        },
        target_type = "tinytile"
    )
