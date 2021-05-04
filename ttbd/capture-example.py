#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Example script to capture data from somewhere and report it on JSON
# format using ttbl.capture_cli.
#
# Arguments: OUTPUTFILE NUMERICSEED:INT PERIOD:FLOAT

import random
import sys
import time

import capture_cli

def _f(rng):
    # note testcase test/test-capture-streams.py relies in this
    # message
    print(f"DEBUG: capture-example sampling {time.time()}",
          file = sys.stderr)
    # Sample
    errors = {}
    data = {}
    data['r1']  = rng.randint(0, 1000000)
    data['r2']  = rng.randint(0, 1000000)
    data['r3']  = rng.randint(0, 1000000)
    return data, errors

def _xlat(d, data):
    d['r1'] = data['r1']/1000000
    d['r2'] = data['r2']/1000000
    d['r3'] = data['r3']/1000000


capture_cli.main(
    sys.argv[1], _f, _xlat,
    # define a random number generator we'll pass to _f via
    # ttbl.capture_cli.main
    random.Random(int(sys.argv[2])),
    period_s = float(sys.argv[3]))
