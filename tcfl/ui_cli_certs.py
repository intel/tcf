#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage target SSL certificates
--------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- add/download and remove certificates::

    $ tcf certs-get TARGETSPEC CERTNAME
    $ tcf certs-rm TARGETSPEC CERTNAME

- list certificates::

    $ tcf certs-ls TARGETSPEC


"""

import argparse
import logging
import sys

import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_certs")



def _cmdline_certs_get(cli_args: argparse.Namespace):

    def _certs_get(target, cli_args):
        if cli_args.prefix and cli_args.save:
            target.certs.get(cli_args.name, save = cli_args.save,
                             key_path = cli_args.prefix + ".key",
                             cert_path = cli_args.prefix + ".key")
            print(f"downloaded client certificate key"
                  f" -> {cli_args.prefix}.{{key,cert}}",
                  file = sys.stderr)
        else:
            target.certs.get(cli_args.name, save = cli_args.save)
            if cli_args.save:
                print(f"downloaded client certificate key"
                      f" -> {target.id}.{cli_args.name}.{{key,cert}}",
                      file = sys.stderr)
            else:
                logging.warning("certificates not downloaded (see --save)")

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _certs_get, cli_args, only_one = True,
        iface = "certs", extensions_only = [ "certs" ])



def _cmdline_certs_remove(cli_args: argparse.Namespace):

    def _certs_remove(target, cli_args):
        target.certs.remove(cli_args.name)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _certs_remove, cli_args, only_one = True,
        iface = "certs", extensions_only = [ "certs" ])



def _cmdline_certs_list(cli_args: argparse.Namespace):
    def _certs_list(target, _cli_args):
        print("\n".join(target.certs.list()))

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _certs_list, cli_args, only_one = True,
        iface = "certs", extensions_only = [ "certs" ])



def cmdline_setup(argsp):
    ap = argsp.add_parser("certs-get",
                          help = "Create and get a client certificate")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument("name", metavar = "NAME", action = "store",
                    type = str, help = "Name of certificate to create")
    ap.add_argument("--save", "-s", action = "store_true", default = False,
                    help = "Save the certificates")
    ap.add_argument("--prefix", "-p", metavar = "PREFIX", action = "store",
                    default = None, type = str,
                    help = "Prefix where to save them to"
                    " (defaults to TARGETNAME.CERTNAME.{key,cert})")
    ap.set_defaults(func = _cmdline_certs_get)


    ap = argsp.add_parser("certs-remove",
                          help = "Remove a client certificate")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument("name", metavar = "NAME", action = "store",
                    type = str, help = "Name of certificate to remove")
    ap.set_defaults(func = _cmdline_certs_remove)


    ap = argsp.add_parser("certs-ls",
                          help = "List available client certificates")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_certs_list)
