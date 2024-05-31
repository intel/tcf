#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command Line Interface helpers
------------------------------

These are helpers to assist in common tasks when creating command line
interfaces.
"""
import argparse
import concurrent
import logging
import numbers
import traceback

import commonl
import tcfl.targets

logger = logging.getLogger("ui_cli")

# when replacing an old command implementation with a new one, append
# this in the name so we can switch them  from the environment (see
# ../tcf handing env variable TCF_NEW_COMMANDS
commands_old_suffix = ""
commands_new_suffix = "2"


def args_verbosity_add(ap: argparse.Namespace):
    """
    Add command line options for verbosity control (*-v* and *-q*) to
    a argument parser

    :param argparse.Namespace ap: arg parse object
    """
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Display more progress information")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Display less progress information")



def args_targetspec_add(
        ap: argparse.Namespace, targetspec_n = False, nargs = None,
        argspec: list = [ 'target' ]):
    """Add command line options for processing target specification
    control (*TARGETSPECs*) to an argument parser

    :param argparse.Namespace ap: arg parse object

    :param targetspec_n: (optional, default *False*)
      number of target specficiations that must be present:

      - *False*: zero or more

      - *True*: one or more

      - integer: exactly N

    :param nargs: (str, int) passed directly to
      :meth:`argparse.ArgumentParser.add_argument`, overriding any
      calculation made by `targetspec_n`. This is useful when we only
      need one command line argument to specify targets but we know it
      can fold into multiple targets that need
      parallelization.

      Usually set to *1*.

    :param bool argspec: (optional; default *['target']*) how to
      specify target filtering options arguments.

      Defaults to a *target* optional parameter. To make them be as
      part of a -t or --target:

      >>> argspec = [ "-t", "--target" ], nargs = 1

      WARNING! Usually you want *nargs = 1* also when doing this

    """
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    # careful testing here bool True compares equal to one, and when
    # we are an integer one is when we want to disable parallelization
    # -- so this is why we test like this
    if isinstance(targetspec_n, bool) or targetspec_n > 1:
        ap.add_argument(
            "--serialize",
            action = "store_const", dest = "parellization_factor", const = 1,
            help = "Serialize (don't parallelize) the operation on"
            " multiple targets")
        ap.add_argument(
            "--parallelization-factor",
            action = "store", type = int, default = -4, metavar = "N",
            help = "(xu) parallelization factor (1: serialize;"
            " > 1: number of threads to use;"
            " 0: use as many threads as CPUs available;"
            " -N: use as many threads as CPUs available times N"
            " [defaults to %(default)d]"
        )
    ap.add_argument(
        "--help-fieldnames",
        action = tcfl.ui_cli_targets.argparser_action_help_fieldnames, nargs = 0,
        help = "Display all fields in the inventory")
    if nargs != None:
        nargs = nargs
    elif isinstance(targetspec_n, bool):
        if targetspec_n:
            nargs = "+"
        else:
            nargs = "*"
    elif isinstance(targetspec_n, numbers.Integral) and targetspec_n > 0:
        nargs = int(targetspec_n)
    else:
        raise ValueError(
            f"targetspec_n: invalid; expected True, False or positive integer"
            f" got {type(targetspec_n)}")

    if argspec != [ "target" ]:
        kwargs_dest = { "dest": "target" }
    else:
        kwargs_dest = { }
    ap.add_argument(
        *argspec,
        metavar = "TARGETSPEC", action = "store", **kwargs_dest,
        nargs = nargs,
        help = "Target's name/s or a general target specification"
        " which might include values from the inventory, etc, in single"
        " quotes (eg: \"id:'STR'\" for all targets with STR in the name"
        " or \"ram.size_gib >= 2 and not type:'^qemu.*'\" for all"
        " machines with more than 2GiB of memory and not of QEMU type)")



def logger_verbosity_from_cli(log, cli_args: argparse.Namespace) -> int:
    """
    Set a loggers verbosity based on what the command line (-v and -q) said

    :param log: logging object (has .setLevel)

    :param argparser.Namespace: command line arguments parsed with
      :mod:`argparse`; was given options *verbosity* and *quietosity*
      with :func:`args_verbosity_add`
    :returns int: verbosity level
    """
    verbosity = getattr(cli_args, "verbosity", 0) - getattr(cli_args, "quietosity", 0)
    levels = [ logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG ]
    # now translate that to logging's module format
    # server-discovery -> tcfl.log_sd
    if verbosity >= len(levels):
        verbosity = len(levels) - 1
    log.setLevel(levels[verbosity])
    return verbosity


def run_fn_on_each_targetspec(
        fn: callable, cli_args: argparse.Namespace,
        *args,
        iface: str = None,
        # COMPAT: removing list[str] so we work in python 3.8
        ifaces: list = None,
        # COMPAT: removing list[str] so we work in python 3.8
        extensions_only: list = None,
        only_one: bool = False,
        one_per_server: bool = False,
        projections = None, targets_all = None,
        **kwargs) -> tuple:
    """Initialize the target discovery and run a function on each target
    that matches a specification

    See :func:'tcfl.targets.run_fn_on_each_targetspec` for arguments;
    the only difference is this function takes most arguments as CLI
    arguments and the return value.

    :param argparse.Namespace cli_args:

      Initialized with :func:`tcfl.ui_cli.args_targetspec_add`

      - *target*: (optional; default *all*) :ref:`target
        specifications<targetspec>`

      - *all*: (optional; default *False*) consider also disabled targets.

      - *parallelization-factor*: (optional) how many threads to run
        per CPU.

      - *serialize*: (optional; default *False*) force the execution of
        fn to be serialized on each target (versus default that runs
        them in parallel)

    :returns: result of the overall operation, a tuple of *(int, dict)*:

      - 0 if all functions executed ok
      - 1 some functions failed
      - 2 all functions failed

      the dict is a dictionary keyed by server id with values being
      the return value of the function and possibly an exception and
      traceback. See :func:`tcfl.targets.run_fn_on_each_targetspec`
      for details.

    will log results

    """
    retval = 0

    if targets_all == None:
        targets_all = cli_args.all

    if getattr(cli_args, "serialize", False):
        # the serialize CLI options gets only added if the command
        # is allowed to have more than one target
        cli_args.parallelization_factor = 1

    r = tcfl.targets.run_fn_on_each_targetspec(
        fn, cli_args.target, *args,
        iface = iface, ifaces = ifaces, extensions_only = extensions_only,
        only_one = only_one,
        one_per_server = one_per_server,
        projections = projections,
        targets_all = targets_all,
        verbosity = cli_args.verbosity - cli_args.quietosity,
        # if the args don't have parallelization factor, this is a
        # single target operation, so serialize
        parallelization_factor = getattr(cli_args, "parallelization_factor", 1),
        **kwargs)

    if not r:
        logger.error(
            f"No targets match the specification (might be disabled, try -a):"
            f" {' '.join(cli_args.target)}")
        return 0, {}

    # r is a dictionaky of ( result, exception ) keyed by targetid
    retval = 0
    for targetid, ( _result, exception, tb ) in r.items():
        if exception != None:
            msg = str(exception.args[0])
            if cli_args.traces:
                tb = "\n" + "".join(tb)
            else:
                tb = ""

            if targetid in msg:	# don't print target/id...
                logger.error(msg + tb)
            else:			# ...if already there
                logger.error(targetid + ": " + msg + tb)
            retval += 1

    if retval == len(r):	# all failed
        retval = 2
    if retval == 0:		# none failed
        retval = 0
    else:
        retval = 1		# some failed
    return retval, r



def run_fn_on_each_server(
        servers: dict,
        fn: callable, cli_args: argparse.Namespace,
        *args, logger = logging,
        **kwargs):
    """Initialize the target discovery and run a function on each target
    that matches a specification

    See :func:'tcfl.targets.run_fn_on_each_targetspec` for arguments;
    the only difference is this function takes most arguments as CLI
    arguments and the return value.

    :param argparse.Namespace cli_args:

      Initialized with :func:`tcfl.ui_cli.args_targetspec_add`

      - *target*: (optional; default *all*) :ref:`target
        specifications<targetspec>`

      - *all*: (optional; default *False*) consider also disabled targets.

      - *parallelization-factor*: (optional) how many threads to run
        per CPU.

      - *serialize*: (optional; default *False*) force the execution of
        fn to be serialized on each target (versus default that runs
        them in parallel)

    :returns: result of the overall operation, a tuple of *(int, dict)*:

      - 0 if all functions executed ok
      - 1 some functions failed
      - 2 all functions failed

      the dict is a dictionary keyed by server id with values
      being the return value of the function.

    will log results

    """

    import tcfl.servers
    tcfl.servers.subsystem_setup()

    r = tcfl.servers.run_fn_on_each_server(
        servers, fn, cli_args, *args,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces,
        **kwargs)
    # r now is a dict keyed by server_name of tuples usernames,
    # exception

    retval = 0
    for server_name, ( _result, exception, ex_tb ) in r.items():
        if exception != None:
            msg = str(exception.args[0])
            if cli_args.traces:
                # need to do like this otherwise if ex_tb has %s, it
                # gets confused; so yeah we just escape it %. Better way?
                logger.error("%s: %s:\n   "
                             + "   ".join(ex_tb).replace("%", "%%"),
                             server_name, msg)
            else:
                logger.error("%s: %s", server_name, msg)

            retval += 1
    if retval == len(r):
        retval = 2
    if retval == 0:
        retval = 1
    retval = 0
    return retval, r
