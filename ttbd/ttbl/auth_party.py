#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl

class authenticator_party_c(ttbl.authenticator_c):
    """Life is a party! Authenticator that allows anyone to log in and be
    an admin.

    To configure, create a config file that looks like:

    >>> import timo.auth_party
    >>>
    >>> add_authenticator(timo.auth_party.authenticator_party_c(
    >>>    [ 'admin', 'user', 'role3', ...],
    >>>    local_addresses = [  '127.0.0.1', '192.168.0.2' ] ))
    >>>

    Where you list the roles that everyone will get all the time.

    Normally you want this only for debugging or for local
    instances. Note you can set a list of local addresses to match
    against (strings or regular expressions) which will enforce that
    only authentication from those addresses will just be allowed.

    FIXME: check connections are coming only from localhost

    """
    def __init__(self, roles = None, local_addresses = None):
        ttbl.authenticator_c.__init__(self)
        if not roles:
            self.roles = []
        else:
            self.roles = roles
        if local_addresses != None:
            self.local_addresses = []
            assert isinstance(local_addresses, set)
            for local_address in local_addresses:
                assert isinstance(local_address, str)
                self.local_addresses.append(local_address)
        else:
            self.local_addresses = None

    def __repr__(self):
        if self.local_addresses:
            return "(anyone from %s allowed)" \
                % ", ".join(self.local_addresses)
        else:
            return "(everyone is allowed)"

    def login(self, email, password, **kwargs):
        """
        Validate a email|token/password combination and pull which roles it
        has assigned

        :kwargs: 'remote_addr' set to a string describing the IP
          address where the connection comes from.
        :returns: set listing the roles the token/password combination
          has according to the configuration
        :rtype: set
        :raises: authenticator_c.invalid_credentials_e if the
          token/password is not valid
        :raises: authenticator_c.unknown_user_e if there are remote
          addresses initialized and the request comes from a non-local
          address.
        :raises: authenticator_c.error_e if any kind of error
          during the process happens
        """
        assert isinstance(email, str)
        assert isinstance(password, str)
        if self.local_addresses != None and 'remote_address' in kwargs:
            for local_address in self.local_addresses:
                if local_address == kwargs['remote_address']:
                    return self.roles
            raise self.unknown_user_e
        else:
            return self.roles
