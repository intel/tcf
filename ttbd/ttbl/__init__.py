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
import collections
import contextlib
import errno
import ipaddress
import logging
import os
import random
import re
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
import fsdb
import user_control

logger = logging.root.getChild("ttb")

class test_target_e(Exception):
    """
    A base for all operations regarding test targets.
    """
    pass

class test_target_busy_e(test_target_e):
    def __init__(self, target):
        test_target_e.__init__(
            self,
            "%s: tried to use busy target (owned by '%s')"
            % (target.id, target.owner_get()))

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


class tt_interface(object):
    """
    A target specific interface

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

    When multiple components are used (such as in
    :class:`ttbl.power.interface` or :class:`ttbl.console.interface`.
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


    def request_process(self, target, who, method, call, args, user_path):
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
import ttbl.config

# FIXME: generate a unique ID; has to be stable across reboots, so it
#        needs to be generated from whichever path we are connecting
#        it to
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
        'pos_reinitialize',
        'pos_repartition', 	# deprecated for pos_reinitialize
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
    def __init__(self, __id, _tags = None, _type = None):
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
        if not os.path.isdir(self.state_dir):
            os.makedirs(self.state_dir, 0o2770)
        #: filesystem database of target state; the multiple daemon
        #: processes use this to store information that reflect's the
        #: target's state.
        self.fsdb = fsdb.fsdb(self.state_dir)

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

    def owner_get(self):
        """
        Return who the current owner of this target is

        :returns: object describing the owner
        """
        return self._acquirer.get()

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
            raise test_target_busy_e(self)
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
        """
        self.fsdb.set(prop, value)

    def property_set_locked(self, who, prop, value):
        """
        Set a target's property (must be locked by the user)

        :param str who: User that is claiming the target
        :param str prop: Property name
        :param str value: Value for the property (None for deleting)
        """
        assert isinstance(who, basestring)
        with self.target_owned_and_locked(who):
            self.fsdb.set(prop, value)

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

    def ip_tunnel_list(self, who):
        """
        List existing IP tunnels

        :returns: list of tuples (protocol, target-ip-address, port,
          port-in-server)
        """
        assert isinstance(who, basestring)
        with self.target_owned_and_locked(who):
            tunnel_descs = self.fsdb.keys("tunnel-id-*")
            tunnels = []
            for tunnel_desc in tunnel_descs:
                port_pid = self.fsdb.get(tunnel_desc)
                if port_pid == None:
                    continue
                lport, _pid = port_pid.split(" ", 2)
                tunnel_id = tunnel_desc[len("tunnel-id-"):]
                proto, ip_addr, port = tunnel_id.split("__", 3)
                tunnels.append((proto, ip_addr, port, lport))
            return tunnels

    def _ip_addr_validate(self, _ip_addr):
        ip_addr = ipaddress.ip_address(unicode(_ip_addr))
        for ic_data in self.tags.get('interconnects', {}).itervalues():
            if not ic_data:
                continue
            for key, value in ic_data.iteritems():
                if not key.endswith("_addr"):
                    continue
                if not key.startswith("ip"):
                    # this has to be an IP address...
                    continue
                itr_ip_addr = ipaddress.ip_address(unicode(value))
                if ip_addr == itr_ip_addr:
                    return
        # if this is an interconnect, the IP addresses are at the top level
        for key, value in self.tags.iteritems():
            if not key.endswith("_addr"):
                continue
            itr_ip_addr = ipaddress.ip_address(unicode(value))
            if ip_addr == itr_ip_addr:
                return
        raise ValueError('Cannot setup IP tunnel to IP "%s" which is '
                         'not owned by this target' % ip_addr)

    def _ip_tunnel_args(self, ip_addr, port, proto):
        if port == None:
            port = 'tcp'
        else:
            assert isinstance(port, int)
        if proto:
            proto = proto.lower()
            assert proto in ('tcp', 'udp', 'sctp',
                             'tcp4', 'udp4', 'sctp4',
                             'tcp6', 'udp6', 'sctp6')
        else:
            proto = 'tcp'
        assert port >= 0 and port < 65536
        self._ip_addr_validate(ip_addr)
        return (ip_addr, port, proto)

    def ip_tunnel_add(self, who, ip_addr, port, proto):
        """
        Setup a TCP/UDP/SCTP v4 or v5 tunnel to the target

        A local port of the given protocol in the server is fowarded
        to the target's port. Stop with :meth:`ip_tunnel_remove`.

        If the tunnel already exists, it is not recreated, but the
        port it uses is returned.

        :param who: user descriptor
        :param str ip_addr: target's IP address to use (it must be
          listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param int port: port to redirect to
        :param str proto: (optional) Protocol to tunnel:
          {udp,sctp,tcp}[{4,6}] (defaults to v4 and to TCP)
        :returns int local_port: port in the server where to connect
          to in order to access the target.
        """
        assert isinstance(who, basestring)
        ip_addr, port, proto = self._ip_tunnel_args(ip_addr, port, proto)
        with self.target_owned_and_locked(who):
            tunnel_id = "%s__%s__%d" % (proto, ip_addr, port)
            port_pid = self.fsdb.get("tunnel-id-%s" % tunnel_id)
            if port_pid != None:
                local_ports, pids = port_pid.split(" ", 2)
                local_port = int(local_ports)
                pid = int(pids)
                if commonl.process_alive(pid, "/usr/bin/socat"):
                    return local_port

            local_port = commonl.tcp_port_assigner(
                port_range = ttbl.config.tcp_port_range)
            ip_addr = ipaddress.ip_address(unicode(ip_addr))
            if isinstance(ip_addr, ipaddress.IPv6Address):
                # beacause socat (and most others) likes it like that
                ip_addr = "[%s]" % ip_addr
            p = subprocess.Popen(
                [
                    "/usr/bin/socat",
                    "-ly", "-lp", tunnel_id,
                    "%s-LISTEN:%d,fork,reuseaddr" % (proto, local_port),
                    "%s:%s:%s" % (proto, ip_addr, port)
                ],
                shell = False, cwd = self.state_dir,
                close_fds = True)
            # FIXME: ugly, this is racy -- need a way to determine if
            # this was succesfully run
            time.sleep(0.5)
            if p.returncode != None:
                raise RuntimeError("IP TUNNEL %s: socat exited with %d"
                                   % (tunnel_id, p.returncode))
            daemon_pid_add(p.pid)	# FIXME: race condition if it died?
            self.fsdb.set("tunnel-id-%s" % tunnel_id, "%d %d" %
                          (local_port, p.pid))
            return local_port

    def _ip_tunnel_remove(self, tunnel_id):
        port_pid = self.fsdb.get(tunnel_id)
        if port_pid != None:
            _, pids = port_pid.split(" ", 2)
            pid = int(pids)
            if commonl.process_alive(pid, "/usr/bin/socat"):
                commonl.process_terminate(
                    pid, tag = "socat's tunnel [%s]: " % tunnel_id)
            self.fsdb.set(tunnel_id, None)

    def ip_tunnel_remove(self, who, ip_addr, port, proto = 'tcp'):
        """
        Teardown a TCP/UDP/SCTP v4 or v5 tunnel to the target
        previously created with :meth:`ip_tunnel_add`.

        :param who: user descriptor
        :param str ip_addr: target's IP address to use (it must be
          listed on the targets's tags *ipv4_address* or
          *ipv6_address*).
        :param int port: port to redirect to
        :param str proto: (optional) Protocol to tunnel:
          {udp,sctp,tcp}[{4,6}] (defaults to v4 and to TCP)
        """
        assert isinstance(who, basestring)
        ip_addr, port, proto = self._ip_tunnel_args(ip_addr, port, proto)
        with self.target_owned_and_locked(who):
            self._ip_tunnel_remove("%s:%s:%d" % (proto, ip_addr, port))

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
        for tunnel_id in self.fsdb.keys("tunnel-id-*"):
            self._ip_tunnel_remove(tunnel_id)
        for release_hook in self.release_hooks:
            release_hook(self, force)
        # Any property set in target.properties_user gets cleared when
        # releasing.
        for prop in self.fsdb.keys():
            if self.property_is_user(prop) and not self.property_keep_value(prop):
                self.fsdb.set(prop, None)

    def release(self, who, force):
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

    @contextlib.contextmanager
    def target_owned_and_locked(self, who):
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
        if self.owner_get() == None:
            raise test_target_not_acquired_e(self)
        if who != self.owner_get():
            raise test_target_busy_e(self)
        yield

    def target_is_owned_and_locked(self, who):
        """
        Returns if a target is locked and owned for an operation that
        requires exclusivity

        :param who: User that is calling the operation
        :returns: True if @who owns the target or is admin, False
          otherwise or if the target is not owned
        """
        assert isinstance(who, basestring)
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
    are valid
    """

    @staticmethod
    def login(token, password, **kwargs):
        """Validate an authentication token exists and the password is valid.

        If it is, extract whichever information from the
        authentication system is needed to determine if the user
        represented by the token is allowed to use the infrastructure
        and which with category (as determined by the role mapping)

        :returns: None if user is not allowed to log in, otherwise a
          dictionary with user's information::

          - roles: set of strings describing roles the user has

          FIXME: left as a dictionary so we can add more information later

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
