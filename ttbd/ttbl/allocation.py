#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
"""

import errno
import logging
import os
import time
import werkzeug

try:
    import functools32
except ImportError as e:
    try:
        import backports.functools_lru_cache as functools32
    except ImportError as e:
        logging.error("Can't import neither functools32 nor backports.functools_lru_cache")
        raise

import commonl
import ttbl
import ttbl.config
import ttbl.user_control

path = None

class exception(Exception):
    pass

class invalid_e(exception):
    def __init__(self, allocationid):
        exception.__init__(
            self, "%s: non-existing allocation" % allocationid)

states = {
    "invalid": "allocation is not valid (might have expired)",
    "queued": "allocation is queued",
    "rejected": "allocation of %(targets)s not allowed: %(reason)s",
    "active": "allocation is being actively used",
    # one of your targets was kicked out and another one assigned on
    # its place, so go call GET /PREFIX/allocation/ALLOCATIONID to get
    # the new targets and restart your run
    "restart-needed": "allocation has been changed by a higher priority allocator",
    "expired": "allocation idle timer has expired and has been revoked",
}

class one_c(object):

    def __init__(self, allocationid, dirname):
        self.path = dirname
        self.allocationid = allocationid
        if not os.path.isdir(path):
            raise invalid_e(allocationid)

    def timestamp(self):
        # Just open the file and truncate it, so if it does not exist,
        # it will be created.
        with open(os.path.join(self.state_dir, "timestamp"), "w") as f:
            f.write(time.strftime("%c\n"))

    def set(self, field, value):
        if value != None:
            assert isinstance(value, str)
            assert len(value) < 1023
        location = os.path.join(self.path, field)
        if value == None:
            try:
                os.unlink(location)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
        else:
            # New location, add a unique thing to it so there is no
            # collision if more than one process is trying to modify
            # at the same time; they can override each other, that's
            # ok--the last one wins.
            location_new = location + "-%s-%s-%s" \
                % (os.getpid(), self.uuid_seed, time.time())
            commonl.rm_f(location_new)
            os.symlink(value, location_new)
            os.rename(location_new, location)

    def get(self, field, default = None):
        location = os.path.join(self.path, field)
        try:
            return os.readlink(location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return default
            raise


def target_is_valid(target_name):
    # FIXME: validate with the inventory
    # FIXME: LRU cache this? target's won't change that much
    return True


#@functools32.lru_cache(maxsize = 200)
#def get

def request(groups, user, obo_user,
            priority = None, preempt = False,
            queue = False, reason = None):
    """
    :params list(str) groups: list of groups of targets

    """
    assert isinstance(groups, dict)
    for group_name, target_list in list(groups.items()):
        assert isinstance(group_name, str)
        assert isinstance(target_list, list)
        # FIXME: verify not empty
        for target_name in target_list:
            assert isinstance(target_name, str)
            assert target_is_valid(target_name)

    user = user._get_current_object()
    obo_user = obo_user._get_current_object()
    assert isinstance(user, ttbl.user_control.User), \
        "user is %s (%s)" % (user, type(user))
    assert isinstance(obo_user, ttbl.user_control.User)

    if priority != None:
        assert priority > 0
        # FIXME: verify calling user has this priority
    else:
        priority = 500 # DEFAULT FROM USER

    assert isinstance(preempt, bool)
    assert isinstance(queue, bool)
    assert reason == None or isinstance(reason, str)

    allocationid = commonl.mkid(obo_user.get_id() + str(time.time()))

    dirname = os.path.join(path, allocationid)
    commonl.makedirs_p(dirname + "/guests")
    commonl.makedirs_p(dirname + "/groups")
    alloc = one_c(allocationid, dirname)

    alloc.set("user", obo_user.get_id())
    alloc.set("creator", user.get_id())
    alloc.timestamp()
    for group in groups:
        # FIXME: this is severly limited in size, we need a normal file to set this info with one target per file
        alloc.set("groups/" + group, " ".join(group))

    result = {
        # { 'busy', 'queued', 'allocated', 'rejected' },
        "state": 'rejected',
        "allocationid": allocationid,
        #"allocationid": None,    # if queued; derived from OWNER's cookie
        # "not allowed on TARGETNAMEs"
        # "targets TARGETNAMEs are busy"
        "message": "not implemented yet"
    }
    return result


def query():
    # list all allocations
    return {
        "result": {
            "ALLOCATIONID": {
                # "unknown", "allocated", "queued", "rejected"
                "state": "unknown",
                # "groupname": [ target1, target 2... ]	# if queued
                # "guests": [ "user1", "user2" ... ]	# if allocated
                # "user":"user1"			# if allocated, allocation owner
            }
        }
    }


def get(allocationid):
    return {
        # "unknown", "allocated", "queued", "rejected"
        "state": "unknown",
        # "groupname": [ target1, target 2... ]	# if queued
        # "guests": [ "user1", "user2" ... ]	# if allocated
        # "user":"user1"			# if allocated, allocation owner
    }


def keepalive(allocations):
    # {
    #     "allocationid1": state,
    #     "allocationid2": state,
    #     "allocationid3": state,
    #     ...
    # }
    # {
    #     "allocationid4": new_state,
    #     "allocationid3": new_state,
    #     ...
    # }
    return {}


def delete(allocationid):
    # if pending, remove all queuing of it
    # if allocated, release all targets
    return {
        # "unknown", "allocated", "queued", "rejected"
        "state": "unknown",
        # "groupname": [ target1, target 2... ]		# if queued
    }


def guest_add(allocationid, user):
    # verify user is valid
    return { }

def guest_remove(allocationid, user):
    # verify user is valid
    # verify user in allocation
    return { }
