#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to run testcases

import commonl
import tcfl.testcase
import tcfl.report_console
import tcfl.report_jinja2


def _cmdline_find(args):

    # add reporters for logging, so if we find issues when importing
    # we'll see detailed data logged
    tcfl.tc.report_driver_c.add(
        tcfl.report_console.driver(args.verbosity - args.quietosity),
        name = "console")
    # report file writer, so we get details
    tcfl.tc.report_driver_c.add(
        tcfl.report_jinja2.driver(args.log_dir),
        name = "jinja2")

    tcs_filtered = {}
    result = tcfl.testcase.discover(
        tcs_filtered,
        sources = args.testcase,
        manifests = args.manifest,
        filter_spec = args.tc_filter_spec,
    )

    for tc_name, tc in tcs_filtered.items():
        print(tc_name, tc.origin)


def _common_args_add(ap):
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Display more progress information")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Display more progress information less progress info")
    ap.add_argument(
        "--log-dir", metavar = "DIRECTORY", action = "store",
        type = str, default = ".",
        help = "Write all log files and reports to the given directory"
        "(default current working directory)")
    ap.add_argument("-m", "--manifest", metavar = "MANIFESTFILEs",
                    action = "append", default = [],
                    help = "Specify one or more manifest files containing "
                    "test case paths (one per line) or '#' prefixed comment "
                    "lines. Test case paths are acumulated, keeping other "
                    "specified paths")
    ap.add_argument(
        "-s", action = "append", dest = 'tc_filter_spec', default = [],
        help = "Specify testcase filters, based on the testcase tags; "
        "multiple tags specifications are ORed together")
    ap.add_argument("testcase", metavar = "TESTCASE|DIR", nargs = "*",
                    help = "Files describing testcases or directories"
                    " where to find them")


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser("find", help = "Find testcases")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_find)
    commonl.argparser_add_aka(arg_subparsers, "find", "tc-find")
    commonl.argparser_add_aka(arg_subparsers, "find", "testcase-find")
