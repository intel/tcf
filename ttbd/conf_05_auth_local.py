#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# This file makes authenticates anyone accessing from the local machine
#
# Note it can be extended to authenticate any source IP; however, this
# is strongly discouraged. Use LDAP or localdb.

local_auth.append("127.0.0.1")
