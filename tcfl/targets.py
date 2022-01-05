#! /usr/bin/python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Utilities for handling targets
#

import concurrent.futures
import logging

import commonl
import tcfl

logger = logging.getLogger("target")

# FIXME: this needs to be unified with the selection mechanism in
# run.py, tc._targets_select_by_spec
def _select_by_spec(rt, spec, _kws = None):
    kws = {}
    if _kws:
        kws.update(_kws)
    origin = "cmdline"
    # We are going to modify the _kws dict, so make a copy!
    commonl.kws_update_from_rt(kws, rt)
    rt_fullid = rt['fullid']
    commonl.kws_update_from_rt(kws, tcfl.rts_flat[rt_fullid])
    rt_type = rt.get('type', 'n/a')

    # If there are no BSPs, just match on the core keywords
    if commonl.conditional_eval("target selection", kws,
                                spec, origin, kind = "specification"):
        # This remote target matches the specification for
        # this target want
        logger.info("%s (type:%s): candidate by spec w/o BSP",
                    rt_fullid, rt_type)
        return True
    logger.info("%s (type:%s): ignoring by spec w/o BSP; "
                "didn't match '%s'", rt_fullid, rt_type, spec)
    return False


def list_by_spec(spec_strings, do_all = False):
    """
    Return a list of dictionaries representing targets that match the
    specification strings

    :param list(str) spec_strings: list of strings that put together
      with a logical *and* bring the logical specification

      >>> tcfl.target_c.subsystem_init()
      >>> tcfl.target.list_by_spec([ "pos_capable and bsps.x86_64.cpu_count > 1"  ])

    :param bool do_all: (optional) include also disabled targets
      (defaults to *False*)
    """
    specs = []
    # Bring in disabled targets? (note the field is a text, not a
    # bool, if it has anything, the target is disabled
    if do_all != True:
        specs.append("( not disabled )")
    # Bring in target specification from the command line (if any)
    if spec_strings:
        specs.append("(" + ") or (".join(spec_strings) +  ")")
    spec = " and ".join(specs)

    targetl = []

    if not spec:
        # no filtering, do this fast
        for rt_fullid in tcfl.rts_fullid_sorted:
            kws = dict(tcfl.rts[rt_fullid])
            kws.update(tcfl.rts_flat[rt_fullid])
            targetl.append(kws)
        return kws

    def _select_rt(rt_fullid):
        rt = dict(tcfl.rts[rt_fullid])
        rt.update(tcfl.rts_flat[rt_fullid])
        if not _select_by_spec(rt, spec):
            return None
        return rt

    # gotta filter, will take longer
    if True:		# filter serially

        for rt_fullid in tcfl.rts_fullid_sorted:
            rt = _select_rt(rt_fullid)
            if rt:
                targetl.append(rt)

    else:		# filter parallel, not really that efficient
                        # some measurements showed
        with concurrent.futures.ThreadPoolExecutor(40) as ex:
            futures = {}
            for rt_fullid in tcfl.rts_fullid_sorted:
                futures[rt_fullid] = ex.submit(_select_rt, rt_fullid)

            for rt_fullid, future in futures.items():
                try:
                    rt = future.result()	# access triggers exception check
                    if rt:
                        targetl.append(rt)
                except Exception as e:
                    logger.error(f"{rt_fullid}: listing failed: {e}")

    return targetl
