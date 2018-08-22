#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""Application builder are a generic tool for building applications of
different types.

They all use the same interface to make it easy and fast for the test
case writer to specify what has to be built for which BSP of which
target with a very simple specification given to the
:func:`tcfl.tc.target` decorator:

>>> tcfl.tc.target(app_zephyr = { 'x86': "path/to/zephyr_app" },
>>>                app_sketch = { 'arc': "path/to/sketch" })
>>> class mytestcase(tcfl.tc.tc_c):
>>> ...

which allows the testcase developer to point the app builders to the
locations of the source code and on which BSPs of the targets it shall
run and have it deal with the details of inserting the right code to
build, deploy, setup and start the testcase.

This allows the testcase writer to focus on writing the test
application.


App builders:

- can be made once and reused multiple times
- they are plugins to the testcase system
- keep no state; they need to be able to gather everything
  from the parameters passed (this is needed so they can be called from
  multiple threads).
- are always called *app_SOMETHING*

Note implementation details on :py:class:`tcfl.app.app_c`; drivers can
be added with :py:func:`tcfl.app.driver_add`.

Currently available application buildrs for:

 - :class:`Zephyr OS apps <tcfl.app_zephyr.app_zephyr>`
 - :class:`Arduino Sketches <tcfl.app_sketch.app_sketch>`

"""

import math
import os

# We multithread to run testcases in parallel
#
# When massively running threads in production environments, we end up
# with hundreds/thousands of threads based on the setup which are just
# launching a build and waiting. However, sometimes something dies
# inside Python and leaves the thing hanging with the GIL taken and
# everythin deadlocks.
#
# For those situations, using the PathOS/pools library works better,
# as it can multithread as processes (because of better pickling
# abilities) and doesn't die.
#
# So there, the PATHOS.multiprocess library if available and in said
# case, use process pools for the testcases.

_multiprocessing = None

def import_mp_pathos():
    import pathos.multiprocessing
    global _multiprocessing
    _multiprocessing = pathos.multiprocessing

def import_mp_std():
    import multiprocessing
    global _multiprocessing
    _multiprocessing = multiprocessing

mp = os.environ.get('TCF_USE_MP', None)
if mp == None:
    try:
        import_mp_pathos()
    except ImportError as e:
        import_mp_std()
elif mp.lower() == 'std':
    import_mp_std()
elif mp.lower() == 'pathos':
    import_mp_pathos()
else:
    raise RuntimeError('Invalid value to TCF_USE_MP (%s)' % mp)

import commonl
import tcfl.tc

def _app_src_validate(app_name, app_src):
    assert isinstance(app_name, basestring), \
        "app_name is '%s', expected str" % type(app_name).__name__
    # validate and transform an specification of an app_src, that can be:
    #
    # - path: a path to a source
    # - (path, str2, ...): a tuple of strings
    #   - path: path to a source
    #   - str2...: more strings, optional, app builder specific interpretation
    if isinstance(app_src, basestring):
        return (app_src, )
    elif isinstance(app_src, tuple) \
         and all([ isinstance(k, basestring) for k in app_src ]):
        return app_src
    elif isinstance(app_src, dict):
        for k, v in app_src.iteritems():
            if not isinstance(k, basestring):
                raise tcfl.tc.blocked_e(
                    "%s: key in dictionary has to be a string, found %s"
                    % (app_name, type(k).__name__))
            app_src[k] = _app_src_validate(app_name, v)
        return app_src
    raise tcfl.tc.blocked_e(
        "value to '%s' has to be a path to the app to build, "
        "a tuple of strings (PATH, OPT1, OPT2...) "
        "or  a dictionary { BSP: PATH } or { BSP: (PATH, OPT1, OPT2...) }; "
        "instead, found '%s'"
        % (app_name, type(app_src).__name__))

def _args_check(ab, testcase, target, app_src = None):
    assert isinstance(testcase, tcfl.tc.tc_c)
    assert isinstance(target, tcfl.tc.target_c)
    assert target.bsp != None, "BUG: %s: target's BSP must be set" \
                         % target.fulid
    for app_name, app_driver in _drivers.iteritems():
        if app_driver[0] == ab:
            app_src = _app_src_validate(app_name, app_src)
            break
    else:
        raise tcfl.tc.blocked_e(
            "BUG? App driver %s not registered?" % ab.__name__)
    return app_src

def args_app_src_check(app_name, app_src):
    """
    Verify the source specification for a given App Driver
    """
    if app_src == None:
        return app_src
    return _app_src_validate(app_name, app_src)

_drivers = dict()

def driver_add(cls, name = None):
    """
    Add a new driver for app building

    Note the driver will be called as the class name; it is
    recommended to call then *app_something*.
    """
    assert issubclass(cls, app_c)
    if name == None:
        name = cls.__name__
    else:
        assert isinstance(name, basestring)
    if name in _drivers:
        raise ValueError('%s: already registered by @%s'
                         % (name, _drivers[name][1]))
    _drivers[name] = (cls, commonl.origin_get(2))

def _driver_get(name):
    if not name in _drivers:
        raise RuntimeError("BUG? app %s: not registered!" % name)
    return _drivers[name][0]

def driver_valid(name):
    return name in _drivers


def get_real_srcdir(origin_filename, _srcdir):
    """
    Return the absolute version of _srcdir, which might be relative
    which the file described by origin_file.
    """
    # FIXME: make this an util fn for others to use
    srcdir = os.path.expanduser(_srcdir)
    if os.path.isabs(srcdir):
        srcdir = os.path.normpath(srcdir)
    else:    # relative to the path origin_filename
        srcdir = os.path.normpath(
            os.path.join(os.path.dirname(origin_filename), srcdir))
    if not os.path.isdir(srcdir):
        # FIXME: print origin of srcdir at the @target definition, the
        # origin_filename now points to the driver code
        raise ValueError("%s: is not a directory; cannot find App" % _srcdir)
    return srcdir

def configure(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.configure(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return

def build(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.build(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return

def deploy(images, ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    assert isinstance(images, set)
    try:
        r = ab.deploy(images, testcase, target, app_src)
        if r == None:
            return tcfl.tc.result_c(1, 0, 0, 0, 0)
        else:
            assert isinstance(r, tcfl.tc.result_c)
    except NotImplementedError:
        # These come from the base class
        return tcfl.tc.result_c(0, 0, 0, 0, 0)

def setup(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.setup(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return

def start(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.start(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return

def teardown(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.teardown(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return


def clean(ab, testcase, target, app_src):
    app_src = _args_check(ab, testcase, target, app_src)
    try:
        ab.clean(testcase, target, app_src)
    except NotImplementedError:
        # These come from the base class
        return

class app_c(object):
    """Subclass this to create an App builder, provide implementations
    only of what is needed.

    The driver will be invoked by the test runner using the methods
    :py:func:`tcfl.app.configure`, :py:func:`tcfl.app.build`,
    :py:func:`tcfl.app.deploy`, :py:func:`tcfl.app.setup`,
    :py:func:`tcfl.app.start`, :py:func:`tcfl.app.teardown`,
    :py:func:`tcfl.app.clean`.

    If your App builder does not need to implement any, then it is
    enough with not specifying it in the class.

    **Targets with multiple BSPs**

    When the target contains multiple BSPs the App builders are
    invoked for each BSP in the same order as they were declared with
    the decorator :py:func:`tcfl.tc.target`. E.g.:

    >>> @tcfl.tc.target(app_zephyr = { 'arc': 'path/to/zephyr_code' },
    >>>                 app_sketch = { 'x86': 'path/to/arduino_code' })

    We are specifying that the *x86* BSP in the target has to run code
    to be built with the Arduino IDE/compiler and the *arc* core will
    run a Zephyr app, built with the Zephyr SDK.

    If the target is being ran in a BSP model where one or more of the
    BSPs are not used, the App builders are responsible for providing
    stub information with :meth:`tcfl.tc.target_c.stub_app_add`. As
    well, if an app builder determines a BSP does not need to be
    stubbed, it can also remove it from the target's list with:

    >>> del target.bsps_stub[BSPNAME]

    Note this removal is done at the specific target level, as each
    target might have different models or needs.


    Note you can use the dictionary :py:meth:`tcfl.tc.tc_c.buffers` to
    store data to communicate amongst phases. This dictionary:

    - will be cleaned in between evaluation runs

    - is not multi-threaded protected; take
      :py:meth:`tcfl.tc.tc_c.buffers_lock` if you need to access it
      from different paralell execution methods
      (setup/start/eval/test/teardown methods are *always* executed
      serially).

    - take care not to *start* more than once; app builders are setup
      to start a target only if there is not a field
      *started-TARGETNAME* set to *True*.

    """
    @staticmethod
    def configure(testcase, target, app_src):
        raise NotImplementedError

    @staticmethod
    def build(testcase, target, app_src):
        raise NotImplementedError

    @staticmethod
    def deploy(images, testcase, target, app_src):
        raise NotImplementedError

    @staticmethod
    def setup(testcase, target, app_src):
        raise NotImplementedError

    @staticmethod
    def start(testcase, target, app_src):
        # This ensures we only start once, in case other BSPs call
        # their start methods too and they don't have anything BSP
        # specific to do on start
        if testcase.buffers.get('started-%s' % target.want_name, False):
            return

        target.report_info("starting", dlevel = 1)
        if target.type.startswith('emsk'):
            # EMSK gets image loaded into RAM, if we reset, we lose
            # it, so we tell it where to start, as we have stopped it
            # to load the image after a power cycle
            if not '__start' in target.kws:
                raise tcfl.tc.blocked_e(
                    "Testcase needs to set with target.kw_set() a "
                    "keyword named '__start' with a (string) value "
                    "that describes the program counter where to start "
                    "(eg: target.kw_set('__start', '0x1000011f')")
            target.debug.openocd("reg pc %s" % target.kws['__start'])
            target.debug.resume()
        else:
            target.power.reset()	# Will power on if off

        # We want to start each target only once
        testcase.buffers['started-%s' % target.want_name] = True

    @staticmethod
    def teardown(testcase, target, app_src):
        raise NotImplementedError

    @staticmethod
    def clean(testcase, target, app_src):
        raise NotImplementedError

def make_j_guess():
    """
    How much paralellism?

    In theoryt there is a make job server that can help throtle this,
    but in practice this also influences how much virtual the build of a
    bunch of TCs can do so...

    So depending on how many jobs are already queued, decide how much
    -j we want to give to make.
    """
    if tcfl.tc.tc_c.jobs > 8:
        # Let's stick to serializing it it (no -j"
        return ""
    elif tcfl.tc.tc_c.jobs > 1:
        return '-j%d' % int(math.ceil(_multiprocessing.cpu_count()/2))
    else:
        # If it's just us, go wild
        return '-j%d' % (2 * _multiprocessing.cpu_count())
