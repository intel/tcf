#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Helper that gets non stop the power consumption numbers from a
# Raritan AC outlet until C-c is pressed.
#
# Args: http[s]://USERNAME@HOSTNAME PASSWORD|environment OUTLET OUTPUTFILE
#
# (if password is 'environment', the password is taken from the ENV
# variable RARITAN_PASSWORD)
#
# It writes to the OUTPUTFILE a json formated file with a list of records
#
## [
##   RECORD1,
##   RECORD2,
##   ...
## ]
#
# Each record is a dictionary with fields described by the power
# reporting convention documented in ttbl/capture.py
#
import datetime
import json
import os
import signal
import sys
import time
import urllib

# This is where my Raritan package is
sys.path.append("/usr/local/lib/python2.7/site-packages")

import raritan
import raritan.rpc
import raritan.rpc.sensors
import raritan.rpc.pdumodel

import ttbl.capture_cli

# Map unit codes to unit names
#
# There is no good way to do it because the unit codes reported below
# are also overriden in what the class defines, but I can't find a
# place where they are just listed as units, so we'll just exclude the
# ones we know for sure are not units.
# Fugly.
unit_id_to_name = {}
for unit_name, unit in raritan.rpc.sensors.Sensor.__dict__.items():
    if not isinstance(unit, int) \
       or unit_name in [
           "DISCRETE_MULTI",
           "POWER_FACTOR",
           "TEMPERATURE",
           "UNBALANCE_CURRENT",
       ]:
        continue
    unit_id_to_name[unit] = unit_name



def raritan_sensor_get(agent, outlet_numbers):

    # create a bulk request object; this way we can request all the
    # data for all the outlets at in a single go; much faster
    bulk = raritan.rpc.BulkRequestHelper(agent, raise_subreq_failure = False)
    # track here the things we put in the bulk request, so we can map
    # the results; for each entry on this we'll expect two entries in
    # the return value
    elements = []

    # Now for each outlet we need data on, create a "sensor_reading"
    # proxy object and for each sensor in the sensor reading, attach a
    # request to the *bulk list plus another to the *elements list, so
    # we can track those results
    for outlet_number in outlet_numbers:
        sensor_reading = outlets[outlet_number].getSensors()
        for element_name in sensor_reading.elements:
            element = getattr(sensor_reading, element_name)
            if not element:
                continue
            if not isinstance(element, raritan.rpc.sensors.NumericSensor):
                continue
            bulk.add_request(element.getReading)
            bulk.add_request(element.getTypeSpec)
            elements.append(( outlet_number, element, element_name ))

    r = bulk.perform_bulk()

    # now unpack the results into a JSON dictionary
    count = 0
    data = {}
    errors = {}
    for outlet_number, element, element_name in elements:
        error_data = errors.setdefault(outlet_number, {})
        outlet_data = data.setdefault(outlet_number, {})
        reading_value = r[count]
        reading_unit = r[count + 1]
        count += 2

        if isinstance(reading_value, Exception):
            # error getting the value, nothing else we can do
            error_data[element_name] = reading_value
            continue

        if isinstance(reading_unit, Exception):
            # error getting Unit name; recoverable, but we don't have
            # the unit ... welp
            unit_name = "ERROR"
            error_data[element_name] = reading_unit
            # fallthrough

        unit_name = unit_id_to_name[reading_unit.unit]
        outlet_data[element_name + " (" + unit_name + ")"] = reading_value.value

    # Note this function was designed to pick multiple outlets, but
    # here we use it only for one, so we return outlet_data
    return outlet_data, errors


def xlat(d, data):
    # these are known fields -- we convert them from whatever raritan provides to our "convention"
    power = data.get("activePower (WATT)", None)
    if power != None:
        d['power (watt)'] = power
    voltage = data.get('voltage (VOLT)', None)
    if voltage != None:
        d['voltage (volt)'] = voltage


#
# Main
#
url = urllib.parse.urlparse(sys.argv[1])
password = sys.argv[2]

if password == "environment":
    password = os.environ['RARITAN_PASSWORD']

# note the indexes for the SW are 0-based, while in the labels
# in the HW for humans, they are 1 based.
outlet_number = int(sys.argv[3]) - 1

# Fire up an agent and get a PDU model for the PDU data
agent = raritan.rpc.Agent(url.scheme, url.hostname, url.username, password,
                          disable_certificate_verification = True)
pdu = raritan.rpc.pdumodel.Pdu("/model/pdu/0", agent)

# list them outlets; if we got a list of outlets to read from,
# validate they are good; otherwise we'll list them all
outlets = pdu.getOutlets()
assert outlet_number < len(outlets), \
    f"outlet {outlet_number} not valid (max len{(outlets)})"

ttbl.capture_cli.main(sys.argv[4], raritan_sensor_get, xlat,
                      agent, [ outlet_number ],
                      period_s = 0.5)
