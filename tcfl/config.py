#! /usr/bin/python3
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
import urllib.parse

import commonl
import tcfl.tc
from . import ttb_client
from . import _install

logger = logging.getLogger("tcfl.config")
#: The list of paths where we find configuration information
path = []
#: The list of config files we have imported
loaded_files = []
#: Path where shared files are stored
share_path = None
#: Path where state files are stored
state_path = None
#: List of URLs to servers we are working with
#:
#: each entry is a tuple of:
#:
#: - URL (str): the location of the server
#: - SSL verification (bool): if we are obeying SSL certificate verification
#: - aka (str): short name for the server
#: - ca_path (str): path to certificates
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
    u = urllib.parse.urlparse(url)
    if u.scheme == "" or u.netloc == "":
        raise Exception("%s: malformed URL?" % url)
    o = inspect.stack()[1]
    origin = "%s:%s" % (o[1], o[2])
    logger.info("%s: Added server URL %s", origin, url)
    urls.append((url, ssl_ignore, aka, ca_path))


def load(config_path = None, config_files = None,
         state_dir = None, ignore_ssl = True):
    """
    Load the TCF Library configuration

    :param config_path: list of strings containing UNIX-style paths
        (DIR:DIR), DIR;DIR on Windows, to look for config files
        (conf_*.py) that will be loaded in alphabetical order. An
        empty path clears the current list.

    :param config_files: list of extra config files to load
    :param str state_path: (optional) path where to store state
    :param bool ignore_ssl: (optional) wether to ignore SSL
        verification or not (useful for self-signed certs)

    """
    if config_path == None:
        config_path = [
            ".tcf", os.path.join(os.path.expanduser("~"), ".tcf"),
        ] + _install.sysconfig_paths

    global state_path
    if state_dir:
        state_path = state_dir
    else:
        state_path = os.path.join(os.path.expanduser("~"), ".tcf")

    global share_path
    share_path = os.path.expanduser(_install.share_path)

    if not config_files:
        config_files = []

    global path
    path = [ i for i in reversed(config_path) ]

    global loaded_files
    logger.info("configuration path %s", path)
    commonl.config_import(path, re.compile("^conf[-_].*.py$"),
                          imported_files = loaded_files)
    for config_file in config_files:
        commonl.config_import_file(config_file, "__main__")
        loaded_files.append(config_file)

    if urls == []:
        logger.warning(
            "No server URLs available; please use --url or "
            "add to a conf_*.py in any of %s with:\n"
            "\n"
            "  tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)\n"
            "\n" % ":".join(config_path))

    for _url in urls:		# create target server objects
        url = _url[0]
        ssl_ignore = ignore_ssl or _url[1]
        if len(_url) > 2:
            aka = _url[2]
        else:
            aka = None
        ttb_client.rest_init(os.path.expanduser(state_path),
                             url, ssl_ignore, aka)

    tcfl.msgid_c.cls_init()


def setup(*args,
          report_drivers = None, verbosity = 2, logfile_name = "run.log",
          **kwargs):
    """
    Setup and Load the TCF Library configuration for standalone execution

    This is needed before you can access from your client program any
    other module.

    :param int verbosity: (optional, default 2) verbosity of output to
      the console

    :param str logfile_name: (optional, default *run.log*) where to
      log the detailed output to.

    :param list(tcfl.tc.report_driver_c) report_drivers: (optional)
      list of drivers for reporting execution data.

      By default, drivers that logs to a logfile, to report files and
      to json files are loaded for you.

    Other arguments as :func:`load`.

    """
    # Do a partial initialzation of the testcase management system
    tcfl.tc.tc_c.tmpdir = "tmp"
    tcfl.tc.tc_c.ticket = "TICKET"
    if not report_drivers:
        tcfl.tc.report_driver_c.add(
            tcfl.tc.report_jinja2.driver("."),
            name = "jinja2")
        tcfl.tc.report_driver_c.add(
            tcfl.tc.report_console.driver(
                verbosity,
                logfile_name, verbosity_logf = 100),
            name = "console")
        tcfl.tc.report_driver_c.add(
            tcfl.tc.report_data_json.driver(),
            name = "json")
    else:
        for report_driver in report_drivers:
            tcfl.tc.report_driver_c.add(report_driver)
    load(*args, **kwargs)
    tcfl.msgid_c.tls.msgid_lifo.append(tcfl.msgid_c("standalone"))
