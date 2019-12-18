#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Controlling targets via RedFish
--------------------------------

This module implements multiple objects that can be used to control a
target using RedFish.

"""

import subprocess
import time
import urlparse

import requests
import sushy

import commonl
import ttbl.power


class pos_mode_c(ttbl.power.impl_c):
    """
    Power controller to redirect a machine's boot to network upon ON

    This can be used in the power rail of a machine that can be
    provisioned with :ref:`Provisioning OS <provisioning_os>`, instead
    of using pre power-on hooks (such as
    :meth:`pci_ipmitool.pre_power_pos_setup`).

    When the target is being powered on, this will be called, and
    based if the value of the *pos_mode* property is *pxe*, the RedFish
    protocol will be used to tell the BMC to order the target to boot
    off the network and then the BMC will force a reset to make sure
    the setting applies.

    Otherwise, it'll let the machine to default boot off the local
    disk. 
    """
    def __init__(self, bmc_url, verify = True):
        assert isinstance(bmc_url, basestring)
        assert isinstance(verify, bool)
        ttbl.power.impl_c.__init__(self, paranoid = True)
        self.power_on_recovery = False
        self.get_samples = 0
        url = urlparse.urlparse(bmc_url)
        self.username = url.username
        self.password = commonl.password_get(url.hostname, self.username,
                                             url.password)
        self.url = commonl.url_remove_user_pwd(url)
        self.verify = verify

    def _redfish_set_boot(self):
        r = requests.get(self.url, verify = self.verify, timeout = (2, 10))

        s = sushy.Sushy(self.url, verify = self.verify,
                        username = self.username, password = self.password)
        # get list of systems described by this
        #
        ## $ curl -k https://HOSTNAME/redfish/v1/Systems
        ## {
        ##   "@odata.context": "/redfish/v1/$metadata#ComputerSystemCollection.ComputerSystemCollection",
        ##   "@odata.id": "/redfish/v1/Systems",
        ##   "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
        ##   "Members": [
        ##     {
        ##       "@odata.id": "/redfish/v1/Systems/system"
        ##     }
        ##   ],
        ##   "Members@odata.count": 1,
        ##   "Name": "Computer System Collection"
        ## }
        #
        # So we take the first one, which describes the system itself
        system_collection = s.get_system_collection()
        member = system_collection.members_identities[0]

        # Get the system info and interfaces
        #
        ## $ curl -k https://root:0penBmc@10.219.139.109/redfish/v1/Systems/system
        ## {
        ##   "@odata.context": "/redfish/v1/$metadata#ComputerSystem.ComputerSystem",
        ##   "@odata.id": "/redfish/v1/Systems/system",
        ##   "@odata.type": "#ComputerSystem.v1_6_0.ComputerSystem",
        ##   "Actions": {
        ##     "#ComputerSystem.Reset": {
        ##       "ResetType@Redfish.AllowableValues": [
        ##         "On",
        ##         "ForceOff",
        ##         "ForceOn",
        ##         "ForceRestart",
        ##         "GracefulRestart",
        ##         "GracefulShutdown",
        ##         "PowerCycle",
        ##         "Nmi"
        ##       ],
        ##       "target": "/redfish/v1/Systems/system/Actions/ComputerSystem.Reset"
        ##     }
        ##   },
        ##   "Boot": {
        ##     "BootSourceOverrideEnabled": "Disabled",
        ##     "BootSourceOverrideMode": "Legacy",
        ##     "BootSourceOverrideTarget": "None",
        ##     "BootSourceOverrideTarget@Redfish.AllowableValues": [
        ##       "None",
        ##       "Pxe",
        ##       "Hdd",
        ##       "Cd",
        ##       "Diags",
        ##       "BiosSetup",
        ##       "Usb"
        ##     ]
        ##   },
        ##   ...
        ##   "PowerState": "On",
        ##   ...
        ## }        
        #
        system = system_collection.get_member(member)

        # We now tell the system to boot next time off th network and
        # reset, so if we were booting, we boot off the network
        target.log.info("setting boot source to PXE")
        system.set_system_boot_source("pxe", enabled = 'once')
        target.log.info("forcing a restart")
        system.reset_system("force restart")


    def on(self, target, _component):
        if target.fsdb.get("pos_mode") == 'pxe':
            # wait for BMC to be online
            ts0 = time.time()
            ts = ts0
            bmc_online_timeout = 140
            while ts - ts0 < bmc_online_timeout:
                ts = time.time()
                try:
                    self._redfish_set_boot()
                    break	# connection worked, thing is online!!!
                except (requests.exceptions.ConnectTimeout,
                        requests.exceptions.ReadTimeout) as e:
                    target.log.info("BMC %s: not yet online +%d/%ds, retrying",
                                    self.url, ts - ts0, bmc_online_timeout)
                    continue
                except sushy.exceptions.AccessError as e:
                    target.log.info("BMC %s: not yet online +%d/%ds, retrying",
                                    self.url, ts - ts0, bmc_online_timeout)
                    continue
                except requests.exceptions as e:
                    if e.status_code == 401:
                        continue
                    target.log.error("BMC %s: error testing connection: %s",
                                     self.url, e)
                    raise
            else:
                    raise RuntimeError("BMC %s: didn't come online after %ds"
                                     % (self.url, bmc_online_timeout))

    def off(self, target, _component):
        pass

    def get(self, target, component):
        return None
