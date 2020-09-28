#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
.. _example_code_python:

Accessing the HTTP API from Python with *requests*
==================================================

Sample code snippet to access a server using Python and the requests
module instead of the :ref:`TCF library<examples_script>` library.

This snippet:
- logs in to a server, acquiring credentials via cookies (which are
  then used for the rest of the operations)
- allocates a machine
- powers the machine off
- powers the machine on
- releases the machine
"""

import logging
import sys
import urllib3

import requests

urllib3.disable_warnings()
logging.basicConfig(level = logging.INFO)

if len(sys.argv) != 5:
    sys.stderr.write("""\
ERROR: wrong number of arguments: SERVERURL TARGETNAME USER PASSWORD
   SERVERURL as https://HOSTNAME:5000 (or other port)
""")
    sys.exit(1)

server_url = sys.argv[1] + "/ttb-v2"
target_name = sys.argv[2]
username = sys.argv[3]
password = sys.argv[4]

print(f"{server_url}: login in as {username}")
r = requests.put(server_url + "/login",
                 verify = False,
                 data = { "username": username, "password": password })
if r.status_code != 200:
    raise RuntimeError(f"login failed: %s" % r.json().get("_message", "n/a"))
# reusing the cookie: pickle it to a file, load it later, exercise for
# the reader
login_cookie = r.cookies

print(f"{server_url}: allocating {username}")
r = requests.put(server_url + "/allocation",
                 cookies = login_cookie, verify = False,
                 json = {
                     "queue": False,
                     "groups": { "mygroup": [ target_name ] },
                 })
if r.status_code != 200:
    raise RuntimeError(
        f"allocation failed: %s" % r.json().get("_message", "n/a"))
j = r.json()
if j['state'] != 'active':
    raise RuntimeError(
        f"allocation failed: state is {target_name}: $(state)s" % j)

try:
    # get power state
    print(f"{server_url}/targets/{target_name}: listing power components")
    r = requests.get(server_url + "/targets/%s/power/list" % target_name,
                     cookies = login_cookie, verify = False)
    if r.status_code != 200:
        raise RuntimeError(
            f"power list failed: %s" % r.json().get("_message", "n/a"))

    # power off
    print(f"{server_url}/targets/{target_name}: powering off")
    r = requests.put(server_url + "/targets/%s/power/off" % target_name,
                     cookies = login_cookie, verify = False)
    if r.status_code != 200:
        raise RuntimeError(
            f"power off failed: %s" % r.json().get("_message", "n/a"))

    # power on
    print(f"{server_url}/targets/{target_name}: powering on")
    r = requests.put(server_url + "/targets/%s/power/on" % target_name,
                     cookies = login_cookie, verify = False)
    if r.status_code != 200:
        raise RuntimeError(
            f"power on failed: %s" % r.json().get("_message", "n/a"))
finally:
    # release the target -- we put it in a try/finally block so we release
    # even if we failed the power list/on/off
    print(f"{server_url}/targets/{target_name}: releasing")
    r = requests.put(server_url + "/targets/%s/release" % target_name,
                     cookies = login_cookie, verify = False)
    if r.status_code != 200:
        raise RuntimeError(
            f"release failed: %s" % r.json().get("_message", "n/a"))
