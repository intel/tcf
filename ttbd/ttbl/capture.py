#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#f'
# SPDX-License-Identifier: Apache-2.0
#
"""
Stream and snapshot capture interface
*************************************

This module implements an interface to capture things in the server
and then return them to the client.

This can be used to, for example:

-  capture screenshots of a screen, by connecting the target's output
   to a framegrabber, for example:

   - `MYPIN HDMI Game Capture Card USB 3.0
     <https://www.amazon.com/AGPTEK-Capture-Streaming-Recorder-Compatible/dp/B074863G59/ref=sr_1_2_sspa?keywords=MYPIN+HDMI+Game+Capture&qid=1556209779&s=electronics&sr=1-2-spons&psc=1>`_

   - `LKV373A <https://www.lenkeng.net/Index/detail/id/149>`_

   - VNC providers

   ...

   and then running somethig such as ffmpeg on its output

- capture a video stream (with or without audio) when the controller
  can say when to start and when to end (same above)

- capture network traffic with tcpdump

- sample power consumption data from PDUs that support it (eg:
  :class:`ttbl.raritan_emx.pci`)

A capturer is a driver, instance of :class:`ttbl.capture.impl_c` that
provides methods to start capturing and stop capturing. When a capture
is started, the driver returns a list of files where streams of data
are captured or being captured.

A snapshot providing only implements the start capture.

A driver captures one or more streams of data (most commonly the data
itself and a log of the capture process). In most cases, the capture
is done forking a process that does the work, forwarding all the
output to the log and the captured data to a file. If multiple files
are captured, each is mapped a *stream*.

Eg: if using ffmpeg to capture video from a screen:

 - *default* stream would have an AVI file with the video/audio
   capture

 - *log* stream would have the stdout and stderr of the ffmpeg
   program.


Capture Inventory
-----------------

.. _inventory_capture:

.. list-table:: Capture Inventory
   :header-rows: 1
   :widths: 20 10 10 60
   :width: 50%

   * - Field name

     - Type
       (str, bool, integer,
       float, dictionary)
     - Disposition
       (mandatory, recommended,
       optional[default])
     - Description

   * - interfaces.capture
     - Dictionary
     - Optional
     - Information about the different capturers available in the
       target; presence of this dictionary indicates the target
       supports data capture

   * - interfaces.capture
     - Dictionary
     - Optional
     - Information about the different capturers available in the
       target; presence of this dictionary indicates the target
       supports data capture

   * - interfaces.capture.NAME
     - Dictionary
     - mandatory
     - Descriptor for a capturer called *NAME*

   * - interfaces.capture.NAME.instrument
     - str
     - mandatory
     - Instrument that implements the capturer. This is described in
       the inventory entry *instrumentation.VALUE*

   * - interfaces.capture.NAME.snapshot
     - bool
     - mandatory
     - Indicates if this capturer is a snapshot or non-snapshot
       capturer. A snapshot capturer takes a single capture and
       returns the capture as set of streams. A non-snapshot capturer
       starts capturing and captures data until stopped and then
       returns the streams captured.

   * - interfaces.capture.NAME.capturing
     - bool
     - optional
     - Indicates if this capturer is currently capturing (applies only
       to non-snapshot capturers). If not present, it can be assumed
       to be *False*.

   * - interfaces.capture.NAME.stream.STREAMNAME
     - Dictionary
     - mandatory
     - Descriptor for each stream captured by *NAME*. The convention
       calls for the default stream to be called *default*, any
       diagnostics or logs to be called *logANYTHING*, others can be
       called anything that is a valid field name.

   * - interfaces.capture.NAME.stream.STREAMNAME.mimetype
     - Dictionary
     - mandatory
     - Indicates the MIME type of the data captured by a stream (eg:
       application/json, text/plain, video/avi...)

   * - interfaces.capture.NAME.stream.STREAMNAME.file
     - Dictionary
     - mandatory
     - When capturing or when having captured, this points to the name
       of a file containing the captured data. The user can download
       this data using the store interface from the location
       *capture/FILENAME*.
"""

import collections
import datetime
import errno
import json
import os
import re
import signal
import shutil
import subprocess
import time
import sys

import commonl
import ttbl

if sys.version_info.major > 2:
    str_type = str
else:
    str_type = basestring

# mimetypes are NAME/NAME
# NAME can be alphanumeric, dots and underscore
# Multiple mimetypes are thus NAME/NAME,NAME/NAME...

mime_type_regex = re.compile(
    r"^([_\.a-zA-Z0-9]+/[_\.a-zA-Z0-9]+)"
    r"(,[_\.a-zA-Z0-9]+/[_\.a-zA-Z0-9]+)*$")

class impl_c(ttbl.tt_interface_impl_c):
    """
    Implementation interface for a capture driver

    The target will list the available capturers in the
       *interfaces.capture* inventory structure.

    :param bool snapshot: if this capturer can only take snapshots (vs
      starting a capture and then ending it)

    :param str mimetype: MIME type of the capture output for a stream
      called *data* (by default)

    :param kwargs: dict keyed by string of other stream names and
       their mimetypes. Stream naming convention:

        - *default*: default
        - *log\**: logs about the capture process [optional]
        - *\**: any other data streams

    """
    def __init__(self, snapshot, mimetype = None,
                 **kwargs):
        assert isinstance(snapshot, bool), \
            "snapshot: expected bool, got %s" % type(snapshot)
        assert mimetype == None or isinstance(mimetype, str_type), \
            "mimetype: default mimetype expected to be a string" \
            "; got %s" % type(mimetype)
        if mimetype:
            assert isinstance(mimetype, str_type), \
                "mimetype: default mimetype expected to be a string" \
                "; got %s" % type(mimetype)
            if 'data' in kwargs:
                assert isinstance(mimetype, str_type), \
                    "mimetype: specifying mimetype overrides a stream" \
                    " source called 'data' which has been specified" \
                    " with mimetype '%s'" % kwargs['data']
            kwargs['default'] = mimetype
        self.stream = collections.OrderedDict()
        for k in kwargs:
            v = kwargs[k]
            assert isinstance(v, str_type), \
                "mimetype for data %s: expected to be a string" \
                "; got %s" % (k, type(v))
            assert mime_type_regex.search(v), \
                "%s: MIME type specification not valid (only" \
                "multiple [_a-zA-Z0-9]+/[_a-zA-Z0-9]+ separated by commas" \
                % mimetype
            self.stream[k] = v
        self.snapshot = snapshot
        ttbl.tt_interface_impl_c.__init__(self)

    def target_setup(self, target, iface_name, component):
        assert component != "capturing", \
            "capturer name 'capturing' is reserved; cannot use"
        # wipe previous state
        target.property_set(f"interfaces.{iface_name}.{component}", None)
        # set the tags as reference
        publish_dict = target.tags['interfaces'][iface_name]
        publish_dict[component]['snapshot'] = self.snapshot
        publish_dict[component]['stream'] = {}
        for stream_name in self.stream:
            publish_dict[component]['stream'][stream_name] = {}
            publish_dict[component]['stream'][stream_name]['mimetype'] = \
                self.stream[stream_name]
        # register the path TARGETSTATEDIR/capture, where we allow the
        # user to download captured data from.
        target.store.target_sub_paths['capture'] = False

    def start(self, target, capturer, path):
        """
        Start capturing

        Usually starts a program that is active, capturing to a file
        until the :meth:`stop` method is called.

        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: name of this capturer
        :param str path: path where to store capture files

        :returns (state, dict): state is a bool *True* if the capturer
          is capturing, *False* if it is not

          A snapshot capturer will capture and return *False*

          A non-snapshot capturer will start capturing and return *True*

          The dictionary is keyed by stream name (as in self.stream) and
          the value is the name of the file RELATIVE to *path* where
          the data is captured or being captured.

        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, str_type)
        assert isinstance(path, str_type)
        # if this just took an snapshot of two stream files relative to path/
        # return False, { STREAM1: FILE1, STREAM2: FILE2... }
        # if this started streaming two stream files relative to path/
        # return True, { STREAM1: FILE1, STREAM2: FILE2... }

    def stop(self, target, capturer, path):
        """
        If this is a non-snapshot capturer and it is streaming, stop
        streaming.

        If it is a snapshot capturer, do nothing; the upper
        layer won't call it.

        The driver is responsible of properly terminating the captured
        data when the capture process is interrupted.

        :param ttbl.test_target target: target on which we are capturing

        :param str capturer: name of this capturer

        :param str path: path where the capture files are to be located

        :returns dict: If an empty dictionary, the capture information
          as returned by :meth:`start` if still valid.

          On error, a dictionary with "_error" and a description on
          it; all the fields in the dictionary will be reported.

          If a dictionary keyed by stream name (as in self.stream), the
          values are names of the file RELATIVE to *path* where
          the data is captured or being captured, overriding the
          values reported upon start by :meth:`start`.

        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(capturer, str_type)
        # must return a dict
        raise NotImplementedError


class interface(ttbl.tt_interface):
    """
    Interface to capture something in the server related to a target

    An instance of this gets added as an object to the target object
    with:

    >>> ttbl.test_target.get('qu05a').interface_add(
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


    **Lifecycle**

    When starting a capture, if the capturer is already capturing, it
    is stopped first and the previous capture is wiped. If trying to
    stop an snapshot capturer or a non-capturing capturer, nothing
    happens.

    Once capturing starts, inventory fields are set with the names of
    the files where the data is being downloaded (see :ref:`inventory
    <inventory_capture>`). The data can be downloaded at any time,
    even when the system is still capturing, and in this case it might
    be incomplete or partial. Only when stopped the data is guaranteed
    to be complete and properly terminated.

    When the targets are released, any captured data is wiped.

    Only allocation owner, creator or guests can access the captured
    data (FIXME: pending).

    """
    def __init__(self, *impls, **kwimpls):
        ttbl.tt_interface.__init__(self)
        self.impls_set(impls, kwimpls, impl_c)


    def _target_setup(self, target, iface_name):
        pass

    @staticmethod
    def _capture_path(target):
        # FIXME: Ideally we'd include teh ALLOCID here, so we could
        # keep data after release for future reference?
        capture_path = os.path.join(target.state_dir, "capture")
        # just make sure it always exist
        commonl.makedirs_p(capture_path)
        return capture_path


    def _release_hook(self, target, _force):
        # nothing to do on target release
        # we don't power off on release so we can pass the target to
        # someone else in the same state it was
        capture_path = self._capture_path(target)
        for capturer in self.impls:
            impl = self.impls[capturer]
            if impl.snapshot:
                continue
            capturing = target.property_get(
                "interfaces.capture.%s.capturing" % capturer, False)
            if not capturing:
                continue
            capturing = target.property_set(
                "interfaces.capture.%s.capturing" % capturer, None)
            try:
                target.log.info(
                    "capture: %s: stopping active capturer on release",
                    capturer)
                impl.stop(target, capturer, capture_path)
            except Exception as e:
                target.log.warning(
                    "capture: %s:"
                    " ignoring exception when stopping upon release: %s",
                    capturer, e)
        # WIPE all the captures: FIXME: fix to per ALLOCID
        shutil.rmtree(capture_path, ignore_errors = True)


    def put_start(self, target, who, args, _files, user_path):
        """
        Take a snapshot or start capturing

        :param str who: user who owns the target
        :param ttbl.test_target target: target on which we are capturing
        :param str capturer: capturer to use, as registered in
          :class:`ttbl.capture.interface`.
        :returns: dictionary of values to pass to the client
        """
        impl, capturer = self.arg_impl_get(args, "capturer")
        assert capturer in list(self.impls.keys()), \
            "capturer '%s' unknown" % capturer

        capture_path = self._capture_path(target)
        with target.target_owned_and_locked(who):
            target.timestamp()
            if not impl.snapshot:
                capturing = target.property_get(
                    "interfaces.capture.%s.capturing" % capturer, False)
                # if we were already capturing, restart it--maybe
                # someone left it capturing by mistake or who
                # knows--but what matters is what the current user wants.
                try:
                    target.log.info(
                        "capture/start: %s: stopping to clear state",
                        capturer)
                    impl.stop(target, capturer, capture_path)
                except:
                    pass	# not care about errors here, resetting state
            capturing, streams = impl.start(target, capturer, capture_path)
            assert isinstance(capturing, bool) and isinstance(streams, dict), \
                "%s: capture driver BUG (%s): start()'s return value " \
                " expected (bool, dict); got (%s, %s)" % (
                    capturer, type(impl), type(capturing), type(streams))
            # Clean state
            target.property_set("interfaces.capture.%s" % capturer, None)
            target.property_set(
                "interfaces.capture.%s.capturing" % capturer, True)
            r = dict(capturing = capturing)
            for stream_name in streams:
                file_name = streams[stream_name]
                if os.path.isabs(file_name):
                    raise RuntimeError(
                        "%s: capture driver BUG (%s): start() returned "
                        " absolute stream capture file: %s" % (
                        capturer, type(impl), file_name))
                target.property_set(
                    "interfaces.capture.%s.stream.%s.file"
                    % (capturer, stream_name), file_name)
                r[stream_name] = file_name

            target.log.info("capture/start: %s: started", capturer)
            return r


    def put_stop(self, target, who, args, _files, _user_path):
        impl, capturer = self.arg_impl_get(args, "capturer")
        with target.target_owned_and_locked(who):
            target.timestamp()
            if impl.snapshot:
                return {}
            capturing = target.property_get(
                "interfaces.capture.%s.capturing" % capturer, False)
            if not capturing:
                # pass on this, maybe it was an streaming capture that
                # stopped on its own after a number of cycles -- the
                # capture info is in the inventory, the use can use
                # that to get the capture
                return {}
            target.log.info("capture/stop: %s: stopping", capturer)
            target.property_set("interfaces.capture.%s.capturing" % capturer, False)
            capture_path = self._capture_path(target)
            r = impl.stop(target, capturer, capture_path)
            assert r == None or isinstance(r, dict), \
                "%s: capture driver BUG (%s): stop()'s return value " \
                " expected dict; got %s" % (capturer, type(impl), type(r))
            target.log.info("capture/stop: %s: stopped", capturer)

            if not r:
                r = {}
                # no new streams, we are good -- let's see what we got
                # and return it to the user for convenience
                streams = target.fsdb.keys("interfaces.capture.%s.stream.*.file"
                                           % capturer)
                prefix = "interfaces.capture.%s.stream." % capturer
                for stream in streams:
                    file_name = target.fsdb.get(stream)
                    # remove prefix and trailing .file
                    stream_name = stream[len(prefix):-len(".file")]
                    r[stream_name] = file_name
                return r

            if '_error' in r:
                raise RuntimeError(r['_error'], r)

            # if the driver reports new streams, let's update them
            # this cleans the state, but leaves the default, which
            # comes from the tags and contains the mimetypes
            target.property_set("interfaces.capture.%s.stream" % capturer,
                                None)
            for stream in r:
                file_name = r[stream]
                if os.path.isabs(file_name):
                    raise RuntimeError(
                        "%s: capture driver BUG (%s): returned "
                        " absolute stream capture file: %s,"
                        " expected relative" % (
                        capturer, type(impl), file_name))
                target.property_set(
                    "interfaces.capture.%s.stream.%s"
                    % (capturer, stream), file_name)
                r[stream] = file_name
            return r


class generic_snapshot(impl_c):
    """This is a generic snaptshot capturer which can be used to invoke any
    program that will do capture a snapshot.

    For example, in a server configuration file, define a capturer
    that will connect to VNC and take a screenshot:

    >>> capture_screenshot_vnc = ttbl.capture.generic_snapshot(
    >>>     "%(id)s VNC @localhost:%(vnc_port)s",
    >>>     # need to make sure vnc_port is defined in the target's tags
    >>>     "gvnccapture -q localhost:%(vnc_port)s %(output_file_name)s",
    >>>     mimetype = "image/png"
    >>> )

    Then attach the capture interface to the target with:

    >>> ttbl.test_target.get('TARGETNAME').interface_add(
    >>>     "capture",
    >>>     ttbl.capture.interface(
    >>>         vnc0 = capture_screenshot_vnc,
    >>>         ...
    >>>     )
    >>> )

    (for a full VNC capturer see :func:`mk_capture_screenshot_vnc`)

    Now the command::

      $ tcf capture TARGETNAME vnc0

    will download to ``file.png`` a capture of the target's screen via
    VNC.

    :param str name: name for error messages from this capturer.

      E.g.: `%(id)s HDMI`

    :param str cmdline: commandline to invoke the capturing the
      snapshot.

      E.g.: `ffmpeg -i /dev/video-%(id)s`; in this case udev
      has been configured to create a symlink called
      */dev/video-TARGETNAME* so we can uniquely identify the device
      associated to screen capture for said target.

    :param str mimetype: MIME type of the capture output, eg image/png

    :param list pre_commands: (optional) list of commands (str_type) to
      execute before the command line, to for example, set parameters
      eg:

      >>> pre_commands = [
      >>>     # set some video parameter
      >>>     "v4l-ctl -i /dev/video-%(id)s -someparam 45",
      >>> ]

    Note all string parameters are `%(keyword)s` expanded from the
    target's tags (as reported by `tcf list -vv TARGETNAME`), such as:

    - stream_filename: name of the file where to dump the capture
      output in the capture/ subdirectory; file shall be overwritten.
    - log_filename: name of the file where we are capturing execution
      log in the capture/ subdirectory; file shall be overwritten.
    - id: target's name
    - type: target's type
    - ... (more with `tcf list -vv TARGETNAME`)

    **System configuration**

    It is highly recommendable to configure *udev* to generate device
    nodes named after the target's name, so make configuration simpler
    and isolate the system from changes in the device enumeration
    order.

    For example, adding to `/etc/udev/rules.d/90-ttbd.rules`::

      SUBSYSTEM == "video4linux", ACTION == "add", \
          KERNEL=="video*", \
          ENV{ID_SERIAL} == "SERIALNUMBER", \
          SYMLINK += "video-TARGETNAME"

    where *SERIALNUMBER* is the serial number of the device that
    captures the screen for *TARGETNAME*. Note it is recommended to
    call the video interface *video-SOMETHING* so that tools such as
    *ffmpeg* won't be confused.
    """
    def __init__(self, name, cmdline, mimetype, pre_commands = None,
                 extension = ""):
        assert isinstance(name, str_type)
        assert isinstance(cmdline, str_type)
        assert isinstance(extension, str_type)
        self.name = name
        self.cmdline = cmdline.split()
        if pre_commands:
            self.pre_commands = pre_commands
            assert all([ isinstance(command, str_type)
                         for command in pre_commands ]), \
                             "list of pre_commands have to be strings"
        else:
            self.pre_commands = []
        self.extension = extension
        impl_c.__init__(self, True, mimetype, log = "text/plain")
        # we make the cmdline be the unique physical identifier, since
        # it is like a different implementation each
        self.upid_set(name, serial_number = commonl.mkid(cmdline))


    def start(self, target, capturer, path):
        stream_filename = capturer + self.extension
        log_filename = capturer + ".log"

        kws = target.kws_collect(self)
        kws['output_file_name'] = os.path.join(path, stream_filename)	# LEGACY
        kws['stream_filename'] = os.path.join(path, stream_filename)	# LEGACY
        kws['_impl.stream_filename'] = os.path.join(path, stream_filename)
        kws['_impl.log_filename'] = os.path.join(path, log_filename)
        kws['_impl.capturer'] = capturer
        kws['_impl.timestamp'] = str(datetime.datetime.utcnow())

        with open(kws['_impl.log_filename'], "w+") as logf:
            logf.write(commonl.kws_expand("""\
INFO: ttbd running generic_snaphost capture for '%(_impl.capturer)s' at %(_impl.timestamp)s
INFO: log_file (this file): %(_impl.log_filename)s
INFO: stream_file: %(_impl.stream_filename)s
""", kws))
            try:
                for command in self.pre_commands:
                    # yup, run with shell -- this is not a user level
                    # command, the configurator has full control
                    pre_command = commonl.kws_expand(command, kws)
                    logf.write("INFO: calling pre-command: %s\n" % pre_command)
                    logf.flush()
                    subprocess.check_call(
                        pre_command,
                        shell = True, close_fds = True, cwd = "/tmp",
                        stdout = logf, stderr = subprocess.STDOUT)
                cmdline = []
                for i in self.cmdline:
                    cmdline.append(commonl.kws_expand(i, kws))
                target.log.info("%s: snapshot command: %s" % (
                    capturer, " ".join(cmdline)))
                logf.write("INFO: calling commandline: %s\n"
                           % " ".join(cmdline))
                logf.flush()
                subprocess.check_call(
                    cmdline, cwd = "/tmp", shell = False, close_fds = True,
                    stdout = logf, stderr = subprocess.STDOUT)
                target.log.info("%s: generic snapshot taken" % capturer)
            except subprocess.CalledProcessError as e:
                target.log.error(
                    "%s: capturing of '%s' with '%s' failed: (%d) %s" % (
                        capturer, self.name, " ".join(e.cmd),
                        e.returncode, e.output))
                logf.write("ERROR: capture failed\n")
                raise
        # report we rare no streaming (snapshot!) and the streams
        # provided in the capture/ directory
        return False, { "default": stream_filename, "log": log_filename }

    # no stop() because is a snapshot capturer



class generic_stream(impl_c):
    """
    This is a generic stream capturer which can be used to invoke any
    program that will do capture the stream for a while.

    For example, in a server configuration file, define a capturer
    that will record video with ffmpeg from a camera that is pointing
    to the target's monitor or an HDMI capturer:

    >>> capture_vstream_ffmpeg_v4l = ttbl.capture.generic_snapshot(
    >>>    "%(id)s screen",
    >>>    "ffmpeg -i /dev/video-%(id)s-0"
    >>>    " -f avi -qscale:v 10 -y %(output_file_name)s",
    >>>     mimetype = "video/avi",
    >>>     wait_to_kill = 0.25,
    >>>     pre_commands = [
    >>>         "v4l2-ctl -d /dev/video-%(id)s-0 -c focus_auto=0"
    >>>     ]
    >>> )

    Then attach the capture interface to the target with:

    >>> ttbl.test_target.get('TARGETNAME').interface_add(
    >>>     "capture",
    >>>     ttbl.capture.interface(
    >>>         hdmi0_vstream = capture_vstream_ffmpeg_v4l,
    >>>         ...
    >>>     )
    >>> )

    Now, when the client runs to start the capture::

      $ tcf capture-start TARGETNAME hdmi0_vstream

    will execute in the server the pre-commands::

      $ v4l2-ctl -d /dev/video-TARGETNAME-0 -c focus_auto=0

    and then start recording with::

      $ ffmpeg -i /dev/video-TARGETNAME-0 -f avi -qscale:v 10 -y SOMEFILE

    so that when we decide it is done, in the client::

      $ tcf capture-get TARGETNAME hdmi0_vstream file.avi

    it will stop recording and download the video file with the
    recording to `file.avi`.

    :param str name: name for error messges from this capturer
    :param str cmdline: commandline to invoke the capturing of the
      stream
    :param str mimetype: MIME type of the capture output, eg video/avi
    :param list pre_commands: (optional) list of commands (str_type) to
      execute before the command line, to for example, set
      volumes.
    :param int wait_to_kill: (optional) time to wait since we send a
      SIGTERM to the capturing process until we send a SIGKILL, so it
      has time to close the capture file. Defaults to one second.

    Note all string parameters are `%(keyword)s` expanded from the
    target's tags (as reported by `tcf list -vv TARGETNAME`), such as:

    - output_file_name: name of the file where to dump the capture
      output; file shall be overwritten.
    - id: target's name
    - type: target's type
    - ... (more with `tcf list -vv TARGETNAME`)

    For more information, look at :class:`ttbl.capture.generic_snapshot`.
    """
    def __init__(self, name, cmdline, mimetype,
                 extension = "",
                 pre_commands = None,
                 wait_to_kill = 2,
                 use_signal = signal.SIGINT, kws = None):
        assert isinstance(name, str_type)
        assert isinstance(cmdline, str_type)
        assert wait_to_kill > 0
        self.name = name
        self.cmdline = cmdline.split()
        self.wait_to_kill = wait_to_kill
        self.extension = extension
        self.use_signal = use_signal
        if pre_commands:
            self.pre_commands = pre_commands
            assert all([ isinstance(command, str_type)
                         for command in pre_commands ]), \
                             "list of pre_commands have to be strings"
        else:
            self.pre_commands = []
        impl_c.__init__(self, False, mimetype, log = 'text/plain')
        # we make the cmdline be the unique physical identifier, since
        # it is like a different implementation each
        self.upid_set(name, serial_number = commonl.mkid(cmdline_s))
        if kws == None:
            self.kws = {}
        else:
            commonl.assert_dict_key_strings(kws, "key")
            self.kws = dict(kws)


    def start(self, target, capturer, path):
        commonl.makedirs_p(path)
        stream_filename = "%s%s" % (capturer, self.extension)
        log_filename = "%s.log" % capturer
        pidfile = "%s/capture-%s.pid" % (target.state_dir, capturer)

        kws = target.kws_collect(self)
        kws['output_file_name'] = os.path.join(path, stream_filename)	# LEGACY
        kws['stream_filename'] = os.path.join(path, stream_filename)	# LEGACY
        kws['_impl.stream_filename'] = os.path.join(path, stream_filename)
        kws['_impl.log_filename'] = os.path.join(path, log_filename)
        kws['_impl.capturer'] = capturer
        kws['_impl.timestamp'] = str(datetime.datetime.utcnow())

        with open(kws['_impl.log_filename'], "w+") as logf:
            logf.write(commonl.kws_expand("""\
INFO: ttbd running generic_stream capture for '%(_impl.capturer)s' at %(_impl.timestamp)s
INFO: log_file (this file): %(_impl.log_filename)s
INFO: stream_file: %(_impl.stream_filename)s
""", kws))
            try:
                for command in self.pre_commands:
                    # yup, run with shell -- this is not a user level
                    # command, the configurator has full control
                    pre_command = commonl.kws_expand(command, kws)
                    logf.write("INFO: calling pre-command: %s\n" % pre_command)
                    logf.flush()
                    subprocess.check_call(
                        pre_command,
                        shell = True, close_fds = True, cwd = "/tmp",
                        stdout = logf, stderr = subprocess.STDOUT)
                cmdline = []
                for i in self.cmdline:
                    cmdline.append(commonl.kws_expand(i, kws))
                target.log.info("%s: stream command: %s" % (
                    capturer, " ".join(cmdline)))
                logf.write("INFO: calling commandline: %s\n"
                           % " ".join(cmdline))
                logf.flush()
                p = subprocess.Popen(
                    cmdline, cwd = "/tmp", shell = False, close_fds = True,
                    stdout = logf, stderr = subprocess.STDOUT)
                target.log.info("%s: generic streaming started" % capturer)
            except subprocess.CalledProcessError as e:
                target.log.error(
                    "%s: capturing of '%s' with '%s' failed: (%d) %s" % (
                        capturer, self.name, " ".join(e.cmd),
                        e.returncode, e.output))
                logf.write("ERROR: capture failed\n")
                raise

        with open(pidfile, "w+") as pidf:
            pidf.write("%s" % p.pid)
        ttbl.daemon_pid_add(p.pid)

        # report we rare no streaming (snapshot!) and the streams
        # provided in the capture/ directory
        return False, { "default": stream_filename, "log": log_filename }


    def stop(self, target, capturer, path):
        pidfile = "%s/capture-%s.pid" % (target.state_dir, capturer)
        target.log.info("%s: stopping generic streaming", capturer)
        commonl.process_terminate(pidfile, tag = "capture:" + capturer,
                                  wait_to_kill = self.wait_to_kill,
                                  use_signal = self.use_signal)
        target.log.info("%s: generic streaming stopped", capturer)
