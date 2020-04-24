#! /usr/bin/python
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
from . import ttb_client

logger = logging.getLogger("tcfl.config")
#: The list of paths where we find configuration information
path = []
#: Path where shared files are stored
share_path = None
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
        global path
        path = commonl.path_expand(config_path)
        logger.info("configuration path %s", path)
        commonl.config_import(path, re.compile("^conf[-_].*.py$"))
    for config_file in config_files:
        commonl.config_import_file(config_file, "__main__")

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
