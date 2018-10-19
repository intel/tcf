#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import curses.ascii
import tc

class console(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run methods from the console
    management interface to TTBD targets.

    Use as:

    >>> target.console.read()
    >>> target.console.write()
    >>> target.console.setup()
    >>> target.console.list()

    """

    def __init__(self, target):
        if not 'test_target_console_mixin' in target.rt.get('interfaces', []):
            raise self.unneeded

    def read(self, console_id = None, offset = 0, fd = None):
        """
        Read data received on the target's console

        :param str console_id: (optional) console to read from
        :param int offset: (optional) offset to read from (defaults to zero)
        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).
        :returns: data read (or if written to a file descriptor,
          amount of bytes read)
        """
        if console_id == None or console_id == "":
            console_id_name = "<default>"
        else:
            console_id_name = console_id
        self.target.report_info(
            "reading console '%s:%s' @%d" % (self.target.fullid,
                                             console_id_name, offset),
            dlevel = 1)
        if fd:
            r = self.target.rtb.rest_tb_target_console_read_to_fd(
                fd,
                self.target.rt, console_id, offset,
                ticket = self.target.ticket)
            ret = r
            l = r
        else:
            r = self.target.rtb.rest_tb_target_console_read(
                self.target.rt, console_id, offset,
                ticket = self.target.ticket)
            ret = r.text
            l = len(ret)
        self.target.report_info("read console '%s:%s' @%d %dB"
                                % (self.target.fullid, console_id_name,
                                   offset, l))
        return ret

    def size(self, console_id = None):
        """
        Return the amount of bytes so far read from the console

        :param str console_id: (optional) console to read from
        """
        return int(self.target.rtb.rest_tb_target_console_size(
            self.target.rt, console_id, ticket = self.target.ticket))

    def write(self, data, console_id = None):
        """
        Write data received to a console

        :param data: data to write
        :param str console_id: (optional) console to read from
        """
        if console_id == None or console_id == "":
            console_id_name = "<default>"
        else:
            console_id_name = console_id
        if len(data) > 30:
            data_report = data[:30] + "..."
        else:
            data_report = data
        data_report = filter(curses.ascii.isprint, data_report)
        self.target.report_info("writing to console '%s:%s'"
                                % (self.target.fullid, console_id_name),
                                dlevel = 1)
        self.target.rtb.rest_tb_target_console_write(
            self.target.rt, console_id, data, ticket = self.target.ticket)
        self.target.report_info("wrote '%s' to console '%s:%s'"
                                % (data_report, self.target.fullid,
                                   console_id_name))

    def setup(self, console_id = None, **kwargs):
        raise NotImplementedError

    def list(self):
        return self.target.rt.get('consoles', [])
