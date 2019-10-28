#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os

import tcfl.app
import tcfl.tc

# FIXME: adapt to global installs
# FIXME: create RPMs for this
# FIXME: add depedencies for the sketch package


def _get_real_srcpath(testcase, _srcpath):
    """
    Return the absolute directory where the source for a Zephyr App,
    maybe relative to the path of the testcase where it was described.
    """
    # FIXME: make this an util fn for others to use
    srcpath = os.path.expanduser(_srcpath)
    if os.path.isabs(srcpath):
        srcpath = os.path.normpath(srcpath)
    else:    # relative to the path of where @target definedit
        testcase_file = inspect.getfile(type(testcase))
        srcpath = os.path.normpath(
            os.path.join(os.path.dirname(testcase_file), srcpath))
        srcpath = os.path.abspath(srcpath)
    return srcpath

class app_sketch(tcfl.app.app_c):
    """
    Driver to build Arduino Sketch applications for flashing into
    MCU's BSPs.

    Note the :ref:`setup instructions <tcf_configure_sketch>`.
    """

    @staticmethod
    def configure(testcase, target, app_src):
        target.kws_required_verify([ 'sketch_fqbn' ])
        # Adds Arduino Sketch sketch_* vars to the target's keywords
        srcpath = _get_real_srcpath(testcase, app_src)
        srcdir, srcfile = os.path.split(srcpath)
        # Place the output in the CWD -- not really like much, but
        # beats the source
        outdir = os.path.join(
            testcase.tmpdir,
            "outdir-%(tc_hash)s-%(tg_hash)s-"  % target.kws + srcfile)
        target.kws_set(dict(
            sketch_outdir = os.path.abspath(outdir),
            arduino_bindir = tcfl.config.arduino_bindir,
            arduino_libdir = tcfl.config.arduino_libdir,
            arduino_extra_libdir = tcfl.config.arduino_extra_libdir,
            sketch_srcfile = srcfile,
            sketch_srcdir = srcdir,
            sketch_srcpath = srcpath
        ), bsp = target.bsp)

    @staticmethod
    def build(testcase, target, app_src):
        """
        Build an Sketh App whichever active BSP is active on a target
        """
        # Yes, using Python-shscript so the compile output shows the
        # exact steps we followed to build that can be run by a
        # human--would be easier to run os.mkdir() and stuff, but not
        # as clear to the would-be-debugger human trying to verify what
        # happened

        # Create destination directory

        # FIXME: need a better dir than sketch
        target.shcmd_local(
            'mkdir -p %(sketch_outdir)s' % target.kws)

        # Build
        target.shcmd_local(
            "%(arduino_bindir)s/arduino-builder"
            " -debug-level 10"
            " -build-path %(sketch_outdir)s"
            " -hardware %(arduino_libdir)s/hardware"
            " -tools %(arduino_libdir)s/tools"
            " -tools %(arduino_libdir)s/tools-builder"
            " -fqbn %(sketch_fqbn)s"
            " -built-in-libraries=%(arduino_libdir)s/libraries"
            " -hardware %(arduino_extra_libdir)s/packages/arduino/hardware"
            " -tools %(arduino_extra_libdir)s/packages/arduino/tools"
            " %(sketch_srcpath)s")

    @staticmethod
    def deploy(images, testcase, target, app_src):
        images['kernel-%(bsp)s' % target.kws] = \
            '%(sketch_outdir)s/%(sketch_srcfile)s.bin' % target.kws

    @staticmethod
    def clean(testcase, target, app_src):
        # Note we remove with a shell command, so it shows what we do
        # that an operator could repeat
        # Note also we don't use the %(board)s substitution; at this
        # point, we might not even have it, because it is BSP specific
        # --s o we clean everything related to this testcase, that is
        # represented by %(tg_hash) and includes the stubs at
        # %(sketch_srcdir)s/outdir-%(tg_hash)s-stub-x86-%(type)s.
        target.shcmd_local('rm -rf %(sketch_outdir)s')
