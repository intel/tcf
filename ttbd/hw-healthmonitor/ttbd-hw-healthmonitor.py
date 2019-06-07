#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Test Target Broker Daemon HW Health Check Monitor

Monitor the kernel's journal output looking for telltale signs of some
piece of hardware gone unresponsive and take action to remediate it.

This has to be configured via config files in
/etc/ttbd-hw-healthmonitor/conf_*.py
"""
import argparse
import bisect
import collections
import logging
import os
import pprint
import re
import select
import subprocess
import time

import systemd.journal
import systemd.daemon
import commonl


usb_root_regex = re.compile("^(?P<bus>[0-9]+)-(?P<port>[0-9]+)$")

def _usb_special_case(path):
    if not path.startswith("/sys/bus/usb/drivers"):
        return path
    filename = os.path.basename(path)
    # we only can workaround root-ports, which look like
    # /sys/bus/usb/drivers/usb/3-2
    match = usb_root_regex.match(filename)
    if not match:
        return path

    # Sometimes /sys/bus/usb/drivers/usb/3-2 (for example) doesn't
    # exist because it has been blown to pieces somehow, but there is
    # a:
    #
    # $ find /sys/ -iname usb3-port2
    # /sys/devices/pci0000:80/0000:80:01.0/0000:81:00.0/0000:82:00.2/usb3/3-0:1.0/usb3-port2
    #
    # so if it doesn't exist, we are going to use that one
    if os.path.exists(path):
        return path

    #  $ readlink -e /sys/bus/usb/drivers/usb/3-2
    # /sys/devices/pci0000:80/0000:80:01.0/0000:81:00.0/0000:82:00.2/usb3/3-2
    #
    # and when it doesn't exist
    #
    # $ find /sys/ -iname usb3-port2
    # /sys/devices/pci0000:80/0000:80:01.0/0000:81:00.0/0000:82:00.2/usb3/3-0:1.0/usb3-port2

    def _find(filename):
        for parent, dirs, _files in os.walk("/sys"):
            if filename in dirs:	# usb3-port2 is a dir
                # return just
                # /sys/devices/pci0000:80/0000:80:01.0/0000:81:00.0/0000:82:00.2/usb3/3-0:1.0,
                # so it is at the same level as
                # /sys/devices/pci0000:80/0000:80:01.0/0000:81:00.0/0000:82:00.2/usb3/3-2.
                logging.info("%s: doesn't exist, but %s does, dead controller",
                             path, parent)
                return parent
        return None
    gd = match.groupdict()
    return _find("usb" + gd['bus'] + "-port" + gd['port'])


def _driver_rebind(bus_name, driver_name, device_name, strip_generations):
    global _ttbd_hw_health_monitor_driver_rebind_path

    # let's start by componsing the /sys path from the arguments
    path = os.path.join("/", "sys", "bus", bus_name, "drivers", driver_name,
                        device_name)
    _path = _usb_special_case(path)
    if _path == None:
        logging.error("%s: doesn't exist, can't rebind", path)
        return
    path = _path

    if strip_generations:
        # Strip children from the device path up because we want to
        # rebind a parent device, not the children
        #
        # For example, for /sys/bus/usb/devices/3-4.1:1.0
        # parent is 3-4.1
        # grandpa is 3-4
        # great-grandpa is usb3
        # great-great-grandpa is 0000:05.00.2
        #
        # we know because
        #
        #   $ readlink -e /sys/bus/usb/devices/3-4.1:1.0
        #   /sys/devices/pci0000:00/0000:00:03.0/0000:04:00.0/0000:05:00.2/usb3/3-4/3-4.1/3-4.1:1.0
        assert strip_generations > 0

        # Now see where that points to, that's the
        #  $ readlink -e /sys/bus/usb/devices/3-4.1:1.0
        #   /sys/devices/pci0000:00/0000:00:03.0/0000:04:00.0/0000:05:00.2/usb3/3-4/3-4.1/3-4.1:1.0
        real_path = os.path.realpath(path).split(os.path.sep)
        # So now chop strip-generations on the right, that's our new device
        #   /sys/devices/pci0000:00/0000:00:03.0/0000:04:00.0/0000:05:00.2
        stripped_path = os.path.join(real_path[:-strip_generations])
        # got device name
        new_device_name = stripped_path[-1]
        # Now let's get what bus and driver this device is attached to
        # by following /DEVICEPATH/driver
        #
        #   /sys/devices/pci0000:00/0000:00:03.0/0000:04:00.0/0000:05:00.2/driver
        driver_path = os.path.realpath(os.path.join(*(
            [ "/" ] + stripped_path +[ "driver" ])))
        # this will give /sys/bus/BUSNAME/drivers/DRIVERNAME, so let's split
        # it and extract the data
        driver_path_components = driver_path.split("/")
        new_bus_name = driver_path_components[3]
        new_driver_name = driver_path_components[5]

        logging.info("%s/%s/%s: stripped %d generations yields %s/%s/%s",
                     bus_name, driver_name, device_name,
                     strip_generations,
                     new_bus_name, new_driver_name, new_device_name)
        device_name = new_device_name
        driver_name = new_driver_name
        bus_name = new_bus_name

    cmdline = [
        "sudo", "-n",
        _ttbd_hw_health_monitor_driver_rebind_path,
        bus_name, driver_name, device_name
    ]
    try:
        logging.info("%s/%s/%s: rebinding with command '%s'",
                     bus_name, driver_name, device_name,
                     " ".join(cmdline))
        output = subprocess.check_output(cmdline, stderr = subprocess.STDOUT)
    except subprocess.CalledProcessError as cpe:
        logging.error("%s/%s/%s: rebinding with command '%s' failed: %s",
                      bus_name, driver_name, device_name,
                      " ".join(cpe.cmd), cpe.output)
        return	# well, nothing we can really do...
    logging.warning("%s/%s/%s: rebound with command '%s': %s",
                    bus_name, driver_name, device_name,
                    " ".join(cmdline), output)


def action_driver_rebind(bus_name, driver_name, device_name,
                         condition, entry, strip_generations = 0):
    """
    Rebind a device to it's driver to reset it

    A device that is in a hosed state will be re-bound to its driver
    to try to reset it and bring it back to life.

    :param str bus_name: name of bus in */sys/bus*
    :param str driver_name: name of driver in
      */sys/bus/BUS_NAME/drivers*
    :param str device_name: name of the device in
      */sys/bus/BUS_NAME/drivers/DRIVER_NAME*

    :param str condition: condition in the configuration given to
      :func:`config_watch_add` that caused this call
    :param dict entry: Systemd journal entry that caused this call
    """
    ts = entry.get('__REALTIME_TIMESTAMP', None)
    logging.error("%s: ACTION: reloading driver due to '%s' @ %s",
                  device_name, condition, ts)
    _driver_rebind(bus_name, driver_name, device_name, strip_generations)


_thresholds = collections.defaultdict(list)

def action_driver_rebind_threshold(bus_name, driver_name, device_name,
                                   condition, entry,
                                   max_hits, period, strip_generations = 0):
    """
    Rebind a device to its driver to reset it if a condition happens often

    When the condition is reported more than *max_hits* time in
    *period* seconds, then the device will be reset via driver
    rebinding.

    See :func:`action_driver_rebind` for information on the common
    paramenters

    :param int period: (in second) amount of time to monitor
    :param int max_hits: maximum number of occurrences of the
      condition that can heppen in a period after which we'd rebind
      the device.
    """
    global _thresholds
    logging.debug("%s/%s/%s rebind_threshold: considering entry %s",
                  bus_name, driver_name, device_name,
                  entry)
    ts = entry.get('__REALTIME_TIMESTAMP', None)
    threshold_name = device_name + "/" + condition
    threshold = _thresholds[threshold_name]
    bisect.insort(threshold, ts)
    ts0 = threshold[0]
    tse = threshold[-1]
    while (tse - ts0).total_seconds() > period:
        # the current list of thresholds we have in the list is longer
        # than the period, so remove the older ones until we are
        # within the period
        threshold.pop(0)
        ts0 = threshold[0]
    logging.warning(
        "%s/%s/%s: current queue has %d (max %d) hits "
        "in %.1f minutes (max %.1f) for '%s'",
        bus_name, driver_name, device_name, len(threshold), max_hits,
        (tse - ts0).total_seconds() / 60, period / 60, condition)
    if len(threshold) > max_hits:
        logging.error("%s/%s/%s: ACTION: reload driver due to: '%s' @ %s "
                      "causing %d (max %d) hits in %.1f minutes (max %.1f)",
                      bus_name, driver_name, device_name,
                      condition, ts,
                      len(threshold), max_hits,
                      (tse - ts0).total_seconds() / 60, period / 60)
        _driver_rebind(bus_name, driver_name, device_name, strip_generations)
        # we start checking from scratch
        _thresholds[threshold_name] = []


_kernel_device_regex = re.compile(r"^\+usb:(?P<busno>[0-9]+)-(?P<devno>[0-9]+)(\.[0-9]+)*$")

def action_driver_rebind_threshold_kernel_device(
        bus_name, driver_name, device_name,
        condition, entry,
        max_hits, period, strip_generations = 0):
    """
    This is the same as action_driver_rebind_threshold(), but adapted
    to the case when the actual /sys/bus/usb/devices/M-N dissapears
    due to a root port failure.

    In this case we get a kernel device name +usb:BUSNUMBER-DEVICENO
    (eg: +usb:3-2) which we have to translate to controller
    /sys/bus/usb/devices/usb3.

    Now we can't just replace with 3-2 becasue in some cases, that
    sysfs node has dissapeared.

    Note the slight change in configuration language:

    >>> config_watch_add("usb", "usb", re.compile("[0-9]+-[0-9]+$"), {
    >>>     # Case happened where /sys/bus/usb/devices/3-2 dissapeared but:
    >>>
    >>>     # May 03 20:44:51 HOSTNAME kernel: usb 3-2: device descriptor read/64, error -110
    >>>     # Apr 27 22:44:02 ... kernel: usb 3-2: clear tt 4 (85c0) error -71
    >>>     # Just reload the thing if we get more than five in a minute
    >>>     'device descriptor read/64, error -110': (
    >>>         # 2 is the number of generations we want to strip from the
    >>>         # device path; because 3-2's parent is usb3, whose
    >>>         # parent is the actual PCI device we need to reset
    >>>         action_driver_rebind_threshold_kernel-device, 5, 60, 2
    >>>     )},
    >>>     kernel_device = re.compile("\+usb:[0-9]+-[0-9]+$"))

    Note the trailing *kernel_device* argument, a regex used to latch
    on a kernel device name dynamically.

    """
    match = _kernel_device_regex.match(device_name)
    if not match:
        raise AssertionError("device name %s does not match +usb:M-N[.O]*"
                             % device_name)
    busno = match.groupdict()['busno']
    # so now we have /sys/bus/usb/devices/usbBUSNO
    realpath = os.path.realpath("/sys/bus/usb/devices/usb" + busno)
    if not os.path.exists(realpath):
        logging.error("%s: doesn't exist -- can't do anything", realpath)
        return
    # which is a symlink to /sys/devices/pci0000:00/0000:00:14.0/usb3
    parent_dev = os.path.dirname(realpath)
    # which is a symlink to /sys/devices/pci0000:00/0000:00:14.0 and
    # it's driver is
    driver_path = os.path.realpath(parent_dev + "/driver")
    # /sys/bus/pci/drivers/xhci_hcd
    # ok, so extract now to [ '', 'sys, 'bus', 'usb', 'drivers', 'xhci_hcd' # ... ]
    _driver_path_parts = driver_path.split('/')
    # bus_name = pci, driver_name = xhci_hcd, device_name #
    # 0000:00:14.0
    _bus_name = _driver_path_parts[3]
    _driver_name = _driver_path_parts[5]
    _device_name = os.path.basename(parent_dev)

    logging.warning("%s/%s/%s mapped to %s/%s/%s",
                    bus_name, driver_name, device_name,
                    _bus_name, _driver_name, _device_name)
    # and let the other function do it for us
    action_driver_rebind_threshold(_bus_name, _driver_name, _device_name,
                                   condition, entry, max_hits, period)


_watch_rules = []

def config_watch_add(bus_name, driver_name, device_name, actions):
    r"""

    :param str bus_name: name of bus in */sys/bus* to watch
    :param str driver_name: name of driver in
      */sys/bus/BUS_NAME/drivers* to watch
    :param str device_name: device under
      /sys/bus/BUS_NAME/drivers/DRIVER_NAME to watch; if *None*, watch
      all of them
    :param dict actions: dictionary describing actions to do; key is a
      substring of a message, value is a function to call or a tuple
      that starts with a function to call and the rest are arguments
      to add

      The action function has to follow this prototype:

      >>> def action_function(bus_name, driver_name, device_name,
                              condition, entry, *args, **kwargs:

      thus, when called, bus_name, driver_name and device_name are all
      the names of the entity that is causing it; condition is the
      condition string that was matched (the key) and *entry* is the
      journal entry which matched. *\*args* and *\*\*kwargs* are the
      extra arguments given in the *actions* value tuple.

    """

    assert isinstance(bus_name, str)
    assert isinstance(driver_name, str)
    if device_name:
        if isinstance(device_name, str):
            _device_name = "/" + device_name
        elif isinstance(device_name, re._pattern_type):
            _device_name = "/" + device_name.pattern
        else:
            raise AssertionError(
                "'device_name' must be string or regex, found %s",
                type(device_name).__name__)
    else:
        _device_name = ""
    assert isinstance(actions, dict)
    global _watch_rules

    _actions = {}
    origin = commonl.origin_get(2)
    # verify arguments and transform all the actions to a unique
    # form (all have to be a list)
    for condition, action in actions.items():
        assert isinstance(condition, str), \
            "Key passed as condition is not a string"
        try:
            action_fn = action[0]
            _actions[condition] = action
        except TypeError:
            action_fn = action
            _actions[condition] = [ action_fn ]
        assert callable(action_fn), \
            "Argument passed as action function to condition '%s' " \
            "is not callable" % condition

    driver_path = os.path.join("/sys/bus", bus_name, "drivers", driver_name)
    if not os.path.isdir(driver_path):
        logging.warning(
            "%s/%s%s @%s: driver path does not exist, will not monitor",
            bus_name, driver_name, _device_name, origin)
        return
    _watch_rules.append((
        bus_name, driver_name, device_name, _actions, origin
    ))
    logging.info("%s/%s%s @%s: will monitor",
                 bus_name, driver_name, _device_name, origin)



# Given a journal entry, check it against the list of stuff we have to
# watch for. note an entry comes as:
#
# {'MESSAGE': u'usb 2-1.2.4: reset full-speed USB device number 17 using ehci-pci',
#  'PRIORITY': 6,
#  'SYSLOG_FACILITY': 0,
#  'SYSLOG_IDENTIFIER': u'kernel',
#  '_BOOT_ID': UUID('dc527a86-fa21-4085-bac2-ed4eccf83d0b'),
#  '_HOSTNAME': u'some.hsot.domain',
#  '_KERNEL_DEVICE': u'c189:144',
#  '_KERNEL_SUBSYSTEM': u'usb',
#  '_MACHINE_ID': UUID('2c766c91-79da-41ab-bb1a-2c903adf2211'),
#  '_SOURCE_MONOTONIC_TIMESTAMP': datetime.timedelta(2, 43626, 293600),
#  '_TRANSPORT': u'kernel',
#  '_UDEV_DEVNODE': u'/dev/bus/usb/002/000',
#  '_UDEV_SYSNAME': u'2-1.2.4',
#  '__CURSOR': 's=9228bb40b9d140a585632aaeaf6c60e5;i=1987771;b=dc527a86fa214085bac2ed4eccf83d0b;m=3263f58acd;t=56c7f257761cc;x=d1b8e5236bc5e591',
#  '__MONOTONIC_TIMESTAMP': (datetime.timedelta(2, 43625, 401037),
#                            UUID('dc527a86-fa21-4085-bac2-ed4eccf83d0b')),
#  '__REALTIME_TIMESTAMP': datetime.datetime(2018, 5, 19, 0, 0, 28, 780492)}
#
def _entry_matched(entry, bus_name, driver_name, devname, actions, origin):
    msg = entry['MESSAGE']
    if '__REALTIME_TIMESTAMP' in entry:
        ts = "  " + str(entry['__REALTIME_TIMESTAMP'])
    else:
        ts = ""
    # Device messages usually start with 'DRIVERNAME DEVICE: msg', so
    # if we have a driver name, we try to match against that
    _driver_name = msg.split(None, 1)[0]
    if driver_name:
        if isinstance(driver_name, str) \
           and driver_name == _driver_name:
            logging.debug("%s/%s: match on driver name @%s",
                          driver_name, devname, origin)
        elif isinstance(driver_name, re._pattern_type) \
             and driver_name.match(_driver_name):
            logging.debug("%s/%s: match on driver name @%s",
                          driver_name, devname, origin)
        else:
            # No driver match
            logging.debug("%s: mismatch on driver name (%s vs %s requested) "
                          "@%s", devname, _driver_name, driver_name, origin)
            return
    else:
        driver_name = _driver_name

    found_actions = False
    for condition, action in actions.items():
        if condition in msg:
            action_fn = action[0]
            _args = action[1:]
            try:
                if logging.getLogger().getEffectiveLevel() < logging.DEBUG:
                    entry_info = ": %s" % pprint.pformat(entry)
                else:
                    entry_info = ""

                found_actions = True
                if args.dry_run:
                    logging.error(
                        "[dry run]%s ACTION %s (%s, %s, %s, %s) @%s%s",
                        ts, action_fn, bus_name, devname, condition, _args,
                        origin, entry_info)
                else:
                    logging.info("%s/%s/%s:%s matched entry%s",
                                 bus_name, driver_name, devname, ts,
                                 entry_info)
                    action_fn(bus_name, driver_name, devname,
                              condition, entry, *_args)
            except Exception as e:	# pylint: disable = broad-except
                logging.exception(
                    "%s/%s/%s:%s action function raised uncaught "
                    "exception: %s",
                    bus_name, driver_name, devname, ts, e)

    if not found_actions:
        logging.debug("%s/%s/%s: mismatch on actions @%s",
                      bus_name, driver_name, devname, origin)

# Given a journal entry, check it against the list of stuff we have to
# watch for. note an entry comes as:
#
# {'MESSAGE': u'usb 2-1.2.4: reset full-speed USB device number 17 using ehci-pci',
#  'PRIORITY': 6,
#  'SYSLOG_FACILITY': 0,
#  'SYSLOG_IDENTIFIER': u'kernel',
#  '_BOOT_ID': UUID('dc527a86-fa21-4085-bac2-ed4eccf83d0b'),
#  '_HOSTNAME': u'some.hsot.domain',
#  '_KERNEL_DEVICE': u'c189:144',
#  '_KERNEL_SUBSYSTEM': u'usb',
#  '_MACHINE_ID': UUID('2c766c91-79da-41ab-bb1a-2c903adf2211'),
#  '_SOURCE_MONOTONIC_TIMESTAMP': datetime.timedelta(2, 43626, 293600),
#  '_TRANSPORT': u'kernel',
#  '_UDEV_DEVNODE': u'/dev/bus/usb/002/000',
#  '_UDEV_SYSNAME': u'2-1.2.4',
#  '__CURSOR': 's=9228bb40b9d140a585632aaeaf6c60e5;i=1987771;b=dc527a86fa214085bac2ed4eccf83d0b;m=3263f58acd;t=56c7f257761cc;x=d1b8e5236bc5e591',
#  '__MONOTONIC_TIMESTAMP': (datetime.timedelta(2, 43625, 401037),
#                            UUID('dc527a86-fa21-4085-bac2-ed4eccf83d0b')),
#  '__REALTIME_TIMESTAMP': datetime.datetime(2018, 5, 19, 0, 0, 28, 780492)}
#
def _check_entry(entry):
    msg = entry['MESSAGE']
    _device_name = entry.get('_UDEV_SYSNAME', None)
    _kernel_name = entry.get('_KERNEL_DEVICE', None)
    bus_name = None
    driver_name = None
    device_name = None
    actions = None
    origin = None
    while not _device_name and not _kernel_name:
        # If the entry has no device message, then let's try to
        # extract it from the message, things like:
        #
        # usb 3-2-port1: cannot reset (err = -110)',
        regex_usb = re.compile("usb (?P<devname>[0-9]+-[0-9]+)-.*:")
        m = regex_usb.match(msg)
        if m:
            _device_name = m.groupdict()['devname']
            if _device_name:
                logging.warning("guessed USB device %s from message (had "
                                "no entry for it)", _device_name)
                break
        logging.debug("ignored deviceless entry: %s",
                      pprint.pformat(entry))
        return
    for bus_name, driver_name, device_name, actions, origin \
        in _watch_rules:
        if device_name and _device_name:
            if isinstance(device_name, str) \
               and device_name == _device_name:
                logging.debug("%s: match on device name @%s",
                              _device_name, origin)
                devname = _device_name
                _entry_matched(entry, bus_name, driver_name,
                               devname, actions, origin)
                continue
            elif isinstance(device_name, re._pattern_type) \
                 and device_name.match(_device_name):
                logging.debug("%s: match on device name @%s",
                              _device_name, origin)
                devname = _device_name
                _entry_matched(entry, bus_name, driver_name,
                               devname, actions, origin)
                continue
        if device_name and _kernel_name:
            # lookup by kernel device name (for example, for USB
            # they look like +usb:3-2
            if isinstance(device_name, str) \
               and device_name == _kernel_name:
                logging.debug("%s: match on kernel name @%s",
                              _kernel_name, origin)
                devname = _kernel_name
                _entry_matched(entry, bus_name, driver_name,
                               devname, actions, origin)
                continue
            elif isinstance(device_name, re._pattern_type) \
                 and device_name.match(_kernel_name):
                logging.debug("%s: match on kernel name @%s",
                              _kernel_name, origin)
                devname = _kernel_name
                _entry_matched(entry, bus_name, driver_name,
                               devname, actions, origin)
                continue


# Support for -v option to increase verbosity
def _logging_verbosity_inc(level):
    if level == 0:
        return
    if level > logging.DEBUG:
        delta = 10
    else:
        delta = 1
    return level - delta

class _action_increase_level(argparse.Action):
    def __init__(self, option_strings, dest, default = None, required = False,
                 nargs = None, **kwargs):
        super(_action_increase_level, self).__init__(
            option_strings, dest, nargs = 0, required = required,
            **kwargs)

    #
    # Python levels are 50, 40, 30, 20, 10 ... (debug) 9 8 7 6 5 ... :)
    def __call__(self, parser, namespace, values, option_string = None):
        if namespace.level == None:
            namespace.level = logging.ERROR
        namespace.level = _logging_verbosity_inc(namespace.level)

logging.addLevelName(50, "C")
logging.addLevelName(40, "E")
logging.addLevelName(30, "W")
logging.addLevelName(20, "I")
logging.addLevelName(10, "D")

# Initialize command line argument parser
arg_parser = argparse.ArgumentParser(
    description = __doc__,
    formatter_class = argparse.RawDescriptionHelpFormatter)

arg_parser.set_defaults(level = logging.ERROR)
arg_parser.add_argument("-v", "--verbose",
                        dest = "level",
                        action = _action_increase_level, nargs = 0,
                        help = "Increase verbosity")
arg_parser.add_argument("--config-path",
                        action = "store", dest = "config_path",
                        default = "/etc/ttbd-hw-healthmonitor",
                        help = "Path from where to load conf_*.py "
                        "configuration files (in alphabetic order)")
arg_parser.add_argument("-b", "--bootid",
                        action = 'store', default = None,
                        help = "select bootid (from journalctl --list-boots)")
arg_parser.add_argument("--seek-realtime",
                        action = 'store', default = False,
                        help = "check from the given time")
arg_parser.add_argument("--seek-head",
                        action = 'store_true', default = False,
                        help = "check from the begining of the boot")
arg_parser.add_argument("-n", "--dry-run",
                        action = 'store_true', default = False,
                        help = "only show what would it do")
args = arg_parser.parse_args()
logging.basicConfig(
    level = args.level,
    format = "%(levelname)s: %(message)s")

#
# Read configuration and decide what to watch
#

_ttbd_hw_health_monitor_driver_rebind_path = \
    commonl.ttbd_locate_helper("ttbd-hw-healthmonitor-driver-rebind.py",
                               log = logging)
logging.debug("Found helper %s", _ttbd_hw_health_monitor_driver_rebind_path)

args.config_path = os.path.expanduser(args.config_path)
if args.config_path != [ "" ]:
    commonl.config_import([ args.config_path ], re.compile("^conf[-_].*.py$"))

journal = systemd.journal.Reader()
journal.log_level(systemd.journal.LOG_INFO)
logging.debug("opened journal")

systemd.daemon.notify("READY=1")

journal.this_boot(args.bootid)
journal.this_machine()
logging.debug("journal: filtering for kernel messages")
journal.add_match(_TRANSPORT = "kernel")
# We don't filter per-subsystem, because some of them messages (like
# USB's cannot reset) are not bound to it

poller = select.poll()
poller.register(journal, journal.get_events())

# Enter directly to iterate to consume all the records since we booted
if args.seek_head:
    journal.seek_head()
elif args.seek_realtime:
    journal.seek_realtime(time.mktime(time.strptime(
        args.seek_realtime, "%Y-%m-%d %H:%M:%S")))
else:
    journal.seek_tail()

_bark_ts0 = time.time()
def _bark_periodically(period, msg):
    global _bark_ts0
    ts = time.time()
    if ts - _bark_ts0 > period:	# every five seconds, bark
        _bark_ts0 = ts
        systemd.daemon.notify("WATCHDOG=1")
        if msg:
            logging.debug("currently checking: %s", msg)
        else:
            logging.debug("currently checking")

first_run = True
while True:
    if not first_run:
        poller.poll(5000)
        if journal.process() != systemd.journal.APPEND:
            continue
    first_run = False
    logging.debug("polled")
    _bark_periodically(5, "main loop")
    for _entry in journal:
        logging.log(8, "entry %s", pprint.pformat(_entry))
        _check_entry(_entry)
        if '__REALTIME_TIMESTAMP' in _entry:
            _bark_periodically(5, _entry.get('__REALTIME_TIMESTAMP'))
        else:
            _bark_periodically(5, _entry)
