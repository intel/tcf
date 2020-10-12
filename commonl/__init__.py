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
import bisect
import collections
import contextlib
import errno
import fcntl
import fnmatch
import glob
import hashlib
import imp
import importlib
import io
import inspect
import logging
import numbers
import os
import random
import re
import requests
import signal
import socket
import string
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import traceback
import types

try:
    import keyring
    keyring_available = True
except ImportError as e:
    logging.warning("can't import keyring, functionality disabled")
    keyring_available = False

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

# Ensure compatibility with python versions before 3.7 since older
# versions use re._pattern_type instead of re.Pattern
if sys.version_info.major == 3 and sys.version_info.minor < 7:
    re.Pattern = re._pattern_type

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
        suffix = suffix, delete = delete, buffering = bufsize, dir = directory)

def argparser_add_aka(ap, name, aka):
    # UGLY, but...
    ap._name_parser_map[aka] = ap._name_parser_map[name]

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

    :param python:argparse.ArgParser parser: command line argument parser

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

    :param something: anything from which an id has to be generate
      (anything iterable)
    """
    if isinstance(something, str):
        h = hashlib.sha512(something.encode('utf-8'))
    else:
        h = hashlib.sha512(something)
    return base64.b32encode(h.digest())[:l].lower().decode('utf-8', 'ignore')


def trim_trailing(s, trailer):
    """
    Trim *trailer* from the end of *s* (if present) and return it.

    :param str s: string to trim from
    :param str trailer: string to trim
    """
    tl = len(trailer)
    if s[-tl:] == trailer:
        return s[:-tl]
    else:
        return s

def verify_str_safe(s, safe_chars = None):
    """
    Raise an exception if string contains unsafe chars

    :param str s: string to check
    :param str safe_chars: (optional) list/set of valid chars
      (defaults to ASCII letters, digits, - and _)
    """
    if safe_chars == None:
        safe_chars = set('-_' + string.ascii_letters + string.digits)
    s_set = set(s)
    s_unsafe = s_set - s_set.intersection(safe_chars)
    assert not s_unsafe, \
        "%s: contains invalid characters: %s (valid are: %s)" % (
            s, "".join(s_unsafe), "".join(safe_chars))


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

def file_touch(file_name):
    """
    Set a file's mtime to current time

    :param str file_name: name of the file whose timestamp is to be modified
    """
    ts = time.time()
    os.utime(file_name, ( ts, ts ))


def hash_file(hash_object, filepath, blk_size = 8192):
    """
    Run a the contents of a file though a hash generator.

    :param hash_object: hash object (from :py:mod:`hashlib`)
    :param str filepath: path to the file to feed
    :param int blk_size: read the file in chunks of that size (in bytes)
    """
    assert hasattr(hash_object, "update")
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(blk_size), b''):
            hash_object.update(chunk)
    return hash_object

def symlink_lru_cleanup(dirname, max_entries):
    """
    Delete the oldest in a list of symlinks that are used as a cache
    until only *max_entries* are left

    :param str dirname: path where the files are located

    :param int max_entries: maximum number of entries which should be
      left

    """
    assert isinstance(dirname, basestring)
    assert isinstance(max_entries, int) and max_entries > 0

    mtimes_sorted_list = []
    mtimes = {}

    for path, _dirs, filenames in os.walk(dirname):
        for filename in filenames:
            filepath = os.path.join(path, filename)
            mtime = os.lstat(filepath).st_mtime
            mtimes[mtime] = filepath
            bisect.insort(mtimes_sorted_list, mtime)
        break	# only one directory level

    clean_number = len(mtimes_sorted_list) - max_entries
    if clean_number < 0:
        return
    for mtime in mtimes_sorted_list[:clean_number]:
        rm_f(mtimes[mtime])


def hash_file_maybe_compressed(hash_object, filepath, cache_entries = 128,
                               cache_path = None, tmpdir = None):
    """Run the file's contents through a hash generator, maybe
    uncompressing it first.

    Uncompression only works if the file is compressed using a filter
    like program (eg: gz, bzip2, xz) -- see :func:`maybe_decompress`.

    If caching is enabled, the results of uncompressing and hashing
    the file will be kept in a cache so that next time it can be used
    instead of decompressing the file again.

    :param hash_object: :mod:`hashlib` returned object to do hashing
      on data.

      >>> hashlib.sha512()

    :param str filepath: path to file to hash; if not compressed, it
      will be passed straight to :func:`hash_file`.

    :param int cache_entries: (optional; default *128*) if zero,
      caching is disabled. Otherwise, caching is enabled and we'll
      keep those many entries.

      The results are cached based on the hash of the compressed
      data--if the hexdigest for the compressed data is in the cache,
      it's value will be the hexdigest of the uncompressed data. If
      not, decompress, calculate and store int he cache for future
      use.

    :param str cache_path: (optional; default
      *~/.cache/compressed-hashes*) if caching is enabled, path where
      to store the cached hashes.

    :param str tmpdir: (optional; default
      */tmp/compressed-hashes.XXXXXX*) temporary directory where to
      uncompress to generate the hash.

    :returns: hexdigest of the compressed file data in string form


    **Cache database**

    Cache entries use symlinks as an atomic key/value storage system
    in a directory. These are lightweight and setting is POSIX
    atomic.

    There is an slight race condition until we move to Python3 in that
    we can't update the mtime when used. However, it is harmless
    because it means a user will decompress and update, but not create
    bad results.

    """
    assert isinstance(cache_entries, int) and cache_entries >= 0

    _basename, ext = file_is_compressed(filepath)
    if ext == None:	# not compressed, so pass through
        return hash_file(hash_object, filepath).hexdigest()

    # File is compressed
    #
    # Let's get the hash of the compressed data, using the same hash
    # object algorithm, to see if we have it cached.
    hoc = hash_file(hashlib.new(hash_object.name), filepath)
    hexdigest_compressed = hoc.hexdigest()
    if cache_entries:
        # if there is no cache location, use our preset in the user's home dir
        if cache_path == None:
            cache_path = os.path.join(
                os.path.expanduser("~"), ".cache", "compressed-hashes")
            makedirs_p(cache_path)
        symlink_lru_cleanup(cache_path, cache_entries)
        cached_filename = os.path.join(cache_path, hoc.hexdigest())
        try:
            value = os.readlink(cached_filename)
            # we have read the value, so now we remove the entry and
            # if it is "valid", we recreate it, so the mtime is
            # updated and thus an LRU cleanup won't wipe it.
            # FIXME: python3 just update utime
            rm_f(cached_filename)
            # basic verification, it has to look like the hexdigest()
            if len(value) != len(hoc.hexdigest()):
                value = None
            # recreate it, so that the mtime shows we just used it
            os.symlink(value, cached_filename)
            return value
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            value = None

    # decompress and generate hash
    #
    # We need a tmpdir where to decompress
    if not tmpdir:
        tmpdir = tempfile.mkdtemp(prefix = "compressed-hashes.")
        tmpdir_delete = True
    else:
        tmpdir_delete = False
    # Now, because maybe_decompress() works by decompressing to a file
    # named without the extension (it is how it is), we link the file
    # with the extension to the tmpdir and tell maybe_decompress() to
    # do its thing -- then we has the raw data
    filename_tmp_compressed = os.path.join(tmpdir, os.path.basename(filepath))
    os.symlink(os.path.abspath(filepath), filename_tmp_compressed)
    try:
        filename_tmp = maybe_decompress(filename_tmp_compressed)
        ho = hash_file(hash_object, filename_tmp)
    finally:
        rm_f(filename_tmp)
        rm_f(filename_tmp_compressed)
        if tmpdir_delete:
            os.rmdir(tmpdir)

    hexdigest = ho.hexdigest()

    if cache_entries:
        symlink_f(hexdigest, os.path.join(cache_path, hexdigest_compressed))

    return hexdigest


def request_response_maybe_raise(response):
    if not response:
        try:
            json = response.json()
            if json != None:
                if '_message' in json:
                    message = json['_message']
                elif 'message' in json:	# COMPAT: older daemons
                    message = json['message']
                else:
                    message = "no specific error text available"
            else:
                message = "no specific error text available"
        except ValueError as e:
            message = "no specific error text available"
        logging.debug("HTTP Error: %s", response.text)
        e = requests.exceptions.HTTPError(
            "%d: %s" % (response.status_code, message))
        e.status_code = response.status_code
        e.message = response.reason
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

def makedirs_p(dirname, mode = None, reason = None):
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
    except OSError as e:
        if not os.path.isdir(dirname):
            raise RuntimeError("%s: path for %s is not a directory: %s"
                               % (dirname, reason, e))
        if not os.access(dirname, os.W_OK):
            raise RuntimeError("%s: path for %s does not allow writes: %s"
                               % (dirname, reason, e))

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
                               % (tag, signal_name, str(e)))
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


def origin_get_object_path(o):
    return inspect.getsourcefile(o)

def origin_get_object(o):
    return "%s:%s" % (inspect.getsourcefile(o),
                      inspect.getsourcelines(o)[1])

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
    kws[prefix + 'type'] = rt.get('type', 'n/a')
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
        return git_version.strip().decode('utf-8')
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
    def __init__(self, d, missing = None):
        assert isinstance(d, dict)
        assert missing == None or isinstance(missing, str)
        dict.__init__(self, d)
        self.missing = missing

    def __getitem__(self, key):
        if self.__contains__(key):
            return dict.__getitem__(self, key)
        if self.missing:
            return self.missing
        return "%s_UNDEFINED_SYMBOL.%s" % (key, origin_fn_get(2, "."))

def ipv4_len_to_netmask_ascii(length):
    return socket.inet_ntoa(struct.pack('>I', 0xffffffff ^ ((1 << (32 - length) ) - 1)))

def password_get(domain, user, password):
    """
    Get the password for a domain and user

    This returns a password obtained from a configuration file, maybe
    accessing secure password storage services to get the real
    password. This is intended to be use as a service to translate
    passwords specified in config files, which in some time might be
    cleartext, in others obtained from services.

    >>> real_password = password_get("somearea", "rtmorris", "KEYRING")

    will query the *keyring* service for the password to use for user
    *rtmorris* on domain *somearea*.

    >>> real_password = password_get("somearea", "rtmorris", "KEYRING:Area51")

    would do the same, but *keyring*'s domain would be *Area51*
    instead.

    >>> real_password = password_get(None, "rtmorris",
    >>>                              "FILE:/etc/config/some.key")

    would obtain the password from the contents of file
    */etc/config/some.key*.

    >>> real_password = password_get("somearea", "rtmorris", "sikrit")

    would just return *sikrit* as a password.

    :param str domain: a domain to which this password operation
      applies; see below *password* (can be *None*)

    :param str user: the username for maybe obtaining a password from
      a password service; see below *password*.

    :param str password: a password obtained from the user or a
      configuration setting; can be *None*. If the *password* is

      - *KEYRING* will ask the accounts keyring for the password
         for domain *domain* for username *user*

      - *KEYRING:DOMAIN* will ask the accounts keyring for the password
         for domain *DOMAIN* for username *user*, ignoring the
         *domain* parameter.

      - *FILE:PATH* will read the password from filename *PATH*.

    :returns: the actual password to use

    Password management procedures (FIXME):

    - to set a password in the keyring::

        $ echo KEYRINGPASSWORD | gnome-keyring-daemon --unlock
        $ keyring set "USER"  DOMAIN
        Password for 'DOMAIN' in 'USER': <ENTER PASSWORD HERE>

    - to be able to run the daemon has to be executed under a dbus session::

        $ dbus-session -- sh
        $ echo KEYRINGPASSWORD | gnome-keyring-daemon --unlock
        $ ttbd...etc

    """
    assert domain == None or isinstance(domain, str)
    assert isinstance(user, str)
    assert password == None or isinstance(password, str)
    if password == "KEYRING":
        if keyring_available == False:
            raise RuntimeError(
                "keyring: functionality to load passwords not available,"
                " please install keyring support")
        password = keyring.get_password(domain, user)
        if password == None:
            raise RuntimeError("keyring: no password for user %s @ %s"
                               % (user, domain))
    elif password and password.startswith("KEYRING:"):
        if keyring_available == False:
            raise RuntimeError(
                "keyring: functionality to load passwords not available,"
                " please install keyring support")
        _, domain = password.split(":", 1)
        password = keyring.get_password(domain, user)
        if password == None:
            raise RuntimeError("keyring: no password for user %s @ %s"
                               % (user, domain))
    elif password and password.startswith("FILE:"):
        _, filename = password.split(":", 1)
        with open(filename) as f:
            password = f.read().strip()
    # fallthrough, if none of them, it's just a password
    return password


def split_user_pwd_hostname(s):
    """
    Return a tuple decomponsing ``[USER[:PASSWORD]@HOSTNAME``

    :returns: tuple *( USER, PASSWORD, HOSTNAME )*, *None* in missing fields.

    See :func:`password_get` for details on how the password is handled.
    """
    assert isinstance(s, str)
    user = None
    password = None
    hostname = None
    if '@' in s:
        user_password, hostname = s.split('@', 1)
    else:
        user_password = ""
        hostname = s
    if ':' in user_password:
        user, password = user_password.split(':', 1)
    else:
        user = user_password
        password = None
    password = password_get(hostname, user, password)
    return user, password, hostname


def url_remove_user_pwd(url):
    """
    Given a URL, remove the username and password if any::

      print(url_remove_user_pwd("https://user:password@host:port/path"))
      https://host:port/path
    """
    _url = url.scheme + "://" + url.hostname
    if url.port:
        _url += ":%d" % url.port
    if url.path:
        _url += url.path
    return _url


def field_needed(field, projections):
    """
    Check if the name *field* matches any of the *patterns* (ala
    :mod:`fnmatch`).

    :param str field: field name
    :param list(str) projections: list of :mod:`fnmatch` patterns
      against which to check field. Can be *None* and *[ ]* (empty).

    :returns bool: *True* if *field* matches a pattern in *patterns*
      or if *patterns* is empty or *None*. *False* otherwise.
    """
    if projections:
        # there is a list of must haves, check here first
        for projection in projections:
            if fnmatch.fnmatch(field, projection):
                return True	# we need this field
            # match projection a to fields a.[x.[y.[...]]]
            if field.startswith(projection + "."):
                return True
        return False		# we do not need this field
    else:
        return True	# no list, have it

def dict_to_flat(d, projections = None, sort = True, empty_dict = False):
    """
    Convert a nested dictionary to a sorted list of tuples *( KEY, VALUE )*

    The KEY is like *KEY[.SUBKEY[.SUBSUBKEY[....]]]*, where *SUBKEY*
    are keys in nested dictionaries.

    :param dict d: dictionary to convert
    :param list(str) projections: (optional) list of :mod:`fnmatch`
      patterns of flay keys to bring in (default: all)
    :param bool sort: (optional, default *True*) sort according to KEY
      name or leave the natural order (needed to keep the order of the
      dictionaries) -- requires the underlying dict to be a
      collections.OrderedDict() in older python versions.
    :returns list: sorted list of tuples *KEY, VAL*

    """
    assert isinstance(d, collections.Mapping)
    fl = []

    def _add(field_flat, val):
        if sort:
            bisect.insort(fl, ( field_flat, val ))
        else:
            fl.append(( field_flat, val ))

    # test dictionary emptiness with 'len(d) == 0' vs 'd == {}', since they
    # could be ordereddicts and stuff

    def __update_recursive(val, field, field_flat, projections = None,
                           depth_limit = 10, prefix = "  ", sort = True,
                           empty_dict = False):
        # Merge d into dictionary od with a twist
        #
        # projections is a list of fields to include, if empty, means all
        # of them
        # a field X.Y.Z means od['X']['Y']['Z']

        # GRRRR< has to dig deep first, so that a.a3.* goes all the way
        # deep before evaluating if keepers or not -- I think we need to
        # change it like that and maybe the evaluation can be done before
        # the assignment.

        if isinstance(val, collections.Mapping):
            if len(val) == 0 and empty_dict == True and field_needed(field_flat, projections):
                # append an empty dictionary; do not append VAL --
                # why? because otherwise it might be modified later by
                # somebody else and modify our SOURCE dictionary, and
                # we do not want that.
                _add(field_flat, dict())
            elif depth_limit > 0:	# dict to dig in
                for key, value in val.items():
                    __update_recursive(value, key, field_flat + "." + str(key),
                                       projections, depth_limit - 1,
                                       prefix = prefix + "    ",
                                       sort = sort, empty_dict = empty_dict)
        elif field_needed(field_flat, projections):
            _add(field_flat, val)

    if len(d) == 0 and empty_dict == True:
        # empty dict, insert it if we want them
        # append an empty dictionary; do not append VAL --
        # why? because otherwise it might be modified later by
        # somebody else and modify our SOURCE dictionary, and
        # we do not want that.
        _add(field_flat, dict())
    for key, _val in d.items():
        __update_recursive(d[key], key, key, projections, 10, sort = sort,
                           empty_dict = empty_dict)

    return fl

def _key_rep(r, key, key_flat, val):
    # put val in r[key] if key is already fully expanded (it has no
    # periods); otherwise expand it recursively
    if '.' in key:
        # this key has sublevels, iterate over them
        lhs, rhs = key.split('.', 1)
        if lhs not in r:
            r[lhs] = collections.OrderedDict()
        elif not isinstance(r[lhs], dict):
            r[lhs] = collections.OrderedDict()

        _key_rep(r[lhs], rhs, key_flat, val)
    else:
        r[key] = val

def flat_slist_to_dict(fl):
    """
    Given a sorted list of flat keys and values, convert them to a
    nested dictionary

    :param list((str,object)): list of tuples of key and any value
      alphabetically sorted by tuple; same sorting rules as in
      :func:`flat_keys_to_dict`.

    :return dict: nested dictionary as described by the flat space of
      keys and values
    """
    # maintain the order in which we add things, we depend on this for
    # multiple things later on
    tr = collections.OrderedDict()
    for key, val in fl:
        _key_rep(tr, key, key, val)
    return tr


def flat_keys_to_dict(d):
    """
    Given a dictionary of flat keys, convert it to a nested dictionary

    Similar to :func:`flat_slist_to_dict`, differing in the
    keys/values being in a dictionary.

    A key/value:

    >>> d["a.b.c"] = 34

    means:

    >>> d['a']['b']['c'] = 34

    Key in the input dictonary are processed in alphabetical order
    (thus, key a.a is processed before a.b.c); later keys override
    earlier keys:

    >>> d['a.a'] = 'aa'
    >>> d['a.a.a'] = 'aaa'
    >>> d['a.a.b'] = 'aab'

    will result in:

    >>> d['a']['a'] = { 'a': 'aaa', 'b': 'aab' }

    The

    >>> d['a.a'] = 'aa'

    gets overriden by the other settings

    :param dict d: dictionary of keys/values
    :returns dict: (nested) dictionary
    """
    tr = {}

    for key in sorted(d.keys()):
        _key_rep(tr, key, key, d[key])

    return tr


class tls_prefix_c(object):

    def __init__(self, tls, prefix):
        assert isinstance(tls, threading.local)
        assert isinstance(prefix, str)
        self.tls = tls
        # repr the prefix as bytes, so when we write there is no
        # conversion needed
        self.prefix = prefix.encode('utf-8')
        self.prefix_old = None

    def __enter__(self):
        self.prefix_old = getattr(self.tls, "prefix_c", b"")
        self.tls.prefix_c = self.prefix_old + self.prefix
        return self

    def __exit__(self, _exct_type, _exce_value, _traceback):
        self.tls.prefix_c = self.prefix_old
        self.prefix_old = None

    def __repr__(self):
        return getattr(self.tls, "prefix_c", None)


def data_dump_recursive(d, prefix = u"", separator = u".", of = sys.stdout,
                        depth_limit = 10):
    """
    Dump a general data tree to stdout in a recursive way

    For example:

    >>> data = [ dict(keya = 1, keyb = 2), [ "one", "two", "three" ], "hello", sys.stdout ]

    produces the stdout::

      [0].keya: 1
      [0].keyb: 2
      [1][0]: one
      [1][1]: two
      [1][2]: three
      [2]: hello
      [3]: <open file '<stdout>', mode 'w' at 0x7f13ba2861e0>

    - in a list/set/tuple, each item is printed prefixing *[INDEX]*

    - in a dictionary, each item is prefixed with it's key

    - strings and cardinals are printed as such

    - others are printed as what their representation as a string produces

    - if an attachment is a generator, it is iterated to gather the data.

    - if an attachment is of :class:generator_factory_c, the method
      for creating the generator is called and then the generator
      iterated to gather the data.

    See also :func:`data_dump_recursive_tls`

    :param d: data to print

    :param str prefix: prefix to start with (defaults to nothing)

    :param str separator: used to separate dictionary keys from the
      prefix (defaults to ".")

    :param :python:file of: output stream where to print (defaults to
      *sys.stdout*)

    :param int depth_limit: maximum nesting levels to go deep in the
      data structure (defaults to 10)
    """
    assert isinstance(prefix, str)
    assert isinstance(separator, str)
    assert depth_limit > 0

    if isinstance(d, dict) and depth_limit > 0:
        if prefix.strip() != "":
            prefix = prefix + separator
        for key, val in sorted(d.items(), key = lambda i: i[0]):
            data_dump_recursive(val, prefix + str(key),
                                separator = separator, of = of,
                                depth_limit = depth_limit - 1)
    elif isinstance(d, (list, set, tuple)) and depth_limit > 0:
        # could use iter(x), but don't wanna catch strings, etc
        count = 0
        for v in d:
            data_dump_recursive(v, prefix + u"[%d]" % count,
                                separator = separator, of = of,
                                depth_limit = depth_limit - 1)
            count += 1
    # HACK: until we move functions to a helper or something, when
    # someone calls the generatory factory as
    # commonl.generator_factory_c, this can't pick it up, so fallback
    # to use the name
    elif isinstance(d, generator_factory_c) \
         or type(d).__name__ == "generator_factory_c":
        of.write(prefix)
        of.writelines(d.make_generator())
    elif isinstance(d, types.GeneratorType):
        of.write(prefix)
        of.writelines(d)
    elif isinstance(d, io.IOBase):
        # not recommended, prefer generator_factory_c so it reopens the file
        d.seek(0, 0)
        of.write(prefix)
        of.writelines(d)
    else:
        of.write(prefix + u": " + mkutf8(d) + u"\n")


_dict_print_dotted = data_dump_recursive	# COMPAT

def data_dump_recursive_tls(d, tls, separator = u".", of = sys.stdout,
                            depth_limit = 10):
    """
    Dump a general data tree to stdout in a recursive way

    This function works as :func:`data_dump_recursive` (see for more
    information on the usage and arguments). However, it uses TLS for
    storing the prefix as it digs deep into the data structure.

    A variable called *prefix_c* is created in the TLS structure on
    which the current prefix is stored; this is meant to be used in
    conjunction with stream writes such as
    :class:`io_tls_prefix_lines_c`.

    Parameters are as documented in :func:`data_dump_recursive`,
    except for:

    :param threading.local tls: thread local storage to use (as returned
      by *threading.local()*
    """
    assert isinstance(separator, str)
    assert depth_limit > 0

    if isinstance(d, dict):
        for key, val in sorted(d.items(), key = lambda i: i[0]):
            with tls_prefix_c(tls, str(key) + ": "):
                data_dump_recursive_tls(val, tls,
                                        separator = separator, of = of,
                                        depth_limit = depth_limit - 1)
    elif isinstance(d, (list, set, tuple)):
        # could use iter(x), but don't wanna catch strings, etc
        count = 0
        for v in d:
            with tls_prefix_c(tls, u"[%d]: " % count):
                data_dump_recursive_tls(v, tls,
                                        separator = separator, of = of,
                                        depth_limit = depth_limit - 1)
            count += 1
    # HACK: until we move functions to a helper or something, when
    # someone calls the generatory factory as
    # commonl.generator_factory_c, this can't pick it up, so fallback
    # to use the name
    elif isinstance(d, generator_factory_c) \
         or type(d).__name__ == "generator_factory_c":
        of.writelines(d.make_generator())
    elif isinstance(d, io.IOBase):
        # not recommended, prefer generator_factory_c so it reopens the file
        d.seek(0, 0)
        of.writelines(d)
    elif isinstance(d, types.GeneratorType):
        of.writelines(d)
    else:
        of.write(mkutf8(d) + u"\n")


class io_tls_prefix_lines_c(io.BufferedWriter):
    """
    Write lines to a stream with a prefix obtained from a thread local
    storage variable.

    This is a limited hack to transform a string written as::

      line1
      line2
      line3

    into::

      PREFIXline1
      PREFIXline2
      PREFIXline3

    without any intervention by the caller other than setting the
    prefix in thread local storage and writing to the stream; this
    allows other clients to write to the stream without needing to
    know about the prefixing.

    Note the lines yielded are unicode-escaped or UTF-8 escaped, for
    being able to see in reports any special character.

    Usage:

    .. code-block:: python

       import io
       import commonl
       import threading

       tls = threading.local()

       f = io.open("/dev/stdout", "w")
       with commonl.tls_prefix_c(tls, "PREFIX"), \
            commonl.io_tls_prefix_lines_c(tls, f.detach()) as of:

           of.write(u"line1\\nline2\\nline3\\n")

    Limitations:

      - hack, only works ok if full lines are being printed

    """
    def __init__(self, tls, *args, **kwargs):
        assert isinstance(tls, threading.local)
        io.BufferedWriter.__init__(self, *args, **kwargs)
        self.tls = tls
        self.data = u""

    def __write_line(self, s, prefix, offset, pos):
        # Write a whole (\n ended) line to the stream
        #
        # - prefix first
        # - leftover data since last \n
        # - current data from offset to the position where \n was
        #   (unicode-escape encoded)
        # - newline (since the one in s was unicode-escaped)
        substr = s[offset:pos]
        io.BufferedWriter.write(self, prefix)
        if self.data:
            io.BufferedWriter.write(
                self, self.data.encode('unicode-escape'))
            self.data = ""
        io.BufferedWriter.write(self, substr.encode('unicode-escape'))
        io.BufferedWriter.write(self, "\n".encode('utf-8'))
        # flush after writing one line to avoid corruption from other
        # threads/processes printing to the same FD
        io.BufferedWriter.flush(self)
        return pos + 1

    def _write(self, s, prefix, acc_offset = 0):
        # write a chunk of data to the stream -- break it by newlines,
        # so when one is found __write_line() can write the prefix
        # first. Accumulate anything left over after the last newline
        # so we can flush it next time we find one.
        offset = 0
        if not isinstance(s, str):
            s = str(s)
        while offset < len(s):
            pos = s.find('\n', offset)
            if pos >= 0:
                offset = self.__write_line(s, prefix, offset, pos)
                continue
            self.data += s[offset:]
            break
        return acc_offset + len(s)

    def flush(self):
        """
        Flush any leftover data in the temporary buffer, write it to the
        stream, prefixing each line with the prefix obtained from
        *self.tls*\'s *prefix_c* attribute.
        """
        prefix = getattr(self.tls, "prefix_c", None)
        if prefix == None:
            io.BufferedWriter.write(
                self, self.data.encode('unicode-escape'))
        else:
            # flush whatever is accumulated
            self._write(u"", prefix)
        io.BufferedWriter.flush(self)

    def write(self, s):
        """
        Write string to the stream, prefixing each line with the
        prefix obtained from *self.tls*\'s *prefix_c* attribute.
        """
        prefix = getattr(self.tls, "prefix_c", None)
        if prefix == None:
            io.BufferedWriter.write(self, s)
            return
        self._write(s, prefix, 0)

    def writelines(self, itr):
        """
        Write the iterator to the stream, prefixing each line with the
        prefix obtained from *self.tls*\'s *prefix_c* attribute.
        """
        prefix = getattr(self.tls, "prefix_c", None)
        if prefix == None:
            io.BufferedWriter.writelines(self, itr)
            return
        offset = 0
        for data in itr:
            offset = self._write(data, prefix, offset)

def mkutf8(s):
    #
    # Python2 left over FIXME: see all the call sites and fix them
    #
    if isinstance(s, str):
        return s
    else:
        # represent it in unicode, however the object says
        return str(s)

class generator_factory_c(object):
    """
    Create generator objects multiple times

    Given a generator function and its arguments, create it when
    :func:`make_generator` is called.

    >>> factory = generator_factory_c(genrator, arg1, arg2..., arg = value...)
    >>> ...
    >>> generator = factory.make_generator()
    >>> for data in generator:
    >>>     do_something(data)
    >>> ...
    >>> another_generator = factory.make_generator()
    >>> for data in another_generator:
    >>>     do_something(data)

    generators once created cannot be reset to the beginning, so this
    can be used to simulate that behavior.

    :param fn: generator function
    :param args: arguments to the generator function
    :param kwargs: keyword arguments to the generator function
    """
    def __init__(self, fn, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def make_generator(self):
        """
        Create and return a generator
        """
        return self.fn(*self.args, **self.kwargs)

def file_iterator(filename, chunk_size = 4096):
    """
    Iterate over a file's contents

    Commonly used along with generator_factory_c to with the TCF
    client API to report attachments:

    :param int chunk_size: (optional) read blocks of this size (optional)

    >>> import commonl
    >>>
    >>> class _test(tcfl.tc.tc_c):
    >>>
    >>>   def eval(self):
    >>>     generator_f = commonl.generator_factory_c(commonl.file_iterator, FILENAME)
    >>>     testcase.report_pass("some message", dict(content = generator_f))

    """
    assert chunk_size > 0
    with io.open(filename, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

def assert_list_of_strings(l, list_name, item_name):
    assert isinstance(l, ( tuple, list )), \
        "'%s' needs to be None or a list of strings (%s); got %s" % (
            list_name, item_name, type(l))
    count = -1
    for i in l:
        count += 1
        assert isinstance(i, str), \
            "items in '%s' needs to be strings (%s); got %s on #%d"  % (
                list_name, item_name, type(i), count)

def assert_list_of_types(l, list_name, item_name, item_types):
    assert isinstance(l, list), \
        "'%s' needs to be a list of items (%s) of types '%s'; got %s" % (
            list_name, item_name,
            ",".join(type(i).__name__ for i in item_types), type(l))
    count = -1
    for i in l:
        count += 1
        assert isinstance(i, item_types), \
            "items in '%s' needs to be %s (%s); got %s on #%d"  % (
                list_name, "|".join(i.__name__ for i in item_types),
                item_name, type(i), count)

def assert_none_or_list_of_strings(l, list_name, item_name):
    if l == None:
        return
    assert_list_of_strings(l, list_name, item_name)

def assert_dict_of_strings(d, d_name):
    for k, v in d.items():
        assert isinstance(k, str), \
            "'%s' needs to be a dict of strings keyed by string;" \
            " got a key type '%s'; expected string" % (d_name, type(k))
        assert isinstance(v, str), \
            "'%s' needs to be a dict of strings keyed by string;" \
            " for key '%s' got a value type '%s'" % (d_name, k, type(v))

def assert_dict_of_ints(d, d_name):
    for k, v in d.items():
        assert isinstance(k, str), \
            "'%s' needs to be a dict of ints keyed by string;" \
            " got a key type '%s'; expected string" % (d_name, type(k))
        assert isinstance(v, int), \
            "'%s' needs to be a dict of ints keyed by string;" \
            " for key '%s' got a value type '%s'" % (d_name, k, type(v))

def assert_none_or_dict_of_strings(d, d_name):
    if d == None:
        return
    assert_dict_of_strings(d, d_name)

#: List of known compressed extensions and ways to decompress them
#: without removing the input file
#:
#: To add more:
#:
#: >>> commonl.decompress_handlers[".gz"] = "gz -fkd"
decompress_handlers = {
    # keep compressed files
    ".gz": "gz -fkd",
    ".bz2": "bzip2 -fkd",
    ".xz": "xz -fkd",
}

def file_is_compressed(filename):
    assert isinstance(filename, basestring)
    basename, ext = os.path.splitext(filename)
    if ext not in decompress_handlers:	# compressed logfile support
        return filename, None
    return basename, ext

def maybe_decompress(filename, force = False):
    """
    Decompress a file if it has a compressed file extension and return
    the decompressed name

    If the decompressed file already exists, assume it is the
    decompressed version already and do not decompress.

    :param str filename: a filename to maybe decompress

    :params bool force: (optional, default *False*) if *True*,
      decompress even if the decompressed file already exists

    :returns str: the name of the file; if it was compressed. If it
      is *file.ext*, where *ext* is a compressed file extension, then
      it decompresses the file to *file* and returns *file*, without
      removing the original *file.ext*.

    The compressed extensions are registered in
    :data:`decompress_handlers`.

    """
<<<<<<< HEAD
    assert isinstance(filename, str)
    basename, ext = os.path.splitext(filename)
    if ext not in decompress_handlers:	# compressed logfile support
=======
    assert isinstance(filename, basestring)
    basename, ext = file_is_compressed(filename)
    if not ext:	# compressed logfile support
>>>>>>> b75b6f07d7f931acb2da3320032515a2fe7db0cf
        return filename
    if force or not os.path.exists(basename):
        # FIXME: we need a lock in case we have multiple
        # processes doing this
        command = decompress_handlers[ext]
        subprocess.check_call(command.split() + [ filename ],
                              stdin = subprocess.PIPE)
    return basename


class dict_lru_c:
    """
    Way simple LRU dictionary with maximum size

    When getting, the entries get removed, so it kinda works like a FIFO

    :param int max_size: maximum number of entries in the dictionary;
      when putting a new one, older entries will be removed.
    """

    def __init__(self, max_size):
        assert isinstance(max_size, int)
        self.max_size = max_size
        self.cache = dict()


    def set(self, key, value):
        self.cache[key] = ( value, time.time() )
        if len(self.cache) > self.max_size:
            # lame LRU purge
            ts_earliest = time.time()
            key_earliest = None
            for key, ( value, ts ) in self.cache.items():
                if ts < ts_earliest:
                    ts_earliest = ts
                    key_earliest = key
            # there has to be one, otherwise, how did we get here past
            # the len check?
            del self.cache[key_earliest]

    def get_and_remove(self, key, default = None):
        """
        Get a value for a key

        Note this is a destructive get; we can get it only once and
        then it is deleted.
        """
        value, ts = self.cache.pop(key, ( None, None ) )
        return value
