#! /usr/bin/python2
#
# Just rebind a driver to a device
#
# args: BUS-NAME DRIVER-NAME DEVICE-NAME
#
# as in /sys/bus/BUS-NAME/drivers/DRIVER-NAME/DEVICE-NAME
#
# pylint: disable = missing-docstring, undefined-variable

import os
import sys

def _verify_name(name):
    assert not os.path.pardir in name
    assert not os.path.sep in name

bus_name = sys.argv[1]
_verify_name(bus_name)
driver_name = sys.argv[2]
_verify_name(driver_name)
device_name = sys.argv[3]
_verify_name(device_name)

with open("/sys/bus/%s/drivers/%s/unbind" % (bus_name, driver_name), "w") as f:
    f.write(device_name)
with open("/sys/bus/%s/drivers/%s/bind" % (bus_name, driver_name), "w") as f:
    f.write(device_name)
