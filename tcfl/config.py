#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Configuration API for *tcf*
---------------------------
"""

import inspect
import logging
import os
import re
import urlparse

import commonl
import report
import tc
import ttb_client

logger = logging.getLogger("tcfl.config")

urls = []

# FIXME: need to figure out a way to tag this as configuration language
def url_add(url, ssl_ignore = False, aka = None, ca_path = None):
    """
    Add a TTBD server

    :param str url: server's URL (``http://SERVER:PORT``); it can be
      *https*; port is most commonly *5000*.
    :param bool ssl_ignore: if True, skips verifying SSL certificates
    :param str aka: Short form for this server, to use in display messages
    """
    u = urlparse.urlparse(url)
    if u.scheme == "" or u.netloc == "":
        raise Exception("%s: malformed URL?" % url)
    o = inspect.stack()[1]
    origin = "%s:%s" % (o[1], o[2])
    logger.info("%s: Added broker URL %s", origin, url)
    urls.append((url, ssl_ignore, aka, ca_path))

def load(config_path = None, config_files = None,
         state_path = "~/.tcf", ignore_ssl = True):
    """Load the TCF Library configuration

    This is needed before you can access from your client program any
    other module.

    :param config_path: list of strings containing UNIX-style
        paths (DIR:DIR) to look for config files (conf_*.py) that will
        be loaded in alphabetical order. An empty path clears the
        current list.
    :param config_files: list of extra config files to load
    :param str state_path: (optional) path where to store state
    :param bool ignore_ssl: (optional) wether to ignore SSL
        verification or not (useful for self-signed certs)

    """
    if not config_path:
        config_path = [ "/etc/tcf:~/.tcf:.tcf" ]
    if not config_files:
        config_files = []
    if config_path != "":
        logger.info("configuration path %s", config_path)
        commonl.config_import(config_path, re.compile("^conf[-_].*.py$"))
    for config_file in config_files:
        commonl.config_import_file(config_file, "__main__")

    if urls == []:
        logger.warning(
            "No broker URLs available; please use --url or "
            "add to ~/.tcf/conf_*.py with:\n"
            "\n"
            "  import commonl.config as commonl.config\n"
            "  \n"
            "  tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)\n"
            "\n")

    for _url in urls:		# create target broker objects
        url = _url[0]
        ssl_ignore = ignore_ssl or _url[1]
        if len(_url) > 2:
            aka = _url[2]
        else:
            aka = None
        ttb_client.rest_init(os.path.expanduser(state_path),
                             url, ssl_ignore, aka)

def tc_driver_add(_cls):
    """Add a testcase driver

    A testcase driver is a subclass of :class:`tcfl.tc.tc_c` which
    overrides the methods used to locate testcases and implements the
    different testcase configure/build/evaluation functions.

    >>> import tcfl.tc
    >>> class my_tc_driver(tcfl.tc.tc_c)
    >>> tcfl.config.tc_driver_add(my_tc_driver)

    :param _cls: subclass of :class:`tcfl.tc.tc_c` that implements the
      driver
    """
    o = inspect.stack()[1]
    origin = "%s:%s" % (o[1], o[2])
    tc.tc_c.driver_add(_cls, origin)

def report_driver_add(obj):
    """Add a reporting driver

    A report driver is used by *tcf run*, the meta test runner, to
    report information about the execution of testcases.

    A driver implements the reporting in whichever way it decides it
    needs to suit the application, uploading information to a server,
    writing it to files, printing it to screen, etc.

    >>> import tcfl.report
    >>> class my_report_driver(tcfl.report.report_c)
    >>> tcfl.config.report_driver_add(my_report_driver)

    :param _cls: subclass :class:`tcfl.report.report_c` of type that
      implements the driver

    """
    o = inspect.stack()[1]
    origin = "%s:%s" % (o[1], o[2])
    report.report_c.driver_add(obj, origin)
