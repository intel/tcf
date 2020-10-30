#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import contextlib
import os
import ttbl

# FIXME: move to console/serial or something more consistent
class cm_loopback(ttbl.test_target_console_mixin):
    """Implement console/s over serial ports or network connections using
    the Python serial module

    The consoles maybe be open right after power on (if the target
    supports the power-on interface) and closed right before power off
    -- this is needed for device nodes that are powered off AT the
    same time as the target.
    This also means that you can loose console output from the time
    the target is powered on until the serial port is attached to the
    system.
    """

    def consoles_close(self):
        # Tell the logger process to stop logging
        for f in list(self.__consoles.values()):
            f.close()
            self.__consoles[f] = None
            del f

    def consoles_open(self):
        for name in list(self.__consoles.keys()):
            f = open(os.path.join(self.state_dir, "console-%s.log" % name),
                     "w+")
            self.__consoles[name] = f

    def consoles_reset(self):
        for f in list(self.__consoles.values()):
            f.truncate()

    def __init__(self, state_dir, names = None):
        """

        :param dict names: string or list of strings with the names of
          the consoles to open.

        """
        if names == None:
            names = [ 'default' ]
        elif isinstance(names, str):
            names = [ names ]
        elif isinstance(names, list):
            assert all([isinstance(l, str) for l in names])
        else:
            raise AssertionError("Bad type, need [STRING|LIST(STRINGS)]")

        #: List of consoles to be opened
        self.__consoles = { name : None for name in names }
        ttbl.test_target_console_mixin.__init__(self)
        self.state_dir = state_dir
        self.console_default = 'default'
        self.consoles_open()

    def __del__(self):
        self.consoles_close()

    # Console mixin
    def console_do_list(self):
        return list(self.__consoles.keys())

    def console_do_read(self, console_id = None, offset = 0):
        if console_id == None:
            console_id = self.console_default
        f = self.__consoles[console_id]
        if not f or f.closed:
            return iter(())

        ifd = open(f.name, "rb")
        if offset > 0:
            ifd.seek(offset)
        return ifd

    def console_do_write(self, data, console_id = None):
        if console_id == None:
            console_id = self.console_default
        f = self.__consoles[console_id]
        f.write(data)

    @contextlib.contextmanager
    def console_takeover(self, console_id = None):
        # Not too useful here
        if console_id == None:
            console_id = self.console_default
        f = self.__consoles[console_id]
        yield self.__consoles[console_id], f.name
