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

import errno
import json
import os
import subprocess
import time

import commonl
import ttbl

class impl_c(object):
    """
    Implementation interface for a capture driver

    The target will list the available capturers in the *capture* tag.

    :param bool stream: if this capturer is capable of streaming; an
      streaming capturer has to be told to start and then stop and
      return the capture as a file.
    :param str mimetype: MIME type of the capture output, eg image/png
    """
    def __init__(self, stream, mimetype = None):
        # can be False (just gets), True (start/stop+get)
        self.stream = stream
        # Path to the user directory, updated on every request_process
        # call
        self.user_path = None
        self.mimetype = mimetype

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
        capturers = []
        for capturer, impl in self.impls.iteritems():
            ctype = "stream" if impl.stream else "snapshot"
            descr = capturer + ":" + ctype
            if impl.mimetype:
                descr += ":" + impl.mimetype
            capturers.append(descr)
        target.tags_update(dict(capture = " ".join(capturers)))

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
        impl_c.__init__(self, False, "image/png")

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
        target.log.warning("This object is deprecated, "
                           "use ttbl.capture.generic_snapshot")
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
        impl_c.__init__(self, False, "image/png")

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
        target.log.warning("This object is deprecated, "
                           "use ttbl.capture.generic_snapshot")
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


class generic_snapshot(impl_c):
    """This is a generic snaptshot capturer which can be used to invoke any
    program that will do capture a snapshot; in a server
    configuration file:

    >>>
    >>> target = ttbl.config.targets['TARGETNAME']
    >>> target.interface_add("capture", ttbl.capture.interface(
    >>>
    >>>         # capture screenshots from VNC, return a PNG
    >>>         vnc0 = ttbl.capture.generic_snapshot(
    >>>             "VNC :%d" % count,
    >>>             "gvnccapture -q localhost:%s $OUTPUTFILENAME$" % count
    >>>         ),
    >>>
    >>>         ...
    >>>     )
    >>> )
    >>>


    Before taking the snapshot, the pre-commands are executed and then
    the cmdline is invoked and the cmline shall capture the snapshot
    and place it in the file *$OUTPUTFILENAME$*.

    :param str name: name for error messges from this capturer
    :param str cmdline: commandline to invoke the capturing the
      snapshot. Eg::

        capture-from-device -i /dev/video1 -o $OUTPUTFILENAME$

      note how *$OUTPUTFILENAME$* is replaced with the outputfile.

    :param str mimetype: MIME type of the capture output, eg image/png

    :param list(str) pre_commands: (optional) list of commands to
      execute before the command line, to for example, set parameters
      eg:

      >>> pre_commands = [
      >>>     # set some video parameter
      >>>     "v4l-ctl -i /dev/video1 -someparam 45",
      >>> ]

    """
    def __init__(self, name, cmdline, pre_commands = None, mimetype = None):
        assert isinstance(name, basestring)
        assert isinstance(cmdline, basestring)
        self.name = name
        self.cmdline = cmdline.split()
        if pre_commands:
            self.pre_commands = pre_commands
            assert all([ isinstance(command, basestring)
                         for command in pre_commands ]), \
                             "list of pre_commands have to be strings"
        else:
            self.pre_commands = []
        impl_c.__init__(self, False, mimetype)

    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        # we don't do anything here, only upon stop

    def stop_and_get(self, target, capturer):
        impl_c.stop_and_get(self, target, capturer)
        file_name = "%s/%s-%s-%s" % (self.user_path, target.id, capturer,
                                     time.strftime("%Y%m%d-%H%M%S"))
        try:
            for command in self.pre_commands:
                subprocess.check_call(command.split())
            # replace $OUTPUTFILENAME$ with the name of the output file
            cmdline = []
            for i in self.cmdline:
                if '$OUTPUTFILENAME$' in i:
                    i = i.replace("$OUTPUTFILENAME$", file_name)
                cmdline.append(i)
            target.log.info("snapshot command: %s" % " ".join(cmdline))
            subprocess.check_call(cmdline, cwd = "/tmp", shell = False,
                                  close_fds = True,
                                  stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error(
                "%s: capturing of '%s' with '%s' failed: (%d) %s"
                % (target.id, self.name, " ".join(cmdline), e.returncode,
                   e.output))
            raise
        # tell the caller to stream this file to the client
        return dict(stream_file = file_name)


class generic_stream(impl_c):
    """
    This is a generic stream capturer which can be used to invoke any
    program that will do capture the stream for a while; in a server
    configuration file:

    >>>
    >>> target = ttbl.config.targets['TARGETNAME']
    >>> target.interface_add("capture", ttbl.capture.interface(
    >>>         ...
    >>>
    >>>         # capture a stream from a webcam pointing to the screen
    >>>         video1_stream = ttbl.capture.generic_stream(
    >>>             "Video stream #1",
    >>>             # Capture with FFMPEG the webcam and Alsa's system
    >>>             # device, as there is no pulse input as a daemon
    >>>             # -y forces overriding the file
    >>>             "ffmpeg -i /dev/video0  -f alsa -i sysdefault "
    >>>             " -f avi -qscale:v 10 -y $OUTPUTFILENAME$",
    >>>             pre_commands = [
    >>>                 # set the input volume so it doesn't clip
    >>>                 "amixer -D sysdefault sset Capture 75%",
    >>>             ],
    >>>             # give it time to save when killing ffmpeg
    >>>             wait_to_kill = 2
    >>>         )
    >>>     )
    >>> )
    >>>


    When the capturer is started, the pre-commands are executed (eg:
    to set volumes) and then the cmdline is invoked. The cmdline is
    expected to start capturing to the $OUTPUTFILENAME$ until killed.

    :param str name: name for error messges from this capturer
    :param str cmdline: commandline to invoke the capturing of the
      stream, eg::

        capture-from-device -i /dev/video1 -o $OUTPUTFILENAME$

      note how *$OUTPUTFILENAME$* is replaced with the outputfile.

    :param list(str) pre_commands: (optional) list of commands to
      execute before the command line, to for example, set
      volumes. eg:

      >>> pre_commands = [
      >>>     # set the input volume so it doesn't clip
      >>>     "amixer -D sysdefault sset Capture 75%",
      >>> ]

    :param int wait_to_kill: (optional) time to wait since we send a
      SIGTERM to the capturing process until we send a SIGKILL, so it
      has time to close the capture file. Defaults to one second.
    :param str mimetype: MIME type of the capture output, eg video/avi
    """
    def __init__(self, name, cmdline, pre_commands = None, wait_to_kill = 1,
                 mimetype = None):
        assert isinstance(name, basestring)
        assert isinstance(cmdline, basestring)
        assert wait_to_kill > 0
        self.name = name
        self.cmdline = cmdline.split()
        self.wait_to_kill = wait_to_kill
        if pre_commands:
            self.pre_commands = pre_commands
            assert all([ isinstance(command, basestring)
                         for command in pre_commands ]), \
                             "list of pre_commands have to be strings"
        else:
            self.pre_commands = []
        impl_c.__init__(self, True)


    def start(self, target, capturer):
        impl_c.start(self, target, capturer)
        pidfile = os.path.join(target.state_dir,
                               "capturer-" + capturer + ".pid")
        file_name = "%s/%s-%s-%s" % (self.user_path, target.id, capturer,
                                     time.strftime("%Y%m%d-%H%M%S"))
        target.property_set("capturer-%s-output" % capturer, file_name)
        try:
            for command in self.pre_commands:
                target.log.info("streaming pre-command: %s" % command)
                subprocess.check_call(command.split())
            # replace $OUTPUTFILENAME$ with the name of the output file
            cmdline = []
            for i in self.cmdline:
                if '$OUTPUTFILENAME$' in i:
                    i = i.replace("$OUTPUTFILENAME$", file_name)
                cmdline.append(i)
            target.log.info("streaming command: %s" % " ".join(cmdline))
            p = subprocess.Popen(cmdline, cwd = "/tmp", shell = False,
                                 close_fds = True,
                                 stderr = subprocess.STDOUT)
            with open(pidfile, "w+") as pidf:
                pidf.write("%s" % p.pid)
        except subprocess.CalledProcessError as e:
            target.log.error(
                "%s: starting capture of '%s' output with '%s' failed: (%d) %s"
                % (target.id, self.name, " ".join(cmdline), e.returncode,
                   e.output))
            raise

    def stop_and_get(self, target, capturer):
        impl_c.stop_and_get(self, target, capturer)
        pidfile = os.path.join(target.state_dir,
                               "capturer-" + capturer + ".pid")
        try:
            file_name = target.property_get("capturer-%s-output" % capturer)
            target.property_set("capturer-%s-output" % capturer, None)
            commonl.process_terminate(pidfile, tag = "capture: ",
                                      wait_to_kill = self.wait_to_kill)
            return dict(stream_file = file_name)
        except OSError as e:
            # adb might have died already
            if e != errno.ESRCH:
                raise
