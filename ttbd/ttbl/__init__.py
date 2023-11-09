#! /usr/bin/env python3
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
import functools
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
import warnings

import __main__
import requests
import serial
import serial.tools.list_ports
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
                    self.release()
                    raise
                time.sleep(self.wait)
                ts = time.time()
                if ts - ts0 > self.timeout:
                    self.release()
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
        assert name == None or isinstance(name, str)
        assert name == None or "%(" not in name, \
            f"name: admits no templating; got '{name}'"
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
        #: base keywords for templaing for this implementation; see
        #: :meth:`ttbl.test_target.kws_figure`
        #:
        #: Each of this NAME keys will be available in fields called
        #: _impl.NAME for templating.
        self.kws = None


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
            assert val == None or isinstance(val, (str, int, float, bool)), \
                "UPID field '%s' must be string|number|bool; got %s" \
                % (key, type(val))
            # None values we don't place'm
            if val == None:
                continue
            # use update so we can accumulate values from inherited classes
            self.upid[key] = val
        if not self.name:
            self.name = name_long
        self.upid['name_long'] = name_long


    def target_setup(self, target, iface_name, component):
        """
        Called when the interface is added to a target to initialize
        anything specific to the target, such as data in the inventory.

        Remember *self* should not be used to store runtime data,
        since this is a multiprocess server
        """
        pass


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
        pass


    def _allocate_hook(self, target, iface_name, allocdb):
        """
        Called when the target is allocated
        """
        pass


    def _release_hook(self, target, force):
        # FIXME: move to public interface
        # FIXME: remove force, unuused
        """
        Called when the target is released
        """
        pass


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
        warnings.warn(
            "impl_add() is deprecated in favour of target.interface_impl_add()",
            DeprecationWarning, stacklevel = 4)


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
        assert isinstance(impls, collections.abc.Iterable)
        assert isinstance(kwimpls, dict), \
            "impls must be a dictionary keyed by console name; got %s" \
            % type(impls).__name__
        assert issubclass(cls, object)

        # initialize for interface_impl_add()
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
        if args == None:
            args = dict()
        else:
            assert isinstance(args, dict), \
                f"args: expected dict, got {type(args)}"
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
    def instrument_mkindex(name, upid):
        # we don't use the name to make the UPID, since we might have
        # multiple components with different name using the same HW
        # instrument
        index = commonl.mkid(pprint.pformat(upid), l = 4)
        return name, index

    def instrumentation_publish_component(
            self, target, iface_name,
            index, instrument_name, upid, components = None):
        """
        Publish in the target's inventory information about the
        instrumentations that implements the functionalities of the
        components of this interface
        """

        assert components == None or isinstance(components, list)
        if index == None:
            instrument_name, index = \
                self.instrument_mkindex(instrument_name, upid)
        prefix = "instrumentation." + index
        properties_flat = []
        properties_flat.append(( prefix + ".name", instrument_name ))
        for key, val in upid.items():
            if val:
                # there might be empty values, as defaults, so we ignore them
                if isinstance(val, str):
                    # if it is a string, it is a template
                    try:
                        properties_flat.append(( prefix + "." + key, val ))
                    except ( ValueError, TypeError ) as e:
                        # don't use target.log --> not fully
                        # initialized yet
                        logging.error(
                            f"{target.id}: possible formatting error for val '{val}': {e}")
                        raise
                else:
                    properties_flat.append(( prefix + "." + key, val ))
        if components:
            properties_flat.append((
                prefix + ".functions." + iface_name, ":".join(components) ))
            # declare the index for the component
            for component in components:
                properties_flat.append((
                    f"interfaces.{iface_name}.{component}.instrument", index ))
        else:
            properties_flat.append((
                prefix + ".functions." + iface_name, True ))
        # setting properties 1:1 can be less eficient than bulk upload
        target.properties_flat_set(properties_flat)



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
        for component in list(self.impls.keys()):
            # validate image types (from the keys) are valid from
            # the components and aliases
            impl, _ = self.impl_get_by_name(component, "component")
            instrument_name, index = \
                self.instrument_mkindex(impl.name, impl.upid)
            tags_interface[component] = {
                # this is also in instrumentation_publish_component so
                # it can work also when adding components after the
                # fact
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
                components)
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
            self.fsdb = commonl.fsdb_symlink_c(self.state_dir)
        else:
            assert isinstance(fsdb, commonl.fsdb_c), \
                "fsdb %s must inherit commonl.fsdb_c" % fsdb
            self.fsdb = fsdb

        #: Keywords that can be used to substitute values in commands,
        #: messages. Target's tags are translated to keywords
        #: here. :func:`ttbl.config.target_add` will update this with
        #: the final list of tags.
        #:
        #: See :meth:`ttbl.test_target.kws_collect` for a unified
        #: function to make this into a dictionary of keywords that
        #: can be used in different environments (mostly drivers) to
        #: expand configuration templates.
        self.kws = {}

        #: Functions to call when the target is allocated
        self.allocate_hooks = dict()

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
        if not isinstance(user, ttbl.user_control.User):
            # not logged in, AnonymousUserMixin or similar which we
            # get sent by Flask or whoever is wrapping us, which we
            # don't want to know here.
            return False
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


    def kws_collect(self, impl = None, kws = None):
        """
        Create/update a key/value dictionary with the target's
        tags/inventory and optionally information from the
        implementations UPID and keywords.

        This dictionary can be used for templating with
        :func:`commonl.kws_expand`

        :param dict kws: (optional; default created)
          commonl.dict_missing_c({}, "n/a")

        :returns dict: flat key dictionary
        """
        assert impl == None or isinstance(impl, tt_interface_impl_c)
        assert kws == None or isinstance(kws, dict)

        if kws == None:
            kws = dict()
        # see to_dict(), very similar
        l = commonl.dict_to_flat(self.tags,
                                 sort = False, empty_dict = True)
        # fstb can overwrite tags, per policy
        l += self.fsdb.get_as_slist()
        kws.update(self.kws)
        kws.update(l)
        # now expand implementation's keywords with _upid. and _impl. prefixes
        if impl:
            for key, value in impl.upid.items():
                kws["_upid." + key] = value
        if impl and impl.kws:
            for key, value in impl.kws.items():
                kws["_impl." + key] = value
        return kws


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


    #: List of properties that can't be set
    properties_forbidden =  ( 'timestamp', '_alloc.timestamp' )


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
        if prop in self.properties_forbidden:
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



    def properties_flat_set(self, props_and_values):
        """
        Set a list of target's properties

        :param str props_and_values: list of *(key, value)* tupples in
          flat format

        Due to the hierarchical aspect of the key property namespace,
        if a property *a.b* is set, any property called *a.b.NAME*
        will be cleared out.

        """
        # See ttbl.test_target.to_dict(): these properties are
        # generated, not allowed to set them

        for prop, value in props_and_values:
            if prop in self.properties_forbidden:
                raise RuntimeError("property '%s' cannot be set" % prop)
        self.fsdb.set_keys(props_and_values)



    def properties_flat_set_locked(self, who, props_and_values):
        """
        Set a list of target's properties (must be locked by the user)

        :param str who: User that is claiming the target

        Rest of parameters as of :meth:`properties_flat_set`
        """
        assert isinstance(who, str)
        with self.target_owned_and_locked(who):
            for prop, value in props_and_values:
                if prop in self.properties_forbidden:
                    raise RuntimeError("property '%s' cannot be set" % prop)
            self.fsdb.set_keys(props_and_values)



    def property_get(self, prop, default = None):
        """
        Get a target's property

        :param str who: User that is claiming the target
        :param str prop: Property name

        This function gets properties from multiple locations, in the
        following order, returning the first hit:

        - from the FSDB (properties set in realtime in the
          target's database)

        - tags (as tag[PROP.SUBPROP.SUBSUBPROP])

        - deep tags (as tag[PROP][SUBPROP][SUBSUBPROP]

        - default

        How we control fsdb properties shading tags is because
        we don't allow setting certain properties that could
        shadow tags.
        """
        if prop in ( 'timestamp', '_alloc.timestamp' ):
            return self.timestamp_get()
        r = self.fsdb.get(prop)
        if r != None:
            return r
        # try flat key tags[field.subfield.subfield]
        r = self.tags.get(prop, None)
        if r != None:
            return r
        # try non-flat key tags[field.subfield.subfield]
        if '.' in prop:
            subfields = prop.split(".")
            d = self.tags
            fields_left = len(subfields)
            for field in subfields:
                fields_left -= 1
                try:
                    v = d[field]
                    if fields_left == 0:	# found it!
                        return v
                except TypeError:	# d is not a dictionary
                    if fields_left == 0:
                        return v
                    break
                except KeyError:	# d is a dict but that key doesn't exist
                    break
                if not isinstance(v, dict):
                    break
                d = v
        return default


    def property_get_locked(self, who, prop, default = None):
        """
        Get a target's property

        :param str who: User that is claiming the target
        :param str prop: Property name
        """
        assert isinstance(who, str)
        with self.target_owned_and_locked(who):
            return self.property_get(prop, default = default)


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
        # FIXME: rename obj -> iface
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
        for component, impl in obj.impls.items():
            # initialize implementations, if any
            # self is target, obj is iface
            impl.target_setup(self, name, component)
        self.interface_origin[name] = commonl.origin_get(2)
        setattr(self, name, obj)
        self.release_hooks.add(obj._release_hook)
        self.allocate_hooks[name] = obj._allocate_hook


    def interface_impl_add(self, iface_name, component, impl):
        """
        Append a new implementation to the list of implementations
        this interface supports.

        This can be used after an interface has been declared, such
        as:

        >>> target = ttbl.test_target('somename')
        >>> target.interface_add('power', ttbl.power.interface(*power_rail))
        >>> target.interface_impl_add("power", 'newcomponent', impl_object)

        :param str component: implementation's name
        :param impl: object that defines the implementation; this must
          be an instance of the class :data:`cls` (this gets set by the
          first call to :meth:`impls_set`.
        """
        iface = getattr(self, iface_name)
        aliases = {}
        iface._init_by_name(component, impl, aliases)
        iface._aliases_update(aliases)
        impl.target_setup(self, iface_name, component)

        instrument_name, instrument_index = \
            iface.instrument_mkindex(impl.name, impl.upid)

        impl.upid_index = instrument_index
        iface.instrumentation_publish_component(
            self, iface_name,
            instrument_index,
            instrument_name,
            impl.upid, [ component ])


    def fsdb_cleanup_initial(self, *key_globs):
        """
        This cleans an initial list of fields that might be lefover
        from previous executions. fsdb_cleanup() below is called
        once th econfiguration is done, but it is not good enough.
        now collect the list of instruments exposed in the FSDB

        This has to be called before actually running the target
        configuration sequence:

        >>> target = ttbl.test_target()
        >>> target.fsdb_cleanup_initial("sometree.*", "anothertree.*")

        Ensures that data in the FSDB for trees *sometree* and
        *anothertree* is wiped but doesn't touch others.
        """
        # Note this is a hacky solution; we also wipe interfaces
        # (since only we, not the user, should be polking therer).
        # FIXME: a proper solution will involve keeping track of who
        # wrote what so that user sets are understood and kepts and
        # everything else is wiped upon reinitialization.
        # There is a task to encode information such as that in the
        # key name (including ACLs and when the key has to be
        # wiped). This should be added there.
        commonl.assert_list_of_strings(key_globs, "key globs", "glob")
        for key in self.fsdb.keys("interfaces.*"):
            self.fsdb.set(key, None)

        # wipe any other set of keys described in config
        for key_glob in key_globs:
            for key in self.fsdb.keys(key_glob):
                self.fsdb.set(key, None)


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

    @staticmethod
    def auth_with_headers(headers):
        """
        Method that receives headers and tries to authenticate a user with
        them.  it should return an objects of the User class, or None if the
        headers are not valid
        """
        return None

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

def sys_device_fields(bus, *fields, **filters):
    """
    Find a device in the sysfs tree based on filters and report the
    value of the given fields

    :param str bus: bus name (from */sys/bus/BUSNAME*)

    :param fields: strings describing the fields to report; these are
      files in the sysfs path for the device

      eg:

      >>> sys_device_fields('usb', 'busnum', 'devnum')

      would return the values of the *busnum* and *devnum* files on
      each device in the USB tree.

    :param filters: things to filter for; file is the name of a file
      in the device path and the value needs to match that provided

      eg:

      >>> sys_device_fields('usb', 'busnum', 'devnum',
      >>>                   'idProduct' = "1138")

      would file for devices which have a *idProduct* file with *1138*
      as content.

    :returns dict: dictionary keyed by the device's sysfs path (eg:
      */sys/bus/usb/XYZ*); value is a dictionary keyed by field name
      and their values. If a field was not present, it'll be *None*.
    """
    r = {}

    def _sysfs_read(filename):
        try:
            with open(filename) as fr:
                return fr.read().strip()
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            return None

    def _check_fields():
        for filter_name, filter_value in filters.items():

            if not os.path.isdir(dev_path):
                return False

            value = _sysfs_read(os.path.join(dev_path, filter_name))
            if filter_value != value:
                return False

        return True

    for dev_path in glob.glob(f"/sys/bus/{bus}/devices/*"):

        if _check_fields():
            r[dev_path] = {}
            for field in fields:
                r[dev_path][field] = _sysfs_read(os.path.join(dev_path, field))

    return r


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

def usb_serial_to_path(arg_serial, sibling_port = None):
    """
    Given a USB serial number, return it's USB path

    DEPRECATED: use ttbl.device_resolver_c()


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
    :param int sibling_port: (optional) work instead on the device
      that is in the same hub as the given device, but in this port
      number.
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
            if sibling_port != None:
                if '.' in devpath:
                    separator = "."
                else:
                    separator = "-"
                head, _sep, _tail = devpath.rpartition(separator)
                devpath = head + separator + str(sibling_port)
            return os.path.basename(devpath), \
                _sysfs_read(os.path.join(devpath, "vendor")), \
                _sysfs_read(os.path.join(devpath, "product"))
    return None, None, None


def usb_device_by_serial(arg_serial, sibling_port = None, *fields):
    """Given a device with a given USB serial number, the sysfs path to
    it and maybe the contents of a list of its sysfs fields

    DEPRECATED: use ttbl.device_resolver_c()

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


def tty_by_usb_serial_number(usb_serial_number):
    """
    DEPRECATED: use ttbl.device_resolver_c()
    """

    ports = serial.tools.list_ports.comports()
    f = filter(lambda port: port.serial_number == usb_serial_number, ports)
    try:
        port = next(f)
        return port.device
    except StopIteration:
        raise RuntimeError(
            f"Cannot find TTY with USB Serial #{usb_serial_number}")

class late_resolve_tty_by_usb_serial_number(str):
    """
    Given a USB serial number, resolve it to a TTY device only when we
    are trying to use it.

    DEPRECATED: use ttbl.device_resolver_c()

    :param str serial_number: USB Serial Number

    When converting to a string (and only when doing that) it will be
    resolved to a USB path. If no such USB device is present, an
    exception will be raised. Otherwise, something like::

      */dev/ttyUSB0*

    will be returned
    """
    def __init__(self, usb_serial_number):
        assert isinstance(usb_serial_number, str)
        self.usb_serial_number = usb_serial_number

    def __str__(self):
        return ttbl.tty_by_usb_serial_number(self.usb_serial_number)


def console_generation_set(target, console):
    # internal to the ttbl.console interface, but needed here since
    # also other drivers call it to reset the generation of consoles
    # they expose.
    target.fsdb.set("interfaces.console." + console + ".generation",
                    # trunc the time and make it a string
                    str(int(time.time())))


class device_resolver_c:

    def __init__(self, target: ttbl.test_target,
                 spec: str, property_name: str = None,
                 spec_prefix: str = "usb,#",
                 deep_match: bool = False):
        """Resolve a device specification to a list of sysfs device paths,
        TTY names, etc

        To use, in any function that requires a device instantate
        right before needing to use (eg: on :meth:`ttbl.power.impl_c.on`)

        >>> dr = ttbl.device_resolver_c(target, "pnp,id:PNP0501")
        >>> dr = ttbl.device_resolver_c(target, "usb,#8220814000,##:1.0",
        >>>                             f"instrumentation.{self.upid_index}.device_spec")
        >>> dr = ttbl.device_resolver_c(target, "usb,#203183BA85F,##__.2.3")
        >>> dr = ttbl.device_resolver_c(target, "203183BA85F",
        >>                              spec_prefix = "usb,#")
        >>> dr = ttbl.device_resolver_c(target, "usb,idVendor=1a86,idProduct=7523,##:1.0")

        Match USB device that is connected to a controller connected
        on PCI slot 2; in this machine, the host controller is PCI;
        PCI exposes, when available and machine dependent, a file
        called label that says "SLOT 2" (*SLOT%202* URL encoded); this
        then would match that USB device when connected to the root
        controller that is in the PCI slot labelled as "SLOT 2":

        >>> dr = ttbl.device_resolver_c(target, "usb,idVendor=1a86,idProduct=7523,deep_match,label=SLOT%202,##:1.0")

        Same thing, but match on the top level USB device (vs the interface):

        >>> dr = ttbl.device_resolver_c(target, "usb,idVendor=1a86,idProduct=7523,deep_match,label=SLOT%202,!bInterfaceClass")

        This works because the top level UBS device path lacks the
        *bInterfaceClass* file.

        Note how for most USB devices you might need to also specify
        the interface (with *##1.0*), since drivers attach to
        interfaces and devices might have multiple.

        Them you can query a list of devices that match the spec:

        >>> devicel = dr.devices_find_by_spec()
        >>> ttyl = dr.ttys_find_by_spec()
        >>> tty = dr.tty_find_by_spec()

        Eventually the device specification would come from some
        initial configuraiton directive and optionally a property can
        be specified to runtime override it. It is highly
        recommendable to add a property to override, so if there is a
        need to replace the instrument, it can't be done without
        having to restart the daemon.

        :param ttbl.test_target target: target which will use this
          device resolver.

        :param str spec: always a str so it can be easily specified in
          config files; it's general form is::

            BUS,FIELD=VALUE,...FIELD:VALUE,..FIELD=VALUE

          - *BUS* is a bus in */sys/bus*

          - *usb,#SERIAL[,##USBRELATIVEPATH][,FIELD[=VALUE]][,FIELD[=VALUE]][,!FIELD]*

            if instead of = it is :, VALUE it is considered a
            regex. '!FIELD' matches if the *FIELD* does not exist.

            - *#SERIAL* is short for *serial=SERIAL*

              This is meant to match /sys/bus/*/devices/*/serial

            - *##USBRELATIVEPATH* is short for *relative=PATH*

              *relative* can be used to:

              - address a device that has multiple interfaces::

                   usb,#A5195F,##:4.0

                means add interface denomination *:4.0* to the USB
                device with serial number *A5195F*

              - address a USB device that has no serial number but is
                in a fixed positon to one that has.

                For example, is in 13-4.5.2.3 and it has no serial
                number, but on 13-4.5.1.1 there is a device with
                serial number *203183BA85F*. So we can say that our
                device is two levels up, and then on 2.3 from there::

                  usb,#203183BA85F,##__.2.3"

                Each underscore (_) at the beginning of the relative
                path means *remove one path level from the end*
                (*13-4.5.1.1* becomes *13-4.5*) and then add *.2.3* to
                *13-4.5.2.3*.

            - *SERIAL*: a serial number, when it doesn't contain a bus
              prefix or anything that can be interpreted as such will
              be prefixed with *spec_prefix* (eg: *usb,#*); this is
              meant to simplify cases where a device will be always
              USB, for example.

            A missing *VALUE* is interpreted as *True*

            Keys and values can be URL encoded to include weird chars
            or comma (,), = and :.

            Fields will be matched against the sysfs fields in
            */sys/bus/BUSNAME/DEVICE*.

            If deep match is enabled (via parameter or by setting
            *deep_match* in the fields, the parents will be tried
            until reaching */sys/devices* and call a mismatch. eg:

            >>> val = urllib.parse.quote("key=:,=")

            Special fields:

            - *usb_depth* (int, >= 0): depth in the USB tree; 0 means
              the device is connected to a root port; 1 to a hub
              connected to a root hub; 2 to a hub connected to a
              hub...

              Eg: a product with ID 3f41 connected via two hubs

              >>> spec = "usb,idProduct=3f41,usb_depth=2"


          - */dev/SOMEDEV*

        :param str property_name: (optional, default *None*) if
          defined, try to get the value by scanning *property* in the
          target.

          The recommended property  name is

          >>> "instrumentation.xxxx.device_spec"

          where *xxxx* is a four alphanumeric characters (see
          :class:`tt_interface_impl_c`), which can be obtained from any
          interface implementation driver on
          :data:`tt_interface_impl_c`.

          >>> f"instrumentation.{self.upid_index}.device_spec")

        :param str spec_prefix: (optional) when the device
          specification has no recognizeable bus prefix, what shall be
          added to it. eG; if the spec is just *12345* (rather than
          *usb,#12345*) we can't tell what it is, but it is easier to
          update.

          So if the code knows that most devices for this drivers will
          be USB, we can make it easier to specify them and set
          @spec_prefix to *usb,#* (or *usb,serial=*) which will
          convert the spec into *usb,#12345*.


        :param bool deep_match: (optional, default *False*) when
          enabled, enables matching of fields in parents of each
          device. If disabled, it can be enabled by adding
          *deep_match* as a field, eg:

          >>> spec = "usb,deep_match,SOMEFIELD=VALUE..."

        **PENDING**

        - expand target' kws in device spec when present

        - support URL form device_spec (for network based devices)

        """

        assert isinstance(spec, str), \
            f"spec: expecting string, got {type(spec)}"
        assert isinstance(target, ttbl.test_target), \
            f"target: expecting ttbl.test_target, got {type(target)}"
        assert isinstance(property_name, str), \
            f"property_name: expecting string, got {type(spec)}"
        self.spec = spec
        self.target = target
        self.property_name = property_name
        if spec_prefix:
            assert isinstance(spec_prefix, str), \
                "spec_prefix: expected string BUS,FIELDS;" \
                f" got {type(spec_prefix)}"
            self.spec_prefix = spec_prefix
        else:
            self.spec_prefix = ""
        self.deep_match = deep_match

    # Valid device spec absolute prefixes for relative specs
    spec_prefixes_regex = re.compile(
        "^("
        # BUS,FIELDS...(we might support @ in the future)
        "[0-9A-Za-z]+[,@]"
        "|"
        # URLs
        "[-+a-zA-Z0-9]://"
        "|"
        # Local file system
        "/dev/"
        "])")

    def spec_get(self):
        """
        Return a resolved device specification and where it is
        resolved from (builtin or from the current property)

        This allows us to override the spec in a property, when needed

        :returns: ( spec, origin )
        """
        def _prefix_q(spec):
            if self.spec_prefixes_regex.search(spec):
                return spec    # absolute bus specification
            # no BUS specification, might be just a serial, add the prefix
            return self.spec_prefix + spec

        # Get the value of the spec, overriding with a property (if specified)
        if self.property_name:
            spec = self.target.property_get(self.property_name, None)
            if spec != None:
                return _prefix_q(spec), f"from property {self.property_name}"

        return _prefix_q(self.spec), "builtin"



    def _match_value(self, match_value, value):
        #
        # See if match_value matches value
        #
        # match_value might be a regex or a string
        if isinstance(match_value, re.Pattern):
            m = match_value.search(value)
            if not m:
                return False
            return True
        if value != match_value:
            return False
        return True


    @staticmethod			# static, so shared by instances
    def _usb_depth_count(usb_path: str) -> int:
        # Calculate USB device's depth
        #
        # Note we lru_cache this, since we'll call it repeatedly to
        # test for stuff, so it's pointless to recalculate
        #
        # $ ls /sys/bus/usb/devices/
        # 1-0:1.0  2-3:1.0    3-0:1.0  3-3.1.1     ...
        # 2-0:1.0  2-3.1:1.0  3-3      3-3.1:1.0   ...
        # 2-3      2-3.2      3-3.1    3-3.1.1:1.0 ...
        # 2-3.1    2-3.2:1.0  3-3:1.0  3-3.1.2     ...
        # $ ls /sys/bus/usb/devices/
        # 1-0:1.0  2-3:1.0    3-0:1.0  3-3.1.1     ...
        # 2-0:1.0  2-3.1:1.0  3-3      3-3.1:1.0   ...
        # 2-3      2-3.2      3-3.1    3-3.1.1:1.0 ...
        # 2-3.1    2-3.2:1.0  3-3:1.0  3-3.1.2     ...
        #
        # Depth in the USB tree is how many periods the name has, each
        # dot being a port in hub.
        #
        # take the file name from /sys/bus/usb/devices/DEVICE/MAYBESOMETHING
        name = usb_path.split("/")[5]
        # remove trailing :WHATEVER (USB interface info which also
        # contains periods)
        name = name.split(":")[0]
        return name.count(".")



    # synth fields makers keyed by fuction, value a string denoting
    # who registered them
    _synth_fields_makers = {

    }


    @classmethod
    def synth_fields_maker_register(cls, fn: callable):
        """Register a function that can be used to generate
        synthetic information fields in for a /sysfs
        device path; these are later used to match

        :param callable fn: Function that will be called; it must
          follow the pattern:

          >>> def function(sys_path: str, expensive: bool) -> dict:
          >>>    d = dict()
          >>>    # do some discovery on sys_path (/sys/bus/usb/devices/1-3.4)
          >>>    # ... eg:
          >>>    # d['mydev_capacity_mib'] = "45"
          >>>    # d['mydev_speed_gbps'] = "2.3"
          >>>    return d

          *expensive* is a switch that says if this is being called on
          the cheap or expensive path; each function needs to
          determine if they are expensive (takes a lot of resources
          or not); if called on the expensive path, then they can
          proceed, otherwise they need to return no fields.

          The return field is a dictionary keyed by string of simple
          scalar values (normally strings, others might be adde
          later). By convention, please prefix all the keys
          *SOMETHING_NAME* where something is a common namespace.

          If it finds errors, it can raise an exception; in that case
          the entry for the device will not be matched and will not be
          cached when resolving with :meth:`devices_find_by_spec`
          (which is the base for all resolving calls).

          This function will be called when there is no entry in the
          cache for a device entry in */sys/bus/BUSNAME/devices* and
          */sys/devices* that is needed to resolve a device in
          :meth:`devices_find_by_spec`. Those entries will also be
          called when the device changes (replugged) since its
          directory entry changes ctime. Changes downstream of the
          device (eg: something it's connected to) cannot be detected
          by this unless the directory entrie's ctime is changed.

        """
        origin = commonl.origin_get(2)
        if fn in cls._synth_fields_makers:
            raise ValueError(
                f"{fn} already registered from {cls._synth_fields_makers[fn]}")
        cls._synth_fields_makers[fn] = origin



    @staticmethod
    def synthetic_fields_make(sys_path: str, expensive: bool) -> dict:
        """Create descriptive
        fields/values for a given device

        :param str sys_path: path in /sys for the device

        :param bool expensive: if *True* we are in the path where
          computational/IO expensive fields can be generated;
          otherwise, we are in the cheap path.

          While this is very relative, expensive paths shall stick to
          taking five seconds, cheap way less than one second.

        :returns dict: dict keyed by field name of values found

        Note these values WILL be cached by the path of the device
        until that device disspears/is reconnected.
        """
        @commonl.lru_cache_disk(
            os.path.realpath(
                os.path.join(
                    # FIXME: ugh, we need a global for daemon
                    # cache path, then this can be moved up
                    # outside of here

                    # Also, we need this defined here so state_path is defined
                    ttbl.test_target.state_path,
                    "..", "cache", "device_resolver_c.synthetic_fields_make"
                )
            ),
            # Don't age; when the device reconnects, the cache entry
            # will change (since the ctime in hte
            # /sys/bus/usb/devices/DEVNAME will change) and old ones
            # will be flushed
            None,
            # a fully loaded system can have lots of entries in
	    # /sys/devices once you start dealing with parents and
	    # stuff -- ~665 USB entries that describe around ~300USB
            # devices and their interfaces need about 36 parent
            # devices (PCI devices, etc) for a total of ~700 entries
            # to cache the USB devices in a live system
            1024,
            exclude_exceptions = [ Exception ])
        def _synthetic_fields_make(sys_path: str,
                                   expensive: bool, _stat_info_st_ctime: int):
            # _stat_info_st_ctime is there only to serve for caching, so
            # when the same device is replugged, it ctime for its /sys dir
            # will be different so we'll rescan it.
            #
            # So is expensive: to cache differently expensive vs cheap

            cost = "expensive" if expensive else "cheap"
            logging.error(f"{sys_path}: synthesizing {cost} fields"
                          f" for {_stat_info_st_ctime=}")
            fields = {}
            if sys_path.startswith('/sys/bus/usb/devices'):
                # This is USB, count its depth and expose it (0 -> N)
                fields['usb_depth'] = str(device_resolver_c._usb_depth_count(sys_path))
                #logging.error(f"{sys_path}: USB depth {usb_depth}")

            for fn, origin in device_resolver_c._synth_fields_makers.items():
                logging.error(
                    f"{sys_path}: {fn}@{origin} synthesizing {cost} fields")
                try:
                    new_fields = fn(sys_path, expensive)
                    commonl.assert_dict_key_strings(new_fields,
                                                    "synthetic fields")
                except Exception as e:
                    logging.error(f"{sys_path}: {fn}@{origin}/{cost}"
                                  f" errored: {e}", exc_info = True)
                    # raise this to bomb the creation of a cache entry
                    # for this device and also so it fails matching,
                    # since we don't have enough info -> we catch this
                    # in _match_fields_to_files()
                    raise
                logging.error(
                    f"{sys_path}: {fn}@{origin} synthesized {cost} {new_fields}")
                fields.update(new_fields)

            logging.info(f"{sys_path}: synthesized fields {fields}")
            return fields

        # get the ctime for the entry, since it is updated everytime
        # this thing is plugged / hot plugged, which will force a
        # re-generatio of the cached info
        stat_info = os.stat(sys_path)

        return _synthetic_fields_make(sys_path, expensive, stat_info.st_ctime)



    def _match_fields_to_files(self, fields, path_original,
                               expensive: bool = False):
        # matches dict of fields against files with the same name in
        # path
        #
        # Mostly used against sysfs directories to find devices
        #
        # So we start with path_original -> /sys/bus/BUSNAME/devices/DEVICETHING
        #
        # for each field, we test against than dir and if we don't
        # find the file/field in there, we try one directory up, etc.
        #
        match = False

        # use this to cache, in this call the synthetic fields for
        # each path, since we'll access it a lot and even the other
        # cache we have would be too hard
        fields_synth_by_path = {}

        cost = "expensive" if expensive else "cheap"

        for match_field, match_value in fields.items():
            path = path_original
            while True:
                # first path is always /sys/bus/BUSNAME/devices/DEVENTRY
                #logging.error(f"{path_original}: checking"
                #              f" {match_field}:{match_value} in {path}")
                try:

                    # synthetic fields take preference over sysfs
                    # fields since they might have massaged them, and
                    # if we don't match there, it's a missamtch, we
                    # don't fall back to /sysfs

                    try:
                        fields_synth = fields_synth_by_path.setdefault(
                            path, self.synthetic_fields_make(path, expensive))
                        logging.debug(
                            "%s: %s synth fields in path %s: %s",
                            path_original, cost, path, fields_synth)
                    except Exception as e:
                        # we couldn't generate extra info, so we will
                        # bomb this entry right away and refuse to
                        # match against it
                        logging.error(f"{path}: {cost} synth fields generations"
                                      f" failed; no match: {e}")
                        return False

                    if match_field in fields_synth:
                        value = fields_synth[match_field]
                        match = self._match_value(match_value, value)
                        field_type = "synth"
                    else:
                        with open(path + "/" + match_field) as f:
                            # need rstrip() to remove trailing newline
                            value = f.read().rstrip()
                        field_type = "sysfs"
                        match = self._match_value(match_value, value)
                    if not match:
                        logging.debug(
                            "%s: MISMATCH for %s %s check %s:'%s' in %s",
                            path_original, field_type, cost, match_field, match_value, path)
                        return False
                    logging.debug(
                        "%s: MATCH for %s %s check %s:'%s' in %s",
                        path_original, field_type, cost, match_field, match_value, path)
                    break	# we matched, so next field
                except IOError as e:
                    if e.errno != errno.ENOENT:
                        #logging.error(f"{path_original}: error {e} matching"
                        #              f" {match_field}:{match_value} in {path}")
                        return False	# whatever happend, didn't
                    if match_value == None:
                        # we are looking for this field not to exist;
                        # the file doesn't exist, so we good
                        logging.debug(
                            "%s: MISSING for %s %s check %s:'%s' in %s",
                            path_original, field_type, cost,
                            match_field, match_value, path)
                        break		# match! file doesn't exist

                    # if we are not doing deep match, we can't
                    # check the parents of this device for
                    # matches, so we call it done here; otherwise, we
                    # fall through
                    if self.deep_match == False:
                        return False
                    # match file/field does not exist, no match, try
                    # one levelup; note we are now checking on the
                    # parent of this device
                    real_path = os.path.realpath(path)
                    path = os.path.dirname(real_path)
                    #logging.error(f"{path_original}: going up to {path}"
                    #              f" for {match_field}")
                    if path == "/sys/devices":
                        return False	# file does not exist, no match

        return True



    def _match_fields_make(self, spec: str):
        #
        # Create a dictionary of match fields from a string
        #
        # :param str spec: comma separated list of fields (see class doc)
        #
        # :return dict: keyed by field name, value being regex or
        #   string to match against
        fieldl = spec.split(",")
        fields_cheap = { }
        fields_expensive = { }
        fields = None
        for field in fieldl:
            # we unquote with urllib, so we can put in there
            # values which have = or :
            if field.startswith("+"):
                fields = fields_expensive
                field = field[1:]
            else:
                fields = fields_cheap
            if field == "deep_match":
                self.deep_match = True
                continue
            elif field.startswith("##"):
                # shorthand ##SIBLING -> relative=SIBLING
                key = 'relative'
                val = urllib.parse.unquote(field[2:])
            elif field.startswith("#"):
                # shorthand #SERIAL -> serial=SERIAL
                key = 'serial'
                val = urllib.parse.unquote(field[1:])
            elif field.startswith("!"):
                # shorthand for field is missing
                key = field[1:]
                val = None
            elif '=' in field:
                key, val = field.split('=', 1)
                val = urllib.parse.unquote(val)
            elif ':' in field:
                key, val = field.split(':', 1)
                val = re.compile(urllib.parse.unquote(val))
            else:
                key = field
                val = True
            key = urllib.parse.unquote(key)
            fields[key] = val
        return fields_cheap, fields_expensive



    def _device_relative_apply(self, devbuspath, relative):
        # Given a USB device path (1-3.2) and a relative path from
        # there (up two levels, add 4.2.4), calculate the new absolute
        # USB path.
        #
        # In the relative path _ at the beginning of the string means
        # one level up, __ two, etc. Then we append the rest:
        #
        # 1-3.2   __4.2.4 -> 1-4.2.4
        # 1-4.3.2 _.5     -> 1-4.3.5
        #

        # most bus paths use the chars -.: to separate components
        def _split_incl_splitter(s: str, splitters = "-.:"):
            # Splits a string along any char in splitters, including the
            # splitter char at the end; I'm sure there is a Python func for
            # it, but I can't find it
            #
            # eg: 1-3.4.1 -> 1- 3. 4. 1
            l = []
            last = 0
            index = 0
            for c in s:
                index += 1
                if c in splitters:
                    l.append(s[last:index])
                    last = index
            l.append(s[last:])
            return l

        levels_up = 0
        downstream = ""
        # calculate how many levels we have to remove from
        # 1-3.2; each leading _ removes one level (eg: __ means 1-, _
        # means 1-3.) Downstream is what we have to append after removing
        for c in relative:
            if c != "_":
                downstream = relative[levels_up:]
                break
            levels_up += 1

        # split 1-3.2 in 1-, 3. 2 (note we keep the split character)
        devbuspathl = _split_incl_splitter(devbuspath)

        if levels_up >= len(devbuspathl):
            # if removing too many levels up, well nothing
            return None
        # so now get the top level -> 1-
        if levels_up == 0:
            # I guess I lernt [:0] wipes it...
            top_l = devbuspathl
        else:
            top_l = devbuspathl[:-levels_up]

        # Now recompose with the final object
        # /sys/bus/usb/devices/1-4.2.4
        return "".join(top_l) + downstream



    def devices_find_by_spec(self, spec: str = None, origin: str = None,
                             only_one: bool = False):
        """Return list of devices that match the specificatoin

        Params are the same as for the class and in most cases, not
        needed, just for internal use.

        :param bool only_one: short cut and return the first device
          found; this can significantly cut resolution times if it is
          known that only one device will be found.

        :returns list[str]: syfs paths to */sys/bus/BUSNAME/devices/DEVICE*,
          since those we can match with multiple things

        """
        if spec == None:
            spec, origin = self.spec_get()
        else:
            assert isinstance(spec, str)
            assert isinstance(origin, str)

        # let's get the bus type; spec is BUS
        bus, spec_bus = spec.split(",", 1)

        busdir = f"/sys/bus/{bus}/devices"
        if not os.path.isdir(busdir):
            raise RuntimeError(
                f"{spec} [@{origin}]: can't resolve;"
                f" bus directory {busdir} does not exist")

        # convert spec_bus into a dict keyed by field name, value is
        # either a string or a regex to match againt
        fields_cheap, fields_expensive = self._match_fields_make(spec_bus)
        # the relative field is handled separately, so remove it
        # because it won't match against anything in the device
        relative = fields_cheap.get('relative', None)
        if relative != None:
            del fields_cheap['relative']

        # now iterate over busdir; eg, for USB, /sys/bus/usb/devices/*:
        #
        ## lrwxrwxrwx. 1 root root 0 Mar 25 01:18 1-0:1.0 -> ../../../devices/pci0000:00/0000:00:14.0/usb1/1-0:1.0
        ## lrwxrwxrwx. 1 root root 0 Mar 25 01:18 1-10 -> ../../../devices/pci0000:00/0000:00:14.0/usb1/1-10
        ## lrwxrwxrwx. 1 root root 0 Mar 25 01:18 1-10:1.0 -> ../../../devices/pci0000:00/0000:00:14.0/usb1/1-10/1-10:1.0
        ## ...
        #
        # for each entry, there are files in that dir; for each field
        # in fields, find a file with that name, read it, match on our
        # value; if missing file or mismatch, that's a miss
        #
        # Filter allt he devices that match, because we might have to
        # do extra filtering later
        devicel = []
        for device_path in glob.glob(busdir + "/*"):
            match = self._match_fields_to_files(fields_cheap, device_path,
                                                expensive = False)
            if not match:
                continue

            # Ok, there was a match -- now match against the expensive
            # fields these are fields that to generate might require
            # more cost, so by doing the filtering in two steps we
            # defer the generation of the expensive fields to a
            # reduced number of devices
            match = self._match_fields_to_files(fields_expensive, device_path,
                                                expensive = True)
            if not match:
                continue

            # ok, device_patch was a match -- do we have to apply relative?
            device = os.path.basename(device_path)
            if relative:
                # we have a relative path to what was found, so let's
                # transform it -- a relative path __.3.4
                device_modified = self._device_relative_apply(
                    device, relative)
                if device_modified:
                    devicel.append(busdir + "/" + device_modified)

            else:
                devicel.append(device_path)
            if only_one:
                break
        self.target.log.info("device paths resolved from %s @%s: %s",
                             spec, origin, " ".join(devicel))
        return devicel



    def device_find_by_spec(self, spec: str = None, origin: str = None):
        """
        Find a single device, complain if it is none or more than one

        Otherwise, same as :meth:`devices_find_by_spec`
        """
        devices = self.devices_find_by_spec(spec, origin)
        if not devices:
            spec, origin = self.spec_get()
            raise RuntimeError(
                f"{self.target.id}: "
                f"found no devices matching device spec {spec} @{origin}")
        devicen = len(devices)
        if devicen > 1:
            spec, origin = self.spec_get()
            raise RuntimeError(
                f"{self.target.id}: "
                f"found {devicen} devices matching device spec"
                f" {spec} @{origin}, expected only one: "
                + ", ".join(devices))
        return devices[0]



    sysfs_tty_globs = [
        # this catches when a tty device is in the top level, such as
        # USB devices specified just a a serial number; if a USB
        # device specifies a single serial port, this makes it work
        "*/tty*", "*/tty/tty*",
        # this catches a tty device that is a subdevice (eg, in a USB
        # device interface)
        "tty*", "tty/tty*"
    ]

    def ttys_find_by_spec(self):
        """
        Return a list of TTY device nodes (eg: /dev/ttyUSB3) that
        match the device specification.

        :returns list[str]: list of device nodes that match the
          specification at the current time

        Note this might change with time based on:

        - what devices are connected to the system

        - the value of the spec set in the property
        """
        spec, origin = self.spec_get()
        if spec.startswith("/dev/"):	# a plain device node? just pull it
            self.target.log.info("TTY resolved to device path %s @%s",
                                 spec, origin)
            return [ spec ]

        # Ok, list all devices that match the spec
        matching_portl = []
        devicel = self.devices_find_by_spec(spec, origin)
        if not devicel:
            self.target.log.info("No TTYs can be resolved to %s @%s",
                                 spec, origin)
            return matching_portl

        # While we could try to map directly instead of using
        # comports(), we'd have to re-do a lot of that logic since
        #
        ## $ readlink -e /sys/class/tty/ttyACM12
        ## /sys/devices/pci0000:3a/0000:3a:00.0/0000:3b:00.0/0000:3c:09.0/0000:40:00.0/usb9/9-1/9-1.1/9-1.1.1/9-1.1.1.1/9-1.1.1.1:1.0/tty/ttyACM12
        ## $ readlink -e /sys/class/tty/ttyUSB2
        ## /sys/devices/pci0000:5d/0000:5d:00.0/0000:5e:00.0/0000:5f:09.0/0000:63:00.0/usb17/17-1/17-1.2/17-1.2.2/17-1.2.2:1.0/ttyUSB2/tty/ttyUSB2
        ## $ readlink -e 17-1.2.2:1.0
        ## /sys/devices/pci0000:5d/0000:5d:00.0/0000:5e:00.0/0000:5f:09.0/0000:63:00.0/usb17/17-1/17-1.2/17-1.2.2/17-1.2.2:1.0
        ##  readlink -e /sys/class/tty/ttyS0
        ## /sys/devices/pnp0/00:04/tty/ttyS0
        #
        # so looking in the realpath of busdevpath for a tty name
        # (tty/ttyACM*, or ttyUSB*) would get us there--and then just
        # adding /dev--would save a lot of trashing.


        # Now get the list of ttys/comports and see which of them have
        # the same device path as the ones we got in devicel
        for busdevpath in devicel:
            # convert the BUS relative devie patch to an absikute
            # device path
            #
            # /sys/bus/BUS/device/BUSDEVPATH -> device_path
            # '/sys/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3.1/1-3.1.7/1-3.1.7.3/1-3.1.7.3:1.0/
            devpath = os.path.realpath(busdevpath)

            # Ok, under devpath, find the tty device nodes, which are
            # called tty something under tty* or tty/tty*
            #
            # /sys/devices/pci0000:5d/.../13-1.4.1/13-1.4.1.3/13-1.4.1.3:1.0/ttyUSB3
            # /sys/devices/pci0000:5d/.../13-1.4.1/13-1.4.1.3/13-1.4.1.3:1.0/tty/ttyACM2
            # /sys/devices/pnp0/00:03/tty/ttyS0
            for tty_glob in self.sysfs_tty_globs:
                for i in glob.glob(devpath + "/" + tty_glob):
                    basename = os.path.basename(i)
                    if basename == "tty":
                        continue
                    matching_portl.append("/dev/" + basename)

        # yeah, not using filter or any of those. Why? not that many
        # devices, so optimizatio is not such a huge deal (yet). Alo
        # open coding is easier to maintain for some people.
        self.target.log.info("TTYs resolved from %s @%s: %s",
                             spec, origin,
                             " ".join(matching_portl))
        return matching_portl


    def tty_find_by_spec(self):
        """
        Find a single device, complain if it is none or more than one

        Otherwise, same as :meth:`ttys_find_by_spec`
        """
        portl = self.ttys_find_by_spec()
        if not portl:
            spec, origin = self.spec_get()
            raise RuntimeError(
                f"{self.target.id}: "
                f"found no TTYs matching device spec {spec} @{origin}")
        portn = len(portl)
        if portn > 1:
            spec, origin = self.spec_get()
            raise RuntimeError(
                f"{self.target.id}: "
                f"found {portn} (more than one!) TTYs matching device spec"
                " {spec} @{origin}")
        return portl[0]


# Register built-in device resolution helpers
import ttbl.pci
import ttbl.usb

device_resolver_c.synth_fields_maker_register(ttbl.usb.synth_fields_maker)
device_resolver_c.synth_fields_maker_register(ttbl.pci.synth_fields_maker_pexusb3s44v)
