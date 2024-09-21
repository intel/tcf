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
import traceback

import commonl
import tcfl.config

logger = logging.getLogger("tcfl.servers")

_subsystem_setup = False

#: Discover more servers or only use those in tcfl.config.urls when
#: initialized?
servers_discover = True

def _discover_bare(*args, ssl_ignore = True, **kwargs):
    # this takes stuff in added by config files to tcfl.config.urls to
    # seed, stuff we saved on disk from previous runs or defaults to
    # hostname "ttbd" that is resovled

    if servers_discover == False:
        tcfl.server_c.discover(
            # this is a list of [ ( URL, ssl_ignore, origin...) ]
            seed_url = [ i[0] for i in tcfl.config.urls ],
            ssl_ignore = ssl_ignore,
            ignore_cache = True,
            loops_max = 0
        )
    else:
        tcfl.server_c.discover(*args, ssl_ignore = ssl_ignore, **kwargs)

    if not tcfl.server_c.servers:
        logger.warning(
"""
No servers available

You can:

1. Provide one or more server URLs to the command line tools with
   the --url option

2. Provide one or more server URLs to to the *servers-discover* command
   to discover more servers

3. Add to any configuration file [conf_ANYTHING.py] in any of %s with: a
   URL with:

   >>> tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)

4. Use the tcfl.servers.discover() API call in a config file or your
   app to force server discovery.

""" % ":".join(tcfl.config_path))



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
        import tcfl.targets	# dependency loop otherwise
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
        # now wipe the servers that didn't match that
        tcfl.server_c.servers = servers
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
        return fn(server_name, server, *args, **kwargs), None, None
    except Exception as e:
        # don't error this, since this might be handled by upper layers
        logger.warning("%s: exception calling %s: %s",
                       server_name, fn, e, exc_info = traces)
        return (
            None,
            e,
            # we can't pickle tracebacks, so we send them as a
            # formated traceback so we can at least do some debugging
            traceback.format_exception(type(e), e, e.__traceback__)
        )


def run_fn_on_each_server(servers: dict, fn: callable, *args,
                          serialize: bool = False, traces: bool = False,
                          parallelization_factor: int = -4,
                          **kwargs):
    """Run a function on each server in parallel

    :param callable fn: function with signature

      >>> def fn(servername: str, server: tcfl.server_c, *args, **kwargs):

      *servername* is whatever was given as key in the @servers
      argument, *server* is a server object; *args* and *kwargs* is
      what was passed to :func:`run_fn_on_each_rerver`.

    :param dict servers: dictionary keyed by server name of
      :class:`tcfl.server_c` objects. This can be
      :data:`tcfl.server_c.servers` for all servers or any other dict
      with whatever server names are chosen.

    :param int parallelization_factor: (optional, default -4, run
      four operations per processor) number of threads to use to
      parallelize the operation; use *1* to serialize.

    :param bool traces: (optional, default *True*) if log messages for
      exceptions shall include stack traces.


    :returns dict: dictionary keyed by server URL of result information:

       >>> { "SERVER.URL": [ RESULT, EXCEPTION, TRACEBACK ] }

       - *RESULT*: is what the function returned for that server's URL
         or *None* if it failed (and there is *EXCEPTION* and *TRACEBACK*)

       - *EXCEPTION*: exception object; *None* if there was no exception

       - *TRACEBACK* (list[str]): if there was an exception, a
          formatted traceback for it (since the traceback object can't
          be pickled); *None* if there was no exception
    """

    processes = min(
        len(servers),
        commonl.processes_guess(parallelization_factor))
    results = {}
    if processes == 0:
        return results

    with concurrent.futures.ProcessPoolExecutor(processes) as executor:
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



def subsystem_setup(*args, tcfl_server_c_discover_kwargs = None, **kwargs):
    """Initialize the server management system in a synchronous way

    Same arguments as :func:`tcfl.config.subsystem_setup`

    Note this will initialize all the modules it requires
    (:mod:`tcfl.config`) if not already initialized.

    Note you can pass arguments to control how the discovery process
    happens; these are the arguments to :meth:`tcfl.server_c.discover`
    and can be passed in the dict *tcfl_server_c_discover_kwargs*; for
    example, to discover just a single known server:

    >>> tcfl.servers.subsystem_setup(
    >>>     tcfl_server_c_discover_kwargs = dict(
    >>>         seed_url = ["https://SERVERNAME:5000" ],
    >>>         ignore_cache = True,
    >>>         loops_max = 0
    >>>     )
    >>> )

    This is useful if you know you only need to talk to one well-known
    server and to avoid the overhead of extra discovery.

    """
    #
    # This is currently a wee of a hack as we move stuff from
    # tcfl.config.load() here.
    #
    # ensure server subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    # ok, this is a hack because at this point, tcfl.config.setup(),
    # which is the "old way but still accepted" to initialize the API
    # also calls this but this also calls
    # tcfl.config.subsystem_setup(). So we need to remove ssl_ignore,
    # which tcfl.config.subsystem_setup() doesn't take
    # FIXME: when we move everything out of using tcfl.ttb_client()
    # and tcfl.config.setup()/load(), this won't be needed.
    if 'ssl_ignore' in kwargs:
        _kwargs = dict(kwargs)
        del _kwargs['ssl_ignore']
    else:
        _kwargs = kwargs
    tcfl.config.subsystem_setup(*args, **_kwargs)
    logger.info("setting up server subsystem")
    if tcfl_server_c_discover_kwargs == None:
        tcfl_server_c_discover_kwargs = {}
    _discover_bare(ssl_ignore = kwargs.get('ignore_ssl'),
                   **tcfl_server_c_discover_kwargs)

    _subsystem_setup = True
