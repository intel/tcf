#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Original by Jing Han
#
# pylint: disable = missing-docstring

import urlparse

import ttbl
import ttbl.power
import raritan
import raritan.rpc
import raritan.rpc.pdumodel

class pci(ttbl.power.impl_c): # pylint: disable = abstract-method
    """
    Power control interface for the Raritan EMX family of PDUs (eg: PX3-\*)

    Tested with a PX3-5190R with FW v3.3.10.5-43736

    In any place in the TCF server configuration where a power control
    implementation is needed and served by this PDU, thus insert:

    >>> import ttbl.raritan_emx
    >>>
    >>> ...
    >>>    ttbl.raritan_emx.pci('https://USER:PASSWORD@HOSTNAME', OUTLET#)

    :param str url: URL to access the PDU in the form::

        https://[USERNAME:PASSWORD@]HOSTNAME

      Note the login credentials are optional, but must be matching
      whatever is configured in the PDU for HTTP basic
      authentication and permissions to change outlet state.

    :param int outlet: number of the outlet in the PDU to control;
      this is an integer 1-N (N varies depending on the PDU model)

    :param bool https_verify: (optional, default *True*) do or
      do not HTTPS certificate verification.

    The RPC implementation is documented in
    https://help.raritan.com/json-rpc/emx/v3.4.0; while this driver
    uses the Raritan SDK driver, probably this is overkill--we could
    do the calls using JSON-RPC directly using jsonrpclib to avoid
    having to install the SDK, which is not packaged for easy
    redistribution and install.

    .. _raritan_emx_setup:

    **Bill of materials**

    - a Raritan EMX-compatible PDU (such as the PX3)

    - a network cable

    - a connection to a network switch to which the server is also
      connected (*nsN*) -- ideally this shall be an infrastructure
      network, isolated from a general use network and any test
      networks.

    **System setup**

    In the server

    1. Install the Raritan's SDK (it is not available as a PIP
       package) from https://www.raritan.com/support/product/emx
       (EMX JSON-RPC SDK)::

         $ wget http://cdn.raritan.com/download/EMX/version-3.5.0/EMX_JSON_RPC_SDK_3.5.0_45371.zip
         $ unzip -x EMX_JSON_RPC_SDK_3.5.0_45371.zip
         $ sudo install -m 0755 -o root -g root -d /usr/local/lib/python2.7/site-packages/raritan
         $ sudo cp -a emx-json-rpc-sdk-030500-45371/emx-python-api/raritan/* /usr/local/lib/python2.7/site-packages/raritan

    2. As the Raritan SDK had to be installed manually away from PIP
       or distro package management, ensurePython to looks into
       */usr/local/lib/python2.7/site-packages* for packages.

       Add your server configuration in a
       */etc/ttbd-production/conf_00_paths.py*::

         sys.path.append("/usr/local/lib/python2.7/site-packages")

       so it is parsed before any configuration that tries to import
       :mod:`ttbl.raritan_emx`.

    **Connecting the PDU**

    - Connect the PDU to the network

    - Assign the right IP and ensure name resolution works; convention
      is to use a short name *spN* (for Switch Power number *N*)

    - Configure a username/password with privilege to set the outlet
      state

    - Configure the system to power up all outlets after power loss
      (this is needed so the infrastructure can bring itself up
      without intervention, as for example it is a good practice to
      connect the servers to switched outlets so they can be remotely
      controlled).

    """
    def __init__(self, url, outlet_number, https_verify = True):
        assert isinstance(url, basestring)
        assert isinstance(outlet_number, int) and outlet_number > 0

        ttbl.power.impl_c.__init__(self)
        self.url = urlparse.urlparse(url)
        # note the indexes for the SW are 0-based, while in the labels
        # in the HW for humans, they are 1 based.
        self.outlet_number = outlet_number - 1
        self.https_verify = https_verify
        self._outlet_rpc = None


    @property
    def _outlet(self):
        # return a Raritan SDK outlet object on which we can run API
        # calls; if not initialized, initialize it on the run.
        #
        # Why not do this in __init__? Because the server runs in
        # multiple processes--this call may come from another process
        # and the initialization done in __init__ might have staled
        # when the processes forked.
        if not self._outlet_rpc:
            agent = raritan.rpc.Agent(
                self.url.scheme, self.url.hostname,
                self.url.username, self.url.password,
                disable_certificate_verification = not self.https_verify)
            pdu = raritan.rpc.pdumodel.Pdu("/model/pdu/0", agent)
            outlets = pdu.getOutlets()
            self._outlet_rpc = outlets[self.outlet_number]
        return self._outlet_rpc

    def on(self, _target, _component):
        self._outlet.setPowerState(
            raritan.rpc.pdumodel.Outlet.PowerState.PS_ON)

    def off(self, _target, _component):
        self._outlet.setPowerState(
            raritan.rpc.pdumodel.Outlet.PowerState.PS_OFF)

    def get(self, _target, _component):
        # We cannot call self._outlet.getState() directly--there seems
        # to be a compat issue between this version of the API in the
        # unit I tested with and what this API expects, with a missing
        # field 'loadShed' in the returned value dict.
        #
        # So we call getState by hand (from
        # raritan/Interface.py:Interface.Method) and we extract the
        # value manually.
        obj = self._outlet.getState
        r = obj.parent.agent.json_rpc(obj.parent.target, obj.name, {})
        state = r['_ret_']['powerState']

        if state == 0:
            return False
        return True
