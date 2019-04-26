#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Stream and snapshot capture interace
------------------------------------

This module implements an interface to capture things in the server
and then return them to the client.

This can be used to, for example:

-  capture screenshots of a screen, by connecting the target's output
   to a framegrabber, for example:

   - `MYPIN HDMI Game Capture Card USB 3.0
     <https://www.amazon.com/AGPTEK-Capture-Streaming-Recorder-Compatible/dp/B074863G59/ref=sr_1_2_sspa?keywords=MYPIN+HDMI+Game+Capture&qid=1556209779&s=electronics&sr=1-2-spons&psc=1>`_

   - `LKV373A <https://www.lenkeng.net/Index/detail/id/149>`_

   ...

   and then running somethig such as ffmpeg on its output

- capture a video stream (with audio) when the controller can say when
  to start and when to end

- capture network traffic with tcpdump


"""

import json
import os
import subprocess
import time

import ttbl

class impl_c(object):
    """
    Implementation interface for a capture driver

    The target will list the available capturers in the *capture* tag.

    :param bool stream: if this capturer is capable of streaming; an
      streaming capturer has to be told to start and then stop and
      return the capture as a file.
    """
    def __init__(self, stream):
        # can be False (just gets), True (start/stop+get)
        self.stream = stream
        # Path to the user directory, updated on every request_process
        # call
        self.user_path = None

    def start(self, target, capturer):
        """
        If this is a streaming capturer, start capturing the stream

        Usually starts a program that is active, capturing to a file
        until the :meth:`stop_and_get` method is called.

        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: name of this capturer
        :returns: dictionary of values to pass to the client, usually
          nothing
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, basestring)
        # must return a dict

    def stop_and_get(self, target, capturer):
        """
        If this is a streaming capturer, stop streaming and return the
        captured data or take a snapshot and return it.

        This stops the capture of the stream and return the file
        or take a snapshot capture and return.

        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: name of this capturer
        :returns: dictionary of values to pass to the client,
          including the data; to stream a large file, include a member
          in this dictionary called *stream_file* pointing to the
          file's path; eg:

          >>> return dict(stream_file = CAPTURE_FILE)
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, basestring)
        # must return a dict


class interface(ttbl.tt_interface):
    """
    Interface to capture something in the server related to a target

    An instance of this gets added as an object to the target object
    with:

    >>> ttbl.config.targets['qu05a'].interface_add(
    >>>     "capture",
    >>>     ttbl.capture.interface(
    >>>         vnc0 = ttbl.capture.vnc(PORTNUMBER)
    >>>         vnc0_stream = ttbl.capture.vnc_stream(PORTNUMBER)
    >>>         hdmi0 = ttbl.capture.ffmpeg(...)
    >>>         screen = "vnc0",
    >>>         screen_stream = "vnc0_stream",
    >>>     )
    >>> )

    Note how *screen* has been made an alias of *vnc0* and
    *screen_stream* an alias of *vnc0_stream*.

    :param dict impls: dictionary keyed by capture name name and which
      values are instantiation of capture drivers inheriting from
      :class:`ttbl.capture.impl_c` or names of other capturers (to
      sever as aliases).

      Names have to be valid python symbol names.

    """
    def __init__(self, **impls):
        assert isinstance(impls, dict), \
            "impls must be a dictionary keyed by capture name, got %s" \
            % type(impls).__name__
        ttbl.tt_interface.__init__(self)
        # Verify arguments
        self.impls = {}
        for capturer, impl in impls.iteritems():
            if isinstance(impl, impl_c):
                if capturer in self.impls:
                    raise AssertionError("capturer '%s' is repeated "
                                         % capturer)
                self.impls[capturer] = impl
            elif isinstance(impl, basestring):
                # synonym
                if not impl in impls:
                    raise AssertionError(
                        "capturer synonym '%s' refers to a capturer "
                        "'%s' that does not exist " % (capturer, impl))
                self.impls[capturer] = impls[impl]
            else:
                raise AssertionError(
                    "capturer '%s' implementation is type %s, " \
                    "expected ttbl.capture.impl_c or str"
                    % (capturer, type(impl)._name__))

        # Path to the user directory, updated on every request_process
        # call
        self.user_path = None

    def _target_setup(self, target):
        """
        Called when the interface is added to a target to initialize
        the needed target aspect (such as adding tags/metadata)
        """
        target.tags_update(dict(capture = " ".join(self.impls.keys())))

    def start(self, who, target, capturer):
        """
        If this is a streaming capturer, start capturing the stream

        :param str who: user who owns the target
        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: capturer to use, as registered in
          :class:`ttbl.capture.interface`.
        :returns: dictionary of values to pass to the client
        """
        assert capturer in self.impls.keys(), "capturer %s unknown" % capturer
        with target.target_owned_and_locked(who):
            impl = self.impls[capturer]
            if impl.stream == False:
                # doesn't need starting
                return { 'result' : 'capture start not needed'}
            capturing = target.property_get("capturer-%s-started" % capturer)
            if not capturing:
                impl.user_path = self.user_path
                impl.start(target, capturer)
                target.property_set("capturer-%s-started" % capturer, "True")
                return { 'result' : 'capture started'}
            else:
                return { 'result' : 'already capturing'}


    def stop_and_get(self, who, target, capturer):
        """
        If this is a streaming capturer, stop streaming and return the
        captured data or if no streaming, take a snapshot and return it.

        :param str who: user who owns the target
        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: capturer to use, as registered in
          :class:`ttbl.capture.interface`.
        :returns: dictionary of values to pass to the client
        """
        assert capturer in self.impls.keys(), "capturer %s unknown" % capturer
        with target.target_owned_and_locked(who):
            impl = self.impls[capturer]
            if impl.stream == False:
                impl.user_path = self.user_path
                return impl.stop_and_get(target, capturer)
            capturing = target.property_get("capturer-%s-started" % capturer)
            if capturing:
                impl.user_path = self.user_path
                target.property_set("capturer-%s-started" % capturer, None)
                return impl.stop_and_get(target, capturer)
            else:
                return { 'result' : 'it is not capturing, can not stop'}


    def list(self, target):
        """
        List capturers available on a target

        :param ttbl.test_target target: target on which we are capturing
        """
        res = {}
        for name, impl in self.impls.iteritems():
            if impl.stream:
                capturing = target.property_get("capturer-%s-started"
                                                % name)
                if capturing:
                    res[name] = "capturing"
                else:
                    res[name] = "not-capturing"
            else:
                res[name] = "ready"
        return dict(capturers = res)


    def _release_hook(self, target, _force):
        for name, impl in self.impls.iteritems():
            if impl.stream == True:
                impl.stop_and_get(target, name)


    def _args_check(self, target, args):
        if not 'capturer' in args:
            raise RuntimeError("missing 'capturer' arguments")
        capturer = args['capturer']
        assert isinstance(capturer, basestring)
        return capturer


    def request_process(self, target, who, method, call, args,
                        _user_path):
        # called by the daemon when a METHOD request comes to the HTTP path
        # /ttb-vVERSION/targets/TARGET/interface/capture/CALL
        self.user_path = _user_path
        ticket = args.get('ticket', "")
        if call == "start" and method == "POST":
            capturer = self._args_check(target, args)
            self.start(who, target, capturer)
            r = {}
        elif call == "stop_and_get" and method == "POST":
            capturer = self._args_check(target, args)
            r = self.stop_and_get(who, target, capturer)
        elif method == "GET" and call == "list":
            r = self.list(target)
        else:
            raise RuntimeError("%s|%s: unsuported" % (method, call))
        target.timestamp()	# If this works, it is acquired and locked
        return r



class vnc(impl_c):
    """
    Implementation interface for a button driver
    """
    def __init__(self, port):
        self.port = port
        impl_c.__init__(self, False)

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
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
        impl_c.__init__(self, False)

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
                "-s", "1",
                "-frames", str(1),	# only one frame
                "-y", file_name	# force overwrite output file
            ]
            subprocess.check_call(cmdline, cwd = "/tmp", stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error(
                "%s: capturing ffmpeg output with '%s' failed: (%d) %s"
                % (target.id, " ".join(cmdline), e.returncode,
                   e.output))
            raise
        # tell the caller to stream this file to the client
        return dict(stream_file = file_name)
