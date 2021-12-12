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

import collections
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
share_path = os.path.expanduser(_install.share_path)
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

# FIXME: eventually this and urls  will be superseeded with a proper
# list/dict of server objects; temporary workaround that allows us to
# have origins for the time being. Hack. Horrible hack
urls_data = collections.defaultdict(dict)

# FIXME: need to figure out a way to tag this as configuration language
def url_add(url, ssl_ignore = False, aka = None, ca_path = None,
            origin = None):
    """
    Add a TTBD server

    :param str url: server's URL (``http://SERVER:PORT``); it can be
      *https*; port is most commonly *5000*.
    :param bool ssl_ignore: if True, skips verifying SSL certificates
    :param str aka: Short form for this server, to use in display messages
    """
    # FIXME: move this to the object construction
    u = urllib.parse.urlparse(url)
    if u.scheme == "" or u.netloc == "":
        raise Exception("%s: malformed URL?" % url)
    if not origin:
        origin = "configured " + commonl.origin_get(2)
    logger.info("%s: Added server URL %s", origin, url)
    urls.append((url, ssl_ignore, aka, ca_path))	# COMPAT
    urls_data[url]['origin'] = origin


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

    if not config_files:
        config_files = []

    global path
    _path = []
    for i in config_path:
        if i == "":
            _path = []
        else:
            _path.append(i)
    path = [ i for i in reversed(_path) ]

    global loaded_files
    logger.info("configuration path %s", path)
    commonl.config_import(path, re.compile("^conf[-_].*.py$"),
                          imported_files = loaded_files,
                          raise_on_fail = False)
    for config_file in config_files:
        commonl.config_import_file(config_file, "__main__")
        loaded_files.append(config_file)

    # this takes stuff in added by config files to tcfl.config.urls to
    # seed, stuff we saved on disk from previous runs or defaults to
    # hostname "ttbd" that is resovled
    tcfl.server_c.discover()

    for _, server in tcfl.server_c.servers.items():		# create target server objects
        # COMPAT: old style ttb_client.rest_target_broker -> being
        # moved to tcfl.server_c
        rtb = ttb_client.rest_target_broker(
            os.path.expanduser(state_path), server.url,
            ignore_ssl = not server.ssl_verify,
            aka = server.aka, origin = server.origin)
        ttb_client.rest_target_brokers[server.parsed_url.geturl()] = rtb

    if not tcfl.ttb_client.rest_target_brokers:
        logger.warning(
            "No servers available; please use --url or "
            "add to a file called conf_ANYTHING.py in any of %s with:\n"
            "\n"
            "  tcfl.config.url_add('https://URL:PORT', ssl_ignore = True)\n"
            "\n" % ":".join(config_path))

    tcfl.msgid_c.cls_init()


def setup(*args,
          report_drivers = None, verbosity = 2, logfile_name = "run.log",
          name = "toplevel",
          runid = None, hashid = "standalone", skip_reports = False,
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
    assert runid == None or isinstance(runid, str)
    assert hashid == None or isinstance(hashid, str)
    assert isinstance(skip_reports, bool)

    tcfl.tc.tc_c.runid = runid
    if runid == None:
        tcfl.tc.tc_c.runid_visible = ""
    else:
        tcfl.tc.tc_c.runid_visible = runid
    # Do a partial initialzation of the testcase management system so
    # the only testcase object declared, tcfl.tc.tc_global reflects
    # all the info
    tcfl.tc.tc_c.tmpdir = "tmp"
    # reinitialize this one up, so that we have minimal hash printing
    tcfl.tc.tc_global = tcfl.tc.tc_c(name, "", commonl.origin_get(1),
                                     hashid = hashid)
    tcfl.tc.tc_global.skip_reports = skip_reports

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
    tcfl.msgid_c.tls.msgid_lifo.append(tcfl.msgid_c(""))
