#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Internal API for *ttbd*

Note interfaces are added with :meth:`test_target.interface_add`, not
by subclassing. See as examples :class:`ttbl.console.interface` or
:class:`ttbl.power.interface`.

"""
import bisect
import collections
import contextlib
import errno
import fcntl
import fnmatch
import glob
import ipaddress
import json
import logging
import numbers
import os
import pprint
import random
import re
import shutil
import signal
import socket
import string
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types
import urllib.parse

import __main__
import requests
import usb.util

import commonl
import ttbl.user_control

logger = logging.root.getChild("ttb")

class test_target_e(Exception):
    """
    A base for all operations regarding test targets.
    """
    pass

class test_target_busy_e(test_target_e):
    def __init__(self, target, who, owner):
        test_target_e.__init__(
            self,
            "%s: '%s' tried to use busy target (owned by '%s')"
            % (target.id, who, owner))

class test_target_wrong_state_e(test_target_e):
    def __init__(self, target, state, expected_state):
        test_target_e.__init__(
            self,
            "%s: tried to use target in state '%s' but needs '%s')"
            % (target.id, state, expected_state))

class test_target_not_acquired_e(test_target_e):
    def __init__(self, target):
        test_target_e.__init__(
            self,
            "%s: tried to use non-acquired target" % target.id)

class test_target_release_denied_e(test_target_e):
    def __init__(self, target):
        test_target_e.__init__(
            self,
            "%s: tried to release target owned by another user" % target.id)


class test_target_not_admin_e(test_target_e):
    def __init__(self, target):
        test_target_e.__init__(
            self,
            "%s: need administrator rights" % target.id)

class test_target_logadapter_c(logging.LoggerAdapter):
    """
    Prefix to test target logging the name of the target and if
    acquired, the current owner.

    This is useful to correlate logs in server in client when
    diagnosing issues.
    """
    def process(self, msg, kwargs):
        target = self.target
        owner = target.owner_get()
        if owner:
            return ( 'target-%s[%s]: %s ' % (target.id, owner, msg), kwargs )
        else:
            return ( 'target-%s: %s ' % (target.id, msg), kwargs )

_who_daemon = None

def who_daemon():
    """
    Returns the internal user for daemon operations
    """
    return _who_daemon

def who_split(who):
    """
    Returns a tuple with target owner specification split in two parts, the
    userid and the ticket. The ticket will be None if the orders
    specification doesn't contain it.
    """
    if ":" in who:
        return who.split(":", 2)
    return who, None

def who_create(user_id, ticket = None):
    """
    Create a TTBD user descriptor from a user id name and a ticket

    :params str user_id: user's name / ID
    :params str ticket: (optional) ticket for the reservation

    :returns: (str) user id descriptor
    """
    if ticket != None and ticket != "":
        return user_id + ":" + ticket
    else:
        return user_id


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
    examples, look at :class:`ttbl.fsdb_symlink_c`.
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

    #: Regular expresion that determines the valid characters in a field
    key_valid_regex = re.compile(r"^[-\.a-zA-Z0-9_]+$")

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
        if not self.key_valid_regex.match(key):
            raise ValueError("%s: invalid key name (valid: %s)" \
                             % (key, self.key_valid_regex.pattern))
        if value != None:
            assert isinstance(value, (str, int, float, bool))
        raise NotImplementedError

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
            self.uuid = commonl.mkid(str(id(self)) + str(os.getpid()))
        else:
            self.uuid = use_uuid

        self.location = dirname

    def keys(self, pattern = None):
        l = []
        for _rootname, _dirnames, filenames_raw in os.walk(self.location):
            filenames = []
            for filename_raw in filenames_raw:
                # need to filter with the unquoted name...
                filename = urllib.parse.unquote(filename_raw)
                if pattern == None or fnmatch.fnmatch(filename, pattern):
                    if os.path.islink(os.path.join(self.location, filename_raw)):
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
                    if commonl.field_needed(filename, patterns):
                        use[filename] = filename_raw
            else:
                use = filenames
            for filename, filename_raw in use.items():
                if os.path.islink(os.path.join(self.location, filename_raw)):
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
                    if commonl.field_needed(filename, patterns):
                        use[filename] = filename_raw
            else:
                use = filenames
            for filename, filename_raw in use.items():
                if os.path.islink(os.path.join(self.location, filename_raw)):
                    d[filename] = self._get_raw(filename_raw)
        return d

    def set(self, key, value, force = True):
        # escape out slashes and other unsavory characters in a non
        # destructive way that won't work as a filename
        key_orig = key
        key = urllib.parse.quote(
            key, safe = '-_ ' + string.ascii_letters + string.digits)
        location = os.path.join(self.location, key)
        if not self.key_valid_regex.match(key):
            raise ValueError("%s: invalid key name (valid: %s)" \
                             % (key, self.key_valid_regex.pattern))
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
                os.unlink(location)
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
                    os.unlink(location)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
            return True	# already wiped by someone else
        if force == False:
            try:
                os.symlink(value, location)
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
        location_new = location + "-" + str(os.getpid())
        commonl.rm_f(location_new)
        os.symlink(value, location_new)
        os.rename(location_new, location)
        return True

    def _get_raw(self, key, default = None):
        location = os.path.join(self.location, key)
        try:
            value = os.readlink(location)
            # if the value was type encoded (see set()), decode it;
            # otherwise, it is a string
            if value.startswith("i:"):
                return json.loads(value.split(":", 1)[1])
            if value.startswith("f:"):
                return json.loads(value.split(":", 1)[1])
            if value.startswith("b:"):
                val = value.split(":", 1)[1]
                if val == "True":
                    return True
                elif val == "False":
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


class process_posix_file_lock_c(object):
    """
    Very simple interprocess file-based spinning lock

    .. warning::

       - Won't work between threads of a process

       - If a process dies, the next process can acquire it but there
         will be no warning about the previous process having died,
         thus state protected by the lock might be inconsistent
    """

    class timeout_e(Exception):
        pass

    def __init__(self, lockfile, timeout = 20, wait = 0.3):
        self.lockfile = lockfile
        self.timeout = timeout
        self.wait = wait
        self.fd = None
        # ensure the file is created
        with open(self.lockfile, "w+") as f:
            f.write("")

    def acquire(self):
        ts0 = time.time()
        self.fd = os.open(self.lockfile, os.O_RDWR | os.O_EXCL)
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except IOError as e:
                if e.errno != errno.EAGAIN:
                    raise
                time.sleep(self.wait)
                ts = time.time()
                if ts - ts0 > self.timeout:
                    raise self.timeout_e

    def release(self):
        os.close(self.fd)
        self.fd = None

    def locked(self):
        return self.fd != None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _a, _b, _c):
        self.release()




class acquirer_c(object):
    """
    Interface to resource acquisition managers/schedulers

    A subclass of this is instantiated to manage the access to
    resources that can be contended; when using the TCF remoting
    mechanism that deals with targets connected to the current host,
    for example, this is :class:`ttbl.symlink_acquirer_c`.

    This can however, use any other resource manager.

    The operations in here can raise any exception, but mostly the
    ones derived from :class:`ttbl.acquirer_c.exception`:

    - :class:`ttbl.acquirer_c.timeout_e`
    - :class:`ttbl.acquirer_c.busy_e`
    - :class:`ttbl.acquirer_c.no_rights_e`
    - :class:`ttbl.acquirer_c.cant_release_not_owner_e`
    - :class:`ttbl.acquirer_c.cant_release_not_acquired_e`

    """
    def __init__(self, target):
        assert isinstance(target, ttbl.test_target)
        self.target = target

    class exception(Exception):
        "General exception for acquisition system errors"
        def __init__(self):
            Exception.__init__(self, self.__doc__)

        def __repr__(self):
            return self.__doc__

    class timeout_e(exception):
        "Timeout acquiring"
        pass

    class busy_e(exception):
        "The resource is busy, can't acquire"
        pass

    class no_rights_e(exception):
        "Not enought rights to perform the operation"
        pass

    class cant_release_not_owner_e(exception):
        "Cannot release since the resource is acquired by someone else"
        pass

    class cant_release_not_acquired_e(exception):
        "Cannot release since the resource is not acquired"
        pass

    def acquire(self, who, force):
        """
        Acquire the resource for the given user

        The implementation is allowed to spin for a little while to
        get it done, but in general this shall be a non-blocking
        operation, return busy if not available.

        :param str who: user name
        :param bool force: force the acquisition (overriding current
          user); this assumes the user *who* has permissions to do so;
          if not, raise an exception child of
          :class:`ttbl.acquirer_c.exception`.

        :raises busy_e: if the target is busy and could not be acquired
        :raises acquirer_c.timeout_e: some sort of timeout happened
        :raises no_rights_e: not enough privileges for the operation
        """
        raise NotImplementedError

    def release(self, who, force):
        """
        Release the resource from the given user

        :param str who: user name
        :param bool force: force the release (overriding current
          user); this assumes the user *who* has permissions to do so;
          if not, raise an exception child of
          :class:`ttbl.acquirer_c.exception`.
        """
        raise NotImplementedError

    def get(self):
        """
        Return the current resource owner
        """
        raise NotImplementedError


class symlink_acquirer_c(acquirer_c):
    """
    The lamest file-system based mutex ever

    This is a rentrant mutex implemented using symlinks (an atomic
    operation under POSIX).

    To create it, declare the location where it will be and a string
    the *owner*. Then you can acquire() or release() it. If it is
    already acquired, it can spin busy wait on it (if given a timeout)
    or just fail. You can only release if you own it.

    Why like this? We'll have multiple processes doing this on behalf
    of remote clients (so it makes no sense to track owner by PID. The
    caller decides who gets to override and all APIs agree to use it
    (as it is advisory).

    .. warning:: The reentrancy of the lock assumes that the owner
      will use a single thread of execution to operate under it.

      Thus, the following scenario would fail and cause a race
      condition:

        - Thread A: acquires as owner-A
        - Thread B: starts to acquire as owner-A
        - Thread A: releases as owner-A (now released)
        - Thread B: verifies it was acquired by owner-A so passes as
          acquired
        - Thread B: MISTAKENLY assumes it owns the mutex when it is
          released in reality

      So use a different owner for each thread of execution.

    """

    def __init__(self, target, wait_period = 0.5):
        assert wait_period > 0
        ttbl.acquirer_c.__init__(self, target)
        self.target = target
        self.location = os.path.join(target.state_dir, "mutex")
        self.wait_period = wait_period

    def acquire(self, who, force):
        """
        Acquire the mutex, blocking until acquired
        """
        if force:
            commonl.rm_f(self.location)
        else:
            current_owner = self.get()
            if current_owner != None and current_owner == who:
                return	# we already own it
        try:
            os.symlink(who, self.location)
        except OSError as e:
            if e.errno == errno.EEXIST:
                raise self.busy_e()
            raise

    def release(self, who, force):
        if force:
            try:
                os.unlink(self.location)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    pass
                raise
            return
        try:
            link_dest = os.readlink(self.location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise self.cant_release_not_acquired_e()
        # Here is the thinking: if you have a right to release this
        # mutex is because you own it; thus, it won't change since the
        # time we read its target until you get to unlock it by
        # removing the file. Yeah, some other process could have come
        # in the middle and removed it and then we are done. Window
        # for race condition
        # I'd rather have an atomic 'unlink if target matches...'
        if link_dest != who:
            raise self.cant_release_not_owner_e()
        os.unlink(self.location)


    def get(self):
        try:
            return os.readlink(self.location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return None
            raise

class tt_interface_impl_c(object):
    def __init__(self, name = None, **kwargs):
        self.name = name
        #: Unique Physical IDentification
        #:
        #: flat dictionary of keys to report HW information for
        #: inventory purposes of whichever HW component is used to
        #: implement this driver.
        #:
        #: Normally set from the driver with a call to
        #: :meth:`upid_set`; howevr, after instantiation, more fields
        #: can be added to a driver with information that can be
        #: useful to locate a piece of HW. Eg:
        #:
        #: >>> console_pc = ttbl.console.generic_c(chunk_size = 8,
        #: >>>     interchunk_wait = 0.15)
        #: >>> console_pc.upid_set("RS-232C over USB", dict(
        #: >>>     serial_number = "RS33433E",
        #: >>>     location = "USB port #4 front"))
        self.upid = kwargs
        #: Unique ID for this instrument/device -- this gets filled in
        #: by the daemon upon initialization
        self.upid_index = None

    def upid_set(self, name_long, **kwargs):
        """
        Set :data:`upid` information in a single shot

        :param str name_long: Long name of the physical component that
          implements this interface functionality.

          This gets registered as instrument property *name_long* and
          if the instrument has defined no short *name* property, it
          will be registered as such.

          The short *name* has more restrictions, thus it is
          recommended implementations set it.

        :param dict kwargs: fields and values (strings) to report for
          the physical component that implements this interface's
          functionality; it is important to specify here a unique
          piece of information that will allow this component to be
          reported separately in the instrumentation section of the
          inventory. Eg: serial numbers or paths to unique devices.

        For example:

        >>> impl_object.upid_set("ACME power controller", serial_number = "XJ323232")

        This is normally called from the *__init__()* function of a
        component driver, that must inherit :class:`tt_interface_impl_c`.
        """
        assert isinstance(name_long, str), \
            "name_long: expected a string; got %s" % type(name_long)
        for key, val in kwargs.items():
            assert val == None or isinstance(val, (str, int,
                                                   float, bool)), \
                "UPID field '%s' must be string|number|bool; got %s" \
                % (key, type(val))
        if not self.name:
            self.name = name_long
        kwargs['name_long'] = name_long
        self.upid = kwargs


class tt_interface(object):
    """A target specific interface

    This class can be subclassed and then instanced to create a target
    specific interface for implementing any kind of functionality. For
    example, the :class:`console <ttbl.console.interface>`, in a
    configuration file when the target is added:

    >>> target = test_target("TARGETNAME")
    >>> ttbl.config.target_add(target)
    >>>
    >>> target.interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         serial0 = ttbl.console.serial_pc("/dev/ttyS0")
    >>>         serial1 = ttbl.console.serial_pc("/dev/ttyS1")
    >>>         default = "serial0",
    >>>     )
    >>> )

    creates an instance of the *console* interface with access to two
    console. The interface is then available over HTTP
    ``https://SERVER/ttb-vN/target/TARGETNAME/console/*``

    A common pattern for interfaces is to be composed of multiple
    components, with a different implementation driver for each. For
    that, a class named *impl_c* is created to define the base
    interface that all the implementation drivers need to support.

    To create methods that are served over the
    ``https://SERVER/ttb-vN/target/TARGETNAME/INTERFACENAME/*`` url,
    create methods in the subclass called *METHOD_NAME* with the
    signature:

    >>>     def METHOD_NAME(self, target, who, args, files, user_path):
    >>>         impl, component = self.arg_impl_get(args, "component")
    >>>         arg1 = args.get('arg1', None)
    >>>         arg2 = args.get('arg2', None)
    >>>         ...

    where:

    - *METHOD* is *put*, *get*, *post* or *delete* (HTTP methods)

    - *NAME* is the method name (eg: *set_state*)

    - *target* is the target object this call is happening onto

    - *who* is the (logged in) user making this call

    - *args* is a dictionary of arguments passed by the client for the
      HTTP call keyed by name (a string)

    - *files* dictionrary of files passed to the HTTP request (FIXME:
       doc properly)

    - *user_path* is a string describing the space in the filesystem
      where files for this user are stored

    Return values:

     - these methods can throw an exception on error (and an error code will
       be sent to the client)

     - a dictionary of keys and values to return to the client as JSON
       (so JSON encodeable).

       To stream a file as output, any other keys are ignored and the
       following keys are interpreted, with special meaning

       - *stream_file*: (string) the named file will be streamed to the client
       - *stream_offset*: (positive integer) the file *steam_file*
         will be streamed starting at the given offset.
       - *stream-generation*: (positive monotonically increasing
         integer) a number that describes the current iteration of
         this file that might be reset [and thus bringing its apparent
         size to the client to zero] upon certain operations (for
         example, for serial console captures, when the target power
         cycles, this number goes up and the capture size starts at
         zero).

       An X-stream-gen-offset header will be returned to the client
       with the string *GENERATION OFFSET*, where the current
       generation of the stream as provided and the offset that was
       used, possibly capped to the actual maximum offset are
       returned.

       This way the client can use OFFSET+Conten-Length to tell the
       next offset to query.

    When multiple components are used to implement the functionality
    of an interface or to expose multiple instruments that
    implement the functionality (such as in
    :class:`ttbl.power.interface` or :class:`ttbl.console.interface`),
    use methods:

    - :meth:`impls_set`

    See as an example the :class:`debug <ttbl.debug.interface>` class.

    """

    def __init__(self):
        #: List of components that implement this interface
        #:
        #: (for interfaces that support multiple components only)
        #:
        #: This has to be an ordered dict because the user might care about
        #: order (eg: power rails need to be executed in the given order)
        self.impls = collections.OrderedDict()
        #: Map of names in :data:`impls` that are actually an alias
        #: and which entry they are aliasing.
        self.aliases = dict()
        #: class the implementations to for this interface are based
        #: on [set by the initial call to :meth:`impls_set`]
        self.cls = None

    def _target_setup(self, target, iface_name):
        # FIXME: move to public interface
        """
        Called when the interface is added to a target to initialize
        the needed target aspect (such as adding tags/metadata)
        """
        raise NotImplementedError


    def _release_hook(self, target, force):
        # FIXME: move to public interface
        # FIXME: remove force, unuused
        """
        Called when the target is released
        """
        raise NotImplementedError

    def _init_by_name(self, name, impl, aliases):
        if isinstance(impl, self.cls):
            if name in self.impls:
                raise AssertionError("component '%s' already exists "
                                     % name)
            self.impls[name] = impl
        elif isinstance(impl, str):		# alias...
            aliases[name] = impl			# ...process later
        else:
            raise AssertionError(
                "'%s' implementation is type %s, " \
                "expected %s or str" % (
                    name, type(impl).__name__,
                    self.cls
                ))

    def _aliases_update(self, aliases):
        for alias, component in aliases.items():
            if component not in self.impls:
                raise AssertionError(
                    "alias '%s' refers to an component "
                    "'%s' that does not exist (%s)"
                    % (alias, component, " ".join(list(self.impls.keys()))))
            self.aliases[alias] = component

    def impl_add(self, name, impl):
        """
        Append a new implementation to the list of implementations
        this interface supports.

        This can be used after an interface has been declared, such
        as:

        >>> target = ttbl.test_target('somename')
        >>> target.interface_add('power', ttbl.power.interface(*power_rail))
        >>> target.power.impl_add('newcomponent', impl_object)

        :param str name: implementation's name
        :param impl: object that defines the implementation; this must
          be an instance of the class :data:`cls` (this gets set by the
          first call to :meth:`impls_set`.
        """
        aliases = {}
        self._init_by_name(name, impl, aliases)
        self._aliases_update(aliases)

    def impls_set(self, impls, kwimpls, cls):
        """
        Record in *self.impls* a given set of implementations (or components)

        This is only used for interfaces that support multiple components.

        :param list impls: list of objects of type *cls* or of tuples
          *(NAME, IMPL)* to serve as implementations for the
          interface; when non named, they will be called *componentN*

        :param dict impls: dictionary keyed by name of objects of type
          *cls* to serve as implementatons for the interface.

        :param type cls: base class for the implementations (eg:
          :class:`ttbl.console.impl_c`)

        This is meant to be used straight in the constructor of a
        derivative of :class:`ttbl.tt_interface` such as:

        >>> class my_base_impl_c(object):
        >>>     ...
        >>> class my_interface(ttbl.tt_interface):
        >>>     def __init__(*impls, **kwimpls):
        >>>         ttbl.tt_interface(self)
        >>>         self.impls_set(impls, kwimplws, my_base_implc_c)

        and it allows to specify the interface implementations in
        multiple ways:

        - a sorted list of implementations (which will be given generic
          component names such as *component0*, *component1*):

          >>> target.interface_add("my", my_interface(
          >>>     an_impl(args),
          >>>     another_impl(args),
          >>> ))

        - *COMPONENTNAME = IMPLEMENTATION* (python initializers),
          which allows to name the components (and keep the order
          in Python 3 only):

          >>> target.interface_add("my", my_interface(
          >>>     something = an_impl(args),
          >>>     someotherthing = another_impl(args),
          >>> ))

        - a list of tuples *( COMPONENTNAME, IMPLEMENTATION )*, which
          allow to name the implementations keeping the order (in Python 2):

          >>> target.interface_add("my", my_interface(
          >>>     ( something, an_impl(args) ),
          >>>     ( someotherthing, another_impl(args) ),
          >>> ))

        all forms can be combined; as well, if the implementation is
        the name of an existing component, then it becomes an alias.
        """
        assert isinstance(impls, collections.Iterable)
        assert isinstance(kwimpls, dict), \
            "impls must be a dictionary keyed by console name; got %s" \
            % type(impls).__name__
        assert issubclass(cls, object)

        # initialize for impl_add()
        self.cls = cls
        aliases = {}

        count = 0
        for impl in impls:
            if isinstance(impl, tuple):
                assert len(impl) == 2, \
                    "tuple of implementations has to have two elements; " \
                    "got %d" % len(impl)
                name, pc = impl
                assert isinstance(name, str), \
                    "tuple[0] has to be a string, got %s" % type(name)
                assert isinstance(pc, (cls, str)), \
                    "tuple[1] has to be a %s or str, got %s" % (cls, type(pc))
                self._init_by_name(name, pc, aliases)
            elif isinstance(impl, cls):
                self._init_by_name("component%d" % count, impl, aliases)
            else:
                raise RuntimeError("list of implementations have to be "
                                   "either instances of subclasses of %s "
                                   " or tuples of (NAME, INSTANCE);"
                                   " %s is a %s"
                                   % (cls, impl, type(impl)))
            count += 1

        for name, impl in list(kwimpls.items()):
            self._init_by_name(name, impl, aliases)
        self._aliases_update(aliases)

    @staticmethod
    def _arg_get(args, name):
        if name not in args:
            raise RuntimeError("missing '%s' argument" % name)
        return args[name]

    @staticmethod
    def arg_get(args, arg_name, arg_type,
                allow_missing = False, default = None):
        """Return the value of an argument passed to the call

        Given the arguments passed with an HTTP request check if one
        called ARG_NAME of type ARG_TYPE is present, return whatever
        value it has.

        Now, some values can be passed JSON encoded, some not -- this
        is done for making it easy on the client side, so it can do
        calls with curl/wget without having to mess it up too much:

        :returns: the value
        """
        assert isinstance(args, dict)
        assert isinstance(arg_name, str)
        assert arg_type == None or isinstance(arg_type, type)\
            or isinstance(arg_type, tuple) and all(isinstance(i, type)
                                                   for i in arg_type)
        assert isinstance(allow_missing, bool)
        if not arg_name in args:
            if allow_missing:
                return default
            raise RuntimeError("missing '%s' argument" % arg_name)
        try:
            # support direct calling inside the daemon; if it is a
            # str, we consider it might be JSON and decode it 
            arg = args[arg_name]
            if isinstance(arg, str):
                arg = json.loads(arg)
        except ValueError as e:
            # so let's assume is not properly JSON encoded and it is
            # just a string to pass along
            arg = args[arg_name]
            # all this is backwards compat..... fugly, yes; but early clients
            # failed to properly json encode args; also, when calling
            # from curl with -d it becomes more ellaborate, so let's
            # keep it.
            if arg in ( "none", "None", "null" ):
                arg = None
            elif arg in ( "True", "true" ):
                arg = True
            elif arg in ( "False", "false" ):
                arg = False
            else:
                # if we are expecting another type, let's try to
                # convert it
                if arg_type and arg_type != str:
                    try:
                        arg = arg_type(arg)
                    except ValueError:
                        raise ValueError(
                            "%s: can't convert expected type %s; value: %s"
                            % (arg_name, arg_type.__name__, arg))
        if arg_type != None and not isinstance(arg, arg_type):
            raise RuntimeError(
                "%s: argument must be a %s; got '%s'"
                % (arg_name, arg_type.__name__, type(arg).__name__))
        return arg

    def impl_get_by_name(self, arg, arg_name = "component"):
        """
        Return an interface's component implementation by name
        """
        if arg in self.aliases:		# translate?
            arg = self.aliases[arg]
        if arg in self.impls:
            return self.impls[arg], arg
        raise IndexError("%s: unknown %s" % (arg, arg_name))


    def arg_impl_get(self, args, arg_name, allow_missing = False):
        """
        Return an interface's component implementation by name

        Given the arguments passed with an HTTP request
        check if one called ARG_NAME is present, we want to get
        args[ARG_NAME] and self.impl[ARG_NAME].

        :returns: the implementation in *self.impls* for the component
          specified in the args
        """
        arg = self.arg_get(args, arg_name, str, allow_missing)
        if arg == None:
            return None, None
        return self.impl_get_by_name(arg, arg_name)


    def args_impls_get(self, args):
        """
        Return a list of components by name or all if none given

        If no *component* argument is given, return the whole list of
        component implementations, otherwise only the selected one.

        (internal interface)

        :params dict args: dictionary of arguments keyed by argument
          name:

          - *component*: a  component name to consider, if none, all
          - *components*: list of component names to consider, if none, all
          - *components_exclude*: (optional) list of components to exclude

        :returns: a tuple of *(list, bool)*; list of a list of
          implementations that need to be operated on; bool is *True*
          if the list refers to all the components because the user
          specified no *component* or *components* argument in the
          call. *False* means only specific implementations are being
          refered.
        """
        impl, component = self.arg_impl_get(args, 'component',
                                            allow_missing = True)
        components_exclude = args.get('components_exclude', [])
        components = args.get('components', [])
        if impl == None:
            # no component was specified, so we operate over all the
            # components unless components was given
            # KEEP THE ORDER
            if components:
                impls = []
                for component in components:
                    impl, name = self.impl_get_by_name(
                        component, arg_name = "component")
                    impls.append(( name, impl ))
                # even if it might be all, we don't now for sure
                _all = False
            else:
                impls = list(self.impls.items())
                _all = True
        else:
            impls = [ ( component, impl ) ]
            _all = False
        if components_exclude:
            # if we are excluding components, then we need to reset
            # the list and also the _all flag
            new_impls = [ i for i in impls if i[0] not in components_exclude ]
            if len(new_impls) < len(impls):
                _all = False
                impls = new_impls
        return impls, _all


    @staticmethod
    def assert_return_type(val, expected_type, target, component, call,
                           none_ok = False):
        """
        Assert a value generated from a target interface call driver
        is of the right type and complain otherwise
        """
        assert isinstance(expected_type, type)
        assert isinstance(target, ttbl.test_target)
        assert component == None or isinstance(component, str)
        assert isinstance(call, str)
        assert isinstance(none_ok, bool)
        if none_ok == True and val == None:
            return
        assert isinstance(val, expected_type), \
            "%s::%s[%s](): driver returned %s, expected %s" \
            % (target.id, call, component,
               type(val).__name__, expected_type.__name__)


    @staticmethod
    def instrument_mkindex(name, upid, kws):
        if name:
            name = name % kws
            index = commonl.mkid(name + pprint.pformat(upid), l = 4)
        else:
            index = commonl.mkid(pprint.pformat(upid), l = 4)
        return name, index

    def instrumentation_publish_component(
            self, target, iface_name,
            index, instrument_name, upid, components = None, kws = None):
        """
        Publish in the target's inventory information about the
        instrumentations that implements the functionalities of the
        components of this interface
        """

        assert components == None or isinstance(components, list)
        if kws == None:
            kws = commonl.dict_missing_c({}, "n/a")
            kws.update(target.kws)
            kws.update(target.fsdb.get_as_dict())
        if index == None:
            instrument_name, index = \
                self.instrument_mkindex(instrument_name, upid, kws)
        prefix = "instrumentation." + index
        target.property_set(prefix + ".name", instrument_name)
        for key, val in upid.items():
            if val:
                # there might be empty values, as defaults, so we ignore them
                if isinstance(val, str):
                    # if it is a string, it is a template
                    target.property_set(prefix + "." + key, val % kws)
                else:
                    target.property_set(prefix + "." + key, val)
        if components:
            target.property_set(prefix + ".functions." + iface_name,
                                ":".join(components))
        else:
            target.property_set(prefix + ".functions." + iface_name,
                                "true")

    def instrumentation_publish(self, target, iface_name):
        """
        Publish in the target's inventory information about the
        instrumentations that implements the functionalities of the
        components of this interface
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(iface_name, str)

        tags_interface = collections.OrderedDict()
        components_by_index = collections.defaultdict(list)
        name_by_index = {}
        upid_by_index = {}
        kws = commonl.dict_missing_c({}, "n/a")
        kws.update(target.kws)
        kws.update(target.fsdb.get_as_dict())
        for component in list(self.impls.keys()):
            # validate image types (from the keys) are valid from
            # the components and aliases
            impl, _ = self.impl_get_by_name(component, "component")
            instrument_name, index = \
                self.instrument_mkindex(impl.name, impl.upid, kws)
            tags_interface[component] = {
                "instrument": index
            }
            impl.upid_index = index
            # FIXME: there must be a more efficient way than using
            # pprint.pformat
            components_by_index[index].append(component)
            name_by_index[index] = instrument_name
            upid_by_index[index] = impl.upid

        for index, components in components_by_index.items():
            self.instrumentation_publish_component(
                target, iface_name, index,
                name_by_index.get(index, None), upid_by_index[index],
                components,
                kws = kws)
        target.tags['interfaces'][iface_name] = tags_interface


    def request_process(self, target, who, method, call,
                        args, files, user_path):
        """
        Process a request into this interface from a proxy / brokerage

        When the ttbd daemon is exporting access to a target via any
        interface (e.g: REST over Flask or D-Bus or whatever), this
        implements a brige to pipe those requests in to this
        interface.

        :param test_target target: target upon which we are operating
        :param str who: user who is making the request
        :param str method: 'POST', 'GET', 'DELETE' or 'PUT' (mapping
          to HTTP requests)
        :param str call: interface's operation to perform (it'd map to
          the different methods the interface exposes)
        :param dict args: dictionary of key/value with the arguments
          to the call, some might be JSON encoded.
        :param dict files: dictionary of key/value with the files
          uploaded via forms
          (https://flask.palletsprojects.com/en/1.1.x/api/#flask.Request.form)
        :param str user_path: Path to where user files are located

        :returns: dictionary of results, call specific
          e.g.:

          >>> dict(
          >>>    result = "SOMETHING",	# convention for unified result
          >>>    output = "something",
          >>>    value = 43
          >>> )

        For an example, see :class:`ttbl.power.interface`.
        """
        assert isinstance(target, test_target)
        assert isinstance(who, str)
        assert isinstance(method, str) \
            and method in ( 'POST', 'GET', 'DELETE', 'PUT' )
        assert isinstance(call, str)
        assert isinstance(args, dict)
        assert user_path != None and isinstance(user_path, str)
        raise NotImplementedError("%s|%s: unsupported" % (method, call))
        # Note that upon return, the calling layer will add a field
        # 'diagnostics', so don't use that
        #
        #return dict(result = "SOMETHING")
        #
        # to streaming a file
        #
        #return dict(stream_file = CAPTURE_FILE, stream_offset = OFFSET)


# FIXME: yeah, ugly, but import dependency hell
from . import allocation
import ttbl.config


class test_target(object):

    #: Path where the runtime state is stored
    state_path = None

    #: Path where files are stored
    files_path = None

    #: Properties that normal users (non-admins) can set when owning a
    #: target and that will be reset when releasing a target (except
    #: if listed in :data:`properties_keep_on_release`)
    #:
    #: Note this is a global variable that can be speciazed to each
    #: class/target.
    properties_user = set([
        # provisioning OS mode
        'pos_mode',
        re.compile('^pos_root_[_a-z0-9A-Z]+$'),
    ])
    #: Properties that should not be cleared on target release
    properties_keep_on_release = set([
        re.compile('^pos_root_[_a-z0-9A-Z]+$'),
        'linux_options_append',
    ])

    """
    A test target base class
    """
    def __init__(self, __id, _tags = None, _type = None, fsdb = None):
        self.id = __id    #: Target name/identifier
        #: Target's tags
        #:
        #: FIXME document more
        #:
        self.tags = {
            'interconnects': {},
        }
        #: List of targets this target is a thing to; see
        #: class:`ttbl.things.interface`
        #:
        #: FIXME: this needs to be moved to that interface
        self.thing_to = set()
        if _tags:
            self.tags.update(_tags)
        if _type != None:
            self._type = _type
        else:
            self._type = type(self).__name__
        self.tags['id'] =  __id
        self.tags['type'] = self._type
        self.log = test_target_logadapter_c(logging.getLogger(), None)
        self.log.target = self
        self.log.propagate = False
        # List of interfaces that this target supports; updated by
        # interface_add().
        self.tags['interfaces'] = {}

        # Create the directory where we'll keep the target's state
        self.state_dir = os.path.join(self.state_path, self.id)
        commonl.makedirs_p(self.state_dir, 0o2770,
                           "target %s's state" % self.id)
        commonl.makedirs_p(os.path.join(self.state_dir, "queue"), 0o2770,
                           "target %s's allocation queue" % self.id)
        self.lock = process_posix_file_lock_c(
            os.path.join(self.state_dir, "lockfile"))
        #: filesystem database of target state; the multiple daemon
        #: processes use this to store information that reflect's the
        #: target's state.
        if fsdb == None:
            self.fsdb = fsdb_symlink_c(self.state_dir)
        else:
            assert isinstance(fsdb, fsdb_c), \
                "fsdb %s must inherit ttbl.fsdb_c" % fsdb
            self.fsdb = fsdb

        #: Keywords that can be used to substitute values in commands,
        #: messages. Target's tags are translated to keywords
        #: here. :func:`ttbl.config.target_add` will update this with
        #: the final list of tags.
        self.kws = {}

        #: Functions to call when the target is released (things like
        #: removing tunnels the user created, resetting debug state,
        #: etc); this is meant to leave the target's state pristine
        #: so that it does not affect the next user that acquires it.
        #: Each interface will add as needed, so it gets executed upon
        #: :meth:`release`, under the owned lock.
        self.release_hooks = set()

        #: Keep places where interfaces were registered from
        self.interface_origin = {}
        #: FIXME
        self._acquirer = None

        #:
        #: Pre/post power on/off hooks
        #:
        #: For historical reasons, these lists are here instead of on
        #: the new power interface extension--at some point they will
        #: be moved
        #:
        #: FIXME: move to target.power.
        self.power_on_pre_fns = []
        self.power_on_post_fns = []
        self.power_off_pre_fns = []
        self.power_off_post_fns = []

    @classmethod
    def known_targets(cls):
        """
        Return list of known targets descriptors
        """
        return ttbl.config.targets.values()

    @classmethod
    def get(cls, target_name):
        """
        Return an object descripting an existing target name

        :param str: name of target (which shall be available in
          configuration)
        """
        return ttbl.config.targets.get(target_name, None)

    @classmethod
    def get_for_user(cls, target_name, calling_user):
        """
        If *calling_user* has permission to see & user *target_name*,
        return the target descriptor

        :param str target_name: target's name
        :param ttbl.user_control.User calling_user: descriptor of user
          who is trying to access the target.

        :return ttbl.test_target: if target exists and the user is
          allowed to see and use it, descriptor to it, *None*
          otherwise.        
        """
        assert isinstance(target_name, str)
        assert isinstance(calling_user, ttbl.user_control.User)
        target = cls.get(target_name)
        if not target:
            return None
        if not target.check_user_allowed(calling_user):
            return None
        return target

    def check_user_allowed(self, user):
        """
        Return if *user* is allowed to see/use this target

        :param ttbl.user_control.User user: descriptor of user
          who is trying to access the target.
        """
        assert isinstance(user, ttbl.user_control.User)
        if user.role_get('admin'):	# admins are always in
            return True

        # Note we get it only from the tags, so it cannot be overriden
        # by fsdb
        roles_required = self.tags.get('_roles_required', [])
        roles_excluded = self.tags.get('_roles_excluded', [])
        for role in roles_excluded:	# users to be excluded
            if user.role_get(role):
                return False
        if roles_required:		# do you require a role?
            for role in roles_required:
                if user.role_get(role):
                    return True		# it has the role, good
            return False		# does not have it, out

        # If there are no requirements and no exclusions, by default
        # you can come in
        return True

    def to_dict(self, projections = None):
        """
        Return all of the target's data as a dictionary

        :param list projections: (optional) list of fields to include
          (default: all).

          Field names can use periods to dig into dictionaries.

          Field names can match :mod:`fnmatch` regular
          expressions.
        """

        # Set read-only values from config as base
        # why convert from flat to dict and then back to dict? Well,
        # because it is way easier to filter on flat triyng to keep
        # what has to be there and what not. And the performance at
        # the end might not be much more or less...
        l = commonl.dict_to_flat(self.tags, projections,
                                 sort = False, empty_dict = True)

        # Override with changeable stuff set by users
        #
        # Note things such as 'disabled', and 'powered' come from
        # self.fsdb
        # we are unfolding the flat field list l['a.b.c'] = 3 we get
        # from fsdb to -> r['a']['b']['c'] = 3
        l += self.fsdb.get_as_slist(*projections)
        r = commonl.flat_slist_to_dict(l)

	# mandatory fields, override them all
        if commonl.field_needed('owner', projections):
            owner = self.owner_get()
            if owner:
                r['owner'] = owner
            else:
                # forcibly delete the key if it might have existed
                # from the tags or fsdb
                try:
                    del r['owner']
                except KeyError:
                    pass

        # these two fields are synthetic, they don't exist on fsdb, we
        # create them from the allocator information
        _queue_needed = commonl.field_needed('_alloc.queue', projections)
        _queue_preemption_needed = \
            commonl.field_needed('_alloc.queue_preemption', projections)
        if _queue_needed or _queue_preemption_needed:
            waiters, preempt_in_queue = \
                allocation._target_queue_load(self)
            if _queue_needed:
                if waiters:
                    r.setdefault('_alloc', {})
                    # override with this format
                    r['_alloc']['queue'] = {}
                    for prio, ts, flags, allocid, _ in reversed(waiters):
                        r['_alloc']['queue'][allocid] = dict(
                            priority = prio,
                            timestamp = int(ts),
                            preempt = 'P' in flags,
                            exclusive = 'E' in flags,
                        )
            if _queue_preemption_needed:
                r.setdefault('_alloc', {})
                r['_alloc']['queue_preemption'] = preempt_in_queue

        # Timestamp comes from the allocation database, since when we
        # refresh on any operation, it is refreshed there.
        # Note there is corresponding code in
        # ttbl.test_target.property_*() to handle this exception
        if commonl.field_needed('timestamp', projections):
            # COMPAT: timestamp field; all new code shall move to
            # _alloc.timestamp
            r['timestamp'] = self.timestamp_get()
        if commonl.field_needed('_alloc.timestamp', projections):
            r.setdefault('_alloc', {})['timestamp'] = self.timestamp_get()
        return r


    @property
    def type(self):
        return self.tags['type']

    @type.setter
    def type(self, new_type):
        assert isinstance(new_type, str)
        self.tags['type'] = new_type
        return self.tags['type']

    @property
    def acquirer(self):
        return self._acquirer

    @acquirer.setter
    def acquirer(self, new):
        assert isinstance(new, acquirer_c)
        self._acquirer = new
        return new

    def get_id(self):
        return self.id

    @classmethod
    def _user_files_create(cls, who):
        """
        Ensures the directory where the user can create files exists
        """
        userdir = os.path.join(cls.files_path, who_split(who)[0])
        try:
            os.makedirs(userdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise RuntimeError("%s: cannot create user storage path: %s"
                                   % (userdir, e))


    def _tags_verify_interconnect(self, name, data):
        if '#' in name:
            real_name, _instance = name.split("#", 1)
        else:
            real_name = name
        ic = self.get(real_name)
        if ic == None:
            self.log.warning("target declares connectivity to interconnect "
                             "'%s' that is not local, cannot verify; "
                             "if it is local, declare it before the targets "
                             "using it" % real_name)
        for key, val in list(data.items()):
            # FIXME: verify duped addresses
            if key in ["ipv4_addr", "ipv6_addr"]:
                proto = key.replace("_addr", "")
                # Just to verify if it checks as an address
                _ic_addr = ipaddress.ip_address(str(val))
                net = ipaddress.ip_network(
                    str(val + "/" + str(data[proto + "_prefix_len"])),
                    strict = False)
                if ic:
                    _ic_addr = ic.tags[key]
                    ic_net = ipaddress.ip_network(
                        str(_ic_addr + "/"
                                + str(ic.tags[proto + "_prefix_len"])),
                        strict = False)
                    if ic_net != net:
                        logging.warning(
                            "%s: IP address %s for interconnect %s is outside "
                            "of the interconnect's network %s (vs %s)" % (
                                self.id, val, name, ic_net, net))
            if key == "ipv4_prefix_len":
                val = int(val)
                assert val > 0 and val < 32, \
                    "%s: invalid IPv4 prefix len %d for interconnect %s " \
                    "(valid valuess are 1-31)" % (self.id, val, name)
            if key == "ipv6_prefix_len":
                val = int(val)
                assert val > 0 and val < 128, \
                    "%s: invalid IPv6 prefix len %s for interconnect %s " \
                    "(valid values are 1-127)" % (self.id, val, name)
            if key == "vlan":
                val = int(val)
                assert val >= 0 and val < 4096, \
                    "vlan %d is outside of the valid values 0-4095" % val
                assert 'mac_addr' in data, \
                    "vlan specified without a mac_addr"

    def _tags_verify(self):
        if 'bsp_models' in self.tags:
            assert isinstance(self.tags['bsp_models'], dict), \
                "Value of tag 'bsp_models' has to be a dictionary " \
                "of NAME=LIST-OF-STRS|None"
            for bsp_model in self.tags['bsp_models']:
                assert isinstance(bsp_model, str), \
                "Keys in tag's 'bsp_models' dictionary " \
                "have to be strings"
                # FIXME: so fugly, better use kwailify's schema validator
                assert (isinstance(self.tags['bsp_models'][bsp_model], list) \
                        and all(isinstance(i, str)
                                for i in self.tags['bsp_models'][bsp_model]))\
                    or self.tags['bsp_models'][bsp_model] == None, \
                    "Value of tag 'bsp_models'/%s has to be a list " \
                    "of strings or None"
        if 'idle_poweroff' in self.tags:
            # must be an integer
            assert self.tags['idle_poweroff'] >= 0
        for name, data in  list(self.tags['interconnects'].items()):
            self._tags_verify_interconnect(name, data)
        roles_required = self.tags.get('_roles_required', None)
        if roles_required:
            assert isinstance(roles_required, list), \
                "tag '_roles_required' has to be a list of strings; " \
                "got %s" % type(roles_required)
            count = 0
            for role in roles_required:
                assert isinstance(role, str), \
                    "role #%d in '_roles_required' has to be a string; " \
                    "got %s" % (count, type(role))
                count += 1
        roles_excluded = self.tags.get('_roles_excluded', None)
        if roles_excluded:
            assert isinstance(roles_excluded, list), \
                "tag '_roles_excluded' has to be a list of strings; " \
                "got %s" % type(roles_excluded)
            count = 0
            for role in roles_excluded:
                assert isinstance(role, str), \
                    "role #%d in '_roles_excluded' has to be a string; " \
                    "got %s" % (count, type(role))
                count += 1

    def add_to_interconnect(self, ic_id, ic_tags = None):
        """Add a target to an interconnect

        :param str ic_id: name of the interconnect; might be present in
          this server or another one.

          If named ``IC_ID#INSTANCE``, this is understood as this
          target has multiple connections to the same interconnect
          (via multiple physical or virtual network interfaces).

          No instance name (no ``#INSTANCE``) means the default,
          primary connection.

          Thus, a target that can instantiate multiple virtual
          machines, for example, might want to declare them here if we
          need to pre-determine and pre-assign those IP addresses.

        :param dict ic_tags: (optional) dictionary of tags describing the
          tags for this target on this interconnect.

        """
        assert isinstance(ic_id, str)
        if ic_tags == None:
            ic_tags = {}
        self.tags_update(ic_tags, ic = ic_id)

    def tags_update(self, d = None, ic = None):
        """
        Update the tags assigned to a target

        This will ensure the tags described in *d* are given to the
        target and all the values associated to them updated (such as
        interconnect descriptions, addresses, etc).

        :param dict d: dictionary of tags
        :param dict ic: (optional) the dict d has to be used to only
          update the data of the given interconnect

        It can be used to add tags to a target after it is added to
        the configuration, such as with:

        >>> arduino101_add("a101-03", ...)
        >>> tclf.config.targets["a101-03"].tags_update(dict(val = 34))

        """
        if d != None:
            assert isinstance(d, dict)
        if ic:
            assert isinstance(ic, str)

        if ic == None:
            self.tags.update(d)
        else:
            # FIXME: validate interconnects is a dict
            self.tags['interconnects'].setdefault(ic, {}).update(d)

        # Once updated, we verify them and let it fail raising an
        # assertion if something is wrong
        self._tags_verify()
        commonl.kws_update_from_rt(self.kws, self.tags)

    def timestamp_get(self):
        """
        Return an integer with the timestamp of the last activity on
        the target.

        See :meth:timestamp.

        :return str: timestamp in the format YYYYMMDDHHSS
        """
        # if no target-specific timestamp is set, just do zero; we
        # cache it instead of using the allocation's since the target
        # might have not been allocated yet
        with self.lock:
            allocdb = self._allocdb_get()
            if allocdb:
                ts = allocdb.timestamp_get()
                self.fsdb.set('timestamp', ts)
                return ts
            # if there is no timestamp, forge the Epoch
            return self.fsdb.get('timestamp', "19700101000000")

    def timestamp(self):
        """
        Indicate this target is being used

        The activity is deemed as the user is using the target for
        something actively; most accesses to the target when it is
        acquired are considered activity.
        """
        with self.lock:
            allocdb = self._allocdb_get()
            if allocdb:
                self.fsdb.set('timestamp', allocdb.timestamp())

    def allocid_get_bare(self):
        return self.fsdb.get('_alloc.id')

    def _allocid_wipe(self):
        self.fsdb.set('_alloc.id', None)
        self.fsdb.set('_alloc.queue_preemption', None)
        self.fsdb.set('_alloc.priority', None)
        self.fsdb.set('_alloc.ts_start', None)
        self.fsdb.set('owner', None)

    def _allocid_get(self):
        # return the allocid, if valid, None otherwise
        # needs to be called with self.lock taken!
        assert self.lock.locked()
        _allocid = self.fsdb.get('_alloc.id')
        if _allocid == None:
            return None
        try:
            allocdb = ttbl.allocation.get_from_cache(_allocid)
            return _allocid	# alloc-ID is valid, return it
        except ttbl.allocation.allocation_c.invalid_e:
            logging.info("%s: wiping ownership by invalid allocation/id %s",
                         self.id, _allocid)
            self._state_cleanup(False)
            self._allocid_wipe()
            return None

    def _allocdb_get(self):
        # needs to be called with self.lock taken!
        assert self.lock.locked()
        _allocid = self.fsdb.get('_alloc.id')
        if _allocid == None:
            return None
        try:
            return allocation.get_from_cache(_allocid)
        except allocation.allocation_c.invalid_e:
            logging.info("%s: wiping ownership by invalid allocation/get %s",
                         self.id, _allocid)
            self._state_cleanup(False)
            self._allocid_wipe()
            return None


    def _deallocate_simple(self, allocid):
        # Siple deallocation -- if the owner points to the
        # allocid, just remove it without validating the
        # allocation is valid
        #
        # This is to be used only when we have taken the target but
        # then have not used it, so there is no need for state clean
        # up.
        #
        # NOTE: ttbl.allocation.allocdb_c.delete() does the same as
        # this because we know it to be the case
        assert self.lock.locked()	    # Must have target.lock taken!
        current_allocid = self.fsdb.get("_alloc.id")
        if current_allocid and current_allocid == allocid:
            self._allocid_wipe()
            return True
        return False

    # FIXME: move to _deallocate(allocdb), needs changes to use
    # allocdb in
    #  - _target_allocate_locked(): current_allocid -> current_allocdb
    #    - _run_target(): current_allocid -> current_allocdb
    #  - _deallocate
    #  - _deallocate_forced
    #  - release()
    #
    # fold _deallocate_forced() to have a state argument that if set,
    # sets the reservation's state to that one
    #
    # NOTE: ttbl.allocation.allocdb_c.delete() does the same as
    # this because we know it to be the case
    def _deallocate(self, allocdb, new_state = None):
        # deallocate verifying the current allocation is valid
        if self._deallocate_simple(allocdb.allocid):
            self._state_cleanup(False)
            # we leave the reservation as is; if someone is using it
            # they are keepaliving and they'll notice the state
            # change and act; otherwise it will timeout and be removed
            # FIXME: if all targets released, release reservation?
            if new_state:
                allocdb.state_set('restart-needed')

    def allocid_get(self):
        with self.lock:
            return self._allocid_get()

    def owner_get_v1(self):
        """
        Return who the current owner of this target is

        :returns: object describing the owner
        """
        # OLD acquisition method
        return self._acquirer.get()

    def owner_get(self):
        """
        Return who the current owner of this target is

        :returns: object describing the owner
        """
        # OLD acquisition method
        acquirer_owner = self._acquirer.get()
        if acquirer_owner:
            return acquirer_owner
        # NEW allocator
        return self.fsdb.get('owner')

    def acquire(self, who, force):
        """
        Assign the test target to user *who* unless it is already
        taken by someone else.

        :param str who: User that is claiming the target
        :raises: :class:`test_target_busy_e` if already taken
        """
        assert isinstance(who, str)
        try:
            if self._acquirer.acquire(who, force):
                self._state_cleanup(True)
        except acquirer_c.busy_e:
            raise test_target_busy_e(self, who, self.owner_get())
        # different operations in the system might require the user
        # storage area to exist, so ensure it is there when the user
        # acquires a target -- as he might need it.
        self._user_files_create(who)
        self.log.log(9, "acquired by '%s'", who)

    def enable(self, who = None):
        """
        Enable the target (so it will be regularly used)

        :param str who: Deprecated
        """
        self.fsdb.set('disabled', None)

    def disable(self, who = None):
        """
        Disable the target (so it will not be regularly used)

        It still can be used, but it will be filtered out by the
        client regular listings.

        :param str who: Deprecated
        """
        self.fsdb.set('disabled', "True")

    def property_set(self, prop, value):
        """
        Set a target's property

        :param str prop: Property name
        :param str value: Value for the property (None for deleting)

        Due to the hierarchical aspect of the key property namespace,
        if a property *a.b* is set, any property called *a.b.NAME*
        will be cleared out.
        """
        # See ttbl.test_target.to_dict(): these properties are
        # generated, not allowed to set them
        if prop in ( 'timestamp', '_alloc.timestamp' ):
            raise RuntimeError("property '%s' cannot be set" % prop)

        self.fsdb.set(prop, value)
        for key in self.fsdb.keys(prop + ".*"):
            self.fsdb.set(key, None)

    def property_set_locked(self, who, prop, value):
        """
        Set a target's property (must be locked by the user)

        :param str who: User that is claiming the target
        :param str prop: Property name
        :param str value: Value for the property (None for deleting)
        """
        assert isinstance(who, str)
        assert isinstance(prop, str)
        with self.target_owned_and_locked(who):
            self.property_set(prop, value)

    def property_get(self, prop, default = None):
        """
        Get a target's property

        :param str who: User that is claiming the target
        :param str prop: Property name
        """
        # See ttbl.test_target.to_dict(): these properties are
        # generated, not allowed to set them
        if prop in ( 'timestamp', prop == '_alloc.timestamp' ):
            return self.timestamp_get()
        r = self.fsdb.get(prop)
        if r == None and default != None:
            return default
        return r

    def property_get_locked(self, who, prop, default = None):
        """
        Get a target's property

        :param str who: User that is claiming the target
        :param str prop: Property name
        """
        assert isinstance(who, str)
        with self.target_owned_and_locked(who):
            r = self.fsdb.get(prop)
        if r == None and default != None:
            return default
        return r

    def property_is_user(self, name):
        """
        Return *True* if a property is considered a user property (no
        admin rights are needed to set it or read it).

        :returns: bool
        """
        for prop in self.properties_user:
            if isinstance(prop, str):
                if prop == name:
                    return True
                continue
            if isinstance(prop, re.Pattern):
                if prop.match(name):
                    return True
                continue
            raise AssertionError("user property %s: not a string or regex, but %s" \
                % (prop, type(prop).__name__))
        return False

    def property_keep_value(self, name):
        """
        Return *True* if a user property's value needs to be kept.
        """
        for prop in self.properties_keep_on_release:
            if isinstance(prop, str):
                if prop == name:
                    return True
                continue
            if isinstance(prop, re.Pattern):
                if prop.match(name):
                    return True
                continue
            raise AssertionError("user property %s: not a string or regex, but %s" \
                % (prop, type(prop).__name__))
        return False



    def _state_cleanup(self, force):
        """
        Actions to perform on a target when before we release it to
        reset it to clean state

        This takes care of killing existing tunnerls, unplugging
        things or unplugging from targets and calling any release hook
        available.

        We also call this on fresh acquisition of the target, to make
        sure it is the right state (in case a server crashed before
        being able to cleanup on release).
        """
        for release_hook in self.release_hooks:
            release_hook(self, force)
        # Any property set in target.properties_user gets cleared when
        # releasing.
        for prop in list(self.fsdb.keys()):
            if self.property_is_user(prop) and not self.property_keep_value(prop):
                self.fsdb.set(prop, None)

    def release_v1(self, who, force):
        """
        Release the ownership of this target.

        If the target is not owned by anyone, it does nothing.

        :param str who: User that is releasing the target (must be the owner)
        :param bool force: force release of a target owned by
          someone else (requires admin privilege)

        :raises: :class:`test_target_not_acquired_e` if not taken
        """
        assert isinstance(who, str)
        try:
            if self.target_is_owned_and_locked(who):
                self._state_cleanup(force)
            self._acquirer.release(who, force)
        except acquirer_c.cant_release_not_owner_e:
            raise test_target_release_denied_e(self)
        except acquirer_c.cant_release_not_acquired_e:
            raise test_target_not_acquired_e(self)

    def release(self, user, force, ticket = None):
        """
        Release the ownership of this target.

        If the target is not owned by anyone, it does nothing.

        :param ttbl.user_control.User user: User that is releasing the
          target (must be the owner, guest, creator of the reservation
          or admin)

        :param bool force: force release of a target owned by
          someone else (requires admin privilege)

        :raises: :class:`test_target_not_acquired_e` if not taken
        """
        assert isinstance(user, ttbl.user_control.User)
        userid = user.get_id()
        try:
            if self.owner_get_v1():
                if self.target_is_owned_and_locked(userid):
                    self._state_cleanup(force)
                self._acquirer.release(who_create(userid, ticket), force)
                return
            allocid = self.allocid_get_bare()
            if not allocid:
                raise test_target_not_acquired_e(self)
            with self.lock:
                # get the DB, we do this only if alloc.id is defined,
                # since it is a heavier op
                allocdb = self._allocdb_get()
                if allocdb == None:	# allocation was removed...shrug
                    return
                # validate WHO has rights
                if allocdb.check_user_is_user_creator(user):
                    # user or creator can release it; don't change the
                    # state because if the user releases it it means
                    # is because they don't need it, so the allocation
                    # can still proceed working
                    logging.error(
                        "FIXME: delete the allocation if "
                        "there are no more targets")
                    self._deallocate(allocdb)
                elif force and allocdb.check_user_is_admin(user):
                    # if admin and force,
                    self._deallocate(allocdb, 'restart-needed')
                elif allocdb.check_user_is_guest(user):
                    # if guest, just remove it as guest
                    allocdb.guest_remove(user.get_id())
                else:
                    raise test_target_release_denied_e(self)
        except acquirer_c.cant_release_not_owner_e:
            raise test_target_release_denied_e(self)
        except acquirer_c.cant_release_not_acquired_e:
            raise test_target_not_acquired_e(self)

    @contextlib.contextmanager
    def target_owned_and_locked(self, who, requested_state = "active"):
        """
        Ensure the target is locked and owned for an operation that
        requires exclusivity

        :param who: User that is calling the operation
        :raises: :class:`test_target_not_acquired_e` if the target is
          not acquired by anyone, :class:`test_target_busy_e` if the
          target is owned by someone else.
        """
        assert isinstance(who, str), \
            "who %s: who parameter has to be a str; got %s" \
            % (who, type(who).__name__)
        if who == who_daemon():
            # this is the path for executing internal daemon processes
            yield
            return
        userid, ticket = who_split(who)
        with self.lock:
            allocdb = self._allocdb_get()
        if allocdb:
            # New style, allocation based
            state = allocdb.state_get()
            if allocdb.state_get() != requested_state:
                raise test_target_wrong_state_e(self, state, requested_state)
            if not allocdb.check_userid_is_user_creator_guest(userid):
                raise test_target_busy_e(self, userid, self.owner_get())
        else:
            # Old style
            owner = self.owner_get()
            if owner == None:
                raise test_target_not_acquired_e(self)
            if who != owner:
                raise test_target_busy_e(self, who, owner)
        yield

    def target_is_owned_and_locked(self, who, requested_state = "active"):
        """
        Returns if a target is locked and owned for an operation that
        requires exclusivity

        :param who: User that is calling the operation
        :returns: True if @who owns the target or is admin, False
          otherwise or if the target is not owned
        """
        # FIXME: need to overload who to be string or
        # ttbl.user_control.User so we can do admin checks here too?
        assert isinstance(who, str)
        userid, ticket = who_split(who)
        with self.lock:
            allocdb = self._allocdb_get()
        if allocdb:
            # New style, allocation based
            if allocdb.state_get() != requested_state:
                return False
            if not allocdb.check_userid_is_user_creator_guest(userid):
                return False
            return True
        # Old style
        if self.owner_get() == None:
            return False
        if who != self.owner_get():
            return False
        return True

    def interface_add(self, name, obj):
        """
        Adds object as an interface to the target accessible as ``self.name``

        :param str name: interface name, must be not existing already
          and a valid Python identifier as we'll be calling functions
          as ``target.name.function()``

        :param tt_interface obj: interface implementation, an instance
          of :class:`tt_interface` which provides the details and
          methods to call plus
          :meth:`ttbl.tt_interface.request_process` to handle calls
          from proxy/brokerage layers.
        """
        assert isinstance(obj, tt_interface), \
            "obj: expected ttbl.tt_interface; got %s" \
            % type(obj).__name__
        if name in self.tags['interfaces']:
            raise RuntimeError(
                "An interface of type %s has been already "
                "registered for target %s at %s" %
                (name, self.id, self.interface_origin[name]))
        # call this before so it creates the placeholder where driver
        # called by _target_setup() can store stuff
        obj.instrumentation_publish(self, name)
        obj._target_setup(self, name)
        self.interface_origin[name] = commonl.origin_get(2)
        setattr(self, name, obj)
        self.release_hooks.add(obj._release_hook)


    def fsdb_cleanup(self):
        # Cleanup the inventory database for the target
        #
        # As the target's evolve, configurations change, instruments
        # are replaced, etc and some information in the database might
        # become stale.
        #
        # This function navigates the driver tree in the target object
        # looking for the instruments we are using and then removes
        # from the instrumentation and interface inventory tree
        # anything that we know is not in use.
        #
        # note we ignore, in the instrument tree, anythinf that has a
        # "manual" field, since this means this was entered by hand,
        # not by a driver.

        instrument_names_driver = set()
        interface_names = set()
        # Get list of instruments used by the different interfaces; we
        # know these because each driver (impl_c object) as an UPID
        # field that contains it
        # So basically scan the hole driver tree looking for them
        # iterate over all the interfaces, objects attached to @self
        # of type tt_interface
        for attr_name in dir(self):
            if attr_name.startswith("__"):
                continue
            attr = getattr(self, attr_name)
            if not isinstance(attr, ttbl.tt_interface):
                continue

            # yay, got an interface; look for implementation info on it
            interface_names.add(attr_name)
            # some interfaces might be also driver
            # implementations (eg: an interface with a single
            # implementation)
            if isinstance(attr, ttbl.tt_interface_impl_c):
                instrument_names_driver.add(attr.upid_index)
            # but most commonly, interfaces contain a list of
            # implementations
            for impl in attr.impls.values():
                instrument_names_driver.add(impl.upid_index)

        # now collect the list of instruments exposed in the FSDB
        instrument_names_fsdb = set()
        for key in self.fsdb.keys("instrumentation.*"):
            instrument_names_fsdb.add(key.split(".")[1])

        # we got now two sets: the list of instruments we know we have
        # from the driver tree and the ones exposed in the FSDB;
        # remove any that is not in the
        for instrument in instrument_names_fsdb - instrument_names_driver:
            if self.fsdb.get("instrumentation." + instrument + ".manual"):
                continue
            self.fsdb.set("instrumentation." + instrument, None)

        # now let's cleanup leftover interface information
        interface_names_fsdb = set()
        for key in self.fsdb.keys("interfaces.*"):
            interface_names_fsdb.add(key.split(".")[1])
        for interface_name in interface_names_fsdb - interface_names:
            self.fsdb.set("interfaces." + interface_name, None)

class interconnect_c(test_target):
    """
    Define an interconnect as a target that provides connectivity
    services to other targets.
    """
    pass

@contextlib.contextmanager
def open_close(*descrs):
    for descr in descrs:
        descr.open()
    try:
        yield descrs
    finally:
        for descr in descrs:
            descr.close()

class authenticator_c(object):
    """
    Base class that defines the interface for an authentication system

    Upone calling the constructor, it defines a set of roles that will
    be returned by the :func:`login` if the tokens to be authenticated
    are valid.

    The roles are used to determine which targets the user has access
    to.
    """

    @staticmethod
    def login(token, password, **kwargs):
        """Validate an authentication token exists and the password is valid.

        If it is, extract whichever information from the
        authentication system is needed to determine if the user
        represented by the token is allowed to use the infrastructure
        and which with category (as determined by the role mapping)

        :returns: None if user is not allowed to log in, otherwise:

          - a dictionary keyed by string containing user information.

            - field *roles* is a set or list of strings describing the
              roles a logged in user will have in this server. For the
              user to be allowed to log in, at least a role of *user*
              has to be listed. Another pre-defined role is *admin*;
              the rest are site-specific roles.

            - any other field is authenticator-specific data that will
              be stored in the user's database.

              Can be accessed as field *data.FIELDNAME* by drivers
              (*user.fsdb.get("data.FIELDNAME")*) or by clients over the
              HTTP calls (*GET http://SERVER/ttb2-v2/users/USERNAME*)

              Allowed types are: *int*, *float*, *Bool* and *str*.

          - deprecated protocol: a list with all the roles a user has
            access to; see :ref:`access control
            <target_access_control>`.

        """
        assert isinstance(token, str)
        assert isinstance(password, str)
        raise NotImplementedError

    class error_e(ValueError):
        pass

    class unknown_user_e(error_e):
        pass

    class invalid_credentials_e(error_e):
        pass



_daemon_pids = set()
# for who knows what reason hidden in the guts of Unix and probably my
# lack of knowledge, because of the way we are handling the SIGCHLD
# handler to avoid zombies, when we run with subprocess it somehow
# misses the return value--so we have the SIGCHLD handler keep it here
# and if anyone needs it, they can use it; eg
# ttbl.images.flash_shell_cmd_c.flash_check_done()
daemon_retval_cache = commonl.dict_lru_c(32)

def daemon_pid_add(pid):
    _daemon_pids.add(pid)

def daemon_pid_check(pid):
    return pid in _daemon_pids

# This is usually called by the SIGCHLD signal handler
def daemon_pid_rm(pid):
    _daemon_pids.remove(pid)


# util

def usb_serial_number(d):
    #depending on the library version, get the USB string one way or another
    if hasattr(d, 'serial_number'):
        serial_number = d.serial_number
    elif hasattr(d, 'iSerialNumber'):
        serial_number = usb.util.get_string(d, 1000, d.iSerialNumber)
    else:
        raise AssertionError("%s: don't know how to find USB device serial number" % d)
    return serial_number

def _sysfs_read(filename):
    try:
        with open(filename) as fr:
            return fr.read().strip()
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise

def usb_serial_to_path(arg_serial):
    """
    Given a USB serial number, return it's USB path

    Given, eg the serial number *4cb7b886a6b0*, it would return *1-9*,
    as what *lsusb.py* would report::

      $ lsusb.py
      ...
       1-9      06cb:009a ff  2.00   12MBit/s 100mA 1IF  (Synaptics, Inc. 4cb7b886a6b0)
       1-7      8087:0a2b e0  2.00   12MBit/s 100mA 2IFs (Intel Corp.)
       1-10     2386:4328 00  2.01   12MBit/s 96mA 1IF  (Raydium Corporation Raydium Touch System)
       1-3      0bda:5411 09  2.10  480MBit/s 0mA 1IF  (Realtek Semiconductor Corp.) hub
        1-3.4   0bda:5400 11  2.01   12MBit/s 0mA 1IF  (Realtek BillBoard Device 123456789ABCDEFGH)
      ....

    :param str arg_serial: USB serial number
    :return: tuple with USB path, vendor product name for the given serial
      number, *None, None, None* if not found

    """
    def _sysfs_read(filename):
        try:
            with open(filename) as fr:
                return fr.read().strip()
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise

    for fn_serial in glob.glob("/sys/bus/usb/devices/*/serial"):
        serial = _sysfs_read(fn_serial)
        if serial == arg_serial:
            devpath = os.path.dirname(fn_serial)
            return os.path.basename(devpath), \
                _sysfs_read(os.path.join(devpath, "vendor")), \
                _sysfs_read(os.path.join(devpath, "product"))
    return None, None, None


def usb_device_by_serial(arg_serial, sibling_port = None, *fields):
    """Given a device with a given USB serial number, the sysfs path to
    it and maybe the contents of a list of its sysfs fields

    Optionally, do it for one of its siblings (devices connected in
    another port of the same hub); this is mainly use to be able to
    pinpoint devices that have no USB serial number (shame) to
    uniquely identify if we know they are going to be connected next
    to one that does.


    :param str arg_serial: USB serial number

      >>> usb_device_by_serial("4cb7b886a6b0")
      >>> '/sys/bus/usb/devices/1-3.2'

    :param int sibling_port: (optional) work instead on the device
      that is in the same hub as the given device, but in this port
      number.

      eg: given the serial number *4cb7b886a6b0* and the port 4 in this
      configuration::

        $ lsusb.py
        ...
         1-7      8087:0a2b e0  2.00   12MBit/s 100mA 2IFs (Intel Corp.)
         1-10     2386:4328 00  2.01   12MBit/s 96mA 1IF  (Raydium Corporation Raydium Touch System)
         1-3      0bda:5411 09  2.10  480MBit/s 0mA 1IF  (Realtek Semiconductor Corp.) hub
          1-3.4   0bda:5400 11  2.01   12MBit/s 0mA 1IF  (Realtek BillBoard Device 123456789ABCDEFGH)
          1-3.2   06cb:009a ff  2.00   12MBit/s 100mA 1IF  (Synaptics, Inc. 4cb7b886a6b0)
        ....

      >>> usb_device_by_sibling("4cb7b886a6b0", sibling_port = 4)
      >>> '/sys/bus/usb/devices/1-3.4
'
      Here it would return */sys/bus/usb/devices/1-3.4*, since that
      device is connected in port 4 in the same hub as the USB device
      with serial number *4cb7b886a6b0*.

    :param str fields: (optional) list of field from the sysfs
      directory whose values we want to return

      >>> usb_device_by_sibling("4cb7b886a6b0", 4, "busnum", "devnum")

    :return: tuple with USB path and values of fields; if *None*, the
      device in said port does not exist. If the values for the fields
      are *None*, those fields do not exist.

    """
    def _sysfs_read(filename):
        try:
            with open(filename) as fr:
                return fr.read().strip()
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise

    # Look for the serial number, kinda like:
    #
    ## $ grep -r YK18738 /sys/bus/usb/devices/*/serial
    ## /sys/bus/usb/devices/1-3.4.3.4/serial:YK18738
    for fn_serial in glob.glob("/sys/bus/usb/devices/*/serial"):
        serial = _sysfs_read(fn_serial)
        if serial == arg_serial:
            devpath = os.path.dirname(fn_serial)
            if sibling_port != None:
                # We are looking for a sibling, so let's find it and
                # modify devpath to point to it.
                # Replace the last .4 in the directory name by our
                # port number in the arguments and look at that
                # top level devices are BUSNUM-PORTNUMBER, vs after they
                # are BUSNUM-PORTNUMBER.[PORTNUMBER[.PORTNUMBER...]]
                if '.' in devpath:
                    separator = "."
                else:
                    separator = "-"
                head, _sep, _tail = devpath.rpartition(separator)
                devpath = head + separator + str(sibling_port)
            if not os.path.isdir(devpath):
                break
            if not fields:
                return devpath
            return [ devpath ] + [
                _sysfs_read(os.path.join(devpath, field))
                for field in fields
            ]

    return None if not fields else [ None ] + [ None for field in fields ]
