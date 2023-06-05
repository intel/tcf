#! /usr/bin/python3
#
# Copyright (c) 2017-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to flash JTAGS, EEPROMs, firmwares...
---------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list destinations that can be flashed::

    $ tcf images-ls TARGETSPEC


"""
import argparse
import sys

import tcfl.ui_cli



def _images_list(target, _cli_args):
    return target.images.list()

def _cmdline_images_ls(cli_args: argparse.Namespace):

    r = tcfl.ui_cli.run_fn_on_each_targetspec(
        _images_list, cli_args,
        iface = "images", extensions_only = [ 'images' ])

    verbosity = cli_args.verbosity - cli_args.quietosity
    # r now is a dict keyed by target_name and tuples of images an
    # maybe an exception, which we don't cavre for

    d = {}
    for targetid, ( images, _e ) in r.items():
        d[targetid] = images

    if verbosity == 0:
        if len(d) == 1:
            # there is only one, print a simple liust
            print(" ".join(d[targetid]))
        else:
            for targetid, v in d.items():
                print(f"{targetid}: " + " ".join(d[targetid]))
    elif verbosity == 1:
        if len(d) == 1:
            # there is only one, print a simple liust
            print("\n".join(d[targetid]))
        else:
            for targetid, v in d.items():
                for dest in v:
                    print(f"{targetid}: {dest}")
    elif verbosity == 2:
        import commonl
        commonl.data_dump_recursive(d)
    elif verbosity == 3:
        import pprint
        pprint.pprint(d, indent = True)
    elif verbosity > 3:
        import json
        json.dump(d, sys.stdout, indent = 4)
        print()
    sys.stdout.flush()



def _cmdline_setup(arg_subparser):

    ap = arg_subparser.add_parser(
        f"images-ls{tcfl.ui_cli.commands_new_suffix}",
        help = "List destinations that can be flashed in this target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_images_ls)
