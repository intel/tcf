#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Internal API for *ttbd*

Note classes names defining general interfaces are expected to end in
_mixin, to be recognized by the auto-lister in
:func:`ttbl.config.target_add`
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
        :param boot force: force the acquisition (overriding current
          user); this assumes the user *who* has permissions to do so;
          if not, raise an exception child of :class:`exception`.

        :raises busy_e: if the target is busy and could not be acquired
        :raises timeout_e: some sort of timeout happened
        :raises no_rights_e: not enough privileges for the operation
        """
        raise NotImplementedError

    def release(self, who, force):
        """
        Release the resource from the given user

        :param str who: user name
        :param boot force: force the release (overriding current
          user); this assumes the user *who* has permissions to do so;
          if not, raise an exception child of :class:`exception`.
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


    def impls_set(self, impls, kwimpls, cls):
        """
        Record in *self.impls* a given set of implementations

        This is only used for interfaces that support multiple components.

        :param list impls: list of objects of type *cls* or of tuples
          *(NAME, IMPL)* to serve as implementations for the
          interface; when non named, they will be called *componentN*
        :param dict impls: dictionary keyed by name of objects of type
          *cls* to serve as implementatons for the itnerface.
        :param type cls: base class for the implementations (eg:
        :class:`ttbl.console.impl_c`)

        """
        assert isinstance(impls, collections.Iterable)
        assert isinstance(kwimpls, dict), \
            "impls must be a dictionary keyed by console name; got %s" \
            % type(impls).__name__
        assert issubclass(cls, object)

        aliases = {}

        def _init_by_name(name, impl):
            if isinstance(impl, cls):
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
                        cls.__name__
                    ))

        count = 0
        for impl in impls:
            if isinstance(impl, tuple):
                assert len(impl) == 2, \
                    "tuple of implementations has to have two elements; " \
                    "got %d" % len(impl)
                name, pc = impl
                assert isinstance(name, basestring), \
                    "tuple[0] has to be a string, got %s" % type(name)
                assert isinstance(pc, cls), \
                    "tuple[1] has to be a %s, got %s" % (cls, type(pc))
                _init_by_name(name, pc)
            elif isinstance(impl, cls):
                _init_by_name("component%d" % count, impl)
            else:
                raise RuntimeError("list of implementations have to be "
                                   "either instances of subclasses of %s "
                                   " or tuples of (NAME, INSTANCE);"
                                   " %s is a %s"
                                   % (cls, impl, type(impl)))
            count += 1

        for name, impl in kwimpls.items():
            _init_by_name(name, impl)

        for alias, component in aliases.iteritems():
            if component not in self.impls:
                raise AssertionError(
                    "alias '%s' refers to an component "
                    "'%s' that does not exist (%s)"
                    % (alias, component, " ".join(self.impls.keys())))
            self.aliases[alias] = component

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
        # List of interfaces that this target supports
        #
        # These are the names of the mixin classes that represent said
        # interfaces implementations. So each base _mixin class has to
        # append the name of the class to this list.

        # NOTE before this was done dynamically doing discovery, but somehow
        # it does not work anymore. We could use a set, but Flask
        # cannot JSONify it. kludge.
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
        self.interface_origin[name] = commonl.origin_get()
        setattr(self, name, obj)
        self.release_hooks.add(obj._release_hook)

class interconnect_impl_c(object):
    pass

class interconnect_c(test_target):
    """
    Define an interconnect as a target that provides connectivity
    services to other targets.
    """
    def __init__(self, name, ic_impl = None, _tags = None, _type = None):
        test_target.__init__(self, name, _tags, _type)
        cls = type(self)
        # FIXME: interfaces should be a set() or auto-discovered from
        # dynamic info
        if not cls.__name__ in self.tags['interfaces']:
            self.tags['interfaces'].append(cls.__name__)
        #: Interconnect implementation
        self.ic_impl = ic_impl


class tt_power_control_impl(object):

    class retry_all_e(Exception):
        """
        Exception raised for a power control implementation operation
        wants the whole power-rail reinitialized
        """
        def __init__(self, wait = None):
            assert wait > 0
            Exception.__init__(self)
            self.wait = wait

    def __init__(self):
        self.power_on_recovery = False

    def power_cycle_raw(self, target, wait = 2):
        """
        Do a raw power cycle

        This does no pre/post actions, just power cycles this
        implementation; used for recovery strategies.

        This is called by the likes of :class:`ttbl.pc.delay_til_usb_device`.

        :param test_target target: target on which to act
        :param int wait: time to wait between power off and on
        """
        self.power_off_do(target)
        time.sleep(wait)
        self.power_on_do(target)

    # Methods to be implemented
    def power_on_do(self, target):
        """
        Flip the power on
        """
        raise NotImplementedError

    def reset_do(self, target):
        """
        Do a reset

        This would ideally trigger a hard reset without a power cycle;
        but it can default to a power-cycle. The power has to be on
        for this to be usable.
        """
        raise NotImplementedError

    def power_off_do(self, target):
        """
        Flip the power off
        """
        raise NotImplementedError

    def power_get_do(self, target):
        """
        Return the power state
        """
        raise NotImplementedError

class tt_power_control_mixin(object):
    """This is the power control interface

    This allows a target to be fully powered off, on, power cycled or
    reset.

    To run functions before power-off or after power-on, add functions
    that take the target object as self to the
    power_(on|off)_(post|pre)_fns lists.

    Power control is implemented with
    :class:`ttbl.tt_power_control_mixin`, which can be
    subclassed or given a subcless of an implementation object
    (:class:`ttbl.tt_power_control_impl`) or a list of them
    (to create a power rail).

    Power rails allow to create complex power configurations where a
    target requires many things to be done in an specific sequence to
    power up (and viceversa to power down). For example, for the
    Arduino101 boards, the following happens::

      power_control = [
        ttbl.pc_ykush.ykush("YK20954", 2),	# Flyswatter2
        # delay power-on until the flyswatter2 powers up as a USB device
        ttbl.pc.delay_til_usb_device(serial = "FS20000"),
        # delay on power off until the serial console device is gone,
        # to make sure it re-opens properly later. It also helps the
        # main board reset properly.
        ttbl.pc.delay_til_file_gone(off = "/dev/tty-arduino101-02"),
        ttbl.pc_ykush.ykush("YK20954", 0),	# serial port
        ttbl.cm_serial.pc(),			# plug serial ports
        ttbl.pc_ykush.ykush("YK20954", 1),	# board
      ],

    this is a six-component power rail, which:

    1. powers a port in a USB hub to power up the Flyswatter2
       (firmware flasher) (with a :class:`ttbl.pc_ykush.ykush`)

    2. waits for the USB device representing said device to show up in
       the system (with :class:`ttbl.pc.delay_til_usb_device`).

    3. (only used during power off) delay until said file is not
       present in the system anymore
       (:class:`ttbl.pc.delay_til_file_gone`); this is used when we
       power off something (like a USB serial device) and we know that
       as a consequence, udev will remove a device node from the
       system.

    4. powers up a serial port

    5. connects the serial ports of the target (once it has been
       powered up in the previous step)

    6. powers up the target itself

    The power off sequence runs in the inverse, first powering off the
    target and then the rest of the components.

    These power rails are often necessary for very small, low power
    devices, that can get resideual power leaks from anywhere, and
    thus anything connected to it has to be powered off (in specific
    sequences) to ensure the board fully powers off.


    The optional tag *idle_poweroff* can be given to the target to
    control how long the target has to be idle before it is powered
    off. If 0, it will never be automatically powered off upon
    iddleness. Defaults to :data:`ttbl.config.target_max_idle`.

    """

    def __init__(self, impl = None):
        self.fsdb.set('powered', None)
        # We could use a set, but Flask cannot JSONify it. kludge.
        c = tt_power_control_mixin
        if not c.__name__ in self.tags['interfaces']:
            self.tags['interfaces'].append(c.__name__)
        # This allows to defer the implementation of the methods to a
        # separate object, so it is quick to change configurations by
        # passing a different type of power controller
        c = tt_power_control_impl
        if isinstance(impl, list):
            for _impl in impl:
                if not isinstance(_impl, tt_power_control_impl):
                    raise TypeError("provided power control implementation "
                                    "list contains an item (type %s) that is "
                                    "not an instance of %s"
                                    % (type(_impl), c.__name__))
        elif isinstance(impl, tt_power_control_impl):
            # We want them all to be a power rail, so change it into
            # it when it is not
            impl = [ impl ]
        elif impl != None:
            raise ValueError("provided power control implementation is not a "
                             "subclass of %s (or list of)" % c.__name__)
        self.pc_impl = impl
        self.power_on_pre_fns = []
        self.power_on_post_fns = []
        self.power_off_pre_fns = []
        self.power_off_post_fns = []
        self.power_state = []

    # Don't override these methods!

    def _power_on_pre(self):
        self.log.debug("pre-on fns %s" % self.power_on_pre_fns)
        for f in self.power_on_pre_fns:
            f(self)

    def _power_on_post(self):
        self.log.debug("post-on fns %s" % self.power_on_post_fns)
        for f in self.power_on_post_fns:
            f(self)

    def _power_on_do(self):
        if getattr(self, "power_on_do", None) != None:
            self.power_on_do(self)
        else:
            retries = 0
            retries_max = 3
            recovery_wait = 0.5
            # Power on in the specified order, off in the reverse
            # We use impl_index instead of iterating so we can reset
            # the index easily without having to deal with
            # StopIteration exceptions and try statements everywhere.
            idx = 0
            while idx < len(self.pc_impl):
                impl = self.pc_impl[idx]
                idx += 1
                self.log.debug("power-on doing %s" % impl)
                try:
                    impl.power_on_do(self)
                    continue
                except impl.retry_all_e as e:
                    retries += 1
                    if retries >= retries_max:
                        raise RuntimeError("power-on: too many retries")
                    self.log.error("power-on %s failed: retrying (%d/%d) "
                                   "the whole power rail: %s",
                                   impl, retries, retries_max, e)
                    try:
                        self._power_off_do()
                    except:	# pylint: disable = bare-except
                        pass	# yeah, we ignore all that happens here
                    idx = 0
                    if e.wait:
                        time.sleep(e.wait)
                    continue
                except Exception as e:
                    self.log.error("power-on %s failed %s, retrying"
                                   % (impl, e))
                # Power cycle this component to try to recover it,
                # give it time to clear up
                try:
                    if impl.power_on_recovery:
                        impl.power_off_do(self)
                except Exception as e:
                    self.log.error("power-on %s recovery (via power off) "
                                   "failed (ignoring): %s" % (impl, e))
                time.sleep(recovery_wait)
                try:	# Maybe let's retry...
                    impl.power_on_do(self)
                    continue
                except Exception as e:
                    self.log.error("power-on %s failed again %s, aborting\n%s"
                                   % (impl, e, traceback.format_exc()))
                    try:
                        self._power_off_do()
                    except:
                        pass
                    raise
        self.fsdb.set('powered', "On")

    def power_on(self, who):
        with self.target_owned_and_locked(who):
            if self.power_get() == True:
                self.log.debug("already powered on")
                return
            self.log.debug("powering on")
            self._power_on_pre()
            self.log.debug("powered on pre")
            self._power_on_do()
            self.log.info("powered on")
            self._power_on_post()
            self.log.debug("powered on post")
            self.fsdb.set('powered', "On")


    def _reset_do(self):
        if getattr(self, "reset_do", None) != None:
	    # Try first if the class has an implementation of reset
            self.reset_do(self)
        elif isinstance(self.pc_impl, tt_power_control_impl):
            self.pc_impl.reset_do(self)
        elif isinstance(self.pc_impl, list):
            for impl in self.pc_impl:
                self.log.debug("reset doing %s" % impl)
                try:
                    impl.reset_do(self)
                    continue
                except NotImplementedError:
                    raise
                except Exception as e:
                    self.log.error("reset %s failed %s, retrying" % (impl, e))
                try:
                    impl.reset_do(self)
                    continue
                except Exception as e:
                    self.log.error("reset %s failed again %s, powering-off\n%s"
                                   % (impl, e, traceback.format_exc()))
                    try:
                        self._power_off_do()
                    except:
                        pass
                    raise
        else:	# There is no power implementation or specifc, so power cycle
            self._power_cycle_do("reset")

    def reset(self, who):
        """
        Reset the target (or power it on if off)
        """
        with self.target_owned_and_locked(who):
            if self.power_get():
                self.log.debug("resetting")
                try:
                    self._reset_do()
                except NotImplementedError:
                    # If there is no reset implementation, we power cycle
                    self._power_cycle_do(tag = 'reset')
                self.log.info("reset")
            else:
                self._power_cycle_do(tag = "reset")

    def _power_off_pre(self):
        self.log.debug("pre-off fns %s" % self.power_off_pre_fns)
        for f in self.power_off_pre_fns:
            f(self)

    def _power_off_post(self):
        self.log.debug("post-off fns %s" % self.power_off_post_fns)
        for f in self.power_off_post_fns:
            f(self)

    def _power_off_do(self):
        if getattr(self, "power_off_do", None) != None:
            self.power_off_do(self)
        elif isinstance(self.pc_impl, tt_power_control_impl):
            self.pc_impl.power_off_do(self)
        elif isinstance(self.pc_impl, list):
            # To power off, we do it in inverse order--in here we have
            # trouble if something fails, what do we do? Well, we
            # retry and then keep moving.
            fe = None
            for impl in reversed(self.pc_impl):
                self.log.debug("power-off doing %s" % impl)
                try:
                    impl.power_off_do(self)
                    continue
                except Exception as e:
                    self.log.error("power-off %s failed %s, retrying"
                                   % (impl, e))
                try:
                    impl.power_off_do(self)
                    continue
                except Exception as e:
                    self.log.error("power-off %s failed again %s, skipping\n%s"
                                   % (impl, e, traceback.format_exc()))
                    fe = e
            if fe != None:
                # pylint gets confused with this
                raise fe	# pylint: disable = raising-bad-type
        else:
            pass	# Nothing to do
        self.fsdb.set('powered', None)

    def power_off(self, who):
        with self.target_owned_and_locked(who):
            # Don't rely on caching, make sure we turn it all off
            self.log.debug("powering off pre")
            self._power_off_pre()
            self.log.debug("powering off")
            self._power_off_do()
            self.log.debug("powering off post")
            self._power_off_post()
            self.log.info("powered off")
            self.fsdb.set('powered', None)

    def _power_cycle_do(self, wait = None, tag = "power cycle"):
        # Note we don't use any HW assisted power cycle, as we need to
        # be able to run power on/off pre/post hooks. So we power off,
        # then we power on. Likewise if we have a power rail, we need
        # to power off everyting, then power it on.

        # Always make sure to power off the whole thing (there
        # might be components in a power rail that are on)
        self.log.debug("%s: turning off (pre)", tag)
        self._power_off_pre()
        self.log.debug("%s: turning off", tag)
        self._power_off_do()
        self.log.debug("%s: turned off (post)", tag)
        self._power_off_post()
        self.log.debug("%s: turned off", tag)
        if wait == None:
            wait = self.tags.get('power_cycle_wait', 5)
        time.sleep(wait)
        # Now flip it on!
        self.log.debug("%s: turning on (pre)", tag)
        self._power_on_pre()
        self.log.debug("%s: turning on", tag)
        self._power_on_do()
        self.log.debug("%s: turned on (post)", tag)
        self._power_on_post()
        self.log.debug("%s: turned on, done", tag)

    def power_cycle(self, who, wait = None):
        """
        Power cycle the target, guaranteeing that at the end, it is
        powered on.

        :param str who: Identity of the user
        :param float wait: how much time to wait before powering on
          after powering off.
        """
        # Note we don't use any HW assisted power cycle, as we need to
        # be able to run power on/off pre/post hooks. So we power off,
        # then we power on. Likewise if we have a power rail, we need
        # to power off everyting, then power it on.
        with self.target_owned_and_locked(who):
            self._power_cycle_do(wait)

    # This is a cache that can be accessed after calling power_get to
    # learn the state of the individual parts; it's a list of (object,
    # state) tuples
    power_state = []

    def power_rail_get(self):
        """
        Return the state of each item of the power rail which powers
        this target.

        :returns list(bool): list of power states for the power rail
          that powers this target.
        """
        power_state = []
        if isinstance(self.pc_impl, tt_power_control_impl):
            powered = self.pc_impl.power_get_do(self)
            if powered != None:
                power_state = [(self.pc_impl, powered)]
            self.log.log(8, "power_get()/%s: %s", self.pc_impl, powered)
        elif isinstance(self.pc_impl, list):
            powered = True
            for impl in self.pc_impl:
                # If anything is off, then the whole thing is off
                _powered = impl.power_get_do(self)
                self.log.log(8, "power_get()[%s]: %s", impl, _powered)
                if _powered == None:
                    # fake power units
                    continue
                power_state.append((impl, _powered))
                if _powered == False:
                    powered = False
        else:
            try:
                powered = self.power_get_do(self)
                if powered != None:
                    power_state = [(self, powered)]
                self.log.log(8, "power_get(): %s", powered)
            except AttributeError as e:
                raise NotImplementedError("%s" % e)
        # Update the cache
        if all(entry[1] for entry in power_state):
            self.fsdb.set('powered', "On")
        else:
            self.fsdb.set('powered', None)
        self.power_state = power_state
        return power_state

    def power_rail_get_any(self):
        """
        Return *True* if any power rail element is on, *False* otherwise.
        """
        power_states = self.power_rail_get()
        return any(entry[1] for entry in power_states)

    def power_get(self):
        """
        Return *True* if all power rail elements are turned on and
        thus the target is on, *False* otherwise.
        """
        states = self.power_rail_get()
        # we are only ON if all states are ON
        return all(entry[1] for entry in states)


class test_target_console_mixin(object):
    """
    bidirectional input/output channel

    FIXME:

    - has to allow us to control a serial port (escape sequences?)
    - buffering? shall it read everything since power on?
    - serial port not necessarily the endpoint, but ability to set
      baud rate and such must be considered
    - more than one channel?
      *console_id* defaults to None, the first one defined by the
      target, which is always available

    """

    class test_target_console_e(IOError):
        pass

    def __init__(self):
        # We could use a set, but Flask cannot JSONify it. kludge.
        c = test_target_console_mixin
        if not c.__name__ in self.tags['interfaces']:
            self.tags['interfaces'].append(c.__name__)

    def console_do_read(self, console_id = None, offset = 0):
        """
        :param offset: Try to read output from given offset
        :returns: an iterator with the output that *HAS TO BE DISPOSED
          OF* with del once done.
        :raises: IndexError if console_id is not implemented,
          ValueError if *all* is not supported.
        """
        raise NotImplementedError

    def console_do_size(self, console_id = None):
        raise NotImplementedError

    def console_do_write(self, data, console_id = None):
        """
        :param data: byte string to write to the console
        """
        raise NotImplementedError

    def console_do_setup(self, console_id = None, **kwargs):
        """
        Set console-specific parameters
        """
        raise NotImplementedError

    def console_do_list(self):
        r"""
        Return list of available *console_id*\s
        """
        raise NotImplementedError

    def console_read(self, who, console_id = None, offset = 0):
        """
        :param int offset: Try to read output from given offset
        :returns: an iterator with the output that *HAS TO BE DISPOSED
          OF* with del once done.
        :raises: IndexError if console_id is not implemented,
          ValueError if *all* is not supported.

        Note the target does not have to be acquired to read off it's
        console. FIXME: makes sense?
        """
        return self.console_do_read(console_id, offset)

    def console_size(self, _who, console_id = None):
        """
        Return how many bytes have been read from the console so far

        :param str console_id: (optional) name of the console
        :returns: number of bytes read
        """
        return self.console_do_size(console_id)

    def console_write(self, who, data, console_id = None):
        """
        :param data: byte string to write to the console
        """
        with self.target_owned_and_locked(who):
            return self.console_do_write(data, console_id)

    def console_setup(self, who, console_id = None, **kwargs):
        """
        Set console-specific parameters
        """
        with self.target_owned_and_locked(who):
            return self.console_do_setup(console_id, **kwargs)

    def console_list(self):
        r"""
        Return list of available *console_id*\s
        """
        consoles = self.console_do_list()
        return consoles

    class expect_e(Exception):		# pylint: disable = missing-docstring
        pass

    class expect_failed_e(expect_e):   	# pylint: disable = missing-docstring
        pass

    class expect_timeout_e(expect_e):	# pylint: disable = missing-docstring
        pass

    #: Consider a timeout a valid event instead of raising
    #: exceptions in :func:`expect`.
    EXPECT_TIMEOUT = -1

    def expect(self, expectations, timeout = 20, console_id = None, offset = 0,
               max_buffering = 4096, poll_period = 0.5, what = ""):
        """
        Wait for any of a list of things to come off the given console

        Waits for a maximum *timeout* to receive from a given console
        any of the list of things provided as *expectations*, checking
        with a *poll_period*.

        :param expectations: list of strings and/or compiled regular
          expressions for which to wait. It can also be the constant
          :data:`EXPECT_TIMEOUT`, in which case, a timeout is a valid
          event to expect (instead of causing a :exc:`exception
          <expect_timeout_e>`.
        :param int timeout: (optional, default 20) maximum time in
          seconds to wait for any of the expectations.
        :param int offset: (optional, default 0) offset into the
          console from which to read.
        :param int max_buffering: (optional, default 4k) how much to
          look back into the read console data.
        :param float poll_period: (optional) how often to poll for new
          data
        :param str what: (optional) string describing what we are
          waiting for (for error messages/logs).
        """
        t0 = time.time()
        t = t0
        # See if timeout should result in an exception or returning an index
        count = 0
        for expectation in expectations:
            if expectation == self.EXPECT_TIMEOUT:
                timeout_index = count
                break
            count += 1
        else:
            timeout_index = None
        # Lame loop, but simple and easy to understand
        while t - t0 < timeout:
            time.sleep(poll_period)
            t = time.time()
            # Note the console_read is giving us already all the data,
            # no need to accumulate it
            fd = self.console_read(self.owner_get(), offset = offset,
                                   console_id = console_id)
            output = fd.read()
            del fd
            if len(output):	# pylint: disable = len-as-condition
                # Filter out any non printables for debugging
                # purposes, otherwise the log is kinda messy to
                # follow
                _output = ''.join([
                    i if i in string.printable and i not in "\r\f\v" else '?'
                    for i in commonl.ansi_regex.sub('', output)
                ])
                max_length = self.fsdb.get("expect_debug_max_length")
                if max_length == None:
                    max_length = 200
                if len(_output) > max_length:
                    _output = "...<snipped>..." + _output[-max_length:]
                self.log.debug("read %dB +@%.2f/%ss [filtered]: %s",
                               len(output), t - t0, timeout, _output)
                if max_buffering and len(output) > max_buffering:
                    output = output[:-max_buffering]
                # Find expectations
                count = 0
                for expectation in expectations:
                    if isinstance(expectation, basestring):
                        expectation = re.compile(re.escape(expectation))
                    elif isinstance(expectation, re._pattern_type):
                        pass
                    elif expectation == self.EXPECT_TIMEOUT:
                        count += 1
                        continue	# we handle this at the end
                    else:
                        raise TypeError(
                            "Bad type for expectation "
                            "'%s': got %s, expected str or regex"
                            % (expectation, type(expectation).__name__))
                    match = expectation.search(output)
                    if match:
                        self.log.info("expect: found match #%d +@%.2f/%ss: %s",
                                      count, t - t0, timeout,
                                      output[match.start():match.end()])
                        return (count, output[match.start():match.end()],
                                len(output), )
                    count += 1
            if t - t0 > timeout:
                msg = "expect: timed out after %ss %s" % (timeout, what)
                self.log.info(msg)
                if timeout_index:
                    return (timeout_index, "", len(output))
                else:
                    raise self.expect_timeout_e(msg)


    def expect_sequence(self, sequence, timeout = 20, offset = 0,
                        console_id = None):
        """Execute a list of expect/send commands to a console

        Each step in the list can first send something, then expect to
        recevive something to pass (or to fail) and then move on to
        the next step until the whole sequence is completed.

        :param sequence: List of dictionaries with the parameters:

          - receive: string/regex of what is expected
          - fail: (optional) strings/regex of something that if received
            will cause a failure
          - send: (optional) string to send after receiving *pass*
          - wait: (optional) integer of time to wait before sending *send*
          - delay: (optional) when sending *send*, delay *delay* seconds
            in between characters (useful for slow readers)

          e.g.::

             [
               dict(receive = re.compile("Expecting number [0-9]+"),
                    fail = re.compile("Error reading"),
                    send = "I am good",
                    wait = 1.3, delay = 0.1),
               dict(receive = re.compile("Expecting number 1[0-9]+"),
                    fail = re.compile("Error reading"))
             ]

        :param int timeout: (optional, default 20s) maximum time in
          seconds the operation has to conclude
        :param int offset: (optional, default 0) offset from which to
          read in the console.
        :param int console_id: (optional) console to use to read/write
        :returns: Nothing if everything went well, otherwise raises
          exceptions :class:`expect_timeout_e` or :class:`expect_failed_e`.

        """

        count = 0
        t0 = time.time()
        for data in sequence:
            receive = data.get('receive', None)
            fail = data.get('fail', None)
            send = data.get('send', None)
            wait = data.get('wait', 0)
            delay = data.get('delay', 0)
            if send:
                if wait:
                    time.sleep(wait)
                if delay:
                    for c in send:
                        self.console_write(self.owner_get(), c,
                                           console_id = console_id)
                        time.sleep(delay)
                else:
                    self.console_write(self.owner_get(), send,
                                       console_id = console_id)
            this_sequence = [ self.EXPECT_TIMEOUT ]
            if fail:
                this_sequence.append(fail)
            # Always check for failures first
            pass_index = len(this_sequence)
            if receive:
                this_sequence.append(receive)
            self.log.info("expect/send phase %d: Waiting for '%s'"
                          % (count, this_sequence))
            index, matched, offset = self.expect(
                this_sequence, timeout = timeout,
                offset = offset, console_id = console_id)
            t = time.time()
            timeout -= t - t0
            if index == 0:
                raise self.expect_timeout_e(
                    count,
                    "expect/send phase %d: Timeout waiting for '%s'"
                    % (count, this_sequence ))
            elif index > 0 and index < pass_index:
                raise self.expect_failed_e(
                    count,
                    "expect/send phase %d: received failure string '%s'"
                    % (count, matched))
            count = count + 1


class test_target_images_mixin(object):	# COMPAT
    class error(Exception):
        pass

    class unsupported_image_e(error):
        pass

    """This mixin defines a list of images (OS, BIOS, Firmware...) that
    can be uploaded to the target broker and deployed into a target.

    The following image types are supported:

     - bios[.X]: bios file X
     - fw[.X]: Firmware file X
     - kernel: a kernel to boot
     - initramfs: an initramfs for said kernel
     - hd[.X]: OS image for hardrive *X*

    The X's are specific to the target and serve to distinguish when
    there have to be many of them.

    The imaging procedure takes control over the target, possibly
    powering it on and off. Note however that after setting, the
    target will be left in the powered off state.

    """
    def __init__(self):
        # We could use a set, but Flask cannot JSONify it. kludge.
        c = test_target_images_mixin
        if not c.__name__ in self.tags['interfaces']:
            self.tags['interfaces'].append(c.__name__)
        self.fsdb.set('powered', None)
        # Image files written to the device are recorded as tags

    _image_type_regex = re.compile(
        r"^(rom|bootloader|bios|fw|kernel|initramfs|hd)([-\.].+)?$")
    def image_type_check(self, image_type):
        m = self._image_type_regex.match(image_type)
        if not m:
            raise self.unsupported_image_e(
                "%s: image_type needs to match regex %s"
                % (image_type, self._image_type_regex.pattern))

    def image_do_set(self, image_type, image_name):
        """
        Take file *image_name* from target-broker storage for the
        current user and write it to the target as *image-type*.

        :raises: Any exception on failure

        This function has to be specialized for each target type. Upon
        finishing, it has to leave the target in the powered off state.
        """
        raise NotImplementedError

    def images_do_set(self, images):
        """Called once image_do_set() has been called for every image.

        This is for targets might need to flash all at the same time,
        or some post flash steps.

        :raises: Any exception on failure

        This function has to be specialized for each target type. Upon
        finishing, it has to leave the target in the powered off state.

        """
        raise NotImplementedError

    def images_set(self, who, images):
        """
        Set a series of images in the target so it can boot

        :param images: dictionary of image type names and image file
          names. The file names are names of files uploaded to the broker.
        :type images: dict
        :raises: Exception on failure
        """
        for t, n in images.iteritems():
            self.image_type_check(t)
            with self.target_owned_and_locked(who):
                self.log.debug("setting image %s:%s" % (t, n))
                self.image_do_set(t, n)
                self.log.debug("set image %s:%s" % (t, n))
                self.tags['images-%s' % t] = n
        self.images_do_set(images)

    def image_get(self, image_type):
        return self.tags.get("image-%s" % image_type, "")

class tt_debug_impl(object):
    """
    Debug object implementation
    """
    def debug_do_start(self, tt):
        """
        Start the debugging support for the target
        """
        raise NotImplementedError

    def debug_do_stop(self, tt):
        """
        Stop the debugging support for the target
        """
        raise NotImplementedError

    def debug_do_halt(self, tt):
        raise NotImplementedError("not implemented")

    def debug_do_reset(self, tt):
        raise NotImplementedError("not implemented")

    def debug_do_reset_halt(self, tt):
        raise NotImplementedError("not implemented")

    def debug_do_resume(self, tt):
        raise NotImplementedError("not implemented")

    def debug_do_info(self, tt):
        """
        Returns a string with information on how to connect to the
        debugging target
        """
        raise NotImplementedError("not implemented")

    def debug_do_openocd(self, tt, command):
        """
        Send a command to OpenOCD and return its output (if the target
        supports it).
        """
        raise NotImplementedError


class tt_debug_mixin(tt_debug_impl):
    """Generic debug interface to start and stop debugging on a
    target.

    When debug is started before the target is powered up, then upon
    power up, the debugger stub shall wait for a debugger to connect
    before continuing execution.

    When debug is started while the target is executing, the target
    shall not be stopped and the debugging stub shall permit a
    debugger to connect and interrupt the target upon connection.

    Each target provides its own debug methodolody; to find out how to
    connect, issue a debug-info command to find out where to connect
    to.
    """
    def __init__(self, impl = None):
        tt_debug_impl.__init__(self)
        # We could use a set, but Flask cannot JSONify it. kludge.
        c = tt_debug_mixin
        if not c.__name__ in self.tags['interfaces']:
            self.tags['interfaces'].append(c.__name__)
        if impl:
            self.impl = impl
        else:
            self.impl = None
        self.fsdb.set("debug", None)
        self.release_hooks.add(self._debug_release_hook)

    def debug_start(self, who):
        """
        Start debugging the target

        If called before powering, the target will wait for the
        debugger to connect before starting the kernel.
        """
        with self.target_owned_and_locked(who):
            if self.fsdb.get("debug") != None:
                return
            if self.impl:
                self.impl.debug_do_start(self)
            else:
                self.debug_do_start(self)
            self.fsdb.set("debug", "On")

    def debug_halt(self, who):
        """
        Resume the target's CPUs after a breakpoint (or similar) stop
        """
        with self.target_owned_and_locked(who):
            if self.impl:
                self.impl.debug_do_halt(self)
            elif getattr(self, "debug_do_halt", None) != None:
                self.debug_do_halt(self)
            else:
                raise NotImplementedError("No known way to halt this target")

    def debug_reset(self, who):
        """
        Reset the target's CPUs
        """
        with self.target_owned_and_locked(who):
            if self.impl:
                self.impl.debug_do_reset(self)
            else:
                self.debug_do_reset(self)

    def debug_reset_halt(self, who):
        """
        Reset the target's CPUs
        """
        with self.target_owned_and_locked(who):
            if self.impl:
                self.impl.debug_do_reset_halt(self)
            else:
                self.debug_do_reset_halt(self)

    def debug_resume(self, who):
        """
        Resume the target

        This is called to instruct the target to resume execution,
        following any kind of breakpoint or stop that halted it.
        """
        with self.target_owned_and_locked(who):
            if self.impl:
                self.impl.debug_do_resume(self)
            else:
                self.debug_do_resume(self)

    def debug_info(self, who):
        """
        Return information about how to connect to the target to debug
        it
        """
        s = ""
        with self.target_owned_and_locked(who):
            if self.impl:
                s = self.impl.debug_do_info(self)
            else:
                s = self.debug_do_info(self)
        if self.fsdb.get("debug") == None:
            s += "\n[Debugging has not been started]"
        return s

    def _debug_stop(self):
        if self.fsdb.get("debug") == None:
            return
        self.fsdb.set("debug", None)
        if self.impl:
            self.impl.debug_do_stop(self)
        else:
            self.debug_do_stop(self)

    def _debug_release_hook(self, _target, _force):
        # When the target is released, stop debugging, so the next
        # acquirer doesn't have surprises
        self._debug_stop()

    def debug_stop(self, who):
        """
        Stop debugging the target

        This might not do anything on the target until power off, or
        it might disconnect the debugger currently connected.
        """
        with self.target_owned_and_locked(who):
            self._debug_stop()

    def debug_openocd(self, who, command):
        """
        Run an OpenOCD command on the target's controller (if the
        target supports it).
        """
        with self.target_owned_and_locked(who):
            if self.impl:
                return self.impl.debug_do_openocd(self, command)
            else:
                return self.debug_do_openocd(self, command)

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



def usb_find_dev_by_serial(cache, log, device_name, serial_number):
    usb_dev = None
    try:
        def _match(d):
            try:
                return d.serial_number == serial_number
            except Exception as e:
                logging.warning(
                    "USB %04x:%04x @ %d.%d: exception filtering: %s",
                    d.idVendor, d.idProduct, d.bus, d.address, e)
                return False
        usb_dev = usb.core.find(custom_match = _match,
                                backend = cache.backend)
    except Exception as e:
        log.error("[retryable] Can't find %s devices #%s: %s",
                  device_name, serial_number, e)
        usb_dev = None
        # When this happens, kill the backend and have a new one
        # allocated; there are cases where the USB device has been
        # reassigned for whichever reason and has to be fully
        # re-scaned and re-initialized.
        if hasattr(cache, "backend"):
            del cache.backend
            cache.backend = None
    if usb_dev == None:
        raise ValueError("cannot find device %s #%s'"
                         % (device_name, serial_number))
    if hasattr(cache, "backend"):
        # pylint seems not to be able to catch members from the generator
        cache.backend = usb_dev._ctx.backend # pylint: disable = no-member
    return usb_dev


def usb_find_sibling_by_serial(serial, port, log = None):
    """
    Given a USB device *A* (with a *serial* number), find if there is
    a USB device *B* that is connected to the same hub as *A* on a
    given *port* and return it's bus number and address
    """

    if log == None:
        log = logging

    class cache_c(object):
        pass

    cache = cache_c()
    cache.backend = None

    usb_dev_a = usb_find_dev_by_serial(cache, log, "", serial)

    # pylint seems not to be able to catch the bus and address members
    # from the generator
    path = "/dev/bus/usb/%03d/%03d" \
           % (usb_dev_a.bus, usb_dev_a.address) # pylint: disable = no-member
    s = os.stat(path)
    dev = "%d:%d" % (os.major(s.st_rdev), os.minor(s.st_rdev))
    for devname in os.listdir("/sys/bus/usb/devices"):
        if ":" in devname:
            # This is an interface, we only care about devices
            continue
        sysfs_dev_path = "/sys/bus/usb/devices/" + devname
        with open(sysfs_dev_path + "/dev") as f:
            dir_dev = f.read().strip()
            if dir_dev == dev:
                break
    else:
        raise ValueError("can't find /sys/bus/usb/devices/ path for %s" % dev)
    # Oky,so this is the path for the device itself
    sysfs_dev = sysfs_dev_path

    # sysfs_dev/port is a symlink to /sys.../PARENTDEVICE/PARENTIFACE/PORT, so
    # getting the link pointer and the dir part of it gets us the
    # parent device/if
    sysfs_parent_dev_if = os.path.dirname(
        os.path.realpath(sysfs_dev + "/port"))
    # This is the PARENTDEVICE basename, which we need to compose the
    # name PARENTDEVICE-portPORTNUMBER
    parent_dev = os.path.basename(os.path.dirname(sysfs_parent_dev_if))
    # Tadah, this would be the path to the device, if it is connected
    sys_sibling_dev_path = sysfs_parent_dev_if \
                           + "/%s-port%d/device" % (parent_dev, port)
    # And here,
    if not os.path.isdir(sys_sibling_dev_path):
        raise ValueError("device sibling in port %d for USB device "
                         "serial #%s not connected" % (port, serial))
    # Okie, so we have it -- now we need to open a descriptor to it --
    # I don't know a better way to do it, so we'll match on device bus
    # and address. FIXME: There has to be a faster way.
    #
    # In that directory, the bus number is in file *bus*, the device
    # address in *devnum*
    with open(sys_sibling_dev_path + "/busnum") as f:
        bus = int(f.read().strip())
    with open(sys_sibling_dev_path + "/devnum") as f:
        address = int(f.read().strip())
    return bus, address

def usb_find_by_bus_address(bus, address):
    """
    Return a USB device descriptor given it's bus and address

    :param int bus: bus number
    :param int address: address in bus
    """
    assert isinstance(bus, int) and bus > 0
    assert isinstance(address, int) and address > 0 < 128
    # Having this, we can open a new descriptor
    def _match(d):
        try:
            return d.bus == bus and d.address == address
        except ValueError as e:
            logging.warning("Error while looking for a match: %s", e)
            return False

    return usb.core.find(custom_match = _match)
