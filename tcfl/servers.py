#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""
Server handling utilities
-------------------------

Initialize with:

>>> import tcfl.servers
>>> tcfl.servers.subsystem_initialize()

(note it takes care of initializing its dependencies)

There is no asynchronous method to initialize this module.
"""

import concurrent.futures
import logging
import os

import tcfl.ttb_client		# COMPAT: FIXME remove

logger = logging.getLogger("tcfl.servers")

_subsystem_setup = False



def _discover_bare(ssl_ignore = True):
    # this takes stuff in added by config files to tcfl.config.urls to
    # seed, stuff we saved on disk from previous runs or defaults to
    # hostname "ttbd" that is resovled
    tcfl.server_c.discover(ssl_ignore = ssl_ignore)

    for _, server in tcfl.server_c.servers.items():		# create target server objects
        # COMPAT: old style ttb_client.rest_target_broker -> being
        # moved to tcfl.server_c
        rtb = tcfl.ttb_client.rest_target_broker(
            tcfl.config.state_path, server.url,
            ignore_ssl = not server.ssl_verify,
            aka = server.aka, origin = server.origin)
        tcfl.ttb_client.rest_target_brokers[server.parsed_url.geturl()] = rtb

    if not tcfl.ttb_client.rest_target_brokers:
        logger.warning(
            "No servers available; please use --url or "
            "add to a file called conf_ANYTHING.py in any of %s with:\n"
            "\n"
            "  tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)\n"
            "\n" % ":".join(tcfl.config_path))



def by_targetspec(targetspec: list = None, verbosity: int = 0):
    """
    Get all servers that offer the targets described in the target
    specification.

    :param list[str] targetspec: (optional; default all) list of
      target specificaitons.

    :returns: dict keyed by server url of server
      :class:`tcfl.server_c` objects.

    """
    if targetspec:
        # we are given a list of targets to look for their servers or
        # default to all, so pass it on to initialize the inventory
        # system so we can filter
        tcfl.targets.setup_by_spec(targetspec, verbosity, targets_all = True)

        # now for all the selected targets, let's pull their servers
        servers = {}
        # pull the server from rt[server], the server's URL, which is how
        # tcfl.server_c.servers indexes servers too
        for rt in tcfl.rts.values():
            server_url = rt['server']
            servers[server_url] = tcfl.server_c.servers[server_url]
        return servers

    # no targets, so all, just init the server discovery system
    import tcfl.servers
    tcfl.servers.subsystem_setup()
    return tcfl.server_c.servers



def _run_on_server(server_name, fn, *args,
                   traces: bool = False, **kwargs):
    # returns a tuple retval, exception
    try:
        server = tcfl.server_c.servers[server_name]
        return fn(server_name, server, *args, **kwargs), None
    except Exception as e:
        # don't error this, since this might be handled by upper layers
        logger.warning("%s: exception calling %s: %s",
                       server_name, fn, e, exc_info = traces)
        return None, e



def run_fn_on_each_server(servers: dict, fn: callable, *args,
                          serialize: bool = False, traces: bool = False,
                          **kwargs):
    """
    Run a function on each server in parallel

    :param callable fn: function with signature

      >>> def fn(servername: str, server: tcfl.server_c, *args, **kwargs):

      *servername* is whatever was given as key in the @servers
      argument, *server* is a server object; *args* and *kwargs* is
      what was passed to :func:`run_fn_on_each_rerver`.

    :param dict servers: dictionary keyed by server name of
      :class:`tcfl.server_c` objects. This can be
      :data:`tcfl.server_c.servers` for all servers or any other dict
      with whatever server names are chosen.

    :param bool serialize: (optional, default *False*) if calls to
      each server need to be run in a single thread or can be run in
      parallel (default).

    :param bool traces: (optional, default *True*) if log messages for
      exceptions shall include stack traces.
    """

    if serialize:
        threads = 1
    else:
        threads = len(servers)

    results = {}
    if threads == 0:
        return results

    with concurrent.futures.ProcessPoolExecutor(threads) as executor:
        futures = {
            # for each server, queue a thread that will call
            # _fn, who will call fn taking care of exceptions
            executor.submit(
                _run_on_server, server_name, fn, *args,
                traces = traces, **kwargs): server_name
            for server_name in servers
        }
        # and as the finish, collect status (pass/fail)
        for future in concurrent.futures.as_completed(futures):
            server_name = futures[future]
            try:
                r = future.result()
                results[server_name] = r
            except Exception as e:
                # this should not happens, since we catch in
                # _run_on_by_targetid()
                logger.error("%s: BUG! exception %s", server_name, e,
                             exc_info = traces)
                continue

        return results


def subsystem_setup(*args, **kwargs):
    """
    Initialize the server management system in a synchronous way

    Same arguments as :func:`tcfl.config.subsystem_setup`

    Note this will initialize all the modules it requires
    (:mod:`tcfl.config`) if not already initialized.
    """
    #
    # This is currently a wee of a hack as we move stuff from
    # tcfl.config.load() here.
    #
    # ensure server subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    tcfl.config.subsystem_setup(*args, **kwargs)
    logger.info("setting up server subsystem")
    _discover_bare(ssl_ignore = kwargs.get('ignore_ssl'))

    _subsystem_setup = True
