#! /usr/bin/python2
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
import urlparse

import __main__
import requests
import usb.core

import commonl
import user_control

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
            return 'target-%s[%s]: %s ' % (target.id, owner, msg), kwargs
        else:
            return 'target-%s: %s ' % (target.id, msg), kwargs

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
        Return a sorted list of tuples *(KEY, VALUE)*s available in the
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
        Return a dictionary of *KEY/VALUE*s available in the
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
          only *string*, *integer*, *float* and *boolean* types,
          limited to a max of 1024

        :parm bool force: (optional; default *True*) if *key* exists,
          force the new value

        :return bool: *True* if the new value was set correctly;
          *False* if *key* already exists and *force* is *False*.
        """
        if not self.key_valid_regex.match(key):
            raise ValueError("%s: invalid key name (valid: %s)" \
                             % (key, self.key_valid_regex.pattern))
        if value != None:
            assert isinstance(value, basestring) and len(value) < 1024
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
    class exception(Exception):
        pass

    class invalid_e(exception):
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
        for _rootname, _dirnames, filenames in os.walk(self.location):
            if pattern:
                filenames = fnmatch.filter(filenames, pattern)
            for filename in filenames:
                if os.path.islink(os.path.join(self.location, filename)):
                    l.append(filename)
        return l

    def get_as_slist(self, *patterns):
        fl = []
        for _rootname, _dirnames, filenames in os.walk(self.location):
            if patterns:	# that means no args given
                use = []
                for filename in filenames:
                    if commonl.field_needed(filename, patterns):
                        use.append(filename)
            else:
                use = filenames
            for filename in use:
                if os.path.islink(os.path.join(self.location, filename)):
                    bisect.insort(fl, ( filename, self.get(filename) ))
        return fl

    def get_as_dict(self, *patterns):
        d = {}
        for _rootname, _dirnames, filenames in os.walk(self.location):
            if patterns:	# that means no args given
                use = []
                for filename in filenames:
                    if commonl.field_needed(filename, patterns):
                        use.append(filename)
            else:
                use = filenames
            for filename in use:
                if os.path.islink(os.path.join(self.location, filename)):
                    d[filename] = self.get(filename)
        return d

    def set(self, key, value, force = True):
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
            elif isinstance(value, basestring):
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

    def get(self, key, default = None):
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


class process_posix_file_lock_c(object):
    """
    Very simple interprocess file-based spinning lock

    .. warnings::

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

    def upid_set(self, name, **kwargs):
        """
        Set :data:`upid` information in a single shot

        :param str name: Name of the physical component that
          implements this interface functionality
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
        assert name == None or isinstance(name, basestring)
        for key, val in kwargs.iteritems():
            assert val == None or isinstance(val, (basestring, int,
                                                   float, bool)), \
                "UPID field '%s' must be string|number|bool; got %s" \
                % (key, type(val))
        self.name = name
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

    >>>     def METHOD_NAME(self, target, who, args, user_path):
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
         *will be streamed starting at the given offset.
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

    def _target_setup(self, target):
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
        elif isinstance(impl, basestring):		# alias...
            aliases[name] = impl			# ...process later
        else:
            raise AssertionError(
                "'%s' implementation is type %s, " \
                "expected %s or str" % (
                    name, type(impl).__name__,
                    self.cls
                ))

    def _aliases_update(self, aliases):
        for alias, component in aliases.iteritems():
            if component not in self.impls:
                raise AssertionError(
                    "alias '%s' refers to an component "
                    "'%s' that does not exist (%s)"
                    % (alias, component, " ".join(self.impls.keys())))
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
                assert isinstance(name, basestring), \
                    "tuple[0] has to be a string, got %s" % type(name)
                assert isinstance(pc, (cls, basestring)), \
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

        for name, impl in kwimpls.items():
            self._init_by_name(name, impl, aliases)
        self._aliases_update(aliases)

    @staticmethod
    def _arg_get(args, name):
        if name not in args:
            raise RuntimeError("missing '%s' argument" % name)
        return args[name]

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
        if not arg_name in args:
            if allow_missing:
                return None, None
            raise RuntimeError("missing '%s' argument" % arg_name)
        arg = args[arg_name]
        if not isinstance(arg, basestring):
            raise RuntimeError("%s: argument must be a string; got '%s'"
                               % (arg_name, type(arg).__name__))
        return self.impl_get_by_name(arg, arg_name)


    def args_impls_get(self, args):
        """
        Return a list of components by name or all if none given

        If no *component* argument is given, return the whole list of
        component implementations, otherwise only the selected one.

        (internal interface)

        :params dict args: dictionary of arguments keyed by argument
          name
        :returns: a list of *(NAME, IMPL)* based on if we got an
          instance to run on (only execute that one) or on all the
          components
        """
        impl, component = self.arg_impl_get(args, 'component',
                                            allow_missing = True)
        if impl == None:
            # no component was specified, so we operate over all the components
            # KEEP THE ORDER
            impls = self.impls.items()
            _all = True
        else:
            impls = [ ( component, impl ) ]
            _all = False
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
        assert component == None or isinstance(component, basestring)
        assert isinstance(call, basestring)
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
        for key, val in upid.iteritems():
            target.property_set(prefix + "." + key, val % kws)
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
        assert isinstance(iface_name, basestring)

        components_by_index = collections.defaultdict(list)
        name_by_index = {}
        upid_by_index = {}
        kws = commonl.dict_missing_c({}, "n/a")
        kws.update(target.kws)
        kws.update(target.fsdb.get_as_dict())
        for component in self.impls.keys():
            # validate image types (from the keys) are valid from
            # the components and aliases
            impl, _ = self.impl_get_by_name(component, "component")
            instrument_name, index = \
                self.instrument_mkindex(impl.name, impl.upid, kws)
            # FIXME: there must be a more efficient way than using
            # pprint.pformat
            components_by_index[index].append(component)
            name_by_index[index] = instrument_name
            upid_by_index[index] = impl.upid

        for index, components in components_by_index.iteritems():
            self.instrumentation_publish_component(
                target, iface_name, index,
                name_by_index.get(index, None), upid_by_index[index],
                components,
                kws = kws)


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

        For an example, see :class:`ttbl.buttons.interface`.
        """
        assert isinstance(target, test_target)
        assert isinstance(who, basestring)
        assert isinstance(method, basestring) \
            and method in ( 'POST', 'GET', 'DELETE', 'PUT' )
        assert isinstance(call, basestring)
        assert isinstance(args, dict)
        assert user_path != None and isinstance(user_path, basestring)
        raise NotImplementedError("%s|%s: unsuported" % (method, call))
        # Note that upon return, the calling layer will add a field
        # 'diagnostics', so don't use that
        #
        #return dict(result = "SOMETHING")
        #
        # to streaming a file
        #
        #return dict(stream_file = CAPTURE_FILE, stream_offset = OFFSET)


# FIXME: yeah, ugly, but import dependency hell
import allocation
import ttbl.config


class test_target(object):

    #! Path where the runtime state is stored
    state_path = "/var/run/ttbd"

    #: Path where files are stored
    files_path = "__undefined__"

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
        self.tags['interfaces'] = []

        # Create the directory where we'll keep the target's state
        self.state_dir = os.path.join(self.state_path, self.id)
        self.lock = process_posix_file_lock_c(
            os.path.join(self.state_path, "lockfile"))
        commonl.makedirs_p(os.path.join(self.state_dir, "queue"), 0o2770)
        #: filesystem database of target state; the multiple daemon
        #: processes use this to store information that reflect's the
        #: target's state.
        if fsdb == None:
            self.fsdb = fsdb_symlink_c(self.state_dir)
        else:
            assert isinstance(fsdb, fsdb_c), \
                "fsdb %s must inherit ttbl.fsdb_c" % fsdb
            self.fsdb = fsdb

        # Much as I HATE reentrant locks, there is no way around it
        # without major rearchitecting that is not going to happen.
        #
        # The ownership lock has to be re-entrant (eg: once locked it
        # can be locked again N times by the same thread, but then it
        # has to be unlocked N times).
        #
        # Why? because things like the image setting procedure
        # (that has to be called with the target locked) might to call
        # the power off routine, that also requires locking the
        # target.
        #
        # At this point, adding locked and unlocked interfaces would
        # make it very complicated -- so we go with a reentrant lock.
        self.ownership_lock = threading.RLock()
        self.timestamp()

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

    @staticmethod
    def get_for_user(target_name, calling_user):
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
        assert isinstance(target_name, basestring)
        assert isinstance(calling_user, ttbl.user_control.User)
        target = ttbl.config.targets.get(target_name, None)
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

          Field names can match :mod:`python.fnmatch` regular
          expressions.
        """

        # Set read-only values from config as base
        # why convert from flat to dict and then back to dict? Well,
        # because it is way easier to filter on flat triyng to keep
        # what has to be there and what not. And the performance at
        # the end might not be much more or less...
        r = commonl.flat_slist_to_dict(
            commonl.dict_to_flat(self.tags, projections))
        # Override with changeable stuff set by users
        #
        # Note things such as 'disabled', and 'powered' come from
        # self.fsdb
        # we are unfolding the flat field list l['a.b.c'] = 3 we get
        # from fsdb to -> r['a']['b']['c'] = 3
        r.update(commonl.flat_slist_to_dict(
            self.fsdb.get_as_slist(*projections)))

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

        return r


    @property
    def type(self):
        return self.tags['type']

    @type.setter
    def type(self, new_type):
        assert isinstance(new_type, basestring)
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
        ic = ttbl.config.targets.get(real_name, None)
        if ic == None:
            self.log.warning("target declares connectivity to interconnect "
                             "'%s' that is not local, cannot verify; "
                             "if it is local, declare it before the targets "
                             "using it" % real_name)
        for key, val in data.iteritems():
            # FIXME: verify duped addresses
            if key in ["ipv4_addr", "ipv6_addr"]:
                proto = key.replace("_addr", "")
                # Just to verify if it checks as an address
                _ic_addr = ipaddress.ip_address(unicode(val))
                net = ipaddress.ip_network(
                    unicode(val + "/" + str(data[proto + "_prefix_len"])),
                    strict = False)
                if ic:
                    _ic_addr = ic.tags[key]
                    ic_net = ipaddress.ip_network(
                        unicode(_ic_addr + "/"
                                + str(ic.tags[proto + "_prefix_len"])),
                        strict = False)
                    if ic_net != net:
                        raise ValueError(
                            "%s: IP address %s for interconnect %s is outside "
                            "of the interconnect's network %s" %(
                                self.id, val, name, ic_net))
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
                assert isinstance(bsp_model, basestring), \
                "Keys in tag's 'bsp_models' dictionary " \
                "have to be strings"
                # FIXME: so fugly, better use kwailify's schema validator
                assert (isinstance(self.tags['bsp_models'][bsp_model], list) \
                        and all(isinstance(i, basestring)
                                for i in self.tags['bsp_models'][bsp_model]))\
                    or self.tags['bsp_models'][bsp_model] == None, \
                    "Value of tag 'bsp_models'/%s has to be a list " \
                    "of strings or None"
        if 'idle_poweroff' in self.tags:
            # must be an integer
            assert self.tags['idle_poweroff'] >= 0
        for name, data in  self.tags['interconnects'].iteritems():
            self._tags_verify_interconnect(name, data)
        roles_required = self.tags.get('_roles_required', None)
        if roles_required:
            assert isinstance(roles_required, list), \
                "tag '_roles_required' has to be a list of strings; " \
                "got %s" % type(roles_required)
            count = 0
            for role in roles_required:
                assert isinstance(role, basestring), \
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
                assert isinstance(role, basestring), \
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
        assert isinstance(ic_id, basestring)
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
            assert isinstance(ic, basestring)

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
        return os.path.getmtime(os.path.join(self.state_dir, "timestamp"))

    def timestamp(self):
        """
        Update the timestamp on the target to record last activity tme
        """
        # Just open the file and truncate it, so if it does not exist,
        # it will be created.
        with open(os.path.join(self.state_dir, "timestamp"), "w") as f:
            f.write(time.strftime("%c\n"))
            pass

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
            logging.error("%s: wiping ownership by invalid allocation %s",
                          self.id, _allocid)
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
            logging.error("%s: wiping ownership by invalid allocation %s",
                          self.id, _allocid)
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
        assert isinstance(who, basestring)
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
        assert isinstance(who, basestring)
        assert isinstance(prop, basestring)
        with self.target_owned_and_locked(who):
            self.property_set(prop, value)

    def property_get(self, prop, default = None):
        """
        Get a target's property

        :param str who: User that is claiming the target
        :param str prop: Property name
        """
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
        assert isinstance(who, basestring)
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
            if isinstance(prop, basestring):
                if prop == name:
                    return True
                continue
            if isinstance(prop, re._pattern_type):
                if prop.match(name):
                    return True
                continue
            raise AssertionError, \
                "user property %s: not a string or regex, but %s" \
                % (prop, type(prop).__name__)
        return False

    def property_keep_value(self, name):
        """
        Return *True* if a user property's value needs to be kept.
        """
        for prop in self.properties_keep_on_release:
            if isinstance(prop, basestring):
                if prop == name:
                    return True
                continue
            if isinstance(prop, re._pattern_type):
                if prop.match(name):
                    return True
                continue
            raise AssertionError, \
                "user property %s: not a string or regex, but %s" \
                % (prop, type(prop).__name__)
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
        for prop in self.fsdb.keys():
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
        assert isinstance(who, basestring)
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
        assert isinstance(who, basestring), \
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
        assert isinstance(who, basestring)
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
        obj._target_setup(self)
        self.tags['interfaces'].append(name)
        self.interface_origin[name] = commonl.origin_get(2)
        setattr(self, name, obj)
        self.release_hooks.add(obj._release_hook)

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

        :returns: None if user is not allowed to log in, otherwise a
          list with user's information; see :ref:`access control
          <target_access_control>`.

        """
        assert isinstance(token, basestring)
        assert isinstance(password, basestring)
        raise NotImplementedError

    class error_e(ValueError):
        pass

    class unknown_user_e(error_e):
        pass

    class invalid_credentials_e(error_e):
        pass

_daemon_pids = set()

def daemon_pid_add(pid):
    _daemon_pids.add(pid)

def daemon_pid_check(pid):
    return pid in _daemon_pids

# This is usually called by the SIGCHLD signal handler
def daemon_pid_rm(pid):
    _daemon_pids.remove(pid)
