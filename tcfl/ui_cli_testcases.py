#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to run testcases
import logging
import random

import tcfl.report_console
import tcfl.report_jinja2


def _cmdline_report_init(args):

    # add reporters for logging, so if we find issues when importing
    # we'll see detailed data logged
    tcfl.report_driver_c.add(
        tcfl.report_console.driver(args.verbosity - args.quietosity),
        name = "console")
    # report file writer, so we get details
    tcfl.report_driver_c.add(
        tcfl.report_jinja2.driver(args.log_dir),
        name = "jinja2")


def _cmdline_find(args):

    import tcfl.testcase		# lazy import, only if needed

    tcfl.testcase.discovery_subsystem_setup(
        log_dir = args.log_dir,
        tmpdir = args.tmpdir,
        remove_tmpdir = args.remove_tmpdir, hashid = "cmdline")
    _cmdline_report_init(args)

    tcs_filtered = {}
    _result = tcfl.testcase.discover(
        tcs_filtered,
        sources = args.testcase,
        manifests = args.manifest,
        filter_spec = args.tc_filter_spec,
    )

    for tc_name, tc in tcs_filtered.items():
        print(tc_name, tc.origin)


def _testcase_info_print(testcase):
    # Print information about a testcase

    print("Testcase name: ", testcase.name)
    if testcase.__doc__:
        print(testcase.__doc__)

    if not testcase.target_roles:
        print("  static: requires no targets")
    else:
        print(f"  Requests {len(testcase.target_roles)} targets (roles):")
        for role_name, role in reversed(testcase.target_roles.items()):
            print(f"\n  - {role_name}"
                  f" {'(interconnect)' if role.interconnect else ''}")
            if role.spec:
                print(f"      filter spec: '{role.spec}'"
                      f" {'args: ' + str(role.spec_args) if role.spec_args else '(no extra args)'}")
            if role.ic_spec:
                print(f"      interconnect spec: '{role.ic_spec}'"
                      f" {'args: ' + str(role.ic_spec_args) if role.ic_spec_args else '(no extra args)'}")

            if role.axes:
                print(f"      declares {len(role.axes)} axes to spin on:")
                for axis, values in role.axes.items():
                    if values:
                        print(f"        - {axis}: {values}")
                    else:
                        print(f"        - {axis}")
            else:
                print(f"      declares no axes to spin on")

    if testcase._axes_all:
        print(f"\n  Axes permutations: {testcase._axes_all_mr.max_integer()}"
              f" from {len(testcase._axes_all)} axes"
              " (testcase's + target role's):\n")

        if testcase._axes_permutations == 0:
            print("    - will spin all possible axes permutations")
            if testcase._axes_all_mr.max_integer() > 100:
                print("      WARNING! this might result in way more"
                      " executions than expected.\n"
                      "               Recommend setting"
                      " knob *axes_permutations* to"
                      " N < 100\n"
                      "               or reducing the number of axes"
                      " if possible")
        else:
            print(f"    - will spin a maximum of"
                  f" {testcase._axes_permutations} axes permutations")
        if testcase._axes_randomizer_original == "sequential":
            print("    - axes permutation randomization: sequential"
                  " by order of enumeration")
        elif testcase._axes_randomizer_original == "random":
            print("    - axes permutation randomization:"
                  " pseudo-random with random seed")
        elif isinstance(testcase._axes_randomizer_original, str):
            print("    - axes permutation randomization: pseudo-random"
                  f" with seed '{testcase._axes_randomizer_original}'")
        elif isinstance(testcase._axes_randomizer_original, random.Random):
            print("    - axes permutation randomization: provided-pseudo"
                  " random random.Ramdom object")
        else:
            print("    - axes permutation randomization: <unknown>"
                  f" {testcase._axes_randomizer_original}")

    if testcase.target_roles:
        print("\n  Target group permutations")
        if testcase._target_group_permutations == 0:
            print("    - will spin all possible target group permutations"
                  " for each axes permutation")
            if len(testcase.target_roles) > 2:
                print("      WARNING! this might result in way more"
                      " executions than expected\n"
                      "               Recommend setting"
                      " knob *target_group_permutations* to"
                      " N < 5")
        else:
            print("    - will spin a maximum of"
                  f" {testcase._target_group_permutations} target group"
                  " permutations for each axes permutation")
        if testcase._target_group_randomizer_original == "sequential":
            print("    - target group randomization: sequential by"
                  " order of enumeration")
        elif testcase._target_group_randomizer_original == "random":
            print("    - target group randomization: pseudo-random"
                  " with random seed")
        elif isinstance(testcase._target_group_randomizer_original, str):
            print("    - target group randomization: pseudo-random with seed"
                  f" '{testcase._target_group_randomizer_original}'")
        elif isinstance(testcase._target_group_randomizer_original, random.Random):
            print("    - target group randomization: provided-pseudo"
                  " random random.Ramdom object")
        else:
            print("    - target group randomization: <unknown>"
                  f" {testcase._target_group_randomizer_original}")
        print()


def _cmdline_info(args):

    import tcfl.testcase		# lazy imports

    tcfl.testcase.discovery_subsystem_setup(
        log_dir = args.log_dir,
        tmpdir = args.tmpdir,
        remove_tmpdir = args.remove_tmpdir)
    _cmdline_report_init(args)

    # FIXME: load testcase
    tcs_filtered = {}
    _result = tcfl.testcase.discover(
        tcs_filtered,
        sources = args.testcase,
        manifests = args.manifest,
        filter_spec = args.tc_filter_spec,
    )

    if not tcs_filtered:
        names = [ driver.__name__ for driver in tcfl.testcase._drivers ]
        logging.error("WARNING! No testcases found"
                      f" (tried drivers: {' '.join(names)})")
        return

    for _name, tc in tcs_filtered.items():
        _testcase_info_print(tc)


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
    ap.add_argument(
        "--no-remove-tmpdir", dest = "remove_tmpdir",
        action = "store_false", default = True,
        help = "Do not remove temporary directory upon exit")
    ap.add_argument(
        "--tmpdir", dest = "tmpdir", action = "store", type = str,
        default = None,
        help = "Directory where to place temporary files "
        "(they will not be removed upon exit; defaults to be "
        "autogenerated and removed upon exit")
    ap.add_argument("testcase", metavar = "TESTCASE|DIR", nargs = "*",
                    help = "Files describing testcases or directories"
                    " where to find them")


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser("find", help = "Find testcases")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_find)


    ap = arg_subparsers.add_parser(
        "info", help = "Print information testcases")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_info)
