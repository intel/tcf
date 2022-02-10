#! /usr/bin/python3
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
import fnmatch
import functools
import glob
import hashlib
import imp
import importlib
import io
import inspect
import json
import logging
import numbers
import os
import random
import re
import signal
import shutil
import socket
import string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types

import filelock
import requests

import urllib.parse

debug_traces = False

if False:
    # disabling all this until we have a proper fix for the import
    # mess they keyring package has
    try:
        import keyring
        keyring_available = True
    except ImportError as e:
        logging.warning("can't import keyring, functionality disabled")
        keyring_available = False
else:
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
        if debug_traces:
            logging.exception("%s: can't load config file: %s", filename, e)
        else:
            logging.error("%s: can't load config file: %s", filename, e)
        if raise_on_fail:
            raise

def path_expand(path_list):
    # Compose the path list
    _list = []
    for _paths in path_list:
        paths = _paths.split(os.pathsep)
        for path in paths:
            if path == "":
                _list = []
            else:
                _list.append(os.path.expanduser(path))
    return _list

def config_import(path_list, file_regex, namespace = "__main__",
                  raise_on_fail = True, imported_files = None):
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
                config_file_path = os.path.join(path, filename)
                config_import_file(config_file_path, namespace,
                                   raise_on_fail = raise_on_fail)
                if imported_files != None:
                    imported_files.append(config_file_path)
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
        return 0
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
        who = frame.f_code.co_name + "__%d" % frame.f_lineno
    if tag != "":
        tag += "-"
    if cls != None:
        clstag = cls.__name__ + "."
    else:
        clstag = ''
    # can't use tempfile.NamedTemporaryFile bc then Windows doesn't
    # let us opent it again
    return open(
        os.path.join(
            directory,
            os.path.basename(sys.argv[0]) + "__" + clstag + who + "-" + tag
            + f"{random.randrange(0, 100000):05d}"
            + suffix
        ),
        "w+b",
        bufsize
    )

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


def kws_expand(s: str, kws: dict, nest_limit: int = 5):
    """
    Expand a template string with a dictionary

    This is a version of *s % kws* that works recursively and supports
    templates in the keys too.

    Eg:

    >>> kws_expand('a simple %(field)s substitution', dict(field = "field"))
    'a simple field substitution'

    >>> kws_expand('a nested %(nested_field)s substitution',
    ...            dict(nested_field = "field", field = 'nested field'))
    'a nested field substitution'

    >>> kws_expand('a key %(nested_%(key)s_field)s substitution',
    ...            dict(nested_key_field = "%(field)s", field = 'nested field', key = "key"))
    'a key nested field substitution'

    :param str s: templated string to expand; if it contains no
      *%(FIELD)* templates, it won't be templated.

      To include a *%(* chacter sequence that is not expanded, you
      need to double the percentage sign as in *%%(*, understanding
      that for every level of nested templating done you will need to
      double them.

    :param dict kws: Dictionary keyed by strings of values to
      template.

    :param int nest_limit: (optional; default 5) how many iterations
      are done when trying to expand all templates before giving up.

    :raises KeyError: if a template field is not available

      To have missing fields expanded with a default value, pass a
      argument to *kws* a :class:`commonl.dict_missing_c`, a
      dictionary that returns pre-defined strings for missing keys.

    :raises RecursionError: if the nest limit is exceeded

    :return str: string with the template fields expanded
    """
    assert isinstance(s, str), \
        f"s: expected str; got {type(s)}"
    if kws != None:
        assert_dict_key_strings(kws, 'kws')
    assert isinstance(nest_limit, int) and nest_limit >= 1, \
        f"nest_limit: expected int <= 1; got {type(nest_limit)} {nest_limit}"

    if not kws:		# nothing to template
        return s

    # template until there are no %( or we are 86ed
    _s = s
    for _count in range(nest_limit+1):
        try:
            if '%(' not in _s:
                break
            _s = _s % kws
        except KeyError as e:
            # missing key?
            key = e.args[0]
            if '%(' in key:
                # this is a templated key, eg someone did:
                #
                # >>> "this string %(field1.%(field2)s.whatever)s ..."
                #
                # so first make "this string %(field1.VALUE2.whatever)s"
                # and then "this string VALUE3"
                _s = _s.replace(key, key % kws)
                continue
            raise KeyError(
                f"configuration error? missing field '{key}' in "
                f"template string '{s}'") from e
    else:
        raise RecursionError(
            f"configuration error? nest limit is {nest_limit} and"
            f" templates not all resolved for template '{s}'")
    return _s


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

def verify_str_safe(s, safe_chars = None, do_raise = True, name = "string"):
    """
    Raise an exception if string contains unsafe chars

    :param str s: string to check
    :param str safe_chars: (optional) list/set of valid chars
      (defaults to ASCII letters, digits, - and _)
    """
    assert isinstance(s, str), \
        f"{name}: got a {type(s)}; expected a string"

    if safe_chars == None:
        safe_chars = set('-_' + string.ascii_letters + string.digits)
    s_set = set(s)
    s_unsafe = s_set - s_set.intersection(safe_chars)
    if not do_raise:
        return not s_unsafe
    assert not s_unsafe, \
        f"{name}: contains invalid characters: {''.join(s_unsafe)}" \
        f" (valid are: {''.join(safe_chars)})"
    return None		# keep pylint happy


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


class fs_cache_c():
    """
    Very simple disk-based cache

    Note this is multiprocess using a file-based lock (ssee
    :module:`filelock`):

    >>> with self.lock():
    >>>    self.get_unlocked()

    """
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        # don't call from initialization, only once we start using it
        # in earnest
        self.cache_lockfile = os.path.join(
            self.cache_dir, "lockfile")
        self.fsdb = fsdb_c.create(self.cache_dir)

    def lock(self):
        return filelock.FileLock(self.cache_lockfile)

    def set_unlocked(self, field, value):
        self.fsdb.set(field, value)

    def set(self, field, value):
        with self.lock():
            self.fsdb.set(field, value)

    def get_unlocked(self, field, default = None):
        return self.fsdb.get(field, default)

    def get(self, field, default = None):
        with self.lock():
            return self.fsdb.get(field, default)

    def lru_cleanup_unlocked(self, max_entries):
        """
        Delete the oldest in a list of entries that are used as a cache
        until only *max_entries* are left

        :param int max_entries: maximum number of entries which should be
          left

        """
        assert isinstance(max_entries, int) and max_entries > 0

        mtimes_sorted_list = []
        mtimes = {}

        for path, _dirs, filenames in os.walk(self.cache_dir):
            # note there should be no subdirs we care for because it's
            # asingle level
            for filename in filenames:
                if filename == "lockfile":
                    continue
                filepath = os.path.join(path, filename)
                mtime = self.fsdb._raw_stat(filepath).st_mtime
                mtimes[mtime] = filepath
                bisect.insort(mtimes_sorted_list, mtime)
            break	# only one directory level

        clean_number = len(mtimes_sorted_list) - max_entries
        if clean_number < 0:
            return
        for mtime in mtimes_sorted_list[:clean_number]:
            rm_f(mtimes[mtime])




_hash_sha512 = hashlib.sha512()

def _hash_file_cached(filepath, digest, cache_path, cache_entries):
    # stat info happens to be iterable, ain't that nice
    filepath_stat_hash = mkid(
        digest + filepath + "".join([ str(i) for i in os.stat(filepath) ]),
        l = 48)
    # if there is no cache location, use our preset in the user's home dir
    if cache_path == None:
        cache_path = os.path.join(
            os.path.expanduser("~"), ".cache", "file-hashes")
    makedirs_p(cache_path)
    cache = fs_cache_c(cache_path)
    with cache.lock():
        cache.lru_cleanup_unlocked(cache_entries)
        value = cache.get_unlocked(filepath_stat_hash)
        # we have read the value, so now we remove the entry and
        # if it is "valid", we recreate it, so the mtime is
        # updated and thus an LRU cleanup won't wipe it.
        # FIXME: python3 just update utime
        if value and isinstance(value, str) \
           and len(value) == 2 * _hash_sha512.digest_size:
            cache.set_unlocked(filepath_stat_hash, value)
            return value
        hoc = hash_file(hashlib.new(digest), filepath, blk_size = 8192)
        cache.set_unlocked(filepath_stat_hash, hoc.hexdigest())
        return hoc.hexdigest()


def hash_file_cached(filepath, digest,
                     cache_path = None, cache_entries = 1024):
    """
    Hash file contents and keep them in a cache in
    *~/.cache/file-hashes*.

    Next time the same file is being cached, use the cache entries (as
    long as the filepath is the same and the os.stat() signature
    doesn't change).

    :param str filepath: path to the file to hash

    :param str digest: digest to use; anything :mod:`python.hashlib` supports

    :param str cache_path: (optional; default
      *~/.cache/file-hashes*) path where
      to store the cached hashes.

    :param int cache_entries: (optional; default *1024*) how many
      entries to keep in the cache; old entries are removed to give way
      to frequently used entries or new ones (LRU).

    :returns str: hex digest

    """
    # If we have a cache
    tries_max = 10
    tries = 0
    while tries < tries_max:
        try:
            return _hash_file_cached(filepath, digest,
                                     cache_path, cache_entries)
        except FileExistsError as e:
            # ops? tried to create a cache entry and found it already
            # is there? ok, retry in case *our* version is better
            # because the file has been updated...but if we had tried
            # 10 times, bail
            if tries >= tries_max:
                raise
            tries += 1


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
        cache = fs_cache_c(cache_path)
        with cache.lock():
            cache.lru_cleanup_unlocked(cache_entries)
            value = cache.get_unlocked(hexdigest_compressed)
            # we have read the value, so now we remove the entry and
            # if it is "valid", we recreate it, so the mtime is
            # updated and thus an LRU cleanup won't wipe it.
            # FIXME: python3 just update utime
            cache.set_unlocked(hexdigest_compressed, None)
            # basic verification, it has to look like the hexdigest()
            if value and len(value) == len(hoc.hexdigest()):
                # recreate it, so that the mtime shows we just used it
                # and LRU will keep it around
                cache.set_unlocked(hexdigest_compressed, value)
                return value

    # ok, we have to decompress and set a hash
    # note we relesae the lock, as this might take time

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
    if sys.platform in ( 'linux', 'macos' ):
        os.symlink(os.path.abspath(filepath), filename_tmp_compressed)
    else:
        # sigh Windows and symlinks...
        shutil.copyfile(os.path.abspath(filepath), filename_tmp_compressed)
    filename_tmp = None
    try:
        filename_tmp = maybe_decompress(filename_tmp_compressed)
        ho = hash_file(hash_object, filename_tmp)
    finally:
        if filename_tmp:
            rm_f(filename_tmp)
        rm_f(filename_tmp_compressed)
        if tmpdir_delete:
            os.rmdir(tmpdir)

    if cache_entries:
        cache.set(hexdigest_compressed, ho.hexdigest())

    return ho.hexdigest()


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

    ts = os.get_terminal_size()
    if len(msg) < ts.columns:
        w_len = ts.columns - len(msg)
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


def verify_timeout(what:str, timeout: float,
                   verify_f: callable, *verify_args,
                   poll_period: float = 0.25, log = logging,
                   **verify_kwargs):
    """
    Verify a condition is met before a certain timeout

    :param str what: short description of what is being verified

    :param float timeout: how long to wait for; has to be at least
      twice the poll period.

    :param callable verify_f: function to call to verify; must return
      something that evaluates to boolean *True* when ok, otherwise it
      is considered not ok.

    :param float poll_period: (optional, default 0.25s) period on
      which to call the verification function

    :param log: logger to use to report messages with INFO level.

    Any other arguments (*\*args* and *\*\*kwargs*) are passed to the
    verification function.
    """
    assert isinstance(what, str), \
        f"what: expected a description string; got {type(what)}"
    assert isinstance(timeout, numbers.Real) and timeout > 0, \
        f"timeout: expected a positive number; got {type(timeout)}"
    assert callable(verify_f), \
        f"verify_f: expected a callable; got {type(verify_f)}"
    assert isinstance(poll_period, numbers.Real) and poll_period > 0, \
        f"poll_period: expected a positive number; got {type(poll_period)}"
    assert poll_period < timeout/2, \
        f"poll_period: expected a lower than half the timeout"
    assert hasattr(log, "info"), \
        f"log: expected logging object; got {type(log)}"

    t0 = t = time.time()
    while True:
        if t - t0 > timeout:
            log.info(
                f"{what}: verifying with {verify_f} timed out at"
                f" +{t-t0:.1f}/{timeout}s")
            raise TimeoutError(f"{what}: timedout at +{t-t0:.1f}/{timeout}s")
        if verify_f(*verify_args, **verify_kwargs):
            log.info(
                f"{what}: verified with {verify_f} at +{t-t0:.1f}/{timeout}s")
            return
        time.sleep(poll_period)		# Give it .1s to come up
        t = time.time()
    assert()


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
                      use_signal = signal.SIGTERM,
                      path = None, wait_to_kill = 0.25):
    """Terminate a process (TERM and KILL after 0.25s)

    :param pid: PID of the process to kill; this can be an
      integer, a string representation of an integer or a path to a
      PIDfile.

    :param str pidfile: (optional) pidfile to remove [deprecated]

    :param str path: (optional) path to the binary

    :param str tag: (optional) prefix to error messages

    :param int use_signal: (optional; default SIGTERM) signal to send
      to stop the process (see signal.SIG*).
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
        signal_name = str(use_signal)
        os.kill(_pid, use_signal)
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
            log.debug("%s: no %s PID yet (+%.2f/%ss), re-checking",
                      tag, path, t - t0, timeout)
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
            cwd = _srcdir, stderr = subprocess.STDOUT, encoding = 'utf-8')
        # RPM versions can't have dash (-), so use underscores (_)
        return git_version.strip().replace("-", ".")
    except subprocess.CalledProcessError as _e:
        print("Unable to determine %s (%s) version: %s"
              % (name, _srcdir, _e.output), file = sys.stderr)
        return "vNA"
    except OSError as e:
        # At this point, logging is still not initialized; don't
        # crash, just report a dummy version
        print("Unable to determine %s (%s) version "
              " (git not installed?): %s" % (name, _srcdir, e),
              file = sys.stderr)
        return "vNA"

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

def ttbd_locate_helper(filename, share_path, log = logging, relsrcpath = ""):
    """
    Find the path to a TTBD file, depending on we running from source
    or installed system wide.

    :param str filename: name of the TTBD file we are looking for.
    :param str share_path: path where share data will be installed
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
    cmd_path = os.path.join(share_path, filename)
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
ansi_regex = re.compile(r'\x1b\[\d+(;\d+){0,2}m')

def ansi_strip(s):
    """
    Strip ANSI sequences from a string

    :param str s: string to strip ANSI sequences from
    :returns s: ANSI-stripped string
    """
    return ansi_regex.sub('', s)


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
        return "%s_UNDEFINED_TEMPLATE.%s" % (key, origin_fn_get(2, "."))

def ipv4_len_to_netmask_ascii(length):
    return socket.inet_ntoa(struct.pack('>I', 0xffffffff ^ ((1 << (32 - length) ) - 1)))

#: Simple general keyring redirectory
#:
#: Any configuration file can add entries to this dictionary, that
#: then can be used by password_lookup() to find passwords when not
#: specified and needed.
#:
#: This is mainly used when passwords will be shared in different
#: parts of the infrastructure and it is easier to refer to them from
#: central location.
passwords = {
    # Simple match username/hostname to password
    #"billy@thismachine.com": "badS3cre7",

    # Match a regular expression for account/hostname to a password
    # located in a file that password_get() will reead
    #re.compile("admin@r[0-9]+p[0-9]+..*.deacluster.intel.com"): \
    #    "FILE:/etc/ttbd-production/pwd.pdu.admin",

}

def password_lookup(entry):
    for entry_r, value in passwords.items():
        if isinstance(entry_r, str) and entry_r == entry:
            return value
        elif isinstance(entry_r, re.Pattern):
            m = entry_r.search(entry)
            if not m:
                continue
            if '%(' in value:
                value = value % m.groupdict()
            return value
        raise RuntimeError(f"can't find a password for entry '{entry}'")



def password_get(domain, user, password):
    """Get the password for a domain and user

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

      - *KEYRING=DOMAIN* (or *KEYRING:DOMAIN*) will ask the accounts
        keyring for the password for domain *DOMAIN* for username
        *user*, ignoring the *domain* parameter.

      - *FILE=PATH* (or *FILE:PATH*) will read the password from
        filename *PATH*.

      Note that using the colon notation *FILE:PATH* can make some URL
      parsing not work, hence you can default to using =

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
    elif password and password.startswith("KEYRING="):
        if keyring_available == False:
            raise RuntimeError(
                "keyring: functionality to load passwords not available,"
                " please install keyring support")
        _, domain = password.split("=", 1)
        password = keyring.get_password(domain, user)
        if password == None:
            raise RuntimeError("keyring: no password for user %s @ %s"
                               % (user, domain))
    elif password and password.startswith("FILE:"):
        _, filename = password.split(":", 1)
        with open(filename) as f:
            password = f.read().strip()
    elif password and password.startswith("FILE="):
        _, filename = password.split("=", 1)
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
                        depth_limit = 20):
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

    - if an attachment is of :class:`generator_factory_c`, the method
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
    assert depth_limit > 0, f"depth_limit: expected >0, got {depth_limit}"

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
        #   (we print them escaping non-visible chars)
        # - newline (since the one in s was escaped)
        substr = s[offset:pos]
        io.BufferedWriter.write(self, prefix)
        if self.data:
            io.BufferedWriter.write(
                self, str_invisible_escape(self.data).encode('utf-8'))
            self.data = ""
        io.BufferedWriter.write(self, str_invisible_escape(substr).encode('utf-8'))
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
                self, str_invisible_escape(self.data).encode('utf-8'))
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
        data = None	# itr might be empty...and later we want to check
        for data in itr:
            offset = self._write(data, prefix, offset)
        if data:
            # if there was an iterator (sometimes we are called with
            # an empty one), if the last char was not a \n, the last
            # line won't be flushed, so let's flush it manually.
            # This is quite hackish but heck...otherwise there will be
            # leftovers in self.data and will accumulate to the next
            # line printed, that might have nothing to do with it.
            last_char = data[-1]
            if last_char != '\n':
                self._write("\n", prefix, 0)

def mkutf8(s):
    #
    # Python2 left over FIXME: see all the call sites and fix them
    #
    if isinstance(s, str):
        return s
    else:
        # represent it in unicode, however the object says
        return str(s)

#: Index of ASCII/Unicode points to be translated because they are
#: invisible by :func:`str_invisible_escape`.
str_invisible_table = [
    "\0",       #  0
    "<SOH>",    #  1
    "<\\x02|Ctrl-B>",    #  2
    "<ETX>",    #  3
    "<EOT>",    #  4
    "<ENQ>",    #  5
    "<ACK>",    #  6
    "\\a",       #  7
    "\\b",       #  8
    "\\t",       #  9
    "\\n",       #  10
    "\\v",       #  11
    "\\f",       #  12
    "\\r",       #  13
    "<SO>",     #  14
    "<SI>",     #  15
    "<DLE>",    #  16
    "<DC1>",    #  17
    "<DC2>",    #  18
    "<DC3>",    #  19
    "<DC4>",    #  20
    "<NAK>",    #  21
    "<SYN>",    #  22
    "<ETB>",    #  23
    "<CAN>",    #  24
    "<EM>",     #  25
    "<SUB>",    #  26
    "<ESC>",    #  27
    "<FS>",     #  28
    "<GS>",     #  29
    "<RS>",     #  30
    "<US>",     #  31
]

def str_invisible_escape(s):
    """
    Translate invisible characters into visible representations

    For example, if a string contains new line characters, they are
    replaced with *\\n*, or \0x30 with *<RS>*; translation table is
    defined by :data:`str_invisible_table`.

    :param str s: string to work on

    :returns str: translated string
    """
    if isinstance(s, bytes):
        _s = bytearray()
        for b in s:
            if b >= 0 and b < 0x20:	# printable chars
                _s.extend(bytes(str_invisible_table[b], 'ascii'))
            else:
                _s.append(b)
    else:
        _s = ""
        for c in s:
            b = ord(c)
            if b >= 0 and b < 0x20:	# printable chars
                c = str_invisible_table[b]
            _s += c
    return _s


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

    def __call__(self):
        """
        Create and return a generator
        """
        return self.fn(*self.args, **self.kwargs)

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

def assert_dict_key_strings(d, d_name):
    """
    Assert a dictionary is keyed by strings
    """
    for k in d:
        assert isinstance(k, str), \
            "'%s' needs to be a dict keyed by string;" \
            " got a key type '%s'; expected string" % (d_name, type(k))

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

macaddr_regex = re.compile(
    "(?P<n0>[0-9a-fA-F][0-9a-fA-F])"
    ":(?P<n1>[0-9a-fA-F][0-9a-fA-F])"
    ":(?P<n2>[0-9a-fA-F][0-9a-fA-F])"
    ":(?P<n3>[0-9a-fA-F][0-9a-fA-F])"
    ":(?P<n4>[0-9a-fA-F][0-9a-fA-F])"
    ":(?P<n5>[0-9a-fA-F][0-9a-fA-F])",
    re.IGNORECASE
)


def assert_macaddr(macaddr):
    assert macaddr_regex.match(macaddr) != None, \
        "invalid MAC address, has to match HH:HH:HH:HH:HH:HH," \
        " H being a hex digit"


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
    assert isinstance(filename, str)
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
    assert isinstance(filename, str)
    basename, ext = file_is_compressed(filename)
    if not ext:	# compressed logfile support
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

def cmdline_str_to_value(value):
    """
    Given a string describing a value from the command line, convert
    it to an scalar

    :params str value: value as read from the command line in the
      format *[FORMAT:]VALUE*, format being **i** for integer, **f**
      for float, **s** for string, **b** for bool; examples::

        i:33
        i:-33
        i:+33
        f:3.2
        f:-3.2
        f:+3.2
        b:true
        b:false
        s:somestring
        somestring

    :returns: value as int, float, bool or string
    """
    if value.startswith("i:"):
        return int(value[2:])
    if value.startswith("f:"):
        return float(value[2:])
    if value.startswith("b:"):
        val = value[2:]
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
        raise ValueError("value %s: bad boolean '%s' (true or false)"
                         % (value, val))
    if value.startswith("s:"):
        # string that might start with s: or empty
        return value[2:]
    return value

def str_cast_maybe(s):
    """
    If given a bytes string, convert to UTF-8; otherwise pass as is

    :param s: string of any type; if bytes, it will be encoded.
    :returns str: converted string
    """
    if isinstance(s, bytes):
        s.encode('utf-8')
    return s

def str_bytes_cast(s, like):
    """
    Convert a string (bytes or str) to be the same type as another one
    using UTF-8

    :param s: string or bytes to convert
    :param str|bytes|type like: another string (str or bytes) to serve
      as the destination type; can also be a type
    :returns: *s* converted into the same type as *like* using UTF-8
    """
    assert isinstance(s, (str, bytes))
    if isinstance(like, type):
        assert like in (str, bytes)
        dest_type = like
    else:
        assert isinstance(like, (str, bytes))
        dest_type = type(like)
    if isinstance(s, str):		# s is str
        if dest_type == str:	# like is is str, so nthing
            return s
        return s.encode('utf-8')	# ...like is bytes, encode s to bytes
    if dest_type == bytes:	    	# s is bytes
        return s		        # like is bytes, so nothing
    return s.decode('utf-8')		# ... like is str, so decode s to str


def removeprefix(s, prefix):
    """
    Remove a prefix from a string

    :param s: string
    :param prefix: prefix to remove
    :returns: the string with the prefix removed
    """
    if hasattr(s, "removeprefix"):
        # python >= 3.9
        return s.removeprefix(prefix)
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


class late_resolve_realpath(str):
    """
    Given a file (symlink or others), resolve it to the file it points
    to when we are trying to use it.

    :param str name: file path

    When converting to a string (and only when doing that) the file
    will be resolved to what it is (eg: symlinks will be resolved,
    etc).
    """
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return os.path.realpath(self.name)


def _sysfs_read(filename):
    try:
        with open(filename) as fr:
            return fr.read().strip()
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise


class late_resolve_usb_path_by_serial(str):
    """
    Given a USB serial number, resolve it to a USB path only when we
    are trying to use it.

    :param str serial_number: USB Serial Number

    When converting to a string (and only when doing that) it will be
    resolved to a USB path. If no such USB device is present, *None*
    will be returned; otherwise, something like:

      */sys/bus/usb/devices/1-3.4.3.4*
    """
    def __init__(self, serial_number):
        assert isinstance(serial_number, str)
        self.serial_number = serial_number

    def __str__(self):
        # Look for the serial number, kinda like:
        #
        ## $ grep -r YK18738 /sys/bus/usb/devices/*/serial
        ## /sys/bus/usb/devices/1-3.4.3.4/serial:YK18738
        for fn_serial in glob.glob("/sys/bus/usb/devices/*/serial"):
            serial = _sysfs_read(fn_serial)
            if serial == self.serial_number:
                devpath = os.path.dirname(fn_serial)
                if not os.path.isdir(devpath):
                    break
                return devpath

        return None


def rpyc_connection(hostname = None, port = None,
                    username = None, password = None,
                    spec = None,
                    mode: str = None, tag = None):
    """
    :param str mode: (optional, default *ssh*) connection mode:

      - zerodeploy
      - ssh
      - direct

      if *None*, defaults to what the environment variables
      RPYC_<TAG>_MODE or RPYC_MODE say, otherwise defaults to *ssh*.

    System Setup
    ^^^^^^^^^^^^

    Python packages needed:

    - rpyc
    - plumbum
    - paramiko

    Tips
    ^^^^

    https://rpyc.readthedocs.io/en/latest/docs/howto.html

    Redirecting remote's stdout and stderr locally

    >>> import sys
    >>> c.modules.sys.stdout = sys.stdout
    >>> c.execute("print('Hello World')")

    TODO/FIXME
    ^^^^^^^^^^

    - use ttbd as a tunnel provider and the TCF cookie

    - implement USERNAME:PASSWORD@HOSTNAME:PORT

      how to spec the SSH port vs the RPYC port?
    """
    # fake lazy import
    try:
        import rpyc
        import rpyc.utils.zerodeploy
        import rpyc.core.stream
        import plumbum.machines.paramiko_machine
        import plumbum
    except ImportError:
        tcfl.tc.tc_global.report_blck(
            "MISSING MODULES: install them with:"
            " pip install --user plumbum rpyc")
        raise

    assert hostname == None or isinstance(hostname, str)
    if mode == None:
        mode = os.environ.get("RPYC_MODE", "ssh")
    assert mode in ( "zerodeploy", "ssh", "direct" )

    spec = ""
    if not hostname:
        hostname = "localhost"
    if not username:
        username = os.environ.get('RPYC_USERNAME', None)
    if username:
        spec += username + "@"
    spec += hostname
    if port:
        spec += ":" + str(port)
    if not password:
        password = os.environ['RPYC_SSHPASS']

    if mode == "zerodeploy":
        machine = plumbum.machines.paramiko_machine.ParamikoMachine(
            hostname, user = username, password = password)
        server = rpyc.utils.zerodeploy.DeployedServer(machine)
        connection = server.classic_connect()
    elif mode == "ssh":
        machine = plumbum.machines.paramiko_machine.ParamikoMachine(
            hostname, user = username, password = password)
        # ParamikoMachine has no tunnel, so use a stram -- copied
        # from rpyc.utils.zerodeploy
        connection = rpyc.utils.classic.connect_stream(
            rpyc.core.stream.SocketStream(machine.connect_sock(port)))
    elif mode == "connect":
        # passwordless
        connection = rpyc.classic.connect(hostname, port = port)
    else:
        assert()
    return connection


def rpyc_compress_dnload_file(remote, remote_name, local_name = None):
    try:
        # fake lazy import
        import rpyc.utils.classic
    except ImportError:
        tcfl.tc.tc_global.report_blck(
            "MISSING MODULES: install them with:"
            " pip install --user plumbum rpyc")
        raise
    if local_name == None:
        local_name = remote_name + ".xz"
    # Compress the file to download it (way faster!)
    remote_subprocess = remote.modules['subprocess']
    remote_subprocess.run([ "xz", "-9f", remote_name ])
    rpyc.utils.classic.download(remote,
                                remote_name + ".xz",
                                local_name)

def buildah_image_create(image_name, dockerfile_s, maybe = True,
                         timeout = 20, capture_output = True):
    """
    Build a container image using buildah

    :returns bool: *True* if the image was built, *False* if not
      because it already existed

    FIXME: add --annotation cfg_hash so we can always refresh them
    based on the config file -> if it changes
    """
    if maybe:
        # since this can take a while, if we see it already exists, we
        # don't redo it
        p = subprocess.run([ "buildah", "images", "--format", "{{.Name}}" ],
                           capture_output = True, check = True, timeout = 5,
                           text = 'utf-8')
        if image_name in p.stdout:
            return False

    with tempfile.NamedTemporaryFile() as f:
        # see ttbl.power.daemon_c
        f.write(dockerfile_s.encode('utf-8'))
        f.flush()
        subprocess.run(
            [
                "buildah", "bud", "-f", f.name, "-t", image_name,
            ], check = True, capture_output = capture_output, text = 'utf-8',
            timeout = timeout)
        return True


class fsdb_c(object):
    """
    This is a very simple key/value flat database

    - sets are atomic and forcefully remove existing values
    - values are just strings
    - value are limited in size to 1K
    - if a field does not exist, its value is *None*

    The key space is flat, but with a convention of periods dividing
    fields, so that:

      l['a.b.c'] = 3

    is the equivalent to:

      l['a']['b']['c'] = 3

    it also makes it way faster and easier to filter for fields.

    This will be used to store data for each target; for implemntation
    examples, look at :class:`commonl.fsdb_symlink_c`.
    """
    class exception(Exception):
        pass

    def keys(self, pattern = None):
        """
        List the fields/keys available in the database

        :param str pattern: (optional) pattern against the key names
          must match, in the style of :mod:`fnmatch`. By default, all
          keys are listed.

        :returns list: list of keys
        """
        raise NotImplementedError

    def get_as_slist(self, *patterns):
        """
        Return a sorted list of tuples *(KEY, VALUE)*\s available in the
        database.

        :param list(str) patterns: (optional) list of patterns of fields
          we must list in the style of :mod:`fnmatch`. By default, all
          keys are listed.

        :returns list(str, str): list of *(KEY, VALUE)* sorted by
          *KEY* (so *a.b.c*, representing *['a']['b']['c']* goes
          after *a.b*, representing *['a']['b']*).
        """
        raise NotImplementedError

    def get_as_dict(self, *patterns):
        """
        Return a dictionary of *KEY/VALUE*\s available in the
        database.

        :param str pattern: (optional) pattern against the key names
          must match, in the style of :mod:`fnmatch`. By default, all
          keys are listed.

        :returns dict: keys and values in dictionary form
        """
        raise NotImplementedError

    def set(self, key, value, force = True):
        """
        Set a value for a key in the database unless *key* already exists

        :param str key: name of the key to set

        :param str value: value to store; *None* to remove the field;
          only *string*, *integer*, *float* and *boolean* types

        :parm bool force: (optional; default *True*) if *key* exists,
          force the new value

        :return bool: *True* if the new value was set correctly;
          *False* if *key* already exists and *force* is *False*.
        """
        assert isinstance(value, (NoneType, str, int, float, bool)), \
            f"value must be None, str, int, float, bool; got {type(value)}"


    def get(self, key, default = None):
        """
        Return the value stored for a given key

        :param str key: name of the key to retrieve

        :param str default: (optional) value to return if *key* is not
          set; defaults to *None*.

        :returns str: value associated to *key* if *key* exists;
          otherwise *default*.
        """
        raise NotImplementedError

    @staticmethod
    def create(cache_dir):
        """
        Create with the right type for the host OS

        Same params as :class:`fsdb_symlink_c`

        Note there are catchas for atomicity; read the docs for:

        - :class:`fsdb_symlink_c`
        - :class:`fsdb_file_c`
        """
        if sys.platform in ( 'linux', 'macos' ):
            return fsdb_symlink_c(cache_dir)
        else:
            return fsdb_file_c(cache_dir)


class fsdb_symlink_c(fsdb_c):
    """
    This implements a database by storing data on the destination
    argument of a Unix symbolic link

    Creating a symlink, takes only one atomic system call, which fails
    if the link already exists. Same to read it. Thus, for small
    values, it is very efficient.
    """
    class invalid_e(fsdb_c.exception):
        pass

    def __init__(self, dirname, use_uuid = None, concept = "directory"):
        """
        Initialize the database to be saved in the give location
        directory

        :param str location: Directory where the database will be kept
        """
        if not os.path.isdir(dirname):
            raise self.invalid_e("%s: invalid %s"
                                 % (os.path.basename(dirname), concept))
        if not os.access(dirname, os.R_OK | os.W_OK | os.X_OK):
            raise self.invalid_e("%s: cannot access %s"
                                 % (os.path.basename(dirname), concept))

        if use_uuid == None:
            self.uuid = mkid(str(id(self)) + str(os.getpid()))
        else:
            self.uuid = use_uuid

        self.location = dirname

    def _raw_valid(self, location):
        return os.path.islink(location)

    def _raw_read(self, location):
        return os.readlink(location)

    def _raw_write(self, location, value):
        os.symlink(value, location)

    def _raw_unlink(self, location):
        os.unlink(location)

    def _raw_rename(self, location_new, location):
        os.replace(location_new, location)

    @staticmethod
    def _raw_stat(location):
        return os.lstat(location)

    def keys(self, pattern = None):
        l = []
        for _rootname, _dirnames, filenames_raw in os.walk(self.location):
            filenames = []
            for filename_raw in filenames_raw:
                # need to filter with the unquoted name...
                filename = urllib.parse.unquote(filename_raw)
                if pattern == None or fnmatch.fnmatch(filename, pattern):
                    if self._raw_valid(os.path.join(self.location, filename_raw)):
                        l.append(filename)
        return l

    def get_as_slist(self, *patterns):
        fl = []
        for _rootname, _dirnames, filenames_raw in os.walk(self.location):
            filenames = {}
            for filename in filenames_raw:
                filenames[urllib.parse.unquote(filename)] = filename
            if patterns:	# that means no args given
                use = {}
                for filename, filename_raw in filenames.items():
                    if field_needed(filename, patterns):
                        use[filename] = filename_raw
            else:
                use = filenames
            for filename, filename_raw in use.items():
                if self._raw_valid(os.path.join(self.location, filename_raw)):
                    bisect.insort(fl, ( filename, self._get_raw(filename_raw) ))
        return fl

    def get_as_dict(self, *patterns):
        d = {}
        for _rootname, _dirnames, filenames_raw in os.walk(self.location):
            filenames = {}
            for filename in filenames_raw:
                filenames[urllib.parse.unquote(filename)] = filename
            if patterns:	# that means no args given
                use = {}
                for filename, filename_raw in filenames.items():
                    if field_needed(filename, patterns):
                        use[filename] = filename_raw
            else:
                use = filenames
            for filename, filename_raw in use.items():
                if self._raw_valid(os.path.join(self.location, filename_raw)):
                    d[filename] = self._get_raw(filename_raw)
        return d

    def set(self, key, value, force = True):
        # escape out slashes and other unsavory characters in a non
        # destructive way that won't work as a filename
        key_orig = key
        key = urllib.parse.quote(
            key, safe = '-_ ' + string.ascii_letters + string.digits)
        location = os.path.join(self.location, key)
        if value != None:
            # the storage is always a string, so encode what is not as
            # string as T:REPR, where T is type (b boolean, n number,
            # s string) and REPR is the textual repr, json valid
            if isinstance(value, bool):
                # do first, otherwise it will test as int
                value = "b:" + str(value)
            elif isinstance(value, numbers.Integral):
                # sadly, this looses precission in floats. A lot
                value = "i:%d" % value
            elif isinstance(value, numbers.Real):
                # sadly, this can loose precission in floats--FIXME:
                # better solution needed
                value = "f:%.10f" % value
            elif isinstance(value, str):
                if value.startswith("i:") \
                   or value.startswith("f:") \
                   or value.startswith("b:") \
                   or value.startswith("s:") \
                   or value == "":
                    value = "s:" + value
            else:
                raise ValueError("can't store value of type %s" % type(value))
            assert len(value) < 4096
        if value == None:
            # note that we are setting None (aka: removing the value)
            # we also need to remove any "subfield" -- KEY.a, KEY.b
            try:
                self._raw_unlink(location)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            # FIXME: this can be optimized a lot, now it is redoing a
            # lot of work
            for key_itr in self.keys(key_orig + ".*"):
                key_itr_raw = urllib.parse.quote(
                    key_itr, safe = '-_ ' + string.ascii_letters + string.digits)
                location = os.path.join(self.location, key_itr_raw)
                try:
                    self._raw_unlink(location)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
            return True	# already wiped by someone else
        if force == False:
            try:
                self._raw_write(location, value)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                # ignore if it already exists
                return False
            return True

        # New location, add a unique thing to it so there is no
        # collision if more than one process is trying to modify
        # at the same time; they can override each other, that's
        # ok--the last one wins.
        location_new = location + "-" + str(os.getpid()) + "-" + str(threading.get_ident())
        rm_f(location_new)
        self._raw_write(location_new, value)
        self._raw_rename(location_new, location)
        return True

    def _get_raw(self, key, default = None):
        location = os.path.join(self.location, key)
        try:
            value = self._raw_read(location)
            # if the value was type encoded (see set()), decode it;
            # otherwise, it is a string
            if value.startswith(b"i:"):
                return json.loads(value[2:])
            if value.startswith(b"f:"):
                return json.loads(value[2:])
            if value.startswith(b"b:"):
                val = value[2:]
                if val == b"True":
                    return True
                if val == b"False":
                    return False
                raise ValueError("fsdb %s: key %s bad boolean '%s'"
                                 % (self.location, key, value))
            if value.startswith("s:"):
                # string that might start with s: or empty
                return value.split(":", 1)[1]
            return value	# other string
        except OSError as e:
            if e.errno == errno.ENOENT:
                return default
            raise

    def get(self, key, default = None):
        # escape out slashes and other unsavory characters in a non
        # destructive way that won't work as a filename
        key = urllib.parse.quote(
            key, safe = '-_ ' + string.ascii_letters + string.digits)
        return self._get_raw(key, default = default)


class fsdb_file_c(fsdb_symlink_c):
    """
    In filesystem quick database, but with files instead of symlinks

    In Linux, with symlinks, this was a very good idea -- in
    Windows...well, let's see it doesn't work so well. But this will
    cut it until Windows1x? where apparently symlinks are saner.

    Now, this is not fully atomic, but it tries to be at the name
    level. It is not meant to be a bomb-proof atomic database--it cuts
    it to have multiple processes/threads waiting to the same area of
    disk and if you lock on top (using :mod:`lockfile`), then you
    should achieve better atomicity.
    """

    # note the data is written as a string, since that's what we do
    # with symlinks, so we can just open in default, text mode

    def _raw_valid(self, location):
        return os.path.isfile(location)

    def _raw_read(self, location):
        with open(location, "r") as f:
            return f.read()

    def _raw_write(self, location, value):
        with open(location, "x") as f:
            f.write(value)

    def _raw_unlink(self, location):
        os.unlink(location)

    def _raw_rename(self, location_new, location):
        os.replace(location_new, location)

    def _raw_stat(self, location):
        return os.lstat(location)


def retry_cb_tries(ExceptionToCheck,
                   tries: int = 4, delay: float = 3, backoff: float = 1,
                   header: str = None,
                   logger: logging.Logger = None):
    """
    Retry/Circuit-Breaker decorator -- circuit-break after X tries
    with optional backoff


    Usage example:

    >>> def run_online(target):
    >>>
    >>>     top_tries = 4
    >>>
    >>>     @retry_cb_tries(subprocess.SubprocessError, tries = top_tries,
    >>>                     header = "ping: ", logger = target.report_info)
    >>>     def _ping(target, ipv4_addr):
    >>>         subprocess.check_output([ "ping", "-c", "3", ipv4_addr ],
    >>>                                 stderr = subprocess.STDOUT, timeout = 5)
    >>>         target.report_pass(f"NUC {ipv4_addr} pings online")
    >>>
    >>>     ipv4_addr = target.kws['ipv4_addr']
    >>>     try:
    >>>         _ping(target, ipv4_addr)
    >>>     except subprocess.TimeoutExpired as e:
    >>>         raise tcfl.fail_e(
    >>>             f"NUC {ipv4_addr} is not online after {top_tries} tries") from e



    :param ExceptionToCheck: the exception to check. may be a tuple of
        exceptions to check

    :param int tries: number of times to try (not retry) before giving up

    :param float delay: initial delay between retries in seconds

    :param float backoff: backoff multiplier e.g. value of 2 will
        double the delay each retry

    :param callable logger: logging function to use for warnings on retry

    References:
    - https://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    - http://wiki.python.org/moin/PythonDecoratorLibrary#Retyr

    """
    def deco_retry(f):

        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    if mdelay <= 0:
                        logger(f"{header}retrying due to exception: {e}")
                        pass
                    if logger:
                        logger(f"{header}retrying in {mdelay} seconds"
                               f" due to exception {type(e).__name__}: {e}")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry
