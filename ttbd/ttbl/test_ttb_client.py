#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# FIXME: cache the target list's per target broker into a pickled
#   ${TCF_CACHE:-~/.tcf/cache}/BROKER.cache; use the cache instead of
#   calling target_list(); implement cache-refresh command.
# FIXME: do a python iterator over the targets
"""
Client API for accessing *ttbd*\'s REST API
"""

import sys
import unittest

import testing
import tcfl.ttb_client

class _test_target(unittest.TestCase):
    def setUp(self):
        pass

    @staticmethod
    @unittest.expectedFailure
    def test_acquire__bad_args():
        tcfl.ttb_client.rest_test_target("a")


if __name__ == "__main__":
    testing.logging_init(sys.argv)
    unittest.main()

