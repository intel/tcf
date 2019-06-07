#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
import errno
import os
import pickle
import logging
import shutil
import threading

import commonl


class User():
    """
    Implement a database of users that are allowed to use this system

    The information on this database is obtained from authentication
    systems and just stored locally for caching--it's mainly to set
    roles for users.

    """
    # Must access the user data files only under this lock, to avoid
    # one process writing while one is reading.
    file_access_lock = threading.Lock()

    # FIXME: this should be more atomic -- we might have multiple
    # threads writing and reading to the disk--need file locks.

    class user_not_existant_e(IndexError):
        """
        Exception raised when information about a user cannot be
        located
        """
        pass

    # Where we save user data so users don't have to re-login
    state_dir = None

    def __init__(self, userid, fail_if_new = False):
        self.userid = userid

        self.roles = set(('user',))

        # Try to load the pickled file with the user's cached roles
        self.filename = User.create_filename(userid)
        with self.file_access_lock:
            try:
                with open(self.filename, 'rb') as file:
                    data = pickle.load(file)
                    self.roles.update(data['roles'])
                    logging.log(3, "%s: new user object created from %s",
                                userid, self.filename)
            except IOError as e:
                if e.errno != errno.ENOENT:
                    logging.warning("%s: cannot load user file '%s': %d %s",
                                    userid, self.filename, e.errno, e)
                    # Wipe the file, it might have errors--it might be not
                    # a file, so wipe hard
                    shutil.rmtree(self.filename, ignore_errors = True)
                elif fail_if_new == True:
                    raise self.user_not_existant_e("%s: no such user" % userid)
                else:
                    logging.log(9, "%s: new user object created", userid)
                    self._save_data()
            except Exception as e:
                logging.warning("%s: cannot load user file '%s': %s %s",
                                userid, self.filename, type(e).__name__, e)
                self._save_data()

    @staticmethod
    def is_authenticated():
        return True

    @staticmethod
    def is_active():
        return True

    @staticmethod
    def is_anonymous():
        return False

    def is_admin(self):
        return 'admin' in self.roles

    def get_id(self):
        return str(self.userid)

    # handle roles
    def set_role(self, role):
        self.roles.add(role)
        self.save_data()

    def has_role(self, role):
        return role in self.roles

    def _save_data(self):
        data = {
            'userid': self.userid,
            'roles': self.roles
        }
        with open(self.filename, "w+b") as f:
            pickle.dump(data, f, protocol = 2)

    def save_data(self):
        with self.file_access_lock:
            self._save_data()

    @staticmethod
    def load_user(userid):
        return User(userid)

    @staticmethod
    def create_filename(userid):
        """
        Makes a safe filename based on the user ID
        """
        filename = "_user_" + commonl.mkid(userid)
        return os.path.join(User.state_dir, filename)

    @staticmethod
    def search_user(userid):
        try:
            return User(userid, fail_if_new = True)
        except:
            return None


class local_user(User):
    """Define a local anonymous user that we can use to skip
    authentication on certain situations (when the user starts the
    daemon as such, for example).

    See https://flask-login.readthedocs.org/en/latest/#anonymous-users for
    the Flask details.

    """
    def __init__(self, **kwargs):
        self.userid = 'local'
        self.roles = set(('user', 'admin'))

    def save_data(self):
        pass

    def is_authenticated(self):
        # For local user, we consider it authenticated
        return True

    def is_anonymous(self):
        # For local user, we consider it not anonymous
        return False

    def is_active(self):
        return True

    def is_admin(self):
        return True
