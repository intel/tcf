#! /usr/bin/python3
# pylint: disable = missing-docstring
import __main__
"""

If a file is part of a Zephyr app or kernel, figure out what testcases
shall be run to verify the change.

FIXME: move to an external agent that can be shared with SanityCheck

"""
import glob
import logging
import os
import pprint
import subprocess
import tempfile

# from .lint.tcf.py
# Test cases to run
# KEY = filename that caused this
# VALUE = dictionary:
#  reason (for clarity in messages)
#  spec (for tcf run -t SPEC )
#  target (for tcf run TCS)
tcs = {}

ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE', None)
ZEPHYR_PATHS = os.environ.get('ZEPHYR_PATHS', "").split()

def scan_zephyr_app(tcs, _repo, cf):
    # lame check
    if not ZEPHYR_BASE:
        cf.log.info("%s: skipping ZEPHYR_BASE not exported", cf.name)
        return
    abspath = os.path.abspath(cf.name)
    for base in [ ZEPHYR_BASE ] + ZEPHYR_PATHS:
        if base in abspath:
            cf.log.info("considering because there is a base path from "
                        "ZEPHYR_BASE or ZEPHYR_PATHS (%s) in file's path (%s)",
                        base, abspath)
            break
    else:
        return
    # Well, we have a winner, this is prolly some sort of Zephy rapp

    abspath = os.path.abspath(cf.name)

    # Ok, we have determined that the file is in the Zephyr base or a
    # path of interest, so now let's see what testcases it should run
    # based on the path
    # FIXME: move this to a separate script that prints one of more
    # JSON reports with the tcs and should be part of the Zephyr
    # source tree
    basename = os.path.basename(cf.name)
    if basename in [ "testcase.ini", "testcase.yaml", "sample.yaml" ] \
       or (basename.endswith(".py") and basename.startswith("test")):
        tcs[cf.name] = dict(
            reason = "found modified TC file %s" % cf.name)

    path_parts = os.path.relpath(cf.name, ZEPHYR_BASE).split("/")
    acc_parts = []
    # walk all the parts from ZEPHYR_BASE to the file and look for testcases
    for part in path_parts:
        acc_parts.append(part)
        check_path = os.path.join(*([ ZEPHYR_BASE ] + acc_parts))
        if os.path.exists(os.path.join(check_path, 'testcase.ini')) \
           or os.path.exists(os.path.join(check_path, 'testcase.yaml')) \
           or os.path.exists(os.path.join(check_path, 'sample.yaml')):
            tcs[cf.name] = dict(
                reason = "testcase/sample in path of modified file",
                test = os.path.relpath(check_path))

    # the file modifies an specific architecture?
    if cf.name.startswith('arch/'):
        # extract architecture name
        arch = cf.name.split('/')[1]
        # Verify this is really an arch name, not some file in 'arch/'
        if os.path.isdir(os.path.join(ZEPHYR_BASE, "arch", arch)):
            # Well, we are touching something in that arch, so we need
            # to run tests for it
            # FIXME: refine this, tests/kernel is heavy
            tcs[cf.name] = dict(
                reason = "tests/kernel has to run due to changes in arch/%s" \
                    % arch,
                spec = 'bsp == "%s"' % arch,
                test = "tests/kernel")

    # FIXME: do the same thing for boards/BOARDNAME/files and add
    # spec 'zephyr_board == BOARDNAME' as for arch

    if cf.name.startswith('subsys/'):
        subsys_dir = os.path.dirname(cf.name)
        tcs[cf.name] = dict(
            reason = "modified subsystem %s" % subsys_dir,
            test = 'tests/' + subsys_dir)
        # FIXME: need to do some work on subsys_dir, because the
        # change might be in subsys/SUBSYS/some1/some2/some3, but only
        # tests/subsys/SUBSYS/some1 will exist

    if cf.name.startswith('drivers/'):
        driver_dir = os.path.dirname(cf.name)
        tcs[cf.name] = dict(
            reason = "modified driver %s" % driver_dir,
            test = 'tests/' + driver_dir)

    # FIXME: do the same for kernel, lib, etc
    #
    # Note when modifying kernel/, we need to run testcases on all
    # arches and boards, so we also would need to add something to
    # counteract the case where there is a change in arch/x86/something
    # and kernel/something, so it runs not only on x86, but on all arches

    return

# register with .lint.tcf.py as scanner that can provide stuff to execute
tcf_config = __main__.linter_config_get('tcf') 
tcf_config['scanners'].append(scan_zephyr_app)
