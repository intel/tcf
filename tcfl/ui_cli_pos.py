#! /usr/bin/env python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command line interface UI to manage POS (Provisioning OS)
---------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list POS capabilities

    $ tcf pos-capability-ls

- list POS capabilities for a given target

    $ tcf pos-capability-ls [TARGETSPEC...]
"""

import argparse
import logging

import tcfl.ui_cli

logger = logging.getLogger("ui_cli_pos")


def _pos_capability_ls(target, cli_args: argparse.Namespace = None):
    import inspect
    import tcfl.pos

    # FIXME: redo this to support multiple formats based on verbosity
    # and print in the top level caller to avoid buffering issues
    for cap_name in tcfl.pos.capability_fns.keys():
        cap_value = target.kws.get(f"pos_capable.{cap_name}", None)
        cap_fn = tcfl.pos.capability_fns[cap_name].get(cap_value, None)
        if cap_value:
            print("%s.%s: %s @%s.%s" % (
                target.id, cap_name, cap_value,
                inspect.getsourcefile(cap_fn), cap_fn.__name__))
        else:
            print("%s.%s: NOTDEFINED @n/a" % (target.id, cap_name))



def _cmdline_pos_capability_ls(cli_args: argparse.Namespace):

    if not cli_args.target:
        import inspect
        import tcfl.pos
        # no target where specified, just list functions
        for name, data in tcfl.pos.capability_fns.items():
            for value, fn in data.items():
                print("%s: %s @%s.%s(): %s" % (
                    name, value, inspect.getsourcefile(fn),
                    fn.__name__, fn.__doc__))
        return 0

    # targets were specified, list for those
    import tcfl.ui_cli
    retval, _r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _pos_capability_ls, cli_args,
        projections = [ "pos", "pos_capable" ])
    return retval



def _cmdline_setup_advanced(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "pos-capability-ls",
        help = "List POS (Provisioning OS) capabilities")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_pos_capability_ls)
