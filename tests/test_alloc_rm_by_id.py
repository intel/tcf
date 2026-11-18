# SPDX-License-Identifier: Apache-2.0

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest import TestCase, mock

import tcfl.allocation
import tcfl.servers
import tcfl.ui_cli_alloc


class TestAllocRmById(TestCase):

    def setUp(self):
        self.alpha = mock.Mock(aka="alpha", url="http://alpha")
        self.beta = mock.Mock(aka="beta", url="http://beta")
        servers = {server.url: server for server in (self.alpha, self.beta)}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.dict(tcfl.server_c.servers, servers, clear=True))
        stack.enter_context(mock.patch.object(tcfl.allocation, "subsystem_setup"))
        stack.enter_context(mock.patch.object(tcfl.servers, "subsystem_setup"))
        stack.enter_context(mock.patch("concurrent.futures.ProcessPoolExecutor",
                                       ThreadPoolExecutor))

    def run_command(self, *ids):
        args = argparse.Namespace(allocid=ids, verbosity=0, quietosity=0,
                                  parallelization_factor=1, traces=False)
        return tcfl.ui_cli_alloc._cmdline_alloc_rm(args)

    def test_qualified_id_uses_named_server(self):
        self.assertEqual(self.run_command("beta/shared"), 0)
        self.alpha.send_request.assert_not_called()
        self.beta.send_request.assert_called_once_with("DELETE", "allocation/shared")

    def test_unknown_server_does_not_send_requests(self):
        self.assertNotEqual(self.run_command("other/shared"), 0)
        self.alpha.send_request.assert_not_called()
        self.beta.send_request.assert_not_called()

    def test_unqualified_id_found_on_second_server(self):
        self.alpha.send_request.side_effect = RuntimeError("invalid allocation")
        self.assertEqual(self.run_command("shared"), 0)
        for server in (self.alpha, self.beta):
            server.send_request.assert_called_once_with("DELETE", "allocation/shared")

    def test_later_success_preserves_failure(self):
        self.alpha.send_request.side_effect = RuntimeError("invalid allocation")
        self.assertNotEqual(self.run_command("alpha/missing", "beta/shared"), 0)
        self.beta.send_request.assert_called_once_with("DELETE", "allocation/shared")

    def test_server_error_returns_failure(self):
        self.alpha.send_request.side_effect = RuntimeError("server unavailable")
        self.assertNotEqual(self.run_command("alpha/shared"), 0)
