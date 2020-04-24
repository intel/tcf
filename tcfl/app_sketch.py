#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os

from . import app
from . import tc

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

class app_sketch(app.app_c):
    """
    Driver to build Arduino Sketch applications for flashing into
    MCU's BSPs.

    Note the :ref:`setup instructions <tcf_configure_sketch>`.
    """

    @staticmethod
    def configure(testcase, target, app_src):
        target.kws_required_verify([
            'sketch_extension',
            'sketch_fqbn',
        ])
        # Adds Arduino Sketch sketch_* vars to the target's keywords
        # if relative to the testcase_file, get us an abs dir to it
        testcase_file = inspect.getfile(type(testcase))
        src = tcfl.app.get_real_srcdir(testcase_file, app_src[0])
        src = os.path.relpath(src)
        if os.path.isdir(src):
            srcdir = src
            srcfile = None
        else:
            srcdir = os.path.dirname(src)
            srcfile = os.path.basename(src)
        # Place the output in the CWD -- not really like much, but
        # beats the source
        outdir = os.path.join(
            testcase.tmpdir,
            "sketch-%(tc_hash)s-%(tg_hash)s"  % target.kws)
        target.kws_set(dict(
            sketch_outdir = os.path.abspath(outdir),
            sketch_srcfile = srcfile,
            sketch_srcdir = srcdir,
            sketch_src = src
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
            "arduino-cli"
            " compile"
            " --build-path %(sketch_outdir)s"
            " --build-cache-path %(sketch_outdir)s"
            " --fqbn %(sketch_fqbn)s"
            " %(sketch_src)s")

    @staticmethod
    def deploy(images, testcase, target, app_src):
        images['kernel-%(bsp)s' % target.kws] = \
            '%(sketch_outdir)s/%(sketch_srcfile)s.%(sketch_extension)s' % target.kws

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
