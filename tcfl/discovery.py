#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""Discover testcases in directories or files
==========================================

This module contains the logic for different drivers to be able to to
discover testcases in a number in different files.

A discovery agent object :class:`agent_c` is created to maintain the
discovery state; then :meth:`agent_c.run` executed to run the discovery
process. :data:`agent_c.tcis` will contain the information about found
testcases. 

The discovery process involves enumerating all possible files in the
paths passed as input and spawning a separate process for each (to
isolate from crashes, failures to import and other errors). When a
valid testcase is found, the process will be left as an execution
server off :meth:`_process_find_in_file` that can launch testcases to
execute. See :class:`agent_c` for more details.

Quick usage:

>>> import tcfl.discovey
>>> tcfl.discovery.subsystem_setup()
>>> discovery_agent = tcfl.discovery.agent_c()
>>> discovery_agent.run(paths = [ "." ])
>>> print(discovery_agent.tcis)

"""
#
# ROADMAP
#
# agent_c.run() gets called from whoever wants to discover testcases;
# see *Quick Usage* above.
#
#  agent_c.run()
#    agent_c._find_in_path()
#      agent_c._find_in_directory()
#        agent_c._find_in_file()
#      agent_c._find_in_file()
#    agent_c._process_find_in_file() [SEPARATE PROCESS]
#      _create_from_file_name()
#        _is_testcase_call()
#           is_tcf_testcase()
#            _classes_enumerate()
#              _classes_enumerate()
#           driver.is_testcase()
#    agent_c.tcis_get_from_queue()
#
#
#
import atexit
import collections
import io
import inspect
import importlib
import logging
import multiprocessing
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

import commonl
import tcfl
import tcfl.tc

# COMPAT
tcfl.tc_global = tcfl.tc.tc_global
tcfl.tc_c = tcfl.tc.tc_c

log = logging.getLogger("tc-discovery")
log_sub = log.getChild("(subprocess)")
log_tcf_sub = logging.getLogger("tcf discovery (subprocess)")

# Testcases are any file that start with `test` and ends with `.py`
tcf_file_regex = re.compile(r'^test[^/]*\.py$')



def _classes_enumerate(path, module, prefix = "", logger = logging):
    # enumerates recursively all classes in a module
    logger.debug("enumerating classes in %s", module.__name__)
    classes = []
    members = inspect.getmembers(module)
    for member_name, member in members:
        if not inspect.isclass(member):
            logger.debug(f"{prefix}{member_name}: skipping, not a class")
            continue
        if member_name == "__class__":
            logger.debug(f"{prefix}{member_name}: skipping,"
                         " class definition")
            continue
        # Why recurse? because if someone defines a testclass inside a
        # class, we want to see it
        logger.debug(f"{prefix}{member_name}: a class, recursing")
        classes += _classes_enumerate(path, member,
                                      prefix = member_name + ".",
                                      logger = logger.getChild(member_name))
        if inspect.isabstract(member):
            logger.debug(f"{prefix}{member_name}: skipping, abstract class")
            continue
        if not issubclass(member, tcfl.tc_c):
            logger.debug(f"{prefix}{member_name}: skipping not"
                         " subclass of tcfl.tc_c")
            continue
        if member_name.endswith("_base") or member_name.endswith("_abc"):
            logger.debug(f"{prefix}{member_name}: skipping base/abstract class")
            continue
        logger.debug(f"{prefix}{member_name}: considering,"
                     " subclass of tcfl.tc_c")
        classes.append(member)
    if classes:
        logger.info("found classes: %s",
                       ' '.join(cls.__name__ for cls in classes))
    else:
        logger.debug("found no classes")
    return classes



# Default driver loader; most test case drivers would over load
# this to determine if a file is a testcase or not.
def is_tcf_testcase(path, from_path, tc_name, subcases_cmdline,
                    logger = log_tcf_sub):
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
    implementation recognizes python files called *test_\\*.py* that
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
    if not tcf_file_regex.search(os.path.basename(path)):
        # note we don't report this as an skipped testcase because it
        # is not a testcase, it is an skipped file that doesn't match
        # the patttern for a testcase
        logger.info(f"tcfl.tc_c: skipping, filename doesn't match {tcf_file_regex.pattern}")
        return []
    # try to load the module.
    # note we are running this in a separate process, so we are not
    # affected by what other modules loaded
    try:
        module_path, _ext = os.path.splitext(path)
        loader = importlib.machinery.SourceFileLoader(
            module_path.replace("/", "."), path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        logger.info("loading module %s", path)
        loader.exec_module(module)
    except Exception as e:
        logger.error("loading module %s failed: %s", path, e, exc_info = True)
        # we are trying to load as Python something that might not be,
        # so catch it all and return an error entry for it
        return [
            tcfl.tc_info_c(
                path, path,
                subcase_spec = subcases_cmdline,
                result = tcfl.result_c(blocked = 1),
                # we don't use the original exception, as it might
                # have things we can't pickle
                exception = RuntimeError(f"cannot import as python: {e}"),
                formatted_traceback = traceback.format_tb(sys.exc_info()[2]),
            )
        ]


    # Find all classes in the module
    try:
        classes = _classes_enumerate(path, module, logger = logger)
        logger.info("enumerated %d classes: %s", len(classes), classes)
    except Exception as e:
        logger.error("exception enumerating classes: %s", e, exc_info = True)
        raise
    # Get instances of subclassess of tc_c class as testcases
    if classes == []:
        logger.warning(" no suitable classes found in %s", module)
        # Nothing found, so let's try to fully delete the module and
        # garbage collect it--note seems that when we load like we
        # did, it doesn't end up in sys.modules
        del module
        return []
    logger.info("found %d classes (%s)",
                len(classes), ",".join([ str(i) for i in classes]))

    # We found stuff
    tcs = []
    for _cls in classes:
        subcase_name = _cls.__name__
        logger.info("exploring testcase class %s", subcase_name)
        if subcase_name != "_driver" \
           and subcase_name != "_test" \
           and subcases_cmdline and subcase_name not in subcases_cmdline:
            logger.info("%s: subcase ignored since it wasn't "
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



def _style_get(_tc_driver):
    # Backwards compat: determine which vesion type a testcase driver
    # is; is_testcase() signature that have evolved over the years
    signature = inspect.signature(_tc_driver.is_testcase)
    if len(signature.parameters) == 1:
        return 2
    # v2: added from_path
    if len(signature.parameters) == 2:
        return 3
    # v3; added tc_name, subcases
    if len(signature.parameters) == 4:
        return 4
    raise AssertionError(
        "%s: unknown # of arguments %d to is_testcase()"
        % (_tc_driver, len(signature.parameters)))



def _is_testcase_call(tc_driver, tc_name, file_name,
                      from_path, subcases_cmdline, logger = logging):
    # Call testcase's is_testcase() method to generate a list of
    # testcase description object
    if tc_driver == tcfl.tc_c:
        # default special case
        return is_tcf_testcase(file_name, from_path,
                               tc_name, subcases_cmdline, logger = logger)
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



def _tc_info_from_tc_c(testcase: tcfl.tc.tc_c):
    assert isinstance(testcase, tcfl.tc.tc_c)
    
    target_roles = dict()
    for target_want_name, tw in testcase._targets.items():
        target_role = tcfl.target_role_c(
            target_want_name,
            origin = tw['origin'],
            spec = tw['spec'],
            interconnect = False,
        )
        # v1 tc_c can only spin type
        target_role.axes = { "type": None }
        target_roles[target_want_name] = target_role
    for ic_want_name in testcase._interconnects:
        ic = testcase._targets[ic_want_name]
        target_roles[ic_want_name] = tcfl.target_role_c(
            ic_want_name,
            origin = ic['origin'],
            spec = ic['spec'],
            interconnect = True,
        )
    if not target_roles:
        target_roles = None
    tc_info = tcfl.tc_info_c(
        testcase.name, testcase.kws['thisfile'],
        origin = testcase.origin,
        target_roles = target_roles,
        subcase_spec = testcase.subcases,
        driver_name = str(testcase),
        tags = testcase._tags,
        result = tcfl.result_c(),
        # original tcfl.tc.tc_c only supports spinning over the type axes
        axes = { "type": None },
    )
    return tc_info



def _create_from_file_name(tcis, file_name, from_path, subcases_cmdline,
                           logger = logging):
    """
    Given a filename that contains a possible test case, create one or
    more TC structures from it and return them in a list

    :param dict tcis: list where to append found test case instances
    :param str file_name: path to file to consider
    :param str from_path: original path from which this file was
      scanned (this will be a parent path of this file)
    :param list subcases: list of subcase names the testcase should
      consider
    :returns: tcfl.result_c with counts of tests passed/failed (zero,
      as at this stage we cannot know), blocked (due to error
      importing) or skipped(due to whichever condition).
    """
    result = tcfl.result_c(0, 0, 0, 0, 0)

    tc_name = file_name
    if subcases_cmdline:
        tc_name += "#" + "#".join(subcases_cmdline)
    for _tc_driver in tcfl.tc.tc_c._tc_drivers:
        testcases = []
        logger.info("scanning with driver %s", _tc_driver)
        with tcfl.msgid_c(depth = 1) as _msgid:	# FIXME: remove, unneeded here
            try:
                # FIXME: replce with __name__ when we remove tc_mc from tcfl.tc_c
                logger_driver = logger.getChild(f"[{_tc_driver}]")
                logger_driver.info("scanning")
                testcases += _is_testcase_call(
                    _tc_driver, tc_name,
                    file_name, from_path,
                    subcases_cmdline,
                    logger = logger_driver)
                logger_driver.info("found %d new testcases", len(testcases))
                # a single file might contain more than one testcase
                for testcase in testcases:
                    if isinstance(testcase, tcfl.tc_c):
                        # FIXME: warn once for each driver
                        logger_driver.warning(
                            f"fix driver '{_tc_driver.__name__}' to return tcfl.tc_info_c")
                        tcis[file_name].append(_tc_info_from_tc_c(testcase))
                    elif isinstance(testcase, tcfl.tc_info_c):
                        logger_driver.info("testcase found @ %s by %s",
                                           testcase.origin, _tc_driver)
                        tcis[file_name].append(testcase)
                    else:
                        tcis[file_name].append(tcfl.tc_info_c(
                            file_name, file_name,
                            subcase_spec = subcases_cmdline,
                            result = tcfl.result_c(blocked = 1),
                            exception = RuntimeError(
                                f"BUG: invalid type {type(testcase)} returned"
                                f" by testcase driver {_tc_driver}")
                        ))

            # this is so ugly, need to merge better with result_c's handling
            except subprocess.CalledProcessError as e:
                # no trace here, since we append it to the
                # formatted_traceback down there that can be
                # seen
                logger_driver.info("scanning exception: subprocess %s", e)
                tcis[file_name].append(tcfl.tc_info_c(
                    tc_name, file_name,
                    subcase_spec = subcases_cmdline,
                    result = tcfl.result_c(blocked = 1),
                    exception = e,
                    formatted_traceback = traceback.format_tb(sys.exc_info()[2]),
                ))
                continue
            except OSError as e:
                logger_driver.info("scanning exception: oserror %s", e)
                attachments = dict(
                    errno = e.errno,
                    strerror = e.strerror
                )
                if e.filename:
                    attachments['filename'] = e.filename
                tcis[file_name].append(tcfl.tc_info_c(
                    tc_name, file_name,
                    subcase_spec = subcases_cmdline,
                    result = tcfl.result_c(blocked = 1),
                    exception = e,
                    formatted_traceback = traceback.format_tb(sys.exc_info()[2])
                ))
                continue
            except Exception as e:
                if isinstance(e, ( AttributeError, TypeError )):
                    # usually a code error we want to see loud and clear
                    logger_driver.error(
                        "scanning exception: %s %s",
                        type(e), e, exc_info = commonl.debug_traces)
                else:
                    logger_driver.info(
                        "scanning exception: %s %s", type(e), e,
                        exc_info = commonl.debug_traces)
                tcis[file_name].append(tcfl.tc_info_c(
                    tc_name, file_name,
                    subcase_spec = subcases_cmdline,
                    result = tcfl.result_c(blocked = 1),
                    exception = e,
                    formatted_traceback = traceback.format_tb(sys.exc_info()[2])
                ))
                continue
    else:
        logger.log(7, "%s: no testcase driver got it", file_name)

    return result



def _manifest_expand(sources, result, manifests):
    # Read all manifest files provided; this is just reading lines
    # that are not empty; later we'll check if we can read them or
    # not, using the testcase drivers
    #
    # regex ignore any line that starts with a comment or is empty
    ignore_r = re.compile(r"^(\s*#.*|\s*)$")
    for manifest_file in manifests:
        try:
            with open(os.path.expanduser(manifest_file)) as manifest_fp:
                tcfl.tc_global.report_info(
                    f"{manifest_file}: reading testcases from manifest file",
                    dlevel = 2)
                for tc_path_line in manifest_fp:
                    tc_path_line = tc_path_line.strip()
                    if ignore_r.match(tc_path_line):
                        tcfl.tc_global.report_info(
                            f"{manifest_file}: {tc_path_line}: ignored"
                            f" (doesn't match regex '{ignore_r.pattern}')",
                            dlevel = 3)
                        continue
                    tcfl.tc_global.report_info(
                        f"{manifest_file}: {tc_path_line}: considering",
                        dlevel = 3)
                    sources.append(os.path.expanduser(tc_path_line))
        except OSError as e:
            tcfl.tc_global.report_blck(
                f"{manifest_file}: can't read manifes file: {e}", dlevel = 3)
            result.blocked += 1



class agent_c:
    """
    Discovery agent to find testcases

    Given a list of paths (in arguments or manifest files), this scans
    those paths for files that might describe one or more testcases
    each according to one or more testcase drivers.

    A testcase driver is a subclass of :class:`tcfl.tc_c` whose
    :meth:`is_testcase` method knows how to find testcases in a file
    and when found, returns a list of :class:`tc_info_c`
    instances. This allows testcases to be written in any language,
    framework, etc since the driver class provides the adaptation
    layer for it.

    The discovery process for each file is run on a separate
    subprocess (to shield the caller from crashes, extra imports,
    collisions between testcases, etc). When the subprocess finds a
    file implements one or more valid subcases, it queues a message to
    the agent with a list of :class:`tc_info_c` instances, each
    definiting a testcase (containing info such as name, what kind of
    targets is needs, what axis, tags, description, etc).

    (PENDING) the per-file process then becomes an execution server
    that on command from the orchestrator can spawn testcases for
    execution.

    """
    def __init__(self):
        #: Maximum number of discovery parallel processes we'll run at
        #: the same time.
        self.threads = 40
        #: Maximum number of seconds we'll wait for a discovery
        #: process to issue a result
        self.timeout = 30
        #: Time to wait before checking if discovery processes are
        #: done and we need to launch more.
        self.wait_period = 0.25
        self.manager = multiprocessing.Manager()
        # create this in the main process, on the forked one it does
        # not work
        self.queue = self.manager.Queue(maxsize = 1000)
        self.lock = self.manager.Lock()
        self.cvar = self.manager.Condition(self.lock)
        #: Number of testcases found
        self.tcis_count = 0
        #: Info about testcases found, indexed by file where found;
        #: #each entry is a list of :class:`tcfl.tc_info_c`
        self.tcis = {}
        self.result = tcfl.result_c()
        self.proc_by_filename = {}


    # FIXME: rename to discover_, make public
    filename_ignore_regexs = [
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


    def _process_find_in_file(self, path, subcase_spec):
        # RUNS IN A SEPARATE IMAGE
        # - makes main image inmune from random imports
        # - makes main image not susceptible to crashes from untrusted
        #   code
        # - OOM killer won't affect main image and we'll be able to
        #   track it

        orig_stderr = sys.stderr
        sys.stderr = sys.stdout = io.StringIO()

        pid = os.getpid()
        logger = log_sub.getChild(f"{path}[{pid}]" )
        tcis = collections.defaultdict(list)
        logger.info("scanning for subcases %s", subcase_spec)
        try:
            _create_from_file_name(tcis, path, path, subcase_spec,
                                   logger = logger)
            output = sys.stderr.getvalue()
            for path, tcil in tcis.items():
                for tci in tcil:
                    # we are just appending; the output of the
                    # discover process
                    if tci.output:
                        tci.output += "\n\n"
                    if output:
                        tci.output += "Discovery Process output:\n" + output
        except Exception as e:
            logger.error("scanning exception: %s", e, exc_info = True)
            # FIXME: send error code
            if hasattr(e, "origin"):
                origin = getattr(e, "origin")
            else:
                # FIXME: get from traceback, last item
                origin = None
            tcis[path] = [
                tcfl.tc_info_c(
                    path, path,
                    subcase_spec = subcase_spec,
                    origin = origin,
                    result = tcfl.result_c(blocked = 1),
                    output = "Discovery Process output:\n" + sys.stderr.getvalue(),
                    exception = e,
                    formatted_traceback = traceback.format_tb(sys.exc_info()[2])
                )
            ]
        logger.info("scanning found %d testcases", len(tcis))
        self.queue.put({ "discovery_result": tcis })


    def _find_in_file(self, path, subcase_spec):
        # Run this as subprocesses instead of a formal pool; WHY?
        #
        # - the subprocesses are free to import stuff, fork others, etc
        #   and won't affect the current running image
        #
        # - DO NOT USE A POOL: if they crash, the Pool gets stuck
        file_name = os.path.basename(path)
        for ignore_regex, origin in self.filename_ignore_regexs:
            if ignore_regex.match(file_name):
                log.log(6, "%s: ignored by regex %s [%s]",
                        file_name, ignore_regex.pattern, origin)
                self.result.skipped += 1
                return

        self.proc_by_filename[path] = None
        # NOTE we do not create p = commonl.fork_c() nor call
        # p.start() to run here; this is done by agent_c.run() to run
        # them in chunks (similar to a pool); otherwise we might have
        # 10000 processes being started. Not fun. We don't use a pool,
        # se above.


    def _find_in_directory(self, path, subcase_spec):
        # walk directory looking for valid files
        for tc_path, dirnames, filenames in os.walk(path):
            tcfl.tc_global.report_info(
                "%s: scanning directory" % path, dlevel = 5)
            keep_dirs = []
            # Skip directories we don't care about
            # NOTE: this works because os.walk will acknoledge changes to @dirnames
            for dirname in list(dirnames):
                for dir_ignore_regex, _origin in tcfl.tc_c._ignore_directory_regexs:
                    if dir_ignore_regex.match(dirname):
                        break
                else:
                    keep_dirs.append(dirname)
            del dirnames[:]
            dirnames.extend(keep_dirs)

            # we sort the file list so we always have consistent findind
            # order which is used later when allocating work in thdiffernt
            # nodes and generating test manifests
            for filename in sorted(filenames):
                self._find_in_file(os.path.join(tc_path, filename),
                                   subcase_spec)


    def _find_in_path(self, path, subcase_spec):
        # FIXME this should cache stuff so we don't have to rescan all the
        # times--if the ctime hasn't changed since our cache entry, then
        # we use the cached value
        result = tcfl.result_c(0, 0, 0, 0, 0)
        tcfl.tc_global.report_info(
            "%s: finding testcases in " % path, dlevel = 4)

        if os.path.isdir(path):
            self._find_in_directory(path, subcase_spec)
        elif os.path.isfile(path):
            self._find_in_file(path, subcase_spec)
        else:
            log.warning(f"{path}: invalid file type")
            result.blocked += 1

    def tcis_get_from_queue(self):
        tcis = {}
        while True:
            try:
                msg = self.queue.get(block = False, timeout = 1)
                if not isinstance(msg, dict):
                    log.error(
                        f"BUG: unknown message type {type(msg)}; expected dict")
                    continue
                for msg_k, msg_v in msg.items():
                    if msg_k == "discovery_result":
                        log.info(f"add from discovery_result {msg_v}")
                        tcis.update(msg_v)
                    else:
                        log.error(
                            f"BUG: unknown message type {type(msg)}")
            except queue.Empty as e:	# queue.get() will raise on empty
                break
        return tcis


    # COMPAT: removing list[str] so we work in python 3.8
    def run(self, paths: list, manifests: list = None,
            filter_spec = None, testcase_name = None):

        if manifests:
            commonl.assert_list_of_strings(manifests, "list of manifests",
                                           "manifest filename")
        else:
            manifests = []		# so we can iterate it and skip

        if len(paths) == 0 and len(manifests) == 0:
            log.warning("no testcases specified; searching in "
                        "current directory, %s", os.getcwd())
            paths = [ os.path.curdir ]

        self.result = tcfl.result_c()
        _manifest_expand(paths, self.result, manifests)

        tcfl.tc_global.report_info(f"scanning for test cases in {paths}", dlevel = 2)
        log.warning("scanning for test cases in %s", paths)

        # For each path to a file/directory we have found, peel off
        # subcase specifications and give it to drivers to see what we
        # find
        for path in paths:
            log.warning("%s: checking", path)
            # if a subcase has been specified (as TC,SUBTC1,SUBTC2,...or
            # as TC#SUBTC1#SUBTC2,...), extract them
            if ',' in path:
                parts = path.split(',')
                path = parts[0]
                subcase_spec = parts[1:]
                log.info("commandline '%s' requests subcases: %s",
                         path, " ".join(subcase_spec))
            elif '#' in path:
                parts = path.split('#')
                path = parts[0]
                subcase_spec = parts[1:]
                log.info("commandline '%s' requests subcases: %s",
                            path, " ".join(subcase_spec))
            else:
                subcase_spec = []
                log.info("commandline '%s' requests no subcases", path)
            if not os.path.exists(path):
                log.error("%s: does not exist; ignoring", path)
                continue
            # finding files (in the path) that might be testcases, does not
            # necessary loading them for operation

            self._find_in_path(path, subcase_spec)

        # ok, so now we have a bunch of proceses ready to start
        # scanning
        #
        # This is a loop that keeps running, launching processes
        # ensuring there are only N running at the same time (to keep
        # a tab on resources).
        procs = len(self.proc_by_filename)
        log.warning(f"discovering on {procs} files")

        while True:
            # This has to be more hardcore
            # We can't assume the process will notify, since if they
            # crash for whichever reason they won't. So this needs to
            # keep track of how many process have terminated, are
            # running and notify more to start as neeedd.
            pending = 0
            running = 0
            completed = 0

            pending_tcs = []
            for filename, p in list(self.proc_by_filename.items()):

                if p == None:		   # did it start?
                    pending += 1
                    pending_tcs.append(filename)
                    log.info(f"pending: {filename}")
                elif p == True:		# already completed, see next
                    completed += 1
                elif p.exitcode == 0:   # done properly
                    self.proc_by_filename[filename] = True
                    completed += 1
                    log.info(f"completed: {p.filename}")
                elif p.exitcode != None:   # done
                    self.proc_by_filename[filename] = True
                    completed += 1
                    log.error(f"{filename}: errored out")
                    self.tcis[filename] = [
                        tcfl.tc_info_c(
                            filename, filename,
                            origin = filename,
                            result = tcfl.result_c(blocked = 1),
                            exception = RuntimeError(
                                f"process failed with exitcode {p.exitcode}"),
                            formatted_traceback = traceback.format_stack(),
                        )
                    ]
                else:
                    log.info(f"currently running: {p.filename}")
                    running += 1
            log.warning(f"current loop {pending}/{running}/{completed}"
                        f" out of {procs}")

            if completed == procs:
                log.warning(f"all {procs} discovery processes done")
                break
            if running < self.threads and pending_tcs:
                # Fire up N of them; note the ones that are left as
                # servers don't count or the total max of threads we
                # can consider
                log.warning(
                    # FIXME: this message is complicated, reword
                    f"starting {self.threads - running}"
                    f" discoveries ({len(pending_tcs)},{pending} pending)")
                for _ in range(self.threads - running):
                    try:
                        filename = pending_tcs.pop()
                    except IndexError:
                        break
                    p = commonl.fork_c(self._process_find_in_file,
                                       filename, subcase_spec)
                    p.filename = filename
                    log.info(f"started: {filename}")
                    self.proc_by_filename[filename] = p
                    p.start()

            self.tcis.update(self.tcis_get_from_queue())
            log.warning(
                f"waiting {self.wait_period}s for"
                f" {pending=}/{running=}/{completed=}"
                f" discovery processes (out of {procs})")
            time.sleep(self.wait_period)


        # we are done launching all subprocesses that discover
        # testcases
        self.tcis.update(self.tcis_get_from_queue())	# flush the queue

        if len(self.tcis) == 0:
            log.error("WARNING! No testcases found")
            return

        # Filter based on their tags
        if False:
            _tcs_filter(tcs_filtered, result, tcs, filter_spec,
                        testcase_name = testcase_name)

        self.tcis_count = 0
        for path, v in self.tcis.items():
            self.tcis_count += len(v)



_subsystem_setup = False

def subsystem_setup(
        logdir: str = None,
        remove_tmpdir: bool = True,
        runid: str = "",
        tmpdir: str = "",
        *args, **kwargs):
    """
    Initialize the testcase discovery subsystem
    """
    # ensure discovery subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    # Minimum initialization of the logging infrastructure needed for
    # discovery and execution, since in some cases discovery will
    # yield something that looks like basic execution (eg: when
    # blocking, or skipping), so the reporting system must be up and
    # running to do discovey.

    # DO NOT USE tcfl.tc_global; since we init it at the end of this

    tcfl.tc_c.runid = runid
    # Where we place collateral
    # FIXME: replace tcfl.log_dir -> logdir for consistence
    if logdir == None or not logdir:
        tcfl.log_dir = os.getcwd()
    else:
        tcfl.log_dir = logdir
    try:
        commonl.makedirs_p(tcfl.log_dir)
    except OSError as e:
        logging.error(f"can't create collateral dir '{logdir}': {e}")
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

    _subsystem_setup = True
