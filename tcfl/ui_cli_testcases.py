#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command line interface UI to discover and run testcases
-------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- find testcases on PATHs or files::

    $ tcf find [PATHORFILE1 [PATHORFILE2 [...]]

- report information about testcases in paths or files::

    $ tcf info [PATHORFILE1 [PATHORFILE2 [...]]


Advanced:

- print templates to configure inventory options for widget runner's
  with parameters

    $ tcf parameters-template-print [PATHTOFILE [...]]

"""

import logging
import random
import time

import commonl
import tcfl

logger = logging.getLogger("ui_cli_testcases")



def _cmdline_report_init(args):
    # initialize reporting based on what the commandline wants

    # late imports, only if needed
    import tcfl.tc	# FIXME: move report_driver_c -> tcfl to remove include hell
    import tcfl.report_console
    import tcfl.report_jinja2

    # add reporters for logging, so if we find issues when importing
    # we'll see detailed data logged
    tcfl.tc.report_driver_c.add(
        tcfl.report_console.driver(args.verbosity - args.quietosity),
        name = "console")
    # report file writer, so we get details
    tcfl.tc.report_driver_c.add(
        tcfl.report_jinja2.driver(args.log_dir),
        name = "jinja2")



def _cmdline_tcs_find(args):

    import tcfl.discovery		# lazy imports

    tcfl.discovery.subsystem_setup(
        logdir = args.log_dir,
        tmpdir = args.tmpdir,
        remove_tmpdir = args.remove_tmpdir)
    _cmdline_report_init(args)

    discovery_agent = tcfl.discovery.agent_c()
    discovery_agent.run(
        paths = args.testcase,
        manifests = args.manifest,
        filter_spec = args.tc_filter_spec,
    )

    if not discovery_agent.tcis:
        names = [ driver.__name__ for driver in tcfl.tc_c._tc_drivers ]
        logger.error("WARNING! No testcases found"
                     f" (tried drivers: {' '.join(names)})")
    return discovery_agent.tcis



def _cmdline_find(args):

    logger.warning("FIXME: atexit handlers not yet being called by"
                   " discovery subprocesses")
    for path, tcis in _cmdline_tcs_find(args).items():
        for tci in tcis:
            print(tci.name, tci.origin if tci.origin else "")



def _axes_info_print(axes, prefix):
    if not axes:
        print(f"{prefix}Declares no axes to spin on")
        return
    print(f"{prefix}Declares {len(axes)} axes to spin on:")
    for axis, values in axes.items():
        if values:
            print(f"{prefix}   - {axis}: {values}")
        else:
            print(f"{prefix}   - {axis}: (will spin over all values in inventory)")



def _testcase_info_print(testcase):
    import textwrap

    assert isinstance(testcase, tcfl.tc_info_c)
    # Print information about a testcase
    #
    # FIXME: this needs to send a message to the discovery agent to
    # get more information from the server process; now we are just
    # dumping the tc_info_c
    #
    # FIXME: a lot of this data would come from the orchestrator, not
    # from the testcase itself, but when available, it is useful
    # information to understand what the TC would do.

    print("Testcase name: ", testcase.name)
    #if testcase.__doc__:
    #    print(testcase.__doc__)

    if testcase.result:
        print(f"  result: {testcase.result}")

    _axes_info_print(testcase.axes, "  ")

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
            _axes_info_print(role.axes, "      ")
            print()

    if testcase.parameters:
        print(f"  Testcase needs/requires {len(testcase.parameters)} parameters:\n")
        for parameter_name, parameter in testcase.parameters.items():
            if parameter['name_ui'] != parameter_name:
                name_ui = " " + parameter['name_ui']
            else:
                name_ui = ""
            if parameter['credential']:
                credential_s = "(credential)"
            else:
                credential_s = "(not a credential)"
            print(f"   - {parameter_name}:{name_ui} {credential_s} @{parameter['origin']}")
            if parameter['default']:
                print(f"     optional; default: {parameter['default']}")
            else:
                print(f"     required (no defaults)")
            print("\n".join(textwrap.wrap(
                parameter['description'], width = 60,
                subsequent_indent = "       ", initial_indent = "       ")))
            print()

    else:
        print(f"  No parameters")


    if False and testcase.axes:
        # FIXME: this needs more data digging from the permutation,
        # which at this point we might not yet have
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


    if testcase.output:
        print("  current output:")
        for line in testcase.output.splitlines():
            print("    " + line)

    if testcase.exception:
        print(f"  exception: {testcase.exception}")

    if testcase.formatted_traceback:
        print(f"  traceback:\n    {'    '.join(testcase.formatted_traceback)}")

    print()


def _cmdline_tcs_iterate(cli_args, fn: callable, *args, **kwargs):
    for path, tcis in _cmdline_tcs_find(cli_args).items():
        logger.warning(f"{path}: iterating over path {len(tcis)} TCIs")
        for tci in tcis:
            logger.warning(f"{path}: iterating over TCI {tci.name}")
            if tci.exception:
                logger.error(f"{tci.name}: {tci.exception}")
                for entry in tci.formatted_traceback:
                    for line in entry.splitlines():
                        logger.error(f"{tci.name}:  traceback: {line}")
            else:
                fn(tci, *args, **kwargs)


def _cmdline_info(args):
    _cmdline_tcs_iterate(args, _testcase_info_print)



def _testcase_parameters_template_print(testcase, mode: str):
    import datetime
    import getpass
    import json
    import socket
    import sys

    assert isinstance(testcase, tcfl.tc_info_c)

    if not testcase.parameters:
        logging.warning(f"TCI: {testcase.name} has no parameters")
        return

    if mode == "shell":
        print("#! /bin/sh -eux")
    else:
        print("#! /usr/bin/env python3")

    print(f"""\
#
# Auto-generated by:
#
#    {" ".join(sys.argv)}
#
# ran by {getpass.getuser()} @{socket.getfqdn()} on {datetime.datetime.now()}
#
""")
    if mode == "shell":
        print('''\
TARGETNAME=$1
RUNNERNAME=$2
''')
    elif mode == "ttbd":
        print("runner_name = 'RUNNERNAME'")
    else:
        raise AssertionError(f"BUG: unknown mode {mode}")


    def _emit_one(parameter: str, field: str, value):
        if mode == "shell":
            if isinstance(value, bool):
                value = f"b:{value}"
            print(f"""\
tcf property-set $TARGETNAME \\
    "runner.$RUNNERNAME.parameter.{parameter}.{field}" \\
    {value}
""")
        elif mode == "ttbd":
            print(f"""\
target.property_set(
    f"runner.{{runner_name}}.parameter.{parameter}.{field}",
    {value})\
""")


    for parameter_name, parameter in testcase.parameters.items():
        typename = parameter['type']
        _emit_one(parameter_name, "type", json.dumps(typename))
        _emit_one(parameter_name, "name_ui", json.dumps(parameter['name_ui']))
        _emit_one(parameter_name, "credential", parameter['credential'])
        if typename == "parameter_username_password_c":
            default = parameter['default']
            if default:
                if default[0]:
                    _emit_one(parameter_name, "default_user",
                              json.dumps(default[0]))
                if default[1]:
                    _emit_one(parameter_name, "default_password",
                              json.dumps(default[1]))

        elif typename == "parameter_choices_c":
            default = parameter['default']
            if default:
                _emit_one(parameter_name, "default", json.dumps(default))

            for choice_name, choice_description \
                    in parameter.get('choices', {}).items():
                _emit_one(parameter_name, f"choice.{choice_name}",
                          json.dumps(choice_description))

        else:	# any other parameter type
            default = parameter['default']
            if default:
                _emit_one(parameter_name, "default", json.dumps(default))

        print()


def _cmdline_parameters_template_print(args):
    _cmdline_tcs_iterate(
        args, _testcase_parameters_template_print,
        args.mode)



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

    ap = arg_subparsers.add_parser(
        "find", help = "Find testcases")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_find)

    ap = arg_subparsers.add_parser(
        "info", help = "Print information testcases")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_info)



def _cmdline_setup_advanced(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "parameters-template-print",
        help = "Print ttbd template configuration"
        " code to configure the widget-runner")
    ap.add_argument(
        "--ttbd", action = "store_const", dest = "mode",
        const = "ttbd", default = "ttbd",
        help = "Print templates suitable for use"
        " in ttbd config files (default)")
    ap.add_argument(
        "--shell", action = "store_const", dest = "mode",
        const = "shell",
        help = "Print templates suitable for use"
        " in shell scripts")
    _common_args_add(ap)
    ap.set_defaults(func = _cmdline_parameters_template_print)
