#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.auth_localdb
import ttbl.auth_userdb
import ttbl.config
import ttbl.power

ttbl.config.add_authenticator(ttbl.auth_localdb.authenticator_localdb_c(
    "Testing user DB",
    [
        [ 'local', 'apassword', 'user', ],
        [ 'local-admin', 'apassword', 'user', 'admin' ],
    ]
))


target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'skip_cleanup' : True,
    })
target.interface_add(
    "power", ttbl.power.interface(power0 = ttbl.power.fake_c()))
