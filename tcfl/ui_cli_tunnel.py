#! /usr/bin/python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage target power
---------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- power on/off/cycle targets::

    $ tcf power-on [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-off [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-cycle [TARGETSPEC [TARGETSPEC [..]]

- get power state::

    $ tcf power-get [TARGETSPEC [TARGETSPEC [..]]
    $ tcf power-ls [TARGETSPEC [TARGETSPEC [..]]


"""

import argparse
import json
import logging
import re
import sys

import commonl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_tunnel")


def _cmdline_tunnel_add(cli_args: argparse.Namespace):

    def _tunnel_add(target, cli_args):
        server_port = target.tunnel.add(
            cli_args.port, cli_args.ip_addr, cli_args.protocol)
        print("%s:%d" % (target.rtb.parsed_url.hostname, server_port))

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_rm, cli_args, only_one = True,
        iface = "power", extensions_only = [ 'power' ])



def _cmdline_tunnel_rm(cli_args: argparse.Namespace):

    def _tunnel_rm(target, cli_args):
        target.tunnel.remove(
            cli_args.port, cli_args.ip_addr, cli_args.protocol)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_rm, cli_args, only_one = True,
        iface = "power", extensions_only = [ 'power' ])



def _cmdline_tunnel_ls(_cli_args: argparse.Namespace):

    def _tunnel_list_by_target(target, _cli_args):
        for local_port, data in  target.tunnel.list().items():
            if not isinstance(data, dict):
                continue
            print("%s %s:%s %s:%s" % (
                data['protocol'],
                target.rtb.parsed_url.hostname, local_port,
                data['ip_addr'], data['port']
            ))

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_list_by_target, cli_args, only_one = True,
        iface = "power", extensions_only = [ 'power' ])



def cmdline_setup(argsp):
    ap = argsp.add_parser(
        f"tunnel-add{tcfl.ui_cli.commands_new_suffix}",
        help = "create an IP tunnel")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument("port", metavar = "PORT", action = "store", type = int,
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to TCPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None, type = str,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = _cmdline_tunnel_add)

    ap = argsp.add_parser(
        f"tunnel-rm{tcfl.ui_cli.commands_new_suffix}",
        help = "remove an existing IP tunnel")
    commonl.argparser_add_aka(argsp, "tunnel-rm", "tunnel-remove")
    commonl.argparser_add_aka(argsp, "tunnel-rm", "tunnel-delete")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument("port", metavar = "PORT", action = "store", type = int,
                    help = "Port to tunnel to")
    ap.add_argument("protocol", metavar = "PROTOCOL", action = "store",
                    nargs = "?", default = None,
                    help = "Protocol to tunnel {tcp,udp,sctp}[{4,6}] "
                    "(defaults to tcp and to IPv4)")
    ap.add_argument("ip_addr", metavar = "IP-ADDR", action = "store",
                    nargs = "?", default = None,
                    help = "target's IP address to tunnel to "
                    "(default is the first IP address the target declares)")
    ap.set_defaults(func = _cmdline_tunnel_rm)

    ap = argsp.add_parser(
        f"tunnel-ls{tcfl.ui_cli.commands_new_suffix}",
        help = "List existing IP tunnels")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_tunnel_ls)
