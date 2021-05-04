#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""Flash binaries/images into the target
-------------------------------------

Interfaces and drivers to flash blobs/binaries/anything into targets;
most commonly these are firmwares, BIOSes, configuration settings that
are sent via some JTAG or firmware upgrade interface.

*Images* (the blobs/binaries/anything) are flashed by a *flashing
device* into an *image type* (which represents a destination a
flashing device can flash).

Interface implemented by :class:`ttbl.images.interface <interface>`,
drivers implemented subclassing :class:`ttbl.images.impl_c <impl_c>`.

A most generic use case is when a target has multiple flashing devices
connected to it; there is a mix of (here a device means a *flashing
device*):

- a device that can flash multiple images to different
  locations (eg: USB DFU, Quartus, OpenOCD)

- devices that can flash only one image at the time (eg: SF100/600)

- devices that impose power requirements on the target (eg: the whole
  thing has to be off, or this subcomponent has to be powered on) and
  thus impose power pre/post sequences

- devices that need to be disconnected for the target to power on and
  work normally

- devices that can operate in parallel (since they flash different
  things and have compatible power requirements on the target)

  eg: two devices that require the target being powered off can flash
  at the same time, while a third that needs it on, but have to be
  done separately.

- (not yet supported) mandating an order in flashing of the image
  types. By default the order followed is the order of declaration in
  the interface.

For example; a user that wants to flash the following files in the
given image types::

  imageA:fileA
  imageB:fileB
  image:fileX
  imageC:fileC
  iamgeD:fileD
  imageE:fileE
  imageF:fileF
  imageG:fileG
  imageH:fileH

The target configuration maps the folling implementations (instances
deriving from :class:ttbl.images.impl_c) to drive the flashing of each
target type:

- image is an aka of imageA

- imageA done by implA

- imageB done by implB

- imageC and imageD done by implCD (parallel capable)

- imageE done by implE (parallel capable)

- imageF done by implF (parallel capable)

- imageG and imageH done by implGH

this will flash:

- serially:

  - fileA and fileX in imageA using driver implA, so one will get
    overriden and not even flashed depending on the specification order

  - fileB in imageB using driver implB

  - fileG in imageG and fileh in imageH using implGH

- in parallel:

   - fileC in imageC and fileD in imageD using driver implCD

   - fileE in imageE using implE

   - fileF in imageF using implF

Power control sequences before flashing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There is the posibility of executing :meth:`power control sequences
<ttbl.power.interface.sequence>` before performing a flash operations:

- Implementations that work serially (their *parallel* method says
  *False*) can execute pre and post sequences before each executes and
  flashes the images assigned to it.

  In the example above, *implB* can have its on pre/post sequnece that
  it'll be run before and after flashing *fileB* in *imageB*. As well,
  *implGH* can have it's sequences that will be run befora and after
  flashing both *fileG* and *fileH*.

- Implementations that work in parallel share a common pre/post
  sequence that is given to the interface constructor; the pre
  sequence is run first, then all the parallel flashers are started
  and then the post sequence is ran.

When some of the flashers or power steps fail, the result is
indetermined in what was run and what not; at that point the safest
course is to assume the hardware is in an undertermined state and do a
full power off.

It is generally a good idea to configure the flashing sequences to
always start with a full power off, then powering on only the
components needed to do the flashing operation after a short wait
(thus to ensure a well known HW state)--this example assumes there is
a power component called *flasher/image0 connector* that
powers-on/connects the flasher for *image0* (a Dediprog in the example):

.. code-block:: python

   target.interface_add(
       "images", ttbl.images.interface(
           image0 = ttbl.images.flash_shell_cmd_c(
               cmdline = [ "/usr/local/bin/dpcmd", "--device", "SERIALNUMBER",
                           "--silent", "--log", "%(image.image0)s.log",
                           "--batch", "%(image.image0)s"
               ],
               estimated_duration = 10,
               power_sequence_pre = [
                   ( 'off', 'full' ),
                   ( 'wait', 3 ),
                   ( 'on', 'flasher/image0 connector' )
               ],
               power_sequence_post = [
                   ( 'off', 'flasher/image0 connector' )
               ],
           ),
       ))

The flashers are usually defined as explicit/on components, so they
are only turned on if explicitly named and stay off otherwise; for
example, to control connectivity with a USB YKush Power switcher

.. code-block:: python

   target.interface_add(
       "power", ttbl.power.interface(
           ...
           (
              "flasher/image0 connector",
              ttbl.pc_ykush.ykush("YK12345", 1, explicit = 'on')
           ),
           (
              "flasher/image1 connector",
              ttbl.pc_ykush.ykush("YK12345", 2, explicit = 'on')
           ),
           ...
        ))

for parallel flashers, it'd be similar, but it would turn on all the
flashers::

   target.interface_add(
       "images", ttbl.images.interface(
           image0 = ttbl.images.flash_shell_cmd_c(
               cmdline = [ "/usr/local/bin/dpcmd", "--device", "SERIALNUMBER0",
                           "--silent", "--log", "%(image.image0)s.log",
                           "--batch", "%(image.image0)s"
               ],
               estimated_duration = 10, parallel = True,
           ),
           image1 = ttbl.images.flash_shell_cmd_c(
               cmdline = [ "/usr/local/bin/dpcmd", "--device", "SERIALNUMBER1",
                           "--silent", "--log", "%(image.image1)s.log",
                           "--batch", "%(image.image1)s"
               ],
               estimated_duration = 10, parallel = True,
           ),
           power_sequence_pre = [
               ( 'off', 'full' ),
               ( 'wait', 3 ),
               ( 'on', 'flasher/image0 connector' )
               ( 'on', 'flasher/image1 connector' )
           ],
           power_sequence_post = [
               ( 'off', 'flasher/image0 connector' )
               ( 'off', 'flasher/image1 connector' )
           ],
       ))



"""

import codecs
import collections
import copy
import errno
import hashlib
import json
import numbers
import os
import subprocess
import time

import serial

import commonl
import ttbl
import ttbl.store

class impl_c(ttbl.tt_interface_impl_c):
    """Driver interface for flashing with :class:`interface`

    Power control on different components can be done before and after
    flashing; the process is executed in the folowing order:

    - pre power sequence of power components
    - flash
    - post power sequence of power components

    :param list(str) power_cycle_pre: (optional) before flashing,
      power cycle the target. Argument is a list of power rail
      component names.

      - *None* (default) do not power cycle
      - *[]*: power cycle all components
      - *[ *COMP*, *COMP* .. ]*: list of power components to power
        cycle

      From this list, anything in :data:power_exclude will be
      excluded.

    :param list(str) power_sequence_pre: (optional) FIXME

    :param list(str) power_sequence_post: (optional) FIXME

    :param list(str) console_disable: (optional) before flashing,
      disable consoles and then re-enable them. Argument is a list of
      console names that need disabling and then re-enabling.

    :param int estimated_duration: (optional; default 60) seconds the
      imaging process is believed to take. This can let the client
      know how long to wait for before declaring it took too long due
      to other issues out of server's control (eg: client to server
      problems).

    :param str log_name: (optional, defaults to image name)
      string to use to generate the log file name (*flash-NAME.log*);
      this is useful for drivers that are used for multiple images,
      where it is not clear which one will it be called to flash to.
    """
    def __init__(self,
                 power_sequence_pre = None,
                 power_sequence_post = None,
                 consoles_disable = None,
                 log_name = None,
                 estimated_duration = 60):
        assert isinstance(estimated_duration, int)
        assert log_name == None or isinstance(log_name, basestring)

        commonl.assert_none_or_list_of_strings(
            consoles_disable, "consoles_disable", "console name")

        # validation of this one by ttbl.images.interface._target_setup
        self.power_sequence_pre = power_sequence_pre
        self.power_sequence_post = power_sequence_post
        if consoles_disable == None:
            consoles_disable = []
        self.parallel = False	# this class can't do parallel
        self.consoles_disable = consoles_disable
        self.estimated_duration = estimated_duration
        self.log_name = log_name
        ttbl.tt_interface_impl_c.__init__(self)

    def flash(self, target, images):
        """
        Flash *images* onto *target*

        :param ttbl.test_target target: target where to flash

        :param dict images: dictionary keyed by image type of the
          files (in the servers's filesystem) that have to be
          flashed.

        The implementation assumes, per configuration, that this
        driver knows how to flash the images of the given type (hence
        why it was configured) and shall abort if given an unknown
        type.

        If multiple images are given, they shall be (when possible)
        flashed all at the same time.
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(images, dict)
        raise NotImplementedError


class impl2_c(impl_c):
    """
    Flasher interface implementation that is capable of execution of
    multiple flashings in parallel.

    The flashing infrastructure will call :meth:flash_start to get the
    flashing process started and then call :meth:flash_check_done
    periodically until it finishes; if it exceeds the declared timeout
    in :attr:estimated_timeout, it will be killed with
    :meth:flash_kill, otherwise, execution will be verified with
    :meth:flash_check_done.

    Falls back to serial execution if *parallel = False* (default) or
    needed by the infrastructure for other reasons.

    :param float check_period: (optional; defaults to 2) interval in
      seconds in which we check how the flashing operation is going by
      calling :meth:flash_check_done.

    :param bool parallel: (optional; defaults to *False*) execute in
      parallel or serially.

      If enabled for parallel execution, no flasher specific pre/post
      power sequences will be run, only the global ones specifed as
      arguments to the :class:ttbl.images.interface.


    :param int retries (optional; defaults to 3) how many times to
      retry before giving up, on failure.

      Note you can/should overload :meth:`flast_post_check` so that on
      failure (if it returns anything but *None*) you might perform a
      recovery action.

    Other parameters as :class:ttbl.images.impl_c

    .. note:: Rules!!!

             - Don't store stuff in self, use *context* (this is to
               allow future expansion)

    """
    def __init__(self, check_period = 2, parallel = False, retries = 3, **kwargs):
        assert isinstance(check_period, numbers.Real) and check_period > 0.5, \
            "check_period must be a positive number of seconds " \
            "greater than 0.5; got %s" % type(check_period)
        assert isinstance(parallel, bool), \
            "parallel must be a bool; got %s" % type(parallel)
        assert isinstance(retries, int) and retries >= 0, \
            "retries must be >= 0; got %s" % type(retries)
        self.check_period = check_period
        self.retries = retries
        impl_c.__init__(self, **kwargs)
        # otherwise it is overriden
        self.parallel = parallel

    def flash_start(self, target, images, context):
        """
        Start the flashing process

        :param ttbl.test_target target: target where to operate

        :param dict images: dictionary keyed by image type with the
          filenames to flash on each image type

        :param dict context: dictionary where to store state; any
          key/value can be stored in there for use of the driver.

          - *ts0*: *time.time()* when the process started

        This is meant to be a non blocking call, just background start
        the flashing process, record in context needed tracking
        information and return.

        Do not use Python threads or multiprocessing, just fork().

        """
        raise NotImplementedError

    def flash_check_done(self, target, images, context):
        """
        Check if the flashing process has completed

        Same arguments as :meth:flash_start.

        Eg: check the PID in *context['pid']* saved by
        :meth:flash_start is still alive and corresponds to the same
        path. See :class:flash_shell_cmd_c for an example.
        """
        raise NotImplementedError

    def flash_kill(self, target, images, context, msg):
        """
        Kill a flashing process that has gone astray, timedout or others

        Same arguments as :meth:flash_start.

        :param str msg: message from the core on why this is being killed

        Eg: kill the PID in *context['pid']* saved by
        :meth:flash_start. See :class:flash_shell_cmd_c for an example.
        """
        raise NotImplementedError

    def flash_post_check(self, target, images, context):
        """
        Check execution logs after a proces succesfully completes

        Other arguments as :meth:flash_start.

        Eg: check the logfile for a flasher doesn't contain any tell
        tale signs of errors. See :class:flash_shell_cmd_c for an example.
        """
        raise NotImplementedError
        return None	# if all ok
        return {}	# diagnostics info

    def flash(self, target, images):
        """
        Flashes in serial mode a parallel-capable flasher
        """
        context = dict()		# setup as interface._flash_parallel()
        context['ts0'] = time.time()
        self.flash_start(target, images, context)
        ts = ts0 = time.time()
        while ts - ts0 < self.estimated_duration:
            time.sleep(self.check_period)
            target.timestamp()	# timestamp so we don't idle...
            if self.flash_check_done(target, images, context) == True:
                break
            ts = time.time()
        else:
            msg = "%s: flashing failed: timedout after %ds" \
                % (" ".join(images.keys()), self.estimated_duration)
            self.flash_kill(target, images, context, msg)
            raise RuntimeError(msg)

        self.flash_post_check(target, images, context)
        target.log.info("flashed image")


class interface(ttbl.tt_interface):
    """Interface to flash a list of images (OS, BIOS, Firmware...) that
    can be uploaded to the target server and flashed onto a target.

    Any image type can be supported, it is up to the configuration to
    set the image types and the driver that can flash them. E.g.:

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface({
    >>>         "kernel-x86": ttbl.openocd.pc(),
    >>>         "kernel-arc": "kernel-x86",
    >>>         "rom": ttbl.images.dfu_c(),
    >>>         "bootloader": ttbl.images.dfu_c(),
    >>>     })
    >>> )

    Aliases can be specified that will refer to the another type; in
    that case it is implied that images that are aliases will all be
    flashed in a single call. Thus in the example above, trying to
    flash an image of each type would yield three calls:

    - a single *ttbl.openocd.pc.flash()* call would be done for images
      *kernel-x86* and *kernel-arc*, so they would be flashed at the
      same time.
    - a single *ttbl.images.dfu_c.flash()* call for *rom*
    - a single *ttbl.images.dfu_c.flash()* call for *bootloader*

    If *rom* were an alias for *bootloader*, there would be a single
    call to *ttbl.images.dfu_c.flash()*.

    The imaging procedure might take control over the target, possibly
    powering it on and off (if power control is available). Thus,
    after flashing no assumptions shall be made and the safest one is
    to call (in the client) :meth:`target.power.cycle
    <tcfl.target_ext_power.extension.cycle>` to ensure the right
    state.

    Whenever an image is flashed in a target's flash destination, a
    SHA512 hash of the file flashed is exposed in metadata
    *interfaces.images.DESTINATION.last_sha512*. This can be used to
    determine if we really want to flash (if you want to assume the
    flash doesn't change) or to select where do we want to run
    (because you want an specific image flashed).

    """
    def __init__(self, *impls,
                 # python2 doesn't support this combo...
                 #power_sequence_pre = None,
                 #power_sequence_post = None,
                 **kwimpls):
        # FIXME: assert
        self.power_sequence_pre = kwimpls.pop('power_sequence_pre', None)
        self.power_sequence_post = kwimpls.pop('power_sequence_post', None)
        ttbl.tt_interface.__init__(self)
        self.impls_set(impls, kwimpls, impl_c)

    def _target_setup(self, target, iface_name):
        if self.power_sequence_pre:
            target.power.sequence_verify(target, self.power_sequence_pre,
                                         "flash pre power sequence")
        if self.power_sequence_post:
            target.power.sequence_verify(target, self.power_sequence_post,
                                         "flash post power sequence")
        for name, impl in self.impls.iteritems():
            commonl.verify_str_safe(name)
            target.fsdb.set(
                "interfaces.images." + name + ".estimated_duration",
                impl.estimated_duration)
            if impl.power_sequence_pre:
                target.power.sequence_verify(
                    target, impl.power_sequence_pre,
                    "flash %s pre power sequence" % name)
            if impl.power_sequence_post:
                target.power.sequence_verify(
                    target, impl.power_sequence_post,
                    "flash %s post power sequence" % name)

    def _release_hook(self, target, _force):
        pass

    def _hash_record(self, target, images):
        # if update MD5s of the images we flashed (if succesful)
        # so we can use this to select where we want to run
        #
        # The name is not a fully good reference, but still helpful
        # sometimes; the name can change though, but the content stays
        # the same, hence the hash is the first reference one.
        #
        # note this gives the same result as:
        #
        ## $ sha512sum FILENAME
        #
        for image_type, name in images.items():
            ho = commonl.hash_file(hashlib.sha512(), name)
            target.fsdb.set(
                "interfaces.images." + image_type + ".last_sha512",
                ho.hexdigest()
            )
            target.fsdb.set(
                "interfaces.images." + image_type + ".last_name",
                name
            )

    def _impl_flash(self, impl, target, subimages):
        if impl.power_sequence_pre:
            target.power.sequence(target, impl.power_sequence_pre)
        try:
            # in some flashers, the flashing occurs over a
            # serial console we might be using, so we can
            # disable it -- we'll renable on exit--or not.
            # This has to be done after the power-cycle, as it might
            # be enabling consoles
            # FIXME: move this for parallel too?
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s: disabling console %s to allow flasher to work"
                    % (img_type, console_name))
                target.console.put_disable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)
            impl.flash(target, subimages)
            self._hash_record(target, subimages)

            # note in case of flashing failure we don't
            # necessarily power on the components, since
            # things might be a in a bad state--we let the
            # user figure it out.
        finally:
            # FIXME: move this for parallel too?
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s: enabling console %s after flashing"
                    % (img_type, console_name))
                target.console.put_enable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)
        # note this might seem counterintuitive; the
        # configuration might specify some components are
        # switched off while others are power cycled, or none
        if impl.power_sequence_post:
            target.power.sequence(target, impl.power_sequence_post)

    def _flash_parallel_once(self, target, parallel, failed):
        # flash a parallel-capable flasher in a serial fashion
        contexts = {}
        estimated_duration = 0
        check_period = 4
        all_images = [ ]
        for impl, images in parallel.items():
            context = dict()
            context['ts0'] = time.time()
            contexts[impl] = context
            estimated_duration = max(impl.estimated_duration, estimated_duration)
            check_period = min(impl.check_period, check_period)
            impl.flash_start(target, images, context)
            all_images += images.keys()

        ts = ts0 = time.time()
        done = set()
        while ts - ts0 < estimated_duration:
            target.timestamp()	# timestamp so we don't idle...
            time.sleep(check_period)
            for impl, images in parallel.items():
                context = contexts[impl]
                ts = time.time()
                if ts - ts0 > impl.check_period \
                   and impl.flash_check_done(target, images, context) == True:
                    done.update(images.keys())
            ts = time.time()
            if len(done) == len(contexts):
                break
        else:
            msg = "%s/%s: flashing failed: timedout after %ds" \
                % (target.id, " ".join(all_images), estimated_duration)
            for impl, images in parallel.items():
                impl.flash_kill(target, images, contexts[impl], msg)
            raise RuntimeError(msg)

        for impl, images in parallel.items():
            context = contexts[impl]
            r = impl.flash_post_check(target, images, context)
            if r == None:
                self._hash_record(target, images)
            else:
                image_names = ",".join(images.keys())
                failed.append(( impl, image_names, r))


    def _flash_parallel(self, target, parallel):
        if self.power_sequence_pre:
            target.power.sequence(target, self.power_sequence_pre)

        total_estimated_duration = 0
        retry_counters = collections.defaultdict(int)
        for impl in parallel.keys():
            total_estimated_duration = max(
                total_estimated_duration,
                impl.retries * impl.estimated_duration)
        total_estimated_duration /= 2

        # run flashings as long as their retry counters are up
        ts0 = time.time()
        results = {}
        while True:
            failed = []
            _parallel = {}
            tasks = []
            for impl in parallel:
                if retry_counters[impl] >= 0:
                    _parallel[impl] = parallel[impl]
                    tasks.append("%s (%d/%d tries)" % (
                        parallel[impl], retry_counters[impl], impl.retries))
            target.log.info("%s: flashing %s", target.id, " ".join(tasks))
            self._flash_parallel_once(target, _parallel, failed)
            if not failed:
                break			# we are good here
            ts = time.time()
            if ts - ts0 > total_estimated_duration:
                raise RuntimeError(
                    "%s: flashing failed: timedout after %fs"
                    % (target.id, total_estimated_duration))

            for impl, image_names, r in failed:
                retry_counters[impl] += 1
                current_count = retry_counters[impl]
                if current_count >= impl.retries:
                    raise RuntimeError(
                        "%s/%s: flashing failed after %d retries: %s" % (
                            target.id, image_names, impl.retries, r))
                target.log.warning(
                    "%s/%s: flashing retrying %d/%d because of result: %s",
                    target.id, image_names,
                    retry_counters[impl],
                    impl.retries, r)

        # note the post sequence is not run in case of flashing error,
        # this is intended, things might be a in a weird state, so a
        # full power cycle might be needed
        if self.power_sequence_post:
            target.power.sequence(target, self.power_sequence_post)
        target.log.info("flashed images" + " ".join(parallel.values()))


    def put_flash(self, target, who, args, _files, user_path):
        images = self.arg_get(args, 'images', dict)
        with target.target_owned_and_locked(who):
            # look at all the images we are asked to flash and
            # classify them, depending on what implementation will
            # handle them
            #
            # We'll give a single call to each implementation with all
            # the images it has to flash in the same order they are
            # given to us (hence the OrderedDict)
            #
            # Note we DO resolve aliases here (imagetype whole
            # implementation is a string naming another
            # implementation); the implementations do not know / have
            # to care about it; if the user specifies *NAME-AKA:FILEA
            # NAME:FILEB*, then FILEB will be flashed and FILEA
            # ignored; if they do *NAME:FILEB NAME-AKA:FILEA*, FILEA
            # will be flashed.
            #
            # flashers that work serially bucketed separated from the
            # ones that can do parallel
            serial = collections.defaultdict(collections.OrderedDict)
            parallel = collections.defaultdict(collections.OrderedDict)
            for img_type, img_name in images.iteritems():
                # validate image types (from the keys) are valid from
                # the components and aliases
                impl, img_type_real = self.impl_get_by_name(img_type,
                                                            "image type")
                if not os.path.isabs(img_name):
                    # file comes from the user's storage
                    file_name = os.path.join(user_path, img_name)
                else:
                    # file from the system (mounted FS or similar);
                    # double check it is allowed
                    for path, path_translated in ttbl.store.paths_allowed.items():
                        if img_name.startswith(path):
                            img_name = img_name.replace(path, path_translated, 1)
                            break
                    else:
                        # FIXME: use PermissionError in Python3
                        raise RuntimeError(
                            "%s: absolute image path tries to read from"
                            " a location that is not allowed" % img_name)
                    file_name = img_name
                # we need to lock, since other processes might be
                # trying to decompress the file at the same time
                # We want to have the lock in another directory
                # because the source directory where the file name
                # might be might not be writable to us
                lock_file_name = os.path.join(
                    target.state_dir,
                    "images.flash.decompress."
                    + commonl.mkid(file_name)
                    + ".lock")
                with ttbl.process_posix_file_lock_c(lock_file_name):
                    # if a decompressor crashed, we have no way to
                    # tell if the decompressed file is correct or
                    # truncated and thus corrupted -- we need manual
                    # for that
                    real_file_name = commonl.maybe_decompress(file_name)
                if impl.parallel:
                    parallel[impl][img_type_real] = real_file_name
                else:
                    serial[impl][img_type_real] = real_file_name
                if real_file_name.startswith(user_path):
                    # modify the mtime, so the file storage cleanup knows
                    # we are still using this file and doesn't not attempt
                    # to clean it up too soon
                    commonl.file_touch(real_file_name)
            target.timestamp()
            # iterate over the real implementations only
            for impl, subimages in serial.iteritems():
                self._impl_flash(impl, target, subimages)
            # FIXME: collect diagnostics here of what failed only if
            # 'admin' or some other role?
            if parallel:
                self._flash_parallel(target, parallel)
            return {}

    # FIXME: save the names of the last flashed in fsdb so we can
    # query them? relative to USERDIR or abs to system where allowed
    def get_list(self, _target, _who, _args, _files, _user_path):
        return dict(
            aliases = self.aliases,
            result = self.aliases.keys() + self.impls.keys())


class arduino_cli_c(impl_c):
    """Flash with the `Arduino CLI <https://www.arduino.cc/pro/cli>`

    For example:

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-arm": ttbl.images.arduino_cli_c(),
    >>>         "kernel": "kernel-arm",
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str sketch_fqbn: (optional) name of FQBN to be used to
      program the board (will be passed on the *--fqbn* arg to
      *arduino-cli upload*).

    Other parameters described in :class:ttbl.images.impl_c.

    *Requirements*

    - Needs a connection to the USB programming port, represented as a
      serial port (TTY)

    .. _arduino_cli_setup:

    - *arduino-cli* has to be available in the path variable :data:`path`.

      To install Arduino-CLI::

        $ wget https://downloads.arduino.cc/arduino-cli/arduino-cli_0.9.0_Linux_64bit.tar.gz
        # tar xf arduino-cli_0.9.0_Linux_64bit.tar.gz  -C /usr/local/bin

      The boards that are going to be used need to be pre-downloaded;
      thus, if the board FQBN *XYZ* will be used and the daemon will
      be running as user *ttbd*::

        # sudo -u ttbd arduino-cli core update-index
        # sudo -u ttbd arduino-cli core install XYZ

      Each user that will compile for such board needs to do the same

    - target declares *sketch_fqbn* in the tags/properties for the BSP
      corresponding to the image. Eg; for *kernel-arm*::

        $ ~/t/alloc-tcf.git/tcf get arduino-mega-01 -p bsps
        {
            "bsps": {
                "arm": {
                    "sketch_fqbn": "arduino:avr:mega:cpu=atmega2560"
                }
            }
        }

      Corresponds to a configuration in the:

      .. code-block:: python

         target.tags_update(dict(
             bsps = dict(
                 arm = dict(
                     sketch_fqbn = "arduino:avr:mega:cpu=atmega2560",
                 ),
             ),
         ))

    - TTY devices need to be properly configured permission wise for
      the flasher to work; it will tell the *console* subsystem to
      disable the console so it can have exclusive access to the
      console to use it for flashing.

        SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "95730333937351308131", \
          SYMLINK += "tty-arduino-mega-01"

    """
    def __init__(self, serial_port = None, sketch_fqbn = None,
                 **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert sketch_fqbn == None or isinstance(sketch_fqbn, basestring)
        self.serial_port = serial_port
        self.sketch_fqbn = sketch_fqbn
        impl_c.__init__(self, **kwargs)
        self.upid_set("Arduino CLI Flasher", serial_port = serial_port)

    #: Path to *arduino-cli*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.arduino_cli_c.path = "/usr/local/bin/arduino-cli"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.arduino_cli_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/arduino-cli"
    path = "/usr/local/bin/arduino-cli"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.items()))
        image_name = images.values()[0]

        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port

        # remember this only handles one image type
        bsp = images.keys()[0].replace("kernel-", "")
        sketch_fqbn = self.sketch_fqbn
        if sketch_fqbn == None:
            # get the Sketch FQBN from the tags for the BSP
            sketch_fqbn = target.tags.get('bsps', {}).get(bsp, {}).get('sketch_fqbn', None)
            if sketch_fqbn == None:
                raise RuntimeError(
                    "%s: configuration error, needs to declare a tag"
                    " bsps.BSP.sketch_fqbn for BSP %s or a sketch_fqbn "
                    "to the constructor"
                    % (target.id, bsp))

        # Arduino Dues and others might need a flash erase
        if sketch_fqbn in [ "arduino:sam:arduino_due_x_dbg" ]:
            # erase the flash by opening the serial port at 1200bps
            target.log.debug("erasing the flash")
            with serial.Serial(port = serial_port, baudrate = 1200):
                time.sleep(0.25)
            target.log.info("erased the flash")

        # now write it
        cmdline = [
            self.path,
            "upload",
            "--port", serial_port,
            "--fqbn", sketch_fqbn,
            "--verbose",
            "--input", image_name
        ]
        target.log.info("flashing image with: %s" % " ".join(cmdline))
        try:
            subprocess.check_output(
                cmdline, stdin = None, cwd = "/tmp",
                stderr = subprocess.STDOUT)
            target.log.info("ran %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (" ".join(cmdline),
                                e.returncode, e.output))
            raise
        target.log.info("flashed image")




class bossac_c(impl_c):
    """Flash with the `bossac <https://github.com/shumatech/BOSSA>`_ tool

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-arm": ttbl.images.bossac_c(),
    >>>         "kernel": "kernel-arm",
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str console: (optional) name of the target's console tied
       to the serial port; this is needed to disable it so this can
       flash. Defaults to *serial0*.

    Other parameters described in :class:ttbl.images.impl_c.

    *Requirements*

    - Needs a connection to the USB programming port, represented as a
      serial port (TTY)

    - *bossac* has to be available in the path variable :data:`path`.

    - (for Arduino Due) uses the bossac utility built on the *arduino*
      branch from https://github.com/shumatech/BOSSA/tree/arduino::

        # sudo dnf install -y gcc-c++ wxGTK-devel
        $ git clone https://github.com/shumatech/BOSSA.git bossac.git
        $ cd bossac.git
        $ git checkout -f 1.6.1-arduino-19-gae08c63
        $ make -k
        $ sudo install -o root -g root bin/bossac /usr/local/bin

    - TTY devices need to be properly configured permission wise for
      bossac to work; for such, choose a Unix group which can get
      access to said devices and add udev rules such as::

        # Arduino2 boards: allow reading USB descriptors
        SUBSYSTEM=="usb", ATTR{idVendor}=="2a03", ATTR{idProduct}=="003d", \
          GROUP="GROUPNAME", MODE = "660"

        # Arduino2 boards: allow reading serial port
        SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "SERIALNUMBER", \
          GROUP = "GROUPNAME", MODE = "0660", \
          SYMLINK += "tty-TARGETNAME"

    For Arduino Due and others, the theory of operation is quite
    simple. According to
    https://www.arduino.cc/en/Guide/ArduinoDue#toc4, the Due will
    erase the flash if you open the programming port at 1200bps and
    then start a reset process and launch the flash when you open the
    port at 115200. This is not so clear in the URL above, but this is
    what expermientation found.

    So for flashing, we'll take over the console, set the serial
    port to 1200bps, wait a wee bit and then call bossac.

    """
    def __init__(self, serial_port = None, console = None, **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self, **kwargs)
        self.serial_port = serial_port
        self.console = console
        self.upid_set("bossac jtag", serial_port = serial_port)

    #: Path to *bossac*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.bossac_c.path = "/usr/local/bin/bossac"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.bossac_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/bossac"
    path = "/usr/bin/bossac"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.items()))
        image_name = images.values()[0]

        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port
        if self.console == None:
            console = "serial0"
        else:
            console = self.console

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None, None)
        # erase the flash by opening the serial port at 1200bps
        target.log.debug("erasing the flash")
        with serial.Serial(port = serial_port, baudrate = 1200):
            time.sleep(0.25)
        target.log.info("erased the flash")

        # now write it
        cmdline = [
            self.path,
            "-p", os.path.basename(serial_port),
            "-e",       # Erase current
            "-w",	# Write a new one
            "-v",	# Verify,
            "-b",	# Boot from Flash
            image_name
        ]
        target.log.info("flashing image with: %s" % " ".join(cmdline))
        try:
            subprocess.check_output(
                cmdline, stdin = None, cwd = "/tmp",
                stderr = subprocess.STDOUT)
            target.log.info("ran %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (" ".join(cmdline),
                                e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
        target.log.info("flashed image")


class dfu_c(impl_c):
    """Flash the target with `DFU util <http://dfu-util.sourceforge.net/>`_

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-x86": ttbl.images.dfu_c(),
    >>>         "kernel-arc": "kernel-x86",
    >>>         "kernel": "kernel-x86",
    >>>     })
    >>> )

    :param str usb_serial_number: target's USB Serial Number

    Other parameters described in :class:ttbl.images.impl_c.

    *Requirements*

    - Needs a connection to the USB port that exposes a DFU
      interface upon boot

    - Uses the dfu-utils utility, available for most (if not all)
      Linux distributions

    - Permissions to use USB devices in */dev/bus/usb* are needed;
      *ttbd* usually roots with group *root*, which shall be
      enough.

    - In most cases, needs power control for proper operation, but
      some MCU boards will reset on their own afterwards.

    Note the tags to the target must include, on each supported
    BSP, a tag named *dfu_interface_name* listing the name of the
    *altsetting* of the DFU interface to which the image for said
    BSP needs to be flashed.

    This can be found, when the device exposes the DFU interfaces
    with the *lsusb -v* command; for example, for a tinyTILE
    (output summarized for clarity)::

      $ lsusb -v
      ...
      Bus 002 Device 110: ID 8087:0aba Intel Corp.
      Device Descriptor:
        bLength                18
        bDescriptorType         1
        ...
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update...
            iInterface              4 x86_rom
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update...
            iInterface              5 x86_boot
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              6 x86_app
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              7 config
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              8 panic
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface              9 events
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             10 logs
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             11 sensor_core
          Interface Descriptor:
            bInterfaceClass       254 Application Specific Interface
            bInterfaceSubClass      1 Device Firmware Update
            iInterface             12 ble_core

    In this case, the three cores available are x86 (x86_app), arc
    (sensor_core) and ARM (ble_core).

    *Example*

    A Tiny Tile can be connected, without exposing a serial console:

    >>> target = ttbl.test_target("ti-01")
    >>> target.interface_add(
    >>>     "power",
    >>>     ttbl.power.interface({
    >>>         ( "USB present",
    >>>           ttbl.pc.delay_til_usb_device("5614010001031629") ),
    >>>     })
    >>> )
    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-x86": ttbl.images.dfu_c("5614010001031629"),
    >>>         "kernel-arm": "kernel-x86",
    >>>         "kernel-arc": "kernel-x86",
    >>>         "kernel": "kernel-x86"
    >>>     })
    >>> )
    >>> ttbl.config.target_add(
    >>>     target,
    >>>     tags = {
    >>>         'bsp_models': { 'x86+arc': ['x86', 'arc'], 'x86': None, 'arc': None},
    >>>         'bsps' : {
    >>>             "x86":  dict(zephyr_board = "tinytile",
    >>>                          zephyr_kernelname = 'zephyr.bin',
    >>>                          dfu_interface_name = "x86_app",
    >>>                          console = ""),
    >>>             "arm":  dict(zephyr_board = "arduino_101_ble",
    >>>                          zephyr_kernelname = 'zephyr.bin',
    >>>                          dfu_interface_name = "ble_core",
    >>>                          console = ""),
    >>>             "arc": dict(zephyr_board = "arduino_101_sss",
    >>>                         zephyr_kernelname = 'zephyr.bin',
    >>>                         dfu_interface_name = 'sensor_core',
    >>>                         console = "")
    >>>         },
    >>>     },
    >>>     target_type = "tinytile"
    >>> )
    """

    def __init__(self, usb_serial_number, **kwargs):
        assert usb_serial_number == None \
            or isinstance(usb_serial_number, basestring)
        impl_c.__init__(self, **kwargs)
        self.usb_serial_number = usb_serial_number
        self.upid_set("USB DFU flasher", usb_serial_number = usb_serial_number)

    #: Path to the dfu-tool
    #:
    #: Change with
    #:
    #: >>> ttbl.images.dfu_c.path = "/usr/local/bin/dfu-tool"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.dfu_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/dfu-tool"
    path = "/usr/bin/dfu-tool"

    def flash(self, target, images):
        cmdline = [ self.path, "-S", self.usb_serial_number ]
        # for each image we are writing to a different interface, we
        # add a -a IFNAME -D IMGNAME to the commandline, so we can
        # flash multiple images in a single shot
        for image_type, image_name in images.iteritems():
            # FIXME: we shall make sure all images are like this?
            if not image_type.startswith("kernel-"):
                raise RuntimeError(
                    "Unknown image type '%s' (valid: kernel-{%s})"
                    % (image_type, ",".join(target.tags['bsps'].keys())))
            bsp = image_type.replace("kernel-", "")
            tags_bsp = target.tags.get('bsps', {}).get(bsp, None)
            if tags_bsp == None:
                raise RuntimeError(
                    "Unknown BSP %s from image type '%s' (valid: %s)"
                    % (bsp, image_type, " ".join(target.tags['bsps'].keys())))
            dfu_if_name = tags_bsp.get('dfu_interface_name', None)
            if dfu_if_name == None:
                raise RuntimeError(
                    "Misconfigured target: image type %s (BSP %s) has "
                    "no 'dfu_interface_name' key to indicate which DFU "
                    "interface shall it flash"
                    % (image_type, bsp))
            cmdline += [ "-a", dfu_if_name, "-D", image_name ]

        # Power cycle the board so it goes into DFU mode; it then
        # stays there for five seconds (FIXME: all of them?)
        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)

        # let's do this
        try:
            target.log.info("flashing image with: %s" % " ".join(cmdline))
            subprocess.check_output(cmdline, cwd = "/tmp",
                                    stderr = subprocess.STDOUT)
            target.log.info("flashed with %s: %s" % (" ".join(cmdline)))
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s" %
                             (" ".join(cmdline), e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
        target.log.info("flashed image")


class fake_c(impl_c):
    """
    Fake flashing driver (mainly for testing the interfaces)

    >>> flasher = ttbl.images.fake_c()
    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-BSP1": flasher,
    >>>         "kernel-BSP2": flasher,
    >>>         "kernel": "kernel-BSPNAME"
    >>>     })
    >>> )

    Parameters like :class:ttbl.images.impl_c.
    """
    def __init__(self, **kwargs):
        impl_c.__init__(self, **kwargs)
        self.upid_set("Fake test flasher", _id = str(id(self)))

    def flash(self, target, images):
        for image_type, image in images.items():
            target.log.info("%s: flashing %s" % (image_type, image))
            time.sleep(self.estimated_duration)
            target.log.info("%s: flashed %s" % (image_type, image))
        target.log.info("%s: flashing succeeded" % image_type)



class esptool_c(impl_c):
    """
    Flash a target using Tensilica's *esptool.py*

    >>> target.interface_add(
    >>>     "images",
    >>>     ttbl.images.interface(**{
    >>>         "kernel-xtensa": ttbl.images.esptool_c(),
    >>>         "kernel": "kernel-xtensa"
    >>>     })
    >>> )

    :param str serial_port: (optional) File name of the device node
       representing the serial port this device is connected
       to. Defaults to */dev/tty-TARGETNAME*.

    :param str console: (optional) name of the target's console tied
       to the serial port; this is needed to disable it so this can
       flash. Defaults to *serial0*.

    Other parameters described in :class:ttbl.images.impl_c.

    *Requirements*

    - The ESP-IDF framework, of which ``esptool.py`` is used to
      flash the target; to install::

        $ cd /opt
        $ git clone --recursive https://github.com/espressif/esp-idf.git

      (note the ``--recursive``!! it is needed so all the submodules
      are picked up)

      configure path to it globally by setting
      :attr:`path` in a /etc/ttbd-production/conf_*.py file:

      .. code-block:: python

         import ttbl.tt
         ttbl.images.esptool_c.path = "/opt/esp-idf/components/esptool_py/esptool/esptool.py"

    - Permissions to use USB devices in */dev/bus/usb* are needed;
      *ttbd* usually roots with group *root*, which shall be
      enough.

    - Needs power control for proper operation; FIXME: pending to
      make it operate without power control, using ``esptool.py``.

    The base code will convert the *ELF* image to the required
    *bin* image using the ``esptool.py`` script. Then it will
    flash it via the serial port.
    """
    def __init__(self, serial_port = None, console = None, **kwargs):
        assert serial_port == None or isinstance(serial_port, basestring)
        assert console == None or isinstance(console, basestring)
        impl_c.__init__(self, **kwargs)
        self.serial_port = serial_port
        self.console = console
        self.upid_set("ESP JTAG flasher", serial_port = serial_port)

    #: Path to *esptool.py*
    #:
    #: Change with
    #:
    #: >>> ttbl.images.esptool_c.path = "/usr/local/bin/esptool.py"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.esptool_c.path(SERIAL)
    #: >>> imager.path =  "/usr/local/bin/esptool.py"
    path = "__unconfigured__ttbl.images.esptool_c.path__"

    def flash(self, target, images):
        assert len(images) == 1, \
            "only one image suported, got %d: %s" \
            % (len(images), " ".join("%s:%s" % (k, v)
                                     for k, v in images.items()))
        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port
        if self.console == None:
            console = "serial0"
        else:
            console = self.console

        cmdline_convert = [
            self.path,
            "--chip", "esp32",
            "elf2image",
        ]
        cmdline_flash = [
            self.path,
            "--chip", "esp32",
            "--port", serial_port,
            "--baud", "921600",
            "--before", "default_reset",
	    # with no power control, at least it starts
            "--after", "hard_reset",
            "write_flash", "-u",
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "detect",
            "0x1000",
        ]

        image_type = 'kernel'
        image_name = images.values()[0]
        image_name_bin = image_name + ".bin"
        try:
            cmdline = cmdline_convert + [ image_name,
                                          "--output", image_name_bin ]
            target.log.info("%s: converting with %s"
                            % (image_type, " ".join(cmdline)))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            target.log.error("%s: converting image with %s failed: (%d) %s"
                             % (image_type, " ".join(cmdline),
                                e.returncode, e.output))
            raise

        target.power.put_cycle(target, ttbl.who_daemon(), {}, None, None)
        # give up the serial port, we need it to flash
        # we don't care it is off because then we are switching off
        # the whole thing and then someone else will power it on
        target.console.put_disable(target, ttbl.who_daemon(),
                                   dict(component = console), None, None)
        try:
            cmdline = cmdline_flash + [ image_name_bin ]
            target.log.info("%s: flashing with %s"
                            % (image_type, " ".join(cmdline)))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
            target.log.info("%s: flashed with %s: %s"
                            % (image_type, " ".join(cmdline), s))
        except subprocess.CalledProcessError as e:
            target.log.error("%s: flashing with %s failed: (%d) %s"
                             % (image_type, " ".join(cmdline),
                                e.returncode, e.output))
            raise
        target.power.put_off(target, ttbl.who_daemon(), {}, None, None)
        target.log.info("%s: flashing succeeded" % image_type)



class flash_shell_cmd_c(impl2_c):
    """
    General flashing template that can use a command line tool to
    flash (possibly in parallel)

    :param list(str) cmdline: list of strings composing the command to
      call; first is the path to the command, that can be overriden
      with the *path* argument

      >>>  [ "/usr/bin/program", "arg1", "arg2" ]

      all the components have to be strings; they will be templated
      using *%(FIELD)s* from the target's metadata, including the
      following fields:

      - *cwd*: directory where the command is being executed

      - *image.TYPE*: *NAME* (for all the images to be flashed, the
         file we are flashing)

      - *image.#<N>*: *NAME* (for all the images to be flashed, the
         file we are flashing), indexed by number in declaration order.

        This is mostly used when there is only one image, so we do not
        need to know the name of the image (*image.#0*).

      - *image_types*: all the image types being flashed separated
         with "-".

      - *pidfile*: Name of the PID file

      - *logfile_name*: Name of the log file

    :param str cwd: (optional; defaults to "/tmp") directory from
      where to run the flasher program

    :param str path: (optional, defaults to *cmdline[0]*) path to the
      flashing program

    :param dict env_add: (optional) variables to add to the environment when
      running the command
    """
    def __init__(self, cmdline, cwd = "/tmp", path = None, env_add = None,
                 **kwargs):
        commonl.assert_list_of_strings(cmdline, "cmdline", "arguments")
        assert cwd == None or isinstance(cwd, basestring)
        assert path == None or isinstance(path, basestring)
        self.p = None
        if path == None:
            path = cmdline[0]
        self.path = path
        self.cmdline = cmdline
        self.cwd = cwd
        if env_add:
            commonl.assert_dict_of_strings(env_add, "env_add")
            self.env_add = env_add
        else:
            self.env_add = {}
        impl2_c.__init__(self, **kwargs)

    def flash_start(self, target, images, context):

        kws = dict(target.kws)
        context['images'] = images

        # make sure they are sorted so they are always listed the same
        image_types = "-".join(sorted(images.keys()))
        kws['image_types'] = image_types
        if self.log_name:
            kws['log_name'] = self.log_name
        else:
            kws['log_name'] = image_types
        # this allows a class inheriting this to set kws before calling us
        context.setdefault('kws', {}).update(kws)
        kws = context['kws']

        count = 0
        for image_name, image in images.items():
            kws['image.' + image_name] = image
            kws['image.#%d' % count ] = image
            count += 1

        pidfile = "%(path)s/flash-%(image_types)s.pid" % kws
        context['pidfile'] = kws['pidfile'] = pidfile

        cwd = self.cwd % kws
        context['cwd'] = kws['cwd'] = cwd

        logfile_name = "%(path)s/flash-%(log_name)s.log" % kws
        # hack so what the log file reading console (if defined) can
        # be restarted properly
        if hasattr(target, "console"):
            console_name = "log-flash-" + kws['log_name']
            if console_name in target.console.impls:
                ttbl.console.generation_set(target, console_name)
        context['logfile_name'] = kws['logfile_name'] = logfile_name

        cmdline = []
        count = 0
        try:
            for i in self.cmdline:
                # some older Linux distros complain if this string is unicode
                cmdline.append(str(i % kws))
            count += 1
        except KeyError as e:
            message = "configuration error? can't template command line #%d," \
                " missing field or target property: %s" % (count, e)
            target.log.error(message)
            raise RuntimeError(message)
        cmdline_s = " ".join(cmdline)
        target.log.info("%s: command line: %s" % (image_types, cmdline_s))
        context['cmdline'] = cmdline
        context['cmdline_s'] = cmdline_s

        if self.env_add:
            env = dict(os.environ)
            env.update(self.env_add)
        else:
            env = os.environ

        ts0 = time.time()
        context['ts0'] = ts0
        try:
            target.log.info("flashing image with: %s" % " ".join(cmdline))
            with open(logfile_name, "w+") as logf:
                self.p = subprocess.Popen(
                    cmdline, env = env, stdin = None, cwd = cwd,
                    stderr = subprocess.STDOUT, stdout = logf)
            with open(pidfile, "w+") as pidf:
                pidf.write("%s" % self.p.pid)
            target.log.debug("%s: flasher PID %s file %s",
                             image_types, self.p.pid, pidfile)
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (cmdline_s, e.returncode, e.output))
            raise

        self.p.poll()
        if self.p.returncode != None:
            msg = "flashing  with %s failed to start: (%s->%s) %s" % (
                cmdline_s, self.p.pid, self.p.returncode, logfile_name)
            target.log.error(msg)
            with open(logfile_name) as logf:
                for line in logf:
                    target.log.error('%s: logfile: %s', image_types, line)
            raise RuntimeError(msg)
        # this is needed so SIGCHLD the process and it doesn't become
        # a zombie
        ttbl.daemon_pid_add(self.p.pid)	# FIXME: race condition if it died?
        target.log.debug("%s: flasher PID %s started (%s)",
                         image_types, self.p.pid, cmdline_s)
        return


    def flash_check_done(self, target, images, context):
        ts = time.time()
        ts0 = context['ts0']
        target.log.debug("%s: [+%.1fs] flasher PID %s checking",
                         context['kws']['image_types'], ts - ts0, self.p.pid)
        self.p.poll()
        if self.p.returncode == None:
            r = False
        else:
            r = True
        ts = time.time()
        target.log.debug(
            "%s: [+%.1fs] flasher PID %s checked %s",
            context['kws']['image_types'], ts - ts0, self.p.pid, r)
        return r


    def flash_kill(self, target, images, context, msg):
        ts = time.time()
        ts0 = context['ts0']
        target.log.debug(
            "%s: [+%.1fs] flasher PID %s terminating due to timeout",
            context['kws']['image_types'], ts - ts0, self.p.pid)
        commonl.process_terminate(context['pidfile'], path = self.path)


    def _log_file_read(self, context, max_bytes = 2000):
        try:
            with codecs.open(context['logfile_name'], errors = 'ignore') as logf:
                try:
                    # SEEK to -MAX_BYTES or if EINVAL (too big), leave it
                    # at beginning of file
                    logf.seek(-max_bytes, 2)
                except IOError as e:
                    if e.errno != errno.EINVAL:
                        raise
                return logf.read()
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            return "<no logls recorded>"

    def flash_post_check(self, target, images, context,
                         expected_returncode = 0):
        """
        Check for execution result.

        :param int expected_returncode: (optional, default 0)
          returncode the command has to return on success. If *None*,
          don't check it.
        """
        if expected_returncode != None and self.p.returncode != expected_returncode:
            msg = "flashing with %s failed, returned %s: %s" % (
                context['cmdline_s'], self.p.returncode,
                self._log_file_read(context))
            target.log.error(msg)
            raise RuntimeError(msg)
        return
        # example, look at errors in the logfile
        try:
            with codecs.open(context['logfile_name'], errors = 'ignore') as logf:
                for line in logf:
                    if 'Fail' in line:
                        logf.seek(0)
                        msg = "flashing with %s failed, issues in logfile: %s" % (
                            context['cmdline_s'], logf.read())
                        target.log.error(msg)
                        raise RuntimeError(msg)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise


class quartus_pgm_c(flash_shell_cmd_c):
    """
    Flash using Intel's Quartus PGM tool

    This allows to flash images to an Altera MAX10, using the Quartus
    tools, freely downloadable from http://dl.altera.com.

    Exports the following interfaces:

    - power control (using any AC power switch, such as the
      :class:`Digital Web Power Switch 7 <ttbl.pc.dlwps7>`)
    - serial console
    - image (in hex format) flashing (using the Quartus Prime tools
      package)

    Multiple instances at the same time are supported; however, due to
    the JTAG interface not exporting a serial number, addressing has
    to be done by USB path, which is risky (as it will change when the
    cable is plugged to another port or might be enumerated in a
    different number).

    :param str device_id: USB serial number of the USB device to use
      (USB-BlasterII or similar)

    :param dict image_map:

    :param str name: (optiona; default 'Intel Quartus PGM #<DEVICEID>')
      instrument's name.

    :param dict args: (optional) dictionary of extra command line options to
      *quartus_pgm*; these are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>`:

      FIXME: move to common flash_shell_cmd_c

    :param dict jtagconfig: (optional) jtagconfig --setparam commands
      to run before starting.

      These are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>` and then run as::

        jtagconfig --setparam CABLENAME KEY VALUE

    Other parameters described in :class:ttbl.images.impl_c.


    **Command line reference**

    https://www.intel.com/content/dam/www/programmable/us/en/pdfs/literature/manual/tclscriptrefmnl.pdf

    Section Quartus_PGM (2-50)

    **System setup**

    -  Download and install Quartus Programmer::

         $ wget http://download.altera.com/akdlm/software/acdsinst/20.1std/711/ib_installers/QuartusProgrammerSetup-20.1.0.711-linux.run
         # chmod a+x QuartusProgrammerSetup-20.1.0.711-linux.run
         # ./QuartusProgrammerSetup-20.1.0.711-linux.run --unattendedmodeui none --mode unattended --installdir /opt/quartus --accept_eula 1

    - if installing to a different location than */opt/quartus*,
      adjust the value of :data:`path` in a FIXME:ttbd configuration
      file.


    **Troubleshooting**

    When it fails to flash, the error log is reported in the server in
    a file called *flash-COMPONENTS.log* in the target's state
    directory (FIXME: we need a better way for this--the admin shall
    be able to read it, but not the users as it might leak sensitive
    information?).

    Common error messages:

    - *Error (213019): Can't scan JTAG chain. Error code 87*

      Also seen when manually running in the server::

        $ /opt/quartus/qprogrammer/bin/jtagconfig
        1) USB-BlasterII [3-1.4.4.3]
          Unable to read device chain - JTAG chain broken

      In many cases this has been:

      - a powered off main board: power it on

      - a misconnected USB-BlasterII: reconnect properly

      - a broken USB-BlasterII: replace unit

    - *Error (209012): Operation failed*

      this usually happens when flashing one component of a multiple
      component chain; the log might read something like::

        Info (209060): Started Programmer operation at Mon Jul 20 12:05:22 2020
        Info (209017): Device 2 contains JTAG ID code 0x038301DD
        Info (209060): Started Programmer operation at Mon Jul 20 12:05:22 2020
        Info (209016): Configuring device index 2
        Info (209017): Device 2 contains JTAG ID code 0x018303DD
        Info (209007): Configuration succeeded -- 1 device(s) configured
        Info (209011): Successfully performed operation(s)
        Info (209061): Ended Programmer operation at Mon Jul 20 12:05:22 2020
        Error (209012): Operation failed
        Info (209061): Ended Programmer operation at Mon Jul 20 12:05:22 2020
        Error: Quartus Prime Programmer was unsuccessful. 1 error, 0 warnings

      This case has been found to be because the **--bgp** option is
      needed (which seems to map to the *Enable Realtime ISP
      programming* in the Quartus UI, *quartus_pgmw*)

    - *Warning (16328): The real-time ISP option for Max 10 is
      selected. Ensure all Max 10 devices being programmed are in user
      mode when requesting this programming option* 

      Followed by:

        *Error (209012): Operation failed*

      This case comes when a previous flashing process was interrupted
      half way or the target is corrupted.

      It needs a special one-time recovery; currently the
      workaround seems to run the flashing with out the *--bgp* switch
      that as of now is hardcoded.
    
      FIXME: move the --bgp and --mode=JTAG switches to the args (vs
      hardcoded) so a recovery target can be implemented as
      NAME-nobgp

    """


    #: Path to *quartus_pgm*
    #:
    #: We need to use an ABSOLUTE PATH if the tool is not in the
    #: normal search path (which usually won't).
    #:
    #: Change by setting, in a :ref:`server configuration file
    #: <ttbd_configuration>`:
    #:
    #: >>> ttbl.images.quartus_pgm_c.path = "/opt/quartus/qprogrammer/bin/quartus_pgm"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.quartus_pgm_c(...)
    #: >>> imager.path =  "/opt/quartus/qprogrammer/bin/quartus_pgm"
    path = "/opt/quartus/qprogrammer/bin/quartus_pgm"
    path_jtagconfig = "/opt/quartus/qprogrammer/bin/jtagconfig"


    def __init__(self, device_id, image_map, args = None, name = None,
                 jtagconfig = None,
                 **kwargs):
        assert isinstance(device_id, basestring)
        commonl.assert_dict_of_ints(image_map, "image_map")
        commonl.assert_none_or_dict_of_strings(jtagconfig, "jtagconfig")
        assert name == None or isinstance(name, basestring)

        self.device_id = device_id
        self.image_map = image_map
        self.jtagconfig = jtagconfig
        if args:
            commonl.assert_dict_of_strings(args, "args")
            self.args = args
        else:
            self.args = {}

        cmdline = [
            self.path,
            # FIXME: move this to args, enable value-less args (None)
            "--bgp",		# Real time background programming
            "--mode=JTAG",	# this is a JTAG
            "-c", "%(device_path)s",	# will resolve in flash_start()
            # in flash_start() call we'll map the image names to targets
            # to add these
            #
            #'--operation=PVB;%(image.NAME)s@1',
            #'--operation=PVB;%(image.NAME)s@2',
            #...
            # (P)rogram (V)erify, (B)lank-check
            #
            # note like this we can support burning multiple images into the
            # same chain with a single call
        ]
        if args:
            for arg, value in args.items():
                cmdline += [ arg, value ]
        # we do this because in flash_start() we need to add
        # --operation as we find images we are supposed to flash
        self.cmdline_orig = cmdline

        flash_shell_cmd_c.__init__(self, cmdline, cwd = '%(file_path)s',
                                   **kwargs)

        if name == None:
            name = "Intel Quartus PGM %s" % device_id
        self.upid_set(name, device_id = device_id)


    def flash_start(self, target, images, context):
        # Finalize preparing the command line for flashing the images

        # find the device path; quartus_pgm doesn't seem to be able to
        # address by serial and expects a cable name as 'PRODUCT NAME
        # [PATH]', like 'USB BlasterII [1-3.3]'; we can't do this on
        # object creation because the USB path might change when we power
        # it on/off (rare, but could happen).
        usb_path, _vendor, product = ttbl.usb_serial_to_path(self.device_id)
        context['kws'] = {
            # HACK: we assume all images are in the same directory, so
            # we are going to cwd there (see in __init__ how we set
            # cwd to %(file_path)s. Reason is some of our paths might
            # include @, which the tool considers illegal as it uses
            # it to separate arguments--see below --operation
            'file_path': os.path.dirname(images.values()[0]),
            'device_path': "%s [%s]" % (product, usb_path)
            # flash_shell_cmd_c.flash_start() will add others
        }

        # for each image we are burning, map it to a target name in
        # the cable (@NUMBER)
        # make sure we don't modify the originals
        cmdline = copy.deepcopy(self.cmdline_orig)
        for image_type, filename in images.items():
            target_index = self.image_map.get(image_type, None)
            # pass only the realtive filename, as we are going to
            # change working dir into the path (see above in
            # context[kws][file_path]
            cmdline.append("--operation=PVB;%s@%d" % (
                os.path.basename(filename), target_index))
        # now set it for flash_shell_cmd_c.flash_start()
        self.cmdline = cmdline

        if self.jtagconfig:
            for option, value in self.jtagconfig.items():
                cmdline = [
                    self.path_jtagconfig,
                    "--setparam", "%s [%s]" % (product, usb_path),
                    option, value
                ]
                target.log.info("running per-config: %s" % " ".join(cmdline))
                subprocess.check_output(
                    cmdline, shell = False, stderr = subprocess.STDOUT)
        flash_shell_cmd_c.flash_start(self, target, images, context)


class sf100linux_c(flash_shell_cmd_c):
    """Flash Dediprog SF100 and SF600 with *dpcmd* from
    https://github.com/DediProgSW/SF100Linux

    :param str dediprog_id: ID of the dediprog to use (when multiple
      are available); this can be found by running *dpdmd --detect* with
      super user privileges (ensure they are connected)::

        # dpcmd
        DpCmd Linux 1.11.2.01 Engine Version:
        Last Built on May 25 2018

        Device 1 (SF611445):    detecting chip
        By reading the chip ID, the chip applies to [ MX66L51235F ]
        MX66L51235F chip size is 67108864 bytes.

      in here, *Device 1* has ID  *SF611445*. It is recommended to do
      this step only on an isolated machine to avoid confusions with
      other devices connected.

    :param int timeout: (optional) seconds to give the flashing
      process to run; if exceeded, it will raise an exception. This
      usually depends on the size of the binary being flashed and the
      speed of the interface.

    :param str mode: (optional; default "--batch") flashing mode, this
      can be:

      - *--prog*: programs without erasing
      - *--auto*: erase and update only sectors that changed
      - *--batch*: erase and program
      - *--erase*: erase

    :param dict args: dictionary of extra command line options to
      *dpcmd*; these are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>`:

      .. code-block:: python

         args = {
             # extra command line arguments for dpcmd
             'dediprog:id': 435,
         }

    Other parameters described in :class:ttbl.images.impl_c.

    **System setup**

    *dpcmd* is not packaged by most distributions, needs to be
    manuallly built and installed.

    1. build and install *dpcmd*::

         $ git clone https://github.com/DediProgSW/SF100Linux sf100linux.git
         $ make -C sf100linux.git
         $ sudo install -o root -g root \
             sf100linux.git/dpcmd sf100linux.git/ChipInfoDb.dedicfg \
             /usr/local/bin

       Note *dpcmd* needs to always be invoked with the full path
       (*/usr/local/bin/dpmcd*) so it will pick up the location of its
       database; otherwise it will fail to list, detect or operate.

    2. (optionally, if installed in another location) configure the
       path of *dpcmd* by setting :data:`path`.

    **Detecting a Dediprog**

    Dediprogs' USB serial numbers are often all the same, so for a
    power-on sequence to wait until the device is detected by the
    system after it has been plugged in (eg: with a
    :class:`ttbl.pc_ykush.ykush` connector)
    :class:`ttbl.pc.delay_til_usb_device` is usually not enough. In
    such case, we can use *dpmcd* to do the detection for us:

    .. code-block:: python

       connector = ttbl.pc_ykush.ykush(ykush, port, explicit = 'on')
       detector = ttbl.power.delay_til_shell_cmd_c(
           [
               # run over timeout, so if the command gets stuck due
               # to HW, we can notice it and not get stuck -- so if
               # it can't detect in five seconds--slice it
               "/usr/bin/timeout", "--kill-after=1", "5",
               ttbl.images.sf100linux_c.path,
               "--detect", "--device", dediprog_id
           ],
           "dediprog %s is detected" % dediprog_id,
           explicit = 'on')

    and then the power rail must include both:

    .. code-block:: python

       target.interface_add("power", ttbl.power.interface([
           ( "flasher connect", connector ),
           ( "flasher detected", detector ),
           ...
       ])


    A console can be added to watch progress with::

      target.console.impl_add("log-flash-IMAGENAME",
                              ttbl.console.logfile_c("flash-IMAGENAME.log"))

    """
    def __init__(self, dediprog_id, args = None, name = None, timeout = 60,
                 sibling_port = None,
                 path = None,
                 mode = "--batch", **kwargs):
        assert isinstance(dediprog_id, basestring)
        assert isinstance(timeout, int)
        assert path == None or isinstance(path, basestring)
        assert mode in [ "--batch", "--auto", "--prog", "--erase" ]
        commonl.assert_none_or_dict_of_strings(args, "args")

        self.timeout = timeout
        if path:
            self.path = path
        # FIXME: verify path works +x
        # file_name and file_path are set in flash_start()
        self.dediprog_id = dediprog_id
        if sibling_port:
            cmdline = [
                self.path,
                mode, "%(file_name)s",
            ]
            self.sibling_port = sibling_port
        else:
            cmdline = [
                self.path,
                "--device", dediprog_id,
                mode, "%(file_name)s",
            ]
            self.sibling_port = None
        if args:
            for arg, value in args.items():
                cmdline += [ arg, value ]

        # when flashing, CD to where the image is, otherwise cpcmd
        # crashes on very log filename :/ workaround
        flash_shell_cmd_c.__init__(self, cmdline, cwd = '%(file_path)s',
                                   **kwargs)
        if name == None:
            name = "Dediprog SF[16]00 " + dediprog_id
        self.upid_set(name, dediprog_id = dediprog_id)


    def flash_start(self, target, images, context):
        if len(images) != 1:
            # yeah, this shoul dbe done in flash_start() but
            # whatever...I don't feel like overriding it.
            raise RuntimeError(
                "%s: Configuration BUG: %s flasher supports only one image"
                " but it has been called to flash %d images (%s)" % (
                    target.id, type(self),
                    len(images), ", ".join(images.keys())))

        # WORKAROUND for dpcmd crashing when the filename is too long;
        # we chdir into where the image is and run with a basename
        context['kws'] = {
            # note this only works with #1 image
            'file_path': os.path.dirname(images.values()[0]),
            'file_name': os.path.basename(images.values()[0]),
        }
        if self.sibling_port:
            devpath, busnum, devnum = ttbl.usb_device_by_serial(
                self.dediprog_id, self.sibling_port,
                "busnum", "devnum")
            if devpath == None or busnum == None or devnum == None:
                raise RuntimeError(
                    "%s: cannot find Dediprog flasher connected to"
                    " as sibling in port #%d of USB device %s" % (
                        target.id, self.dediprog_id, self.sibling_port))
            # dpcmd can use these two variables to filter who do we
            # use
            self.env_add["DPCMD_USB_BUSNUM"] = busnum
            self.env_add["DPCMD_USB_DEVNUM"] = devnum
        flash_shell_cmd_c.flash_start(self, target, images, context)
        
        
    #: Path to *dpcmd*
    #:
    #: We need to use an ABSOLUTE PATH, as *dpcmd* relies on it to
    #: find its database.
    #:
    #: Change by setting, in a :ref:`server configuration file
    #: <ttbd_configuration>`:
    #:
    #: >>> ttbl.images.sf100linux_c.path = "/usr/local/bin/dpcmd"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.images.sf100linux_c.path(...)
    #: >>> imager.path =  "/opt/bin/dpcmd"
    path = "/usr/local/bin/dpcmd"

    def flash_post_check(self, target, images, context):
        """
        Checks the process returned with no errors

        Looks further in the log file to ensure that is the case
        """
        if len(images) != 1:
            # yeah, this shoul dbe done in flash_start() but
            # whatever...I don't feel like overriding it.
            raise RuntimeError(
                "%s: Configuration BUG: %s flasher supports only one image"
                " but it has been called to flash %d images (%s)" % (
                    target.id, type(self),
                    len(images), ", ".join(images.keys())))
        flash_shell_cmd_c.flash_post_check(self, target, images, context)
