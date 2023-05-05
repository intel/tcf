#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Interface to manage target specific SSL certificates
----------------------------------------------------

See :ref:`details <ttbl_certs>`

"""
import collections
import contextlib
import inspect
import logging
import os
import shutil
import sys
import time

import commonl
from . import tc



class extension(tc.target_extension_c):

    def __init__(self, target):
        tc.target_extension_c.__init__(self, target)
        if not 'certs' in target.rt.get('interfaces', []):
            raise self.unneeded


    def get(self, name: str,
            save: bool = False, key_path: str = None, cert_path:str = None):
        """Retrieve a certificate, creating it if non-existing

        :param str name: name of the client certificate

        :param bool save: (default *False*) save both the private key
          and certificate to disk (to default file names
          *TARGETNAME.NAME.{key|cert}*.

        :param str key_path: (default *None*) if specified, file name
          where to save the private key.

        :param str key_path: (default *None*) if specified, file name
          where to save the certificate.

        :returns dict: dictionary with the following fields:
          - *name*: (str) the name of the certificate
          - *created*: (bool) if the cert was created new or already existed
          - *key*: (str) key data
          - *cert*: (str) certificate data
        """
        assert isinstance(name, str), \
            "name: expected string, got {type(name)}"
        assert isinstance(save, bool), \
            "save: expected bool, got {type(save)}"
        assert key_path == None or isinstance(key_path, str), \
            "key_path: expected None or string, got {type(key_path)}"
        assert cert_path == None or isinstance(cert_path, str), \
            "cert_path: expected None or string, got {type(cert_path)}"

        self.target.report_info(f"{name}: getting", dlevel = 3)
        r = self.target.ttbd_iface_call("certs", "certificate", method = "PUT",
                                        name = name)

        if save and key_path == None:
            key_path = f"{self.target.id}.{name}.key"

        if key_path:
            with open(key_path, "w") as keyf:
                keyf.write(r['key'])
            self.target.report_info(f"CERT {name} key -> {key_path}", dlevel = 2)

        if save and cert_path == None:
            cert_path = f"{self.target.id}.{name}.cert"
        if cert_path:
            with open(cert_path, "w") as certf:
                certf.write(r['cert'])
            self.target.report_info(f"CERT {name} cert -> {cert_path}", dlevel = 2)

        if not cert_path and not key_path:
            self.target.report_info(f"CERT {name} gotten", dlevel = 2)
        return r


    def remove(self, name):
        """
        Remove a named client certificate

        :param str name: name of the client certificate

        """
        self.target.report_info(f"{name}: deleting", dlevel = 3)
        self.target.ttbd_iface_call("certs", "certificate", method = "DELETE",
                                    name = name)
        self.target.report_info(f"{name}: deleted", dlevel = 2)


    def list(self):
        """
        List existing client certificates

        :returns list(str): list of certificate names
        """
        self.target.report_info(f"listing", dlevel = 3)
        r = self.target.ttbd_iface_call("certs", "certificate", method = "GET")
        self.target.report_info(f"listed: {r}", dlevel = 2)
        return r.get("client_certificates", [])


    def _healthcheck(self):
        # not much we can do here without knowing what the interfaces
        # can do, we can start and stop them, they might fail to start
        # since they might need the target to be powered on
        target = self.target
        testcase = target.testcase

        for i in range(10):
            name = "cert%d" % i
            with testcase.subcase(name):
                with testcase.subcase("creation"):
                    self.get(name)
                    target.report_pass("creation works")

                with testcase.subcase("check-exists"):
                    l = self.list()
                    if name in l:
                        target.report_pass(f"created '{name}' listed")
                    else:
                        target.report_fail(f"created '{name}' not listed")

                with testcase.subcase("save"):
                    self.get(name, save = True)
                    target.report_pass(f"save worked")

                with testcase.subcase("save_key"):
                    commonl.rm_f(f"{target.tmpdir}.{name}.key")
                    self.get(name, key_path = f"{target.tmpdir}.{name}.key")
                    if os.path.isfile(f"{target.tmpdir}.{name}.key"):
                        target.report_pass(f"save key worked")
                    else:
                        target.report_fail(f"save key: no file?")

                with testcase.subcase("save_cert"):
                    commonl.rm_f(f"{target.tmpdir}.{name}.cert")
                    self.get(name, cert_path = f"{target.tmpdir}.{name}.cert")
                    if os.path.isfile(f"{target.tmpdir}.{name}.cert"):
                        target.report_pass(f"save cert worked")
                    else:
                        target.report_fail(f"save cert: no file?")

                with testcase.subcase("removal"):
                    self.remove(name)
                    target.report_pass("removal works")

                with testcase.subcase("check-removed"):
                    l = self.list()
                    if name in l:
                        target.report_fail(f"removed '{name}' is still listed")
                    else:
                        target.report_pass(f"removed '{name}' not listed")
