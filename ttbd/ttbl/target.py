#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import time

import pexpect
try:
    import pexpect.spawnbase
    expect_base = pexpect.spawnbase.SpawnBase
except:
    import pexpect.fdpexpect
    expect_base = pexpect.spawn

"""
Support for interacting with the target from the target broker
==============================================================

"""

def expect_send_sequence(logger, e, _list):
    """Execute a list of expect/send commands

    :param logging.Logger logger: a logging object to report progress
      to.
    :param pexpect.spawn e: Expect-like object on which to execute the
      commands; for example, a expect object connected to a serial
      line to control a remote device::

        s = serial.Serial("/dev/ttyS0", baudrate = 115200)
        e = fdpexpect.fdspawn(s, logfile = open("file.log", "w+"),
                              timeout = 20)

    :param _list: List of tuples ``(EXPECT[, SEND[, WAIT[,
      DELAY]]])``:

      - EXPECT: string that is expected to be received
      - SEND: string to send (or None if nothing shall be sent.)

      The tuple can just be a string for an EXPECT
    """
    assert isinstance(e, expect_base)
    count = 0
    for s in _list:
        if isinstance(s, str):
            expect = s
        else:
            expect = s[0]
        logger.info("expect/send phase %d: Waiting for '%s'" % (count, expect))
        r = e.expect_exact([expect, pexpect.EOF, pexpect.TIMEOUT],
                           # This is only needed for the linux boot
                           timeout = 50)
        if r == 0:
            pass
        elif r == 1:
            raise Exception("expect/send phase %d: EOF waiting for '%s'"
                            % (count, expect))
        elif r == 2:
            raise Exception("expect/send phase %d: Timeout waiting for '%s'"
                            % (count, expect))
        if not isinstance(s, str) and len(s) > 1:
            send = s[1]
            if len(s) > 2:	# there is a wait period
                time.sleep(float(s[2]))
            if len(s) > 3:
                delay = float(s[3])
                # Slow down the send by waiting in between
                # each char for readers who have small buffers.
                for c in send:
                    e.send(c)
                    time.sleep(delay)
            else:
                e.send(send)
        count = count + 1

