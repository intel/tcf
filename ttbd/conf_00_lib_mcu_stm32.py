#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
.. _conf_00_lib_mcu_stm32:

Configuration data for STM32 MCUs used with the Zephyr OS and others
--------------------------------------------------------------------
"""

import ttbl.flasher

#
# Configurations settings for STM32
#
#

stm32_models = dict()

ttbl.openocd.addrmaps['unneeded'] = dict(
    # FIXME: we need this so the mappings in flasher.c don't get all
    # confused
    arm = dict()
)

ttbl.openocd.boards['disco_l475_iot1'] = dict(
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


ttbl.openocd.boards['nucleo_f103rb'] = dict(
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
#reset_config srst_only connect_assert_srst

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


ttbl.openocd.boards['nucleo_f207zg'] = dict(
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


ttbl.openocd.boards['nucleo_f429zi'] = dict(
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


ttbl.openocd.boards['nucleo_f746zg'] = dict(
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


ttbl.openocd.boards['nucleo_l073rz'] = dict(
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


ttbl.openocd.boards['stm32f3_disco'] = dict(
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

