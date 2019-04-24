#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import time

import ttbl


class impl_c(object):
    """
    Implementation interface for a button driver
    """
    def __init__(self):
        # can be None (no need to start), True if started, False if stopped
        self.capturing = False
        # Path to the user directory, updated on every request_process
        # call
        self.user_path = None

    def start(self, target, capturer):
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, basestring)
        # must return a dict

    def stop_and_get(self, target, capturer):
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, basestring)
        # must return a dict

class interface(ttbl.tt_interface):
    """
    Interface to capture something

    An instance of this gets added as an object to the main target
    with:

    >>> ttbl.config.targets['qu05a'].interface_add(
    >>>     "capture",
    >>>     ttbl.capture.interface(
    >>>         screen = ttbl.vnc.capture_impl(PORTNUMBER)
    >>>     )
    >>> )

    FIXME: add synonyms so we can have descriptive names and defaults

    :param dict impls: dictionary keyed by capture name name and which
      values are instantiation of button drivers inheriting from
      :class:`ttbl.capture.impl_c`.

      Names have to be valid python symbol names.

    """
    def __init__(self, **impls):
        assert isinstance(impls, dict), \
            "impls must be a dictionary keyed by capture name, got %s" \
            % type(impls).__name__
        ttbl.tt_interface.__init__(self)
        # Verify arguments
        for name, impl in impls.iteritems():
            assert isinstance(impl, impl_c), \
                "capture implementation is type %s, " \
                "expected ttbl.capture.impl_c " % type(impl)._name__
        # save it
        self.impls = impls
        # Path to the user directory, updated on every request_process
        # call
        self.user_path = None

    def start(self, who, target, capturer):
        target.log.error("DEBUG here! 3")
        assert capturer in self.impls.keys(), "capturer %s unknown" % capturer
        with target.target_owned_and_locked(who):
            impl = self.impls[capturer]
            if impl.capturing == None:
                # doesn't need starting
                return { 'result' : 'capture start not needed'}
            if impl.capturing == False:
                impl.user_path = self.user_path
                impl.start(target, capturer)
                impl.capturing = True
                return { 'result' : 'capture started'}
            else:
                return { 'result' : 'already capturing'}

    def stop_and_get(self, who, target, capturer):
        assert capturer in self.impls.keys(), "capturer %s unknown" % capturer
        with target.target_owned_and_locked(who):
            impl = self.impls[capturer]
            if impl.capturing == None:
                impl.user_path = self.user_path
                return impl.stop_and_get(target, capturer)
            elif impl.capturing == True:
                impl.user_path = self.user_path
                impl.capturing = False
                return impl.stop_and_get(target, capturer)
            else:
                return { 'result' : 'it is not capturing, can not stop'}

    def list(self, target):
        """
        List capturers available on a target
        """
        res = {}
        for name, impl in self.impls.iteritems():
            res[name] = impl.capturing
        return dict(capturers = res)

    def _release_hook(self, target, _force):
        for name, impl in self.impls.iteritems():
            if impl.capturing == True:
                impl.stop_and_get(target, name)

    def _args_check(self, target, args):
        target.log.error("DEBUG here! 4 args %s" % args)
        if not 'capturer' in args:
            raise RuntimeError("missing 'capturer' arguments")
        capturer = args['capturer']
        assert isinstance(capturer, basestring)
        return capturer

    def request_process(self, target, who, method, call, args,
                        _user_path):
        self.user_path = _user_path
        ticket = args.get('ticket', "")
        if call == "start" and method == "POST":
            capturer = self._args_check(target, args)
            self.start(who, target, capturer)
            r = {}
        elif call == "stop_and_get" and method == "POST":
            capturer = self._args_check(target, args)
            r = self.stop_and_get(who, target, capturer)
            target.log.error("DEBUG stop_and_get r %s" % r)
        elif method == "GET" and call == "list":
            r = self.list(target)
        else:
            raise RuntimeError("%s|%s: unsuported" % (method, call))
        target.timestamp()	# If this works, it is acquired and locked
        return r

def _check_iface(target):
    buttons_iface = getattr(target, "buttons", None)
    if not buttons_iface or not isinstance(buttons_iface, interface):
        raise RuntimeError("%s: target has no buttons interface" % target.id)


class vnc(impl_c):
    """
    Implementation interface for a button driver
    """
    def __init__(self, port):
        self.port = port
        impl_c.__init__(self)
        self.capturing = None  # meaning we don't need to start

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
        target.log.error("DEBUG vnc stop and get")
        impl_c.stop_and_get(self, target, capturer)
        file_name = "%s/%s-%s-%s.png" % (self.user_path, target.id, capturer,
                                         time.strftime("%Y%m%d-%H%M%S"))
        try:
            cmdline = [ "gvnccapture", "localhost:%s" % self.port, file_name ]
            subprocess.check_call(cmdline, cwd = "/tmp",
                                  stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error(
                "%s: capturing VNC output with '%s' failed: (%d) %s"
                % (target.id, " ".join(cmdline), e.returncode, e.output))
            raise
        # tell the caller to stream this file to the client
        return dict(stream_file = file_name)


class ffmpeg(impl_c):
    """
    """
    def __init__(self, video_device):
        self.video_device = video_device
        impl_c.__init__(self)
        self.capturing = None  # meaning we don't need to start

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
        impl_c.stop_and_get(self, target, capturer)
        file_name = "%s/%s-%s-%s.png" % (self.user_path, target.id, capturer,
                                         time.strftime("%Y%m%d-%H%M%S"))
        try:
            # might want to add -ss H:M:S to wait before starting
            # capture for the device to stabilize
            # -f video4linux can be ignored
            cmdline = [
                "ffmpeg",
                "-i", self.video_device,
                "-frames", str(1),	# only one frame
                "-y", file_name	# force overwrite output file
            ]
            target.log.error("DEBUG cmdline %s" % cmdline)
            subprocess.check_call(cmdline, cwd = "/tmp", stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error(
                "%s: capturing ffmpeg output with '%s' failed: (%d) %s"
                % (target.id, " ".join(cmdline), e.returncode,
                   e.output))
            raise
        # tell the caller to stream this file to the client
        return dict(stream_file = file_name)
