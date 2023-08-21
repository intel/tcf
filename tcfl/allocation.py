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

import tcfl

logger = logging.getLogger("tcfl.allocation")

_subsystem_setup = False


def _server_allocs_get(_server_name: str, self: tcfl.server_c, username):
    try:
        r = self.send_request("GET", "allocation/")
    except (Exception, tcfl.ttb_client.requests.HTTPError) as e:
        self.log.error("%s", e)
        return {}

    # So, r is a dictionary { "ALLOCID": { ALLOCDATA } }
    #
    # ALLOCDATA is a dictionary { "FIELD1": VALUE1 } and among the fields there is:
    #
    # - creator: who created it
    # - user: who is the allocation assigned to

    if username:
        # filter here, as we can translate the username 'self' to the
        # user we are logged in as in the server
        filtered_r = {}
        if username == "self":
            username = self.logged_in_username()

        def _alloc_filter_by_user(allocdata, username):
            if username != None \
               and username != allocdata.get('creator', None) \
               and username != allocdata.get('user', None):
                return False
            return True

        for allocid, allocdata in r.items():
            if _alloc_filter_by_user(allocdata, username):
                filtered_r[allocid] = allocdata
            else:
                self.log.info("alloc-ls: filtered out %s: %s",
                              self.url, allocdata)

        return filtered_r

    return r


def ls(spec, username: str, parallelization_factor: int = -4,
       traces: bool = True):

    import tcfl.servers

    return tcfl.servers.run_fn_on_each_server(
        tcfl.server_c.servers, _server_allocs_get, username,
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
