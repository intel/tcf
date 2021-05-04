#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Helper to get data from a noyito capturer, see ttbl/noyito.py.channel_c
#
# It writes to the OUTPUTFILE a json formated file with a list of
# records
#
## [
##   RECORD1,
##   RECORD2,
##   ...
## ]
#
# Each record is a dictionary with fields described by the sensor
# reporting convention documented in ttbl/capture.py
#
## {
##     timestamp: TIMESTAMP,
##     sequence: SEQUENCE,
##     raw: {
##       "CHANNEL<0-9> (sample)": NNN,	# integer 0-2047
##       "CHANNEL<0-9> (Volts)": F.f,	# float 0-3.3V
##       "CHANNEL<0-9> (sample)": NNN,	# integer 0-2047
##       "CHANNEL<0-9> (Volts)": F.f,	# float 0-3.3V
##       ...
##     },
##     NAME<A>: VALUEB,
##     NAME<B>: VALUEB,
##     ...
## }
#
#
#
# Args:
#
##  UNIX-DOMAIN-SOCKET OUTPUTFILE \
##  CHANNEL1:mode=MODE1[:name=NAME1:ARG1=VAL1:ARG2=VAL2] \
##  CHANNEL2:mode=MODE2[:name=NAME2...]...
##  ...
#
#   name: NAME
#
#     Call this channel *NAME*. If no name is given, then the channel
#     number is used as a name.
#
#   mode: MODENAME
#
#     Process this channel according to mode:
#
#     - bool|boolean: print true/false when voltage is under/over cutoff
#
#     - onoff: print on/off when voltage is under/over cutoff
#
#     - cutoff: (float) voltage cutoff for bool|boolean|onoff
#
# If no mode is specified, the voltage is reported
#
import contextlib
import re
import socket
import sys

import ttbl.capture_cli

#
# Main
#
line_regex = re.compile(
    r"^CH(?P<channel>[0-9]+):(?P<sample>[0-9]+)\t(?P<voltage>[\.0-9]+)V$")
unix_domain_socket = sys.argv[1]
outputfilename = sys.argv[2]
modes = {}
mode_args = {}
channel_names = {}
cutoffs = {}

for i in sys.argv[3:]:
    args = []
    parts = i.split(":")
    channel = parts[0]
    if len(parts) > 1:
        mode = parts[1]
    if len(parts) > 2:
        args = parts[1:]
    argd = {}
    mode = 'voltage'	# default
    for arg in args:
        if '=' in arg:
            name, value = arg.split("=", 1)
        else:
            name = arg
            value = True
        if name == "name":
            channel_names[channel] = value
        elif name == "mode":
            mode = value
        elif name == "cutoff":
            cutoffs[channel] = float(value)
        else:
            argd[name] = value
    # we make sure there is always an entry per channel
    modes[channel] = mode
    mode_args[channel] = argd

def parse_chunk(chunk):
    # parse and report
    samples = {}
    voltages = {}
    # make it all a string, easier
    chunk = chunk.decode('ascii')
    for line in chunk.splitlines():
        ## CH<CH>:<NNNN><TAB><FLOAT>V\r\n
        match = line_regex.match(line.strip())
        if not match:
            # hmmm FIXME?
            continue
        gd = match.groupdict()
        channel = gd['channel']
        samples[channel] = gd['sample']
        voltages[channel] = gd['voltage']

    chunk_data = {}
    for channel, _mode in modes.items():
        #name, value, unit_suffix = transform(channel, voltages[channel],
        #                                     mode, mode_args[channel])
        #chunk_data[name + unit_suffix] = value
        chunk_data[channel + " (sample)"] = int(samples[channel])
        chunk_data[channel + " (Volt)"] = float(voltages[channel])
    return chunk_data


bytes_read = 0
data_read = b''

def sample(inf):
    # this returns like
    #
    ## CH0:<NNNN><TAB><FLOAT>V\r\n
    ## ...
    ## CH8:<NNNN><TAB><FLOAT>V\r\n
    ## CH9:<NNNN>	<FLOAT>V\r\n
    ## \r\n
    #
    # NNNN being 0000-4095, FLOAT (only four bytes) 0 to 3.3V
    #
    # So the max length of a record is
    #
    # 10 x (4 [CH<N>:] + 4 [<NNNN>] + 1 [ <TAB>] + 6 [ <N.NNN>V ] + 2)
    # 2
    #
    # 10 x 16 + 2 == 162 Bytes
    #
    # Everytime we see a whole chunk, we can parse it

    global data_read
    global bytes_read
    while True:

        while bytes_read > 172:
            index = data_read.find(b'\r\n\r\n')
            if index == -1:
	        # not found, read more? keep reading
                # FIXME: give up after too many
                print("INFO: didn't find \\r\\n\\r\\n, reading more")
                break
            print("INFO: found \\r\\n\\r\\n @%s" % index)

            # 168 is the lenght of the chunk without the final
            # \r\n\r\n...might be a weird partial match, so wipe
            if index < 168:
                print("INFO: not a full record before the \\r\\n\\r\\n"
                      " @%s, reading more" % index)
                data_read = data_read[index + 4:]
                bytes_read = len(data_read)
                break

            chunk_data = parse_chunk(data_read[index - 168:index])
            # make it lazy, just remove the current chunk, read again
            # (if anything new) and parse the next chunk next time we sample
            data_read = data_read[index + 4:]
            bytes_read = len(data_read)
            return chunk_data, {}

        # hmm, not enouth? keep reading
        data_read += inf.recv(172)
        bytes_read = len(data_read)
        print("INFO: read %sB" % bytes_read)



def xlat(d, data):
    for channel, mode in modes.items():
        voltage = data[channel + " (Volt)"]
        sample = data[channel + " (sample)"]

        name = channel_names.get(channel, "%s" % channel)
        if mode in ( 'boolean', 'bool' ):
            value = float(voltage)
            d[name] = value < cutoffs[channel]
        elif mode == 'onoff':
            value = float(voltage)
            d[name] = "on" if value < cutoffs[channel] else "off"
        else:
            d[name + " (Volts)"] = voltage
            d[name + " (sample)"] = sample
    return d

# Main loop, keep reading power until stopped
first = True
period_s = 0.5	# wait at least one sec between reads


with \
     contextlib.closing(socket.socket(socket.AF_UNIX,
                                      socket.SOCK_STREAM)) as inf:
    inf.connect(sys.argv[2])
    ttbl.capture_cli.main(sys.argv[1], sample, xlat, inf,
                          period_s = 0.5)
