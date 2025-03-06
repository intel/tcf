#! /usr/bin/python3
#
# Copyright (c) 2021-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage servers
----------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- List available servers::

    $ tcf servers

- Discover more servers, by indicating more servers and querying known
  servers for other servers they might know::

    $ tcf servers-discover [HOSTNAME]

- Delete info about a server::

    $ tcf servers-rm [HOSTNAME|URL|SERVER_AKA [...]]

- Flush/delete list of available servers::

    $ tcf servers-flush

"""

import argparse
import json
import logging
import sys

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_servers")


def _logged_in_username(_server_name, server):
    return server.logged_in_username()



def _cookies(_server_name, server,
             _cli_args: argparse.Namespace):
    return server.state_load()

def _cmdline_cookies(cli_args: argparse.Namespace):

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)
    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.servers.by_targetspec(
        cli_args.target, verbosity = verbosity)

    r = tcfl.servers.run_fn_on_each_server(
        servers, _cookies, cli_args,
        parallelization_factor = cli_args.parallelization_factor,
        traces = cli_args.traces)
    # r now is a dict keyed by server_name of tuples cookies,
    # exception, traceback
    if cli_args.json:
        d = {}
        for server_name, ( cookies, _e, _tb ) in r.items():
            d[server_name] = cookies
        json.dump(d, sys.stdout, indent = 4)
        print()
    elif cli_args.cookiejar:
        # Follow https://curl.se/docs/http-cookies.html
        # Note we don't keep the TTL field, so we set it at zero
        for server_name, ( cookies, _e, _tb ) in r.items():
            for cookie, value in cookies.items():
                print(f"{server_name}\tFALSE\t/\tTRUE\t0"
                      f"\t{cookie}\t{value}")
    else:
        d = {}
        for server_name, ( cookies, _e, _tb ) in r.items():
            d[server_name] = cookies
        if len(d) == 1:	# print less info if there is only one
            commonl._dict_print_dotted(d[server_name], separator = ".")
        else:
            commonl._dict_print_dotted(d, separator = ".")



def _cmdline_servers(cli_args: argparse.Namespace):
    import tcfl.servers
    import tcfl.targets
    # collect data in two structures, makes it easier to print at
    # different verbosity levels...yah, lazy
    d = {}
    servers = {}	# new stuff
    usernames = {}

    verbosity = cli_args.verbosity - cli_args.quietosity
    servers = tcfl.servers.by_targetspec(
        cli_args.target, verbosity = verbosity)

    # servers is now a dict of servers we care for, keyed by server URL
    if verbosity >= -1:

        r = tcfl.servers.run_fn_on_each_server(
            servers, _logged_in_username,
            parallelization_factor = cli_args.parallelization_factor,
            traces = cli_args.traces)
        # r now is a dict keyed by server_name of tuples usernames,
        # exception, traceback
        for server_name, ( username, _e, _tb ) in r.items():
            usernames[server_name] = username if username else "n/a"

    servers_sorted = {}
    for server_url in sorted(servers.keys()):
        servers_sorted[server_url] = servers[server_url]
    servers = servers_sorted

    if verbosity < -2:		# print just the AKAs
        for server in servers.values():
            print(server.aka)
    elif verbosity == -2:	# print just the hostnames
        for server in servers.values():
            print(server.parsed_url.hostname)
    elif verbosity == -1:	# print aka, url, hostname
        for server_url, server in servers.items():
            print(server.aka, server.url, usernames[server_url])
    elif verbosity == 0:	# more details in table form
        import tabulate		# lazy import, only when needed
        headers = [
            "Server",
            "URL",
            "UserID",
        ]
        table = []
        for server_url, server in servers.items():
            table.append([
                server.aka,
                server.url, usernames[server_url]
            ])
        print(tabulate.tabulate(table, headers = headers))
    elif verbosity == 1:	# add origin
        import tabulate		# lazy import, only when needed
        headers = [
            "Server",
            "Herd",
            "URL",
            "UserID",
            "Origin"
        ]
        table = []
        for server_url, server in servers.items():
            table.append([
                server.aka, "\n".join(server.herds),
                server.url, usernames[server_url], server.origin
            ])
        print(tabulate.tabulate(table, headers = headers))
    elif verbosity == 2:	# key/value
        d = {}
        for server_url, server in servers.items():
            d[server.aka] = dict(
                url = server.url,
                herds = ":".join(server.herds),
                username = usernames[server_url],
                origin = server.origin
            )
        commonl.data_dump_recursive(d)
    elif verbosity >= 2:	# JSON
        d = {}
        for server_url, server in servers.items():
            d[server.aka] = dict(
                url = server.url,
                herds = ":".join(server.herds),
                username = usernames[server_url],
                origin = server.origin
            )
        json.dump(d, sys.stdout, skipkeys = True, indent = 4)



def _cmdline_servers_discover(cli_args: argparse.Namespace):

    log_sd = logging.getLogger("server-discovery")
    tcfl.ui_cli.logger_verbosity_from_cli(log_sd, cli_args)

    server_count0 = len(tcfl.server_c.servers)
    log_sd.warning("at start I know about %d servers", server_count0)
    if cli_args.flush:
        log_sd.warning("flushing cached server list (--flush given)")
        tcfl.server_c.flush()
    else:
        log_sd.warning("keeping cached server list (--flush not given)")
    if log_sd.isEnabledFor(logging.DEBUG):
        count = 0
        for url, _server in tcfl.server_c.servers.items():
            log_sd.debug("starting server[%d]: %s", count, url)
            count += 1

    tcfl.server_c.discover(
        ssl_ignore = cli_args.ssl_ignore,
        seed_url = cli_args.items,
        seed_port = cli_args.port,
        herds_exclude = cli_args.herd_exclude,
        herds_include = cli_args.herd_include,
        loops_max = 0 if not cli_args.servers_discover else cli_args.iterations,
        max_cache_age = 0,	        # force discoverying all known servers
        ignore_cache = cli_args.flush or not cli_args.servers_cache,
        zero_strikes_max = cli_args.zero_strikes_max,
        origin = "command line",
    )
    server_count = len(tcfl.server_c.servers)
    server_delta = server_count - server_count0
    if server_delta > 0:
        log_sd.error("NOTICE: found %d new server/s"
                     " (%d total)", server_delta, server_count)
    elif len(cli_args.items) > 0:
        # we already have some servers, but found no new ones and we
        # weren't gvien any seeds;; might be an error
        log_sd.error("no new servers (%d known) from command line seed: %s",
                     server_count, ' '.join(cli_args.items))
    else:
        # were given no seed, suggest
        log_sd.error("no new servers (%d known)."
                     " You can try passing a server's name", server_count)



def _cmdline_servers_rm(cli_args: argparse.Namespace):

    log_sd = logging.getLogger("servers-rm")

    import tcfl.servers

    verbosity = tcfl.ui_cli.logger_verbosity_from_cli(log_sd, cli_args)
    tcfl.servers.subsystem_setup(verbosity = verbosity)

    for item in cli_args.items:
        found = False
        for server_url, server in tcfl.server_c.servers.items():
            if item == server_url \
               or item == server.aka \
               or item == server.parsed_url.hostname:
                found = True
                print(f"{server_url}: deleting server")
                try:
                    server.logout()
                except Exception as e:
                    log_sd.warning("%s: error logging out; ignoring: %s",
                                   server_url, e)
                try:
                    server.cache_wipe()
                except Exception as e:
                    log_sd.warning("%s: error wiping cache; ignoring: %s",
                                   server_url, e)
                try:
                    server.state_wipe()
                except Exception as e:
                    log_sd.warning("%s: error wiping state; ignoring: %s",
                                   server_url, e)
        if not found:
            log_sd.error("%s: can't delete, unknown", item)



def _cmdline_servers_flush(_args):
    tcfl.server_c.flush()



def cmdline_setup(arg_subparser):

    ap = arg_subparser.add_parser(
        "servers",
        help = "List configured/discovered servers")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_servers)


    ap = arg_subparser.add_parser(
        "servers-discover",
        help = "Discover servers")
    tcfl.ui_cli.args_verbosity_add(ap)
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


    ap = arg_subparser.add_parser(
        "servers-rm",
        help = "Remove servers from knowledge")
    tcfl.ui_cli.args_verbosity_add(ap)
    ap.add_argument(
        "items", metavar = "AKA|HOSTNAME|URL", nargs = "+",
        action = "store", default = [],
        help = "Hostnames, URLs or server AKAs to remove")
    ap.set_defaults(func = _cmdline_servers_rm)


    ap = arg_subparser.add_parser(
        "servers-flush",
        help = "Flush currently cached/known servers"
        " (might need to servers-discover after)")
    ap.set_defaults(func = _cmdline_servers_flush)



def cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "cookies",
        help = "Show login cookies (to feed into curl, etc)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "-c","--cookiejar", action = "store_true", default = False,
        help = "Print in cookiejar format"
        " (https://curl.se/docs/http-cookies.html)")
    ap.add_argument(
        "-j","--json", action = "store_true", default = False,
        help = "Print in JSON format")
    ap.set_defaults(func = _cmdline_cookies)
