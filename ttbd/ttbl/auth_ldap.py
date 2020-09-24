#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import collections
import logging
import time
import urlparse

import ldap

import commonl
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

    If *'groups'* is a *None*, it means give that role to anyone, they
    don't have to be part of any group. This allows to permit the role
    to anyone that can authenticate with LDAP.
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
                if roles[role][tag] != None:
                    if not isinstance(roles[role][tag], list):
                        raise ValueError(
                            "value of role[%s][%s] must be a "
                            "list of strings or None" % (role, tag))
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


    ldap_field_set = set()

    def ldap_login_hook(self, record):
        """
        Function called by :meth:login once a user is authenticated
        sucessfully on LDAP

        This function does nothing and is meant for being overloaded
        in an inherited class to implement any extra needed
        functionality, eg:

        >>> class my_auth_c(ttbl.auth_ldap.authenticator_ldap_c)
        >>>
        >>>     def ldap_login_hook(self, record):
        >>>
        >>>
        >>>     def ldap_login_hook(self, records):
        >>>         d = 0
        >>>         record = records[0]
        >>>         dn = record[0]
        >>>         fields = record[1]
        >>>
        >>>         data = {}
        >>>         dnl = ldap.dn.explode_dn(dn)
        >>>         for i in dnl:
        >>>             if i.startswith("CN="):
        >>>                 # CN=Lastname\\, Name -> unscape the value
        >>>                 data['name'] = i.split("=", 1)[1].replace("\\", "")
        >>>             if i.startswith("DC=") and 'domain' not in data:
        >>>                 # we take the first DC= component and store as domain,
        >>>                 # ignore the rest from a string such as
        >>>                 # u'DC=subdomain2', u'DC=subdomain3', u'DC=company', u'DC=com'
        >>>                 data['domain'] = i.split("DC=")[1].replace("\\", "")
        >>>
        >>>         data['login'] = fields['sAMAccountName'][0]
        >>>         return data

        :param list record: All the records matching the email given
          to :meth:login are passed in *record*, which has the
          following structure:

          >>> [
          >>>    ( DN, DICT-OF-FIELDS ),
          >>>    ( DN1, DICT-OF-FIELDS ),
          >>>    ( DN2, DICT-OF-FIELDS ),
          >>>    ...
          >>> ]

          In most properly configured LDAPs, there will be just ONE
          entry for the matching user.

          *DN* is a string containing the the distinguished name, and
          might look as::

            CN=Lastnames\\, Firstnames,OU=ORGUNIT,DC=DOMAIN1,DC=DOMAIN2,...

          eg::

            CN=Doe\\, Jane John,OU=Staff,DC=company,DC=com

          Dict of fields is a dictionary of all the fields listed in
          :data:ldap_field_set plus *sAMAccountName*, *mail* and
          *memberOf* (which :meth:login below always queries).

          Each fields is a list of values; in some case it might be only
          one, in others, multiple.

        :returns: dictionary keyed by strings of fields we want the
          user database to contain; only int, float, bool and strings
          are allowed. Key name *roles* is reserved.

        """
        return {}

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
        # let the connection die reasonably fast so a new one is
        # re-opened if the peer killed it.
        self.conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)

        record = None
        # First bind to LDAP and search the user's email
        try:
            ldap_fields = set([ 'sAMAccountName', 'mail', 'memberOf' ])
            # add anything else the admin has said
            ldap_fields.update(self.ldap_field_set)
            self.conn.simple_bind_s(email, password.encode('utf8'))
            # search_s is picky in the field list; has to be a list,
            # can't be a set
            record = self.conn.search_s(
                "", ldap.SCOPE_SUBTREE, 'mail=%s' % email, list(ldap_fields))
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
        for group in data_record.get('memberOf', []):
            tmp = group.split(",")
            for i in tmp:
                if i.startswith('CN='):
                    group_name = i.replace('CN=', '')
                    groups.append(group_name)
                    break
        groups = set(groups)
        # Given the group list @groups, check which more roles we
        # need to add based on group membership
        for role_name, role in self.roles.iteritems():
            role_groups = role.get('groups', [])
            if role_groups == None:
                # any valid user can take this role
                token_roles.add(role_name)
            elif set(role_groups) & groups:
                # the LDAP records describes groups that are also in
                # the list of acceptable groups for this role
                token_roles.add(role_name)

        data = self.ldap_login_hook(record)
        assert isinstance(data, dict), \
            "%s.ldap_login_hook() returned '%s', expected dict" \
            % (type(self).__name__, type(data))
        assert 'roles' not in data, \
            "%s.ldap_login_hook() returned a dictionary with a 'roles'" \
            " field, which is reserved"
        data['roles'] = token_roles
        return data


class ldap_map_c(object):
    """General LDAP mapper

    This objects allows maps and caches entities in an LDAP database, to
    speed up looking up of values from other values.

    For example, to get the *displayName* based on the *sAMAccountName*:

    >>> account_name = self.lookup("Some User", 'displayName', 'sAMAccountName')

    looks up an LDAP entity that has *Some User* as field
    *displayName* and returns it's *sAMAccountName*.

    This does the same, but caches the results so that the next
    time it looks it up, it doesn't need to hit LDAP:

    >>> account_name = self.lookup_cached("Some User", 'displayName', 'sAMAccountName')

    this object caches the objects, as we assume LDAP behaves
    mostly as a read-only database.

    :param str url: URL of the LDAP server; in the form
      *ldap[s]://[BIND_USERNAME[:BIND_PASSWORD]]@HOST:PORT*.

      The bind username and password can be specified in the
      arguments below (eg: when either have a *@* or *:* and they
      follow the same rules for password discovery.

    :param str bind_username: (optional) login for binding to
      LDAP; might not be needed in all setups.

    :param str bind_password: (optional) password to binding to
      LDAP; migt not be needed in all setups.

      Will be handled by :func:`commonl.password_get`, so
      passwords such as:

       - *KEYRING* will ask the accounts keyring for the password
          for service *url* for username *bind_username*

       - *KEYRING:SERVICE* will ask the accounts keyring for the password
          for service *SERVICE* for username *bind_username*

       - *FILENAME:PATH* will read the password from filename *PATH*.

      otherwise is considered a hardcoded password.

    :param int max_age: (optional) number of seconds each cached
      entry is to live. Once an entry is older than this, the LDAP
      server is queried again for that entry.
    """

    class error_e(ValueError):
        pass

    class invalid_credentials_e(error_e):
        pass

    def __init__(self, url,
                 bind_username = None, bind_password = None,
                 max_age = 200):
        assert isinstance(url, basestring)
        assert bind_username == None or isinstance(bind_username, basestring)
        assert bind_password == None or isinstance(bind_password, basestring)
        assert max_age > 0

        url_parsed = urlparse.urlparse(url)
        if url_parsed.scheme != "ldap" or url_parsed.netloc == "":
            raise ValueError("%s: malformed LDAP URL?" % url)
        self.url = commonl.url_remove_user_pwd(url_parsed)
        if bind_username == None:
            self.bind_username = url_parsed.username
        else:
            self.bind_username = bind_username
        if bind_password == None:
            self.bind_password = url_parsed.password
        else:
            self.bind_password = bind_password
        self.bind_password = commonl.password_get(self.url, self.bind_username,
                                                  self.bind_password)
        # dictionary of [ field_lookup, field_report ] = {
        #   VALUE: ( TIMESTAMP, REPORTED_FIELD ),
        # }
        self._cache = collections.defaultdict(dict)
        self.conn = None
        #: maximum number of seconds an entry will live in the cache
        #: before it is considered old and refetched from the servers.
        self.max_age = max_age

    def _conn_setup(self):
        if self.conn:
            return
        self.conn = ldap.initialize(self.url)
        self.conn.set_option(ldap.OPT_REFERRALS, 0)
        # let the connection die reasonably fast so a new one is
        # re-opened if the peer killed it.
        self.conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
        self.conn.simple_bind_s(self.bind_username, self.bind_password)

    def lookup(self, what, field_lookup, field_report):
        """
        Lookup the first LDAP record whose field *field_lookup*
        contains a value of *what*

        :returns: the value of the field *field_record* for the
          record found; *None* if not found or the record doesn't have
          the field.
        """
        assert isinstance(what, basestring)
        assert isinstance(field_lookup, basestring)
        assert isinstance(field_report, basestring)

        while True:	# retry
            try:
                self._conn_setup()
                record = self.conn.search_s(
                    "", ldap.SCOPE_SUBTREE, '%s=%s' % (field_lookup, what),
                    [ field_lookup, field_report ])
                return record
            except ldap.INVALID_CREDENTIALS as e:
                raise self.invalid_credentials_e(
                    "%s: invalid credentials for LDAP %s=%s: %s"
                    % (self.url, field_lookup, what, e))
            except (ldap.error, ldap.CONNECT_ERROR) as e:
                logging.warning("LDAP: connection error, retrying: %s / %s",
                                type(e), e)
                # ok, reinit the connection, rebind, retry
                self.conn = None
                continue
            except Exception as e:
                logging.exception("error %s: %s", type(e), e)
                raise self.error_e(
                    "%s: generic error in LDAP searching %s=%s: %s"
                    % (self.url, field_lookup, what, e))

    def lookup_cached(self, value, field_lookup, field_report):
        """
        Same operation as :meth:`lookup`; however, it caches the
        result, so if the last lookup is younger than :data:`max_age`,
        said result is used. Otherwise a new LDAP lookup is done and
        the value cached.
        """
        assert isinstance(value, basestring)
        assert isinstance(field_lookup, basestring)
        assert isinstance(field_report, basestring)

        cache = self._cache[( field_lookup, field_report)]
        if value in cache:
            # hit in the cache
            ts, mapped_value = cache[value]
            now = time.time()
            if now - ts < self.max_age:
                return mapped_value	                # still fresh, use it
            # cache entry is stale, delete it and lookup
            del cache[value]
        records = self.lookup(value, field_lookup, field_report)
        # returns a list of records, so let's check each, although
        # mostl likely it'll be only
        now = time.time()
        for _dn, record in records:
            # displayName is also a list of names, so we match on one
            # that contains exactly the name we are looking for
            mapped_value = record[field_report][0]
            if value in record[field_lookup]:
                cache[value] = ( now, mapped_value )
                return mapped_value
        # nothing found, so bomb it.
        return None
