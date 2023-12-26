#! /usr/bin/python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage tunnels to targets
---------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- add or create tunnels

    $ tcf tunnel-add TARGETSPEC PORT [PROTOCOL] [IP-ADDR]
    $ tcf tunnel-rm TARGETSPEC PORT [PROTOCOL] [IP-ADDR]

- list tunnels::

    $ tcf tunnel-ls [TARGETSPEC [TARGETSPEC [..]]


"""

import argparse
import logging

import commonl
import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_tunnel")



def _tunnel_add(target, cli_args):
    server_port = target.tunnel.add(
        cli_args.port, cli_args.ip_addr, cli_args.protocol)
    print(f"{target.parsed_url.hostname}:{server_port}")

def _cmdline_tunnel_add(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_add, cli_args,  cli_args,
        only_one = True,
        iface = "tunnel", extensions_only = [ "tunnel" ],
        projections = [ "interconnects" ])[0]



def _tunnel_rm(target, cli_args):
    target.tunnel.remove(
        cli_args.port, cli_args.ip_addr, cli_args.protocol)

def _cmdline_tunnel_rm(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_rm, cli_args, cli_args,
        only_one = True,
        iface = "tunnel", extensions_only = [ "tunnel" ],
        projections = [ "interconnects" ])[0]



def _tunnel_list_by_target(target, _cli_args):
    for local_port, data in  target.tunnel.list().items():
        if not isinstance(data, dict):
            continue
        try:
            print(f"{data['protocol']}"
                  f" {target.server.parsed_url.hostname}:{local_port}"
                  f" {data['ip_addr']}:{data['port']}")
        except KeyError:
            pass	# ignore, bad data stored

def _cmdline_tunnel_ls(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _tunnel_list_by_target, cli_args, cli_args,
        only_one = True,
        iface = "tunnel", extensions_only = [ "tunnel" ],
        projections = [ "interconnects" ])[0]



def cmdline_setup(argsp):

    ap = argsp.add_parser(
        f"tunnel-add",
        help = "create an IP tunnel")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
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
        f"tunnel-rm",
        help = "remove an existing IP tunnel")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
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
        f"tunnel-ls",
        help = "List existing IP tunnels")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_tunnel_ls)
