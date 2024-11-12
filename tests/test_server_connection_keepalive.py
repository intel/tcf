#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
#! SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# WARNING! yes, it'd be nice to have a test_base and then two tests
# that just set the string to the desired server type, but it fails with:
#
##   19:   File "/usr/lib/python3.12/site-packages/werkzeug/serving.py", line 918, in make_server
##  20:     raise ValueError("Cannot have a multi-thread and multi-process server.")
##  21: ValueError: Cannot have a multi-thread and multi-process server.
#
# Why? not sure but it seems to me that the mechanism we have to
# create test servers gets very confused once it is a derived class it
# is created from. Not a biggie. Some day we'll fix it.

import tcfl.tc

class test_tornado(tcfl.tc.tc_c):
    """
    Test when serving with the Tornado or Gunicorn HTTP server
    that it allows connections to be kept alive for performance
    reasons

    When this happens, when we query a basic URL, such as /ttb in the
    server, it shall report a header::

      Connection: keep-alive

    Anything else means the connection is closed and means something
    is wrong in either the framework configuration (Flask) or the HTTP
    server (Tornado, Gunicorn

    """

    def eval(self):
        import requests

        import commonl.testing

        ttbd = commonl.testing.test_ttbd(
            config_text = f"""
ttbl.config.server = "tornado"
""",
            errors_ignore = [
                'DEBUG'
            ])
        self.report_info(f"server URL {ttbd.url}", dlevel = 1)
        r = requests.get(f"{ttbd.url}/ttbd")
        connection_header = r.headers.get('Connection', None)
        self.report_info(f"Connection header: {connection_header}", dlevel = 1)
        if connection_header != "keep-alive":
            raise tcfl.fail_e("Connection header is not keep-alive as"
                              f" expected, but '{connection_header}'")
        self.report_pass("Connection header is keep-alive as expected")



class test_gunicorn(tcfl.tc.tc_c):
    """
    Test when serving with the Tornado HTTP server that it allows
    connections to be kept alive for performance reasons

    See :class:`test_tornado` for details.
    """

    def eval(self):
        import requests

        import commonl.testing

        ttbd = commonl.testing.test_ttbd(
            config_text = """
ttbl.config.server = "gunicorn"
""",
            errors_ignore = [
                'DEBUG',
            ])
        self.report_info(f"server URL {ttbd.url}", dlevel = 1)
        r = requests.get(f"{ttbd.url}/ttbd")
        connection_header = r.headers.get('Connection', None)
        self.report_info(f"Connection header: {connection_header}", dlevel = 1)
        if connection_header != "keep-alive":
            raise tcfl.fail_e("Connection header is not keep-alive as"
                              f" expected, but '{connection_header}'")
        self.report_pass("Connection header is keep-alive as expected")
