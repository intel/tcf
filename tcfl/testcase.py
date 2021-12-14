#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Utilities for testcases
#
# - scan for testcases
#
#
# Most of this code has been moved from tcfl/tc.py and is in the
# process of being cleaned up

import inspect
import logging
import os
import re
import subprocess

import tcfl
import tcfl.tc

logger = logging.getLogger("testcase")

#: List of callables that will be executed when a testcase is
#: identified; these can modify as needed the testcase (eg:
#: scanning for tags)
testcase_patchers = []

# FIXME: rename to discover_, make public
_ignore_regexs = [
    # FIXME: there was a way to get the current file and line to
    # replace builtin
    (re.compile(".*~$"), "builtin"),
    (re.compile(r".*\.txt$"), "builtin"),
    (re.compile(r".*\.[oachS]$"), "builtin"),
    (re.compile(r".*\.asm$"), "builtin"),
    (re.compile(r".*\.so$"), "builtin"),
    (re.compile(r".*\.o\.cmd$"), "builtin"),
    (re.compile(r".*\.cmd$"), "builtin"),
    (re.compile(r".*\.pyc$"), "builtin"),
    (re.compile(r"\.git/"), "builtin"),
]
# List of regular expressions of directory names to ignore
_ignore_directory_regexs = [
    (re.compile("^outdir(-.*)?$"), "builtin"),
    (re.compile("^.git$"), "builtin"),
]

def _create_from_file_name(tcis, file_name, from_path,
                           subcases_cmdline):
    """
    Given a filename that contains a possible test case, create one or
    more TC structures from it and return them in a list

    :param list tcis: list where to append found test case instances
    :param str file_name: path to file to consider
    :param str from_path: original path from which this file was
      scanned (this will be a parent path of this file)
    :param list subcases: list of subcase names the testcase should
      consider
    :returns: tcfl.result_c with counts of tests passed/failed (zero,
      as at this stage we cannot know), blocked (due to error
      importing) or skipped(due to whichever condition).
    """
    # FIXME: not working well to ignore .git
    result = tcfl.result_c(0, 0, 0, 0, 0)
    for ignore_regex, origin in _ignore_regexs:
        if ignore_regex.match(file_name):
            logger.log(6, "%s: ignored by regex %s [%s]",
                       file_name, ignore_regex.pattern, origin)
            return result

    def _style_get(_tc_driver):
        argspec = inspect.getargspec(_tc_driver.is_testcase)
        if len(argspec.args) == 2:
            return 2
        # v2: added from_path
        elif len(argspec.args) == 3:
            return 3
        # v3; added tc_name, subcases
        elif len(argspec.args) == 5:
            return 4
        else:
            raise AssertionError(
                "%s: unknown # of arguments %d to is_testcase()"
                % (_tc_driver, len(argspec.args)))

    def _is_testcase_call(tc_driver, tc_name, file_name,
                          from_path, subcases_cmdline):
        style = _style_get(tc_driver)
        # hack to support multiple versions of the interface
        if style == 2:
            return tc_driver.is_testcase(file_name)
        elif style == 3:
            return tc_driver.is_testcase(file_name, from_path)
        elif style == 4:
            return tc_driver.is_testcase(file_name, from_path,
                                         tc_name, subcases_cmdline)
        raise AssertionError("bad style %d" % style)

    if subcases_cmdline:
        tc_name = file_name + "#" + "#".join(subcases_cmdline)
    else:
        tc_name = file_name
    for _tc_driver in tcfl.tc.tc_c._tc_drivers:
        tc_instances = []
        # new one all the time, in case we use it and close it
        tc_fake = tcfl.tc.tc_c(tc_name, file_name, "builtin")
        tc_fake.mkticket()
        with tcfl.msgid_c(depth = 1) as _msgid:
            cwd_original = os.getcwd()
            try:
                tc_instances += _is_testcase_call(_tc_driver, tc_name,
                                                  file_name, from_path,
                                                  subcases_cmdline)
                for _tc in tc_instances:
                    logger.info("testcase found @ %s by %s",
                                _tc.origin, _tc_driver)

            # this is so ugly, need to merge better with tcfl.result_c's handling
            except subprocess.CalledProcessError as e:
                retval = tcfl.result_c.from_exception_cpe(tc_fake, e)
                tc_fake.finalize(retval)
                result += retval
                continue
            except OSError as e:
                attachments = dict(
                    errno = e.errno,
                    strerror = e.strerror
                )
                if e.filename:
                    attachments['filename'] = e.filename
                retval = tcfl.result_c.report_from_exception(tc_fake, e,
                                                        attachments)
                tc_fake.finalize(retval)
                result += retval
                continue
            except Exception as e:
                retval = tcfl.result_c.report_from_exception(tc_fake, e)
                tc_fake.finalize(retval)
                result += retval
                continue
            finally:
                cwd = os.getcwd()
                if cwd != cwd_original:
                    logging.error(
                        "%s: driver changed working directory from "
                        "%s to %s; this is a BUG in the driver!"
                        % (_tc_driver.origin, cwd_original, cwd))
                    os.chdir(cwd_original)
        if not tc_instances:
            continue

        for _tc in tc_instances:
            for testcase_patcher in testcase_patchers:
                testcase_patcher(_tc)
        tcis += tc_instances
        break
    else:
        logger.log(7, "%s: no testcase driver got it", file_name)

    return result


def _find_in_path(tcs, path, subcases_cmdline):
    """
    Given a path, scan for test cases and put them in the
    dictionary @tcs based on filename where found.
    list of zero or more paths, scan them for files that
    contain testcase tc information and report them.
    :param dict tcs: dictionary where to add the test cases found

    :param str path: path where to scan for test cases

    :param list subcases: list of subcase names the testcase should
      consider

    :returns: tcfl.result_c with counts of tests passed/failed (zero,
      as at this stage we cannot know), blocked (due to error
      importing) or skipped(due to whichever condition).
    """
    assert isinstance(tcs, dict)
    # FIXME this should cache stuff so we don't have to rescan all the
    # times--if the ctime hasn't changed since our cache entry, then
    # we use the cached value
    result = tcfl.result_c(0, 0, 0, 0, 0)
    tcfl.tc.tc_global.report_info(
        "%s: scanning argument" % path, dlevel = 4)
    if os.path.isdir(path):
        for tc_path, _dirnames, _filenames in os.walk(path):
            logger.log(5, "%s: scanning directory", tc_path)
            tcfl.tc.tc_global.report_info("%s: scanning directory" % tc_path,
                                          dlevel = 5)
            # Remove directories we don't care about
            # FIXME: very o(n)
            keep_dirs = []
            for dirname in list(_dirnames):
                for dir_ignore_regex, _origin in _ignore_directory_regexs:
                    if dir_ignore_regex.match(dirname):
                        break
                else:
                    keep_dirs.append(dirname)
            del _dirnames[:]
            _dirnames.extend(keep_dirs)
            for filename in sorted(_filenames):
                tc_instances = []
                file_name = os.path.join(tc_path, filename)
                result += _create_from_file_name(
                    tc_instances, file_name, path, subcases_cmdline)
                for _tc in tc_instances:
                    tcs[_tc.name] = _tc
    elif os.path.isfile(path):
        tc_instances = []
        result += _create_from_file_name(
            tc_instances, path, os.path.dirname(path), subcases_cmdline)
        for _tc in tc_instances:
            tcs[_tc.name] = _tc
    return result


def _match_tags(tc, tags_spec, origin = None):
    """
    Given a testcase and a tag specification, raise an skip
    :param str tags: string describing tag selection expression
    for :py:mod:`commonl.expr_parser`
    :param bool not_found_mistmatch: if a tag filter specifies a
      tag that is not found in the test case, treat it as a mismatch
      versus ignoring it.
    """
    if tags_spec == None:
        tc.report_info("selected by no-tag specification", dlevel = 4)
        return
    else:
        assert isinstance(tags_spec, str)
    if origin == None:
        origin = "[builtin]"
    kws = dict()
    for name, (value, _vorigin) in tc._tags.items():
        kws[name] = value

    if not commonl.conditional_eval("testcase tag match", kws, tags_spec,
                                    origin, kind = "specification"):
        raise skip_e("because of tag specification '%s' @ %s" %
                     (tags_spec, origin), dict(dlevel = 4))
    tc.report_info("selected by tag specification '%s' @ %s" %
                   (tags_spec, origin), dlevel = 4)

#
# Keep this away from tcfl.tc_c, they are side internals that need not
# clutter that API that's already too dense
#

def discover(tcs_filtered, sources, manifests, filter_spec,
             testcase_name = None):
    """

    :param str testcase_name: (optional) used for unit testing

    :returns tcfl.

    PENDING/FIXME:

    - discover using a multiprocess Pool external program to avoid
      loading into the current address space (Pool is platform
      agnostic)
    """
    result = tcfl.result_c(0, 0, 0, 0, 0)

    # discover test cases
    tcs_filtered.clear()
    if len(sources) == 0 and len(manifests) == 0:
        logger.warning("No testcases specified, searching in "
                       "current directory, %s", os.getcwd())
        sources = [ '.' ]
    tcs = {}
    tcfl.tc.tc_global.report_info("scanning for test cases", dlevel = 2)

    ignore_r = re.compile(r"^(\s*#.*|\s*)$")
    for manifest_file in manifests:
        try:
            with open(os.path.expanduser(manifest_file)) as manifest_fp:
                for tc_path_line in manifest_fp:
                    if not ignore_r.match(tc_path_line):
                        sources.append(
                            os.path.expanduser(tc_path_line.strip()))
        except OSError:
            file_error = sys.exc_info()[1]
            logger.error("Error reading file: " + str(file_error))
            result.blocked += 1

    for tc_path in sources:
        if ',' in tc_path:
            parts = tc_path.split(',')
            tc_path = parts[0]
            subcases_cmdline = parts[1:]
            logger.info("commandline '%s' requests subcases: %s",
                        tc_path, " ".join(subcases_cmdline))
        elif '#' in tc_path:
            parts = tc_path.split('#')
            tc_path = parts[0]
            subcases_cmdline = parts[1:]
            logger.info("commandline '%s' requests subcases: %s",
                        tc_path, " ".join(subcases_cmdline))
        else:
            subcases_cmdline = []
            logger.info("commandline '%s' requests no subcases", tc_path)
        if not os.path.exists(tc_path):
            logger.error("%s: does not exist; ignoring", tc_path)
            continue
        result += _find_in_path(tcs, tc_path, subcases_cmdline)
        # FIXME: move this to tcfl.tc_c._drivers
        for tcd in tcfl.tc.tc_c._tc_drivers:
            # If a driver has a different find function, use it to
            # find more
            # FIXME: just call the dang function?
            tcd_find_in_path = getattr(tcd, "find_in_path", None)
            if tcd_find_in_path is not None and\
               id(getattr(tcd_find_in_path, "__func__", tcd_find_in_path)) \
               != id(tcfl.tc.tc_c.find_in_path.__func__):
                result += tcd.find_in_path(tcs, tc_path, subcases_cmdline)
    if len(tcs) == 0:
        logger.error("WARNING! No testcases found")
        return result

    # Now that we have them testcases, filter them based on the
    # tag filters specified in the command line with '-s'. Multiple's
    # are ORed together. Then for each testcase, apply the filter see
    # if it selects it or not.
    if not filter_spec:
        tags_spec = None
    else:
        tags_spec = "(" + ") or (".join(filter_spec) +  ")"

    for tc_path, tc in tcs.items():
        try:
            # This is a TC unit testcase aid
            if testcase_name and tc.name != testcase_name:
                # Note this is only use for unit testing, so we don't
                # account it in the list of skipped TCs
                tcfl.tc.tc_global.report_info(
                    "ignoring because of testcase name '%s' not "
                    "matching sources_name %s'"
                    % (tc.name, sources_name),
                    dict(dlevel = 1))
                continue
            # FIXME: simplify this a lot, just have it return STH? I
            # feel we could do without the exception handling it, this
            # is too complicated
            _match_tags(tc, tags_spec, "command line")
            # Anything with a skip tag shall be skipped
            skip_value, skip_origin = tc.tag_get('skip', False)
            if skip_value != False:
                if isinstance(skip_value, str):
                    raise skip_e("because of 'skip' tag @%s: %s"
                                 % (skip_origin, skip_value))
                else:
                    raise skip_e("because of 'skip' tag @%s" % skip_origin)
            # Fill in any arguments from the command line
            # We will consider this testcase
            tcs_filtered[tc_path] = tc
        except exception as e:
            tc.mkticket()
            with msgid_c() as _msgid:
                result += tcfl.result_c.report_from_exception(tc, e)

    if not tcs_filtered:
        logger.error("All testcases skipped or filtered out by command "
                     "line -s options")
        return result
    logger.warning("Testcases filtered by command line to: %s",
                   ", ".join(list(tcs_filtered.keys())))
    return result
