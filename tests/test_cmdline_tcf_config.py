#! /usr/bin/python3
#
# Copyright (c) 2025 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import re
import subprocess

import tcfl
import tcfl.tc

import clil


def run_tcf_config(self, target: tcfl.tc.target_c):


    # this should report the same as "python -m setuptools_scm" ran in
    # the source tree
    with self.subcase("version_check_vs_setuptools_scm"):
        output = subprocess.run(
            "python -m setuptools_scm".split(),
            capture_output = True, text = True, cwd = clil.topdir).stdout.strip()
        if output != tcfl.tc.version:
            self.report_fail(
                f"tcfl.tc.version '{tcfl.tc.version}' does not match"
                f" output of 'python -m setuptools_scm': '{output}'",
                { "tcfl.tc": tcfl.tc.__file__ })
        else:
            self.report_pass(
                f"tcfl.tc.version '{tcfl.tc.version}' matches"
                " output of 'python -m setuptools_scm'")

    # copy the cmdline_environment_run.py file to temp as test_ ->
    # we do it like this so when we 'tcf run tests/', we don't
    # run that one.
    with self.subcase("execution"):
        # the environment has been set so this runs the right TCF
        # command; eg PATH has been set to be:
        #
        # - for running from source, the first path component is the
        #   source tree
        #
        # - for running from python vevn, activated and the path set
        #   to the python venv
        #
        # - for running from prefix, the first path is set to the
        #   prefix's path
        #
        output = target.shell.run("tcf config", output = True)
        self.report_pass(
            "can run 'tcf config' command",
            { "output": output })

    # FIXME: verify we just print that, nothing more, nothing less
    #
    # This shall print
    #
    ## tcf: ./tcf
    ## tcf/realpath: .../tcf
    ## tcfl: .../tcfl/__init__.py
    ## commonl: .../commonl/__init__.py
    ## share path: ...
    ## state path: $HOME/.tcf
    ## config path: .../zephyr:...:$HOME/.tcf:.tcf
    ## config file 0: .../zephyr/conf_zephyr.py
    ## config file 1: .../conf_...
    ## version: ...
    ## python: ...
    ## uname.machine: ...
    ## uname.node: ...
    ## uname.processor: ...
    ## uname.release: ...
    ## uname.system: ...
    ## uname.version: ...
    ## servers: 11
    ## server ...: ...
    ## resolvconf: ...
    ## resolvconf: ...
    #
    with self.subcase("section_presence"):
        for subsection in [
                "tcf",
                "tcf/realpath",
                "tcfl",
                "commonl",
                "share path",
                "state path",
                "config path",
                # at least it will discover one config file
                # FIXME: when running in prefix/venv/container it
                # might disconver no config files, so for now we won't
                # check for it, but we need a test that creates a
                # config file and we discover it
                #"config file 0",
                "version",
                "python",
                "servers",
                # this is only if we discover servers, which we
                # won't in this run
                #"server",
                "resolvconf",
        ]:
            if not subsection + ":" in output:
                self.report_fail(
                    f"can't find section '{subsection}': in 'tcf config' output",
                    subcase = subsection)
            else:
                self.report_pass(
                    f"can find section '{subsection}': in 'tcf config' output",
                    subcase = subsection)

    # parse the output, it mush match tcfl.tc.version
    with self.subcase("version_check"):
        version_regex = re.compile("^version: (?P<version>\S+)$", re.MULTILINE)
        m = version_regex.search(output)
        if not m:
            self.report_error(
                f"can't extract version with pattern {version_regex.pattern}",
                { "output": output })
        else:
            version_found = m.groupdict()['version']
            if version_found == "vNA":
                self.report_fail(
                    "CLI reports version vNA, meaning not available;"
                    " expected vMAJOR.MINOR.PL....",
                    { "output": output })
            elif version_found != tcfl.tc.version:
                self.report_fail(
                    f"CLI reports version '{version_found}';"
                    f" expected '{tcfl.tc.version}' from tcfl.tc.version",
                    { "output": output })
            else:
                self.report_pass(
                    f"CLI reports version '{version_found}';"
                    f" matching expected from tcfl.tc.version")


@tcfl.tc.tags(
    "tcf_client",
    # files relative to top level this testcase exercises
    files = [ 'tcf', 'tcfl/ui_cli_main.py' ],
    level = "basic")
class _test(clil.test_base_c):
    """
    Test running *tcf config* works basically
    """

    # clil.test_base_c has setup the environment and path to run into
    # whatever combination of local|containerimge, source tree, dir
    # prefix or virtual environment

    def eval_10(self, target):
        run_tcf_config(self, target)
