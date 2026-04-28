#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

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
import filelock
import hashlib
import numbers
import os
import re
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
        assert log_name == None or isinstance(log_name, str)

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

    def target_setup(self, target, iface_name, component):
        target.fsdb.set(
            "interfaces.images." + component + ".estimated_duration",
            self.estimated_duration)
        if self.power_sequence_pre:
            target.power.sequence_verify(
                target, self.power_sequence_pre,
                f"flash {component} pre power sequence")
        if self.power_sequence_post:
            target.power.sequence_verify(
                target, self.power_sequence_post,
                f"flash {component} post power sequence")


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

    def flash_read(self, target, image, file_name, image_offset = 0, read_bytes = None):
        """
        Read a flash image

        :param ttbl.test_target target: target where to flash

        :param str image: name of the image to read.

        :param str file_name: name of file where to dump the image;
          the implementation shall overwrite it by any means
          necessary. Parent directories can be assumed to exist.

        :param int offset: (optional, defaults to zero) offset in
          bytes from which to start reading relative to the image's
          beginning.

        :param int size: (optional, default all) number of bytes to
          read from offset.

        If the implementation does not support reading, it can raise a
        NotImplementedError (maybe we need a better exception).
        """
        assert isinstance(target, ttbl.test_target)
        assert isinstance(image, str)
        raise NotImplementedError("reading not implemented")

    def flash_write(self, target, image, data, _user_path):
        """
        Write data to specific offsets in a flash image

        :param ttbl.test_target target: target where to write

        :param str image: name of image to write to

        :param dict data: dictionary of data to write to the image using the
          format { OFFSET:DATA, OFFSET:DATA ... }where both offset and data are
          hexidecimal values

        :param str user_path: path to the users directory which is used to
          store temporary image files reading the image first is required in
          some cases in order to no lose any data

        If the implementation does not support writing to specific addresses,
        it can raise a NotImplementedError.
        """

        assert isinstance(target, ttbl.test_target)
        assert isinstance(image, str)
        assert isinstance(data, dict)
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
        for image_type, name in list(images.items()):
            ho = commonl.hash_file(hashlib.sha512(), name)
            target.fsdb.set(
                "interfaces.images." + image_type + ".last_sha512",
                ho.hexdigest()
            )
            target.fsdb.set(
                "interfaces.images." + image_type + ".last_name",
                name
            )

    def _flash_parallel_do(self, target, parallel, image_names):
        # flash a parallel-capable flasher in a serial fashion; when
        # something fails, repeat it right away if it has retries
        contexts = {}
        estimated_duration = 0
        check_period = 4
        all_images = [ ]
        filenames = set()
        for impl, images in list(parallel.items()):
            context = dict()
            context['ts0'] = time.time()
            context['retry_count'] = 1	# 1 based, nicer for human display
            contexts[impl] = context
            estimated_duration = max(impl.estimated_duration, estimated_duration)
            check_period = min(impl.check_period, check_period)
            all_images += images.keys()
            for image_name, filename in images.items():
                filenames.add(filename)
                # Ensure the files are accessile
                #
                # For files that are in automount directories, and for
                # tools that don't really access them properly, this
                # kinda tries a few times
                last_e = None
                for count in range(1, 4):
                    try:
                        os.stat(filename)
                        break
                    except Exception as e:
                        target.log.error(
                            "%s: can't find %s to flash in %s: retrying %s/4",
                            target.id, image_name, filename, count)
                        last_e = e
                        time.sleep(count * 0.2)	# give automounters some time
                else:
                    target.log.error(
                        "%s: can't find %s to flash in %s (gave up)",
                        target.id, image_name, filename)
                    raise last_e
            target.log.info("%s: flashing %s", target.id, image_names[impl])
            impl.flash_start(target, images, context)

        ts = ts0 = time.time()
        done = set()
        done_impls = set()
        while ts - ts0 < estimated_duration:
            target.timestamp()	# timestamp so we don't idle...

            # sometimes files are in dynamically mounted
            # directories -- avoid they being mounted in very long
            # flash process -- some tools are just not good at
            # telling the system they are active
            for filename in filenames:
                try:
                    os.stat(filename)
                    target.log.info(
                        "flashing: stating file %s", filename)
                except Exception as e:
                    target.log.warning(
                        "flashing: (ignoring) exception stating file %s: %s",
                        filename, e)

            time.sleep(check_period)
            for impl, images in parallel.items():
                if impl in done_impls:	# already completed? skip
                    continue
                context = contexts[impl]
                retry_count = context['retry_count']
                ts = time.time()
                if ts - ts0 > impl.check_period \
                   and impl.flash_check_done(target, images, context) == True:
                    # says it is done, let's verify it
                    r = impl.flash_post_check(target, images, context)
                    if r == None:
	                # success! we are done in this one
                        self._hash_record(target, images)
                        done.update(images.keys())
                        done_impls.add(impl)
                        target.log.warning(
                            "%s/%s: flashing completed; done_impls: %s",
                            target.id, image_names[impl], done_impls)
                    elif retry_count <= impl.retries:
	                # failed, retry?
                        context['retry_count'] += 1
                        target.log.warning(
                            "%s/%s: flashing failed, retrying %d/%d: %s",
                            target.id, image_names[impl],
                            context['retry_count'], impl.retries, r)
                        impl.flash_start(target, images, context)
                    else:
                        # failed, out of retries, error as soon as possible
                        msg = "%s/%s: flashing failed %d times, aborting: %s" % (
                            target.id, image_names[impl], retry_count, r)
                        target.log.error(msg)
                        for _impl, _images in parallel.items():
                            _impl.flash_kill(target, _images, contexts[_impl], msg)
                        raise RuntimeError(msg)
            ts = time.time()
            if len(done_impls) == len(parallel):
                target.log.info("flashed images" + " ".join(image_names.values()))
                return
        else:
            msg = "%s/%s: flashing failed: timedout after %ds" \
                % (target.id, " ".join(all_images), estimated_duration)
            for impl, images in list(parallel.items()):
                impl.flash_kill(target, images, contexts[impl], msg)
            raise RuntimeError(msg)


    def _flash_consoles_disable(self, target, parallel, image_names):
        # in some flashers, the flashing occurs over a
        # serial console we might be using, so we can
        # disable it -- we'll renable on exit--or not.
        # This has to be done after the power-cycle, as it might
        # be enabling consoles
        # FIXME: move this for parallel too?
        for impl in parallel:
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s/%s: disabling console %s to allow flasher to work",
                    target.id, image_names[impl], console_name)
                target.console.put_disable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)

    def _flash_consoles_enable(self, target, parallel, image_names):
        for impl in parallel:
            for console_name in impl.consoles_disable:
                target.log.info(
                    "flasher %s/%s: enabling console %s after flashing",
                    target.id, image_names[impl], console_name)
                target.console.put_enable(
                    target, ttbl.who_daemon(),
                    dict(component = console_name),
                    None, None)


    def _flash_parallel(self, target, parallel, power_sequence_pre, power_sequence_post):
        if power_sequence_pre:
            target.power.sequence(target, power_sequence_pre)

        image_names = { }
        for impl, images in parallel.items():
            image_names[impl] = ",".join([ i + ":" + images[i] for i in images ])

        try:
            target.log.info("flasher %s/%s: starting",
                            target.id, image_names[impl])
            self._flash_consoles_disable(target, parallel, image_names)
            self._flash_parallel_do(target, parallel, image_names)
        finally:
            target.log.info("flasher %s/%s: done",
                            target.id, image_names[impl])
            self._flash_consoles_enable(target, parallel, image_names)

            # note the post sequence is not run in case of flashing error,
            # this is intended, things might be a in a weird state, so a
            # full power cycle might be needed
            if power_sequence_post:
                target.power.sequence(target, power_sequence_post)


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
            for img_type, img_name in images.items():
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
                        raise PermissionError(
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
                with filelock.FileLock(lock_file_name, timeout = 10):
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
            for impl, subimages in serial.items():
                # Serial implementation we just fake like it is
                # parallel, but with a single implementation at the
                # same time
                self._flash_parallel(target, { impl: subimages },
                                     impl.power_sequence_pre,
                                     impl.power_sequence_post)
            # FIXME: collect diagnostics here of what failed only if
            # 'admin' or some other role?
            if parallel:
                self._flash_parallel(target, parallel,
                                     self.power_sequence_pre,
                                     self.power_sequence_post)
            return {}


    def get_flash(self, target, who, args, _files, user_path):
        image = self.arg_get(args, 'image', str)
        image_offset = self.arg_get(args, 'image_offset', int,
                                    allow_missing = True, default = 0)
        read_bytes = self.arg_get(args, 'read_bytes', int,
                                  allow_missing = True, default = None)
        file_name = "FIXME_temp"

        with target.target_owned_and_locked(who):
            impl, img_type_real = self.impl_get_by_name(image, "image type")

            # FIXME: file_name needs making safe
            real_file_name = os.path.join(user_path, file_name)
            # FIXME: make parent dirs of real_file_name
            # FIXME: should we lock so we don't try to write also? or
            # shall that be left to the impl?
            # we write the content to the user's storage area, that
            # gets cleaned up regularly

            if self.power_sequence_pre:
                target.power.sequence(target, self.power_sequence_pre)

            impl.flash_read(target, img_type_real, real_file_name,
                            image_offset, read_bytes)

            if self.power_sequence_post:
                target.power.sequence(target, self.power_sequence_post)

            return dict(stream_file = real_file_name)

    # FIXME: save the names of the last flashed in fsdb so we can
    # query them? relative to USERDIR or abs to system where allowed
    def get_list(self, _target, _who, _args, _files, _user_path):
        return dict(
            aliases = self.aliases,
            result = list(self.aliases.keys()) + list(self.impls.keys()))

    def put_write(self, target, who, args, _files, user_path):
        img_type = self.arg_get(args, 'image', str)
        values = self.arg_get(args, 'values', dict)

        for key, value in values.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
            assert re.match("^(0x)?[a-fA-F0-9]+$", value), \
                f"data \"{value}\" needs to be in hexidecimal"

        with target.target_owned_and_locked(who):
            impl, img_type_real = self.impl_get_by_name(img_type,
                                                        "image type")

            if self.power_sequence_pre:
                target.power.sequence(target, self.power_sequence_pre)

            impl.flash_write(target, img_type_real, values, user_path)

            if self.power_sequence_post:
                target.power.sequence(target, self.power_sequence_post)

            return {}

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
        assert serial_port == None or isinstance(serial_port, str)
        assert sketch_fqbn == None or isinstance(sketch_fqbn, str)
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
                                     for k, v in list(images.items())))
        image_name = list(images.values())[0]

        if self.serial_port == None:
            serial_port = "/dev/tty-%s" % target.id
        else:
            serial_port = self.serial_port

        # remember this only handles one image type
        bsp = list(images.keys())[0].replace("kernel-", "")
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
        assert serial_port == None or isinstance(serial_port, str)
        assert console == None or isinstance(console, str)
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
                                     for k, v in list(images.items())))
        image_name = list(images.values())[0]

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
            or isinstance(usb_serial_number, str)
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
        for image_type, image_name in images.items():
            # FIXME: we shall make sure all images are like this?
            if not image_type.startswith("kernel-"):
                raise RuntimeError(
                    "Unknown image type '%s' (valid: kernel-{%s})"
                    % (image_type, ",".join(list(target.tags['bsps'].keys()))))
            bsp = image_type.replace("kernel-", "")
            tags_bsp = target.tags.get('bsps', {}).get(bsp, None)
            if tags_bsp == None:
                raise RuntimeError(
                    "Unknown BSP %s from image type '%s' (valid: %s)"
                    % (bsp, image_type, " ".join(list(target.tags['bsps'].keys()))))
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


class fake_c(impl2_c):
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
        impl2_c.__init__(self, **kwargs)
        self.upid_set("Fake test flasher", _id = str(id(self)))

    def flash_start(self, target, images, context):
        target.fsdb.set(f"fake-{'.'.join(images.keys())}-{context}.ts0", time.time())

    def flash_check_done(self, target, images, context):
        ts0 = target.fsdb.get(f"fake-{'.'.join(images.keys())}-{context}.ts0", None)
        ts = time.time()
        return ts - ts0 > self.estimated_duration - self.check_period

    def flash_kill(self, target, images, context, msg):
        target.fsdb.set(f"fake-{'.'.join(images.keys())}-{context}.state", "started", None)

    def flash_post_check(self, target, images, context):
        return None

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
        assert serial_port == None or isinstance(serial_port, str)
        assert console == None or isinstance(console, str)
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
                                     for k, v in list(images.items())))
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
        image_name = list(images.values())[0]
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

    :param str|list(str) cmdline_for_each_image: list of strings
      to append to the command line for each image we want to flash:

      >>> cmdline_for_each_image = [ "%(image_name)s:%(image_file)s" ])

      Fields *%(FIELD)s* are replaced from target's keywords, with added

       - *image_name*: the name of the image being flashed (destination)

       - *image_file*: the file name of the image being flashed
    """
    def __init__(self, cmdline, cwd = "/tmp", path = None, env_add = None,
                 cmdline_for_each_image: list = None,
                 **kwargs):
        commonl.assert_list_of_strings(cmdline, "cmdline", "arguments")
        assert cwd == None or isinstance(cwd, str)
        assert path == None or isinstance(path, str)
        self.p = None
        if path == None:
            path = cmdline[0]
        self.path = path
        self.cmdline = cmdline
        self.cwd = cwd
        if isinstance(cmdline_for_each_image, str):
            self.cmdline_for_each_image = [ cmdline_for_each_image ]
        elif cmdline_for_each_image:
            commonl.assert_list_of_strings(
                cmdline_for_each_image, "cmdline_for_each_image", "cmdline")
            self.cmdline_for_each_image = cmdline_for_each_image
        else:
            self.cmdline_for_each_image = []
        if env_add:
            commonl.assert_dict_of_strings(env_add, "env_add")
            self.env_add = env_add
        else:
            self.env_add = {}
        impl2_c.__init__(self, **kwargs)



    def flash_start(self, target, images, context):

        kws = target.kws_collect()
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
                try:
                    cmdline.append(commonl.kws_expand(str(i), kws))
                except Exception as e:
                    target.log.error(
                        "Can't expand commandline component #%d: %s", count, e)
                    raise
                count += 1
            count = 0
            for cmdline_image in self.cmdline_for_each_image:
                for image_name, image_file in images.items():
                    kws_image = dict(kws)
                    kws_image['image_name'] = image_name
                    kws_image['image_file'] = image_file
                    try:
                        cmdline.append(commonl.kws_expand(cmdline_image, kws_image))
                    except Exception as e:
                        target.log.error(
                            "Can't expand commandline for each image"
                            " component #%d: %s", count, e)
                        raise
            count += 1
        except KeyError as e:
            message = "configuration error? can't template command line #%d," \
                " missing field or target property: %s" % (count, e)
            target.log.error(message)
            raise RuntimeError(message)
        cmdline_s = " ".join(cmdline)
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
            target.log.info("flashing %s image with: %s",
                            image_types, " ".join(cmdline))
            with open(logfile_name, "w+") as logf:
                self.p = subprocess.Popen(
                    cmdline, env = env, stdin = None, cwd = cwd,
                    bufsize = 0,	# output right away, to monitor
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
            with open(context['logfile_name'], 'rb') as logf:
                try:
                    # SEEK to -MAX_BYTES or if EINVAL (too big), leave it
                    # at beginning of file
                    logf.seek(-max_bytes, 2)
                except IOError as e:
                    if e.errno != errno.EINVAL:
                        raise
                return logf.read().decode('utf-8')
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
            return { "message": msg }
        return
        # example, look at errors in the logfile
        try:
            with codecs.open(context['logfile_name'], errors = 'ignore') as logf:
                for line in logf:
                    if 'Fail' in line:
                        msg = "flashing with %s failed, issues in logfile" % (
                            context['cmdline_s'])
                        target.log.error(msg)
                        return { "message": msg }
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise



class flash_shell_cmd_rpyc_c(impl2_c):
    """General flashing template that can use a command line tool to
    flash (possibly in parallel)

    Note this is meant to run command line tools to do the flashing
    operation; it is able to operate in a remote machine (using RPYC),
    in which case it will upload the file to the remote machine first.

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

    :param int max_log_size: (optional; default 65k) maximum size of
      the log file in bytes; older entries are removed.

    :param tuple rpyc_spec: (optional; default *None*) if specified,
      tuple of string with a hostname and an integer TCP port where an
      RPYC server is listening.

      If specified, the flashing command will be run in the remote
      host. The files to flash will be uploaded to a temporary
      directory with a name based on the target, the destination and
      the sha 256 hash of the file (to avoid conflicts).

      An RPYC server is usually created as a separate power component
      that uses :class:`ttbl.console.ssh_pc` to run an SSH command
      that starts RPYC in the remote host and creates an encrypted
      tunnel for the RPYC connection. eg:

      >>> power_rail['redir_rpyc'] = ttbl.console.ssh_pc(
      >>>     "USER:PASSWORD@HOSTNAME",
      >>>     crlf = "\r",
      >>>     shell_cmd = "py /Python311/Scripts/rpyc_classic.py --host 127.0.0.1 -p 5998",
      >>>     extra_opts = {
      >>>         "LocalForward#127.0.0.1:23000": "127.0.0.1:5998"
      >>>     },
      >>>     extra_tcp_ports = { 23000 }
      >>> )

      then when powered on, the server's 127.0.0.1:23000 will be
      redirected to HOSTNAME"s 127.0.0.1:5998, where RPYC is
      listening over the SSH encrypted connection.

    :param dict env_add: (optional) variables to add to the environment when
      running the command


    :param str log_name: (optional) name to use for the log file;
      defaults to a name generated from the image types being flashed
      (flash-IMAGE1-IMAGE2....log); note this means that different
      files will be generated if you flash different things.

    :param callable cmdline_prepare: (optional) function to call to
      finish preparing the command line before running it

      >>> def function(cmdline: list, target: test.ttbl_target, env:
      >>>              dict, context: dict, kws: dict):
      >>>     cmdline.append("-w", "somevalue")

      - *cmdline*: a list of strings with the component of the
        command line that will be called. Any modifications to it will
        be seen and used by the caller.

      - *target*: the target we are working on.

      - *env*: a dictionary of the environment that will be passed to
        the subprocess; has been prefilled with the current one and
        anything in *env_add* has been added already. Anything added
        will be seen and used by the caller.

      - *context*: is a dictionary with execution context info (see
        :meth:`ttbl.images.impl2_c`).

    """
    def __init__(self, cmdline, cwd = "/tmp", path = None, env_add = None,
                 cmdline_for_each_image: list = None,
                 max_log_size: int = 65 * 1025 * 1024,
                 rpyc_spec: tuple = None,	# host port
                 cmdline_prepare: callable = None,
                 **kwargs):
        commonl.assert_list_of_strings(cmdline, "cmdline", "arguments")
        assert cwd == None or isinstance(cwd, str)
        assert path == None or isinstance(path, str)
        self.p = None
        if path == None:
            path = cmdline[0]
        self.path = path
        self.cmdline = cmdline
        self.cwd = cwd
        if isinstance(cmdline_for_each_image, str):
            self.cmdline_for_each_image = [ cmdline_for_each_image ]
        elif cmdline_for_each_image:
            commonl.assert_list_of_strings(
                cmdline_for_each_image, "cmdline_for_each_image", "cmdline")
            self.cmdline_for_each_image = cmdline_for_each_image
        else:
            self.cmdline_for_each_image = []
        if env_add:
            commonl.assert_dict_of_strings(env_add, "env_add")
            self.env_add = env_add
        else:
            self.env_add = {}
        if rpyc_spec:
            assert isinstance(rpyc_spec, tuple) \
                and len(rpyc_spec) == 2, \
                f"rpyc_spec: got {type(rpyc_spec)}; expected tuple (host:str, port:int)"
            self.rpyc_host = rpyc_spec[0]
            self.rpyc_port = rpyc_spec[1]
            assert isinstance(self.rpyc_host, str), \
                f"rpyc_spec[0]: expected str (hostname), got {type(self.rpyc_host)}"
            assert isinstance(self.rpyc_port, int) and self.rpyc_port > 0, \
                f"rpyc_spec[1]: expected int (0 < TCP port < 65536)," \
                f" got [{type(self.rpyc_port)}] {self.rpyc_port}"
        else:
            self.rpyc_host = None
            self.rpyc_port = None
        if cmdline_prepare != None:
            assert callable(cmdline_prepare), \
                f"cmdline_prepare: expected a callable, got [{type(cmdline_prepare)}] {cmdline_prepare}"
        self.cmdline_prepare = cmdline_prepare
        assert isinstance(max_log_size, int) and max_log_size > 0, \
            f"max_log_size: expected a positive integer, got [{type(max_log_size)}] {max_log_size}"
        self.max_log_size = max_log_size
        impl2_c.__init__(self, **kwargs)


    @staticmethod
    def _logf_close(target, context):
        for key, description in [
                ('logf_local', 'local log file'),
                ('logf', 'remote log file'),
                ('logf_read', 'remote log file for reading'),
        ]:
            logf = context.get(key, None)
            if logf == None:
                continue
            target.log.error(f"DEBUG closing {description} {logf.name}")
            try:
                logf.close()
            except Exception as e:
                target.log.error(f"DEBUG closing {description} {logf.name} failed (ignoring): {e}")
            del context[key]



    @staticmethod
    def _remote_read_maybe(target, context):
        logf_local = context.get('logf_local', None)
        if logf_local == None:
            return
        logf_read = context['logf_read']
        ts0 = context['ts0']
        p = context['p']
        while data := logf_read.read():
            ts = time.time()
            logf_local.write(data)
            logf_local.flush()
            for line in data.splitlines():
                target.log.info("%s: [+%.1fs] flasher PID %s %s output: %s",
                                context['kws']['image_types'], ts - ts0,
                                context['remote_s'], p.pid,
                                line)



    def flash_start(self, target, images, context):

        kws = target.kws_collect()
        context['images'] = images

        # it might survive from the previous call, but we want to
        # recreate it
        remote = context.get('rpyc_remote', None)
        if remote != None:
            del context['rpyc_remote']
            del remote

        # make sure they are sorted so they are always listed the same
        image_types = "-".join(sorted(images.keys()))
        kws['image_types'] = image_types
        if self.log_name:
            kws['log_name'] = self.log_name
        else:
            # the name is the name of the images we are flashing--this
            # can get messy, so to control it, set log_name
            kws['log_name'] = "flash-" + image_types + ".log"
        # this allows a class inheriting this to set kws before calling us
        context.setdefault('kws', {}).update(kws)
        kws = context['kws']

        # ok, create the RPYC connection *and* the modules we all have
        # to use now in flash_* calls
        if self.rpyc_host:
            import rpyc
            remote_s = context['remote_s'] = \
                f"RPYC:{self.rpyc_host}:{self.rpyc_port}"
            target.log.info(
                "flashing: connecting to RPYC server at %s:%d",
                self.rpyc_host, self.rpyc_port)
            remote = rpyc.classic.connect(self.rpyc_host, self.rpyc_port)
            ros = remote.modules['os']
            rsubprocess = remote.modules['subprocess']
            rtempfile = remote.modules['tempfile']
            cwd = context['cwd'] = kws['cwd'] = "c:/temp"

        else:
            remote = None
            remote_s = ""
            ros = os
            rsubprocess = context['rsubprocess'] = subprocess
            rtempfile = tempfile
            cwd = context['cwd'] = kws['cwd'] = self.cwd % kws

        images_remote = dict(images)

        # Using tempfile.gettempdir() gets the system's tempfile
        # location for what it is (windows's user dir, unix /tmp
        # etc) so it gets auto cleaned up.
        #
        # And replace backlash with forward because it gets all
        # messed up, and Python can then fix it if remote is
        # Windows anyway
        rtmpdir = rtempfile.gettempdir().replace("\\", "/")

        # handle the files we are are going to flash; if we are doing
        # remote, upload them to the remote machine.
        if remote:
            # we have to upload the files to the remote host; we are
            # going to upload them to a file named after their
            # destination and the hash of the content; we are going to
            # check if it is already there and skip the upload and
            # reuse it if the hash matches
            #
            # also, set kws['image*']
            count = 0
            for image_name, image_file in list(images.items()):

                # we keep image name at the end because quartus likes
                # its extensions at the end (eg .jic, .pof)
                _, ext = os.path.splitext(image_file)

                if os.path.islink(image_file):
                    # we might transform some file paths here due to rpyc not
                    # being able to upload symlinks
                    image_tmpfile = tempfile.NamedTemporaryFile(
                        prefix = f"ttbl-flash-{target.id}-{image_name}.",
                        suffix = "." + ext,
                        delete = True)
                    shutil.copy(image_file, image_tmpfile.name,
                                follow_symlinks = True)
                    _image_file = image_tmpfile.name
                else:
                    _image_file = image_file
                    image_tmpfile = None

                # get the local hash
                h = hashlib.sha256()
                commonl.hash_file(h, _image_file)
                local_hash = h.hexdigest()[:20]

                # will there be clashes? well, not really since each file
                # is named per target id, destination and content and only
                # ONE is supposed to run at the time
                #
                if ext:
                    image_file_remote = f"{rtmpdir}/{target.id}-{local_hash}-{image_name}.{ext}"
                else:
                    image_file_remote = f"{rtmpdir}/{target.id}-{local_hash}-{image_name}"

                # get the hash for the remote file, if it exists
                remote_hash = None
                try:
                    # why run like this? because this way the remote
                    # execution goes all remote and the file data
                    # isn't sent back and forth. Maybe there is a
                    # better way. Can't use teleport() bc difference
                    # in python versions (local vs remote) would whack it.
                    remote.execute(f"""
import hashlib
hash_object = hashlib.sha256()
with open('{image_file_remote}', 'rb') as f:
   for chunk in iter(lambda: f.read(8192), b''):
      hash_object.update(chunk)
""")
                    remote_hash = remote.namespace['hash_object'].hexdigest()[:20]
                except Exception as e:
                    target.log.warning(
                        "flashing: can't get info on already uploaded %s in rpyc://%s:%d/%s: %s",
                        _image_file, self.rpyc_host, self.rpyc_port,
                        image_file_remote, e)
                    # remote_hash stays at None, we assume difference
                    # and re-upload

                if local_hash == remote_hash:
                    target.log.warning(
                        "flashing: using already uploaded %s in"
                        " rpyc://%s:%d/%s (signatures match)",
                        _image_file,
                        self.rpyc_host, self.rpyc_port, image_file_remote)
                else:
                    target.log.info(
                        "flashing: uploading %s to rpyc://%s:%d/%s",
                        _image_file,
                        self.rpyc_host, self.rpyc_port, image_file_remote)
                    # https://rpyc.readthedocs.io/en/latest/api/utils_classic.html#rpyc.utils.classic.upload
                    rpyc.utils.classic.upload(
                        remote, _image_file, image_file_remote)
                    target.log.warning(
                        "flashing: uploaded %s to rpyc://%s:%d/%s",
                        _image_file,
                        self.rpyc_host, self.rpyc_port, image_file_remote)

                images_remote[image_name] = image_file_remote
                kws['image.' + image_name] = image_file_remote
                kws['image.#%d' % count ] = image_file_remote
                count += 1

                if image_tmpfile != None:
                    del image_tmpfile

        else:
	    # local flashing, no need to upload, just set kws['image*']
            count = 0
            for image_name, image in images.items():
                images_remote[image_name] = image
                kws['image.' + image_name] = image
                kws['image.#%d' % count ] = image
                count += 1

        # we have generated the environment, maybe remote; let's add
        # whatever the config wants
        env = dict(ros.environ)
        if self.env_add:
            env.update(self.env_add)

        if remote:
            target.log.error(f"FIXME: kill existing leftover processes?")


        # Prepare the log files
        #
        # need it so we have kws set before expanding cmdline
        #
        # Note this code ca run local commands or remote commands via
        # RPYC; because of that, the output logging thing is quite a
        # mess.
        #
        # - We can subprocess.open to a (local) file descriptor,
        #   because we couldn't get it to work maybe future versions
        #   will
        #
        # - We open a file in the machine that runs it (local or
        #   remote) and we pass the descriptor to it so if it is
        #   remote we are guaranteed the resource used is the one in
        #   the host, not a proxyed one.
        #
        # - If the running is local, then the log file is already the
        #   log file we watch, no more to do.
        #
        # - If the log file is remote, flash_check_done() will take
        #   care of copying the bits as they go to the local log file,
        #   so we can watch progress
        #
        # - We keep appending to the log file, so we can see prev
        #   executions on retries; we cap its size
        logfile_name = "%(path)s/%(log_name)s" % kws
        try:
            commonl.file_truncate_from_end(logfile_name, self.max_log_size)
        except FileNotFoundError:
            pass
        if remote:
            # remotely we create a log file that we'll read locally
            # when we call flash_check_done()
            rlogfile_name = context['rlogfile_name'] = f"{rtmpdir}/{target.id}-flash.log"
            # open w so the size is capped to a single execution's
            logf = context['logf'] = remote.builtins.open(rlogfile_name, "w")
            context['logf_read'] = remote.builtins.open(rlogfile_name, "r")
            # we always append to this logfile and we have truncated
            # it above to a max size
            context['logf_local'] = open(logfile_name, "a")
        else:
            logf = context['logf'] = open(logfile_name, "a")

        #
        # Prepare the command line
        #
        # 1. expand the cmdline we are given
        # 2. add per-image cmdline components
        # 3. add optional preparation steps from a function given to
        #    the constructor
        #
        # Format each component of the commandline, since they might
        # have %(KEYWORD)s which are to be expanded from kws
        cmdline = []
        count = 0
        try:
            for i in self.cmdline:
                # some older Linux distros complain if this string is unicode
                try:
                    cmdline.append(commonl.kws_expand(str(i), kws))
                except Exception as e:
                    target.log.error(
                        "Can't expand commandline component #%d: %s", count, e)
                    raise
                count += 1
            count = 0
            for cmdline_image in self.cmdline_for_each_image:
                for image_name, image_file in images_remote.items():
                    kws_image = dict(kws)
                    kws_image['image_name'] = image_name
                    kws_image['image_file'] = image_file
                    try:
                        cmdline.append(commonl.kws_expand(cmdline_image, kws_image))
                    except Exception as e:
                        target.log.error(
                            "Can't expand commandline for each image"
                            " component #%d: %s", count, e)
                        raise
            count += 1
        except KeyError as e:
            message = "configuration error? can't template command line #%d," \
                " missing field or target property: %s" % (count, e)
            target.log.error(message)
            raise RuntimeError(message)

        if self.cmdline_prepare:
            self.cmdline_prepare(cmdline, target, env, context, kws)

        cmdline_s = " ".join(cmdline)
        context['cmdline'] = cmdline
        context['cmdline_s'] = cmdline_s

        context['ts0'] = ts0 = time.time()

        logf.write(f"""

# New flash started at {time.ctime(ts0)}
#
# cmdline: {remote_s} {' '.join(cmdline)}
#

""")
        logf.flush()


        #
        # Ok, let's run the flashing command, after all this prep
        #
        try:
            target.log.info("flashing %s image with: %s %s",
                            image_types, remote_s, " ".join(cmdline))
            p = context['p'] = rsubprocess.Popen(
                cmdline, env = env, stdin = None, cwd = cwd,
                text = True,
                bufsize = 0,	# output right away, to monitor
                # we cannot redirect stdout to a local file if we
                # re doing RPYC, so we are going to hack it -- we tell
                # it to log to a descriptor, so it works in local and
                # remote mode. Then in remote mode we'll be reading
                # that file in flash_check_done() and moving it to the
                # local file. In local file, we'll just see the local
                # file and they'll both display in the logging console.
                stderr = rsubprocess.STDOUT, stdout = logf.fileno())
        except subprocess.CalledProcessError as e:
            target.log.error("flashing with %s failed: (%d) %s"
                             % (cmdline_s, e.returncode, e.output))
            self._remote_read_maybe(target, context)
            self._logf_close(target, context)
            raise

        p.poll()
        if p.returncode != None:
            msg = "flashing with %s %s failed to start: (%s->%s) %s" % (
                remote_s, cmdline_s, p.pid, p.returncode,
                logfile_name)
            target.log.error(msg)
            raise RuntimeError(msg)
        if not remote:
            # this is needed so SIGCHLD the process and it doesn't become
            # a zombie
            ttbl.daemon_pid_add(p.pid)
        target.log.debug("%s: flasher PID %s started (%s)",
                         image_types, p.pid, cmdline_s)
        return



    def flash_check_done(self, target, _images: dict, context: dict):
        self._remote_read_maybe(target, context)
        p = context.get('p', None)
        if p == None:
            return True
        p.poll()
        if p.returncode == None:
            return False
        else:
            return True
        return p.returncode



    def flash_kill(self, target, _images: dict, context: dict,
                   msg: str, tag: str = "kill"):
        ts = time.time()
        ts0 = context['ts0']
        p = context.get('p', None)
        if not p:
            target.log.debug(
                "%s: [+%.1fs] flasher::%s: WARNING! no flasher to %s?",
                context['kws']['image_types'], tag)
            return None
        p.poll()
        returncode = p.returncode	# we'll return it
        self._remote_read_maybe(target, context)

        # ok, stop nicely then kill and retry killing if anything
        # seems to have failed, just to be safe
        target.log.info(
            "%s: [+%.1fs] flasher::%s: finishing PID %s %s",
            context['kws']['image_types'], ts - ts0, msg,
            context.get('remote_s', ''), p.pid)
        try:
            p.terminate()
            time.sleep(0.02)
            for count in range(10):
                time.sleep(0.02)
                if p.poll() == None:
                    p.kill()
                else:
                    break
        except:
            try:
                p.kill()
            except:
                pass
        finally:
            # now whatever we do, read the rest of the logs that we
            # might have around
            self._logf_close(target, context)

            # get rid of all the process descriptors
            del context['p']
            del p

            # if this was a remote sessions, close it to avoid leaving
            # resources hanging
            remote = context.get('rpyc_remote', None)
            if remote != None:
                try:
                    # order matters; ensure we remove it from the dict
                    # so it goes out scope and it's garbage collected
                    # even if the remote.close() fails
                    del context['rpyc_remote']
                    remote.close()
                    del remote
                except:
                    pass

        return returncode



    def flash_post_check(self, target, images, context,
                         expected_returncode = 0):
        """
        Check for execution result.

        :param int expected_returncode: (optional, default 0)
          returncode the command has to return on success. If *None*,
          don't check it.
        """
        returncode = self.flash_kill(target, None, context, "no message",
                                     tag = "terminate")

        if expected_returncode != None and returncode != expected_returncode:
            msg = f"flashing with {context['cmdline_s']} failed, returned {returncode}"
            target.log.error(msg)
            return { "message": msg }
        return



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
        assert isinstance(device_id, str)
        commonl.assert_dict_of_ints(image_map, "image_map")
        commonl.assert_none_or_dict_of_strings(jtagconfig, "jtagconfig")
        assert name == None or isinstance(name, str)

        self.device_id = device_id
        self.image_map = image_map
        self.jtagconfig = jtagconfig
        if args:
            commonl.assert_dict_of_strings(args, "args")
            self.args = args
        else:
            self.args = {}

        cmdline = [
            "stdbuf", "-o0", "-e0", "-i0",
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
                if value != None:
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
        port = target.fsdb.get("jtagd.tcp_port")
        context['kws'] = {
            # HACK: we assume all images are in the same directory, so
            # we are going to cwd there (see in __init__ how we set
            # cwd to %(file_path)s. Reason is some of our paths might
            # include @, which the tool considers illegal as it uses
            # it to separate arguments--see below --operation
            'file_path': os.path.dirname(list(images.values())[0]),
            'device_path': "%s on localhost:%s [%s]" % (product, port, usb_path)
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

      target.interface_impl_add("console", "log-flash-IMAGENAME",
                                ttbl.console.logfile_c("flash-IMAGENAME.log"))

    """
    def __init__(self, dediprog_id, args = None, name = None, timeout = 60,
                 sibling_port = None,
                 path = None,
                 mode = "--batch", **kwargs):
        assert isinstance(dediprog_id, str)
        assert isinstance(timeout, int)
        assert path == None or isinstance(path, str)
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
            'file_path': os.path.dirname(list(images.values())[0]),
            'file_name': os.path.basename(list(images.values())[0]),
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
        return flash_shell_cmd_c.flash_post_check(self, target, images, context)


    def flash_read(self, _target, _image, file_name, image_offset = 0, read_bytes = None):
        """
        Reads data from the SPI and writes them to 'file_name'
        """

        cmdline = [ self.path,  "--device", self.dediprog_id,
                    "-r", file_name, "-a", str(image_offset) ]

        if read_bytes != None:
            cmdline += [ "-l", str(read_bytes) ]

        subprocess.check_output(cmdline, shell = False)
