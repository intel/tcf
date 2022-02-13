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

import atexit
import errno
import importlib
import inspect
import logging
import multiprocessing
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import commonl
import tcfl

logger = logging.getLogger("testcase")

#: List of callables that will be executed when a testcase is
#: identified; these can modify as needed the testcase (eg:
#: scanning for tags)
testcase_patchers = []


# temporary class to fork() using multiprocessing (works in Windows
# and Linux)
class Process(multiprocessing.Process):
    def __init__(self, *args, **kwargs):
        multiprocessing.Process.__init__(self, *args, **kwargs)
        self._parent_connection, self._child_connection = multiprocessing.Pipe()

    def run(self):
        try:
            r = self._target(*self._args, **self._kwargs)
            self._child_connection.send(r)
        except Exception as e:
            tb = traceback.format_exc()
            self._child_connection.send((e, tb))

    def exception(self):
        if self._parent_connection.poll():
            return self._parent_connection.recv()
        return None

    def retval(self):
        if self._parent_connection.poll():
            return self._parent_connection.recv()
        return None


def this_filename_get(level = 1):
    """Return the name of the filename the function calling this is

    In some cases *__file__* doesn't work because of the way the
    config files are imported (it points to the last filename
    imported).

    So we inspect the current stack frame to look for this
    file's name so we can use it to fish for other files.

    :param int level: (optional 1) how many levels in the stack to go
      up, defaults to this function's caller.

    :returns str: name of the file that declared the calling function
    """
    frame = inspect.stack()[level][0]
    return frame.f_code.co_filename



# Testcases are any file that start with `test` and ends with `.py`
file_regex = re.compile(r'^test[^/]*\.py$')

def _classes_enumerate(path, module, prefix = ""):
    logger.warning("%s: enumerating", module.__name__)
    classes = []
    members = inspect.getmembers(module)
    for member_name, member in members:
        if not inspect.isclass(member):
            logging.info(f"{path}:{prefix}{member_name}: skipping, not a class")
            continue
        if member_name == "__class__":
            logging.info(f"{path}:{prefix}{member_name}: skipping, class definition")
            continue
        # Why recurse? because if someone defines a testclass inside a
        # class, we want to see it
        logging.debug(f"{path}:{prefix}{member_name}: a class, recursing")
        classes += _classes_enumerate(path, member, prefix = member_name + ".")
        if inspect.isabstract(member):
            logging.info(f"{path}:{prefix}{member_name}: skipping, abstract class")
            continue
        if not issubclass(member, tcfl.tc_c):
            logging.debug(f"{path}/{prefix}{member_name}: skipping not subclass of tcfl.tc_c")
            continue
        if member_name.endswith("_base") or member_name.endswith("_abc"):
            logging.info(f"{path}/{prefix}{member_name}: skipping base/abstract class")
            continue
        logging.debug(f"{path}/{prefix}{member_name}: considering, subclass of tcfl.tc_c")
        classes.append(member)
    logger.warning("%s: enumerated: %s", module.__name__,
                   ' '.join(cls.__name__ for cls in classes))
    return classes


# Default driver loader; most test case drivers would over load
# this to determine if a file is a testcase or not.
def is_tcf_testcase(path, from_path, tc_name, subcases_cmdline):
    """Determine if a given file describes one or more testcases and
    crete them

    TCF's test case discovery engine calls this method for each
    file that could describe one or more testcases. It will
    iterate over all the files and paths passed on the command
    line files and directories, find files and call this function
    to enquire on each.

    This function's responsibility is then to look at the contents
    of the file and create one or more objects of type
    :class:`tcfl.tc.tc_c` which represent the testcases to be
    executed, returning them in a list.

    When creating :term:`testcase driver`, the driver has to
    create its own version of this function. The default
    implementation recognizes python files called *test_\*.py* that
    contain one or more classes that subclass :class:`tcfl.tc.tc_c`.

    See examples of drivers in:

    - :meth:`tcfl.tc_clear_bbt.tc_clear_bbt_c.is_testcase`
    - :meth:`tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.is_testcase`
    - :meth:`examples.test_ptest_runner` (:term:`impromptu
      testcase driver`)

    note drivers need to be registered with
    :meth:`tcfl.tc.tc_c.driver_add`; on the other hand, a Python
    :term:`impromptu testcase driver` needs no registration, but
    the test class has to be called *_driver*.

    :param str path: path and filename of the file that has to be
      examined; this is always a regular file (or symlink to it).

    :param str from_path: source command line argument this file
      was found on; e.g.: if *path* is *dir1/subdir/file*, and the
      user ran::

        $ tcf run somefile dir1/ dir2/

      *tcf run* found this under the second argument and thus:

      >>> from_path = "dir1"

    :param str tc_name: testcase name the core has determine based
      on the path and subcases specified on the command line; the
      driver can override it, but it is recommended it is kept.

    :param list(str) subcases_cmdline: list of subcases the user
      has specified in the command line; e.g.: for::

        $ tcf run test_something.py#sub1#sub2

      this would be:

      >>> subcases_cmdline = [ 'sub1', 'sub2']

    :returns: list of testcases found in *path*, empty if none
      found or file not recognized / supported.

    """
    if not file_regex.search(os.path.basename(path)):
        logging.info(f"{path}: skipping, doesn't match {file_regex.pattern}")
        return []
    # try to load the module.
    # FIXME: move to tcf-detect.py
    try:
        loader = importlib.machinery.SourceFileLoader("module", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    except Exception as e:
        # we are trying to load as Python something that might not be,
        # so catch it all
        raise tcfl.blocked_e(
            "cannot import: %s (%s)" % (e, type(e).__name__),
            { "ex_trace": traceback.format_exc() })

    # Find all classes in the module
    try:
        classes = _classes_enumerate(path, module)
    except Exception as e:
        logging.exception(e)
        raise
    # Get instances of subclassess of tc_c class as testcases
    if classes == []:
        logger.warning("%s: no suitable classes found in %s",
                       path, module)
        # Nothing found, so let's try to fully delete the module and
        # garbage collect it--note seems that when we load like we
        # did, it doesn't end up in sys.modules
        del module
        return []

    tcs = []
    for _cls in classes:
        subcase_name = _cls.__name__
        if subcase_name != "_driver" \
           and subcase_name != "_test" \
           and subcases_cmdline and subcase_name not in subcases_cmdline:
            logging.info("%s: subcase ignored since it wasn't "
                         "given in the command line list: %s",
                         subcase_name, " ".join(subcases_cmdline))
            continue
        if subcase_name not in ( "_test", "_driver" ):
            # if the test class name is just "_test", we don't
            # even list it as as test, we assume per convention it
            # is the only test in the file
            name = tc_name + "#" + subcase_name
        else:
            name = tc_name
        # testcase name, file where it came from, origin
        try:
            # some forms of defining classes (like using type)
            # might not find it funny and make it easy to find the
            # line number
            source_line = str(inspect.getsourcelines(_cls)[1])
        except ( TypeError, IOError ) as e:
            # TypeError happens in deep classes (a class within a
            # class) because Pyhton can't find the line number for
            # that (??)
            source_line = "n/a"
        tc = _cls(name, path, path + ":" + source_line)
        if subcase_name in ( "_test", "_driver" ):
            # make a copy, as we might modify during execution
            tc.subcases = list(subcases_cmdline)
        tcs.append(tc)
    return tcs



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
        if tc_driver == tcfl.tc_c:
            # default special case
            return is_tcf_testcase(file_name, from_path,
                                   tc_name, subcases_cmdline)
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
    for _tc_driver in _drivers:
        tc_instances = []
        # new one all the time, in case we use it and close it
        tc_fake = tcfl.tc_c(tc_name, file_name,
                            f"builtin @{commonl.origin_get(1)}")
        tcfl.testcase.discovery_init(tc_fake)
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
                tcfl.testcase.run_finalize(tc_fake, retval)
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
                tcfl.testcase.run_finalize(tc_fake, retval)
                result += retval
                continue
            except Exception as e:
                retval = tcfl.result_c.report_from_exception(tc_fake, e)
                tcfl.testcase.run_finalize(tc_fake, retval)
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

def discover(tcs_filtered, sources, manifests = None, filter_spec = None,
             testcase_name = None):
    """

    :param str testcase_name: (optional) used for unit testing

    :returns tcfl.

    PENDING/FIXME:

    - discover using a multiprocess Pool external program to avoid
      loading into the current address space (Pool is platform
      agnostic)
    """
    if manifests != None:
        commonl.assert_list_of_strings(manifests, "list of manifests",
                                       "manifest filename")
    else:
        manifests = []
    result = tcfl.result_c(0, 0, 0, 0, 0)

    # discover test cases
    tcs_filtered.clear()
    if len(sources) == 0 and len(manifests) == 0:
        logger.warning("No testcases specified, searching in "
                       "current directory, %s", os.getcwd())
        sources = [ '.' ]
    tcs = {}
    tcfl.tc.tc_global.report_info("scanning for test cases", dlevel = 2)

    # Read all manifest files provided; this is just reading lines
    # that are not empty; later we'll check if we can read them or
    # not, using the testcase drivers
    #
    # regex ignore any line that starts with a comment or is empty
    ignore_r = re.compile(r"^(\s*#.*|\s*)$")
    for manifest_file in manifests:
        try:
            with open(os.path.expanduser(manifest_file)) as manifest_fp:
                tcfl.tc.tc_global.report_info(
                    f"{manifest_file}: reading testcases from manifest file",
                    dlevel = 2)
                for tc_path_line in manifest_fp:
                    tc_path_line = tc_path_line.strip()
                    if ignore_r.match(tc_path_line):
                        tcfl.tc.tc_global.report_info(
                            f"{manifest_file}: {tc_path_line}: ignored"
                            f" (doesn't match regex '{ignore_r.pattern}')",
                            dlevel = 3)
                        continue
                    tcfl.tc.tc_global.report_info(
                        f"{manifest_file}: {tc_path_line}: considering",
                        dlevel = 3)
                    sources.append(os.path.expanduser(tc_path_line))
        except OSError as e:
            tcfl.tc.tc_global.report_blck(
                f"{manifest_file}: can't read manifes file: {e}", dlevel = 3)
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
        for driver in _drivers:
            if driver == tcfl.tc_c:
                continue	# skip, core searching done above
            driver.find_testcases(tcs, tc_path, subcases_cmdline)

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
        discovery_init(tc)
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
        except Exception as e:
            with tcfl.msgid_c() as _msgid:
                result += tcfl.result_c.report_from_exception(tc, e)

    # FIXME: this should be printed by caller? or not by caller and here
    if not tcs_filtered:
        logger.error("All testcases skipped or filtered out by command "
                     "line -s options")
        return result
    logger.warning("Testcases filtered by command line to: %s",
                   ", ".join(list(tcs_filtered.keys())))
    return result

def mkhashid(tc: tcfl.tc_c, hashid: str = None):
    """
    Set a testcases' :term:hashid
    """
    # FIXME: rename to internal API, _mkid
    #        rename ticket to hashid
    #        change to consider also tc axes
    #          (test running on same TC group with different axes)
    #        remove passing of ticket to server? we don't really
    #        use it anymore
    #
    # Note we use this msgid's string as tc_hash for subsitution,
    # it is a unique name based on target name and BSP model, test
    # case name (which might be more than just the tescase path if
    # a single file yields multiple test cases).
    if hashid != None:
        assert isinstance(hashid, str)
        tc.hashid = hashid
        return

    # Feed entropy into the ID:
    # - the testcase name
    # - the salt specified by the user
    # - the RunID
    # - the target group ID where the testcase is runing
    #   [str in case it's None at the time]
    logging.error("FIXME: _mkhashid feed APID")
    logging.error("FIXME: _mkhashid feed TGID")
    tc.hashid = commonl.mkid(tc.name + tc.hash_salt + tc.runid + str(tc.tgid),
                             tc.hashid_len)

    tc.kw_set("tc_hash", tc.hashid)
    tc.kw_set("hashid", tc.hashid)
    tc.ticket = tc.hashid		# COMPAT/FIXME reporter_c
    if tc.runid:
        tc.runid_hashid = f"{tc.runid}{tcfl.report_runid_hashid_separator}{tc.hashid}"
    else:
        tc.runid_hashid = tc.hashid
    tc.kw_set("runid_hashid", tc.runid_hashid)


def discovery_init(tc: tcfl.tc_c):
    print(f"DEBUG discovery_init {id(tc)} STARTING")
    # init a testcase to be able to do basic discovery
    mkhashid(tc)
    tc.tmpdir = os.path.join(tcfl.tc_c.tmpdir, tc.hashid)
    commonl.makedirs_p(tc.tmpdir, reason = "testcase's tmpdir")

    # Add a bunch of kws that we can use in multiple areas
    tc.kw_set('pid', str(os.getpid()))
    tc.kw_set('tid', "%x" % threading.current_thread().ident)
    # use instead of getfqdn(), since it does a DNS lookup and can
    # slow things a lot
    tc.kw_set('host_name', socket.gethostname())
    tc.kw_set('tc_name', tc.name)
    # top level testcase name is that of the toplevel testcase,
    # with any subcases removed (anything after ##), so
    #
    # some/test/path/name#param1#param2##subcase/path/subcase
    #
    # becomes
    #
    # some/test/path/name#param1#param2
    tc.kw_set('tc_name_toplevel', tc.name.split("##", 1)[0])
    tc.kw_set('cwd', os.getcwd())
    # This one is left for drivers to do their thing in here
    tc.kw_set('tc_name_short', tc.name)
    tc.kw_set('tc_origin', tc.origin)

    # Calculate the report file prefix and set it
    tc.report_file_prefix = os.path.join(tcfl.tc_c.log_dir, f"report-{tc.runid_hashid}")
    tc.kws['report_file_prefix'] = tc.report_file_prefix
    print(f"DEBUG discovery_init {id(tc)} DONE")

def run_cleanup(tc):
    # Remove and wipe files left behind
    # FIXME: move this to set all the files in a tempdir specific
    # to each TC instantation and just wipe that dir at the end / __del__
    for pathname in tc.cleanup_files:
        try:
            os.unlink(pathname)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise


def run_finalize(tc, result):
    """
    Mark the end of a testcase's execution
    """
    # this is here vs run to simplify the dependency chain
    assert isinstance(tc, tcfl.tc_c)
    assert isinstance(result, tcfl.result_c)
    tc.ts_end = time.time()
    tc.report_tweet(
        "COMPLETION", result,
        # Trick: won't see this, report driver will
        level = 1000,
        ignore_nothing = False
    )
    run_cleanup(tc)


# List of registered drivers
_drivers = []


def driver_add(cls: tcfl.tc_c, *args, origin: str = None, **kwargs):
    """
    Add a driver to handle test cases (a subclass of :class:`tc_c`)

    A testcase driver is a subclass of :class:`tcfl.tc.tc_c` which
    overrides the methods used to locate testcases and implements the
    different testcase configure/build/evaluation functions.

    >>> import tcfl
    >>> class my_tc_driver_c(tcfl.tc_c):
    >>>    ...
    >>> tcfl.testcases.driver_add(my_tc_driver_c)

    :param tcfl.tc.tc_c _cls: testcase driver
    :param str origin: (optional) origin of this call
    """
    assert issubclass(cls, tcfl.tc_c), \
        f"cls: expected subclass of tcfl.tc_c; got {type(cls)}"
    if origin == None:
        origin = commonl.origin_get(1)
    else:
        assert isinstance(origin, str)

    cls.origin = origin
    logger.info("%s: added test case driver @%s", cls.__name__, origin)
    cls.driver_setup(*args, **kwargs)
    _drivers.append(cls)


def discovery_setup(log_dir = None, tmpdir = None,
                    remove_tmpdir = True, runid = ""):
    #
    # Minimum initialization of the testcase discovery system
    #

    tcfl.tc_c.runid = runid
    # Where we place collateral
    if log_dir == None or not log_dir:
        tcfl.tc_c.log_dir = os.getcwd()
    else:
        tcfl.tc_c.log_dir = log_dir
    try:
        commonl.makedirs_p(tcfl.tc_c.log_dir)
    except OSError as e:
        logging.error(f"can't create collateral dir '{log_dir}': {e}")
        raise

    # Create a tempdirectory for testcases to go wild
    #
    # - each testcase runs in a separate thread, and the change
    #   directory is per-process, so we can't have tstcases magically
    #   writing to CWD and not collide with each other
    #
    # - we want trash being written in a noticeable place, so it is
    #   noticed and fixed.
    #
    if tmpdir:
        commonl.check_dir_writeable(tmpdir,
                                    "testcases' run temporary directory")
        # We don't check if the tempdir is empty -- we might want to
        # reuse build stuff from a prev build and such -- it's up to
        # the user to use the right tempdir
        tcfl.tc_c.tmpdir = os.path.abspath(tmpdir)
    else:
        tcfl.tc_c.tmpdir = tempfile.mkdtemp(prefix = "tcf.run.")
    if remove_tmpdir:
        atexit.register(shutil.rmtree, tcfl.tc_c.tmpdir, True)
    else:
        atexit.register(
            sys.stderr.write,
            "I: %s: not removing temporary directory\n" % tcfl.tc_c.tmpdir)


# Add the core test driver class which recognizes TCF testcases
driver_add(tcfl.tc_c)
