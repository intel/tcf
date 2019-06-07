#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# This file defines authentication against LDAP servers for
# users that are on the given groups
#
import ttbl.config
import ttbl.auth_ldap
import ttbl.auth_localdb

ttbl.config.add_authenticator(ttbl.auth_ldap.authenticator_ldap_c(
    "ldap://LDAPHOST:LDAPPORT",
    roles = {
        'user': {
            'users': [],
            'groups': [
                "GROUP1",
                "GROUP2"
                # ...
            ]
        },
        'admin': {
            'users': [],
            'groups': [
                "GROUP3",
                "GROUP4",
                # ...
            ]
        }
    }))
