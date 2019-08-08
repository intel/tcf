#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Configuration API for PDUs and other power switching equipment
--------------------------------------------------------------
"""

import urlparse
import ttbl.raritan_emx

def raritan_emx_add(url, outlets = 8, targetname = None,
                    https_verify = True, powered_on_start = None):
    """
    Add targets to control the individual outlets of a Raritan EMX PDU

    This is usually a low level tool for administrators that allows to
    control the outlets individually. Normal power control for targets
    is implemented instantiating a power controller interface as
    described in :py:class:`ttbl.raritan_emx.pci`.

    For example add to a ``/etc/ttbd-production/conf_10_targets.py``
    (or similar) configuration file:

    .. code-block:: python

       raritan_emx_add("https://admin:1234@sp6")

    yields::

      $ tcf list
      local/sp6-1
      local/sp6-2
      local/sp6-3
      local/sp6-4
      local/sp6-5
      local/sp6-6
      local/sp6-7
      local/sp6-8

    :param str url: URL to access the PDU in the form::

        https://[USERNAME:PASSWORD@]HOSTNAME

      Note the login credentials are optional, but must be matching
      whatever is configured in the PDU for HTTP basic
      authentication and permissions to change outlet state.

    :param int outlets: number of outlets in the PDU (model specific)

      FIXME: guess this from the unit directly using JSON-RPC

    :param str targetname: (optional) base name
      to for the target's; defaults to the hostname (eg: for
      *https://mypdu.domain.com* it'd be *mypdu-1*, *mypdu-2*, etc).

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are
      - *False*: power them off
      - *True*: power them on

    :param bool https_verify: (optional, default *True*) do or
      do not HTTPS certificate verification.

    **Setup instructions**

    Refer to :ref:`ttbl.raritan_emx.pci <raritan_emx_setup>`.
    """
    _url = urlparse.urlparse(url)
    if targetname == None:
        targetname = _url.hostname.split('.')[0]
    for outlet in range(1, outlets + 1):
        name = "%s-%d" % (targetname, outlet),
        ttbl.config.target_add(
            name,
            ttbl.tt.tt_power(
                name, ttbl.raritan_emx.pci(url, outlet, https_verify),
                power = powered_on_start),
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(idle_poweroff = 0))
        ttbl.config.targets[name].disable("")
