#! /usr/bin/python3
#
# Copyright (c) 2017-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Common utilities for test cases
"""

import collections
import contextlib
import datetime
import os
import re
import ssl
import time
import traceback
import urllib.parse

import pyte

import commonl
import tcfl.tc

def ansi_render_approx(s, width = 80, height = 2000):
    """
    Does an approximated render of how a string would look on a vt100
    terminal

    The string can contain ANSI escape sequences, which the
    :module:`pyte` engine can render so a string such as

    >>> s = '\x1b[23;08Hi\x1b[23;09H\x1b[23;09Hf\x1b[23;10H\x1b[23;10Hc\x1b[23;11H\x1b[23;11Ho\x1b[23;12H\x1b[23;12Hn\x1b[23;13H\x1b[23;13Hf\x1b[23;14H\x1b[23;14Hi\x1b[23;15H\x1b[23;15Hg\x1b[23;16H\x1b[23;16H \x1b[23;17H\x1b[23;17H-\x1b[23;18H\x1b[23;18Hl\x1b[23;19H\x1b[23;19H \x1b[23;20H\x1b[23;20He\x1b[23;21H\x1b[23;21Ht\x1b[23;22H\x1b[23;22Hh\x1b[23;23H\x1b[23;23H0\x1b[23;24H\x1b[23;24H\r\n\r\n'

    renders to::

      <RENDERER: skipped 23 empty lines>
             ifconfig -l eth0

      Shell> ping -n 5 10.219.169.119

    (loosing attributes such as boldface, colors, etc) Note also that
    the sequences might move the cursor, override things, etc --
    sometimes you need to render different parts of the string and
    feed parts to it and see how it updates it.

    :param str s: string to render, possibly containing ANSI escape
      sequences

    :param int width: (optional) with of the screen where to render
      (usually 80, the original vt100 terminal size)

    :param int height: (optional) height of the screen where to render
      (usually 24, the original vt100 terminal size, however made to
      default to 2000 so it catches history for sequential command
      executions; this might not work on all cases if the sequentials
      clear the screen or move the cursor.
    """
    assert isinstance(s, str)
    assert isinstance(width, int) and width > 20
    assert isinstance(height, int) and height > 20
    r = ""
    screen = pyte.Screen(width, height)
    stream = pyte.Stream(screen)
    stream.feed(s)

    empty_line = width * " "
    last = empty_line
    skips = 1
    for line in screen.display:
        # skip over repeated empty lines
        if line == empty_line and line == last:
            skips += 1
            continue
        else:
            if skips > 1:
                r += f"<RENDERER: skipped {skips} empty lines>\n"
            skips = 1
            last = line
        r += line.rstrip() + "\n"
    return r



def data_deploy(target, data: dict, destpath: str = "/"):
    """
    Deploy any data to the target

    Assumes Linux is running in the target, the default console is
    setup for shell execution and the following tools are available:

    - curl
    - rsync
    - cp

    :param tcfl.tc.target_c target: target to which we are copying data

    :param dict data: dictionary keyed by source URL and value
      destination path in the target; eg:

      >>> data = {
      >>>     "http://example.com/somefile.bin": "/tmp/somefile.bin",
      >>>     "rsync://example.com/otherfile.img": "/opt/otherfile.img",
      >>>     "/gfs/gfs/group/RASP/somefile.bin": "/opt/",
      >>> }

      note that the destination path is relative to *destpath*. As
      well, the environment variable *$GFS_SERVER* will be set so that
      you could specify something like:

      >>> data = {
      >>>     "http://$GFS_SERVER/gfs/group/RASP/somefile.bin": "/tmp/",
      >>> }
    """
    count = 0
    total = len(data)
    target.report_info("installing data",
                       { "data": data }, dlevel = -1)
    for k, v in data.items():
        k_lower = k.lower()
        count += 1
        target.shell.run(f"# downloading data {count}/{total}")
        with target.testcase.subcase(commonl.name_make_safe(k_lower)):

            if k_lower.startswith("http://") or k_lower.startswith("https://"):
                if v.endswith("/"):
                    # filename will be the same as what we are downloading
                    dest = v + k.split('/')[-1]
                else:
                    dest = v
                target.shell.run(f"curl {k} -o {destpath}/{dest}")
                target.report_pass(f"downloaded {k} to {dest}")
                continue

            if k_lower.startswith("rsync://"):
                # rsync://server/path -> server/path
                src = k.replace("rsync://", "")
                # server /path
                hostname, path = src.split("/", 1)
                # remove leading /, not needed for rsync module
                target.shell.run(f"rsync -av {hostname}::{path[1:]} {destpath}/{v}")
                target.report_pass(f"rsynced {k} to {v}")
                continue

            if "://" in k_lower:
                raise tcfl.error_e(f"data source URL scheme not supported: {k}")

            # this is a normal file copy from something mounted, most like
            # /gfs

            target.shell.run(f"cp -a {k} {destpath}/{v}")
            target.report_pass(f"copied {k} to {v}")
    target.report_info("installed data",
                       { "data": data }, dlevel = -1)



def ipxe_sanboot_url(target, sanboot_url, dhcp = None,
                     power_cycle: bool = True,
                     assume_in_main_menu: bool = None,
                     precommands: list = None,
                     mac_addr: str = None,
                     timeout: float = None):
    """Use iPXE to sanboot a given URL

    Given a target than can boot iPXE via a PXE boot entry (normally
    in EFI), drive it to boot iPXE and iPXE to load a sanboot URL so
    any ISO image can be loaded and booted as a local one.

    This is also used in :ref:`the iPXE Sanboot<example_efi_pxe_sanboot>`.

    Requirements:

    - iPXE: must have Ctrl-B configured to allow breaking into the
      console

    :param tcfl.tc.target_c target: target where to perform the
      operation

    :param str sanboot_url: URL to download and map into a drive to
      boot into. If *skip* nothing is done and you are left with an
      iPXE console connected to the network.

    :param bool dhcp: (optional) have iPXE issue DHCP for IP
      configuration or manually configure using target's data.

      If *None*, the default is taken from the machine's inventory
      *ipxe.dhcp* setting, which defaults to *True* if not present.

    :param bool power_cycle: (optional; default *True*) do power cycle
      the target before starting; if *False*, it is assumed the target
      is power cycled and in the BIOS main menu.

    :param bool assume_in_main_menu: (optional; default *not power_cycle*)
      Assume the BIOS is already in the main menu.

    :param list[str] precomands: list of pre-commands to run before
      launching

      >>> ( "set server 192.34.12.1" )

    :param str mac_addr: (optional; default is obtained from the
      inventory) MAC address to select boot option

      >>> mac_addr = "4a:b0:15:5f:98:a1"

    """
    if power_cycle:
        if 'qemu' in target.type:
            # horrible hack -- see tcfl.biosl.main_menu_expect(); this
            # allos the EFI to be slowed down so it receives the F2 to
            # boot the BIOS menu
            target.property_set("debug", True)
        target.power.cycle()
        tcfl.biosl.main_menu_expect(target)	# take boot to the BIOS menu

    if mac_addr != None:
        commonl.assert_macaddr(mac_addr)
    else:
        boot_ic = target.kws['pos_boot_interconnect']
        mac_addr = target.kws['interconnects'][boot_ic]['mac_addr']

    if assume_in_main_menu == None:
        # if we had to power cycle, BIOS is in menu
        assume_in_main_menu = power_cycle
    else:
        assert isinstance(assume_in_main_menu, bool), \
            f"assume_in_main_menu: expected bool, got {type(assume_in_main_menu).__name__}"

    # the bios.boot_entry_pxe section of the inventory can tell us
    # what is the PXE boot entry--gather it or default to a default
    # one if not set.
    boot_entry_pxe = target.kws.get(
        "bios.boot_entry_pxe", None)
    if boot_entry_pxe == None:
        boot_entry_pxe = r"UEFI PXEv4 \(MAC:%s\)"
        target.report_info("UEFI: booting PXE boot entry (default):"
                           f" {boot_entry_pxe}")
    else:
        target.report_info("UEFI: booting PXE boot entry from inventory"
                           " bios.boot_entry_pxe:"
                           f" {boot_entry_pxe}")

    if '%' in boot_entry_pxe:
        # Eg: UEFI PXEv4 (MAC:4AB0155F98A1)
        # FIXME: this is lame and needs keyword encoding with macs in multiple formats
        boot_entry_pxe = boot_entry_pxe % mac_addr.replace(":", "").upper().strip()

    tcfl.biosl.boot_network_pxe(
        target,
        boot_entry_pxe,
        assume_in_main_menu = assume_in_main_menu
    )

    expecter_ipxe_error = target.console.text(
        # When iPXE prints an error, it looks like:
        ## http://10.219.169.112/ttbd-pos/x86_64/vmlinuz-tcf-live..................
        ## Connection timed out (http://ipxe.org/4c0a6092)
        #
        # So, if we find that URL, raise an error
        re.compile(r"\(http://ipxe\.org/[0-9a-f]+\)"),
        name = f"{target.want_name}: iPXE error",
        timeout = 0, poll_period = 1,
        raise_on_found = tcfl.tc.error_e("iPXE error detected")
    )

    if dhcp == None:
        dhcp = bool(target.property_get("ipxe.dhcp", True))

    # can't wait also for the "ok" -- debugging info might pop in th emiddle
    target.expect("iPXE initialising devices...")
    # if the connection is slow, we have to start sending Ctrl-B's
    # ASAP
    #target.expect(re.compile("iPXE .* -- Open Source Network Boot Firmware"))

    # send Ctrl-B to go to the PXE shell, to get manual control of iPXE
    #
    # do this as soon as we see the boot message from iPXE because
    # otherwise by the time we see the other message, it might already
    # be trying to boot pre-programmed instructions--we'll see the
    # Ctrl-B message anyway, so we expect for it.
    #
    # before sending these "Ctrl-B" keystrokes in ANSI, but we've seen
    # sometimes the timing window being too tight, so we just blast
    # the escape sequence to the console.
    target.console.write("\x02\x02")	# use this iface so expecter
    time.sleep(0.3)
    target.console.write("\x02\x02")	# use this iface so expecter
    time.sleep(0.3)
    target.console.write("\x02\x02")	# use this iface so expecter
    time.sleep(0.3)
    # in some circumstances, some iPXEs fail to chainload, or get
    # stuff from a different NIC than the one they were loaded from --
    r = target.expect(
        re.compile(
            "(?P<what>"
            # normal message we expect, a 'press Ctrl-B for shell'
            "Ctrl-B"
            # error message -> still we can hit s for the iPXE shell
            "|Chainloading failed, hit 's' for the iPXE shell"
            ")"),
        timeout = 250)
    # r is a dict with a single key (name of the matching thing) and
    # info about the match. because we gave it a regex with named
    # groups, we'll get a groupdict entry:
    data, = r.values()	# note the comma! works because we have a single item
    what = data.get('groupdict', {}).get('what', None)
    if what != None:
        if b"Chainloading failed, hit 's' for the iPXE shell" in what:
            target.console.write("s")
            target.expect("iPXE>")
        else:	# just send Ctrl-B
            target.console.write("\x02\x02")
            time.sleep(0.3)
            target.console.write("\x02\x02")
            time.sleep(0.3)
            target.expect("iPXE>")
    prompt_orig = target.shell.prompt_regex
    try:
        #
        # When matching end of line, match against \r, since depends
        # on the console it will send one or two \r (SoL vs SSH-SoL)
        # before \n -- we removed that in the kernel driver by using
        # crnl in the socat config
        #
        # FIXME: block on anything here? consider infra issues
        # on "Connection timed out", http://ipxe.org...
        target.shell.prompt_regex = "iPXE>"

        # Find what network interface our MAC address is; the
        # output of ifstat looks like:
        #
        ## net0: 00:26:55:dd:4a:9d using 82571eb on 0000:6d:00.0 (open)
        ##   [Link:up, TX:8 TXE:1 RX:44218 RXE:44205]
        ##   [TXE: 1 x "Network unreachable (http://ipxe.org/28086090)"]
        ##   [RXE: 43137 x "Operation not supported (http://ipxe.org/3c086083)"]
        ##   [RXE: 341 x "The socket is not connected (http://ipxe.org/380f6093)"]
        ##   [RXE: 18 x "Invalid argument (http://ipxe.org/1c056082)"]
        ##   [RXE: 709 x "Error 0x2a654089 (http://ipxe.org/2a654089)"]
        ## net1: 00:26:55:dd:4a:9c using 82571eb on 0000:6d:00.1 (open)
        ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
        ##   [Link status: Down (http://ipxe.org/38086193)]
        ## net2: 00:26:55:dd:4a:9f using 82571eb on 0000:6e:00.0 (open)
        ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
        ##   [Link status: Down (http://ipxe.org/38086193)]
        ## net3: 00:26:55:dd:4a:9e using 82571eb on 0000:6e:00.1 (open)
        ##   [Link:down, TX:0 TXE:0 RX:0 RXE:0]
        ##   [Link status: Down (http://ipxe.org/38086193)]
        ## net4: 98:4f:ee:00:05:04 using NII on NII-0000:01:00.0 (open)
        ##   [Link:up, TX:10 TXE:0 RX:8894 RXE:8441]
        ##   [RXE: 8173 x "Operation not supported (http://ipxe.org/3c086083)"]
        ##   [RXE: 268 x "The socket is not connected (http://ipxe.org/380f6093)"]
        #
        # thus we need to match the one that fits our mac address
        ifstat = target.shell.run("ifstat", output = True, trim = True,
                                  timeout = timeout)
        regex = re.compile(
            "(?P<ifname>net[0-9]+): %s using" % mac_addr.lower(),
            re.MULTILINE)
        m = regex.search(ifstat)
        if not m:
            raise tcfl.tc.error_e(
                "iPXE: cannot find interface name for MAC address %s;"
                " is the MAC address in the configuration correct?"
                % mac_addr.lower(),
                dict(target = target, ifstat = ifstat,
                     mac_addr = mac_addr.lower())
            )
        ifname = m.groupdict()['ifname']

        # Before we configure, disable all the network interfaces
        # so we don't get bad routing if any are already
        # configured; we want to only route on the in @ifname
        # first extract all interface names and then close'em all
        regex = re.compile(
            "^(?P<ifname>net[0-9]+): .*$",
            re.MULTILINE)
        ifnames = re.findall(regex, ifstat)
        for disable_ifname in ifnames:
            target.shell.run(
                f"ifclose {disable_ifname}"
                "    # disable so we don't get incorrect routing",
                timeout = timeout)
        # wait until we scan to install this
        target.testcase.expect_global_append(expecter_ipxe_error)

        if dhcp:
            target.shell.run("dhcp " + ifname, re.compile("Configuring.*ok"),
                             timeout = timeout)
            target.shell.run("show %s/ip" % ifname, timeout = timeout)
        else:
            # static is much faster and we know the IP address already
            # anyway; but then we don't have DNS as it is way more
            # complicated to get it

            boot_ic = target.kws.get(
                'pos.boot_interconnect',
                target.kws.get('pos_boot_interconnect', None))
            if boot_ic == None:
                raise tcfl.error_e(
                    "can't configure IP statically:"
                    " no pos.boot_interconnect in inventory to get MAC addr",
                    { "target": target })
            mac_addr = target.kws['interconnects'][boot_ic]['mac_addr']
            ipv4_addr = target.kws['interconnects'][boot_ic]['ipv4_addr']
            ipv4_prefix_len = target.kws['interconnects'][boot_ic]['ipv4_prefix_len']

            target.shell.run("set %s/ip %s" % (ifname, ipv4_addr),
                             timeout = timeout)
            target.shell.run("set %s/netmask %s" % (ifname, commonl.ipv4_len_to_netmask_ascii(ipv4_prefix_len)),
                             timeout = timeout)
            target.shell.run("ifopen " + ifname,
                             timeout = timeout)

        if precommands:
            for precommand in precommands:
                target.shell.run(precommand, timeout = timeout)

        if sanboot_url == "skip":
            target.report_skip(
                "not sanbooting since 'skip' was given as sanboot_url")
        elif sanboot_url.endswith(".ipxe"):
            target.send("boot %s" % sanboot_url)
        else:
            target.send("sanboot %s" % sanboot_url)
    finally:
        try:
            target.testcase.expect_global_remove(expecter_ipxe_error)
        except KeyError:
            # in case we excepted before installing the handler,
            # we are ok with it
            pass
        target.shell.prompt_regex = prompt_orig


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



#
# PCI selector support specification
#

pci_selector_regex_entry = re.compile(
        "^"
        "(?P<pcivid>[^:]*)"
        ":(?P<pcidid>[^:]*)"
        "(:(?P<pci_path>[^:]*)"
        "(:(?P<type>.+)))?"
        "$"
    )


def pci_selector_spec_compile(spec: str, qualifier: str = "PCI selector") -> dict:
    """Compile a PCI selector specification

    >>> pci_selector_spec = '''
    >>> 8086:1533::BHS-.*
    >>> 8086:1533::OKS-.*
    >>> :1533
    >>> '''
    >>> pci_selector_regexes = pci_selector_spec_compile(pci_selector_spec)

    :param str spec: PCI Selector specification string; is a
      whitespace separated string of
      entries that describe possible PCI devices, in the form::

        PCIVID:PCIDID(:[[DDDD.][BB.DD[.FF]]:TYPE)

      - all entries are python regex patterns

      - an empty entry means anything will match

      - all entries are to be matched (case ignored) against the target
        devices, which will be as::

          VENDORID:DEVICEID:DOMAIN.BUS.DEVICE.FUNCTION:TARGETTYPE

        All numbers (VENDORID, DEVICEID, DOMAIN, BUS, DEVICE, FUNCTION)
        are in lowercase hex (without 0x prefix).

      - TYPE is matched against the target type
    """
    regexes = {}
    count = 0
    for v in spec.split():
        count += 1
        v = v.strip()
        if v == "+":
            regexes = {}
        m = pci_selector_regex_entry.search(v)
        if not m:
            continue
        regexes[v] = {}
        for field in [ "pcivid", "pcidid", "pci_path", "type" ]:
            try:
                if m.group(field):
                    regexes[v][field] = re.compile(m.group(field), re.IGNORECASE)
            except Exception as e:
                raise RuntimeError(f"{qualifier}: can't parse entry #{count}"
                                   f" of spec '{v}', field '{field}': {e}") from e


    return regexes


def pci_selector_match(pci_selector_regexes: dict, spec: str) -> bool:
    """Compile a PCI selector specification

    >>> pci_selector_spec = '''
    >>> 8086:1533::BHS-.*
    >>> 8086:1533::OKS-.*
    >>> :1533
    >>> '''
    >>> pci_selector_regexes = pci_selector_spec_compile(pci_selector_spec)
    >>> pci_selector_match(pci_selector_regexes, "8086:1533:00.2a.00.0:OKS-JC-DMR")

    :param dict pci_selector_regexes: compiled PCI selector specs; see
      :func:`pci_selector_spec_compile` for the format spec and to
      generate it.

    :param str spec: PCI spec to match against

    :returns bool: *True* if the spec matches any regex in the
      selector argument; *False* otherwise.
    """
    spec_m = pci_selector_regex_entry.search(spec)
    if not spec_m:
        raise RuntimeError("{spec} is not a valid PCI Selector expression")

    for selector, selector_regexs in pci_selector_regexes.items():
        # each regex has N fields; the ones that are not specified are
        # optional, so are a True; but the ones specified need to
        # match
        matches = False
        for field, regex_field in selector_regexs.items():
            value = spec_m.groupdict().get(field, None)
            if not value:	# a non match, there has to be a value bc...
                break		# ... we have a regex
            m = regex_field.search(value)
            if not m:
                break    	# a non match, value doesn't fit regex
        else:
            matches = True	# no non-matches, so we are good
        if matches:
            return True		# all fields specified matched, so we good

    return False		# no matches


def console_dump_on_failure(testcase, alevel = 0):
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
    for target in list(testcase.targets.values()):
        if not hasattr(target, "console"):
            continue
        attachments = {}
        console_list = target.console.list()
        if len(console_list) == 1:
            attachments["console"] = target.console.generator_factory(None)
        else:
            for console in console_list:
                target.console.capture_complete(console)
                attachments['console[' + console + ']'] = \
                    target.console.generator_factory(console)
        if testcase.result_eval.failed:
            target.report_fail("console dump due to failure",
                               attachments, alevel = alevel)
        elif testcase.result_eval.errors:
            target.report_error("console dump due to errors",
                                attachments, alevel = alevel)
        else:
            target.report_blck("console dump due to blockage",
                               attachments, alevel = alevel)

def target_ic_kws_get(target, ic, keyword, default = None):
    target.report_info(
        "DEPRECATED: tcfl.tl.target_ic_kws_get() deprecated in"
        " favour of target.ic_key_get()",
        dict(trace = traceback.format_stack()))
    return target.ic_key_get(ic, keyword, default)


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
    for dummy_twn, target  in reversed(list(testcase.targets.items())):
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
    assert filename == None or isinstance(filename, str)
    if filename == None:
        filename = \
            "report-%(runid)s:%(tc_hash)s" % ic.kws \
            + "-%d" % (ic.testcase.eval_count + 1) \
            + ".tcpdump"
    ic.power.off()		# ensure tcpdump flushes
    ic.store.dnload(ic.kws['tc_hash'] + ".cap", filename)
    ic.report_info("tcpdump available in file %s" % filename)


_os_release_regex = re.compile("^[_A-Z]+=.*$")



def linux_ifname_by_mac(target, mac_addr: str) -> str:
    """
    Return the name of the network interface with the given MAC
    address using Linux shell commands.

    This uses the *ip* command to list current interfaces

    :param tcfl.target_c target: target where to operate

    :param str mac_addr: MAC address to look for

       >> mac_addr = "00:11:22:33:44:55"

    :return str: interface's name if MAC address found

    :raises tcfl.error_e: if MAC address not found
    """
    assert isinstance(mac_addr, str), \
        f"mac_addr: expected str, got {type(mac_addr)}"
    # ip -o link
    ##1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    ##2: enp1s0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc mq state DOWN mode DEFAULT group default qlen 1000\    link/ether 98:4f:ee:00:68:51 brd ff:ff:ff:ff:ff:ff
    ##3: bootnet: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000\    link/ether 40:a6:b7:66:38:a0 brd ff:ff:ff:ff:ff:ff\    altname enp129s0\    altname ens5
    ##4: ens11: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000\    link/ether 40:a6:b7:8d:92:60 brd ff:ff:ff:ff:ff:ff\    altname enp56s0
    output = target.shell.run("ip -o link", output = True)
    mac_addr = mac_addr.lower()
    for line in output.splitlines():
        line = line.strip().lower()
        if mac_addr in line:
            # the ifname ends in colon, which we need to remove
            ifname = line.split()[1].rstrip(":")
            return ifname

    raise tcfl.tc.error_e(f"{target.id}: can't find interface"
                          f" with MAC {mac_addr}",
                          { 'interfaces': output })



def linux_if_configure_static(target, ifname,
                              network = None,
                              ipv4_addr = None, ipv4_prefix_len = None,
                              ipv6_addr = None, ipv6_prefix_len = None):
    """
    Configure a Linux network interface using ip commands

    :param tcfl.target_c target: target whose interface is to be configured

    :param str ifname: name of the network interface to configure

    :param tcfl.target_c network: (optional) network to which the target is
      connected; the target's inventory describes a connection to a
      network in the *interconnects.NWNAME* section. From there, the MAC
      address for the network connection can be obtained and different
      methods for configuring can be selected/implemented.

      If not specified, *ipv4_addr*, *ipv4_prefix_len* and/or
      *ipv6_addr*, *ipv6_prefix_len*  have to be specified.

    :param str ipv4_addr: IPv4 address of the server in the VLAN;
      normally we use .1 for the server and the second nibble (4
      in the example) matches the VLAN:

      >>> ipv4_addr = "192.4.0.1"

    :param int ipv4_prefix_len: IPv4 address prefix; (0-32) used to
      determine the network mask; most common: 8, 16, 24.

      Building on the previous example:

      >>> ipv4_prefix_len = 16

      Would assing to this VLAN an IPv4 range of 65k IP addresses,
      with a server/router 192.4.0.1, a network address 192.4.0.0
      and a broadcast 192.4.255.255.

    :param str ipv4_addr: same as ipv4_addr, but for IPv6 addresses:

      >>> ipv6_addr = "fd:99:4::1"

    :param int ipv6_prefix_len: same as ipv4_prefix_len, but for
      IPv6 addresses.

      Building on the previous example:

      >>> ipv6_prefix_len = 104

    """
    assert isinstance(target, tcfl.tc.target_c), \
        f"target: expected tcfl.tc.target_c; got {type(target)}"
    if network == None:
        assert ( ipv4_addr and ipv4_prefix_len ) \
            or ( ipv6_addr and ipv6_prefix_len ), \
            "no network specified, IPv4 and/or IPv6 addresses" \
            " need to be provided"
    else:
        assert isinstance(target, tcfl.tc.target_c), \
            f"network: expected tcfl.tc.target_c; got {type(network)}"
        ipv4_addr = target.addr_get(network, "ipv4")
        ipv4_prefix_len = target.ic_field_get(network, "ipv4_prefix_len", "(prefix_len)")
        ipv6_addr = target.addr_get(network, "ipv6")
        ipv6_prefix_len = target.ic_field_get(network, "ipv6_prefix_len", "(prefix_len)")

    target.shell.run(
        f"ip link set dev {ifname} up")
    target.shell.run(
        f"ip addr flush dev {ifname}	# clean previous config")
    if ipv6_addr and ipv6_prefix_len:
        target.shell.run(
            f"ip addr add {ipv6_addr}/{ipv6_prefix_len} dev {ifname}")
    if ipv4_addr and ipv4_prefix_len:
        target.shell.run(
            f"ip addr add {ipv4_addr}/{ipv4_prefix_len} dev {ifname}")



def linux_if_configure_dhclient(target, ifname: str):
    """
    Configure a Linux network interface using dhclient

    :param tcfl.target_c target: target whose interface is to be configured

    :param str ifname: name of the network interface to configure
    """
    assert isinstance(target, tcfl.tc.target_c), \
        f"target: expected tcfl.tc.target_c; got {type(target)}"
    # Configure using dhclient
    target.shell.run(
        f"dhclient -x {ifname}   # kill maybe running instance first")
    target.shell.run(
        f"dhclient {ifname}    # blocks until address acquired")



def linux_if_configure(target, network, method: str = "static"):
    """
    Configure the network interface connected to a given network
    address using Linux shell commands.

    :param tcfl.target_c target: target whose interface is to be configured

    :param tcfl.target_c network: network to which the target is
      connected; the target's inventory describes a connection to a
      network in the *interconnects.NWNAME* section. From there, the MAC
      address for the network connection can be obtained and different
      methods for configuring can be selected/implemented.

    :param str method: (optional; default *static*) method to
      configure the network interface:

      - *static*: use the IP information in the inventory fields
        *ipv4_addr*, *ipv4_prefix_len*, *ipv6_addr*,
        *ipv6_prefix_len*.

      - *dhcp*, *dhclient*: configure the interface using DHCP and
        *dhclient*

    """
    assert isinstance(target, tcfl.tc.target_c), \
        f"target: expected tcfl.tc.target_c; got {type(target)}"
    assert isinstance(network, tcfl.tc.target_c), \
        f"network: expected tcfl.tc.target_c; got {type(network)}"
    methods = { 'static', 'dhcp', 'dhclient' }
    assert method in methods, \
        f"method: expected one of {','.join(methods)}; got '{method}'"
    if method == 'dhcp':
        method = "dhclient"

    mac_addr = target.addr_get(network, "mac")
    base_ifname = tcfl.tl.linux_ifname_by_mac(target, mac_addr)

    vlan_id = target.kws.get(f'interconnects.{network.id}.vlan_id', None)
    # allow doing untagged by not setting vlan_id in the target's inventory
    #if vlan_id == None:
    #    vlan_id = network.kws.get('vlan_id', None)
    #if vlan_id == None:
    #    vlan_id = network.kws.get('vlan', None)
    if vlan_id != None:
        ifname = network.id
        target.shell.run(		# flush
            f"ip link delete {network.id} || true")
        target.shell.run(
            "ip link add"
            f" link {base_ifname} name {network.id}"
            f" type vlan id {vlan_id}")
        target.shell.run(
            f"ip link set dev {base_ifname} up")
    else:
        ifname = base_ifname

    if method == "static":
        linux_if_configure_static(target, ifname, network = network)
    elif method == "dhclient":
        linux_if_configure_dhclient(target, ifname)



def linux_if_add(target, new_ifname: str, ifname: str, mac_addr: str):
    """
    Adds a new virtual network interface associated with an existing one

    :param tcfl.target_c target: target where to execute commands

    :param str new_ifname: name of the new interface (must be less
      than 16 characters)

      >> new_ifname = "eth_fake"

    :param str ifname: name of the existing interface the new
      interface will be associated with.

      >> new_ifname = "ens28"

    :param str mac_addr: MAC address for the new interface (six hex bytes
      separated by colons).

      >> mac_addr = "00:11:22:33:44:55"

    """
    target.shell.run(
        f"ip link delete {new_ifname} || true   # flush existing?")
    target.shell.run(
        f"ip link add  link {ifname} name {new_ifname}"
        f" address {mac_addr} type macvlan")
    target.shell.run(
        f"ip link dev {new_ifname} set up")



def linux_os_release_get(target, prefix = ""):
    """
    Get the os-release file from a Linux target and return its
    contents as a dictionary.

    /etc/os-release is documented in
    https://www.freedesktop.org/software/systemd/man/os-release.html

    :param tcfl.tc.target_c target: target on which to run (must be
      started and running a Linux OS)
    :returns: dictionary with the */etc/os-release* values, such as:

      >>> os_release = tcfl.tl.linux_os_release_get(target)
      >>> print os_release
      >>> { ...
      >>>     'ID': 'fedora',
      >>>     'VERSION_ID': '29',
      >>>   ....
      >>> }
    """
    os_release = {}
    output = target.shell.run("cat %s/etc/os-release || true" % prefix,
                              output = True, trim = True)
    # parse painfully line by line, this way it might be better at
    # catching corruption in case we had output from kernel or
    # whatever messed up in the output of the command
    for line in output.split("\n"):
        line = line.strip()
        if not _os_release_regex.search(line):
            continue
        field, value = line.strip().split("=", 1)
        # remove leading and ending quotes
        os_release[field] = value.strip('"')

    target.kw_set("linux.distro", os_release['ID'].strip('"'))
    target.kw_set("linux.distro_version", os_release['VERSION_ID'].strip('"'))
    return os_release


def linux_mount_scratchfs(target,
                          reformat: bool = True, path: str = "/scratch"):
    """
    Mount in the target the TCF-scratch filesystem in */scratch*

    The default partitioning schemas define a partition with a label
    TCF-scratch that is available to be reformated and reused at will
    by any automation. This is made during deployment.

    This function creates an ext4 filesystem on it and mounts it in
    */scratch* if not already mounted.

    :param tcfl.tc.target_c target: target on which to mount

    :param bool reformat: (optional; default *True*) re-format the
      scratch file system before mounting it

    :param str path: (optional; default */scratch*) path where to
      mount the scratch file system.
    """
    output = target.shell.run("cat /proc/mounts", output = True, trim = True)
    if ' /scratch ' not in output:
        # not mounted already
        if reformat:
            target.shell.run("mkfs.ext4 -F /dev/disk/by-partlabel/TCF-scratch")
        target.shell.run(f"mkdir -p {path}")
        target.shell.run(f"mount /dev/disk/by-partlabel/TCF-scratch {path}")


def linux_ssh_root_nopwd(target, prefix = ""):
    """
    Configure a SSH deamon to allow login as root with no passwords

    .. _howto_restart_sshd:

    In a script:

    >>> tcfl.tl.linux_ssh_root_nopwd(target)
    >>> tcfl.tl.linux_sshd_restart(ic, target)

    or if doing it by hand, wait for *sshd* to be fully ready; it is a hack:

    >>> target.shell.run("systemctl restart sshd")
    >>> target.shell.run(           # wait for sshd to fully restart
    >>>     # this assumes BASH
    >>>     "while ! exec 3<>/dev/tcp/localhost/22; do"
    >>>     " sleep 1s; done", timeout = 10)

    - why not *nc*? easy and simple; not default installed in most distros

    - why not *curl*? most distros have it installed; if SSH is replying
      with the SSH-2.0 string, then likely the daemon is ready

      Recent versions of curl now check for HTTP headers, so can't be
      really used for this

    - why not plain *ssh*? because that might fail by many other
      reasons, but you can check the debug in *ssh -v* messages for a
      *debug1: Remote protocol version* string; output is harder to
      keep under control and *curl* is kinda faster, but::

        $ ssh -v localhost 2>&1 -t echo | fgrep -q 'debug1: Remote protocol version'

      is a valid test

    - why not *netstat*? for example::

        $  while ! netstat -antp | grep -q '^tcp.*:22.*LISTEN.*sshd'; do sleep 1s; done

      *netstat* is not always available, when available, that is also
       a valid test

    Things you can do after this:

    1. switch over to an SSH console if configured (they are faster
       and depending on the HW, more reliable):

       >>> target.console.setup_preferred()

    """
    target.shell.run('mkdir -p %s/etc/ssh' % prefix)
    target.shell.run(
        f'grep -qe "^PermitRootLogin yes" {prefix}/etc/ssh/sshd_config'
        f' || echo "PermitRootLogin yes" >> {prefix}/etc/ssh/sshd_config')
    target.shell.run(
        f'grep -qe "^PermitEmptyPasswords yes" {prefix}/etc/ssh/sshd_config'
        f' || echo "PermitEmptyPasswords yes" >> {prefix}/etc/ssh/sshd_config')


def deploy_linux_ssh_root_nopwd(_ic, target, _kws):
    linux_ssh_root_nopwd(target, "/mnt")


def linux_hostname_set(target, prefix = ""):
    """
    Set the target's OS hostname to the target's name

    :param tcfl.tc.target_c target: target where to run

    :param str prefix: (optional) directory where the root partition
      is mounted.
    """
    target.shell.run("echo %s > %s/etc/hostname" % (target.id, prefix))

def deploy_linux_hostname_set(_ic, target, _kws):
    linux_hostname_set(target, "/mnt")

def linux_sshd_restart(ic, target):
    """
    Restart SSHD in a linux/systemctl system

    Use with :func:`linux_ssh_root_nopwd`
    """
    target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
    target.shell.run("systemctl restart sshd")
    target.shell.run(		# wait for sshd to fully restart
        # this assumes BASH
        "while ! exec 3<>/dev/tcp/localhost/22; do"
        " sleep 1s; done", timeout = 15)
    time.sleep(2)	# SSH settle
    # force the SSH tunnel on 22 being re-created -- since it might be
    # toast...bit it will distirb ithir thrids? we just restarted
    # sshd. They were disturbed
    last_e = None
    target.tunnel.remove(22)
    for _count in range(4):
        try:
            target.ssh.check_call("echo Checking SSH tunnel is up")
            break
        except tcfl.error_e as e:
            last_e = e
            data = e.attachments
            target.report_info(
                f"SSH tunnel not up: SSH returned {data['returncode']}",
                e.attachments)
            continue
    else:
        raise last_e


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

def proxy_collect(ic, target):
    """
    Collect proxy information from the inventory and return it

    Note the proxies might be different based on which network the
    target is connected to.

    The order of sources tried is:

    - TARGET.interconnects.INTERCONNECTNAME.<XYZ>_proxy
    - INTERCONNECTNAME.<XYZ>_proxy
    - TARGET.support.<XYZ>_proxy

    :param tcfl.target_c ic: interconnect the target is connected to
    :param tcfl.target_c target: target for which we want proxies
    :return dict: dictionary with the final proxy information:

      - *http_proxy*: string for the proxy
      - *https_proxy*: string for the proxy
      - *ftp_proxy*: string for the proxy
      - *no_proxy*: *list* of strings describing hostnames/ips/domains
        for which no proxy has to be added

      any of this fields maybe missing if not present

    """

    d = {}
    ftp_proxy =  target.ic_key_get(
        ic, 'ftp_proxy', target.kws.get('support.ftp_proxy', None))
    http_proxy =  target.ic_key_get(
        ic, 'http_proxy', target.kws.get('support.http_proxy', None))
    https_proxy =  target.ic_key_get(
        ic, 'https_proxy', target.kws.get('support.https_proxy', None))
    # no proxy list is harder, locallost, defaults and the IPv4/IPv6
    no_proxyl = set(target.ic_key_get(
        ic, 'no_proxy', target.kws.get('support.no_proxy', "")).split(","))
    # if we are setting a proxy, make sure it doesn't do the
    # local networks
    no_proxyl.add("127.0.0.1")
    no_proxyl.add("localhost")
    if 'ipv4_addr' in ic.kws:
        no_proxyl.add("%(ipv4_addr)s/%(ipv4_prefix_len)s" % ic.kws)
    if 'ipv6_addr' in ic.kws:
        no_proxyl.add("%(ipv6_addr)s/%(ipv6_prefix_len)s" % ic.kws)

    # Collect and fill out the dictionary
    if ftp_proxy:
        d['http_proxy'] = http_proxy
    if http_proxy:
        d['http_proxy'] = http_proxy
    if https_proxy:
        d['https_proxy'] = https_proxy
    if d and no_proxyl:
        # only set no_proxy if any proxy was set
        d['no_proxy'] = ",".join(no_proxyl)

    return d


def sh_export_proxy(ic, target):
    """
    If the interconnect *ic* defines a proxy environment, issue a
    shell command in *target* to export environment variables that
    configure it:

    >>> class test(tcfl.tc.tc_c):
    >>>
    >>>     def eval_some(self, ic, target):
    >>>         ...
    >>>         tcfl.tl.sh_export_proxy(ic, target)

    would yield a command such as::

       $ export  http_proxy=http://192.168.98.1:8888 \
          https_proxy=http://192.168.98.1:8888 \
          no_proxy=127.0.0.1,192.168.98.1/24,fd:00:62::1/104 \
          HTTP_PROXY=$http_proxy \
          HTTPS_PROXY=$https_proxy \
          NO_PROXY=$no_proxy

    being executed in the target

    """
    proxies = proxy_collect(ic, target)
    if 'http_proxy' in proxies:
        target.shell.run("export http_proxy=%(http_proxy)s; "
                          "export HTTP_PROXY=$http_proxy" % proxies)
    if 'https_proxy' in proxies:
        target.shell.run("export https_proxy=%(https_proxy)s; "
                         "export HTTPS_PROXY=$https_proxy" % proxies)
    if 'ftp_proxy' in proxies:
        target.shell.run("export ftp_proxy=%(ftp_proxy)s; "
                         "export FTP_PROXY=$ftp_proxy" % proxies)
    if 'no_proxy' in proxies:
        target.shell.run("export no_proxy=%(no_proxy)s; "
                         "export NO_PROXY=$no_proxy" % proxies)
    return proxies


def sh_proxy_environment(ic, target, prefix = "/"):
    """
    If the interconnect *ic* defines a proxy environment, issue
    commands to write the proxy configuration to the target's
    */etc/environment*.

    As well, if the directory */etc/apt/apt.conf.d* exists in the
    target, an APT proxy configuration file is created there with the
    same values.

    See :func:`tcfl.tl.sh_export_proxy`
    """
    proxies = proxy_collect(ic, target)
    apt_proxy_conf = []
    dnf_proxy = None

    # FIXME: we need to change proxies in targets to be homed in the
    # proxy hierarchy as a backup? they are always network specific anyway?
    proxy_hosts = {}

    etc_environment = False
    if 'ftp_proxy' in proxies:
        etc_environment = True
        target.shell.run(
            "grep -qi 'ftp_proxy=%(ftp_proxy)s}' /etc/environment"
            " || echo -e 'ftp_proxy=%(ftp_proxy)s\nFTP_PROXY=%(ftp_proxy)s'"
            " >> /etc/environment" % proxies)
        apt_proxy_conf.append('FTP::proxy "%(ftp_proxy)s";' % proxies)

    if 'http_proxy' in proxies:
        etc_environment = True
        target.shell.run(
            "grep -qi 'http_proxy=%(http_proxy)s}' /etc/environment"
            " || echo -e 'http_proxy=%(http_proxy)s\nHTTP_PROXY=%(http_proxy)s'"
            " >> /etc/environment" % proxies)
        apt_proxy_conf.append('HTTP::proxy "%(http_proxy)s";' % proxies)
        dnf_proxy = proxies['http_proxy']

    if 'https_proxy' in proxies:
        etc_environment = True
        target.shell.run(
            "grep -qi 'http_proxy=%(https_proxy)s}' /etc/environment"
            " || echo -e 'https_proxy=%(https_proxy)s\nHTTPS_PROXY=%(https_proxy)s'"
            " >> /etc/environment" % proxies)
        apt_proxy_conf.append('HTTPS::proxy "%(https_proxy)s";' % proxies)
        dnf_proxy = proxies['https_proxy']	# override https if available

    if 'no_proxy' in proxies:
        etc_environment = True
        target.shell.run(
            "grep -qi 'no_proxy=%(no_proxy)s' /etc/environment"
            " || echo -e 'no_proxy=%(no_proxy)s\nNO_PROXY=%(no_proxy)s'"
            " >> /etc/environment" % proxies)

    if etc_environment:
        # we updated, let's re-parse
        target.shell.run(". /etc/environment")

    if apt_proxy_conf:
        target.shell.run(
            "test -d /etc/apt/apt.conf.d"
            " && cat > /etc/apt/apt.conf.d/tcf-proxy.conf <<EOF\n"
            "Acquire {\n"
            + "\n".join(apt_proxy_conf) +
            "}\n"
            "EOF")

    # there is no way to distinguis https vs http so we need to make a
    # wild guess by overriding
    if dnf_proxy:
        target.shell.run(
            "rm -f /tmp/dnf.conf; test -r /etc/dnf/dnf.conf"
            # sed's -n and -i don't play well, so copy it to post-process
            f" && cp /etc/dnf/dnf.conf /tmp/dnf.conf"
            # sed: wipe existing proxy (if any) add new setting
            # hack: assumes [main] section is the only one
            f" && sed -n -e '/^proxy=/!p' -e '$aproxy={dnf_proxy}' /tmp/dnf.conf > /etc/dnf/dnf.conf")

    return proxy_hosts


def linux_wait_online(ic, target, loops = 60, wait_s = 0.5):
    """
    Wait on the serial console until the system is assigned an IP

    We make the assumption that once the system is assigned the IP
    that is expected on the configuration, the system has upstream
    access and thus is online.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(ic, tcfl.tc.target_c) \
        and "interconnect_c" in ic.kws['interfaces'], \
        "argument 'ic' shall be an interconnect/network target"
    assert loops > 0
    assert wait_s > 0
    target.shell.run(
        "for i in {1..%d}; do"
        " hostname -I | grep -Fq %s && break;"
        " date +'waiting %.1f @ %%c';"
        " sleep %.1fs;"
        "done; "
        "hostname -I "
        "# block until the expected IP is assigned, we are online"
        % (loops, target.addr_get(ic, "ipv4"), wait_s, wait_s),
        timeout = (loops + 1) * wait_s)


def linux_wait_host_online(target, hostname, loops = 20):
    """
    Wait on the console until the given hostname is pingable

    We make the assumption that once the system is assigned the IP
    that is expected on the configuration, the system has upstream
    access and thus is online.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(hostname, str)
    assert loops > 0
    target.shell.run(
        "for i in {1..%d}; do"
        " ping -c 3 %s && break;"
        "done; "
        "# block until the hostname pongs"
        % (loops, hostname),
        # three pings at one second each
        timeout = (loops + 1) * 3 * 1)


def linux_wait_host_port_online(target, hostname, port, loops = 5):
    """
    Wait on the console until the given hostname and port are connectable

    We make the assumption that once the system is assigned the IP
    that is expected on the configuration, the system has upstream
    access and thus is online.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(hostname, str), \
        "hostname: expected str; got {type(hostname)}"
    assert loops > 0
    target.shell.run(
        f"for i in {{1..{loops}}}; do"
        # this assumes netcat/nc is available
        f"  echo Checking for 5s if TCP:{hostname}:{port} is open;"
        f"  nc -w 5 -vz {hostname} {port} && break; "
        f"done",
        # N loops at 5s second each, timeout one loop early
        timeout = (loops - 1) * 5)


def linux_rsync_cache_lru_cleanup(target, path, max_kbytes):
    """Cleanup an LRU rsync cache in a path in the target

    An LRU rsync cache is a file tree which is used as an accelerator
    to rsync trees in to the target for the POS deployment system;

    When it grows too big, we need to purge the files/dirs that were
    uploaded longest ago (as this indicates when it was the last time
    they were used). For that we use the mtime and we sort by it.

    Note this is quite naive, since we can't really calculate well the
    space occupied by directories, which adds to the total...

    So it sorts by reverse mtime (newest first) and iterates over the
    list until the accumulated size is more than max_kbytes; then it
    starts removing files.

    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(path, str)
    assert max_kbytes > 0

    testcase = target.testcase
    target.report_info(
        "rsync cache: reducing %s to %dMiB" % (path, max_kbytes / 1024.0))

    prompt_original = target.shell.prompt_regex
    python_error_ex = target.console.text(
        re.compile("^(.*Error|Exception):.*^>>> ", re.MULTILINE | re.DOTALL),
        name = "python error",
        timeout = 0, poll_period = 1,
        raise_on_found = tcfl.tc.error_e("error detected in python"))
    testcase.expect_tls_append(python_error_ex)
    try:
        target.send("TTY=dumb python || python2 || python3")	 # launch python!
        # This lists all the files in the path recursively, sorting
        # them by oldest modification time first.
        #
        # In Python? Why? because it is much faster than doing it in
        # shell when there are very large trees with many
        # files. Make sure it is 2 and 3 compat.
        #
        # Note we are feeding lines straight to the python
        # interpreter, so we need an extra newline for each
        # indented block to close them.
        #
        # The list includes the mtime, the size and the name  (not using
        # bisect.insort() because it doesn't support an insertion key
        # easily).
        #
        # Then start iterating newest first until the total
        # accumulated size exceeds what we have been
        # asked to free and from there on, wipe all files.
        #
        # Note we list directories after the files; since
        # sorted(), when sorted by mtime is most likely they will
        # show after their contained files, so we shall be able to
        # remove empty dirs. Also, sorted() is stable. If they
        # were actually needed, they'll be brought back by rsync
        # at low cost.
        #
        # We use statvfs() to get the filesystem's block size to
        # approximate the actual space used in the disk
        # better. Still kinda naive.
        #
        # why not use scandir()? this needs to be able to run in
        # python2 for older installations.
        #
        # walk: walk depth first, so if we rm all the files in a dir,
        # the dir is empty and we will wipe it too after wiping
        # the files; if stat fails with FileNotFoundError, that's
        # usually a dangling symlink; ignore it. OSError will
        # likely be something we can't find, so we ignore it too.
        #
        # And don't print anything...takes too long for large trees
        target.shell.run("""
import os, errno, stat
l = []
dirs = []
try:
    fsbsize = os.statvfs('%(path)s').f_bsize
    for r, dl, fl in os.walk('%(path)s', topdown = False):
        for fn in fl + dl:
            fp = os.path.join(r, fn)
            try:
                s = os.stat(fp)
                sd = fsbsize * ((s.st_size + fsbsize - 1) / fsbsize)
                l.append((s.st_mtime, sd, fp, stat.S_ISDIR(s.st_mode)))
            except (OSError, FileNotFoundError) as x:
                pass
except (OSError, FileNotFoundError) as x:
    pass


acc = 0
sc = %(max_bytes)d
for e in sorted(l, key = lambda e: e[0], reverse = True):
    acc += e[1]
    if acc > sc:
        if e[3]:
            try:
                os.rmdir(e[2])
            except OSError as x:
                if x.errno == errno.ENOTEMPTY:
                    pass
        else:
            os.unlink(e[2])


exit()""" % dict(path = path, max_bytes = max_kbytes * 1024))
    finally:
        target.shell.prompt_regex = prompt_original
        testcase.expect_tls_remove(python_error_ex)

#
# Well, so this is a hack anyway; we probably shall replace this with
# a combination of:
#
# - seeing if the progress counter is updating
# - a total timeout dependent on the size of the package
#

#:
#: Timeouts for adding different, big size bundles
#:
#: To add to this configuration, specify in a client configuration
#: file or on a test script:
#:
#: >>> tcfl.tl.swupd_bundle_add_timeouts['BUNDLENAME'] = TIMEOUT
#:
#: note timeout for adding a bundle defaults to 240 seconds.
swupd_bundle_add_timeouts = {
    # Keep this list alphabetically sorted!
    'LyX': 500,
    'R-rstudio': 1200, # 1041MB
    'big-data-basic': 800, # (1049MB)
    'c-basic': 500,
    'computer-vision-basic': 800, #1001MB
    'container-virt': 800, #197.31MB
    'containers-basic-dev': 1200, #921MB
    'database-basic-dev': 800, # 938
    'desktop': 480,
    'desktop-dev': 2500,	# 4500 MiB
    'desktop-autostart': 480,
    'desktop-kde-apps': 800, # 555 MB
    'devpkg-clutter-gst': 800, #251MB
    'devpkg-gnome-online-accounts': 800, # 171MB
    'devpkg-gnome-panel': 800, #183
    'devpkg-nautilus': 800, #144MB
    'devpkg-opencv': 800, # 492MB
    'education': 800,
    'education-primary' : 800, #266MB
    'game-dev': 6000, # 3984
    'games': 800, # 761MB
    'java-basic': 1600, # 347MB
    'java9-basic': 1600, # 347MB
    'java11-basic': 1600,
    'java12-basic': 1600,
    'java13-basic': 1600,
    'machine-learning-basic': 1200, #1280MB
    'machine-learning-tensorflow': 800,
    'machine-learning-web-ui': 1200, # (1310MB)
    'mail-utils-dev ': 1000, #(670MB)
    'maker-cnc': 800, # (352MB)
    'maker-gis': 800, # (401MB)
    'network-basic-dev': 1200, #758MB
    'openstack-common': 800, # (360MB)
    'os-clr-on-clr': 8000,
    'os-clr-on-clr-dev': 8000,	# quite large too
    'os-core-dev': 800,
    'os-testsuite': 1000,
    'os-testsuite-phoronix': 2000,	# 4000MiB
    'os-testsuite-phoronix-desktop': 1000,
    'os-testsuite-phoronix-server': 1000,
    'os-util-gui': 800, #218MB
    'os-utils-gui-dev': 6000, #(3784MB)
    'python-basic-dev': 800, #466MB
    'qt-basic-dev': 2400, # (1971MB)
    'service-os-dev': 800, #652MB
    'storage-cluster': 800, #211MB
    'storage-util-dev': 800, # (920MB)
    'storage-utils-dev': 1000, # 920 MB
    'supertuxkart': 800, # (545 MB)
    'sysadmin-basic-dev': 1000, # 944 MB
    'texlive': 1000, #1061
}

def swupd_bundle_add(ic, target, bundle_list,
                     debug = None, url = None,
                     wait_online = True, set_proxy = True,
                     fix_time = None, add_timeout = None,
                     become_root = False):
    """Install bundles into a Clear distribution

    This is a helper that install a list of bundles into a Clear
    distribution taking care of a lot of the hard work.

    While it is preferrable to have an open call to *swupd bundle-add*
    and it should be as simple as that, we have found we had to
    repeatedly take manual care of many issues and thus this helper
    was born. It will take take care of:

    - wait for network connectivity [convenience]
    - setup proxy variables [convenience]
    - set swupd URL from where to download [convenience]
    - fix system's time for SSL certification (in *broken* HW)
    - retry bundle-add calls when they fail due:
      - random network issues
      - issues such as::

          Error: cannot acquire lock file. Another swupd process is \
          already running  (possibly auto-update)

      all retryable after a back-off wait.

    :param tcfl.tc.target_c ic: interconnect the target uses for
      network connectivity

    :param tcfl.tc.target_c target: target on which to operate

    :param bundle_list: name of the bundle to add or list of them;
      note they will be added each in a separate *bundle-add* command

    :param bool debug: (optional) run *bundle-add* with ``--debug--``;
      if *None*, defaults to environment *SWUPD_DEBUG* being defined
      to any value.

    :param str url: (optional) set the given *url* for the swupd's
      repository with *swupd mirror*; if *None*, defaults to
      environment *SWUPD_URL* if defined, otherwise leaves the
      system's default setting.

    :param bool wait_online: (optional) waits for the system to have
      network connectivity (with :func:`tcfl.tl.linux_wait_online`);
      defaults to *True*.

    :param bool set_proxy: (optional) sets the proxy environment with
      :func:`tcfl.tl.sh_export_proxy` if the interconnect exports proxy
      information; defaults to *True*.

    :param bool fix_time: (optional) fixes the system's time if *True*
      to the client's time.; if *None*, defaults to environment
      *SWUPD_FIX_TIME* if defined, otherwise *False*.

    :param int add_timeout: (optional) timeout to set to wait for the
      *bundle-add* to complete; defaults to whatever is configured in
      the :data:`tcfl.tl.swupd_bundle_add_timeouts` or the the default
      of 240 seconds.

    :param bool become_root: (optional) if *True* run the command as super
      user using *su* (defaults to *False*). To be used when the script has the
      console logged in as non-root.

      This uses *su* vs *sudo* as some installations will not install
      *sudo* for security reasons.

      Note this function assumes *su* is configured to work without
      asking any passwords. For that, PAM module *pam_unix.so* has to
      be configured to include the option *nullok* in target's files
      such as:

      - */etc/pam.d/common-auth*
      - */usr/share/pam.d/su*

      ``tcf-image-setup.sh`` will do this for you if using it to set
      images.
    """

    testcase = target.testcase

    # gather parameters / defaults & verify
    assert isinstance(ic, tcfl.tc.target_c)
    assert isinstance(target, tcfl.tc.target_c)
    if isinstance(bundle_list, str):
        bundle_list = [ bundle_list ]
    else:
        assert isinstance(bundle_list, collections.abc.Iterable) \
            and all(isinstance(item, str) for item in bundle_list), \
            "bundle_list must be a string (bundle name) or list " \
            "of bundle names, got a %s" % type(bundle_list).__name__

    if debug == None:
        debug = 'SWUPD_DEBUG' in os.environ
    else:
        assert isinstance(debug, bool)

    if url == None:
        url = os.environ.get('SWUPD_URL', None)
    else:
        assert isinstance(url, str)

    if fix_time == None:
        fix_time = os.environ.get("SWUPD_FIX_TIME", None)
    else:
        assert isinstance(fix_time, bool)

    # note add_timeout might be bundle-specific, so we can't really
    # set it here
    if add_timeout != None:
        assert add_timeout > 0
    assert isinstance(become_root, bool)

    # the system's time is untrusted; we need it to be correct so the
    # certificate verification works--set it from the client's time
    # (assumed to be correct). Use -u for UTC settings to avoid TZ
    # issues
    if fix_time:
        target.shell.run("date -us '%s'; hwclock -wu"
                         % str(datetime.datetime.utcnow()))

    if wait_online:		        # wait for connectivity to be up
        tcfl.tl.linux_wait_online(ic, target)

    kws = dict(
        debug = "--debug" if debug else "",
        hashid = testcase.kws['tc_hash']
    )
    if become_root:
        kws['su_prefix'] = "su -mc '"
        kws['su_postfix'] = "'"
    else:
        kws['su_prefix'] = ""
        kws['su_postfix'] = ""
    target.shell.run(			# fix clear certificates if needed
        "%(su_prefix)s"			# no space here, for su -mc 'COMMAND'
        "certs_path=/etc/ca-certs/trusted;"
        "if [ -f $certs_path/regenerate ]; then"
        " rm -f $certs_path/regenerate $certs_path/lock;"
        " clrtrust -v generate;"
        "fi"
        "%(su_postfix)s"		# no space here, for su -mc 'COMMAND'
        % kws)

    if set_proxy:			# set proxies if needed
        tcfl.tl.sh_export_proxy(ic, target)

    if url:				# set swupd URL if needed
        kws['url'] = url
        target.shell.run("%(su_prefix)sswupd mirror -s %(url)s%(su_postfix)s"
                         % kws)

    # Install them bundles
    #
    # installing can take too much time, so we do one bundle at a
    # time so the system knows we are using the target.
    #
    # As well, swupd doesn't seem to be able to recover well from
    # network glitches--so we do a loop where we retry a few times;
    # we record how many tries we did and the time it took as KPIs
    for bundle in bundle_list:
        kws['bundle'] = bundle
        # adjust bundle add timeout
        # FIXME: add patch to bundle-add to recognize --dry-run --sizes so
        # that it lists all the bundles it has to download and their sizes
        # so we can dynamically adjust this
        if add_timeout == None:
            if bundle in swupd_bundle_add_timeouts:
                _add_timeout = swupd_bundle_add_timeouts[bundle]
                target.report_info(
                    "bundle-add: adjusting timeout to %d per configuration "
                    "tcfl.tl.swupd_bundle_add_timeouts" % _add_timeout)
            else:
                _add_timeout = 240
        else:
            _add_timeout = add_timeout

        count = 0
        top = 10
        for count in range(1, top + 1):
            # WORKAROUND: server keeps all active
            target.testcase.targets_active()
            # We use -p so the format is the POSIX standard as
            # defined in
            # https://pubs.opengroup.org/onlinepubs/009695399/utilities
            # /time.html
            # STDERR section
            output = target.shell.run(
                "time -p"
                " %(su_prefix)sswupd bundle-add %(debug)s %(bundle)s%(su_postfix)s"
                " || echo FAILED''-%(hashid)s"
                % kws,
                output = True, timeout = _add_timeout)
            if not 'FAILED-%(tc_hash)s' % testcase.kws in output:
                # We assume it worked
                break
            if 'Error: Bundle too large by' in output:
                df = target.shell.run("df -h", output = True, trim = True)
                du = target.shell.run("du -hsc /persistent.tcf.d/*",
                                      output = True, trim = True)
                raise tcfl.tc.blocked_e(
                    "swupd reports rootfs out of space to"
                    " install bundle %(bundle)s" % kws,
                    dict(output = output, df = df, du = du))
            target.report_info("bundle-add: failed %d/%d? Retrying in 5s"
                               % (count, top))
            time.sleep(5)
        else:
            # match below's
            target.report_data("swupd bundle-add retries",
                               bundle, count)
            raise tcfl.tc.error_e("bundle-add failed too many times")

        # see above on time -p
        kpi_regex = re.compile(r"^real[ \t]+(?P<seconds>[\.0-9]+)$",
                               re.MULTILINE)
        m = kpi_regex.search(output)
        if not m:
            raise tcfl.tc.error_e(
                "Can't find regex %s in output" % kpi_regex.pattern,
                dict(output = output))
        # maybe domain shall include the top level image type
        # (clear:lts, clear:desktop...)
        target.report_data("swupd bundle-add retries",
                           bundle, int(count))
        target.report_data("swupd bundle-add duration (seconds)",
                           bundle, float(m.groupdict()['seconds']))

def linux_time_set(target):
    """
    Set the time in the target using the controller's date as a reference

    :param tcfl.tc.target_c target: target whose time is to be set

    """
    target.shell.run("date -us '%s'; hwclock -wu --noadjfile"
                     % str(datetime.datetime.utcnow()))


def linux_package_add(ic, target, *packages,
                      timeout = 120, fix_time = True,
                      proxy_wait_online = True,
                      **kws):
    """Ask target to install Linux packages in distro-generic way

    This function checks the target to see what it has installed and
    then uses the right tool to install the list of packages; distro
    specific package lists can be given:

    >>> tcfl.tl.linux_package_add(
    >>>      ic, target, [ 'git', 'make' ],
    >>>      centos = [ 'cmake' ],
    >>>      ubuntu = [ 'cmake' ])

    :param tcfl.tc.target_c ic: interconnect that provides *target*
      with network connectivity

    :param tcfl.tc.target_c target: target where to install

    :param list(str) packages: (optional) list of packages to install

    :param list(str) DISTROID: (optonal) list of packages to install,
      in addition to *packages* specific to a distro:

       - CentOS: use *centos*
       - Clear Linux OS: use *clear*
       - Fedora: use *fedora*
       - RHEL: use *rhel*
       - Ubuntu: use *ubuntu*

    :param bool proxy_wait_online: (optional, default *True*) if there
      are proxies defined, wait for them to be pingable before
      accessing the network.

    Anything that uses DNF can be modified by setting keyword
    *linux.dnf.install.options* in the target's keywords:

    >>> target.kws['linux.dnf.install.options'] = "--nobest -v"

    FIXME:

     - missing support for older distros and to specify packages
       for specific distro version

     - most of the goodes in swupd_bundle_add have to be moved here,
       like su/sudo support, ability to setup proxy, fix date and pass
       distro-specific setups (like URLs, etc)

    """
    assert isinstance(ic, tcfl.tc.target_c)
    assert isinstance(target, tcfl.tc.target_c)
    assert all(isinstance(package, str) for package in packages), \
            "package list must be a list of strings;" \
            " some items in the list are not"
    for key, packagel in kws.items():
        assert isinstance(packagel, list), \
            "value %s must be a list of strings; found %s" \
            % (key, type(packagel))
        assert all(isinstance(package, str) for package in packages), \
            "value %s must be a list of strings;" \
            " some items in the list are not" % key

    if not 'linux.distro' in target.kws or not 'linux.distro_version' in target.kws:
        os_release = linux_os_release_get(target)
        distro = os_release['ID']
        distro_version = os_release['VERSION_ID']
        target.kw_set("linux.distro", distro)
        target.kw_set("linux.distro_version", distro_version)
    else:
        distro = target.kws['linux.distro']
        distro_version = target.kws['linux.distro_version']

    if fix_time:
        # if the clock is messed up, SSL signing won't work for some things
        target.shell.run("date -us '%s'; hwclock -wu"
                         % str(datetime.datetime.utcnow()))

    if proxy_wait_online:
        with target.testcase.lock:
            # don't do this repeatedly, it is pointless
            checked = target.testcase.buffers.get(
                f"linux_package_add.proxy_wait_online.{ic.id}.{target.id}",
                None)
        if not checked:
            proxy_hosts = set()
            if 'ftp_proxy' in ic.kws:
                url = urllib.parse.urlparse(ic.kws['ftp_proxy'])
                proxy_hosts.add(( url.hostname, url.port ))
            if 'http_proxy' in ic.kws:
                url = urllib.parse.urlparse(ic.kws['http_proxy'])
                proxy_hosts.add(( url.hostname, url.port ))
            if 'https_proxy' in ic.kws:
                url = urllib.parse.urlparse(ic.kws['https_proxy'])
                proxy_hosts.add(( url.hostname, url.port ))
            if proxy_hosts:
                for hostname, port in proxy_hosts:
                    target.report_info(
                        f"waiting for proxies {hostname} to respond on port {port}")
                    linux_wait_host_port_online(target, hostname, port)
            with target.testcase.lock:
                target.testcase.buffers["linux_package_add.proxy_wait_online"
                                        f".{ic.id}.{target.id}"] = True

    packages = list(packages)
    if distro.startswith('clear'):
        _packages = packages + kws.get("any", []) + kws.get("clear", [])
        if _packages:
            tcfl.tl.swupd_bundle_add(ic, target, _packages,
                                     add_timeout = timeout,
                                     fix_time = True, set_proxy = True)
    elif distro == 'centos':
        _packages = packages + kws.get("any", []) + kws.get("centos", [])
        if _packages:
            target.shell.run(
                "dnf install"
                f" {target.kws.get('linux.dnf.install.options', '')}"
                " -y " +  " ".join(_packages),
            timeout = timeout)
    elif distro == 'fedora':
        _packages = packages + kws.get("any", []) + kws.get("fedora", [])
        if _packages:
            target.shell.run(
                f"dnf install --releasever {distro_version}"
                f" {target.kws.get('linux.dnf.install.options', '')} -y "
                +  " ".join(_packages),
                timeout = timeout)
    elif distro == 'rhel':
        _packages = packages + kws.get("any", []) + kws.get("rhel", [])
        if _packages:
            target.shell.run(
                "dnf install"
                f" {target.kws.get('linux.dnf.install.options', '')} "
                " -y " + " ".join(_packages),
                timeout = timeout)
    elif distro == 'ubuntu':
        _packages = packages + kws.get("any", []) + kws.get("ubuntu", [])
        if _packages:
            # FIXME: add needed repos [ubuntu|debian]_extra_repos
            target.shell.run(
                "sed -i 's/main restricted/main restricted universe multiverse/'"
                " /etc/apt/sources.list")
            target.shell.run("apt-get -qy update", timeout = timeout)
            target.shell.run(
                "DEBIAN_FRONTEND=noninteractive"
                " apt-get install -qy " +  " ".join(_packages),
                timeout = timeout)
    else:
        raise tcfl.tc.error_e("unknown OS: %s %s (from /etc/os-release)"
                              % (distro, distro_version))
    return distro, distro_version



@contextlib.contextmanager
def chroot_run(target, rootdir: str, message: str = None, **report_kwargs):
    """Enter an environment to execute commands in a systemd-nspawn chroot

    >>>  with tcfl.tl.chroot_run(target, "/somepath"):
    >>>      target.shell.run("ls -l")

    This is handled as a context manager; upon entering, it will run
    the *systemd-nspawn* command, setup the shell and then yield.

    All execution now runs under it--when exiting the block, it will
    kill the process, which will remove the chroot.

    :param tcfl.tc.target_c target: target where to operate
    :param str rootdir: path to the root of the chroot
    :param str message: (optional) message to include in the
      reporting information when entering and exiting the chroot
    """
    assert isinstance(target, tcfl.tc.target_c), \
        f"target: expected tcfl.tc.target_c; got {type(target)}"
    assert isinstance(rootdir, str), \
        f"rootdir: expected str; got {type(rootdir)}"
    assert message == None or isinstance(message, str), \
        f"message: expected str|None; got {type(message)}"
    try:
        if not message:
            message = rootdir
        target.report_info("entering systemd/nspawn chroot for" + message,
                           **report_kwargs)
        target.shell.run("# entering systemd/nspawn chroot for " + message)

        # SYSTEMD_NSPAWN_LOCK=0: don't lock, since the rootfs is RO
        # --register=no: no need to register, again, rootfs is RO
        # || true: so it doesn't print ERROR-IN-SHELL when we stop it
        # in finally:
        target.send(f"SYSTEMD_NSPAWN_LOCK=0 systemd-nspawn -D {rootdir} --register=no || true")
        target.shell.setup()
        target.shell.run(f"export PS1=CHROOT{rootdir}::$PS1")
        yield
    finally:
        # systemd-nspawn prints
        ## Press ^] three times within 1s to kill container.
        # 0x1d is ^]
        target.console_tx("\x1d\x1d\x1d")
        target.report_info("exited systemd/nspawn chroot for" + message,
                           **report_kwargs)
        target.shell.run("# exited systemd/nspawn chroot for " + message)



def linux_network_ssh_setup(ic, target, proxy_wait_online = True):
    """
    Ensure the target has network and SSH setup and running

    :param tcfl.tc.target_c ic: interconnect where the target is connected

    :param tcfl.tc.target_c target: target on which to operate

    :param bool proxy_wait_online: (optional, default *True*) if there
      are proxies defined, wait for them to be pingable before
      accessing the network.
    """
    tcfl.tl.linux_wait_online(ic, target)
    tcfl.tl.sh_export_proxy(ic, target)
    tcfl.tl.sh_proxy_environment(ic, target)

    # Make sure the SSH server is installed
    distro, distro_version = tcfl.tl.linux_package_add(
        ic, target,
        centos = [ 'openssh-server' ],
        clear = [ 'sudo', 'openssh-server', 'openssh-client' ],
        fedora = [ 'openssh-server' ],
        rhel = [ 'openssh-server' ],
        ubuntu = [ 'openssh-server' ],
        proxy_wait_online = proxy_wait_online
    )

    tcfl.tl.linux_ssh_root_nopwd(target)	# allow remote access
    tcfl.tl.linux_sshd_restart(ic, target)

tap_mapping_result_c = {
    'ok': tcfl.result_c(passed = 1),
    'not ok': tcfl.result_c(failed = 1),
    'skip': tcfl.result_c(skipped = 1),
    'todo': tcfl.result_c(errors = 1),
}

def tap_parse_output(output_itr):
    """
    Parse `TAP
    <https://testanything.org/tap-version-13-specification.html>`_
    into a dictionary

    :param str output: TAP formatted output
    :returns: dictionary keyed by test subject containing a dictionary
       of key/values:
       - lines: list of line numbers in the output where data was found
       - plan_count: test case number according to the TAP plan
       - result: result of the testcase (ok or not ok)
       - directive: if any directive was found, the text for it
       - output: output specific to this testcase
    """
    tap_version = re.compile("^TAP version (?P<tap_version>[0-9]+)$")
    tc_plan = re.compile(r"^(?P<plan_min>[0-9]+)\.\.(?P<plan_max>[0-9]+)$")
    tc_line = re.compile(r"^(?P<result>(ok |not ok ))(?P<plan_count>[0-9]+ )?"
                         r"-\w*(?P<subject>[^#]*)?(#(?P<directive>.*))?$")
    tc_output = re.compile(r"^#(?P<data>.*)$")
    skip_regex = re.compile(r"skip(ped)?:?", re.IGNORECASE)
    todo_regex = re.compile(r"todo:?", re.IGNORECASE)

    # state
    _plan_min = None
    _plan_top = None
    plan_set_at = None
    tcs = {}

    linecnt = 0
    _plan_count = 1
    plan_max = 0
    tc = None
    for line in output_itr:
        linecnt += 1
        m = tc_plan.search(line)
        if m:
            if plan_set_at and _plan_count > plan_max:
                # only complain if we have not completed it, otherwise
                # consider it spurious and ignore
                continue
            if plan_set_at:
                raise tcfl.tc.blocked_e(
                    f"{linecnt}: setting range, but was already set at {plan_set_at}",
                    dict(line_count = linecnt, line = line))
            plan_set_at = linecnt
            plan_min = int(m.groupdict()['plan_min'])
            plan_max = int(m.groupdict()['plan_max'])
            continue
        m = tc_line.search(line)
        if m:
            d = m.groupdict()
            result = d['result']
            count = d['plan_count']
            if not count or count == "":
                count = _plan_count	# if no count, use our internal one
            subject = d['subject']
            if not subject or subject == "":
                subject = str(count)	# if no subject, use count
            subject = subject.strip()
            directive_s = d.get('directive', '')
            if directive_s == None:
                directive_s = ''
                # directive is "TODO [text]", "skip: [text]"
            directive_s = directive_s.strip()
            directive_sl = directive_s.split()
            if directive_sl:
                directive = directive_sl[0]
                if skip_regex.match(directive):
                    result = "skip"
                elif todo_regex.match(directive):
                    result = "todo"
            else:
                directive = ''
            tc_current = subject
            print(f"DEBUG subject is {subject}")
            tcs[subject] = dict(
                lines = [ linecnt ],
                plan_count = count,
                result = result.strip(),
                directive = directive_s,
                output = "",
            )
            tc = tcs[subject]
            # oficially a new testcase in the plan
            _plan_count += 1
            continue
        m = tap_version.search(line)
        if m:
            d = m.groupdict()
            tap_version = int(d['tap_version'])
            if tap_version < 12:
                raise RuntimeError("%d: Can't process versions < 12", linecnt)
            continue
        m = tc_output.search(line)
        if m:
            d = m.groupdict()
            if tc:
                tc['output'] += d['data'] + "\n"
                tc['lines'].append(linecnt)
            else:
                raise tcfl.tc.blocked_e(
                    "Can't parse output; corrupted? didn't find a header",
                    dict(output = output_itr, line = linecnt))
            continue
    return tcs


def rpyc_connect(target, component: str,
                 cert_name: str = "default",
                 iface_name = "power", sync_timeout = 60,
                 retries_max: int = 10, retry_wait: float = 3,
                 console_check_timeout: float = 60):
    """Connect to an RPYC component exposed by the target

    :param tcfl.tc.target_c target: target which exposes the RPYC
      component.

      An RPYC component exposes in the inventory for the (power)
      interface two fields:

        - *interfaces.power.COMPONENT.rpyc_port*: (int) TCP port in
          the server where the RPYC listens

        - *interfaces.power.COMPONENT.ssl_enabled*: (bool) *True* if
          SSL enabled; SSL is considered disabled otherwise.

    :param str component: name of the component that exposes the RPYC
      interface.

    :param str cert_name: (optional, defaults to *default*) name of
      the client certificate to use to connect to the RPYC
      interface it requests SSL.

      See :mod:`ttbl.certs` for more info; the server can issue SSL
      client certificates to use as One-Time-Passwords for the
      duration of the target allocation.

    :param str iface_name: (optional; default *power*) name of the
      interface which exposes the component. In most cases it is the
      power interface, but it could be associated to any.

    :param int sync_timeout: (optional; default *60* seconds) timeout
      for calls to remote functions to return. Increase when running
      longer functions, although this will incur a longter time to
      detect network drops.

      As well, it can be done temporarily as:

      >>> remote = tcfl.tl.rpyc_connect(...)
      >>> ...
      >>> timeout_orig = remote._config['sync_request_timeout']
      >>> try:
      >>>     remote._config['sync_request_timeout'] = 30 * 60 # 30min
      >>>     ... run long remote operation...
      >>> finally:
      >>>     remote._config['sync_request_timeout'] = timeout_orig

    :param int retries_max: (optional; default 10) positive maximum
      number of times to retry connections

    :param float retry_wait: (optional; default 3s) seconds to wait before
      retrying a connection

    :param float console_check_timeout: (optional; default *60*)
      number of seconds to wait on the log console output of the RPYC
      container for a message denoting the connection has been fully
      established [console is usually called *log-COMPONENT*].

      In some circumstances of higher load in the server, when
      rpyc_connect() establishes the connection it takes it a while to
      spin up a new server that can actually serve; this functionality
      waits for the server to print the message indicating the listener
      daemon is up before continuing.

      0 to disable; automatically disabled if there is no console
      support or log console.

    """
    # FIXME: assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(component, str)
    assert isinstance(cert_name, str)
    assert isinstance(console_check_timeout, (int, float) ) \
        and console_check_timeout >= 0, \
        "console_check_timeout: expected positive number of" \
        f" seconds; got {type(console_check_timeout)}"

    try:
        import rpyc	# pylint: disable=import-outside-toplevel
    except ImportError:
        tcfl.tc.tc_global.report_blck(
            "MISSING MODULES: install them with: pip install --user rpyc")
        raise

    rpyc_port = target.kws[f"interfaces.{iface_name}.{component}.rpyc_port"]
    ssl_enabled = target.kws[f"interfaces.{iface_name}.{component}.ssl_enabled"]
    if ssl_enabled:
        # get the certificate files from the server, unless they are already created
        client_key_path = os.path.join(target.tmpdir, "client." + cert_name + ".key")
        client_cert_path = os.path.join(target.tmpdir, "client." + cert_name + ".cert")

        # FIXME: this needs to be smarter -- it needs to re-download
        # if the allocid is different; now it is causing way too many
        # issues when there are files left around (eg: reusing tmp).
        if True or not os.path.isfile(client_key_path) or not os.path.isfile(client_cert_path):
            # if we have the certificates int
            r = target.certs.get(cert_name)
            with open(client_key_path, "w") as keyf:
                keyf.write(r['key'])
            with open(client_cert_path, "w") as certf:
                certf.write(r['cert'])

        target.report_info(
            f"rpyc: {component}: will use SSL cert '{cert_name}' for"
            f" {target.server.parsed_url.hostname}:{rpyc_port}", dlevel = 3)

        ssl_args = dict(
            keyfile = client_key_path,
            certfile =  client_cert_path,
            ssl_version = ssl.PROTOCOL_TLS
        )

    else:
        ssl_args = {}

    target.report_info(
        f"rpyc: connecting to '{component}' on"
        f" {target.server.parsed_url.hostname}:{rpyc_port}", dlevel = 3)

    # When we connect right after powering on a remote container,
    # sometimes it takes the container some time to spin up, so we
    # give by default 10s
    e = None

    log_console_name = "log-" + component
    if console_check_timeout \
       and hasattr(target, "console") \
       and log_console_name in target.console.console_list:
        # reset console expectation to current end-of-console
        target.expect("", console = log_console_name)
    else:
        console_check_timeout = 0

    wait_time = retry_wait
    for cnt in range(1, retries_max + 1):
        try:
            remote = rpyc.utils.classic.ssl_connect(
                target.server.parsed_url.hostname,
                port = rpyc_port, **ssl_args)

            if console_check_timeout > 0:
                # workaround that sometimes the server takes a LONG
                # time to start; basically wait for the remote RPYC
                # process to print
                #
                ## INFO:SLAVE/PORTNUMBER:accepted ('<CLIENTIP>', CLIENTPORT) with fd NNN
                #
                # FIXME: we should extract CLIENTIP, CLIENTPORT and
                # verify it against the socket inside the remote
                # object and possibly check more matches in case we
                # have multiple clients (rare)
                #
                # INFO.*SLAVE because different verions print
                # INFO:SLAVE or INFO SLAVE...#$#@$@3
                #
                target.expect(re.compile("INFO.*SLAVE/.*accepted .* with fd"),
                              timeout = console_check_timeout,
                              console = log_console_name)

            break
        except ( ConnectionResetError ) as _e:
            e = _e
            if cnt == retries_max:
                message = f"rpyc: {component}: failure connecting to" \
                    f" {target.server.parsed_url.hostname}:{rpyc_port}: {e}"
                raise tcfl.blocked_e(message) from e
            target.report_info(f"rpyc: {component}: soft failure connecting,"
                               f" retrying {cnt}/{retries_max}: {e}")
            wait_time *= 1.5
            time.sleep(wait_time)

    target.report_info(
        f"rpyc: connected to '{component}' on"
        f" {target.server.parsed_url.hostname}:{rpyc_port}", dlevel = 2)

    if sync_timeout:
        assert isinstance(sync_timeout, int) and sync_timeout > 0, \
            "sync_timeout: expected positive number of seconds; got {sync_timeout}"
        remote._config['sync_request_timeout'] = sync_timeout
    return remote
