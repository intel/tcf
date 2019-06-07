#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import errno
import logging
import multiprocessing
import os
import select
import time
import traceback

import serial

_spec_queue = None

def _spec_open_one(spec):
    if isinstance(spec, str):
        descr = serial.serial_for_url(spec)
        descr.nonblocking()
        return descr
    elif isinstance(spec, dict):
        # We have to remove the port thing for passing to the
        # function, but we want to keep the original spec intact
        _spec = dict(spec)
        url = _spec.pop('port')
        descr = serial.serial_for_url(url, **_spec)
        descr.nonblocking()
        return descr
    else:
        raise RuntimeError("Don't know how to open: %s" % spec)

def _spec_open(spec):
    t0 = time.time()
    timeout = 10
    while True:
        try:
            t = time.time()
            descr = _spec_open_one(spec)
            logging.debug("open waited %.2fs for '%s' to appear",
                          t - t0, spec)
            return descr
        except (serial.SerialException, OSError) as e:
            if t - t0 >= timeout:
                logging.error("timeout (%.1fs) trying to open %s: %s",
                              timeout, spec, e)
                raise
            if e.errno == errno.ENOENT or e.errno == errno.EBUSY:
                logging.debug("open waiting for '%s' to appear: %s",
                              spec, e)
                time.sleep(0.25)
                continue
            logging.error("cannot open '%s': %s", spec, e)
            return None
        except Exception as e:
            logging.error("cannot open '%s': %s", spec, e)
            raise

reader_dict = dict()
poller = None

def _reopen(spec, logfile_name):
    global reader_dict
    global poller
    logfile = open(logfile_name, "wb")	# Open truncating
    descr = _spec_open(spec)
    if descr == None:
        return -1
    logging.debug("fd %d[%s/%d]: (re)opened: %s",
                  descr.fileno(), logfile_name, logfile.fileno(), spec)
    reader_dict[descr.fileno()] = (spec, logfile, descr)
    poller.register(descr.fileno(),
                    select.POLLIN | select.POLLPRI \
                    | select.POLLERR | select.POLLHUP | select.POLLNVAL)
    return descr.fileno()

def _write(fd, data, filename):
    global reader_dict
    global poller
    if data:
        logging.log(6, "fd %d: writing : \"%s\"", fd, data)
        os.write(fd, data)
    else:
        logging.log(6, "fd %d: writing file contents: \"%s\"", fd, filename)
        with open(filename, "rb") as f:
            # FIXME: use sendfile, this won't work for big files, obvs.
            os.write(fd, f.read())

def _reset(fd):
    global reader_dict
    spec = reader_dict[fd][0]
    logfile = reader_dict[fd][1]
    logfile_name = logfile.name
    try:
        logfile_fileno = logfile.fileno()
    except ValueError as e:
        logfile_fileno = -1
    try:
        while True:
            s = os.read(fd, 1024) 	# Flush the input channel
            if s == None:
                l = -1
            else:
                l = len(s)
                logging.log(6, "fd %d[%s/%d]: flushed (%dB): %s",
                            fd, logfile_name, logfile_fileno, l, s)
                # FIXME: stop after so
                # much stuff flushed, that
                # means the target DID NOT
                # stop or something is
                # wrong
            if s == None or l <= 0:
                break
    except OSError as e:
        logging.info("fd %d[%s/%d]: flush error, reopening: %s",
                     fd, logfile_name, logfile_fileno, e)
    # It's easier to just close and re-open everyhing
    _close(fd)
    fd =_reopen(spec, logfile.name)
    logfile = reader_dict[fd][1]
    logging.debug("fd %d[%s/%d]: reset logger",
                  fd, logfile.name, logfile.fileno())

def _close(fd):
    global reader_dict
    global poller
    spec = reader_dict[fd][0]
    logfile = reader_dict[fd][1]
    descr = reader_dict[fd][2]
    try:
        logfile_fileno = logfile.fileno()
    except ValueError as e:
        logfile_fileno = -1
    logfile.close()
    try:
        poller.unregister(fd)
    except KeyError:
        pass
    try:
        descr.close()
    except OSError as e:
        if e.errno != errno.EBADF:
            raise
        logging.debug("fd %d[%s/%d]: ignoring -EBADF on close()",
                      fd, logfile.name, logfile_fileno)
    logging.debug("fd %d[%s/%d]: removed reader",
                  fd, logfile.name, logfile_fileno)
    del spec
    del descr
    del logfile
    del reader_dict[fd]
#
# This thread reads from all the file descriptors (normally describing
# serial consoles) given to the daemon. Note the daemon itself is the
# one that has to open the file descriptor, otherwise it might be
# another process.
#
def _reader_fn():
    global _spec_queue
    global reader_dict
    global poller

    poller = select.poll()
    queue_fd = _spec_queue._reader.fileno()

    logging.info("console logger thread")
    while True:
        try:				# Make sure it is there (in
            poller.register(queue_fd)	# case an error took it out)
            rs = poller.poll(1000)          	# Wait for activity
            for r in rs:			# Process said activity
                fd = r[0]
                # Handle management events first
                if fd == queue_fd:		# Read and discard
                    logging.log(8, "QUEUE fd %d, signalled 0x%x", fd, r[1])
                    o = _spec_queue.get_nowait()# just used to run the
                    if o == None:
                        logging.warning("QUEUE: woken up, but got nothing")
                        continue
                    logfile_name = o[1]
                    try:
                        if o[0] == 'add':
                            spec = o[2]
                            _reopen(spec, logfile_name)
                        elif o[0] == 'write':
                            for fd in list(reader_dict.keys()):
                                if reader_dict[fd][1].name == logfile_name:
                                    _write(fd, o[2], o[3])
                        elif o[0] == 'rm':
                            for fd in list(reader_dict.keys()):
                                if reader_dict[fd][1].name == logfile_name:
                                    _close(fd)
                                    break
                        elif o[0] == 'reset':
                            for fd in list(reader_dict.keys()):
                                if reader_dict[fd][1].name == logfile_name:
                                    _reset(fd)
                                    break
                        else:
                            raise ValueError("Unknown action '%s'" % o[0])
                    finally:
                        _spec_queue.task_done()
                        del o                    	
                    continue			# Process next change
                if not fd in reader_dict:
                    logging.debug("fd %d has been removed: 0x%x", fd, r[1])
                    continue
                spec = reader_dict[fd][0]
                logfile = reader_dict[fd][1]
                logfile_name = logfile.name
                try:
                    logfile_fileno = logfile.fileno()
                except ValueError as e:
                    # If closed, just pass it on
                    logfile_fileno = -1
                if r[1] in (select.POLLERR, select.POLLHUP, select.POLLNVAL):
                    # Something is wrong, let it be refreshed; be
                    # loud, normally this means something bad has
                    # happened to the HW or a lurking bug (file has
                    # been closed somehow).
                    logging.warning(
                        "BUG? fd %d[%s/%d]: has to be removed: 0x%x",
                        fd, logfile_name, logfile_fileno, r[1])
                    _close(fd)
                    _reopen(spec, logfile_name)
                elif r[1] == select.POLLIN or r[1] == select.POLLPRI:
                    # Data is available, read in 1K chunks and record
                    # it [FIXME: consider using sendfile()].
                    try:
                        data = os.read(fd, 1024)
                        logging.log(7, "fd %d[%s/%d]: Read %dB: %s",
                                    fd, logfile_name, logfile_fileno,
                                       len(data), data)
                    except OSError as e:
                        logging.error(
                            "fd %d[%s/%d]: log read error, reopening: %s",
                            fd, logfile_name, logfile_fileno, e)
                        _close(fd)
                        _reopen(spec, logfile_name)
                        data = "[some data might have been lost]"
                    try:
                        os.write(logfile_fileno, data)
                    except OSError as e:
                        logging.error("fd %d[%s/%d]: log write error: %s",
                                      fd, logfile_name, logfile_fileno, e)
                    del data			# Ensure data it is gone
                elif r[1] == errno.ENOTTY:
                    logging.info("fd %d[%s/%d]: reopen due to ENOTTY, "
                                 "device replugging?",
                                 fd, logfile_name, logfile_fileno)
                    _close(fd)
                    _reopen(spec, logfile_name)
                else:	# Me not know what you talking'bout
                    if r[1] != errno.ENODEV:
                        logging.error(
                            "fd %d[%s/%d]: Unhandled poll reason 0x%x",
                            fd, logfile_name, logfile_fileno, r[1])
                    else:
                        logging.info("fd %d[%s/%d]: device disconnected",
                                     fd, logfile_name, logfile_fileno)
                    _close(fd)
                    # We do not reopen, usually this means the device is gone
        except Exception as e:
            logging.error("Unhandled reader thread exception: %s: %s",
                          e, traceback.format_exc())

def setup():
    """
    FIXME
    """
    global _spec_queue
    _spec_queue = multiprocessing.JoinableQueue(100)
    # Background thread that reads from all serial ports to a log file
    reader = multiprocessing.Process(target = _reader_fn)
    reader.daemon = True
    reader.start()
    logging.info("console logger launched")


# This to be ran by the master or other processes in the
# multiprocessing pool
def spec_add(logfile_name, spec):
    """
    FIXME
    """
    assert isinstance(logfile_name, str)
    assert isinstance(spec, dict)
    global _spec_queue
    if _spec_queue == None:
        setup()

    # wait here for the node to show up -- we'll also do it in the
    # loop for double checking, but here we don't block anyone and if
    # it fails, we can tell the caller -- otherwise, just proceed for
    # cm_logger to open it (for which we have to delete it again)
    # We can't open it and pass it to the caller because it is another
    # process.
    descr = _spec_open(spec)
    if descr != None:
        descr.close()
        del descr
    else:
        raise RuntimeError("Cannot open serial port (%s); is "
                           "ModemManager trying to scan it?" % spec)

    _spec_queue.put(['add', logfile_name, spec])
    _spec_queue.join()
    logging.debug("%s: adding logger for '%s'", logfile_name, spec)

def spec_write(logfile_name, data = None, filename = None):
    """
    Write to a file descriptor monitored by a logger

    :param str logfile_name: Name of the logger to which file
      descriptor to write to
    :param data: data to be written; use this only for short amounts
      of data
    :param str filename: name of the file that contains the data that
      has to be written, use this for longer data.
    """
    global _spec_queue
    # Either one has to be given, but not both
    assert (data == None) != (filename == None)
    _spec_queue.put(['write', logfile_name, data, filename])
    _spec_queue.join()
    logging.debug("%s: wrote to logger", logfile_name)

# This is to be ran by the master or other processes in the
# multiprocessing pool
def spec_rm(logfile_name):
    global _spec_queue
    _spec_queue.put(['rm', logfile_name])
    _spec_queue.join()
    logging.debug("%s: removing logger", logfile_name)

# This is to be ran by the master or other processes in the
# multiprocessing pool
def spec_reset(logfile_name):
    global _spec_queue
    logging.debug("%s: resetting logger", logfile_name)
    _spec_queue.put(['reset', logfile_name])
    _spec_queue.join()
    # Wait for queue to be flushed?
    logging.debug("%s: reset logger completed", logfile_name)

