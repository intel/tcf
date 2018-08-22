#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import urlparse

import ldap

import ttbl

class authenticator_ldap_c(ttbl.authenticator_c):
    """Use LDAP to authenticate users

    To configure, create a config file that looks like:

    >>> import ttbl.auth_ldap
    >>>
    >>> add_authenticator(timo.auth_ldap.authenticator_ldap_c(
    >>>     "ldap://URL:PORT",
    >>>     roles = {
    >>>         ....
    >>>     roles = {
    >>>       'role1': { 'users': [ "john", "lamar", ],
    >>>                  'groups': [ "Occupants of building 3"  ]
    >>>       },
    >>>       'role2': { 'users': [ "anthony", "mcclay" ],
    >>>                  'groups': [ "Administrators",
    >>>                              "Knights who say ni" ]
    >>>        },
    >>>     }))

    The *roles* dictionary determines *who gets to be an admin* or who gets
    access to XYZ resources.

    This will make that *john*, *lamar* and any user on the group
    *Occupants of building 3* to have the role *role1*.

    Likewise for *anthony*, *mcclay* and any user who is a member of
    either the group *Administrators* or the group *Knights who say
    ni*, they are given role *role2*
    """
    def __init__(self, url, roles = None):
        """
        :param str url: URL of the LDAP server
        :param dict roles: map of roles to users and groups
        """
        if not roles:
            roles = {}
        assert isinstance(url, basestring)
        assert isinstance(roles, dict)

        u = urlparse.urlparse(url)
        if u.scheme == "" or u.netloc == "":
            raise ValueError("%s: malformed LDAP URL?" % url)
        self.url = u.geturl()

        for role in roles:
            if not isinstance(role, basestring):
                raise ValueError("role specification keys must be strings")
            for tag in roles[role]:
                if not tag in ('users', 'groups'):
                    raise ValueError(
                        "subfield for role must be 'users' or 'groups'")
                if not isinstance(roles[role][tag], list):
                    raise ValueError("value of role[%s][%s] must be a "
                                     "list of strings" % (role, tag))
                for value in roles[role][tag]:
                    if not isinstance(value, basestring):
                        raise ValueError("members of role[%s][%s] must "
                                         "be  strings; '%s' is not" %
                                         (role, tag, value))
        self.conn = None
        self.roles = roles
        if ttbl.config.ssl_enabled_check_disregard == False \
                and ttbl.config.ssl_enabled == False:
            raise RuntimeError("LDAP can't run as HTTPS is disabled")
    def __repr__(self):
        return self.url

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
        assert isinstance(email, basestring)
        assert isinstance(password, basestring)

        # Always use a new connection, so it doesn't get invalidated
        # after a while
        self.conn = ldap.initialize(self.url)
        self.conn.set_option(ldap.OPT_REFERRALS, 0)

        record = None
        # First bind to LDAP and search the user's email
        try:
            self.conn.simple_bind_s(email, password.encode('utf8'))
            # FIXME: with self.conn.simple_bind_s?
            record = self.conn.search_s(
                "", ldap.SCOPE_SUBTREE, 'mail=%s' % email,
                [ 'sAMAccountName', 'mail', 'memberOf'])
            self.conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            raise self.invalid_credentials_e(
                "%s: invalid credentials for LDAP %s: %s"
                % (email, self, e))
        except Exception as e:
            logging.exception(e)
            raise self.error_e(
                "%s: generic error in LDAP %s: %s"
                % (email, self, e))

        token_roles = set()
        # So the token/password combination exists and is valid, so
        # now let's see what roles we need to assign the user
        # depending on if it shows in the user list for that role
        for role_name, role in self.roles.iteritems():
            if email in role.get('users', []):
                token_roles.add(role_name)

        # Now let's check groups -- pull the LDAP groups from the record
        data = {}
        # get data from record
        # record is a list of entries returned by conn.search_s
        # conn.search_s -> conn.search_ext_s
        # "Each result tuple is of the form (dn, attrs) where dn is a
        # string containing the DN (distinguished name) of the entry,
        # and attrs is a dictionary containing the attributes
        # associated with the entry."  from
        # http://www.python-ldap.org/doc/html/ldap.html#ldap.LDAPObject.search_ext_s
        if record and record[0] and record[0][1]:
            data_record = record[0][1]

            for key in data_record.keys():
                # here we extract the information from the dict, wich is a list
                # if we have only 1 element, we remove the list object
                data[key] = data_record[key][0] \
                            if len(data_record[key]) == 1 else data_record[key]

        # extend memberOf here is to remove all the ldap fields for
        # the group name, and save only the name the name is between
        # CN=%GROUP NAME%,DC=...
        groups = []
        for group in data_record['memberOf']:
            tmp = group.split(",")
            for i in tmp:
                if i.startswith('CN='):
                    group_name = i.replace('CN=', '')
                    groups.append(group_name)
                    break
        # Given the group list @groups, check which more roles we
        # need to add based on group membership
        for group in groups:
            for role_name, role in self.roles.iteritems():
                if group in role.get('groups', []):
                    token_roles.add(role_name)
        return token_roles
