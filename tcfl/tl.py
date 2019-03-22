#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Common utilities for test cases
"""

import os
import re

import tcfl.tc

#! Place where the Zephyr tree is located
# Note we default to empty string so it can be pased
ZEPHYR_BASE = os.environ.get(
    'ZEPHYR_BASE',
    '__environment_variable_ZEPHYR_BASE__not_exported__')

def zephyr_tags():
    """
    Evaluate the build environment and make sure all it is needed to
    build Zephyr apps is in place.

    If not, return a dictionary defining a *skip* tag with the reason
    that can be fed directly to decorator :func:`tcfl.tc.tags`; usage:

    >>> import tcfl.tc
    >>> import qal
    >>>
    >>> @tcfl.tc.tags(**qal.zephyr_tests_tags())
    >>> class some_test(tcfl.tc.tc_c):
    >>>     ...
    """
    tags = {}
    zephyr_vars = set([ 'ZEPHYR_BASE', 'ZEPHYR_GCC_VARIANT',
                        'ZEPHYR_TOOLCHAIN_VARIANT' ])
    zephyr_vars_missing = zephyr_vars - set(os.environ.keys())
    if 'ZEPHYR_GCC_VARIANT' in zephyr_vars_missing \
       and 'ZEPHYR_TOOLCHAIN_VARIANT' in set(os.environ.keys()):
        # ZEPHYR_GCC_VARIANT deprecated -- always remove it
        # TOOLCHAIN_VARIANT (the new form) is set
        zephyr_vars_missing.remove('ZEPHYR_GCC_VARIANT')
    if zephyr_vars_missing:
        tags['skip'] = ",".join(zephyr_vars_missing) + " not exported"
    return tags


def console_dump_on_failure(testcase):
    """
    If a testcase has errored, failed or blocked, dump the consoles of
    all the targets.

    :param tcfl.tc.tc_c testcase: testcase whose targets' consoles we
      want to dump

    Usage: in a testcase's teardown function:

    >>> import tcfl.tc
    >>> import tcfl.tl
    >>>
    >>> class some_test(tcfl.tc.tc_c):
    >>>     ...
    >>>
    >>>     def teardown_SOMETHING(self):
    >>>         tcfl.tl.console_dump_on_failure(self)
    """
    assert isinstance(testcase, tcfl.tc.tc_c)
    if not testcase.result_eval.failed \
       and not testcase.result_eval.errors \
       and not testcase.result_eval.blocked:
        return
    for target in testcase.targets.values():
        if not hasattr(target, "console"):
            continue
        if testcase.result_eval.failed:
            reporter = target.report_fail
            reporter("console dump due to failure")
        elif testcase.result_eval.errors:
            reporter = target.report_error
            reporter("console dump due to errors")
        else:
            reporter = target.report_blck
            reporter("console dump due to blockage")
        for line in target.console.read().split('\n'):
            reporter("console: " + line.strip())


def setup_verify_slip_feature(zephyr_client, zephyr_server, _ZEPHYR_BASE):
    """
    The Zephyr kernel we use needs to support
    CONFIG_SLIP_MAC_ADDR, so if any of the targets needs SLIP
    support, make sure that feature is Kconfigurable
    Note we do this after building, because we need the full
    target's configuration file.

    :param tcfl.tc.target_c zephyr_client: Client Zephyr target

    :param tcfl.tc.target_c zephyr_server: Client Server target

    :param str _ZEPHYR_BASE: Path of Zephyr source code

    Usage: in a testcase's setup methods, before building Zephyr code:

    >>>     @staticmethod
    >>>     def setup_SOMETHING(zephyr_client, zephyr_server):
    >>>         tcfl.tl.setup_verify_slip_feature(zephyr_client, zephyr_server,
                                                  tcfl.tl.ZEPHYR_BASE)

    Look for a complete example in
    :download:`../examples/test_network_linux_zephyr_echo.py`.
    """
    assert isinstance(zephyr_client, tcfl.tc.target_c)
    assert isinstance(zephyr_server, tcfl.tc.target_c)
    client_cfg = zephyr_client.zephyr.config_file_read()
    server_cfg = zephyr_server.zephyr.config_file_read()
    slip_mac_addr_found = False
    for file_name in [
            os.path.join(_ZEPHYR_BASE, "drivers", "net", "Kconfig"),
            os.path.join(_ZEPHYR_BASE, "drivers", "slip", "Kconfig"),
    ]:
        if os.path.exists(file_name):
            with open(file_name, "r") as f:
                if "SLIP_MAC_ADDR" in f.read():
                    slip_mac_addr_found = True

    if ('CONFIG_SLIP' in client_cfg or 'CONFIG_SLIP' in server_cfg) \
       and not slip_mac_addr_found:
        raise tcfl.tc.blocked_e(
            "Can't test: your Zephyr kernel in %s lacks support for "
            "setting the SLIP MAC address via configuration "
            "(CONFIG_SLIP_MAC_ADDR) -- please upgrade"
            % _ZEPHYR_BASE, dict(dlevel = -1)
        )

def teardown_targets_power_off(testcase):
    """
    Power off all the targets used on a testcase.

    :param tcfl.tc.tc_c testcase: testcase whose targets we are to
      power off.

    Usage: in a testcase's teardown function:

    >>> import tcfl.tc
    >>> import tcfl.tl
    >>>
    >>> class some_test(tcfl.tc.tc_c):
    >>>     ...
    >>>
    >>>     def teardown_SOMETHING(self):
    >>>         tcfl.tl.teardown_targets_power_off(self)

    Note this is usually not necessary as the daemon will power off
    the targets when cleaning them up; usually when a testcase fails,
    you want to keep them on to be able to inspect them.
    """
    assert isinstance(testcase, tcfl.tc.tc_c)
    for dummy_twn, target  in reversed(list(testcase.targets.iteritems())):
        target.power.off()

def tcpdump_enable(ic):
    """
    Ask an interconnect to capture IP traffic with TCPDUMP

    Note this is only possible if the server to which the interconnect
    is attached has access to it; if the interconnect is based on the
    :class:vlan_pci driver, it will support it.

    Note the interconnect *must be* power cycled after this for the
    setting to take effect. Normally you do this in the *start* method
    of a multi-target testcase

    >>> def start(self, ic, server, client):
    >>>    tcfl.tl.tcpdump_enable(ic)
    >>>    ic.power.cycle()
    >>>    ...
    """
    assert isinstance(ic, tcfl.tc.target_c)
    ic.property_set('tcpdump', ic.kws['tc_hash'] + ".cap")


def tcpdump_collect(ic, filename = None):
    """
    Collects from an interconnect target the tcpdump capture

    .. warning: this will power off the interconnect!

    :param tcfl.tc.target_c ic: interconnect target
    :param str filename: (optional) name of the local file where to
        copy the tcpdump data to; defaults to
        *report-RUNID:HASHID-REP.tcpdump* (where REP is the repetition
        count)
    """
    assert isinstance(ic, tcfl.tc.target_c)
    assert filename == None or isinstance(filename, basestring)
    if filename == None:
        filename = \
            "report-%(runid)s:%(tc_hash)s" % ic.kws \
            + "-%d" % (ic.testcase.eval_count + 1) \
            + ".tcpdump"
    ic.power.off()		# ensure tcpdump flushes
    ic.broker_files.dnload(ic.kws['tc_hash'] + ".cap", filename)
    ic.report_info("tcpdump available in file %s" % filename)

def linux_os_release_get(target, prefix = ""):
    """
    Return in a dictionary the contents of a file /etc/os-release (if
    it exists)
    """
    output = target.shell.run(
        "cat %s/etc/os-release || true" % prefix, output = True)
    matches = re.findall(r"^(?P<field>\S+)=(?P<valur>\S+)$", output,
                         re.MULTILINE)
    os_release = {}
    for match in matches:
        os_release[match[0]] = match[1]
    return os_release

def linux_ssh_root_nopwd(target, prefix = ""):
    """
    Configure a SSH deamon to allow login as root with no passwords
    """
    target.shell.run("""\
mkdir -p %s/etc/ssh
cat <<EOF >> %s/etc/ssh/sshd_config
PermitRootLogin yes
PermitEmptyPasswords yes
EOF""" % (prefix, prefix))

def deploy_linux_ssh_root_nopwd(_ic, target, _kws):
    linux_ssh_root_nopwd(target, "/mnt")

def linux_ipv4_addr_get_from_console(target, ifname):
    """
    Get the IPv4 address of a Linux Interface from the Linux shell
    using the *ip addr show* command.

    :param tcfl.tc.target_c target: target on which to find the IPv4
      address.
    :param str ifname: name of the interface for which we want to find
      the IPv4 address.

    :raises tcfl.tc.error_e: if it cannot find the IP address.

    Example:

    >>> import tcfl.tl
    >>> ...
    >>>
    >>> @tcfl.tc.interconnect("ipv4_addr")
    >>> @tcfl.tc.target("pos_capable")
    >>> class my_test(tcfl.tc.tc_c):
    >>>    ...
    >>>    def eval(self, tc, target):
    >>>        ...
    >>>        ip4 = tcfl.tl.linux_ipv4_addr_get_from_console(target, "eth0")
    >>>        ip4_config = target.addr_get(ic, "ipv4")
    >>>        if ip4 != ip4_config:
    >>>            raise tcfl.tc.failed_e(
    >>>                "assigned IPv4 addr %s is different than"
    >>>                " expected from configuration %s" % (ip4, ip4_config))

    """
    output = target.shell.run("ip addr show dev %s" % ifname, output = True)
    regex = re.compile(r"^    inet (?P<name>([0-9\.]+){4})/", re.MULTILINE)
    matches = regex.search(output)
    if not matches:
        raise tcfl.tc.error_e("can't find IP addr")
    return matches.groupdict()['name']
