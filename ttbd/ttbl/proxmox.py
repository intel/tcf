#! /usr/bin/env python3
#
# Copyright (c) 2026 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Module with drivers used to interact with Proxmox virtualization managers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

https://www.proxmox.com/
"""
import requests
import urllib.parse

import commonl
import ttbl.power

class pc(ttbl.power.impl_c):
    """
    Power control for a VM managed with Proxmox

    :param url: Proxmox VM URL https://USER[__REALM]:PASSWORD@HOSTNAME/DOMAIN/VMNAME

      For example::

        https://root__pam:PASSWORD@10.1.3.146:8006/domain3/machine01

     - ``USERNAME`` is the Proxmox username (eg: ``root``); note that
       in most cases you need to include a realm; Proxmox usernames
       are of the form ``username@realm`` (eg: ``root@pam``), but to
       this driver you need to give them as ``username__realm`` (eg:
       ``root__pam``).

     - ``PASSWORD`` can be either a literal password or a password
       specification understood by :func:`commonl.password_get`.

       Note that in the password field, after FILE: or KEYRING: or
       ENV: specifying the password, you must use ``%%`` instead of
       ``/`` to separate directories, as in the following example::

         https://root__pam:FILE:%%path%%to%%passwor.file@hostname/domain3/machine01

     - ``DOMAIN`` is the Proxmox node name (eg: ``pve``); it shall already exist

     - ``VMNAME`` is the Proxmox VM name (eg: ``machine01``); it shall already exist

    Rest of arguments as for :class:`ttbl.power.impl_c`

    Any URL-special characters in the username, password specification,
    node name, or VM name must be percent-encoded.

    """

    def __init__(
            self,
            url,
            verify = False,
            timeout = 10,
            **kwargs):

        assert isinstance(url, str)
        assert isinstance(verify, (bool, str))
        assert isinstance(timeout, (int, float))
        assert timeout > 0

        ttbl.power.impl_c.__init__(self, **kwargs)

        self._urlparse(url)
        self.verify = verify
        self.timeout = timeout

        self.upid_set(
            "Proxmox VM",
            device_spec = self.url_clean,
        )



    def _urlparse(self, url: str):
        """
        Parse the Proxmox VM URL and extract the username, realm,
        password, generating password-less clean versions for log
        messages

        :param url: Proxmox VM URL
          https://USER[__REALM]:PASSWORD@HOSTNAME/DOMAIN/VMNAME

        :raises ValueError: if the URL is malformed or missing required components
        """
        assert isinstance(url, str), \
            f"Proxmox VM URL must be a string" \
            " https://USER[__REALM]:PASSWORD@HOSTNAME/DOMAIN/VMNAME," \
            f" got {type(url).__name__}"

        url_parsed = urllib.parse.urlsplit(url)
        # with no password, for debug/error messages
        if url_parsed.username:
            url_clean = f"{url_parsed.scheme}://"\
                f"{url_parsed.username}@{url_parsed.hostname}:{url_parsed.port or 8006}{url_parsed.path}"
        else:
            url_clean = f"{url_parsed.scheme}://"\
                f"{url_parsed.hostname}:{url_parsed.port or 8006}{url_parsed.path}"

        if url_parsed.username:
            # there is the chance that there is no realm on some auth
            if "__" in url_parsed.username:
                username, realm = url_parsed.username.rsplit("__", 1)
                realm = "@" + realm
            else:
                username = url_parsed.username
                realm = ""

            if url_parsed.password:
                # expand passwords (eg: KEYRING:...) to the actual password
                password = commonl.password_get(
                    url_parsed.hostname, username + realm, url_parsed.password)
            else:
                password = ""
        else:
            raise ValueError(f"Proxmox VM {url_clean}: missing USERNAME in URL")

        if url_parsed.scheme != "https":
            raise ValueError(f"Proxmox VM {url_clean}: URL must use https")

        if not url_parsed.hostname:
            raise ValueError(f"Proxmox VM {url_clean}: missing HOSTNAME")

        # compute node and vm_name from path, which should be /DOMAIN/VMNAME
        path_parts = [
            urllib.parse.unquote(part)
            for part in url_parsed.path.split("/")
            if part
        ]
        if len(path_parts) < 1:
            raise ValueError(f"Proxmox VM {url_clean}: missing DOMAIN in path")
        if len(path_parts) < 2:
            raise ValueError(f"Proxmox VM {url_clean}: missing VMNAME in path")
        if len(path_parts) > 2:
            raise ValueError(f"Proxmox VM {url_clean}: too many path"
                             " components, expected /DOMAIN/VMNAME")
        self.username = username
        self.realm = realm
        self.password = password
        self.node = path_parts[0]
        self.vm_name = path_parts[1]
        self.url_parsed = url_parsed
        self.url_clean = url_clean
        self.url_base = f"{url_parsed.scheme}://{url_parsed.hostname}:{url_parsed.port or 8006}"
        self.url = url



    def _login(self):
        """
        Log in to Proxmox and return the authentication ticket and CSRF token.

        :return: tuple of (ticket, CSRFPreventionToken)
        :raises: requests.exceptions.RequestException on network or HTTP errors
        """
        if self.username:
            data = {
                "username": self.username + self.realm,
                "password": self.password,
            }
        else:
            data = {}
        response = requests.post(
            f"{self.url_base}/api2/json/access/ticket",
            data = data,
            verify = self.verify,
            timeout = self.timeout,
        )
        response.raise_for_status()

        data = response.json()["data"]

        return (
            data["ticket"],
            data["CSRFPreventionToken"],
        )



    def _vmid_get_by_name(self, ticket):
        """
        Get the VMID of the VM by its name.

        :param ticket: Proxmox authentication ticket
        """
        node = urllib.parse.quote(self.node, safe = "")

        response = requests.get(
            f"{self.url_base}/api2/json/nodes/{node}/qemu",
            cookies = { "PVEAuthCookie": ticket },
            verify = self.verify,
            timeout = self.timeout,
        )
        response.raise_for_status()

        matches = [
            vm
            for vm in response.json()["data"]
            if vm.get("name") == self.vm_name
        ]

        if not matches:
            raise RuntimeError(
                f"Proxmox VM {self.url_clean}: VM not found on node"
            )

        if len(matches) > 1:
            raise RuntimeError(
                f"Proxmox VM {self.url_clean}: multiple VMs with same name found on node"
            )

        return matches[0]["vmid"]



    def _status_set(self, operation):
        """
        Set the status of the VM to the specified operation.

        :param operation: The operation to perform on the VM (e.g., "start", "stop")
        :raises: requests.exceptions.RequestException on network or HTTP errors

        This is based on the Proxmox API documentation for VM status operations which can be found at
        https://pve.proxmox.com/pve-docs/api-viewer/index.html#/
        """
        ticket, csrf_token = self._login()
        vmid = self._vmid_get_by_name(ticket)

        node = urllib.parse.quote(self.node, safe = "")
        vmid = urllib.parse.quote(str(vmid), safe = "")

        response = requests.post(
            f"{self.url_base}/api2/json/nodes/{node}/qemu/{vmid}/status/{operation}",
            cookies = {
                "PVEAuthCookie": ticket,
            },
            headers = {
                "CSRFPreventionToken": csrf_token,
            },
            verify = self.verify,
            timeout = self.timeout,
        )
        response.raise_for_status()



    def on(self, target, component: str):
        target.log.info("%s: Proxmox VM %s: starting", component, self.url_clean)
        self._status_set("start")



    def off(self, target, component: str):
        target.log.info("%s: Proxmox VM %s: stopping", component, self.url_clean)
        # "stop" is a hard power-off. For graceful shutdown, use
        # "shutdown". In here we consider it a pull the cable, so we
        # use "stop".
        self._status_set("stop")



    def get(self, target, component: str):
        try:
            ticket, _ = self._login()
            vmid = self._vmid_get_by_name(ticket)

            node = urllib.parse.quote(self.node, safe = "")
            vmid = urllib.parse.quote(str(vmid), safe = "")

            response = requests.get(
                f"{self.url_base}/api2/json/nodes/{node}/qemu/{vmid}/status/current",
                cookies = { "PVEAuthCookie": ticket },
                verify = self.verify,
                timeout = self.timeout,
            )
            response.raise_for_status()

            status = response.json()["data"].get("status")
            return status == "running"
        except requests.exceptions.RequestException as e:
            target.log.error(
                "%s: Proxmox VM %s: error getting status: %s",
                component, self.url_clean, str(e),
                exc_info = True)
            # don't raise exception, otherwise we can't do absolutely
            # anything, we just want to log the error and return None
            # to indicate we couldn't get the status
            return None
