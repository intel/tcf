#! /usr/bin/env python3
#
# SPDX-License-Identifier: Apache-2.0
#
# (C) Copyright 2026 Intel Corporation
import os
import requests

import commonl
import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    local_auth = False,
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

# can't use @tcfl.tc.target(ttbd.url_spec + " and t0")
# because we are going to be playing with two users
@tcfl.tc.tags(
    "ttbl",
    # files relative to top level this testcase exercises
    files = [ 'ttbd/ttbl/store.py' ],
    objects = [ "ttbl.store.interface" ],
    level = "basic"
)
class _test(tcfl.tc.tc_c):
    """
    Verify a user cannot get a certificate file from a target
    allocated by another user (in general test a user cannot get a
    file from a target that is allocated to another user).

    """

    def eval(self):
        base_url = ttbd.url + "/ttb-v2"
        self.report_info(f"server url is {base_url=}")
        target = "t0"

        user0_user = "user0"
        user0_pass = "user0.password"
        user1_user = "user1"
        user1_pass = "user1.password"

        user0 = requests.Session()
        user1 = requests.Session()

        with self.subcase("user0_logins"):
            r = user0.put(
                f"{base_url}/login",
                data = { "username": user0_user, "password": user0_pass },
                verify = False,
                timeout = 30,
            )
            r.raise_for_status()
            self.report_pass("user0 logged in")

        with self.subcase("user0_allocates"):
            r = user0.put(
                f"{base_url}/allocation",
                json = { "queue": False, "reason": "n/a", "groups": { "group": [ target ] } },
                verify = False,
                timeout = 30,
            )
            r.raise_for_status()
            j = r.json()
            if j.get("state", None) != "active":
                raise tcfl.tc.failed_e(
                    f"user0 allocation failed: HTTP {r.status_code}: {r.text[:200]}"
                )
            self.report_pass("allocated", { "r.j": j })

        with self.subcase("user0_cert_create"):
            r = user0.put(
                f"{base_url}/targets/{target}/certs/certificate",
                data = { "name": "somecert" },
                verify = False,
                timeout = 30,
            )
            if r.status_code != 200:
                raise tcfl.tc.failed_e(
                    f"user0 cert creation failed: HTTP {r.status_code}: {r.text[:200]}"
                )
            self.report_pass("cert created")

        with self.subcase("user1_login"):
            r = user1.put(
                f"{base_url}/login",
                data = { "username": user1_user, "password": user1_pass },
                verify = False,
                timeout = 30,
            )
            r.raise_for_status()
            self.report_pass("user1 logged in")

        # user1 tries in t0 (allocated by user0) to get a t0
        # certificate or store a file in t0's certificate store
        with self.subcase("user1_certs_get"):
            r = user1.get(
                f"{base_url}/targets/{target}/certs/certificate",
                verify = False,
                timeout = 30,
            )
            if r.status_code != 400 or "tried to use busy" not in r.text:
                raise tcfl.tc.failed_e(
                    "expected cert API denial (400/...tried to use busy...);"
                    f" got {r.status_code}/{r.text[:200]}",
                    {
                        "r.status_code": r.status_code,
                        "r.t": r.text,
                    },
                )
            self.report_pass("cert read denied as expected")

        store_path = "certificates_client/somecert.key"
        with self.subcase("user1_get_cert_file"):
            r = user1.get(
                f"{base_url}/targets/{target}/store/file",
                params = { "file_path": store_path },
                verify = False,
                timeout = 30,
            )

            attachments = { "r.status_code": r.status_code, }
            try:
                attachments["r.j"] = r.json()
            except:
                attachments["r.t"] = r.text

            if r.status_code == 200:
                raise tcfl.tc.failed_e(
                    "user1 read user0 cert via store API ",
                    attachments,
                )
            elif r.status_code == 400:
                self.report_pass(
                    f"store/file blocked as expected ({r.status_code=})",
                    attachments,
                )
            else:
                self.report_error(
                    f"store/file returned unexpected status {r.status_code=}",
                    attachments,
                )
