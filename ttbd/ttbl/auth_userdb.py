#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import errno
import hashlib
import os
import stat

import ttbl

class driver(ttbl.authenticator_c):
    """Authenticate users from a local database directory

    To configure, create a database directory where a file per user
    will be created, describing the user's roles and hashed password;
    ensure the group *ttbd* can read it and also new files created on
    it, and it is not available to other users (mode *02770*)::

      # install -g ttbd -m 2770 -d /etc/ttbd-production/userdb

    Configure in any server :ref:`configuration file
    <ttbd_configuration>` such as
    ``/etc/ttbd-production/conf_04_auth.py``:

    >>> import ttbl.auth_userdb
    >>> import ttbl.config
    >>>
    >>> ttbl.config.add_authenticator(ttbl.auth_userdb.driver("/etc/ttbd-production/userdb"))

    Restart to read the configuration::

      # systemctl restart ttbd@production

    - Add or modify new users with::

        $ ttbd-passwd -p /etc/ttbd-production/userdb user1
        Password for user1:
        $ ttbd-passwd -p /etc/ttbd-production/userdb user2 password2
        $ ttbd-passwd -p /etc/ttbd-production/userdb user3 password3 -r admin

      Note how the password can be specified on the command line or
      queried in stdin. Roles can be added with the *-r* option. See
      *--help* for more options. After this::

        $ ls -l /etc/ttbd-production/userdb
        total 12
        -rw-r----- 1 LOGIN ttbd 86 May 13 21:37 user1
        -rw-r----- 1 LOGIN ttbd 86 May 13 21:38 user2
        -rw-r----- 1 LOGIN ttbd 92 May 13 21:38 user3

        $ cat /etc/ttbd-alloc/userdb/user3
        user,admin:sha256:892147:64:13bbb3e5deaa8f42fa10b233278c7b480549d7c7cfa085bf9203f867c7ec3af2

    - Delete users USERNAME by removing file
      */etc/ttbd-production/userdb/USERNAME*

    The database can be placed in any directory wanted/needed.

    The fields are in a single line, separated by colons:

    - list of user roles (simple strings with chars *[_a-zA-Z0-9]*,
      separated by commas; see :ref:`access control
      <target_access_control>` for a description on roles.

    - algorithm used to hash (from the list of names reported by
      python's *hashlib.algorithms_available*).

    - salt value (integer)

    - hexdigest len (integer)

    - hexdigest (obtained by hashing a string composed of joining the
      salt as a string, the username and the password with the hashing
      algorithm), converting to a hex representaion and taking the
      first *hexdigest len* characters of it.

    """
    def __init__(self, userdb):
        """
        :param str userdb: path to directory where the user database
          is stored (one file per user)
        """
        assert isinstance(userdb, str)

        if not os.path.isdir(userdb):
            raise AssertionError(
                "auth_userdb: %s: path is not a directory" % userdb)
        st = os.stat(userdb)
        if st.st_mode & stat.S_IRWXO:
            raise AssertionError(
                "auth_userdb: %s: path is accessible by other than"
                " user/group (%04o); fix with 'chmod o= %s'"
                % (userdb, st.st_mode, userdb))
        #: path for the user database
        #:
        #: This is a directory, 
        self.userdb_path = userdb

    def __repr__(self):
        return "user database @%s" % self.userdb_path

    def login(self, username, password, **kwargs):
        """
        Validate a username/password combination and pull which roles it
        has assigned in the user db :attr:`userdb_path`

        :param str username: name of user to validate

        :param str password: user's password to validate

        :returns set: set listing the roles the token/password combination
          has according to the configuration

        :raises: :exc:`ttbl.authenticator_c.invalid_credentials_e` if the
          token/password is not valid

        :raises: :exc:`ttbl.authenticator_c.error_e` if any kind of error
          during the process happens
        """
        assert isinstance(username, str)
        assert isinstance(password, str)

        data_path = os.path.join(self.userdb_path, username)
        try:
            with open(data_path, "r") as f:
                data = f.read()
        except IOError as e:
            if e.errno == errno.ENOENT:
                raise self.unknown_user_e("unknown user '%s'" % username)
            raise

        # ttbd-passwd generates five fields separated by :
        datal = data.strip().split(":")
        if len(datal) != 5:
            raise self.unknown_user_e(
                "invalid user '%s': corrupted DB?" % username)

        try:
            roles = datal[0].split(",")
            algorithm = datal[1]
            salt = datal[2]
            digest_len = int(datal[3])
            hashed_password = datal[4]
        except Exception as e:
            raise self.unknown_user_e(
                "invalid user '%s': corrupted data? %s" % (username, e))

        hashed_password_input = hashlib.new(
            algorithm,
            (salt + username + password).encode("utf-8"))
        hashed_password_input = hashed_password_input.hexdigest()[:digest_len]

        if hashed_password_input != hashed_password:
            raise self.invalid_credentials_e(
                "invalid password for user '%s'" % username)
        return set(roles)
