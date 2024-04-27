#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""
Allocation utilities
--------------------

Initialize with:

>>> import tcfl.allocation
>>> tcfl.allocation.subsystem_initialize()

(note it takes care of initializing its dependencies)

There is no asynchronous method to initialize this module.
"""

import logging

import requests

import tcfl

logger = logging.getLogger("tcfl.allocation")

_subsystem_setup = False


def server_allocs_get(_server_name: str, self: tcfl.server_c,
                      username: str = None, allocids: list = None):
    """
    List all allocations in a server

    :param str server_name: Server's name

      Note this parameter is mostly ignored; it allows the function to
      be used with :func:`tcfl.servers.run_for_each_server`.

    :param tcfl.server_c server: Object describing the server

    :param str: username: Name of the user whose allocations are to be
      removed. The special name *self* refers to the current logged in
      user for that server.

    :returns dict: dictionary keyed by Allocation ID of allocation
      data:

      >>> { ALLOCID: ALLOCDATA }

      *ALLOCDATA* is a dictionary keyed by strings of fields and
      values, fields being:

      - *creator* (str): user who created the allocation
      - *user* (str): user who owns the allocation
      - *state* (str):  state the allocation is on
      - *guests* (list[str]):  list of users who are guests in the allocation
      - *reason* (str):  reason for the allocation
      - *target_group* (str):  list of target names in the allocation,
        sparated by commas
      - *timestamp* (str): last use timestamp for the allocation in
        YYYYMMDDHHMMSS format

    """
    try:
        r = self.send_request("GET", "allocation/")
    except (Exception, requests.HTTPError) as e:
        self.log.error("%s", e)
        return {}

    # So, r is a dictionary { "ALLOCID": { ALLOCDATA } }
    #
    # ALLOCDATA is a dictionary { "FIELD1": VALUE1 } and among the fields there is:
    #
    # - creator: who created it
    # - user: who is the allocation assigned to

    if not username and not allocids:
        return r

    # filter here, as we can translate the username 'self' to the
    # user we are logged in as in the server
    filtered_r = {}
    if username == "self":
        username = self.logged_in_username()

    def _alloc_filter_by_user(allocdata, username):
        if not username:
            return False
        if username == allocdata.get('creator', None):
            return True
        if username == allocdata.get('user', None):
            return True
        return False

    for allocid_itr, allocdata in r.items():
        if _alloc_filter_by_user(allocdata, username):
            filtered_r[allocid_itr] = allocdata
        elif allocids and allocid_itr in allocids:
            filtered_r[allocid_itr] = allocdata
        else:
            self.log.info("alloc-ls: filtered out %s: %s",
                          self.url, allocdata)

    return filtered_r



def rm_server_by_allocid(
        _server_name: str, server: tcfl.server_c, allocid: str):
    """
    Remove an allocation from a server given its ID

    :param str server_name: Server's name

      Note this parameter is mostly ignored; it allows the function to
      be used with :func:`tcfl.servers.run_for_each_server`.

    :param tcfl.server_c server: Object describing the server

    :param str allocid: Allocation ID

    """
    server.send_request("DELETE", "allocation/" + allocid)



def rm_server_by_username(
        server_name: str, server: tcfl.server_c, username: str):
    """
    Remove all allocations in a server owner by a given user

    :param str server_name: Server's name

      Note this parameter is mostly ignored; it allows the function to
      be used with :func:`tcfl.servers.run_for_each_server`.

    :param tcfl.server_c server: Object describing the server

    :param str: username: Name of the user whose allocations are to be
      removed. The special name *self* refers to the current logged in
      user for that server.

    :returns int: number of allocations removed in the server
    """
    if username == "self":
        username = server.logged_in_username()
    allocids = server_allocs_get(server_name, server, username)
    for allocid in allocids:
        rm_server_by_allocid(server_name, server, allocid)
    return len(allocids)



def ls(allocids: list = None, username: str = None,
       parallelization_factor: int = -4,
       traces: bool = True):
    """
    List all allocations in all known servers

    :param list[str] allocids: (default all) list of Alloc IDs to list

    :param str: username: Name of the user whose allocations are to be
      removed. The special name *self* refers to the current logged in
      user for that server.

    :param bool traces: (optional; default *False*) do log trace
      information when detecting issues.

    :returns dict: dictionary keyed by server URL of allocation
      data:

      >>> { SERVERNAME: [ { ALLOCID: ALLOCDATA }, EXCEPTION, TB ] }

      *ALLOCDATA* is documented in :func:`server_allocs_get`.

      if a server failed, the allocid dictionary will be empty and
      *EXCEPTION* and *TB* will be set (see
      :func:`tcfl.servers.run_fn_on_each_server`).
    """
    import tcfl.servers

    return tcfl.servers.run_fn_on_each_server(
        tcfl.server_c.servers, server_allocs_get,
        allocids = allocids, username = username,
        parallelization_factor = parallelization_factor,
        traces = traces)



def subsystem_setup(*args, **kwargs):
    """
    Initialize the allocation management system in a synchronous way

    Same arguments as :func:`tcfl.servers.subsystem_setup`

    Note this will initialize all the modules it requires
    (:mod:`tcfl.config`) if not already initialized.
    """
    global _subsystem_setup
    if _subsystem_setup:
        return
    tcfl.servers.subsystem_setup(*args, **kwargs)
    logger.info("setting up allocation subsystem")
    _subsystem_setup = True
