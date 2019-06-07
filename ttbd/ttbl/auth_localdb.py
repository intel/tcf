#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import hashlib
import ttbl

class authenticator_localdb_c(ttbl.authenticator_c):
    """Use a simple DB to authenticate users

    To configure, create a config file that looks like:

    >>> import ttbl.auth_localdb
    >>>
    >>> add_authenticator(ttbl.auth_localdb.authenticator_localdb_c(
    >>>     "NAME",
    >>>     [
    >>>       ['user1', 'password1', 'role1', 'role2', 'role3'...],
    >>>       ['user2', 'password2', 'role1', 'role4', 'role3' ],
    >>>       ['user3', None, 'role2', 'role3'...],
    >>>       ['user4', ],
    >>>      ]))

    Each item in the users list is a list containing:

     - the user id (*userX*)
     - the password in plaintext (FIXME: add digests); if empty, then
       the user has no password.
     - list of roles (*roleX*)

    """
    def __init__(self, name, users):
        """
        :param str name: FIXME
        :param dict users: map of roles to users and groups
        """
        assert isinstance(name, str)
        assert isinstance(users, list)

        self.name = name
        self.passwords = {}
        self.roles = {}
        for user in users:
            if not isinstance(user, list):
                raise ValueError("user specification '%s' must be "
                                 "a list of strings" % user)
            for tag in user:
                if tag != None and not isinstance(tag, str):
                    raise ValueError("user specification '%s' must be "
                                     "a list of strings" % user)
            user_name = user[0]
            if len(user) > 1:
                password = user[1]
            else:
                password = None
            if len(user) > 2:
                roles = set(user[2:])
            else:
                roles = set()
            self.passwords[user_name] = password
            self.roles[user_name] = roles

    def __repr__(self):
        return "localdb %s" % self.name

    def login(self, email, password, **kwargs):
        """
        Validate a email|token/password combination and pull which roles it
        has assigned

        :returns: set listing the roles the token/password combination
          has according to the configuration
        :rtype: set
        :raises: authenticator_c.invalid_credentials_e if the
          token/password is not valid
        :raises: authenticator_c.error_e if any kind of error
          during the process happens
        """
        assert isinstance(email, str)
        assert isinstance(password, str)

        if email not in self.passwords:
            raise self.unknown_user_e(
                "%s: unknown user in  %s" % (email, self))
        hashed_password = hashlib.sha256(password).hexdigest()

        _password = self.passwords[email]
        while True:
            if _password != None and hashed_password == _password:
                break
            if _password != None and password == _password:
                break
            raise self.invalid_credentials_e(
                "%s: invalid password in %s" % (email, self))
        return self.roles[email]
