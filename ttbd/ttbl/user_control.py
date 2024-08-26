#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
import errno
import glob
import logging
import os
import os
import pickle
import shutil
import threading

# FIXME: create cache using lru_aged_c, so we don't constantly reload
# FIXME: UGLY HACK, move code around
import ttbl
import commonl

def known_user_list():
    # this now is a HACK, FIXME, repeats a lot of code, but when
    # the user database is moved to fsdb it will be cleaned up
    user_path = os.path.join(User.state_dir, "_user_*")
    l = []
    for path in glob.glob(user_path):
        try:
            # FIXME: ugly hack, fix when we have the cache
            fsdb = commonl.fsdb_symlink_c(path)
            userid = fsdb.get('userid', None)
            if userid:
                l.append(userid)
        except Exception as e:	# FIXME: move to invalid_e
            logging.warning("cannot load user DB '%s': %s",
                            path, e)
            # Wipe the file, it might have errors--it might be not
            # a file, so wipe hard
            commonl.rm_f(path)
    return l


class User(object):
    """
    Implement a database of users that are allowed to use this system

    The information on this database is obtained from authentication
    systems and just stored locally for caching--it's mainly to set
    roles for users.

    Roles are labels which can be used to describe which privileges a
    user has. An :class:`authentication driver
    <ttbl.authenticator_c>`, via it's :meth:`login method
    <ttbl.authenticator_c.login>` has provided a list of roles the
    user shall have.

    Each role can be *gained* or *dropped*; a role can be moved from
    one state to the other by the user themselves or by anyone with
    the *admin* role.

    This allows, for example, a user with the *admin* role to drop it
    for normal use and only gain it when necessary (akin to using
    *sudo*, for example).
    """
    class exception(Exception):
        pass

    class user_not_existant_e(exception):
        """
        Exception raised when information about a user cannot be
        located
        """
        pass

    # Where we save user data so users don't have to re-login
    state_dir = None
    # Optional secondary path to store user state dir info
    state_dir_secondary = None

    def __init__(self, userid, fail_if_new = False, roles = None):
        path = self.create_filename(userid, self.state_dir)
        self.userid = userid
        if not os.path.isdir(path) and fail_if_new == False:
            commonl.rm_f(path)	# cleanup, just in case
            commonl.makedirs_p(path)

        # if requested by admin by setting the variable
        # `ttbl.user_control.User.state_dir_secondary` in the config files
        # we will create a secondary fsdb instance. If nothing was defined we
        # will use the same as the primary
        if self.state_dir != self.state_dir_secondary:
            path_s = self.create_filename(userid, self.state_dir_secondary)
            if not os.path.exists(path_s):
                # create the secondary FSDB top level directory for
                # the user, it does not exist yet
                commonl.makedirs_p(path_s)
            elif not os.path.isdir(path_s) and fail_if_new == False:
                # it exists but it seems to be something else than a
                # directory--just fail, since this doesn't seem to be
                # something we can't control and if it is failing
                # because the directory is corrupted or something,
                # we'd rather an admin looks at it
                raise RuntimeError(
                    f'{path_s} exists but it is not a directory, please'
                     'consider erase it so ttbl/user_control can create it'
                     'properly'
                )
        try:
            self.fsdb = commonl.fsdb_symlink_c(path)
            if self.state_dir != self.state_dir_secondary:
                self.fsdb_secondary = commonl.fsdb_symlink_c(path_s)
            else:
                self.fsdb_secondary = self.fsdb

        except ( AssertionError, commonl.fsdb_c.exception ) as e:
            if fail_if_new:
                raise self.user_not_existant_e("%s: no such user" % userid)
        self.fsdb.set('userid', userid)
        if roles:
            assert isinstance(roles, list)
            for role in roles:
                self.role_add(role)

    def to_dict(self):
        r = commonl.flat_keys_to_dict(self.fsdb.get_as_dict())
        r['name'] = os.path.basename(self.fsdb.location)
        return r

    def wipe(self):
        """
        Remove the knowledge of the user in the daemon, effectively
        logging it out.
        """
        shutil.rmtree(self.fsdb.location, ignore_errors = True)

    @staticmethod
    def is_authenticated():
        return True

    @staticmethod
    def is_active():
        return True

    @staticmethod
    def is_anonymous():
        return False

    def get_id(self):
        return str(self.userid)

    def role_add(self, role):
        """
        Add a given role

        :param str role: name of role to add; if it starts with *!*,
          indicates leave the role dropped.
        """
        assert isinstance(role, str)
        if role.startswith("!"):
            role = role[1:]
            self.role_drop(role)
        else:
            self.role_gain(role)

    def role_drop(self, role):
        """
        Drop a given role

        :param str role: name of role to drop

        Note user can only drop a role they have been given access to
        before with :meth:`role_add`.
        """
        assert isinstance(role, str)
        self.fsdb.set('roles.' + role, False)

    def role_gain(self, role):
        """
        Gain an existing role
        :param str role: name of role to gain

        Note user can only gain a role they have been given access to
        before with :meth:`role_add`.
        """
        assert isinstance(role, str)
        # FIXME: convert to normal booleans
        self.fsdb.set('roles.' + role, True)

    def role_get(self, role):
        """
        Return if the user has a role, gained or dropped

        :return: *True* if the user has the role gained, *False* if
          dropped, *None* if the user does not have the role.
        """
        val = self.fsdb.get('roles.' + role, None)
        assert val == None or isinstance(val, bool), \
            "BUG: user %s[roles.%s] is val type %s; expected bool" \
            % (self.userid, role, type(val))
        return val

    def role_present(self, role):
        """
        Return *True* if the user has the role (gained or dropped),
        *False* otherwise
        """
        return self.fsdb.get('roles.' + role, None) != None

    def is_admin(self):
        """
        Return *True* if the user has the *admin* role gained.
        """
        return self.fsdb.get('roles.admin', False) == True

    def role_list(self):
        """
        Return a list of roles the user has

        :returns dict: dict listing all roles and their state
        """
        # note we need to remove from each key the leading
        # roles. string to get the actual roles
        d = {}
        for role_key in self.fsdb.keys('roles.*'):
            d[role_key[len("roles."):]] = self.fsdb.get(role_key, False)
        return d


    @staticmethod
    def load_user(userid):
        return User(userid)

    @staticmethod
    def create_filename(userid, state_dir):
        """
        Makes a safe filename based on the user ID
        """
        filename = "_user_" + commonl.mkid(userid)
        return os.path.join(state_dir, filename)

    @staticmethod
    def search_user(userid):
        try:
            return User(userid, fail_if_new = True)
        except:
            return None
