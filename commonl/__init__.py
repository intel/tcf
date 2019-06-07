#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Common timo infrastructure and code
Command line and logging helpers

.. moduleauthor:: FIXME <fixme@domain.com>

.. admonition:: FIXMEs

  - This is still leaking temporary files (subpython's stdout and
    stderr) when running top level tests.

"""
import argparse
import base64
import contextlib
import errno
import fcntl
import glob
import hashlib
import imp
import importlib
import inspect
import logging
import numbers
import os
import random
import re
import signal
import socket
import string
import struct
import subprocess
import sys
import tempfile
import termios
import time
import traceback

import requests

from . import expr_parser

logging.addLevelName(50, "C")
logging.addLevelName(40, "E")
logging.addLevelName(30, "W")
logging.addLevelName(20, "I")
logging.addLevelName(10, "D")
logging.addLevelName(9, "D2")
logging.addLevelName(8, "D3")
logging.addLevelName(7, "D4")
logging.addLevelName(6, "D5")

def config_import_file(filename, namespace = "__main__",
                       raise_on_fail = True):
    """Import a Python [configuration] file.

    Any symbol available to the current namespace is available to the
    configuration file.

    :param filename: path and file name to load.

    :param namespace: namespace where to insert the configuration file

    :param bool raise_on_fail: (optional) raise an exception if the
      importing of the config file fails.

    >>> timo.config_import_file("some/path/file.py", "__main__")

    """

    logging.log(9, "%s: configuration file being loaded", filename)
    try:
        imp.load_source(namespace, filename)
        sys.stdout.flush()
        sys.stderr.flush()
        logging.debug("%s: configuration file imported", filename)
    except Exception as e:	# pylint: disable = W0703
        # throw a wide net to catch any errors in filename
        logging.exception("%s: can't load config file: %s", filename, e)
        if raise_on_fail:
            raise

def path_expand(path_list):
    # Compose the path list
    _list = []
    for _paths in path_list:
        paths = _paths.split(":")
        for path in paths:
            if path == "":
                _list = []
            else:
                _list.append(os.path.expanduser(path))
    return _list

def config_import(path_list, file_regex, namespace = "__main__",
                  raise_on_fail = True):
    """Import Python [configuration] files that match file_regex in any of
    the list of given paths into the given namespace.

    Any symbol available to the current namespace is available to the
    configuration file.

    :param paths: list of paths where to import from; each item can be
      a list of colon separated paths and thus the list would be further
      expanded. If an element is the empty list, it removes the
      current list.

    :param file_regex: a compiled regular expression to match the file
      name against.

    :param namespace: namespace where to insert the configuration file

    :param bool raise_on_fail: (optional) raise an exception if the
      importing of the config file fails.

    >>> timo.config_import([ ".config:/etc/config" ],
    >>>                    re.compile("conf[_-].*.py"), "__main__")

    """

    # Compose the path list
    _list = path_expand(path_list)
    paths_done = set()
    # Bring in config files
    # FIXME: expand ~ -> $HOME
    for path in _list:
        abs_path = os.path.abspath(os.path.normpath(path))
        if abs_path in paths_done:
            # Skip what we have done already
            continue
        logging.log(8, "%s: loading configuration files %s",
                    path, file_regex.pattern)
        try:
            if not os.path.isdir(path):
                logging.log(7, "%s: ignoring non-directory", path)
                continue
            for filename in sorted(os.listdir(path)):
                if not file_regex.match(filename):
                    logging.log(6, "%s/%s: ignored", path, filename)
                    continue
                config_import_file(path + "/" + filename, namespace)
        except Exception:	# pylint: disable = W0703
            # throw a wide net to catch any errors in filename
            logging.error("%s: can't load config files", path)
            if raise_on_fail:
                raise
        else:
            logging.log(9, "%s: loaded configuration files %s",
                        path, file_regex.pattern)
        paths_done.add(abs_path)

def logging_verbosity_inc(level):
    if level == 0:
        return
    if level > logging.DEBUG:
        delta = 10
    else:
        delta = 1
    return level - delta


def logfile_open(tag, cls = None, delete = True, bufsize = 0,
                 suffix = ".log", who = None, directory = None):
    assert isinstance(tag, str)
    if who == None:
        frame = inspect.stack(0)[1][0]
        who = frame.f_code.co_name + ":%d" % frame.f_lineno
    if tag != "":
        tag += "-"
    if cls != None:
        clstag = cls.__name__ + "."
    else:
        clstag = ''
    return tempfile.NamedTemporaryFile(
        prefix = os.path.basename(sys.argv[0]) + ":"
        + clstag + who + "-" + tag,
        suffix = suffix, delete = delete, bufsize = bufsize, dir = directory)

class _Action_increase_level(argparse.Action):
    def __init__(self, option_strings, dest, default = None, required = False,
                 nargs = None, **kwargs):
        super(_Action_increase_level, self).__init__(
            option_strings, dest, nargs = 0, required = required,
            **kwargs)

    #
    # Python levels are 50, 40, 30, 20, 10 ... (debug) 9 8 7 6 5 ... :)
    def __call__(self, parser, namespace, values, option_string = None):
        if namespace.level == None:
            namespace.level = logging.ERROR
        namespace.level = logging_verbosity_inc(namespace.level)

def log_format_compose(log_format, log_pid, log_time = False):
    if log_pid == True:
        log_format = log_format.replace(
            "%(levelname)s",
            "%(levelname)s[%(process)d]", 1)
    if log_time == True:
        log_format = log_format.replace(
            "%(levelname)s",
            "%(levelname)s/%(asctime)s", 1)
    return log_format

def cmdline_log_options(parser):
    """Initializes a parser with the standard command line options to
    control verbosity when using the logging module

    :param parser: command line argument parser
    :type parser: argparser.ArgParser()
    :returns: none
    :raises: unknown

    -v|--verbose to increase verbosity (defaults to print/log errors only)

    Note that after processing the command line options, you need to
    initialize logging with:

    >>> import logging, argparse, timo.core
    >>> arg_parser = argparse.ArgumentParser()
    >>> timo.core.cmdline_log_options(arg_parser)
    >>> args = arg_parser.parse_args()
    >>> logging.basicConfig(format = args.log_format, level = args.level)

    """
    if not isinstance(parser, argparse.ArgumentParser):
        raise TypeError("parser argument has to be an argparse.ArgumentParser")

    parser.add_argument("-v", "--verbose",
                        dest = "level",
                        action = _Action_increase_level, nargs = 0,
                        help = "Increase verbosity")
    parser.add_argument("--log-pid-tid", action = "store_true",
                        default = False,
                        help = "Print PID and TID in the logs")
    parser.add_argument("--log-time", action = "store_true",
                        default = False,
                        help = "Print Date and time in the logs")


def mkid(something, l = 10):
    """
    Generate a 10 character base32 ID out of an iterable object

    :param something: anything from which an id has to be generated
    :type something: anything iterable
    """
    h = hashlib.sha512(something)
    return base64.b32encode(h.digest())[:l].lower()



def trim_trailing(s, trailer):
    """
    Trim *trailer* from the end of *s* (if present) and return it.

    :param s: string to trim from
    :type s: string
    :param trailer: string to trim
    :type trailer: string
    """
    tl = len(trailer)
    if s[-tl:] == trailer:
        return s[:-tl]
    else:
        return s


class subpython(object):
    """Convenience to run another program in a subprocess and get its output

    >>> import timo
    >>> sp = timo.subpython("some/file.py -v ARG1 ARG2")
    # do something to stimulate it / test it
    >>> try:
    >>>     r = sp.join()
    >>> except Exception as e:
    >>> ...

    Upon object instantiation, the process is spawned and started,
    arguments passed. :func:`sp.join` waits for the process to
    complete and then whatever it ereturns it's returned. If it was
    terminated by a signal, it'll return the negative signal number.
    """

    #: lines of standard output
    stdout_lines = []
    #: lines of standard error
    stderr_lines = []
    #: formatted standard error and output
    output_str = ""

    def __init__(self, cmdline, stdout_name = None, stderr_name = None):
        """
        """
        self.cmdline = cmdline
        self.l = logging.getLogger("subpython")
        frame = inspect.stack(0)[1][0]
        # Yup, we do two sets of file descriptors so they don't
        # interfere on eachothre; one pair is given to the subprocess
        # to write, the other we use it to read.
        who = frame.f_code.co_name + ":%d" % frame.f_lineno
        if stdout_name == None:
            self._stdout = logfile_open("stdout-", cls = subpython,
                                        who = who, suffix = ".log")
        else:
            self._stdout = open(stdout_name, "w")
        self.stdout = open(self._stdout.name, "r")
        if stderr_name == None:
            self._stderr = logfile_open("stderr-", cls = subpython,
                                        who = who, suffix = ".log")
        else:
            self._stderr = open(stderr_name, "w")
        self.stderr = open(self._stderr.name, "r")
        (self.stdin_pipe_fdr, self.stdin_pipe_fdw) = os.pipe()
        self.p = subprocess.Popen(
            cmdline, close_fds = True, shell = True,
            stdout = self._stdout,
            stderr = self._stderr,
            stdin = self.stdin_pipe_fdr)
        self.l.log(9, "spawned: %s", self.cmdline)

    def flush(self):
        """
        Flush output files (stdout and stderr) and rewind them to the
        beginning of the file.
        """
        if not self.stdout.closed:
            self.stdout.flush()
            self.stdout.seek(0)
            self.stdout_lines = self.stdout.readlines()
        else:
            with open(self.stdout.name) as f:
                self.stdout_lines = f.readlines()
        if not self.stderr.closed:
            self.stderr.flush()
            self.stderr.seek(0)
            self.stderr_lines = self.stderr.readlines()
        else:
            with open(self.stderr.name) as f:
                self.stderr_lines = f.readlines()

    def join(self):
        """
        Wait for the process to finish and return it's exitcode.

        Fill out outputs. See :func:`self.output`.

        :returns: proccess' return code, or negative signal number if
          killed by a signal
        """
        self.l.log(8, "joining: %s", self.cmdline)
        self.p.wait()
        self.l.log(9, "joined: %s", self.cmdline)
        self.flush()
        self.output()
        for line in self.stderr_lines:
            self.l.log(9, "stderr: " + line.strip())
        for line in self.stdout_lines:
            self.l.log(9, "stdout: " + line.strip())
        self.stdout.close()
        self._stdout.close()
        self.stderr.close()
        self._stderr.close()
        if self.stdin_pipe_fdr != -1:
            os.close(self.stdin_pipe_fdr)
            self.stdin_pipe_fdr = -1
        if self.stdin_pipe_fdw != -1:
            os.close(self.stdin_pipe_fdw)
            self.stdin_pipe_fdw = -1
        return self.p.returncode

    def stdin_write(self, data):
        os.write(self.stdin_pipe_fdw, data)

    def started(self):
        """
        Returns *True* if the process has succesfully started
        """
        self.p.poll()
        return self.p.pid != None

    def terminate_if_alive(self):
        """
        Stop the subprocess if it is running
        """
        self.p.poll()
        if self.p.returncode == None:
            self.l.log(8, "terminating: %s", self.cmdline)
            # Use negative, so we also kill child processes of a setsid
            try:
                os.kill(-self.p.pid, signal.SIGTERM)
                time.sleep(0.25)
                os.kill(-self.p.pid, signal.SIGKILL)
            except OSError:	# Most cases, already dead
                pass
            self.p.terminate()
            self.l.log(9, "terminated: %s", self.cmdline)
            self.stdout.close()
            self._stdout.close()
            self.stderr.close()
            self._stderr.close()
            if self.stdin_pipe_fdr != -1:
                os.close(self.stdin_pipe_fdr)
                self.stdin_pipe_fdr = -1
            if self.stdin_pipe_fdw != -1:
                os.close(self.stdin_pipe_fdw)
                self.stdin_pipe_fdw = -1

    def output(self):
        """
        Return a string formatted with all the standard and error
        outputs of the subprocess. Fill out :data:`stdout_lines`,
        :data:`stderr_lines` and :data:`output_str` with the
        formatting of those two.
        Leave the file pointers at the beginning in case we have to
        re-read.
        """
        self.flush()
        self.output_str = "stdout: ".join(["\n"] + self.stdout_lines) \
            + "stderr: ".join(["\n"] + self.stderr_lines)
        self.flush()
        return self.output_str


def name_make_safe(name, safe_chars = None):
    """
    Given a filename, return the same filename will all characters not
    in the set [-_.0-9a-zA-Z] replaced with _.

    :param str name: name to make *safe*
    :param set safe_chars: (potional) set of characters that are
      considered safe. Defaults to ASCII letters and digits plus - and
      _.
    """
    if safe_chars == None:
        safe_chars = set('-_' + string.ascii_letters + string.digits)
    # We don't use string.translate()'s deletions because it doesn't
    # take them for Unicode strings.
    r = ""
    for c in name:
        if c not in safe_chars:
            c = '_'
        r += c
    return r


def file_name_make_safe(file_name, extra_chars = ":/"):
    """
    Given a filename, return the same filename will all characters not
    in the set [-_.0-9a-zA-Z] removed.

    This is useful to kinda make a URL into a file name, but it's not
    bidirectional (as it is destructive) and not very fool proof.
    """
    # We don't use string.translate()'s deletions because it doesn't
    # take them for Unicode strings.
    r = ""
    for c in file_name:
        if c in set(extra_chars + string.whitespace):
            continue
        r += c
    return r

def hash_file(hash_object, filepath, blk_size = 8192):
    """
    Run a the contents of a file though a hash generator.

    :param hash_object: hash object (from :py:mod:`hashlib`)
    :param filepath: path to the file to feed
    :type filepath: str
    :param blk_size: read the file in chunks of that size (in bytes)
    :type blk_size: integer
    """
    assert hasattr(hash_object, "update")
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(blk_size), b''):
            hash_object.update(chunk)
    return hash_object

def request_response_maybe_raise(response):
    if not response:
        try:
            json = response.json()
            if json != None and 'message' in json:
                message = json['message']
            else:
                message = "no specific error text available"
        except ValueError as e:
            message = "no specific error text available"
        logging.debug("HTTP Error: %s", response.text)
        e = requests.HTTPError(
            "%d: %s" % (response.status_code, message))
        e.status_code = response.status_code
        raise e

def _os_path_split_full(path):
    """
    Split an absolute path in all the directory components
    """
    t = os.path.split(path)
    if t[0] == "/":
        l = [ t[1] ]
    else:
        l = _os_path_split_full(t[0])
        l.append(t[1])
    return l

def os_path_split_full(path):
    """
    Split an absolute path in all the directory components
    """
    parts =  _os_path_split_full(os.path.abspath(path))
    return parts

def progress(msg):
    """
    Print some sort of progress information banner to standard error
    output that will be overriden with real information.

    This only works when stdout or stderr are not redirected to files
    and is intended to give humans a feel of what's going on.
    """
    if not sys.stderr.isatty() or not sys.stdout.isatty():
        return

    _h, w, _hp, _wp = struct.unpack(
        'HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ,
                            struct.pack('HHHH', 0, 0, 0, 0)))
    if len(msg) < w:
        w_len = w - len(msg)
        msg += w_len * " "
    sys.stderr.write(msg + "\r")
    sys.stderr.flush()


def digits_in_base(number, base):
    """
    Convert a number to a list of the digits it would have if written
    in base @base.

    For example:
     - (16, 2) -> [1, 6] as 1*10 + 6 = 16
     - (44, 4) -> [2, 3, 0] as 2*4*4 + 3*4 + 0 = 44
    """
    if number == 0:
        return [ 0 ]
    digits = []
    while number != 0:
        digit = int(number % base)
        number = int(number / base)
        digits.append(digit)
    digits.reverse()
    return digits

def rm_f(filename):
    """
    Remove a file (not a directory) unconditionally, ignore errors if
    it does not exist.
    """
    try:
        os.unlink(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

def makedirs_p(dirname, mode = None):
    """
    Create a directory tree, ignoring an error if it already exists

    :param str pathname: directory tree to crate
    :param int mode: mode set the directory to
    """
    try:
        os.makedirs(dirname)
        # yes, this is a race condition--but setting the umask so
        # os.makedirs() gets the right mode would interfere with other
        # threads and processes.
        if mode:
            os.chmod(dirname, mode)
    except OSError:
        if not os.path.isdir(dirname):
            raise

def symlink_f(source, dest):
    """
    Create a symlink, ignoring an error if it already exists

    """
    try:
        os.symlink(source, dest)
    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.islink(dest):
            raise

def _pid_grok(pid):
    if pid == None:
        return None, None
    if isinstance(pid, str):
        # Is it a PID encoded as string?
        try:
            return int(pid), None
        except ValueError:
            pass
        # Mite be a pidfile
        try:
            with open(pid) as f:
                pids = f.read()
        except IOError:
            return None, pid
        try:
            return int(pids), pid
        except ValueError:
            return None, pid
    elif isinstance(pid, int):
        # fugly
        return pid, None
    else:
        assert True, "don't know how to convert %s to a PID" % pid

def process_alive(pidfile, path = None):
    """
    Return if a process path/PID combination is alive from the
    standpoint of the calling context (in terms of UID permissions,
    etc).

    :param str pidfile: path to pid file (or)
    :param str pidfile: PID of the process to check (in str form) (or)
    :param int pidfile: PID of the process to check
    :param str path: path binary that runs the process

    :returns: PID number if alive, *None* otherwise (might be running as a
      separate user, etc)
    """
    if path:
        paths = path + ": "
    else:
        paths = ""
    pid, _pidfile = _pid_grok(pidfile)
    if pid == None:
        return None
    try:
        os.kill(pid, 0)
    except OSError as e:
        if e.errno == errno.ESRCH:	# Not running
            return None
        if e.errno == errno.EPERM:	# Running, but not our user?
            return None
        raise RuntimeError("%scan't signal pid %d to test if running: %s"
                           % (paths, pid, e))
    if not path:
        return pid
    # Thing is running, let's see what it is
    try:
        _path = os.readlink("/proc/%d/exe" % pid)
    except OSError as e:
        # Usually this means it has died while we checked
        return None
    if path == _path:
        return pid
    else:
        return None

def process_terminate(pid, pidfile = None, tag = None,
                      path = None, wait_to_kill = 0.25):
    """Terminate a process (TERM and KILL after 0.25s)

    :param pid: PID of the process to kill; this can be an
      integer, a string representation of an integer or a path to a
      PIDfile.

    :param str pidfile: (optional) pidfile to remove [deprecated]

    :param str path: (optional) path to the binary

    :param str tag: (optional) prefix to error messages
    """
    if tag == None:
        if path:
            _tag = path
        else:
            _tag = ""
    else:
        _tag = tag + ": "
    _pid, _pidfile = _pid_grok(pid)
    if _pid == None:
        # Nothing to kill
        return
    if path:
        # Thing is running, let's see what it is
        try:
            _path = os.readlink("/proc/%d/exe" % _pid)
        except OSError as e:
            # Usually this means it has died while we checked
            return None
        if os.path.abspath(_path) != os.path.abspath(path):
            return None	            # Not our binary
    try:
        signal_name = "SIGTERM"
        os.kill(_pid, signal.SIGTERM)
        time.sleep(wait_to_kill)
        signal_name = "SIGKILL"
        os.kill(_pid, signal.SIGKILL)
    except OSError as e:
        if e.errno == errno.ESRCH:	# killed already
            return
        else:
            raise RuntimeError("%scan't %s: %s"
                               % (tag, signal_name, e.message))
    finally:
        if _pidfile:
            rm_f(_pidfile)
        if pidfile:	# Extra pidfile to remove, kinda deprecated
            rm_f(pidfile)

def process_started(pidfile, path,
                    tag = None, log = None,
                    verification_f = None,
                    verification_f_args = None,
                    timeout = 5, poll_period = 0.3):
    if log == None:
        log = logging
    if tag == None:
        tag = path
    t0 = time.time()		# Verify it came up
    while True:
        t = time.time()
        if t - t0 > timeout:
            log.error("%s: timed out (%ss) starting process", tag, timeout)
            return None
        time.sleep(poll_period)		# Give it .1s to come up
        pid = process_alive(pidfile, path)
        if pid == None:
            log.debug("%s: no PID yet (+%.2f/%ss), re-checking", tag,
                      t - t0, timeout)
            continue
        # PID found, if there is a verification function, let's run it
        break
    if verification_f:
        log.debug("%s: pid %d found at +%.2f/%ss), verifying",
                  tag, pid, t - t0, timeout)
        while True:
            if t - t0 > timeout:
                log.error("%s: timed out (%ss) verifying process pid %d",
                          tag, timeout, pid)
                return None
            if verification_f(*verification_f_args):
                log.debug("%s: started (pid %d) and verified at +%.2f/%ss",
                          tag, pid, t - t0, timeout)
                return pid
            time.sleep(poll_period)		# Give it .1s to come up
            t = time.time()
    else:
        log.debug("%s: started (pid %d) at +%.2f/%ss)",
                  tag, pid, t - t0, timeout)
        return pid

def origin_get(depth = 1):
    """
    Return the name of the file and line from which this was called
    """
    o = inspect.stack()[depth]
    return "%s:%s" % (o[1], o[2])

def origin_fn_get(depth = 1, sep = ":"):
    """
    Return the name of the function and line from which this was called
    """
    frame = inspect.stack()[depth][0]
    return frame.f_code.co_name + sep + "%d" % frame.f_lineno

def kws_update_type_string(kws, rt, kws_origin = None, origin = None,
                           prefix = ""):
    # FIXME: rename this to _scalar
    # FIXME: make this replace subfields as .
    #        ['bsps']['x86']['zephyr_board'] = 'arduino_101' becomes
    #        'bsps.x86.zephyr_board' = 'arduino_101'
    """
    Given a dictionary, update the second only using those keys with
    string values

    :param dict kws: destination dictionary
    :param dict d: source dictionary
    """
    assert isinstance(kws, dict)
    if not isinstance(rt, dict):
        # FIXME: this comes from the remote server...
        return
    for key, value in rt.items():
        if value == None:
            kws[prefix + key] = ""
            if kws_origin and origin:
                kws_origin[prefix + key] = origin
        elif isinstance(value, str) \
           or isinstance(value, numbers.Integral):
            kws[prefix + key] = value
            if kws_origin and origin:
                kws_origin[prefix + key] = origin
        elif isinstance(value, bool):
            kws[prefix + key] = value

def _kws_update(kws, rt, kws_origin = None, origin = None,
                prefix = ""):
    """
    Given a dictionary, update the second only using those keys from
    the first string values

    :param dict kws: destination dictionary
    :param dict d: source dictionary
    """
    assert isinstance(kws, dict)
    if not isinstance(rt, dict):
        return
    for key, value in rt.items():
        if value == None:
            kws[prefix + key] = ""
            if kws_origin and origin:
                kws_origin[prefix + key] = origin
        else:
            kws[prefix + key] = value
            if kws_origin and origin:
                kws_origin[prefix + key] = origin

def kws_update_from_rt(kws, rt, kws_origin = None, origin = None,
                       prefix = ""):
    """
    Given a target's tags, update the keywords valid for exporting and
    evaluation

    This means filtering out things that are not strings and maybe
    others, decided in a case by case basis.

    We make sure we fix the type and 'target' as the fullid.
    """
    # WARNING!!! This is used by both the client and server code
    assert isinstance(kws, dict)
    assert isinstance(rt, dict)
    if origin == None and 'url' in rt:
        origin = rt['url']
    if origin == None:
        origin = origin_get(2)
    else:
        assert isinstance(origin, str)

    _kws_update(kws, rt, kws_origin = kws_origin,
                origin = origin, prefix = prefix)
    if 'fullid' in rt:
        # Clients have full id in the target tags (as it includes the
        # server AKA')
        kws[prefix + 'target'] = file_name_make_safe(rt['fullid'])
    else:
        # Said concept does not exist in the server...
        kws[prefix + 'target'] = file_name_make_safe(rt['id'])
    kws[prefix + 'type'] = rt['type']
    if kws_origin:
        assert isinstance(kws_origin, dict)
        kws_origin[prefix + 'target'] = origin
        kws_origin[prefix + 'type'] = origin
    # Interconnects need to be exported manually
    kws['interconnects'] = {}
    if 'interconnects' in rt:
        _kws_update(kws['interconnects'], rt['interconnects'],
                    kws_origin = kws_origin,
                    origin = origin, prefix = prefix)


def if_present(ifname):
    """
    Return if network interface *ifname* is present in the system

    :param str ifname: name of the network interface to remove
    :returns: True if interface exists, False otherwise
    """
    return os.path.exists("/sys/class/net/" + ifname)

def if_index(ifname):
    """
    Return the interface index for *ifname* is present in the system

    :param str ifname: name of the network interface
    :returns: index of the interface, or None if not present
    """
    try:
        with open("/sys/class/net/" + ifname + "/ifindex") as f:
            index = f.read().strip()
            return int(index)
    except IOError:
        raise IndexError("%s: network interface does not exist" % ifname)

def if_find_by_mac(mac, physical = True):
    """
    Return the name of the physical network interface whose MAC
    address matches *mac*.

    Note the comparison is made at the string level, case
    insensitive.

    :param str mac: MAC address of the network interface to find
    :param bool physical: True if only look for physical devices (eg:
      not vlans); this means there a *device* symlink in
      */sys/class/net/DEVICE/*
    :returns: Name of the interface if it exists, None otherwise
    """
    assert isinstance(mac, str)
    for path in glob.glob("/sys/class/net/*/address"):
        if physical and not os.path.exists(os.path.dirname(path) + "/device"):
            continue
        with open(path) as f:
            path_mac = f.read().strip()
            if path_mac.lower() == mac.lower():
                return os.path.basename(os.path.dirname(path))
    return None

def if_remove(ifname):
    """
    Remove from the system a network interface using
    *ip link del*.

    :param str ifname: name of the network interface to remove
    :returns: nothing
    """
    subprocess.check_call("ip link del " + ifname, shell = True)

def if_remove_maybe(ifname):
    """
    Remove from the system a network interface (if it exists) using
    *ip link del*.

    :param str ifname: name of the network interface to remove
    :returns: nothing
    """
    if if_present(ifname):
        if_remove(ifname)

def ps_children_list(pid):
    """
    List all the PIDs that are children of a give process

    :param int pid: PID whose children we are looking for
    :return: set of PIDs children of *PID* (if any)
    """
    cl = set()
    try:
        for task_s in os.listdir("/proc/%d/task/" % pid):
            task = int(task_s)
            with open("/proc/%d/task/%d/children" % (pid, task)) as childrenf:
                children = childrenf.read()
                for child in children.split():
                    if child != pid:
                        cl.add(int(child))
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

    f = set()
    for child_pid in cl:
        f.update(ps_children_list(child_pid))
    f.update(cl)
    return f

def ps_zombies_list(pids):
    """
    Given a list of PIDs, return which are zombies

    :param pids: iterable list of numeric PIDs
    :return: set of PIDs which are zombies
    """
    zombies = set()
    for pid in pids:
        try:
            with open("/proc/%d/stat" % pid) as statf:
                stat = statf.read()
                if ") Z " in stat:
                    zombies.add(pid)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            # If the PID doesn't exist, ignore it
    return zombies

def version_get(module, name):
    try:
        # Try version module created during installation by
        # {,ttbd}/setup.py into {ttbd,tcfl}/version.py.
        #
        # We use two different version modules to catch be able to
        # catch mismatched installations
        importlib.import_module(module.__name__ + ".version")
        return module.version.version_string
    except ImportError as _e:
        pass
    # Nay? Maybe a git tree because we are running from the source
    # tree during development work?
    _src = os.path.abspath(module.__file__)
    _srcdir = os.path.dirname(_src)
    try:
        git_version = subprocess.check_output(
            "git describe --tags --always --abbrev=7 --dirty".split(),
            cwd = _srcdir, stderr = subprocess.STDOUT)
        return git_version.strip()
    except subprocess.CalledProcessError as _e:
        # At this point, logging is still not initialized
        raise RuntimeError("Unable to determine %s (%s) version: %s"
                           % (name, _srcdir, _e.output))

def tcp_port_busy(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.close()
        del s
        return False
    except socket.error as e:
        if e.errno == errno.EADDRINUSE:
            return True
        raise

# FIXME: this thing sucks, it is obviously racy, but I can't figure
# out a better way -- we can't bind to (0) because we have plenty of
# daemons that need to get assigned more than one port and then it is
# impossible to get from them where did they bind (assuming they can
# do it)
def tcp_port_assigner(ports = 1, port_range = (1025, 65530)):
    assert isinstance(port_range, tuple) and len(port_range) == 2 \
        and port_range[0] > 0 and port_range[1] < 65536 \
        and port_range[0] + 10 < port_range[1], \
        "port range has to be (A, B) with A > 0 and B < 65536, A << B; " \
        "got " + str(port_range)
    max_tries = 1000
    while max_tries > 0:
        port_base = random.randrange(port_range[0], port_range[1])
        for port_cnt in range(ports):
            if tcp_port_busy(port_base + port_cnt):
                continue
            else:
                return port_base
        max_tries -= 1
    raise RuntimeError("Cannot assign %d ports" % ports)

def tcp_port_connectable(hostname, port):
    """
    Return true if we can connect to a TCP port
    """
    try:
        with contextlib.closing(socket.socket(socket.AF_INET,
                                              socket.SOCK_STREAM)) as sk:
            sk.settimeout(5)
            sk.connect((hostname, port))
            return True
    except socket.error:
        return False

def conditional_eval(tag, kw, conditional, origin,
                     kind = "conditional"):
    """
    Evaluate an action's conditional string to determine if it
    should be considered or not.

    :returns bool: True if the action must be considered, False
      otherwise.
    """
    if conditional == None:
        return True
    try:
        return expr_parser.parse(conditional, kw)
    except Exception as e:
        raise Exception("error evaluating %s %s "
                        "'%s' from '%s': %s"
                        % (tag, kind, conditional, origin, e))

def check_dir(path, what):
    if not os.path.isdir(path):
        raise RuntimeError("%s: path for %s is not a directory" % (path, what))

def check_dir_writeable(path, what):
    check_dir(path, what)
    if not os.access(path, os.W_OK):
        raise RuntimeError("%s: path for %s does not allow writes"
                           % (path, what))

def prctl_cap_get_effective():
    """
    Return an integer describing the effective capabilities of this process
    """
    # FIXME: linux only
    # CAP_NET_ADMIN is 12 (from /usr/include/linux/prctl.h
    with open("/proc/self/status") as f:
        s = f.read()
        r = re.compile(r"^CapEff:\s(?P<cap_eff>[0-9a-z]+)$", re.MULTILINE)
        m = r.search(s)
        if not m or not 'cap_eff' in m.groupdict():
            raise RuntimeError("Cannot find effective capabilities "
                               "in /proc/self/status: %s",
                               m.groupdict() if m else None)
        return int(m.groupdict()['cap_eff'], 16)


def which(cmd, mode = os.F_OK | os.X_OK, path = None):
    """Given a command, mode, and a PATH string, return the path which
    conforms to the given mode on the PATH, or None if there is no such
    file.

    `mode` defaults to os.F_OK | os.X_OK. `path` defaults to the result
    of os.environ.get("PATH"), or can be overridden with a custom search
    path.

    .. note: Lifted from Python 3.6
    """
    # Check that a given file can be accessed with the correct mode.
    # Additionally check that `file` is not a directory, as on Windows
    # directories pass the os.access check.
    def _access_check(fn, mode):
        return (os.path.exists(fn) and os.access(fn, mode)
                and not os.path.isdir(fn))

    # If we're given a path with a directory part, look it up directly
    # rather than referring to PATH directories. This includes
    # checking relative to the current directory, e.g. ./script
    if os.path.dirname(cmd):
        if _access_check(cmd, mode):
            return cmd
        return None

    if path is None:
        path = os.environ.get("PATH", os.defpath)
    if not path:
        return None
    path = path.split(os.pathsep)

    # On other platforms you don't have things like PATHEXT to tell you
    # what file suffixes are executable, so just pass on cmd as-is.
    files = [cmd]

    seen = set()
    for _dir in path:
        normdir = os.path.normcase(_dir)
        if not normdir in seen:
            seen.add(normdir)
            for thefile in files:
                name = os.path.join(_dir, thefile)
                if _access_check(name, mode):
                    return name
    return None

def ttbd_locate_helper(filename, log = logging, relsrcpath = ""):
    """
    Find the path to a TTBD file, depending on we running from source
    or installed system wide.

    :param str filename: name of the TTBD file we are looking for.
    :param str relsrcpath: path relative to the running binary in the source
    """
    # Simics needs an image with a bootloader, we use grub2 and we
    # share the setup-efi-grub2-elf.sh implementation from grub2elf.
    _src = os.path.abspath(sys.argv[0])
    _srcdir = os.path.dirname(_src)
    # Running from source tree
    cmd_path = os.path.join(_srcdir, relsrcpath, filename)
    if os.path.exists(cmd_path):
        return cmd_path
    # System-wide install in the same prefix -> ../share/tcf
    cmd_path = os.path.join(_srcdir, "..", "share", "tcf", filename)
    log.debug("looking for %s" % cmd_path)
    if os.path.exists(cmd_path):
        return cmd_path
    raise RuntimeError("Can't find util %s" % filename)

def raise_from(what, cause):
    """
    Forward compath to Python 3's raise X from Y
    """
    setattr(what, "__cause__", cause)
    raise what

#: Regex to filter out ANSI characters from text, to ease up debug printing
#:
#: Use as:
#:
#: >>> data = commonl.ansi_regex.sub('', source_data)
#:
# FIXME: this is deleting more stuff than it should
ansi_regex = re.compile(r'\x1b(\[[0-9]*J|\[[0-9;]*H|\[[0-9=]*h|\[[0-9]*m|\[B)')


class dict_missing_c(dict):
    """
    A dictionary that returns as a value a string KEY_UNDEFINED_SYMBOL
    if KEY is not in the dictionary.

    This is useful for things like

    >>> "%(idonthavethis)" % dict_missing_c({"ihavethis": True"}

    to print "idonthavethis_UNDEFINED_SYMBOL" intead of raising KeyError
    """
    def __init__(self, d):
        dict.__init__(self, d)

    def __getitem__(self, key):
        if self.__contains__(key):
            return dict.__getitem__(self, key)
        return "%s_UNDEFINED_SYMBOL.%s" % (key, origin_fn_get(2, "."))

def ipv4_len_to_netmask_ascii(length):
    return socket.inet_ntoa(struct.pack('>I', 0xffffffff ^ ((1 << (32 - length) ) - 1)))
    
