#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME: legacy functions to add UCs were removed due to code rot,
#         available in git history
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
# FIXME: bitrot -- import ttbl.openocd
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
