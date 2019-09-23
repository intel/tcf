#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Common utilities for test cases
"""

import collections
import datetime
import os
import re
import time

import tcfl.tc
import target_ext_shell

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

    .. _howto_restart_sshd:

    In a script:

    >>> tcfl.tl.linux_ssh_root_nopwd(target)
    >>> target.shell.run("systemctl restart sshd")

    wait for *sshd* to be fully ready; it is a hack

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

# common linux root prompts
linux_root_prompts = target_ext_shell._shell_prompt_regex

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
          no_proxy=127.0.0.1,192.168.98.1/24,fc00::62:1/112 \
          HTTP_PROXY=$http_proxy \
          HTTPS_PROXY=$https_proxy \
          NO_PROXY=$no_proxy

    being executed in the target

    """
    proxy_cmd = ""
    if 'http_proxy' in ic.kws:
        proxy_cmd += " http_proxy=%(http_proxy)s "\
            "HTTP_PROXY=%(http_proxy)s"
    if 'https_proxy' in ic.kws:
        proxy_cmd += " https_proxy=%(https_proxy)s "\
            "HTTPS_PROXY=%(https_proxy)s"
    if proxy_cmd != "":
        # if we are setting a proxy, make sure it doesn't do the
        # local networks
        proxy_cmd += \
            " no_proxy=127.0.0.1,%(ipv4_addr)s/%(ipv4_prefix_len)s," \
            "%(ipv6_addr)s/%(ipv6_prefix_len)d,localhost" \
            " NO_PROXY=127.0.0.1,%(ipv4_addr)s/%(ipv4_prefix_len)s," \
            "%(ipv6_addr)s/%(ipv6_prefix_len)d,localhost"
        target.shell.run("export " + proxy_cmd % ic.kws)

def linux_wait_online(ic, target, loops = 10, wait_s = 0.5):
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
    assert isinstance(path, basestring)
    assert max_kbytes > 0

    target.report_info(
        "rsync cache: reducing %s to %dMiB" % (path, max_kbytes / 1024.0))

    prompt_original = target.shell.shell_prompt_regex
    with target.on_console_rx_cm(
            re.compile("^(.*Error|Exception):.*^>>> ", re.MULTILINE | re.DOTALL),
            timeout = False, result = 'errr'):
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
fsbsize = os.statvfs('%(path)s').f_bsize
l = []
dirs = []
for r, dl, fl in os.walk('%(path)s', topdown = False):
    for fn in fl + dl:
        fp = os.path.join(r, fn)
        try:
            s = os.stat(fp)
            sd = fsbsize * ((s.st_size + fsbsize - 1) / fsbsize)
            l.append((s.st_mtime, sd, fp, stat.S_ISDIR(s.st_mode)))
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


exit()
""" % dict(path = path, max_bytes = max_kbytes * 1024))
        finally:
            target.shell.shell_prompt_regex = prompt_original

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
    'computer-vision-basic': 800, #1001MB
    'container-virt': 800, #197.31MB
    'containers-basic-dev': 1200, #921MB
    'database-basic-dev': 800, # 938
    'desktop': 480,
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
    'java9-basic': 800, # 347MB
    'machine-learning-basic': 1200, #1280MB
    'machine-learning-tensorflow': 800,
    'machine-learning-web-ui': 1200, # (1310MB)
    'mail-utils-dev ': 1000, #(670MB)
    'maker-cnc': 800, # (352MB)
    'maker-gis': 800, # (401MB)
    'network-basic-dev': 1200, #758MB
    'openstack-common': 800, # (360MB)
    'os-clr-on-clr': 8000,
    'os-core-dev': 800,
    'os-testsuite': 1000,
    'os-testsuite-phoronix': 1000,
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
    if isinstance(bundle_list, basestring):
        bundle_list = [ bundle_list ]
    else:
        assert isinstance(bundle_list, collections.Iterable) \
            and all(isinstance(item, basestring) for item in bundle_list), \
            "bundle_list must be a string (bundle name) or list " \
            "of bundle names, got a %s" % type(bundle_list).__name__

    if debug == None:
        debug = 'SWUPD_DEBUG' in os.environ
    else:
        assert isinstance(debug, bool)

    if url == None:
        url = os.environ.get('SWUPD_URL', None)
    else:
        assert isinstance(url, basestring)

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
        target.shell.run("date -us '%s' && hwclock -wu"
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
        "test -f /etc/ca-certs/trusted/regenerate"
        " && rm -rf /run/lock/clrtrust.lock"
        " && clrtrust -v generate"
        " && rm -f /etc/ca-certs/trusted/regenerate"
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
                add_timeout = swupd_bundle_add_timeouts[bundle]
                target.report_info(
                    "bundle-add: adjusting timeout to %d per configuration "
                    "tcfl.tl.swupd_bundle_add_timeouts" % add_timeout)
            else:
                add_timeout = 240

        count = 0
        top = 10
        for count in range(1, top + 1):
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
                output = True, timeout = add_timeout)
            if not 'FAILED-%(tc_hash)s' % testcase.kws in output:
                # We assume it worked
                break
            if 'Error: Bundle too large by' in output:
                df = target.shell.run("df -h", output = True, trim = True)
                raise tcfl.tc.blocked_e(
                    "swupd reports rootfs out of space to"
                    " install bundle %(bundle)s" % kws,
                    dict(output = output, df = df))
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
