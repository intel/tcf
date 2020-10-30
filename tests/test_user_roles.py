#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import json
import os

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


class _test_roles_login(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.mk_tcf_config()

        self.run_local(self.tcf_cmdline() +
                       " login -p bad_password user1 || true",
                       "user user1: not allowed")
        self.report_pass("user1 can't login with a bad password")

        self.run_local(self.tcf_cmdline() +
                       " login -p password user1")
        self.report_pass("user1 logged in")

        json_output = self.run_local(self.tcf_cmdline() +
                                     " user-list -vvvv")
        data = json.loads(json_output)
        assert 'local' in data
        assert 'user1' in data['local']
        assert data['local']['user1']['userid'] == 'user1'
        # save the encoded user name to check later if it is removed
        # from the DB when we logout
        self.user_name = data['local']['user1']['name']

        if not os.path.isdir(os.path.join(self.ttbd.lib_dir, self.user_name)):
            raise tcfl.tc.failed_e(
                "after login, there is entry %s for %s is in %s"
                % (self.user_name, 'user1', self.ttbd.lib_dir))
        self.report_pass("user1 directory in the server has been created")

        # in the config we only set these two roles
        assert 'roles' in data['local']['user1']
        assert len(data['local']['user1']['roles']) == 2
        assert 'user' in data['local']['user1']['roles']
        assert 'context1' in data['local']['user1']['roles']
        self.report_pass("user1 logged in has only expected roles")


    def eval_30(self):
        self.ttbd.local_auth_disable()
        self.run_local(self.tcf_cmdline() +
                       " logout")

        # if we have logged out, the user entry shall be removed from
        # the server
        if os.path.isdir(os.path.join(self.ttbd.lib_dir, self.user_name)):
            raise tcfl.tc.failed_e(
                "after logout user entry %s for %s is still in %s"
                % (self.user_name, 'user1', self.ttbd.lib_dir))
        self.report_pass("user1 directory in the server has been deleted")

        # FIXME: try every possible endpoint, shall return unauthorized
        for command in [
                'user-list',
                'list',
        ]:
            self.run_local(self.tcf_cmdline() +
                           " %s || true" % command,
                           "400: User unauthorized; please login")
        self.report_pass("different commands fail to run when logged out")


class roles_gain_drop(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.mk_tcf_config()

        self.run_local(self.tcf_cmdline() +
                       " login -p password user2")
        self.report_pass("user2 logged in")

        self.run_local(self.tcf_cmdline() +
                       " role-drop context2")
        json_output = self.run_local(self.tcf_cmdline() +
                                     " user-list -vvvv")
        data = json.loads(json_output)
        # in the config we only set these two roles
        assert len(data['local']['user2']['roles']) == 2
        assert data['local']['user2']['roles']['user'] == True
        # context2 has to be now disabled
        assert data['local']['user2']['roles']['context2'] == False
        self.report_pass("user2 can drop role context2")

        self.run_local(self.tcf_cmdline() +
                       " role-gain context2")
        json_output = self.run_local(self.tcf_cmdline() +
                                     " user-list -vvvv")
        data = json.loads(json_output)
        # in the config we only set these two roles
        assert len(data['local']['user2']['roles']) == 2
        assert data['local']['user2']['roles']['user'] == True
        # context2 has to be now enabled
        assert data['local']['user2']['roles']['context2'] == True
        self.report_pass("user2 can gain role context2")
