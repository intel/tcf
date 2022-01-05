#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Command line interface UI to manage servers

import concurrent.futures
import json
import logging
import pprint

import tabulate

import commonl
import tcfl

logger = logging.getLogger("server")

def _cmdline_servers(args):
    # collect data in two structures, makes it easier to print at
    # different verbosity levels...yah, lazy
    servers = {}

    if args.targets:
        # a target? initialize targets first, basic init
        tcfl.target_c.subsystem_initialize()
        for target_name in args.targets:
            try:
                rt = tcfl.target_c.get_rt_by_id(args.target)
                url = rt['server']
                logger.info(f"{args.target} is in server {url}")
                servers[url] = tcfl.server_c.servers[url]
            except IndexError as e:
                logger.error("%s: invalid target" % target_name)
    else:
        servers = tcfl.server_c.servers

    username = {}
    if args.verbosity >= 0:

        with concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers)) as ex:
            futures = {}
            for server in tcfl.server_c.servers.values():
                futures[server] = ex.submit(server.logged_in_username)

            for server, future in futures.items():
                try:
                    username[server] = future.result()
                except Exception as e:
                    logger.error(f"{server.url}: finding logged-in user failed: {e}")
                    username[server] = "n/a"

    verbosity = args.verbosity - args.quietosity

    def _to_dict(servers):
        d = {}
        for server in servers.values():
            d[server.aka] = {
                "url": server.url,
                "userid": username.get(server, "n/a"),
                "origin": server.origin
            }
        return d

    if verbosity < -1:
        for server in servers.values():
            print(server.aka)
    elif verbosity == -1:
        for server in servers.values():
            print(server.parsed_url.hostname)
    elif verbosity == 0:
        for aka, url, username, _origin in r:
            print(aka, url, username)
    elif verbosity in ( 1, 2 ):
        headers = [
            "Server",
            "URL",
            "UserID",
            "Origin"
        ]
        table = []
        for server in servers.values():
            table.append([
                server.aka,
                server.url,
                username.get(server, "n/a"),
                server.origin
            ])
        print(tabulate.tabulate(table, headers = headers))
    elif verbosity == 2:
        commonl.data_dump_recursive(_to_dict(servers))
    elif verbosity == 3:
        pprint.pprint(_to_dict(servers))
    elif verbosity >= 4:
        print(json.dumps(_to_dict(servers), skipkeys = True, indent = 4))


def _cmdline_servers_flush(_args):
    log_sd = logging.getLogger("server-discovery")
    log_sd.setLevel(logging.INFO)
    tcfl.server_c.flush()


def _cmdline_servers_discover(args):
    # adjust logging level of server-discovery
    # -qqqq -vvvvvv -> -vvv
    verbosity = args.verbosity - args.quietosity
    levels = [ logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG ]
    # now translate that to logging's module format
    # server-discovery -> tcfl.log_sd
    log_sd = logging.getLogger("server-discovery")
    if verbosity >= len(levels):
        verbosity = len(levels) - 1
    log_sd.setLevel(levels[verbosity])

    if args.flush:
        log_sd.warning("flushing cached server list (--flush given)")
        tcfl.server_c.flush()
    else:
        log_sd.warning("keeping cached server list (--flush not given)")
    current_server_count = len(tcfl.server_c.servers)
    log_sd.warning(f"starting with {current_server_count} server/s")
    if log_sd.isEnabledFor(logging.DEBUG):
        count = 0
        for url, _server in tcfl.server_c.servers.items():
            log_sd.debug(f"starting server[{count}]: {url}")
            count += 1

    tcfl.server_c.discover(
        ssl_ignore = args.ssl_ignore,
        seed_url = args.items,
        seed_port = args.port,
        herds_exclude = args.herd_exclude,
        herds_include = args.herd_include,
        loops_max = args.iterations,
        max_cache_age = 0,	        # force discoverying all known servers
        ignore_cache = args.flush,
        zero_strikes_max = args.zero_strikes_max,
        origin = "command line",
    )
    log_sd.warning(f"found {len(tcfl.server_c.servers)} server/s")


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "servers",
        help = "List configured/discovered servers")
    commonl.argparser_add_aka(arg_subparsers, "servers", "server-ls")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q list of shortname, url and username, "
        "-qq the hostnames, -qqq the shortnames"
        "; all one per line")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(none is a table, -v table with more details, "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.add_argument(
        "targets", metavar = "TARGETNAMES", nargs = "*",
        action = "store", default = None,
        help = "List of targets for which we want to find server"
        " information (optional; defaults to all)")
    ap.set_defaults(func = _cmdline_servers)

    ap = arg_subparsers.add_parser(
        "servers-flush",
        help = "Flush currently cached/known servers")
    ap.set_defaults(func = _cmdline_servers_flush)

    ap = arg_subparsers.add_parser(
        "servers-discover",
        help = "Discover servers")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q list of shortname, url and username, "
        "-qq the hostnames, -qqq the shortnames"
        "; all one per line")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 1,
        help = "Increase verbosity of progress info [%(default)d] ")
    ap.add_argument(
        "--iterations", "-e", type = int, metavar = "MAX_LOOPS",
        action = "store", default = 10,
        help = "Maximum number of iterations [%(default)d]")
    ap.add_argument(
        "--zero-strikes-max", "-z", type = int, metavar = "MAX",
        action = "store", default = 4,
        help = "Stop after this many iterations [%(default)d] finding"
        " no new servers")
    ap.add_argument(
        "--flush", "-f", action = 'store_true', default = False,
        help = "Flush existing cached entries before")
    ap.add_argument(
        "--ssl-ignore", "-s", action = 'store_false', default = True,
        help = "Default to ignore SSL validation [False]")
    ap.add_argument(
        "--port", "-p", action = 'store', type = int, default = 5000,
        help = "Default port when none specified %(default)s")
    ap.add_argument(
        "--herd-exclude", "-x", metavar = "HERDNAME", action = 'append',
        default = [], help = "Exclude herd (can be given multiple times)")
    ap.add_argument(
        "--herd-include", "-i", metavar = "HERDNAME", action = 'append',
        default = [], help = "Include herd (can be given multiple times)")
    ap.add_argument(
        "items", metavar = "HOSTNAME|URL", nargs = "*",
        action = "store", default = [],
        help = "List of URLs or hostnames to seed discovery"
        f" [{' '.join(tcfl.server_c._seed_default.keys())}]")
    ap.set_defaults(func = _cmdline_servers_discover)
