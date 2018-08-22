#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import tc
import commonl.tcob

#
# FIXME: this is a hack to patch the TCOB information into targets
#        that still don't have it; will be removed and moved to the
#         server.

_connections = {}
_pin_map = {}

COMMON_TCOB_CONNECTIONS = dict(
    # switch 0
    DUT_SCL = "0 0",
    DUT_SDA = "0 1",
    SPI_0_MOSI = "0 2",
    SPI_0_MISO = "0 3",
    SPI_0_SCK = "0 4",
    SPI_0_CS = "0 5",
    DUT_IO10 = "0 5",
    DUT_GPIO_A = "0 6",
    DUT_GPIO_B = "0 7",
    ARDUINO_IO8 = "0 8",
    ARDUINO_IO9 = "0 9",
    ARDUINO_IO10 = "0 10",
    PWM_0 = "0 11",
    # switch 1
    DUT_GPIO_C = "1 0",
    DUT_GPIO_D = "1 1",
    V3_3 = "1 2",
    FRAM_SCL = "1 3",
    FRAM_SDA = "1 4",
    ARDUINO_SCL = "1 6",
    ARDUINO_SDA = "1 7",
    ARDUINO_SPI_MOSI = "1 8",
    ARDUINO_SPI_MISO = "1 9",
    ARDUINO_SPI_SCK = "1 10",
    GROUND = "1 11",
)


_pin_map['arduino_101'] = dict(
    GPIO_SS_2 = "DUT_GPIO_A",
    GPIO_18 = "DUT_IO2",
    GPIO_16 = "DUT_GPIO_C",
    GPIO_17 = "DUT_GPIO_D",
    GPIO_15 = "DUT_GPIO_B",
    AIN_10 = "DUT_GPIO_A",
    SPI_1_MOSI = "SPI_0_MOSI",
    SPI_1_MISO = "SPI_0_MISO",
    SPI_1_SCK = "SPI_0_SCK",
    SPI_1_CS = "SPI_0_CS",
    DUT_IO10 = "SPI_0_CS",
    DUT_IO11 = "SPI_0_MOSI",
    DUT_IO12 = "SPI_0_MISO",
    ARDUINO_DAC0 = "DUT_GPIO_A",
    ARDUINO_IO22 = "ARDUINO_IO10"
)

_connections['arduino_101'] = dict(
    # Switch 2
    DUT_A1 = "2 0",
    DUT_A2 = "2 1",
    DUT_A3 = "2 2",
    DUT_IO2 = "2 4",
    DUT_IO4 = "2 5",
    GY68_SCL = "2 6",
    GY68_SDA = "2 7",
    DUT_IO5 = "2 9",
    DUT_IO6 = "2 10",
    DUT_IO9 = "2 11",

    # Switch 3
    GY30_SCL = "3 0",
    GY30_SDA = "3 1",
    GY2561_SCL = "3 4",
    GY2561_SDA = "3 5",
    GY271_SCL = "3 6",
    GY271_SDA = "3 7",
)
# Switch 0/1
_connections['arduino_101'].update(COMMON_TCOB_CONNECTIONS)


_pin_map['quark_se_c1000_devboard'] = dict(
    GPIO_SS_2 = "DUT_GPIO_A",
    GPIO_15 = "DUT_GPIO_B",
    GPIO_16 = "DUT_GPIO_D",
    GPIO_AON_0 = "DUT_GPIO_C",
    AIN_10 = "DUT_GPIO_A"
)
_pin_map['quark_se_c1000_ss_devboard'] = _pin_map['quark_se_c1000_devboard']

_connections['quark_se_c1000_devboard'] = dict(
    # Switch 2
    DUT_A1 = "2 0",
    DUT_A2 = "2 1",
    DUT_A3 = "2 2",
    DUT_IO2 = "2 4",
    DUT_IO4 = "2 5",
    GY68_SCL = "2 6",
    GY68_SDA = "2 7",
    PWM_1 = "2 9",
    PWM_2 = "2 10",
    PWM_3 = "2 11",

    # Switch 3
    GY30_SCL = "3 0",
    GY30_SDA = "3 1",
    GY2561_SCL = "3 4",
    GY2561_SDA = "3 5",
    GY271_SCL = "3 6",
    GY271_SDA = "3 7",
    SPI_1_SCK = "3 8",
    SPI_1_MISO = "3 9",
    SPI_1_MOSI = "3 10",
    SPI_1_CS = "3 11",

    # Switch 4
    ARC_SPI_SCK = "4 0",
    ARC_SPI_MISO = "4 1",
    ARC_SPI_MOSI = "4 2",
    ARC_SPI_CS = "4 3",
    ARC_SPI_1_SCK = "4 4",
    ARC_SPI_1_MISO = "4 5",
    ARC_SPI_1_MOSI = "4 6",
    ARC_SPI_1_CS = "4 7",
    I2C_1_SCL = "4 8",
    I2C_1_SDA = "4 9",
    ARC_I2C_SCL = "4 10",
    ARC_I2C_SDA = "4 11",

    # Switch 5
    ARC_I2C_1_SCL = "5 0",
    ARC_I2C_1_SDA = "5 1",
)
# Switch 0/1
_connections['quark_se_c1000_devboard'].update(COMMON_TCOB_CONNECTIONS)
_connections['quark_se_c1000_ss_devboard'] = \
    _connections['quark_se_c1000_devboard']


_pin_map['quark_d2000_crb'] = dict(
    GPIO_8 = "DUT_GPIO_B"
)

_connections['quark_d2000_crb'] = dict(
    # Switch 2
    DUT_A1 = "2 0",
    DUT_A2 = "2 1",
    DUT_A3 = "2 2",
    DUT_IO2 = "2 4",
    DUT_IO4 = "2 5",
    GY68_SCL = "2 6",
    GY68_SDA = "2 7",
    PWM_1 = "2 9",
    DUT_IO6 = "2 10",
    DUT_IO9 = "2 11",

    # Switch 3
    GY30_SCL = "3 0",
    GY30_SDA = "3 1",
    GY2561_SCL = "3 4",
    GY2561_SDA = "3 5",
    GY271_SCL = "3 6",
    GY271_SDA = "3 7",
)
# Switch 0/1
_connections['quark_d2000_crb'].update(COMMON_TCOB_CONNECTIONS)

_boards = set(_connections.keys())
assert _boards == set(_pin_map.keys()), \
    "Must declare connections and pin maps for the same amount of boards"

class tcob(tc.target_extension_c):

    """
    TCOB interface extension to :py:class:`tcfl.tc.target_c` using
    :mod:`commonl.tcob`.

    To use, access as, eg:

    >>> target.tcob.port("PORTNAME')

    """
    def port(self, name):
        # It's ok to fail miserably if there is no entry
        name = self.target.rt['tcob_pin_map'].get(name, name)
        return self.target.rt['tcob_connections'][name]

    def __init__(self, target):
        if not 'tcob_connections' in target.rt:
            # if this target no TCOB information, no need to add a
            # TCOB interface.
            raise self.unneeded
        self.target = target
        commonl.tcob.validate_connections(target.rt['tcob_connections'])
        commonl.tcob.validate_pin_map(target.rt['tcob_pin_map'])
        # FIXME: this is not printing with the right prefix, eff.
        target.report_info("TCOB extension available")
