#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Original by Andrew Boie, Inaky did the final integration
#
"""
Zephyr's SanityCheck testcase.ini driver for testcase integration
-----------------------------------------------------------------

This implements a driver to run Zephyr's Sanity Check testcases
(described with a testcase.ini file) without having to implement any
new descriptions. Details are explained in
:class:`tc_zephyr_sanity_c`.

"""
import codecs
import collections
import ConfigParser
import contextlib
import copy
import errno
import glob
import inspect
import logging
import mmap
import os
import pprint
import re
import subprocess
import threading
import traceback

# Needed so I can also import from tc to initialize -- ugly
import commonl.expr_parser
import expecter
import tcfl
import tc
import tc_zephyr_scl

from . import msgid_c

logger = logging.getLogger("tcfl.tc_zephyr_sanity")

class ConfigurationError(Exception):
    pass

arch_valid_keys = {"name" : {"type" : "str", "required" : True},
                   "platforms" : {"type" : "list", "required" : True}}

platform_valid_keys = {
    "qemu_support" : { "type" : "bool", "default" : False },
    "microkernel_support" : {
        "type" : "bool",
        "default" : True
    }
}

# testcase_valid_keys and SanityConfigParser taken verbatim from the
# Zephyr sanitycheck code
testcase_valid_keys = {
    "arch_exclude": {"type": "set"},
    "arch_whitelist": {"type": "set"},
    "build_on_all": {"type": "bool", "default": False},
    "build_only": {"type": "bool", "default": False},
    "depends_on": {"type": "set"},
    "extra_args": {"type": "list"},
    "extra_configs": {"type": "list"},
    "extra_sections": {"type": "list", "default": []},
    "filter": {"type": "str"},
    "harness": {"type": "str"},
    "harness_config": {"type": "map", "default": {}},
    "min_flash": {"type": "int", "default": 32},
    "min_ram": {"type": "int", "default": 8},
    "platform_exclude": {"type": "set"},
    "platform_whitelist": {"type": "set"},
    "skip": {"type": "bool", "default": False},
    "slow": {"type": "bool", "default": False},
    "tags": {"type": "set", "required": False},
    "timeout": {"type": "int", "default": 60},
    "toolchain_exclude": {"type": "set"},
    "toolchain_whitelist": {"type": "set"},
    "type": {"type": "str", "default": "integration"},

    # old version support
    "config_whitelist" : {"type" : "set"},
    "hw_requires" : {"type" : "set"},
    "kernel" : {"type": "str", "required" : False},

}


class SanityConfigParser:
    """
    Class to read architecture and test case .ini files with semantic
    checking

    This is only used for the old, .ini support
    """
    def __init__(self, filename):
        """Instantiate a new SanityConfigParser object

        :param str filename: Source .ini file to read
        """
        cp = ConfigParser.SafeConfigParser()
        cp.readfp(open(filename))
        self.filename = filename
        self.cp = cp

    def _cast_value(self, value, typestr):
        v = value.strip()
        if typestr == "str":
            return v

        elif typestr == "float":
            return float(v)

        elif typestr == "int":
            return int(v)

        elif typestr == "bool":
            v = v.lower()
            if v == "true" or v == "1":
                return True
            elif v == "" or v == "false" or v == "0":
                return False
            raise ConfigurationError(self.filename,
                                     "bad value for boolean: '%s'" % value)

        elif typestr.startswith("list"):
            vs = v.split()
            if len(typestr) > 4 and typestr[4] == ":":
                return [self._cast_value(vsi, typestr[5:]) for vsi in vs]
            else:
                return vs

        elif typestr.startswith("set"):
            vs = v.split()
            if len(typestr) > 3 and typestr[3] == ":":
                return set([self._cast_value(vsi, typestr[4:]) for vsi in vs])
            else:
                return set(vs)
        elif typestr.startswith("map"):
            return value
        else:
            raise ConfigurationError(self.filename, "unknown type '%s'"
                                     % typestr)


    def sections(self):
        """Get the set of sections within the .ini file

        :returns: a list of string section names"""
        return self.cp.sections()

    def get_section(self, section, valid_keys):
        """Get a dictionary representing the keys/values within a section

        :param str section: The section in the .ini file to retrieve data from

        :param dict valid_keys: A dictionary representing the intended
            semantics for this section. Each key in this dictionary is
            a key that could be specified, if a key is given in the
            .ini file which isn't in here, it will generate an
            error. Each value in this dictionary is another dictionary
            containing metadata:

                "default" - Default value if not given

                "type" - Data type to convert the text value to. Simple types
                    supported are "str", "float", "int", "bool" which will get
                    converted to respective Python data types. "set" and "list"
                    may also be specified which will split the value by
                    whitespace (but keep the elements as strings). finally,
                    "list:<type>" and "set:<type>" may be given which will
                    perform a type conversion after splitting the value up.

                "required" - If true, raise an error if not defined. If false
                    and "default" isn't specified, a type conversion will be
                    done on an empty string

        :returns: A dictionary containing the section key-value pairs with
            type conversion and default values filled in per valid_keys
        """

        d = {}
        cp = self.cp

        if not cp.has_section(section):
            raise ConfigurationError(self.filename,
                                     "Missing section '%s'" % section)

        for k, v in cp.items(section):
            if k not in valid_keys:
                raise ConfigurationError(
                    self.filename,
                    "Unknown config key '%s' in definition for '%s'"
                    % (k, section))
            d[k] = v

        for k, kinfo in valid_keys.items():
            if k not in d:
                if "required" in kinfo:
                    required = kinfo["required"]
                else:
                    required = False

                if required:
                    raise ConfigurationError(
                        self.filename,
                        "missing required value for '%s' in section '%s'"
                        % (k, section))
                else:
                    if "default" in kinfo:
                        default = kinfo["default"]
                    else:
                        default = self._cast_value("", kinfo["type"])
                    d[k] = default
            else:
                try:
                    d[k] = self._cast_value(d[k], kinfo["type"])
                except ValueError:
                    raise ConfigurationError(
                        self.filename,
                        "bad %s value '%s' for key '%s' in section '%s'"
                        % (kinfo["type"], d[k], k, section))

        return d

class harness_c(object):	# pylint: disable = too-few-public-methods
    """A test harness for a Zephyr test

    In the Zephyr SanityCheck environment, a harness is a set of steps
    to verify that a testcase did the right thing.

    The default harness just verifies if *PROJECT EXECUTION FAILED* or
    *PROJECT EXECUTION SUCCESFUL*  was printed (which is done in
    :meth:`tc_zephyr_sanity_c.eval_50`).

    However, if a harness is specified in the testcase/sample YAML
    with::

      harness: HARNESSNAME
      harness_config:
        field1: value1
        field2: value2
        ...

    then *tc_zephyr_sanity_c._dict_init()* will create a harness
    object of class *_harness_HARNESSNAME_c* and set it to
    :data:`tc_zephyr_sanity_c.harness`. Then, during the evaluation
    phase, we'll run it in :meth:`tc_zephyr_sanity_c.eval_50`.

    The harness object has :meth:`evaluate` which is called to
    implement the harness on the testcase and target it is running
    on.

    For each type of harness, there is a class for it implementing the
    details of it.
    """
    def evaluate(self, _testcase):	# pylint: disable = missing-docstring
        pass

class _harness_console_c(harness_c):	# pylint: disable = too-few-public-methods
    """
    Implement the Zephyr console harness

    Given a list of regexs which have to be received
    ordered/unordered a number of times.
    """
    def __init__(self, ordered, repeat, regexs):
        assert isinstance(ordered, bool)
        assert repeat > 0
        assert all([ isinstance(regex, basestring)
                     for regex in regexs ])
        harness_c.__init__(self)
        self.repeat = repeat
        self.ordered = ordered
        self.regexs = [ re.compile(regex) for regex in regexs ]

    def _evaluate_ordered(self, testcase):
        target = testcase.targets['target']
        for regex in self.regexs:
            target.expect(regex)

    def _evaluate_unordered(self, testcase):
        target = testcase.targets['target']
        for regex in self.regexs:
            target.on_console_rx(regex)
        testcase.tls.expecter.run()

    def evaluate(self, testcase):
        if self.repeat == 1:
            if self.ordered:
                self._evaluate_ordered(testcase)
            else:
                self._evaluate_unordered(testcase)
        else:
            for count in range(1, self.repeat + 1):
                with msgid_c("R#%d" % (count + 1)):
                    if self.ordered:
                        self._evaluate_ordered(testcase)
                    else:
                        self._evaluate_unordered(testcase)


#
# Subtestcase scanning
#
# We use this part to scan the source of a ztest Zephyr testcase for
# what are the possible subtestcases we need to work for
#
# The format of this in the source is formalized in FIXME, so we look
# for a C file that includes ztest.h and then declares the
# ztest_test_suite, pulling them from that list.
#
# We have now a list of subtestcases; when we execute the testcase,
# we'll parse the output and expect to see each of them executed with
# either PASS/FAILED. If we find an unexpected test case or an
# expected testcase is not run, we'll BLOCK it.

suite_regex = re.compile(
    # do not match until end-of-line, otherwise we won't allow
    # stc_regex below to catch the ones that are declared in the same
    # line--as we only search starting the end of this match
    r"^\s*ztest_test_suite\(\s*(?P<suite_name>[a-zA-Z0-9_]+)\s*,",
    re.MULTILINE)
# This has to catch multiple forms of:
#
# ztest_test_suite(TESTNAME,
#                  ztest_unit_test(NAME),
#                  ztest_user_unit_test(NAME),
#                  ztest_unit_test_setup_teardown(NAME, FN1, FN2)
# );
# We care for extracting the NAMEs
stc_regex = re.compile(
    r"^\s*"		# empy space at the beginning is ok
    # catch the case where it is declared in the same sentence, e.g:
    #
    # ztest_test_suite(mutex_complex, ztest_user_unit_test(TESTNAME));
    r"(?:ztest_test_suite\([a-zA-Z0-9_]+,\s*)?"
    # Catch ztest[_user]_unit_test-[_setup_teardown](TESTNAME)
    r"ztest_(?:user_)?unit_test(?:_setup_teardown)?"
    # Consume the argument that becomes the extra testcse
    r"\(\s*"
    r"(?P<stc_name>[a-zA-Z0-9_]+)"
    # _setup_teardown() variant has two extra arguments that we ignore
    r"(?:\s*,\s*[a-zA-Z0-9_]+\s*,\s*[a-zA-Z0-9_]+)?"
    r"\s*\)",
    # We don't check how it finishes; we don't care
    re.MULTILINE)
suite_run_regex = re.compile(
    r"^\s*ztest_run_test_suite\((?P<suite_name>[a-zA-Z0-9_]+)\)",
    re.MULTILINE)
achtung_regex = re.compile(
    r"(#ifdef|#endif)",
    re.MULTILINE)

def _stc_scan_file(inf_name):
    warnings = None

    with open(inf_name) as inf:
        with contextlib.closing(mmap.mmap(inf.fileno(), 0, mmap.MAP_PRIVATE,
                                          mmap.PROT_READ, 0)) as main_c:
            suite_regex_match = suite_regex.search(main_c)
            if not suite_regex_match:
                # can't find ztest_test_suite
                return None, None

            suite_run_match = suite_run_regex.search(main_c)
            if not suite_run_match:
                raise ValueError("can't find ztest_run_test_suite")

            # pylint: disable = unsubscriptable-object
            achtung_matches = re.findall(
                achtung_regex,
                main_c[suite_regex_match.end():suite_run_match.start()])
            if achtung_matches:
                warnings = "found invalid %s in ztest_test_suite()" \
                           % ", ".join(set(achtung_matches))
            # pylint: disable = unsubscriptable-object
            _matches = re.findall(
                stc_regex,
                main_c[suite_regex_match.end():suite_run_match.start()])
            matches = [ match.replace("test_", "") for match in _matches ]
            return matches, warnings

def _stc_scan_path_source(path):
    subcases = []
    warnings = []
    for filename in \
        glob.glob(os.path.join(path, "src", "*.c"))  \
        + glob.glob(os.path.join(path, "*.c")):		# old style unit tests
        _subcases, _warnings = _stc_scan_file(filename)
        if warnings:
            warnings.append(_warnings)
        if _subcases:
            subcases += _subcases
    return subcases, warnings,

class tc_zephyr_subsanity_c(tc.tc_c):
    """Subtestcase of a Zephyr Sanity Check

    A Zephyr Sanity Check testcase might be composed of one or more
    subtestcases.

    We run them all in a single shot using :class:`tc_zephyr_sanity_c`
    and when done, we parse the output
    (tc_zephyr_sanity_c._subtestcases_grok) and for each subtestcase,
    we create one of this sub testcase objects and queue it to be
    executed in the same target where the main testcase was ran.

    This is only a construct to ensure they are reported as separate
    testcases. We already know if they passed or errored or failed, so
    all we do is report as such.

    """
    # in terms of attachments, attachment 'description' is a one liner
    # used to give more information in the eval
    # pass/errr/fail/block/skip line.
    def __init__(self, name, tc_file_path, origin,
                 zephyr_name, parent, attachments = None):
        assert isinstance(name, basestring)
        assert isinstance(tc_file_path, basestring)
        assert isinstance(origin, basestring)
        assert isinstance(zephyr_name, basestring)
        assert isinstance(parent, tcfl.tc.tc_c)
        assert not attachments or isinstance(attachments, dict)

        tc.tc_c.__init__(self, name, tc_file_path, origin)
        self.parent = parent
        self.attachments = attachments if attachments else {}
        # This is to be left uninitialized so if it is when we are
        # evaluating, we'll take it from the parent testcase. So if it
        # errored/failed/skip/block to configure, build, deploy etc,
        # all the subTCs are errored/failed/skipped/blocked
        self._result = None
        self.kw_set('tc_name_short', zephyr_name)

    def configure_50(self):	# pylint: disable = # missing-docstring
	# we don't need to manipulate the targets, so don't assign;
        # will be faster -- do it like this so we can use the same
        # class for normal sanity check testcases that require a
        # target and unit test cases that don't.
        for target in self.targets.values():
            target.acquire = False
        self.report_pass("NOTE: This is a subtestcase of %(tc_name)s "
                         "(%(runid)s:%(tc_hash)s); refer to it for full "
                         "information" % self.parent.kws, dlevel = 1)

    def eval_50(self):
        if self._result == None:
            result = self.parent.result
            # inherit from parent, as no result has been determined yet
            if result.failed:
                self._result = "FAIL"
            elif result.errors:
                self._result = "ERRR"
            elif result.blocked:
                self._result = "BLCK"
            elif result.skipped:
                self._result = "SKIP"
            else:
                self._result = "PASS"
        for target_want_name, target in self.targets.iteritems():
            self.attachments[target_want_name] = target
        if 'description' in self.attachments:
            append = ": " + self.attachments['description']
        else:
            append = ""
        if self._result == 'PASS':
            raise tcfl.tc.pass_e("subtestcase passed" + append,
                                 self.attachments)
        elif self._result == 'FAIL':
            raise tcfl.tc.failed_e("subtestcase failed" + append,
                                   self.attachments)
        elif self._result == 'ERRR':
            raise tcfl.tc.error_e("subtestcase errored" + append,
                                  self.attachments)
        elif self._result == 'BLCK':
            raise tcfl.tc.blocked_e("subtestcase blocked" + append,
                                    self.attachments)
        elif self._result == 'SKIP':
            raise tcfl.tc.skip_e("subtestcase skipped" + append,
                                 self.attachments)
        else:
            raise AssertionError("unknown result %s" % self._result)

    @staticmethod
    def clean():
        # Nothing to do, but do it anyway so the accounting doesn't
        # complain that nothing was found to run
        return

class tc_zephyr_sanity_c(tc.tc_c):
    """
    Test case driver specific to Zephyr project testcases

    This will generate test actions based on Zephyr project testcase.ini
    files.

    See Zephyr sanitycheck --help for details on the format on these
    testcase configuration files. A single testcase.ini may specify
    one or more test cases.

    This rides on top of :py:class:`tcfl.tc.tc_c` driver; tags are
    translated, whitelist/excludes are translated to target selection
    language and and a single target is declared (for cases that are
    not unit tests).

    :meth:`is_testcase` looks for ``testcase.ini`` files, parses up
    using :class:`SanityConfigParser` to load it up into memory and
    calls ``_dict_init()`` to set values and generate the target
    (when needed) and setup the App Zephyr builder.

    This is how we map the different testcase.ini sections/concepts to
    :py:class:`tcfl.tc.tc_c` data:

    - ``extra_args = VALUES``: handled as ``app_zephyr_options``,
      passed to the Zephyr App Builder.

    - ``extra_configs = LIST``: list of extra configuration settings

    - testcase source is assumed to be in the same directory as the
      ``testcase.ini`` file. Passed to the Zephyr App Builder with
      ``app_zephyr``.

    - ``timeout = VALUE``: use to set the timeout in the testcase
      expect loop.

    - ``tags = TAGS``: added to the tags list, with an origin

    - ``skip``: skipped right away with an :py:exc:`tcfl.tc.skip_e` exception

    - ``slow``: coverted to tag

    - ``build_only``: added as ``self.build_only``

    - ``(arch,platform)_(whitelist,exclude)``: what testcase.ini calls
      `arch` is a `bsp` in TCF parlance and `platform` maps to the
      `zerphyr_board` parameter the Zephyr test targets export on their BSP
      specific tags. Thus, our spec becomes something like::

        bsp == "ARCH1' or bsp == "ARCH2" ) and not ( bsp == "ARCH3" or bsp == "ARCH4")

      * ``arch_whitelist = ARCH1 ARCH2`` mapped to
        ``@targets += bsp:^(ARCH1|ARCH2)$``
      * ``arch_exclude = ARCH1 ARCH2`` mapped to
        ``@targets += bsp:(?!^(ARCH1|ARCH2)$)``
      * ``platform_whitelist = PLAT1 PLAT2`` mapped to
        ``@targets += board:^(PLAT1|PLAT2)$``
      * ``platform_exclude = PLAT1 PLAT2`` mapped to
        ``@targets += board:(?!^(PLAT1|PLAT2)$)``
      * ``config_whitelist`` and ``filter``: filled into the args
        stored in the testcase as which then gets passed as part of
        the kws[config_whitelist] dictionary... The build process then
        calls the action_eval_skip() method to test if the TC has to
        be skipped after creating the base config.

    """
    def __init__(self, name, tc_file_path, origin, zephyr_name, subcases):
        tc.tc_c.__init__(self, name, tc_file_path, origin)
        # app_zephyr will have inserted methods to build, cleanup, setup
        # Force hooks to be run by app_zephyr's setup
        self.unit_test = False
        self.sanity_check = True
        self.extra_args = ""
        self.extra_configs = []
        self.app_src = None
        # Naming: for TCF, our name is our path#sectionname, but for
        # Zephyr, we are just sectioname, so for the benefit of
        # reporting, let's generate that
        self.kw_set('tc_name_short', zephyr_name)
        self.zephyr_filter = None
        self.zephyr_filter_origin = None
        #: Harness to run
        self.harness = None
        self.subcases = subcases
        #: Subtestcases that are identified as part of this (possibly)
        #: a container testcase.
        self.subtestcases = dict()
        #: Filename of the output of the unit test case; when we run a
        #: unit testcase, the output does not come from the console
        #: system, as it runs local, but from a local file.
        self.unit_test_output = None
        self.zephyr_depends_on = []

    @classmethod
    def __sanity_check_list_tests(cls, path):
        ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE',
                                     "__ZEPHYR_BASE_not_defined__")
        sanity_check = os.path.join(ZEPHYR_BASE, 'scripts', 'sanitycheck')
        env = dict(os.environ)
        # When sanitycheck builds the parsetab.py module from YACC
        # information, it will place it by default in the source
        # directory; then multiple processes doing it at the same time
        # will collide. This moves that to our tempdir, so they do not
        # collide. Ideally we'd generate it only once, but we have no
        # easy way to do it.
        env['PARSETAB_DIR'] = cls.tmpdir
        cmdline = [ sanity_check, '--list-tests', '-T', path ]
        try:
            # --list-tests prints in stdout
            #
            # Cleaning output directory ZEPHYR_BASE/sanity-out
            # - kernel.common.byteorder_memcpy_swap
            # - kernel.common.byteorder_mem_swap
            # - kernel.common.atomic
            # - kernel.common.bitfield
            # - kernel.common.printk
            # - kernel.common.slist
            # - kernel.common.dlist
            # - kernel.common.intmath
            # - kernel.common.timeout_order
            # - kernel.common.clock_uptime
            # - kernel.common.clock_cycle
            # - kernel.common.version
            # - kernel.common.multilib
            # 13 total.
            #
            # We are going to ignore the kernel.common part, so we scan the
            # last component
            return subprocess.check_output(
                cmdline, shell = False, stderr = subprocess.STDOUT, env = env)
        except OSError as e:
            raise tcfl.tc.error_e("Can't execute '%s: %s'"
                                  % (" ".join(cmdline), e))
    @classmethod
    def _list_subtests(cls, path):
        output = cls.__sanity_check_list_tests(path)
        subcases = []
        for line in output.split("\n"):
            if line.startswith(" - "):
                subcases.append(line[3:])
        return subcases


    @classmethod
    def _stc_scan_path(cls, path):
        output = cls.__sanity_check_list_tests(path)
        subcases = []
        # --list-tests prints in stdout
        #
        # Cleaning output directory ZEPHYR_BASE/sanity-out
        # - kernel.common.byteorder_memcpy_swap
        # - kernel.common.byteorder_mem_swap
        # - kernel.common.atomic
        # - kernel.common.bitfield
        # - kernel.common.printk
        # - kernel.common.slist
        # - kernel.common.dlist
        # - kernel.common.intmath
        # - kernel.common.timeout_order
        # - kernel.common.clock_uptime
        # - kernel.common.clock_cycle
        # - kernel.common.version
        # - kernel.common.multilib
        # 13 total.
        #
        # We are going to ignore the kernel.common part, so we scan the
        # last component
        for line in output.split("\n"):
            if line.startswith(" - "):
                components = line.split(".")
                component = components[-1]
                subcases.append(component)

        # For the time being, let's check we have the same data when we
        # scan with our fall back method
        subcases_src, _warnings_src = _stc_scan_path_source(path)
        set_subcases_src = set(subcases_src)
        set_subcases = set(subcases)
        if set_subcases_src - set_subcases:
            logging.error(
                "subtestcase detection with 'sanitycheck --list-tests' "
                "missed: %s", " ".join(set_subcases_src - set_subcases))
        if set_subcases - set_subcases_src:
            logging.error(
                "subtestcase detection fallback missed: %s",
                " ".join(set_subcases - set_subcases_src))
        return subcases, [],

    # Because of unfortunate implementation decissions that have to be
    # revisited, we need to initialize the expected list of
    # sub-testcases here.
    #
    # Why? because once we create an instance of this testcase,
    # instead of creating a new one for each target it has to run on
    # in tcfl.tc.tc_c._run_on_targets(), we deepcopy() it in
    # _clone(). So the constructor is never called again -- yeah, that
    # has to change.
    def configure_00(self):	# pylint: disable = missing-docstring
        for subcase in self.subcases:
            # if they haven't ran, we fail them on purpose
            stc = tc_zephyr_subsanity_c(
                self.name + "." + subcase,
                self.kws['thisfile'], self.origin,
                self.kws['tc_name_short'] + "." + subcase,
                self,
                {
                    "description":
                    "subtestcase didn't run: likely the image failed "
                    "to build or to deploy"
                })
            stc.tags_set(self._tags, overwrite = False)
            self.subtestcases[subcase] = stc
            self.post_tc_append(stc)
        if self.subcases:
            self.report_pass("NOTE: this testcase will unfold subcases: %s" %
                             " ".join(self.subcases), dlevel = 1)
        else:
            self.report_pass("NOTE: this testcase does not provide subcases",
                             dlevel = 1)
    #: Dictionary of tags that we want to add to given test cases; the
    #: key is the name of the testcase -- if the testcase name *ends* with
    #: the same value as in here, then the given list of boolean tags
    #: will be patched as True; eg::
    #:
    #:   { "dir1/subdir2/testcase.ini#testname" : [ 'ignore_faults', 'slow' ] }
    #:
    #: usually this will be setup in a
    #: ``{/etc/tc,~/.tcf.tcf}/conf_zephy.py`` configuration file as::
    #:
    #:   tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_tags = {
    #:     "tests/legacy/kernel/test_static_idt/testcase.ini#test": [
    #:         'ignore_faults'
    #:     ],
    #:     ...
    #:   }
    patch_tags = {}

    #: Dictionary of *hw_requires* values that we want to add to given
    #: test cases; the key is the name of the testcase -- if the
    #: testcase name *ends* with the same value as in here, then the
    #: given list of *hw_requires* will be appended as requirements to
    #: the target; eg::
    #:
    #:   { "dir1/subdir2/testcase.ini#testname" : [ 'fixture_1' ],
    #:     "dir1/subdir2/testcase2.ini#testname" : [ 'fixture_2' ] }
    #:
    #: usually this will be setup in a
    #: ``{/etc/tc,~/.tcf.tcf}/conf_zephy.py`` configuration file as::
    #:
    #:   tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_hw_requires = {
    #:     "dir1/subdir2/testcase.ini#testname" : [ 'fixture_1' ],
    #:     "dir1/subdir2/testcase2.ini#testname" : [ 'fixture_2' ],
    #:     ...
    #:   }
    patch_hw_requires = {}

    def _dict_init(self, tc_dict, path, section):
        origin = path + "#" + section

        if tc_dict.get("skip", False):
            raise tc.skip_e("%s: test case skipped" % section)

        if tc_dict.get("build_only", False):
            self.build_only.append(origin)

        target_spec = [ ]
        if tc_dict.get('kernel', None):
            # ignored
            pass

        # harness stuff
        harness_class = tc_dict.get('harness', None)
        harness_config = tc_dict.get('harness_config', {})
        # Get fixture information
        fixtures = harness_config.get('fixture', "").split()

        # Patch 'hw_requires'
        tc_dict.setdefault('hw_requires', set())
        myname = os.path.normpath(self.name)
        for name, hw_requires in self.patch_hw_requires.iteritems():
            if myname.endswith(os.path.normpath(name)):
                for hw_require in hw_requires:
                    tc_dict['hw_requires'].add(hw_require)
        # these are the ones gthat come from the YAML's.harness_config
        for fixture in fixtures:
            tc_dict['hw_requires'].add(fixture)
            
        # depends_on and hw_requires are the same
        if tc_dict.get('hw_requires', None):
            if isinstance(tc_dict['hw_requires'], basestring):
                # .ini format gives us a list
                tc_dict['hw_requires'] = tc_dict['hw_requires'].split()
            target_spec.append("( " + " and ".join(tc_dict['hw_requires'])
                               + " )")

        # This we have to match later
        if tc_dict.get('depends_on', None):
            if isinstance(tc_dict['depends_on'], basestring):
                # .ini format gives us a list
                tc_dict['depends_on'] = tc_dict['depends_on'].split()
            self.zephyr_depends_on = tc_dict['depends_on']

        # We only run on targets with a BSP model that has one BSP
        # The target also has to expose one of the indicators that say
        # Zephyr can run it ('zephyr_board', for new style, or 'board',
        # for the old style). So we test on them as a boolean to
        # ensure they are defined.
        spec = "bsp_count == 1 and (zephyr_board or board)"
        if target_spec:
            spec += " and " + " and ".join(target_spec)
        del target_spec
        self.log.debug("target spec will be '%s'", spec)

        # These are variables we add for the default rules to pick up
        if tc_dict.get("extra_args", None):
            if isinstance(tc_dict['extra_args'], basestring):
                self.extra_args = tc_dict["extra_args"]
            else:
                # .ini format gives us a list
                self.extra_args = " ".join(tc_dict["extra_args"])

        # These are variables we add for the default rules to pick up
        # The build script will now add them to the configuration file
        self.extra_configs = tc_dict.get("extra_configs", [])

        _src = os.path.abspath(path)
        _srcdir = os.path.dirname(_src)
        self.app_src = _srcdir
        if tc_dict.get('type', None) == 'unit':
            self.unit_test = True
        else:
            tc.target_want_add(self, "target", spec, origin,
                               app_zephyr = self.app_src,
                               app_zephyr_options = self.extra_args)

        tags = tc_dict.get("tags", [])
        if isinstance(tags, basestring):
            tags = tags.split()
        for tag in tags:
            self._tags[tag] = (True, origin)

        # This is a Zephyr convention. The component for the testcase
        # is derived from the testname (COMPONENT.TESTNAME) if there
        # is a period in there.
        # We store them as tags component/COMPONENT and in a tag
        # called *components* with the list of COMPONENT names
        if '.' in section:
            component = section.split('.')[0]
            component_tag = "component/" + component
            self.tag_set(component_tag, component, origin)

        if tc_dict.get("slow", False):
            self._tags['slow'] = (True, origin)

        # Patch tags
        for name, tags in self.patch_tags.iteritems():
            if myname.endswith(os.path.normpath(name)):
                for tag in tags:
                    if isinstance(tags, collections.Mapping):
                        value = tags[tag]
                    else:
                        value = True
                    self.tag_set(tag, value)


        if 'timeout' in tc_dict:
            self.tls.expecter.timeout = int(tc_dict['timeout'])

        self.zephyr_filter = tc_dict.get("filter", None)
        self.zephyr_filter_origin = origin
        self.tc_dict = tc_dict
        # The filtering is actually done by app_zephyr.py, on it's build
        # and configure phases

        # If this is defining a harness we know about, create an
        # object to describe it with the config options and append it
        # to the list of harnesses to run in eval_50()
        if harness_class == 'console':
            # we don't care for one_line vs multi_line, treat them the same
            self.harness = _harness_console_c(
                harness_config.get('ordered', True),
                harness_config.get('repeat', 1),
                harness_config.get('regex', [])
            )
        # Anything else is the default harness, which is implemented
        # by eval_50()
        elif harness_class != None and harness_class != "":
            self.build_only.append("Unimplemented Zephyr harness '%s' @%s"
                                   % (harness_class, origin))


    def _get_kws(self):
        testcase_file = inspect.getfile(type(self))
        return dict(
            extra_args = self.extra_args,
            objdir = tcfl.app.get_real_srcdir(testcase_file, self.app_src),
            srcdir = tcfl.app.get_real_srcdir(testcase_file, self.app_src))

    #
    # YAML schemas
    #
    # We will need to load the YAML schemas for verification; however,
    # we might have different versions to be loaded based on (future)
    # support of multiple ZEPHYR_BASEs--as well, we want to have a
    # fallback the copy in the TCF configration libary.
    #
    # So allow each thread to access-or-load and cache them, so they
    # don't have to be re-loaded and re-parsed all the time. And of
    # course, because there are mutiple threads trying it out, protect
    # access to the dictionary with a Lock(). Doing all the loading
    # and parsing under it is ugly, but makes the code simpler and
    # will happen at most (1 + N) times per ZEPHYR_BASE (N being the
    # number of different boards we find), until all the combinations
    # are loaded. Not that bad.
    #
    _schemas_lock = threading.Lock()
    _schemas = {}

    @classmethod
    def schema_get_file(cls, path):
        with cls._schemas_lock:
            if path in cls._schemas:
                return cls._schemas[path]
            if os.path.exists(path):
                # Let if fail if unreadable
                cls._schemas[path] = tcfl.tc_zephyr_scl.yaml_load(path)
                logger.debug("%s: schema loaded", path)
                return cls._schemas[path]
        return None

    @classmethod
    def schema_get(cls, filename):
        ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE',
                                     "__ZEPHYR_BASE_not_defined__")
        locations = [
            # post 09/17 location
            os.path.join(ZEPHYR_BASE, "scripts", "sanity_chk"),
            # pre 9/17 location
            os.path.join(ZEPHYR_BASE, "scripts"),
            # copy in source directory (if running from source)
            os.path.join(os.path.dirname(os.path.join(__file__)),
                         "..", "zephyr"),
            # System global install default copy
            "/etc/tcf",
        ]
        for location in locations:
            schema = cls.schema_get_file(os.path.join(location, filename))
            if schema:
                return schema
        raise tc.error_e("%s: can't load schema from paths %s"
                         % (filename, "".join(locations)))

    def build_00_tc_zephyr(self):
        #
        # Verify that Zephyr testcase limits are obeyed by checking
        # some of the stuff gathered from Zephyr YAML description
        # match the metadata from Zephyr board descriptions.
        #
        if not 'target' in self.targets:
            # Unit test
            return
        target = self.targets['target']

        if self.extra_configs:
            target.zephyr.config_file_write(
                "500_extra_configs",
                """\
# Configuration settings extracted from:
#
#  - %s
#
# by:
#
#  - %s

%s
"""
                % (
                    self.zephyr_filter_origin,
                    commonl.origin_get(1),
                    "\n".join(self.extra_configs)
                )
            )

        def _find_filename(filename, topdir):
            for path, _dirs, filenames in os.walk(topdir):
                if filename in filenames:
                    return os.path.join(path, filename)
            return None

        # Get definitions from ZEPHYR_BASE/board/ARCH/BOARD.yaml to do
        # some filtering.
        arch = target.kws['bsp']
        board = target.kws['zephyr_board']
        yaml_platform_schema = self.schema_get(
            "sanitycheck-platform-schema.yaml")
        topdir = os.path.join(os.environ["ZEPHYR_BASE"], "boards", arch)
        # Find the board definition find; we can't assume is in
        # boards/ARCH/BOARDNAME/BOARDNAME.yaml because places like
        # em_starterkit don't follow that...
        board_yaml_filename = _find_filename(board + ".yaml", topdir)
        if board_yaml_filename == None:
            if os.path.exists(os.path.join(
                    os.environ["ZEPHYR_BASE"], "scripts", "sanity_chk",
                    "sanitycheck-platform-schema.yaml")):
                # newer Zephyr, the tree is broken
                raise tcfl.tc.error_e(
                    "Cannot find board description file %s in %s/*"
                    % (board + ".yaml", topdir))
            else:
                # older Zephyr, no yaml metadata yet
                return
        board_yaml = tc_zephyr_scl.yaml_load_verify(
            board_yaml_filename, yaml_platform_schema)


        # Skip if any platform/arch is whitelisted/excluded
        #
        # We could have added this as a TCF native filter (a target
        # spec), but then non-matching targets would have been silently
        # non-matched and there is a want from the Zephyr people for
        # reporting those as skipped instead of untested. Oh well.
        tc_dict = self.tc_dict
        board_arch = board_yaml['arch']
        board_platform = board_yaml['identifier']
        if tc_dict.get('arch_whitelist', None):
            if isinstance(tc_dict['arch_whitelist'], basestring):
                # .ini format gives us a list
                tc_dict['arch_whitelist'] = tc_dict['arch_whitelist'].split()
            if board_arch not in tc_dict['arch_whitelist']:
                raise tcfl.tc.skip_e(
                    "architecture %s not in the whitelist %s"
                    % (board_arch, " ".join(tc_dict['arch_whitelist'])))

        if tc_dict.get('platform_whitelist', None):
            if isinstance(tc_dict['platform_whitelist'], basestring):
                # .ini format gives us a list
                tc_dict['platform_whitelist'] = tc_dict['platform_whitelist'].split()
            if board_platform not in tc_dict['platform_whitelist']:
                raise tcfl.tc.skip_e(
                    "platform %s not in the whitelist %s"
                    % (board_platform, " ".join(tc_dict['platform_whitelist'])))

        if tc_dict.get('arch_exclude', None):
            if isinstance(tc_dict['arch_exclude'], basestring):
                # .ini format gives us a list
                tc_dict['arch_exclude'] = tc_dict['arch_exclude'].split()
            if board_arch in tc_dict['arch_exclude']:
                raise tcfl.tc.skip_e("architecture %s excluded" % board_arch)

        if tc_dict.get('platform_exclude', None):
            if isinstance(tc_dict['platform_exclude'], basestring):
                # .ini format gives us a list
                tc_dict['platform_exclude'] = tc_dict['platform_exclude'].split()
            if board_platform in tc_dict['platform_exclude']:
                raise tcfl.tc.skip_e("platform %s excluded" % board_platform)

        board_ram = board_yaml.get('ram', 128)	# default from sanitycheck
        if 'min_ram' in self.tc_dict and board_ram < self.tc_dict['min_ram']:
            raise tc.skip_e("test case skipped, need at least "
                            "%dKiB RAM (have %dKiB)" %
                            (self.tc_dict['min_ram'], board_ram))

        board_flash = board_yaml.get('flash', 512)	# default from sanitycheck
        if 'min_flash' in self.tc_dict \
           and board_flash < self.tc_dict['min_flash']:
            raise tc.skip_e("test case skipped, need at least "
                            "%dKiB flash (have %dKiB)" %
                            (self.tc_dict['min_flash'], board_flash))

        ignore_tags = board_yaml.get('testing', {}).get('ignore_tags', [])
        for tag, (_value, origin) in self._tags.iteritems():
            if tag in ignore_tags:
                raise tc.skip_e(
                    "skipped: testcase tagged %s (@%s), marked to ignore "
                    "in Zephyr's board YAML testing.ignore_tags"
                    % (tag, origin))

        zephyr_supported = board_yaml.get('supported', [])
        for supported in zephyr_supported:
            if ':' in supported:
                # if given LABEL:SUBLABEL, allow matching on LABEL
                # only, so when a TC declares it depends_on LABEL and
                # board declares LABEL:SUBLABEL, it matches
                zephyr_supported.append(supported.split(":")[0])
        for dependency in self.zephyr_depends_on:
            if not dependency in zephyr_supported:
                raise tc.skip_e("zephyr board '%s' doesn't provide required "
                                "'%s' dependency" % (board, dependency))


    def build_unit_test(self):
        """
        Build a Zephyr Unit Test in the local machine
        """
        # If this is not a unit test, the app builder app_zephyr
        # builds for us, introducing a method build_for_target()
        if not self.unit_test:
            return

        # Yes, using Python-shcript so the compile output shows the
        # exact steps we followed to build that can be run by a
        # human--would be easier to run os.mkdir() and stuff, but not
        # as clear to the would-be-debugger human trying to verify what
        # happened

        ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE',
                                     "__ZEPHYR_BASE_not_defined__")
        srcdir = self.kws['srcdir']
        self.kws_set(dict(
            zephyr_objdir = os.path.join(self.tmpdir, "outdir-%(tc_hash)s"
                                         % self.kws),
            zephyr_srcdir = srcdir,
            zephyr_extra_args = self.extra_args,
            MAKE = os.environ.get('MAKE', 'make')
        ))
        # Create destination directory
        self.shcmd_local('mkdir -p %(zephyr_objdir)s')

        if os.path.exists(os.path.join(ZEPHYR_BASE, "CMakeLists.txt")):
            if not os.path.exists(os.path.join(srcdir, "CMakeLists.txt")):
                raise tc.error_e(
                    "%s: Zephyr App is not cmake based, but Zephyr @%s is"
                    % (srcdir, ZEPHYR_BASE))
            is_cmake = True
        else:
            if os.path.exists(os.path.join(srcdir, "CMakeLists.txt")):
                raise tc.error_e(
                    "%s: Zephyr App is cmake based, but Zephyr @%s is not"
                    % (srcdir, ZEPHYR_BASE))
            is_cmake = False

        # Build the test binary
        if is_cmake:
            self.shcmd_local(
                'cmake'
                ' -DBOARD=unit_testing '
                ' -DEXTRA_CPPFLAGS="-DTC_RUNID=%(runid)s:%(tc_hash)s"'
                ' -DEXTRA_CFLAGS="-Werror -Wno-error=deprecated-declarations"'
                ' -DEXTRA_AFLAGS=-Wa,--fatal-warnings'
                ' -DEXTRA_LDFLAGS=-Wl,--fatal-warnings'
                ' %(zephyr_extra_args)s'
                ' -B"%(zephyr_objdir)s" -H"%(zephyr_srcdir)s"')
            self.shcmd_local('%(MAKE)s -C %(zephyr_objdir)s')
        else:
            self.shcmd_local(
                '%(MAKE)s -j -C %(zephyr_srcdir)s'
                ' KCPPFLAGS=-DTC_RUNID=%(runid)s:%(tc_hash)s'
                ' BOARD=unit_testing %(zephyr_extra_args)s'
                ' O=%(zephyr_objdir)s')

    @staticmethod
    def _in_file(f, regex):
        f.seek(0, 0)
        if isinstance(regex, basestring):
            regex = re.compile(re.escape(regex))
        for line in f:
            if regex.search(line):
                return True
        return False

    # Our evaluation always looks the same
    def eval_50(self):		# pylint: disable = missing-docstring
        if self.harness:	# Do a Zephyr harness evaluation
            return self.harness.evaluate(self)
        elif self.unit_test:
            with commonl.logfile_open("testbinary_output", delete = False,
                                      directory = self.tmpdir) as logf:
                self.unit_test_output = logf.name	# keep for subtestcase
                self.shcmd_local("%(zephyr_objdir)s/testbinary",
                                 logfile = logf)
                if self._in_file(logf, "PROJECT EXECUTION FAILED"):
                    raise tc.failed_e("PROJECT EXECUTION FAILED found",
                                      { "output": logf })
                if self._in_file(logf, "PROJECT EXECUTION SUCCESSFUL"):
                    raise tc.pass_e("PROJECT EXECUTION SUCCESSFUL found",
                                    { "output": logf })
                else:
                    raise tc.error_e("PROJECT EXECUTION SUCCESSFUL not found",
                                     { "output": logf })
        else:			# Default Zephyr harness evaluation
            # This mimics what app_zephyr is computing for us and setting
            # into the build. We can do this because sanity check TCs are
            # ALWAYS one target, one core BSP model.
            target = self.targets["target"]
            
            # So set three things we need to see out the console
            # before we can say we have passed:
            #
            # - Runid: RUNID:HASH
            # - ***** Booting Zephyr OS BLAHBLAH delayed boot Nms ******
            # - PROJECT EXECUTION SUCCESSFUL
            #
            # Do it like this instead of tree expect sequences in a
            # row to minimize the chances of timing blips causing a
            # timeout (eg: first expect passes, thr process is put to
            # sleep for a long time before the next expect can run and
            # decide it was a timeout, when it wasn't).
            target.on_console_rx("RunID: %(runid)s:%(tg_hash)s" % target.kws,
                                 console = target.kws.get("console", None))
            target.on_console_rx(
                re.compile("\*\*\*\*\* Booting Zephyr OS .* \(delayed boot [0-9]+ms\) *\*\*\*\*\*"),
                console = target.kws.get("console", None))
            target.on_console_rx("PROJECT EXECUTION SUCCESSFUL",
                                 console = target.kws.get("console", None))
            # And wait for them to happen
            self.tls.expecter.run()

    _data_parse_regexs = {}

    @classmethod
    def data_harvest(cls, domain, name, regex,
                     main_trigger_regex = None, trigger_regex = None,
                     origin = None):
        """Configure a data harverster

        After a Zephyr sanity check is executed succesfully, the
        output of each target is examined by the data harvesting
        engine to extract data to store in the database with
        :meth:`tcfl.tc.tc_c.report_data`.

        The harvester is a very simple state machine controlled by up
        to three regular expressions whose objective is to extract a
        value, that will be reported to the datase as a
        domain/name/value triad.

        A domain groups together multiple name/value pairs that are
        related (for example, latency measurements).

        Each line of output will be matched by each of the entries
        registered with this function.

        All arguments (except for *origin*) will expand '%(FIELD)s'
        with values taken from the target's keywords
        (:data:`tcfl.tc.target_c.kws`).

        :param str domain: to which domain this measurement applies
          (eg: "Latency Benchmark %(type)s");
          It is recommended this is used to aggregate values to
          different types of targets.
        :param str name: name of the value  (eg: "context switch
          (microseconds)")
        :param str regex: regular expression to match against each
          line of the target's output. A Python regex
          '(?P<value>SOMETHING)` has to be used to point to the value
          that has to be extracted (eg: "context switch time
          (?P<value>[0-9]+) usec").
        :param str main_trigger_regex: (optional) only look for
          *regex* if this regex has already been found. This trigger
          is then considered active for the rest of the output.
          This is used to enable searching this if there is a banner
          in the output that indicates that the measurements are about
          to follow (eg: "Latency Benchmark starts here).
        :param str trigger_regex: (optional) only look for
          *regex* if this regex has already been found. However, once
          *regex* is found, then this trigger is deactivated.
          This is useful when the measurements are reported in two
          lines::

            measuring context switch like this
            measurement is X usecs

          and thus the regex could catch multiple lines because
          another measurement is::

            measuring context switch like that
            measurement is X usecs

          the regex `measurement is (?P<value>[0-9]) usecs` would
          catch both, but by giving it a *trigger_regex* of `measuring
          context switch like this`, then it will catch only the
          first, as once it is found, the trigger is removed.

        :param str origin: (optional) where this values are coming
          from; if not specified, it will be the call site for the
          function.

        """
        assert isinstance(domain, basestring)
        assert isinstance(name, basestring)
        assert isinstance(regex, basestring)
        if main_trigger_regex:
            assert isinstance(main_trigger_regex, basestring)
        if trigger_regex:
            assert isinstance(trigger_regex, basestring)
        if not origin:
            origin = commonl.origin_get()
        else:
            assert isinstance(origin, basestring)
        cls._data_parse_regexs[domain, name] = (
            main_trigger_regex, trigger_regex, regex, origin)

    def _report_data_from_target(self, target):
        # Scan for KPIs that we want to report
        regex_list = []
        # We need to re-generate this list per-target as there
        # might be field formatting in domain name, name and regex
        # patterns
        for (domain, name), (main_trigger_regex, trigger_regex, regex, origin) \
            in self._data_parse_regexs.iteritems():
            try:
                regex_list.append((
                    domain % target.kws,
                    name % target.kws,
                    re.compile(main_trigger_regex % target.kws) \
                      if main_trigger_regex else None,
                    re.compile(trigger_regex % target.kws) \
                      if trigger_regex else None,
                    re.compile(regex % target.kws),
                    origin
                ))
            except KeyError as e:
                raise tcfl.tc.blocked_e(
                    "%s/%s: can't find field '%s' to expand (@%s)"
                    % (domain, name, e.message, origin))
            except re.error as e:
                raise tcfl.tc.blocked_e(
                    "%s/%s: bad regex (@%s): %s"
                    % (domain, name, origin, e))
        if self.unit_test:
            f = codecs.open(self.unit_test_output, 'r', encoding = 'utf-8')
        else:
            console_id = target.kws.get('console', None)
            f_existing = self.tls.expecter.console_get_file(target, console_id)
            # this gives a file descriptor whose pointer might be in
            # any location, so we are going to reopen a new one to
            # read from the start--because we don't want to modify the
            # file pointer
            f = open(f_existing.name)
        main_triggered = set()
        triggered = set()
        # Note the triggers; each regex might depend on a trigger and
        # a main trigger; when a main trigger happens, then it is
        # on for the rest of the file. When a trigger happens, it
        # is on only until the regex that specified it is hit, then it
        # is cleared. See fn doc
        for line in f.readlines():
            for domain, dataname, main_trigger_regex, \
                trigger_regex, regex, origin in regex_list:
                line = line.strip()
                if main_trigger_regex:
                    # We have a main trigger regex to match on
                    if not main_trigger_regex.pattern in main_triggered:
                        # The main trigger hasn't been found yet
                        if main_trigger_regex.search(line):
                            # Found it, add it to the triggered list
                            main_triggered.add(main_trigger_regex.pattern)
                        continue  # main trigger didn't happen yet, skip
                    # fall through, the main trigger has happened, so we
                    # can search for more stuff
                if trigger_regex:
                    # We have a trigger regex to match on
                    if not trigger_regex.pattern in triggered:
                        # The trigger hasn't been found yet
                        if trigger_regex.search(line):
                            # Found it, add it to the triggered list
                            triggered.add(trigger_regex.pattern)
                        continue  # trigger didn't happen yet, skip
                    # fall through, the trigger has happened, so we
                    # can search for the main regex
                m = regex.search(line)
                if not m:
                    continue
                value = m.groupdict().get('value', None)
                if not value:
                    self.log.warning(
                        "%s/%s: bad regex specificatiom @%s, no 'value' "
                        "field on match", domain, dataname, origin)
                    continue
                target.report_data(domain, dataname, value, expand = False)
                # Release the trigger this thing depends on
                # Note we don't release the main triggers, as once
                # they are on, they are valid for all.
                if trigger_regex:
                    triggered.remove(trigger_regex.pattern)

    # per zephyr/tests/include/tc_util.h:TC_START and TC_END_RESULT,
    # there are only two results, PASS and FAILED and they print
    #
    #   starting test - TESTNAME
    #   (MAYBE OUTPUT)
    #   PASS|FAIL - TESTNAME.
    #
    # Yeah, not the most consistent best format, but we can parse
    # it. Mind there might be \r at the end, so we'll hack it.
    subtc_results_valid = ('PASS', 'FAIL', 'SKIP')
    subtc_regex = re.compile(r"^(?P<result>(" + "|".join(subtc_results_valid)
                             + "|starting test)) - (?P<testname>[\S\\r\.]+)$",
                             re.MULTILINE)

    def _subtestcases_grok(self, target):
        # So, Zephyr sanitycheck testcases might be implemented with
        # the ztest framework, which packs one ore more testcase
        # inside a single image.
        #
        # Because we want to be able to report them separatedly, we
        # look at the output and we report each subtestcase we find as
        # a separate subtestcase using the tcfl.tc_c.post_tc_append()
        # facility.

        # The output has been captured already by the expecter's
        # polling loop, but (FIXME) I don't really like much how we
        # are using internal details on the buffers, we are kind of
        # breaking inside the knowledge of expecter.console_*
        # functions
        if self.unit_test:
            outputf = codecs.open(self.unit_test_output, 'r',
                                  encoding = 'utf-8')
        else:
            console = target.kws.get('console', None)
            _console_id_name, console_code = expecter.console_mk_code(
                target, console)
            outputf = self.tls.expecter.buffers.get(console_code, None)
            if not outputf:
                return	# *shrug* no output to parse
        results = collections.defaultdict(dict)

        try:
            with contextlib.closing(
                mmap.mmap(outputf.fileno(), 0, mmap.MAP_PRIVATE,
                          mmap.PROT_READ, 0)) as output:
                for m in re.finditer(self.subtc_regex, output):
                    mgd = m.groupdict()
                    # testname might have the \r at the end (which we
                    # don't need) and for the finishing message, it has a
                    # period too...geeze
                    testname = mgd['testname'].rstrip(".\r\r")
                    testname = testname.replace("test_", "")
                    if mgd['result'] == 'starting test':
                        # if the message is 'starting test', then this
                        # marks the beginning of the output of this
                        # subtestcase
                        results[testname]['start'] = m.end()
                    elif mgd['result'] in self.subtc_results_valid:
                        # however, this means the end of the output
                        results[testname]['end'] = m.start()
                        results[testname]['result'] = mgd['result']
        except ValueError as e:
            if 'cannot mmap an empty file' in e.message:
                return	# *shrug* no output to parse
            raise

	# in case of failure, for the reporting to know where to start
        # reading; note we report the *whole* ouput, as failures could
        # we due to a previous failure or condition
        outputf.seek(0)
        expected_testcases = set(self.subtestcases.keys())
        for testname, td in results.iteritems():
            if not 'start' in td:
                self.report_blck("%s: no way to determine start of output" %
                                 testname)
                continue
            if not 'end' in td:
                self.report_blck("%s: no way to determine end of output" %
                                 testname)
                continue
            zephyr_name = self.kws['tc_name_short']
            if testname not in self.subtestcases:
                # Did we find a testcase that wasn't found when
                # parsing the source code? This is bad, so report it
                stc = tc_zephyr_subsanity_c(
                    self.name + "." + testname,
                    self.kws['thisfile'], self.origin,
                    self.kws['tc_name_short'] + "." + testname, self,
                    {
                        "description": "subtestcase found in output but not "
                                       "defined in source"
                    })
                stc.tags_set(self._tags, overwrite = False)
                stc._result = "ERRR"
                self.subtestcases[testname] = stc
            else:
                expected_testcases.remove(testname)
                # Ok, this is a hack -- in case we are doing multiple
                # evaluations, re-use the subtestcases created for the
                # first one, but for the subsequent ones, create new
                # ones, as they will be all run at the end.
                if self.eval_count == 0:
                    stc = self.subtestcases[testname]
                    del stc.attachments['description']
                else:
                    stc = copy.copy(self.subtestcases[testname])
                    self.post_tc_append(stc)
                # only gather the result if legally found--we don't
                # want to override the BLCK from the other condition
                # branch
                stc._result = td['result']
            stc.attachments['console output'] = outputf
        # Is there any sub testcase we expected to run but didn't run?
        # Well, by default is set to block already, let's just patch
        # in a description and plug the output
        for testname in expected_testcases:
            stc = self.subtestcases[testname]
            stc._result = "ERRR"
            stc.attachments['description'] = "testcase didn't run as expected"
            stc.attachments['console output'] = outputf

    def teardown_subtestcases(self):
        """
        Given the output of the testcases, parse subtestcases for each target
        """
        if self.unit_test:
            self._subtestcases_grok(None)
        else:
            for target in self.targets.values():
                self._subtestcases_grok(target)

    def teardown(self):
        if self.result_eval.summary().passed == 0:
            return
        for target in self.targets.values():
            self._report_data_from_target(target)

    def clean(self):
        if not self.unit_test:
            # if not a unit test, app_zephyr cleans for us
            return
        # Note we remove with a shell command, so it shows what we do
        # that an operator could repeat
        self.shcmd_local('rm -rf %(srcdir)s/outdir-%(tc_hash)s-unit_testing')

    filename_regex = re.compile(r"^test.*\.ini$")
    filename_yaml_regex = re.compile(r"^(testcase|sample)\.yaml$")

    @classmethod
    def _testcase_ini_mktcs(cls, path):
        if not cls.filename_regex.match(os.path.basename(path)):
            return []

        tcs = []
        cp = SanityConfigParser(path)

        for section in cp.sections():
            origin = path + "#" + section
            try:
                tc_dict = cp.get_section(section, testcase_valid_keys)
            except ConfigurationError as e:
                raise tc.blocked_e("can't parse: %s @%s" % (e[1], e[0]),
                                   { "trace": traceback.format_exc() })
            _tc = cls(origin, path, origin, section)
            _tc.log.debug("Original testcase.ini data for section '%s'\n%s"
                          % (section, pprint.pformat(tc_dict)))
            _tc._dict_init(tc_dict, path, section)
            tcs.append(_tc)
        return tcs

    # this is lefted straight from Zephyr's
    # sanitycheck.SanityConfigParser._cast_value(), until we can
    # export the functionality
    @classmethod
    def _cast_value(cls, value, typestr, name):
        if isinstance(value, str):
            v = value.strip()
        if typestr == "str":
            return v

        elif typestr == "float":
            return float(value)

        elif typestr == "int":
            return int(value)

        elif typestr == "bool":
            return value

        elif typestr.startswith("list") and isinstance(value, list):
            return value
        elif typestr.startswith("list") and isinstance(value, str):
            vs = v.split()
            if len(typestr) > 4 and typestr[4] == ":":
                return [cls._cast_value(vsi, typestr[5:]) for vsi in vs]
            else:
                return vs

        elif typestr.startswith("set"):
            vs = v.split()
            if len(typestr) > 3 and typestr[3] == ":":
                return set([cls._cast_value(vsi, typestr[4:], name) for vsi in vs])
            else:
                return set(vs)

        elif typestr.startswith("map"):
            return value
        else:
            raise ConfigurationError(
                name, "unknown type '%s'" % value)

    # this is lefted straight from Zephyr's
    # sanitycheck.SanityConfigParser.get_test(), until we can export
    # the functionality
    @classmethod
    def _get_test(cls, name, test_data, common, valid_keys):

        d = {}
        for k, v in common.iteritems():
            d[k] = v

        for k, v in test_data.iteritems():
            if k not in valid_keys:
                raise ConfigurationError(
                    name,
                    "Unknown config key '%s' in definition for '%s'" %
                    (k, name))

            if k in d:
                if isinstance(d[k], str):
                    d[k] += " " + v
            else:
                d[k] = v

        for k, kinfo in valid_keys.iteritems():
            if k not in d:
                if "required" in kinfo:
                    required = kinfo["required"]
                else:
                    required = False

                if required:
                    raise ConfigurationError(
                        name,
                        "missing required value for '%s' in test '%s'" %
                        (k, name))
                else:
                    if "default" in kinfo:
                        default = kinfo["default"]
                    else:
                        default = cls._cast_value("", kinfo["type"], name)
                    d[k] = default
            else:
                try:
                    d[k] = cls._cast_value(d[k], kinfo["type"], name)
                except ValueError as ve:
                    raise ConfigurationError(
                        name, "bad %s value '%s' for key '%s' in name '%s'" %
                        (kinfo["type"], d[k], k, name))

        return d
    
    @classmethod
    def _testcasesample_yaml_mktcs(cls, path):
        #
        #
        # ASSUMPTIONS:
        #   - way too many
        #
        # 1 - each subtestcase listed in testcase|sample.yaml or in the
        #     output of 'sanitycheck --list-tests' is in the form
        #     something.other.whatever.final
        #
        # 2 - if the testcase provides subcases inside the source,
        #     something.other.whatever has to match as a subcase in the
        #     testcase|sample.yaml
        #
        # so anyhoo, there are multiple testcases declared in the
        # yaml, which allow us to build multiple testcases from the
        # same source; then the source might define multiple
        # subtestcases and 'scripts/sanitycheck --list-tests' throws
        # them all in the same bag
        #
        # So it is kinda hard to identify what is the top_subcase
        # subtestcase (off the YAML file) or scanned from the source
        # (src_subcase)
        #
        # For example, when listing zephyr/samples/philosophers
        #
        #   $ scripts/sanitycheck --list-tests -T samples/philosophers/
        #   JOBS: 16
        #    - sample.philosopher
        #    - sample.philosopher.coop_only
        #    - sample.philosopher.fifos
        #    - sample.philosopher.lifos
        #    - sample.philosopher.preempt_only
        #    - sample.philosopher.same_prio
        #    - sample.philosopher.semaphores
        #    - sample.philosopher.stacks
        #    - sample.philosopher.static
        #    - sample.philosopher.tracing
        #
        # these are all top_subcase (from the YAML tests: listing)
        # but there is no way to tell; for example:
        #
        #   $ scripts/sanitycheck --list-tests -T tests/kernel/critical/
        #   JOBS: 16
        #   - kernel.common.critical
        #   - kernel.common.nsim.critical
        #   2 total.
        #
        # off the YAML come kernel.common and kernel.common.nsim and
        # critical a src_subcase.
        #
        tcs = []
        yaml_tc_schema = cls.schema_get("sanitycheck-tc-schema.yaml")
        y = tc_zephyr_scl.yaml_load_verify(path, yaml_tc_schema)

        subcases = cls._list_subtests(os.path.dirname(path))

        data = y.get('tests', None)
        if isinstance(data, list):
            mapping = {}
            # There backward compatibility...
            # Before the YAML was defined by mistake to contain the
            # tests in a list of mappings rather than in a mapping, so
            # now that is fixed, we flatten that.
            for entry in data:
                mapping.update(entry)
        elif data == None:
            # this means this .yaml has just a description but it does
            # not specify how to run any of it, so we are going to
            # pass
            raise tc.skip_e(
                "no `tests` section declared in %s" % path)
            return
        else:
            assert isinstance(data, dict), \
                "tests data is not a dict but a %s" % type(data).__name__
            mapping = data
        common = y.get('common', {})
        # tc_name iterate over the testcase names in
        # testcase|sample.yaml, where we are getting config options,
        # excludes, etc...
        for tc_name, _tc_vals in mapping.iteritems():
            the_subcases = []
            for subcase in subcases:
                # split kernel.common.somecase -> kernel.common ||
                # somecase
                # Well, this is the magic to try to differentiate when
                # the thing is a subcase from the source or from the
                # yaml and when it is impossible to tell appart...look
                # for the big comment block above. Yep, it is a
                # POS.
                #
                # ASSUMPTION: src subcases can come after only
                # one period (name1.name2.name3.name4, a src_subcase
                # can come only as name4, not as name3.name4).
                top_subcase, src_subcase = os.path.splitext(subcase)
                if ( subcase == tc_name and top_subcase >= tc_name ) \
                   or ( top_subcase == tc_name ):
                    if not tc_name.endswith(src_subcase):
                        # the src_subcase is from the split .WHATEVER
                        the_subcases.append(src_subcase[1:])
            tc_vals = cls._get_test(tc_name, _tc_vals, common, testcase_valid_keys)
            origin = path + "#" + tc_name
            _tc = cls(origin, path, origin, tc_name, the_subcases)
            _tc.log.debug("Original %s data for test '%s'\n%s"
                          % (os.path.basename(path), tc_name,
                             pprint.pformat(tc_vals)))
            _tc._dict_init(tc_vals, path, tc_name)
            tcs.append(_tc)
        return tcs

    @classmethod
    def is_testcase(cls, path):
        if cls.filename_regex.match(os.path.basename(path)):
            return cls._testcase_ini_mktcs(path)
        if cls.filename_yaml_regex.match(os.path.basename(path)):
            return cls._testcasesample_yaml_mktcs(path)
        else:
            return []
