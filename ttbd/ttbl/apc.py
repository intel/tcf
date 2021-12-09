#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import sys
from pathlib import Path

import ttbl.power
try:
    import pysnmp.entity.rfc3413.oneliner.cmdgen
    import pysnmp.proto.rfc1902
except ImportError as e:
    # if building doc, it's ok not to have the dependencies
    if 'sphinx.cmd' not in sys.modules:
        raise

class pc(ttbl.power.impl_c):
    """
    Power control driver for APC PDUs using SNMP

    This is a very hackish implementation that attempts to require the
    least setup possible. It hardcodes the OIDs and MIBs because APC's
    MIBs are not publicly available and the setup
    becomes...complicated (please contribute a better one if you can help)

    To use in any place where a power control element is needed:

    >>> import ttbl.apc
    >>>
    >>> ...
    >>>     ttbl.apc.pc("HOSTNAME", 4)
    >>>

    for doing power control on APC PDU *HOSTNAME* on outlet *4*.

    :param str hostname: IP address or hostname of the PDU
    :param str outlet: number of the outlet to control
    :param str oid: (optional) Base SNMP OID for the unit. To find it,

    Other parameters as to :class:ttbl.power.impl_c.

    Tested with:

    - AP7930

    References used:

    - https://tobinsramblings.wordpress.com/2011/05/03/snmp-tutorial-apc-pdus/
    - http://mibs.snmplabs.com/asn1/POWERNET-MIB
    - https://www.apc.com/shop/us/en/products/POWERNET-MIB-V4-3-1/P-SFPMIB431
    - https://download.schneider-electric.com/files?p_enDocType=Firmware+-+Released&p_Doc_Ref=APC_POWERNETMIB_431&p_File_Name=powernet431.mib


    **System setup**

    2 different options available:
    SNMPv1 without authentication.
    SNMPv3 with authentication data read from a config file.

    - configure an IP address (static, DHCP) to the APC PDU

    SNMPv1 configuration:

    - in the web configuration:

       - Administration > Network > SNMPv1 > access: enable
       - Administration > Network > SNMPv1 > access control: set the
         community name *private* to *Access Type* *write +*

      When using SNMPv1 without authentication it is recommended to place
      these units in a private protected network.

    SNMPv3 configuration:

    - in the web configuration:

       - Administration/Configuration > Network > SNMPv3 > access: enable
       - Administration/Configuration > Network > SNMPv3 > user profiles: select user
         in this example the username is 'admin'
       - Administration/Configuration > Network > SNMPv3 > user profiles > admin:
         configure the Authentication and Privacy passphrases. In this example
         we're using 'Authentication Protocol' MD5 and 'Privacy Protocol' DES.

    - SNMPv3 config file example:

      Add a config file for each PDU on the machine where this python module is installed to:
      /etc/snmp/hosts/<hostname>.conf
      This is the same location Linux 'net-snmp-utils' tools would look for
      configuration data for <hostname> snmp controlled device.

      Example configuration file contents:

      defVersion 3
      defSecurityName admin
      defSecurityLevel AuthPriv
      defAuthType MD5
      defPrivType DES
      defAuthPassphrase <Authentication passphrase you configured to PDU>
      defPrivPassphrase <Privacy passphrase you configured to PDU>


    **Finding OIDs, etc**

    FIXME: incomplete
    This is only need in a system to find out numbers, not needed in
    the servers:

    - Install the POWERNET-MIB::

        $ mkdir -p ~/.snmp/mibs/
        $ wget http://mibs.snmplabs.com/asn1/POWERNET-MIB -O ~/.snmp/mibs/
        $ echo mibs POWERNET-MIB >> ~/.snmp/snmp.conf

    Find OID for querying number of outlets::

      $ snmptranslate -On POWERNET-MIB::sPDUOutletControlTableSize.0
      .1.3.6.1.4.1.318.1.1.4.4.1.0

    Find OID for controlling outlet #1::

      $ snmptranslate -On POWERNET-MIB::sPDUOutletCtl.1
      .1.3.6.1.4.1.318.1.1.4.4.2.1.3.1

    """

    #: Main OID for the APC PDU (this can be changed with the *oid*
    #: parameter to the constructor)
    oid = [ 1, 3, 6, 1, 4, 1, 318, 1, 1, 4 ]

    #: MIB for the command to list the number of tablets
    #:
    #: Obtained with::
    #:
    #:   $ snmptranslate -On POWERNET-MIB::sPDUOutletControlTableSize.0
    #:   .1.3.6.1.4.1.318.1.1.4.4.1.0
    table_size =  [ 4, 1, 0 ]

    #: MIB for the command to control outlets
    #:
    #: Obtained with::
    #:
    #:   $ snmptranslate -On POWERNET-MIB::sPDUOutletCtl.1
    #:   .1.3.6.1.4.1.318.1.1.4.4.2.1.3.1
    #:
    #: the last digit is the outlet number, 1..N.
    pdu_outlet_ctl_prefix = [ 4, 2, 1, 3 ]

    def __init__(self, hostname, outlet, oid = None, **kwargs):
        ttbl.power.impl_c.__init__(self, **kwargs)

        # if SNMP config file corresponding to the hostname exists read the contents to a dictionary
        # and use the user authentication information provided to access the pdu with SNMPv3 methods
        # else use SNMPv1 with no authentication information.
        cfgdata = {}
        cfgfilepath = Path("/etc/snmp/hosts/" + hostname + ".conf")
        if cfgfilepath.is_file():
            with open(cfgfilepath) as file:
                for line in file:
                    if line.strip():
                        if not line.startswith("#"):
                            (key, value) = line.split()
                            cfgdata[key] = value

            self._authdata = pysnmp.entity.rfc3413.oneliner.cmdgen.UsmUserData(cfgdata['defSecurityName'],
                                                                               cfgdata['defAuthPassphrase'],
                                                                               cfgdata['defPrivPassphrase'])
        else:
            self._authdata = pysnmp.entity.rfc3413.oneliner.cmdgen.CommunityData('private')

        self._destination = pysnmp.entity.rfc3413.oneliner.cmdgen.UdpTransportTarget((hostname, 161))
        self.outlets = self._outlet_count()
        self.host = hostname
        self.outlet = outlet
        if oid:
            self.oid = oid
        assert outlet > 0 and outlet <= self.outlets, \
            "outlet number '%s' invalid or out of range (1-%d)" \
            % (outlet, self.outlets)
        self.pdu_outlet_ctl = self.pdu_outlet_ctl_prefix + [ outlet ]
        self.upid_set("APC PDU", hostname = hostname, outlet = outlet)

    def _outlet_count(self):
        ( _errors, _status, _index, varl ) = \
            pysnmp.entity.rfc3413.oneliner.cmdgen.CommandGenerator().getCmd(
                self._authdata, self._destination,
                (self.oid + self.table_size)
            )
        # response is something like:
        #
        # (
        #       None,
        #       0,
        #       0,
        #       [
        #           ObjectType(
        #               ObjectIdentity(ObjectName('1.3.6.1.4.1.318.1.1.4.4.1.0')),
        #               Integer(24)
        #           )
        #       ]
        # )
        #
        # so varl is the list of []
        #
        #           ObjectType(
        #               ObjectIdentity(ObjectName('1.3.6.1.4.1.318.1.1.4.4.1.0')),
        #               Integer(24)
        #           )
        #
        # And sincerely, I have not been able to figure out how in
        # heaven to extract the value in a kosher way, but obj[1]
        # worked, so be it.
        return int(varl[0][1])

    def get(self, target, component):
        #
        # So get returns:
        #
        # (None, 0, 0, [ObjectType(ObjectIdentity(ObjectName('1.3.6.1.4.1.318.1.1.4.4.2.1.3.1')), Integer(2))])
        ( errors, status, _index, varl ) = \
            pysnmp.entity.rfc3413.oneliner.cmdgen.CommandGenerator().getCmd(
                self._authdata, self._destination,
                (self.oid + self.pdu_outlet_ctl)
            )
        if errors != None:
            raise RuntimeError("%s#%d: error getting PDU outlet state: %s" %
                               (self.host, self.outlet, status))
        # we only expect one variable, so we are going to shorcircuit
        # and get it's value right away
        state = int(varl[0][1])
        if state == 1:
            return True		# on
        elif state == 2:
            return False	# off
        else:
            return None		# no idea

    def on(self, target, component):
        ( errors, status, _index, _varl ) = \
            pysnmp.entity.rfc3413.oneliner.cmdgen.CommandGenerator().setCmd(
                self._authdata, self._destination,
                (
                    self.oid + self.pdu_outlet_ctl,
                    pysnmp.proto.rfc1902.Integer(1) # 2 - turn on
                )
            )
        if errors != None:
            raise RuntimeError("%s#%d: error turning PDU outlet on: %s" %
                               (self.host, self.outlet, status))

    def off(self, target, component):
        ( errors, status, _index, _varl ) = \
            pysnmp.entity.rfc3413.oneliner.cmdgen.CommandGenerator().setCmd(
                self._authdata, self._destination,
                (
                    self.oid + self.pdu_outlet_ctl,
                    pysnmp.proto.rfc1902.Integer(2) # 2 - turn off
                )
            )
        if errors != None:
            raise RuntimeError("%s#%d: error turning PDU outlet off: %s" %
                               (self.host, self.outlet, status))
