#! /usr/bin/python3
#
# Copyright (c) 2026 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import msal
import requests

import commonl
import ttbl

import logging



class driver_c(ttbl.authenticator_c):
    def __init__(self,
                 tenant_id: str,
                 client_id: str,
                 client_secret: str,
                 role_map: dict = None):
        """Authenticate with username and password against the
        Microsoft Entra Identity Management System

        :param str tenant_id: RFC4122 GUID from
          https://entra.microsoft.com, Tenant ID describing your
          organization, in the form *hhhhhhhh-hhhh-hhhh-hhhhhhhhhhhh*,
          where h is a hexadecimal digit.

          eg: *64ac98d8-34e4-d44e-8694-eadbc4257e5d*

        :param str client_id: RFC4122 GUID from
          *https://entra.microsoft.com > App Registrations >
          <APPLICATION>*, Application (client) IDT describing your
          application, in the form *hhhhhhhh-hhhh-hhhh-hhhhhhhhhhhh*,
          where h is a hexadecimal digit.

          eg: *6b3abd14-e645-54ac-94e2-3413da5b08d2*

        :param str client_secret: a secret generated with

          *https://entra.microsoft.com > App Registrations >
          <APPLICATION> > Certificates & Secrets*.

          this can be specifed as *FILE:<FILENAME>* to be read from a
          file everytime is needed, so it can be updated on the run.

          To rotate the client secret key, it needs to be a file (or
          keyring entry); it will be loaded new everytime a login
          operation is done.

        :param dict role_map: dictionary keyed by role name of users
          and groups that shall the role.

          Each value is a dictionary with two possible keys:

          - *users*: with a list of users that shall take that role.

          - *groups*: with a list of users that shall take that role
            if they are in any of the groups listed.

            If None, it will match any group.

          Example:

          >>> role_map = {
          >>>    "ROLENAME": {
          >>>        'user': [
          >>>             'some.name@domain.com',
          >>>             'another.name@domain.com',
          >>>        ],
          >>>        'groups': [
          >>>             'group one',
          >>>             'group two',
          >>>        ]
          >>>    },
          >>>    "user": {   # any user that can log in gets this
          >>>        'groups': None
          >>> }

          Note that this can also be done in the inventory for the
         *local* target

        *System Setup*

        Some permissions are needed in the Microsoft Entra App
        registration so this can be done:

        - GroupMember.Read.All

        - User.Read

        - User.ReadBasic.All

        They all need permissions granted for the tenant in *Entra >
        App registration > *APPNAME* > API Permissions*

        - Grant permission to the Tenant ID; steps
          1. Microsoft Graph
          2. Delegated Permission
          3. Select permissions
            - GroupMember.Read.All
            - User.Read
            - User.ReadBasic.All

        """
        assert isinstance(tenant_id, str), \
            f"tenant_id: expected string; got {type(tenant_id)}"
        assert isinstance(client_id, str), \
            f"client_id: expected string; got {type(client_id)}"
        assert isinstance(client_secret, str), \
            f"client_secret: expected string; got {type(client_secret)}"
        if role_map != None:
            commonl.assert_dict_of_types(role_map, "role_map", dict)

        self.log = logging.getLogger("auth_ms_entra")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.role_map = role_map



    def __repr__(self):
        return f"MSAL-{self.tenant_id}/{self.client_id}"



    def groups_get_by_access_token(self, username: str, access_token: str) -> list[str]:

        # Now get the groups and map them.
        #

        # Get groups
        #
        # Doing this with the MSAL libraries SDK is way too complex,
        # this is simpler to read the group names, we need
        #
        ## GroupMember.Read.All
        #
        # see above for configuration

        # shall be configured, if anything from top level
        # configuration setting it in local
        groups = set()

        url = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf"
        while url:
            # the response might be paged, so we need to iterate
            resp = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {access_token}"
                })
            resp.raise_for_status()
            # j is a dictionary of fields
            j = resp.json()
            # Collect groups from this page
            for group_itr in j.get("value", []):
                if group_itr["@odata.type"] == "#microsoft.graph.group":
                    display_name = group_itr.get('displayName', None)
                    if display_name:
                        groups.add(display_name)
            url = j.get("@odata.nextLink")

        return groups


    def map_roles(self, username: str, groups: set) -> dict:
        """Given a username and groups from the auth system, map it to roles

        Every group is made a role, and then each group might drive in
        additional roles from:

        - input configuration to the driver

        - variables in the inventory for the local target under
          *auth.user.USERNAME* and  *auth.group.GROUPNAME*

        """
        roles = set(groups)

        # map groups from config time to roles
        for role, data in self.role_map.items():
            if username in data.get('users', []):
                roles.add(role)
            if 'groups' in data:
                data_groups = data['groups']
                if data_groups == None:
                    roles.add(role)
                    continue
                role_groups = set(data_groups) & groups
                if role_groups:
                    self.log.info(
                        "%s: adding to role '%s' because of membership in groups %s",
                        username, role, role_groups)
                    roles.add(role)

        # map groups from inventory to roles
        #
        # local.auth.user.<username>: role1,role2,role3
        # local.auth.group.<groupname>: role1,role2,role3
        target_local = ttbl.test_target.get("local")
        if target_local:
            # if the configuration did create a local target, it might
            # expose extra role/mapping configuration
            auth_groups = target_local.to_dict([ "auth.group" ])
            auth_groups = auth_groups.get("auth", {}).get("group", {})
            for group in groups:
                group_safe = commonl.name_make_safe(group)
                roles_group = auth_groups.get(group_safe, None)
                if roles_group:
                    roles.update(roles_group.split(','))

            # publish extra information about herds/servers
            auth_user = target_local.to_dict([ "auth.user" ])
            username_safe = commonl.name_make_safe(username)
            roles_user = auth_user.get(username_safe)
            # this is a comma-separated list of rolenames
            if roles_user:
                roles.update(roles_user.split(','))
        return roles



    def login_hook(self, msal_r, groups):
        """
        Function called by :meth:login once a user is authenticated
        sucessfully

        This function does nothing and is meant for being overloaded
        in an inherited class to implement any extra needed
        functionality, eg:

        >>> class my_driver(ttbl.auth_ms_entra._driver)
        >>>
        >>>     def login_hook(self, records):
        >>>         ...
        >>>         return data

        :param list record: All the records matching the username given
          to :meth:login are passed in *record*, which has the
          following structure:

          >>> [
          >>>    ( DN, DICT-OF-FIELDS ),
          >>>    ( DN1, DICT-OF-FIELDS ),
          >>>    ( DN2, DICT-OF-FIELDS ),
          >>>    ...
          >>> ]

        :returns: dictionary keyed by strings of fields we want the
          user database to contain; only int, float, bool and strings
          are allowed. Key name *roles* is reserved.

        """
        return {}



    def login(self, username: str, password: str, **kwargs):
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
        assert isinstance(username, str), \
            f"username: expected string; got {type(username)}"
        assert isinstance(password, str), \
            f"password: expected string; got {type(password)}"


        # expand so it can be updated frequently in disk when it has
        # to change without restarting the server
        client_secret = commonl.password_get(
            self.tenant_id,
            self.client_id,
            self.client_secret)

        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority = f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential = client_secret,
        )

        # authenticate username/password against MS Entra, and get the
        # token if the combination is valid; this is in *result*; r is
        # a dictionary of values or erors
        r = app.acquire_token_by_username_password(
            username, password,
            scopes = [ "https://graph.microsoft.com/.default" ]
        )

        if 'error' in r:
            # if we have an error, the token/password combination is not
            # valid, so we raise invalid_credentials_e
            message = r.get("error_description", str(r))
            raise self.invalid_credentials_e(
                f"invalid credentials for username '{username}': {message}",
                **r)
        access_token = r['access_token']

        # auth is valid, r is like
        ## {
        ##  "token_type": "Bearer",
        ##  "scope": "profile openid email https://graph.microsoft.com/GroupMember.Read.All https://graph.microsoft.com/User.Read https://graph.microsoft.com/User.ReadBasic.All https://graph.microsoft.com/.default",
        ##  "expires_in": 4551,
        ##  "ext_expires_in": 4551,
        ##  "access_token": "AAA....",
        ##  "refresh_token": "AAA...",
        ##  "id_token": "AAA....",
        ##  "client_info": "AAA...",
        ##  "id_token_claims": {
        ##   "aud": "...",
        ##   "iss": "https://login.microsoftonline.com/46c98d88-.../v2.0",
        ##   "iat": nnnn...,
        ##   "nbf": 1778...,
        ##   "exp": 1778...,
        ##   "name": "NAME",
        ##   "oid": "hhhhhhhh-hhhh-hhhh-hhhhhhhhhhhh",
        ##   "preferred_username": "name@domain",
        ##   "rh": "AAAAAAAAAAA.............................AAAAAAAAAAAAAAA..",
        ##   "sid": "*hhhhhhhh-hhhh-hhhh-hhhhhhhhhhhh*",
        ##   "sub": "AAAAAAAAAAAA..................AAAAAAAAAAAAA",
        ##   "tid": "hhhhhhhhhhhhhh.............hhhhhhhhh",
        ##   "uti": "AAAAAAA.............AA",
        ##   "ver": "2.0"
        ##  },
        ##  "token_source": "identity_provider"
        ## }

        groups = self.groups_get_by_access_token(username, access_token)
        roles = self.map_roles(username, groups)
        data = self.login_hook(r, roles)
        data['roles'] = roles
        return data
