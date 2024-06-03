#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to manage commonl data structures
-----------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- List cache directory

    $ tcf lru-cache-ls DIRECTORY

"""

import argparse
import logging
import os

import commonl

logger = logging.getLogger("commonl.ui_cli")


def _cmdline_lru_cache_ls(cli_args: argparse.Namespace):

    import pickle
    import time

    cache_dir = os.path.expanduser(cli_args.cache_dir)
    # Same as commonl._lru_cache_disk()
    cache = commonl.fs_cache_c(cache_dir, base_type = commonl.fsdb_file_c)

    # fs_cache_c is a fsdb which stores the data in files vs symlinks;
    # keys are one way hashes of args and kwargs, which we can't
    # decode and we shan't, since they might include passwords.
    #
    # values are pickled tuples ( timestamp, value [, exception] )
    #
    # see commonl.fs_cache_c.set_unlocked()
    for key, value_pickled in cache.fsdb.get_as_slist():
        if key == "lockfile":
            continue		# this we know is not valid storage
        print(f"{key}\n"
              f"   raw: {value_pickled}")
        try:
            value = pickle.loads(value_pickled)
            if isinstance(value, tuple):
                if len(value) == 2:
                    ts, r = value
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
                    print(f"   recorded on: {timestamp} ({ts})\n"
                          f"   value: {r}")
                elif len(value) == 3:
                    ts, r, ex = value
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
                    print(f"   recorded on: {ts} {timestamp}\n"
                          f"   value: {r}\n"
                          f"   exception: {ex}")
                else:
                    print(f"   [unexpected value tuple length {len(value)}]: {value}")
            else:
                print(f"   [unexpected value type {type(value)}]: {value}")
        except Exception as e:
            print(f"   can't pickle load value: {e}")
        print()



def _cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "lru-cache-ls",
        help = "Dump contents of a LRU cache disk directory, as managed"
        " by the decorator commonl.lru_cache_disk()")
    ap.set_defaults(func = _cmdline_lru_cache_ls)

    ap.add_argument(
        "cache_dir", metavar = "DIRECTORY", action = "store", default = None,
        help = "Directory where cache is stored (eg ~/.cache/tcf/socket_gethostbyaddr/)")
