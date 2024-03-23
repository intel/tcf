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
#   ARGs:
#
#     - cutoff: (float) voltage cutoff for bool|boolean|onoff
#
# If no mode is specified, the voltage is reported; if no name is
# specifed, that channel is omitted:
#
#  $ noyito-capture.py /dev/ttyUSB0 kk.json 0:mode=bool:name=CH0:cutoff=2.3
#  $ noyito-capture.py /dev/ttyUSB0 kk.json 1:name=CH1 0:mode=bool:name=CH0:cutoff=2.3
#
# note the device can be specified in URL for, where more modes are
# supported; see code doc
#
# rpyc+usb://REMOTEHOST:PORT/VID:PID=1234:4532
# tcp://REMOTEHOST:PORT
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
        if hasattr(inf, "recv"):
            data_read += inf.recv(172)
        else:
            data_read += inf.read()
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

import fcntl
import stat
import os

import urllib.parse


# EG: url = urllib.parse.urlparse("usb:///VID:PID=1A86:7523")
# (note three slashes)
url = urllib.parse.urlparse(sys.argv[1])
if "+" in url.scheme:		# eg: rpyc+usb://
    schemes = url.scheme.split("+")
else:
    schemes = [ url.scheme ]

if "rpyc" in schemes:
    #
    # rpyc+usb://hostname:PORT/VID:PID=1A86:7523
    # rpyc://hostname:PORT/dev/ttyUSB0
    #
    # establish a normal RPYC connection to a host/port
    import rpyc.utils
    remote = rpyc.utils.classic.connect(url.hostname, port = url.port)
    serial = remote.modules['serial']
    serial.tools = remote.modules['serial.tools']
    serial.tools.list_ports = remote.modules['serial.tools.list_ports']

else:
    remote = None
    import serial
    import serial.tools
    import serial.tools.list_ports

if 'usb' in schemes:
    # Do this after rpyc, since we might have to access remotely
    #
    # rpyc+usb://hostname:PORT/VID:PID=1A86:7523
    # usb:///VID:PID=1A86:7523
    # usb:///SERIAL=SOMESERIALNUMBER
    #
    # (all fields from usb_info in serial.tools.list_ports.comports())
    #
    # eg VID:PID=1A86:7523 -> 1: remove leading /
    device_spec = url.path[1:]
    devicel = list(serial.tools.list_ports.grep(device_spec))
    if len(devicel) != 1:
        raise RuntimeError(
            f"{device_spec}: spec matches {len(devicel)} devices; expected 1")
    device = devicel[0].device

else:	# anything else we assume is a local device path
    device = sys.argv[1]

if remote == None:
    try:
        s = os.stat(device)
    except FileNotFoundError as e:
        pass	# might be a remote file, it's ok

if url.scheme == "tcp":
    # We are reading data from a TCP port
    #
    # To redirect a windows serial port to TCP you can use hub4com
    #
    # 1. download https://sourceforge.net/projects/com0com/ (GPLv2)
    #   https://downloads.sourceforge.net/project/com0com/com0com/3.0.0.0/com0com-3.0.0.0-i386-and-x64-signed.zip?ts=gAAAAABl_iHtN4q_KvwLkIp6jj6sPoF2ZiZjYWpgK897AgAXaDebt2sG_u8dVbaZE7A4ajurL4rAZ2GCOTDQVujSKR_4HzmbBg%3D%3D&r=https%3A%2F%2Fsourceforge.net%2Fprojects%2Fcom0com%2Ffiles%2Flatest%2Fdownload
    #
    # 2. unzip to C:\Program Files
    #
    # 3. Run, eg::
    #
    #    C:\> 'c:\Program Files\hub4com-2.1.0.0-386\hub4com.exe --baud=115200 --create-filter=pin2con --add-filters=0:pin2con COM4 --use-driver=tcp --reconnect=1000 5000'
    #
    # 4. now that is serving our serial port on port #5000
    with contextlib.closing(socket.socket(socket.AF_INET,
                                          socket.SOCK_STREAM)) as inf:
        inf.connect(( url.hostname, url.port ))
        ttbl.capture_cli.main(outputfilename, sample, xlat, inf,
                              period_s = 0.5)
elif remote == None and stat.S_ISSOCK(s[stat.ST_MODE]):
    # it's a Unix doman socket -> using with multiplexor
    with contextlib.closing(socket.socket(socket.AF_UNIX,
                                          socket.SOCK_STREAM)) as inf:
        inf.connect(device)
        ttbl.capture_cli.main(outputfilename, sample, xlat, inf,
                              period_s = 0.5)
else:
    # it's a normal device, maybe in a remote machine
    with serial.Serial(device, 115200) as inf:
        flag = fcntl.fcntl(inf.fileno(), fcntl.F_GETFD)
        fcntl.fcntl(inf, fcntl.F_SETFD, flag | os.O_NONBLOCK)
        flag = fcntl.fcntl(inf, fcntl.F_GETFD)
        ttbl.capture_cli.main(outputfilename, sample, xlat, inf,
                              period_s = 0.5)
