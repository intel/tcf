#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Library of functions mainly useful for testing
==============================================
"""

import argparse
import atexit
import errno
import inspect
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import requests

import commonl
import tcfl.config
import tcfl.tc
import tcfl.ttb_client

def mkprefix(tag = None, cls = None):
    """
    Create a temporary file prefix PROGNAME:[CLASSNAME.]FUNCTION-TAG-

    :param str tag: a tag to append to the prefixb
    :param type cls: an optional type to prefix FUNCTION
    :returns: the prefix
    :rtype: str
    """
    assert isinstance(tag, str)
    if cls == None:
        cls_str = ""
    else:
        assert isinstance(cls, type)
        cls_str = cls.__name__ + "."
    frame = inspect.stack(0)[1][0]
    f_code = frame.f_code
    if tag != None:
        tag_str = "%s-" % tag
    else:
        tag_str = ""
    return os.path.basename(f_code.co_filename) \
        + "_" + cls_str \
        + f_code.co_name \
        + "-%s" % tag_str

def tmpfile_py_close(f):
    """
    Remove any .pyc compiled files associated to an open Python file.
    """
    assert hasattr(f, "name")
    try:
        # Remove the (python) compiled version of the config file
        os.unlink(f.name + "c")
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    f.close()

def ttbd_start(cmdline, url = None, timeout = 10,
               stdout_name = None, stderr_name = None):
    """
    Start the TTBD daemon
    """
    sp = commonl.subpython(cmdline,
                           stdout_name = stdout_name,
                           stderr_name = stderr_name)
    t = t0 = time.time()
    r = False
    time.sleep(0.5)
    while not r:
        if t - t0 > timeout:
            sp.output()
            sp.terminate_if_alive()
            raise Exception(
                "ttbd not ready after %d seconds: %s\n" % (timeout, cmdline) \
                + sp.output_str)
        if url != None:
            try:
                API_PREFIX = tcfl.ttb_client.rest_target_broker.API_PREFIX
                r = requests.get(url + API_PREFIX + 'validate_session')
                if r.status_code == 200:
                    break
            except requests.ConnectionError as e:
                # FIXME: need to use logger, but it is still not initialized?
                sys.stderr.write("W: %s\n" % e)
        time.sleep(1.5)
        t = time.time()
    # Check for errors in the configuration
    sp.flush()
    for line in sp.stderr:
        if line.startswith("E["):
            raise RuntimeError("ttbd has errors in the log\n" + sp.output())
    return sp

def logging_init(argv):
    """
    Spy on the -[qv],--{quiet,verbose} cmdline options to tell the
    verbosity level for our logging. Initialize logging.
    """
    import getopt
    verbosity = logging.ERROR
    lopts = [ 'verbose', 'quiet' ]
    try:
        opts, _ = getopt.getopt(argv[1:], 'qv', lopts)
        for opt, _ in opts:
            if opt in ('-q','--quiet'):
                verbosity = logging.CRITICAL
            if opt in ('-v','--verbose'):
                verbosity = commonl.logging_verbosity_inc(verbosity)
    except getopt.error:
        # We don't do anything, unittest will do for us
        pass

    logging.basicConfig(
        format = "%(levelname)s %(module)s[%(process)d].%(funcName)s():%(lineno)d: %(message)s",
        level = verbosity)

class test_tcf_mixin(object):
    """
    This class is used to create integration test cases that involve
    running a TCF client w/o TTBD daemon.

    To use, derive this class along with :class:`unittest.TestCase`::

      class test_run(unittest.TestCase, test_tcf_mixin):
          @classmethod
          def configfile(cls):
              return "CONFIG FILE TEXT"

          @classmethod
          def setUpClass(cls):
              test_tcf_mixin.setUpClass(cls.configfile())

          @classmethod
          def tearDownClass(cls):
               test_tcf_mixin.tearDownClass()

          def test_SOMETEST(self):
               ....

    """

    # Print our message on asserts and the original message from the lib
    longMessage = True

    @classmethod
    def setUpClass(cls,	# pylint: disable = dangerous-default-value
                   tcf_config_text = None,
                   tcf_config_files = []):
        """
        Prepare a TCF test

        - make a working directory (cls.wd)
        - make config directory (cls.tcf_etc_dir)
        - add config files (text and other files, if given)
        - change into working directory (cls.wd)

        then you can use tcf_args()

        :param str tcf_config_text: configuration text to add to a
           main TCF config file
        :param str tcf_config_files: list of (absolute) paths to more
           configuration files to consider for TCF. The will be copied
           to cls.tcf_etc_dir.
        """
        cls.wd = tempfile.mkdtemp(prefix = mkprefix("wd", cls = cls))
        os.chdir(cls.wd)
        cls.tcf_etc_dir = os.path.join(cls.wd, "tcf-etc")
        os.mkdir(cls.tcf_etc_dir)

        for fn in tcf_config_files:
            shutil.copy(fn, cls.tcf_etc_dir)

        cls.tcf_config = open(
            os.path.join(cls.tcf_etc_dir, "conf_00_base.py"), "w")
        if tcf_config_text:
            cls.tcf_config.write(tcf_config_text)
            cls.tcf_config.flush()
            cls.tcf_config.seek(0)

    @classmethod
    def tcf_args(cls):
        """
        Generate internal TCF args structure to call TCF subcommands
        directly instead of invoking the subcommand.
        """
        args = argparse.Namespace()
        args.dry_run = False
        args.tmpdir = None
        args.release = True
        args.ticket = None
        args.hash_salt = ""
        args.id = None
        args.log_dir = cls.wd
        args.log_file = os.path.join(cls.wd, "tcf.log")
        args.log_file_verbosity = 999
        args.all = False
        args.verbosity = 0
        args.quietosity = 1
        args.limited = True
        args.extra_report = None
        args.phases = []
        args.phases_skip = []
        args.manifest = []
        args.mode = 'one-per-type'
        args.testcase = []
        args.tags_spec = []
        args.repeat_evaluation = 1
        args.max_permutations = 10
        args.not_found_mismatch = False
        args.remove_tmpdir = True
        args.shard = None
        args.target = []
        args.threads = 10
        return args

    def _tcf_run_cut(self, cut = None, args_fn = None, filename = None,
                     testcase_name_postfix = ""):
        #
        # Given a Class Under Test representing a testcase, run it
        # through the test runner
        #
        if cut == None:
            # Class Under Test is named as this function with _ prefixed.
            # eval is evil, I know -- I'll be glad to find a best way
            # to get the name of the Class Under Test and map that to
            # self._CUT.
            cut = eval("self._" + inspect.stack()[1][3])	# pylint: disable = W0123
        args = self.tcf_args()
        if filename == None:
            args.testcase = [ self.src ]
            args.testcase_name = args.testcase[0] + "#" + cut.__name__
        else:
            args.testcase = [ filename ]
            args.testcase_name = filename + testcase_name_postfix
        self.cut = cut
        self.args = args
        if args_fn:
            args_fn(args)
        return tcfl.tc._run(args)	# pylint: disable = W0212


    def assert_in_file(self, f, regex, msg = None):
        """
        Raise an assertion with the given message if the regex is
        found in the file f.
        """
        if isinstance(regex, str):
            regex = re.compile(re.escape(regex))
        with open(f, "r") as f:
            for line in f:
                if regex.search(line):
                    return
            f.seek(0)
            if msg:
                self.fail(msg + "\n" + "%s: does not contain: %s\n%s"
                          % (f.name, regex.pattern,
                             "log: ".join(["\n"] + f.readlines())))
            else:
                self.fail("%s: does not contain: %s\n%s"
                          % (f.name, regex.pattern,
                             "log: ".join(["\n"] + f.readlines())))


    def assert_not_in_file(self, f, regex, msg = None):
        """
        Raise an assertion with the given message if the regex is
        NOT found in the file f.
        """
        if isinstance(regex, str):
            regex = re.compile(re.escape(regex))
        with open(f, "r") as f:
            for line in f:
                if regex.search(line):
                    f.seek(0)
                    if msg:
                        self.fail(msg + "\n" + "%s: contains: %s\n%s"
                                  % (f.name, regex.pattern,
                                     "log: ".join(["\n"] + f.readlines())))
                    else:
                        self.fail("%s: contains: %s\n%s"
                                  % (f.name, regex.pattern,
                                     "log: ".join(["\n"] + f.readlines())))

    def assert_in_tcf_log(self, regex, msg = None):
        """
        Raise an assertion with the given message if the regex is
        found in the TCF log file.
        """
        if msg == None:
            msg = self.cut.__doc__
        self.assert_in_file(self.args.log_file, regex, msg)

    def assert_not_in_tcf_log(self, regex, msg = None):
        """
        Raise an assertion with the given message if the regex is
        NOT found in the TCF log file.
        """
        if msg == None:
            msg = self.cut.__doc__
        self.assert_not_in_file(self.args.log_file, regex, msg)

    def tcf_log(self):
        """
        Return a single string with all the TCF log
        """
        r = ""
        with open(self.args.log_file) as f:
            for line in f:
                r += "tcf-log: " + line
        return r

    @classmethod
    def tearDownClass(cls):
        """
        Cleanup all the state of the client library
        """
        # FIXME: add flag to keep tempdir, print about it
        tcfl.ttb_client.rest_target_broker.rts_cache_flush()
        os.chdir(os.path.dirname(cls.wd))
        shutil.rmtree(cls.wd)

class test_ttbd_mixin(test_tcf_mixin):
    """
    This class is used to create integration test cases that involve
    running a TTBD daemon and launching a client against it.

    The setup methods are used to start and kill the daemon. Pass it a
    config file as text. Other config files will be ignore. Members
    *url*, *port* and  *wd*.

    Changes into a temporary working directory (class member *wd*);
    port is set at member *port*, URL at member *url*.

    To use, derive this class along with :class:`unittest.TestCase`::

      class test_run(unittest.TestCase, test_ttbd_mixin):
          @classmethod
          def configfile(cls):
              return "CONFIG FILE TEXT"

          @classmethod
          def setUpClass(cls):
              test_ttbd_mixin.setUpClass(cls.configfile())

          @classmethod
          def tearDownClass(cls):
               test_ttbd_mixin.tearDownClass()

          def test_SOMETEST(self):
               ....

    """

    # Print our message on asserts and the original message from the lib
    longMessage = True

    #: Exclude these strings from triggering an error message check
    exclude_errors = []

    #: Exclude these strings from triggering an warning message check
    exclude_warnings = [ 'daemon lacks CAP_NET_ADMIN' ]

    @classmethod
    def ttbd_info(cls):
        """
        Return a string with the daemon's configuration and it's
        stdout and stderr.
        """
        r = ""
        try:
            # In case we are called after completing the whole thing
            cls.ttbd_sp.flush()
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise

        if cls.ttbd_sp and cls.ttbd_sp.stderr_lines != []:
            r += "ttbd-stderr: ".join(["\n"] + cls.ttbd_sp.stderr_lines)
        if cls.ttbd_sp and cls.ttbd_sp.stdout_lines != []:
            r += "ttbd-stdout: ".join(['\n'] + cls.ttbd_sp.stdout_lines)
        # FIXME: the right fix here is to have *all* the config files
        # pasted here line by line before killing the temp dir so this
        # can be called after collecting everything
        try:
            r += "ttbd-config: ".join(
                ["\n"] + open(cls.ttbd_config.name).readlines())
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
        return r

    # pylint's disables: functions take naturally different arguments
    # and that's ok. On the default values, too bad, it makes the code
    # way easier. None is non iterable, [] is without having to add
    # extra code.
    @classmethod
    def setUpClass(cls,	# pylint: disable = arguments-differ, dangerous-default-value, too-many-arguments
                   config_text = None, use_ssl = False, ttbd_config_files = [],
                   tcf_config_text = None, tcf_config_files = []):
        test_tcf_mixin.setUpClass()

        srcdir = os.path.realpath(os.path.join(
            os.path.dirname(inspect.getsourcefile(cls)), ".."))
        cls.ttbd_etc_dir = os.path.join(cls.wd, "ttbd-etc")
        os.mkdir(cls.ttbd_etc_dir)
        cls.ttbd_files_dir = os.path.join(cls.wd, "ttbd-files")
        os.mkdir(cls.ttbd_files_dir)
        cls.ttbd_state_dir = os.path.join(cls.wd, "ttbd-state")
        os.mkdir(cls.ttbd_state_dir)

        for fn in ttbd_config_files:
            shutil.copy(fn, cls.ttbd_etc_dir)

        cls.ttbd_config = open(
            os.path.join(cls.ttbd_etc_dir, "conf_00_base.py"), "w")
        if config_text:
            cls.ttbd_config.write(config_text)
        cls.ttbd_config.flush()
        cls.ttbd_config.seek(0)	# So we can read it

        cls.port = commonl.tcp_port_assigner()
        # FIXME: establish a random port that is not used
        if use_ssl == True:
            cls.url = "https://localhost:%d" % cls.port
            ssl_context = ""
        else:
            cls.url = "http://localhost:%d" % cls.port
            ssl_context = "--no-ssl"
        try:
            # This allows us to default to the source location,when
            # running from source, or the installed when running from
            # the system
            ttbd_path = os.environ.get("TTBD_PATH", srcdir + "/ttbd/ttbd")
            cls.ttbd_sp = ttbd_start(
                ttbd_path + " --local-auth -vvvvv --host localhost "
                "%s --port %d --files-path %s --state-path %s "
                "--config-path %s "
                % (ssl_context, cls.port,
                   cls.ttbd_files_dir, cls.ttbd_files_dir,
                   cls.ttbd_etc_dir),
                url = cls.url,
                stdout_name = os.path.join(cls.wd, "ttbd-stdout.log"),
                stderr_name = os.path.join(cls.wd, "ttbd-stderr.log")
            )
        except Exception as e:
            logging.error(e)
            raise
        # Leave TCF client library ready to use with this server
        tcfl.ttb_client.rest_init(cls.ttbd_state_dir,
                                  cls.url, use_ssl, None)

    @classmethod
    def tearDownClass(cls):	# pylint: disable = too-many-branches
        cls.ttbd_sp.terminate_if_alive()
        r = cls.ttbd_sp.join()
        cls.ttbd_sp.flush()

        for line in cls.ttbd_sp.stderr_lines:
            if line.startswith("E[") or 'Error' in line:
                for exclude in cls.exclude_errors:
                    if hasattr(exclude, 'pattern'):
                        if exclude.search(line):
                            break
                    elif exclude in line:
                        break
                else:
                    raise RuntimeError("ttbd has errors in the log\n"
                                       + cls.ttbd_info())
            if line.startswith("W["):
                for exclude in cls.exclude_warnings:
                    if exclude in line:
                        break
                else:
                    sys.stderr.write("WARNING! ttbd has warnings in the log\n"
                                     + cls.ttbd_info())
            if 'FIXME' in line:
                sys.stderr.write("WARNING! ttbd has FIXMEs in the log\n"
                                 + cls.ttbd_info())
            if 'DEBUG' in line:
                sys.stderr.write("WARNING! ttbd has DEBUGs in the log\n"
                                 + cls.ttbd_info())

        tmpfile_py_close(cls.ttbd_config)
        if r != -signal.SIGTERM:
            logging.error(cls.ttbd_info())
            test_tcf_mixin.tearDownClass()
            raise Exception(
                "exit code %d != -SIGTERM\n" % r)
        else:
            test_tcf_mixin.tearDownClass()

class test_ttbd(object):
    """
    This class is used to launch a daemon with an specific
    configuration for testing, with all the stuff placed in temporary
    directories where later we can capture it.

    The setup methods are used to start and kill the daemon. Config
    files can be passed as text or as pointers to config files in disk
    that will be read.
    Members *url*, *port* and  *wd*.

    A single run of TCF with unit test will start many of these
    servers, each for a single testcase--they key is that the targets
    they request must be filtered to start with :attr:`url_spec`
    with:

    >>> ttbd = test_ttbd(etc etc)
    >>> print ttbd.url_spec
    >>> url:'^%s' ... etc
    >>> ...
    >>> @tcfl.tc.targets(ttbd.url_spec + " and OTHERs " % ttbd.url)
    """
    # FIXME:
    #  - Use tc_c.tmpdir
    #  - aka name shall be a hash of the config files, so it is
    #    constant upon invocations and the report hashes too
    #
    def __init__(self, config_text = None, config_files = None,
                 use_ssl = False, tmpdir = None, keep_temp = True,
                 errors_ignore = None, warnings_ignore = None,
                 aka = None, local_auth = True):

        # Force all assertions, when running like this, to fail the TC
        tcfl.tc.tc_c.exception_to_result[AssertionError] = tcfl.tc.failed_e

        # If no aka is defined, we make one out of the place when this
        # object is being created, so it is always the same *and* thus
        # the report hashes are always identical with each run

        if aka == None:
            self.aka = "ttbd-" + commonl.mkid(commonl.origin_get(2), 4)
        else:
            self.aka = aka
        if config_files == None:
            config_files = []
        self.keep_temp = keep_temp
        self.port = commonl.tcp_port_assigner()
        self.use_ssl = use_ssl
        if use_ssl == True:
            self.url = "https://localhost:%d" % self.port
            ssl_context = ""
        else:
            self.url = "http://localhost:%d" % self.port
            ssl_context = "--no-ssl"
        self.url_spec = "fullid:'^%s'" % self.aka
        if tmpdir:
            self.tmpdir = tmpdir
        else:
            # default to place the server's dir in the tempdir for
            # testcases
            self.tmpdir = os.path.join(tcfl.tc.tc_c.tmpdir, "server", self.aka)
        shutil.rmtree(self.tmpdir, ignore_errors = True)
        commonl.makedirs_p(self.tmpdir)

        self.etc_dir = os.path.join(self.tmpdir, "etc")
        self.files_dir = os.path.join(self.tmpdir, "files")
        self.lib_dir = os.path.join(self.tmpdir, "lib")
        self.state_dir = os.path.join(self.tmpdir, "state")
        os.mkdir(self.etc_dir)
        os.mkdir(self.files_dir)
        os.mkdir(self.lib_dir)
        os.mkdir(self.state_dir)
        self.stdout = self.tmpdir + "/stdout"
        self.stderr = self.tmpdir + "/stderr"

        for fn in config_files:
            shutil.copy(fn, self.etc_dir)

        with open(os.path.join(self.etc_dir,
                               "conf_00_base.py"), "w") as cfgf:
            cfgf.write(r"""
import ttbl.config
ttbl.config.processes = 2
host = '127.0.0.1'
""")
            # We don't define here the port, so we see it in the
            # command line
            if config_text:
                cfgf.write(config_text)

        self.srcdir = os.path.realpath(
            os.path.join(os.path.dirname(__file__), ".."))
        self.cmdline = [
            "stdbuf", "-o0", "-e0",
            # This allows us to default to the source location,when
            # running from source, or the installed when running from
            # the system
            os.environ.get("TTBD_PATH", self.srcdir + "/ttbd/ttbd"),
            "--port", "%d" % self.port,
            ssl_context,
            "-vvvvv",
            "--files-path", self.files_dir,
            "--state-path", self.state_dir,
            "--config-path", "", # This empty one is to clear them all
            "--config-path", self.etc_dir
        ]
        self.local_auth = local_auth
        if local_auth:
            self.cmdline.append("--local-auth")
        self.p = None
        #: Exclude these regexes / strings from triggering an error
        #: message check
        self.errors_ignore = [] if errors_ignore == None else errors_ignore

        #: Exclude these regexes / strings from triggering an warning
        #: message check
        self.warnings_ignore = [ re.compile('daemon lacks CAP_NET_ADMIN') ]
        if warnings_ignore:
            self.warnings_ignore += warnings_ignore

        def _preexec_fn():
            stdout_fd = os.open(self.stdout,
                                # O_CREAT: Always a new file, so
                                # we can check for errors and not
                                # get confused with previous runs
                                os.O_WRONLY | os.O_EXCL |os.O_CREAT, 0o0644)
            stderr_fd = os.open(self.stderr,
                                # O_CREAT: Always a new file, so
                                # we can check for errors and not
                                # get confused with previous runs
                                os.O_WRONLY | os.O_EXCL |os.O_CREAT, 0o0644)
            os.dup2(stdout_fd, 1)
            os.dup2(stderr_fd, 2)

        logging.info("Launching: %s", " ".join(self.cmdline))
        self.p = subprocess.Popen(
            self.cmdline, shell = False, cwd = self.tmpdir,
            close_fds = True, preexec_fn = _preexec_fn,
            bufsize = 0)
        try:
            self._check_if_alive()
        finally:
            self.check_log_for_issues()
        # if we call self.terminate() from __del__, the garbage
        # collector has started to wipe things, so we can't use, ie:
        # open() to check the log file
        atexit.register(self.terminate)

    def _check_if_alive(self):
        timeout = 5
        t0 = time.time()
        time.sleep(0.25)
        while True:
            t = time.time()
            if t - t0 > timeout:
                self.terminate()
                raise RuntimeError(
                    "ttbd:%d not ready after %d seconds: %s\n"
                    % (self.port, timeout, " ".join(self.cmdline)))
            try:
                # This is where we register this new server with the
                # client, by putting it in the cache (so no
                # tcfl.config is touched for it).
                rtb = tcfl.ttb_client.rest_init(self.state_dir,
                                                self.url, not self.use_ssl,
                                                self.aka)
                # FIXME: these are still being unified
                self.server = tcfl.server_c(
                    url = self.url, aka = self.aka,
                    ssl_verify = self.use_ssl,
                    origin = "unit test run")
                tcfl.server_c.servers[self.server.url] = self.server
                self.server.setup()
                # let's see if we get the basic ttb endpoint working
                #
                # meaning the server is up and running
                try:
                    r = rtb.send_request("GET", "ttb", skip_prefix = True)
                    break
                except requests.HTTPError as e:
                    raise RuntimeError(
                        f"server {self.url} does not respond to /ttb") from e
                break
            except (requests.ConnectionError, ValueError) as e:
                # FIXME: need to use logger, but it is still not initialized?
                logging.warning("ttbd:%d: retrying connection because %s",
                                self.port, e)
                time.sleep(0.25)

    # Don't make these too generic or they will bounce all the time
    bad_strings = [
        # marker for an exception
        r"Traceback (most recent call last):",
        r"DEBUG",
        r"FIXME",
    ]
    error_regex = re.compile("(error|Error)")
    warning_regex = re.compile("(warning|Warning)")
    def _check_log_line_for_issues(self, line):
        line = line.strip()
        for bad_string in self.bad_strings:
            if bad_string in line:
                for exclude in self.errors_ignore + self.warnings_ignore:
                    if isinstance(exclude, re.Pattern):
                        if exclude.search(line):
                            return False
                    elif exclude in line:
                        return False
                return True
        if self.error_regex.search(line):
            for exclude in self.errors_ignore:
                if isinstance(exclude, re.Pattern):
                    if exclude.search(line):
                        return False
                elif exclude in line:
                    return False
            return True
        if self.warning_regex.search(line):
            for exclude in self.warnings_ignore:
                if isinstance(exclude, type(self.warning_regex)):
                    if exclude.search(line):
                        return False
                elif exclude in line:
                    return False
            return True

    def _log_report(self, fd, fd_name, issues, testcase):
        if testcase:
            raise tcfl.tc.error_e(
                "issues found on server's " + fd_name,
                {
                    "lines": " ".join(issues),
                    "server-" + fd_name :
                        commonl.generator_factory_c(open, fd.name)
                })
        else:
            print("issues found on server's %s: %s" \
                % (fd_name, " ".join(issues)), file=sys.stderr)
            fd.seek(0, 0)
            count = 0
            for line in fd:
                print("  %d: %s" % (count, line), file=sys.stderr, end = "")
                count += 1

    def check_log_for_issues(self, testcase = None):
        """
        Read the current log file from the TTBD daemon and raise an
        exception if any line reports a warning or error.

        Note any line that matches :attr:`warnings_ignore` or
        :attr:`errors_ignore` won't trigger said exception.
        """
        try:
            issues = []
            if os.path.isfile(self.stdout):
                with open(self.stdout) as stdout:
                    cnt = 0
                    for line in stdout:
                        if self._check_log_line_for_issues(line):
                            issues.append(str(cnt))
                        cnt += 1
                    if issues:
                        self._log_report(stdout, "stdout", issues, testcase)

            issues = []
            if os.path.isfile(self.stderr):
                with open(self.stderr) as stderr:
                    cnt = 0
                    for line in stderr:
                        if self._check_log_line_for_issues(line):
                            issues.append(str(cnt))
                        cnt += 1
                    if issues:
                        self._log_report(stderr, "stderr", issues, testcase)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            # ignore otherwise, this means we deleted the directory
            # already, the daemon had been already terminated

    def local_auth_disable(self):
        """
        Disable local authentication, to be able to test
        authentication

        The server is normally configured with local authentication
        enabled, so we can query and interact with it without having
        to login first.

        But then this makes it impossible to test login/logout, as
        there is always a valid local user.

        Call this at the beginning of a testcase that deals with
        authentication after the core has been able to query
        targets, etc to switch that off.

        .. warning:: THIS WILL AFFECT all uses of this test daemon instance
        """
        with open(os.path.join(self.lib_dir,
                               "local_auth_disabled"), "w") as wf:
            wf.write("")


    def terminate(self):
        """
        Terminate the TTBD daemon, cleaning up after it.
        """
        self.p.poll()
        if self.p.pid:
            # Use negative, so we also kill child processes of a setsid
            try:
                os.kill(-self.p.pid, signal.SIGTERM)
                time.sleep(1)	# give it time to flush
                os.kill(-self.p.pid, signal.SIGKILL)
            except OSError:	# Most cases, already dead
                pass
        try:
            self.check_log_for_issues()
        except IOError as e:
            if e.errno != errno.ENOENT:
                # tmpdir has been removed, ignore
                raise
        if not self.keep_temp:
            shutil.rmtree(self.tmpdir, ignore_errors = True)
        else:
            logging.warning("keeping TTBD #%s temporary directory @ %s\n",
                            self.port, self.tmpdir)
        # remove cache entry for this temporary server
        self.server.cache_wipe()


class shell_client_base(tcfl.tc.tc_c):
    """
    Base template for a testcase that uses the *tcf* command line client

    This is basically for running things such as:

    - *tcf do-this ...*
    - *tcf do-that ...*

    Makes it easy to generate the TCF client configuration and the
    command line to run it with :meth:`mk_tcf_config` and
    :meth:`tcf_cmdline`. e.g.:

    .. code-block:: python

       import commonl.testing

       class _test(commonl.testing.shell_client_base):

           def eval_00(self):
               self.ttbd = ttbd
               self.mk_tcf_config()

               self.run_local(self.tcf_cmdline() +
                              " login -p bad_password user1 || true",
                              "user user1: not allowed")
               self.report_pass("user1 can't login with a bad password")

    Tricks

    - to serialize access to a resource, use a target to run on as a
      decorator to a class:

      >>> @tcfl.tc.target(ttbd.aka + '/tg_req_c1')

    """

    #: instance of the test server to run against; must be set in some
    #: test method before calling :meth:`mk_tcf_config` or
    #: :meth:`tcf_cmdline`.
    ttbd = None	# NEEDs to be set once instantiated

    def mk_tcf_config(self, conf_file_name = "conf.py"):
        """
        Generate a configuration file that points to the test server
        """
        with open(os.path.join(self.tmpdir, conf_file_name), "w") as cf:
            cf.write(
                'tcfl.config.url_add("%s", aka = "local", ssl_ignore = True)'
                % self.ttbd.url)

    def tcf_cmdline(self):
        """
        Generate the basic command line that will run against the test
        server.
        """
        return self.ttbd.srcdir + "/tcf --state-path . -p: -c conf.py"

    def teardown_90_scb(self):
        """
        Check the server's log for errors
        """
        self.ttbd.check_log_for_issues(self)
