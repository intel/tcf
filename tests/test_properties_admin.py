#! /usr/bin/env python3
#
# SPDX-License-Identifier: Apache-2.0
#
# (C) Copyright 2026 Intel Corporation
#
import os
import requests

import commonl.testing
import tcfl.tc


srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    local_auth=False,
    config_files=[
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip("cd")))
    ],
    errors_ignore=[
        "Traceback",
    ],
)


@tcfl.tc.tags(
    "ttbl",
    files = [ "ttbd/ttbd", "ttbd/ttbl/__init__.py" ],
    level = "basic",
)
class _test(tcfl.tc.tc_c):
    """
    Verify admin users can set protected properties, non-admin users can't
    """

    property_list = {
        "bridge_ifname": "used by QEMU and others"
    }

    def eval(self):
        base_url = ttbd.url + "/ttb-v2"
        self.report_info(f"server url is {base_url=}")
        target = "t0"

        admin_name = "user0"
        admin_password = "user0.password"
        admin_session = requests.Session()

        user_name = "user1"
        user_password = "user1.password"
        user_session = requests.Session()

        with self.subcase("login_user"):
            r = user_session.put(
                f"{base_url}/login",
                data = { "username": user_name, "password": user_password },
                verify = False,
                timeout = 30,
            )
            r.raise_for_status()
            self.report_pass("user logged in")

        with self.subcase("login_admin"):
            r = admin_session.put(
                f"{base_url}/login",
                data = { "username": admin_name, "password": admin_password },
                verify = False,
                timeout = 30,
            )
            r.raise_for_status()
            self.report_pass("admin logged in")


        for prop, description in self.property_list.items():
            with self.subcase(prop):
                with self.subcase("user"):
                    r = user_session.patch(
                        f"{base_url}/targets/{target}",
                        json = { prop: "test_value" },
                        verify = False,
                        timeout = 30,
                    )
                    if r.status_code // 2 != 4 \
                       and f"Forbidden: not enough privilege to change property {prop}" in r.text:
                        self.report_pass(
                            "user cannot set protected property as expected;"
                            " expected message in place",
                            {
                                "r.status_code": r.status_code,
                                "r.text": r.text,
                                "r.url": r.url,
                            }
                        )
                    else:
                        self.report_fail(
                            "user can set protected property; expected not",
                            {
                                "r.status_code": r.status_code,
                                "r.text": r.text,
                                "r.url": r.url,
                            })


                with self.subcase("admin"):
                    r = admin_session.patch(
                        f"{base_url}/targets/{target}",
                        json = { prop: "test_value" },
                        verify = False,
                        timeout = 30,
                    )
                    if r.status_code != 200:
                        self.report_fail(
                            "admin cannot set protected property as expected",
                            {
                                "r.status_code": r.status_code,
                                "r.text": r.text,
                            }
                        )
                    else:
                        self.report_pass(
                            "admin can set protected property as expected",
                            {
                                "r.status_code": r.status_code,
                                "r.text": r.text,
                            })
