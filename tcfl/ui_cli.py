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

import commonl

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
        ap: argparse.Namespace, targetspec_n = False):
    """
    Add command line options for processing target specification
    control (*TARGETSPECs*) to an argument parser

    :param argparse.Namespace ap: arg parse object

    :param targetspec_n: (optional, default *False*)
      number of target specficiations that must be present:

      - *False*: zero or more

      - *True*: one or more

      - integer: exactly N

    """
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    if targetspec_n != 1:
        ap.add_argument(
            "--serialize", action = "store_true", default = False,
            help = "Serialize (don't parallelize) the operation on"
            " multiple targets")
    if isinstance(targetspec_n, bool):
        if targetspec_n:
            nargs = "+"
        else:
            nargs = "*"
    elif isinstance(targetspec_n, numbers.Integral) and targetspec_n > 0:
        nargs = int(targetspec_n)
    else:
        raise ValueError(
            f"targetspec_n: invalid; expeted True, False or positive integer"
            f" got {type(targetspec_n)}")

    ap.add_argument(
        "target",
        metavar = "TARGETSPEC", action = "store",
        nargs = nargs,
        help = "Target's name/s or a general target specification "
        "which might include values from the inventory, etc, in single"
        "quotes (eg: 'ram.size_gib >= 2 and not type:\"^qemu.*\"')")



def run_fn_on_each_targetspec(
        fn: callable, cli_args: argparse.Namespace,
        *args,
        # COMPAT: removing list[str] so we work in python 3.8
        iface: str = None, extensions_only: list = None,
        only_one: bool = False,
        projections = None,
        **kwargs):
    """Initialize the target discovery and run a function on each target
    that matches a specification

    This is mostly used to quickly implement CLI functionality, which
    all follows a very common pattern; see for example
    :download:`ui_cli_power.py`.

    :param callable fn: function to call, with the signature::

        >>> def fn(target: tcfl.tc.target_c, cli_args: argparse.Namespace, *args, **kwargs):
        >>>     ...

    :param argparse.Namespace cli_args:

      Initialized with :func:`args_targetspec_add`

      - *target*: (optional; default *all*) :ref:`target
        specifications<targetspec>`

      - *all*: (optional; default *False*) consider also disabled targets.

      - *serialize*: (optional; default *False*) force the execution of
        fn to be serialized on each target (versus default that runs
        them in parallel)

    :param bool only_one: (optional; default *False*) ensure the
      target specification resolves to a single target, complain
      otherwise.

    :param list[str] projections: list of fields to download from the
      inventory; normally this function tries to download as little a
      possible (faster), including:

      - *id*
      - *disabled* state
      - *type*

      If an interface, was specified, also that interface is
      downloaded:

      - *interfaces.NAME*

      Any extra fields (and their subfields) specified here are also
      downloaded; eg:

      >>> [ "instrumentation", "pci" ]

    :param *args: extra arguments for *fn*

    :param **kwargs: extra keywords arguments for *fn*

    *iface* and *extensions_only* same as :meth:`tclf.tc.target_c.create`.

    :returns int: 0 if all functions executed ok, not 0 if any
      failed. Errors will be logged.

    """
    import tcfl.targets
    import tcfl.tc

    with tcfl.msgid_c("ui_cli"):

        project = { 'id', 'disabled', 'type', 'interfaces.' + iface }
        if projections:
            commonl.assert_list_of_strings(projections,
                                           "projetions", "field")
            for projection in projections:
                project.add(projection)
        # Discover all the targets that match the specs in the command
        # line and pull the minimal inventories as specified per
        # arguments
        tcfl.targets.setup_by_spec(
            cli_args.target, cli_args.verbosity - cli_args.quietosity,
            project = project,
            targets_all = cli_args.all)

        # FIXMEh: this should be grouped by servera, but since is not
        # that we are going to do it so much, (hence the meh)
        targetids = tcfl.targets.discovery_agent.rts_fullid_sorted
        if not targetids:
            logger.error(f"No targets match the specification: {cli_args.target}")
            return 1
        if only_one and len(targetids) > 1:
            logger.error(
                f"please narrow down target specification"
                f" {cli_args.target}; it matches more than one target: "
                + " ".join(tcfl.targets.discovery_agent.rts_fullid_sorted ))
            return 1
        if getattr(cli_args, "serialize", False):
            # the serialize CLI options gets only added if the command
            # is allowed to have more than one target
            threads = 1
        else:
            threads = len(targetids)

        logger.warning(f"targetspec resolves to {len(targetids)} targets")

        def _run_on_by_targetid(targetid):
            # call the function on the target; note we create a target
            # object for the targetid and give it to the function, so
            # they don't have to do it.
            try:
                target = tcfl.tc.target_c.create(
                    targetid,
                    iface = iface, extensions_only = extensions_only,
                    target_discovery_agent = tcfl.targets.discovery_agent)
                return fn(target, cli_args, *args, **kwargs)
            except Exception as e:
                msg = str(e.args[0])
                if targetid in msg:	# don't print target/id...
                    logger.error(msg, exc_info = cli_args.traces)
                else:			# ...if already there
                    logger.error(f"{targetid}: {msg}",
                                 exc_info = cli_args.traces)
                return 1

        result = 0
        with concurrent.futures.ThreadPoolExecutor(threads) as executor:
            futures = {
                # for each target id, queue a thread that will call
                # _run_on_by_targetid(), who will call fn taking care
                # of exceptions
                executor.submit(
                    _run_on_by_targetid, targetid, *args, **kwargs): targetid
                for targetid in targetids
            }
            # and as the finish, collect status (pass/fail)
            for future in concurrent.futures.as_completed(futures):
                targetid = futures[future]
                try:
                    r = future.result()
                    if r == None:	# bleh, because fn will miss it
                        r = 0
                    result |= r
                except Exception as e:
                    # this should not happens, since we catch in
                    # _run_on_by_targetid()
                    logger.error(f"{targetid}: BUG! exception {e}",
                                 exc_info = cli_args.traces)
                    continue
        return result
