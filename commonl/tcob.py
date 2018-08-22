#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Common routines to server and client side TCOB support
#
"""TCOB Fixture setup instructions
===============================

The TCOB board is a rectangular board, considered to be:

- facing up (DIP switches 1, 2 3, and 4 facing the viewer)   -

- top left is the side where the power barrel connector J4 is
                                        -
- bottom is the side where jumpers J1, J2, J3, J6 and J7, J8, J9 are

::

   +---------------------------------------------------------------+
   |+----+       +--J11----------------+  +---J10---------------+  |
   || J4 |       | X11 X10 X9... X1 X0 |  | X11 X10 X9... X1 X0 |  |
   |+----+       +---------------------+  +---------------------+  |
   |            +------------------+ +-----------------+           |
   |  +----+    |     DIP3         | |    DIP2         |           |
   |  | J5 |    +------------------+ +-----------------+  +---+    |
   |  +----+                                              | D |    |
   |                                                      | I |    |
   |                                                      | P |    |
   |                                                      | 4 |    |
   |                                        +---------+   +---+    |
   |                                        |  DIP1   |            |
   |                                        +---------+            |
   |  +----+----+----+         +----+            +----+----+----+  |
   |  | J2 | J3 | J6 |         | J1 |            | J7 | J8 | J9 |  |
   |  +----+----+----+         +----+  +-----+   +----+----+----+  |
   +-----------------------------------| J13 |---------------------+
                                       +-----+

**Sensing pins banks**

These are the pins that are connected to the Arduino header for
testing

- J11 is a bank of 12 pins on the top left of the board, named X0
  through X11 (from right to left)

  J11's I2C 3-bit address is controlled by J2/J3/J6. Shorting the two
  left pins of the jumper means 1, shorting the two right pins means
  0. The address is computed as:

    J2 << 2 | J3 << 1| J6

- J10 is a bank of 12 pins on the top left of the board, named X0
  through X11 (from right to left)

  J11's I2C address is controlled by J7/J8/J9; same SPI address
  assignment strategy as for J11.

To address the sensing pins XN we use the tuple *(addr, N)*, where
addr is the address of the J11 or J10 block where the pin is
physically located. Thus, if J11 has assigned address 3, J11's X5
would be *(3, 5)*.

**DIP configuration to allow control of the TCOB via the I2C protocol**

- DIP3: turn on 1, 2 and 4 (I2C SCL, SDA and GND)
- DIP2: turn on 6 (reset)

- DIP3: FIXME? turn on 3, 9, 10 on first TCOB layer

- DIP4: turn on 2, 3, 4 and 5 to use the Arduino Due SPI port for pins
  MISO/MOSI/SCK/CS (FIXME: not clear).

**Power configuration**

- default power supply: short J5 two bottom pins (we use this by default)
- external (barrel) 12 VDC power supply: open all of J5 pins
- J1: reference voltage

  - short J1 if if the Arduino (FIXME: Dut? controller?) logic voltage
    level is 3.3V

  - connect to 5V for reference voltage otherwise

**Stacking**

TCOBs are designed to be stacked, the top level J1, J5 and J21 being
passed through. The top level board shall be the one used to short J1
and J5 if such is the configuration.

**Connection map**

We will give the TCOB controller a connection and a pin map, in which
we describe to which pins the different Arduino pins are connected,
for example:

.. code-block:: python

   _common_connections = dict(
     # switch 0
     DUT_SCL = "0 0",
     DUT_SDA = "0 1",
     SPI_0_MOSI = "0 2",
   )

pin map: FIXME, what is it for?

Indicates that pin X0 of the bank which I2C address 0 is to be
connected to the Arduino headers *SCL* line. By definition, it means
there has to be a sensing pink bank with address 0

For most configurations described below, we stack two TCOBs:

  - top TCOB: J11 is #1 (001), J10 is #0 (000)
  - bottom TCOB: J11 is #3 (011), J10 is #2 (010)

"""

import numbers

valid_keys = [
    "AIN_10",
    "ARC_I2C_1_SCL",
    "ARC_I2C_1_SDA",
    "ARC_x2C_SCL",
    "ARC_I2C_SDA",
    "ARC_SPI_1_CS",
    "ARC_SPI_1_MISO",
    "ARC_SPI_1_MOSI",
    "ARC_SPI_1_SCK",
    "ARC_SPI_CS",
    "ARC_SPI_MISO",
    "ARC_SPI_MOSI",
    "ARC_SPI_SCK",
    "ARDUINO_DAC0",
    "ARDUINO_IO10",
    "ARDUINO_IO22",
    "ARDUINO_IO8",
    "ARDUINO_IO9",
    "ARDUINO_SCL",
    "ARDUINO_SDA",
    "ARDUINO_SPI_MISO",
    "ARDUINO_SPI_MOSI",
    "ARDUINO_SPI_SCK",
    "DUT_A1",
    "DUT_A2",
    "DUT_A3",
    "DUT_GPIO_A",
    "DUT_GPIO_B",
    "DUT_GPIO_C",
    "DUT_GPIO_D",
    "DUT_IO10",
    "DUT_IO11",
    "DUT_IO12",
    "DUT_IO2",
    "DUT_IO4",
    "DUT_IO5",
    "DUT_IO6",
    "DUT_IO9",
    "DUT_SCL",
    "DUT_SDA",
    "FRAM_SCL",
    "FRAM_SDA",
    "GPIO_15",
    "GPIO_16",
    "GPIO_17",
    "GPIO_18",
    "GPIO_8",
    "GPIO_AON_0",
    "GPIO_SS_2",
    "GROUND",
    "GY2561_SCL",
    "GY2561_SDA",
    "GY271_SCL",
    "GY271_SDA",
    "GY30_SCL",
    "GY30_SDA",
    "GY68_SCL",
    "GY68_SDA",
    "I2C_1_SCL",
    "I2C_1_SDA",
    "PWM_0",
    "PWM_1",
    "PWM_2",
    "PWM_3",
    "SPI_0_CS",
    "SPI_0_MISO",
    "SPI_0_MOSI",
    "SPI_0_SCK",
    "SPI_1_CS",
    "SPI_1_MISO",
    "SPI_1_MOSI",
    "SPI_1_SCK",
    "V3_3",
]

def validate_pin_map(pin_map):
    if pin_map == None:
        return

    if not isinstance(pin_map, dict):
        raise ValueError("Bad pin_map data: shall be a dictionary")

    errors = ""
    for key, val in pin_map.iteritems():
        if not isinstance(key, basestring):
            errors += "%s: invalid key type (must be string) " % key
            continue

        if key not in valid_keys:
            errors += "%s: invalid key (not in allowed set " \
                      "commonl.tcob.valid_keys) " % key
            continue

        if not isinstance(val, basestring):
            errors += " %s: invalid value type for key (must be string) " % key
            continue

    if errors != "":
        raise ValueError("Bad pin_map data: " + errors)

def validate_connections(connections):
    if connections == None:
        return

    if not isinstance(connections, dict):
        raise ValueError("Bad connections data: shall be a dictionary")

    errors = ""
    for key, val in connections.iteritems():
        if not isinstance(key, basestring):
            errors += "%s: invalid key type (must be string) " % key
            continue

        if key not in valid_keys:
            errors += "%s: invalid key (not in allowed set " \
                      "commonl.tcob.valid_keys) " % key
            continue

        if isinstance(val, basestring):
            _value1, _value2 = val.split(None, 2)
            try:
                value1 = int(_value1)
                value2 = int(_value2)
            except ValueError:
                errors += \
                    " %s: invalid value for key (must be tuple " \
                    "of two integers or [legacy] string of two integers) " \
                    % key
                continue
        elif isinstance(val, tuple):
            if len(val) != 2:
                errors += " %s: invalid value for key (must be tuple " \
                          "of two integers) " % key
                continue
            value1 = val[0]
            if not isinstance(value1, numbers.Integral):
                errors += " %s: invalid value1 type for key (must be tuple " \
                          "of two integers) " \
                          % key
                continue
            value2 = val[1]
            if not isinstance(value2, numbers.Integral):
                errors += " %s: invalid value2 type for key (must be tuple " \
                          "of two integers) " \
                          % key
                continue
        else:
            errors += " %s: invalid value type for key (must be tuple " \
                      "of two integers or [legacy] string of two integers) " \
                      % key
            continue

    if errors != "":
        raise ValueError("Bad connections data: " + errors)

# Common fixtures
# FIXME: move those addresses to (INT, INT)
_common_connections = dict(
    # switch 0
    DUT_SCL = "0 0",    # Arduino SCL
    DUT_SDA = "0 1",    # Arduino SDA
    SPI_0_MOSI = "0 2", # Arduino Digital 11, aka MOSI
    SPI_0_MISO = "0 3", # Arduino Digital 12, aka MISO
    SPI_0_SCK = "0 4",  # Arduino Digital 13, aka SCK
    SPI_0_CS = "0 5",   # FIXME: where is this plugged to?
    DUT_IO10 = "0 5",   # FIXME: where is this plugged to?
    DUT_GPIO_A = "0 6", # FIXME: where is this plugged to?
    DUT_GPIO_B = "0 7", # FIXME: where is this plugged to?
    ARDUINO_IO8 = "0 8",    # Arduino Digital 08,
    ARDUINO_IO9 = "0 9",    # Arduino Digital 09,
    ARDUINO_IO10 = "0 10",  # Arduino Digital 10, aka SS0
    PWM_0 = "0 11",         # Arduino Digital 06, aka PWM0
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

pin_map_arduino_101 = dict(
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

connections_arduino_101 = dict(
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
connections_arduino_101.update(_common_connections)


pin_map_quark_se_c1000_devboard = dict(
    GPIO_SS_2 = "DUT_GPIO_A",
    GPIO_15 = "DUT_GPIO_B",
    GPIO_16 = "DUT_GPIO_D",
    GPIO_AON_0 = "DUT_GPIO_C",
    AIN_10 = "DUT_GPIO_A"
)

connections_quark_se_c1000_devboard = dict(
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
connections_quark_se_c1000_devboard.update(_common_connections)


pin_map_quark_d2000_crb = dict(
    GPIO_8 = "DUT_GPIO_B"
)

connections_quark_d2000_crb = dict(
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
connections_quark_d2000_crb.update(_common_connections)
