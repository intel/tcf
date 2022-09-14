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
