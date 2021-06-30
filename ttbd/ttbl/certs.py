#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
# use openssl req
#     -subj "/C=$CERT_COUNTRY/ST=$CERT_STATE/L=$CERT_CITY/O=$CERT_COMPANY_NAME Signing Authority/CN=$CERT_COMPANY_NAME Signing Authority"
"""
Interface to manage target specific SSL certificates
****************************************************

.. _ttbl_certs:

The target's certificate storage allows the creation of target and
allocation specific certificates and downloading them from the server
for multiple uses (eg: secure tunneling).

Note these certificates are:

- specific to each target (can't be used on another one)

- specific to each allocation (can't be used for another allocation)

- passwordless, for scripting simplicity

- meant to be used as one-time-passwords valid only for the duration
  of the target's allocation for instrumentation drivers using
  protocols that work over SSL.

**Security**

- clients can share the certificates to access whichever is needed
  from the server--however, as the target is released, the
  certificates are no longer valid.

- all the client certificates are signed with a certificate authority
  that is specific to the target and allocation

- all client certificates, server certificates and certificate
  authority are wiped when the target is released

HTTP interface
--------------

PUT /targets/TARGETID/certs/certificate -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Retrieve a named client certificate, creating it if non existing.

**Access control:** the user, creator or guests of an allocation that
has this target allocated.

**Arguments:**

- *name*: Name of the client certificate to retrieve/create

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with the following
  fields:

  - *name*: (str) certificate's name (matching the argument)
  - *created*: (bool) *True* if it was created, *False* if it
    already existed.
  - *key*: (str) private key contents
  - *cert*: (str) certificate contents

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

DELETE /targets/TARGETID/certs/certificate -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove an existing client certificate

**Access control:** the user, creator or guests of an allocation that
has this target allocated.

**Arguments:**

- *name*: Name of the client certificate to remove

**Returns:**

- On success, 200 HTTP code and an empty JSON dictionary

- On error, non-200 HTTP code and a JSON dictionary with diagnostics


GET /targets/TARGETID/certs/certificate -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

List currently created client certificates

**Access control:** the user, creator or guests of an allocation that
has this target allocated.

**Arguments:**

None

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with values:

  - *client_certificates*: list of strings with the anames of
    currently created certificates.

- On error, non-200 HTTP code and a JSON dictionary with diagnostics


"""
import os
import shutil
import subprocess

import commonl
import ttbl

class interface(ttbl.tt_interface):

    def __init__(self, key_size = 2048):
        ttbl.tt_interface.__init__(self)
        self.cert_path = None
        self.cert_client_path = None
        self.key_size = key_size


    def _target_setup(self, target, iface_name):
        # initialize and ensure no certificate is left over from
        # previous execution
        self.cert_path = os.path.join(target.state_dir, "certificates")
        self.cert_client_path = os.path.join(target.state_dir, "certificates_client")
        # the certificate storage access is read only
        target.store.target_sub_paths['certificates_client'] = False
        self._release_hook(target, True)


    def _allocate_hook(self, target, iface_name, allocdb):
        # initalize certificates once allocated, so they are available
        # to all the components that might need them
        self._setup_maybe(target)


    def _release_hook(self, target, force):
        # wipe all the certificates for this target, the allocation is
        # cancelled
        shutil.rmtree(self.cert_path, ignore_errors = True)
        shutil.rmtree(self.cert_client_path, ignore_errors = True)
        target.log.debug(f"wiped target's certificates in {self.cert_path}")


    def _setup_maybe(self, target):
        if os.path.isdir(self.cert_path) and os.path.isdir(self.cert_client_path):
            return
        # not initialized or inconsistent state, just wipe it all
        self._release_hook(target, True)
        try:
            commonl.makedirs_p(self.cert_path)
            commonl.makedirs_p(self.cert_client_path)
            # FIXME: do from python-openssl?

            # Create a Certificate authority for signing
            #
            # The duration is irrelevant since all these certificates will
            # be killed when the target is released

            allocid = target.fsdb.get("_alloc.id", "UNKNOWN")
            subprocess.run(
                f"openssl req -nodes -newkey rsa:{self.key_size}"
                f" -keyform PEM -keyout ca.key"
                f" -subj /C=LC/ST=Local/L=Local/O=TCF-Signing-Authority-{target.id}-{allocid}/CN=TTBD"
                f" -x509 -days 1000 -outform PEM -out ca.cert".split(),
                check = True, cwd = self.cert_path,
                stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
            target.log.debug(f"created target's certificate authority in {self.cert_path}")

            # Now create a server key
            subprocess.run(
                f"openssl genrsa -out server.key {self.key_size}".split(),
                stdin = None, timeout = 5,
                capture_output = True, cwd = self.cert_path, check = True)
            target.log.debug("created target's server key")

            subprocess.run(
                f"openssl req -new -key server.key -out server.req -sha256"
                f" -subj /C=LC/ST=Local/L=Local/O=TCF-Signing-Authority-{target.id}-{allocid}/CN=TTBD".split(),
                check = True, cwd = self.cert_path,
                stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
            target.log.debug("created target's server req")

            subprocess.run(
                f"openssl x509 -req -in server.req -CA ca.cert -CAkey ca.key"
                f" -set_serial 100 -extensions server -days 1460 -outform PEM"
                f" -out server.cert -sha256".split(),
                check = True, cwd = self.cert_path,
                stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
            target.log.debug("created target's server cert")
        except subprocess.CalledProcessError as e:
            target.log.error(f"command {' '.join(e.cmd)} failed: " + e.output.decode('ascii'))
            raise
        except:
            # wipe the dir on any error, to avoid having half
            # initialized state
            self._release_hook(target, True)
            raise

    client_extensions = [ "key", "req", "cert" ]

    def _client_wipe(self, name):
        # wipe without complaining if not there
        for extension in self.client_extensions:
            commonl.rm_f(os.path.join(self.cert_client_path,
                                      name + "." + extension))

    def put_certificate(self, target, who, args, _files, _user_path):
        """
        Get a client certificate, maybe creating it

        :returns dict: on success, dictionary with keys:
          - *name*: (str) the name of the certificate
          - *created*: (bool) if the cert was created new or already existed
          - *key*: (str) key data
          - *cert*: (str) certificate data
        """
        name = self.arg_get(args, 'name', str)
        if not commonl.verify_str_safe(name, do_raise = False):
            raise ValueError(
                f"{name}: invalid certificate name, only [-_a-zA-Z0-9] allowed")

        with target.target_owned_and_locked(who):

            self._setup_maybe(target)

            client_key_path = os.path.join(self.cert_client_path, name + ".key")
            client_req_path = os.path.join(self.cert_client_path, name + ".req")
            client_cert_path = os.path.join(self.cert_client_path, name + ".cert")

            if os.path.isfile(client_key_path) \
               and os.path.isfile(client_cert_path):	# already made?
                with open(client_key_path) as keyf, \
                     open(client_cert_path) as certf:
                    return dict({
                        "name": name,
                        "created": False,
                        "key": keyf.read(),
                        "cert": certf.read(),
                    })

            try:
                subprocess.run(
                    f"openssl genrsa -out {client_key_path} {self.key_size}".split(),
                    stdin = None, timeout = 5,
                    capture_output = True, cwd = self.cert_path, check = True)
                allocid = target.fsdb.get("_alloc.id", "UNKNOWN")
                subprocess.run(
                    f"openssl req -new -key {client_key_path} -out {client_req_path}"
                    f" -subj /C=LC/ST=Local/L=Local/O=TCF-Signing-Authority-{target.id}-{allocid}/CN=TCF-{name}".split(),
                    check = True, cwd = self.cert_path,
                    stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
                target.log.debug(f"{name}: created client's certificate")

                # Issue the client certificate using the cert request and the CA cert/key.
                # note we run in the self.cert_path directory, so the ca.*
                # files are there
                subprocess.run(
                    f"openssl x509 -req -in {client_req_path} -CA ca.cert"
                    " -CAkey ca.key -set_serial 101 -extensions client"
                    f" -days 365 -outform PEM -out {client_cert_path}".split(),
                    stdin = None, timeout = 5,
                    capture_output = True, cwd = self.cert_path, check = True)
            except subprocess.CalledProcessError as e:
                target.log.error(f"command {' '.join(e.cmd)} failed: {e.output}")
                self._client_wipe(name)	# don't leave things half there
                raise

            with open(client_key_path) as keyf, \
                 open(client_cert_path) as certf:
                return dict({
                    "name": name,
                    "created": True,
                    "key": keyf.read(),
                    "cert": certf.read(),
                })


    def delete_certificate(self, target, who, args, _files, _user_path):
        name = self.arg_get(args, 'name', str)
        if not commonl.verify_str_safe(name, do_raise = False):
            raise ValueError(
                "invalid certificate name, only [-_a-zA-Z0-9] allowed")
        with target.target_owned_and_locked(who):
            self._client_wipe(name)
            return dict({ })


    def get_certificate(self, target, who, _args, _files, _user_path):
        with target.target_owned_and_locked(who):
            client_certificates = set()
            if os.path.isdir(self.cert_client_path):
                for filename in os.listdir(self.cert_client_path):
                    name, extension = os.path.splitext(filename)
                    if extension[1:] not in self.client_extensions:
                        target.log.error(
                            "CERT: unknown file in client directory %s", filename)
                        continue
                    client_certificates.add(name)
            return dict(client_certificates = list(client_certificates))
