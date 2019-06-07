#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# This file creates a user database for local authentication
#
import ttbl.auth_localdb

ttbl.config.add_authenticator(ttbl.auth_localdb.authenticator_localdb_c(
    "Some name for the authentication scheme",
    [
        # USERNAME  PASSWORD GROUPS ('user' and/or 'admin')
        [ 'usera', 'PASSWORDA', 'user', ],
        [ 'superuserB', 'PASSWORDB', 'user', 'admin', ],
        #...
    ]))
