#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
#  - reject messages to carry a 40x code?
#  - each target allocation carries a max TTL per policy
"""
Dynamic preemptable queue multi-resource allocator


Preemption use cases
^^^^^^^^^^^^^^^^^^^^

- Use case 1: queue for target with no preemption enabled

  queue: N O:500 1:450 2:400 3:350

  new waiter is added, 500P, whole thing is set to have preemption on

  queue: P O:500 1:500P 2:450 3:400 4:350

- Use case 2: (builds on 1)

  during a maintenance run (or other reason), prio of 1 is boosted by
  50; preemption kicks in, kicks out O

  queue: O:550  2:450 3:400 4:350


"""

import bisect
import collections
import errno
import json
import logging
import numbers
import pprint
import os
import re
import shutil
import tempfile
import time
import uuid
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

_allocationid_valid_regex = re.compile(r"^[_a-zA-Z0-9]+$")
# note this matches the valid characters that tmpfile.mkdtemp() will use
_allocationid_valid = set("_0123456789"
                          "abcdefghijklmnopqrstuvwxyz"
                          "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_queue_number_valid = set("0123456789")

# FIXME: consider defining these as constants so the state set can
# track missing stuff and make it harder to mess up, plus it'll do
# static checks
states = {
    "invalid": "allocation is not valid",
    "queued": "allocation is queued",
    "busy": "targets cannot be allocated right now and queuing not allowed",
    "removed": "allocation has been removed by the user",
    "rejected": "user has no privilege for this operation",
    "active": "allocation is being actively used",
    "overtime": "maximum time-to-live exceeded",
    # one of your targets was kicked out and another one assigned on
    # its place, so go call GET /PREFIX/allocation/ALLOCATIONID to get
    # the new targets and restart your run
    "restart-needed": "allocation has been changed by a higher priority allocator",
    "timedout": "allocation was idle for too long",
}

# FIXME: merge with fsdb_symlink_c
class symlink_set_c(object):

    class exception_e(Exception):
        pass

    class invalid_e(exception_e):
        pass

    def __init__(self, dirname, use_uuid = None, concept = "directory"):
        if not os.path.isdir(dirname):
            raise self.invalid_e("%s: invalid %s"
                                 % (os.path.basename(dirname), concept))
        self.dirname = dirname
        # FIXME: need to give seed here the PID/TID
        if use_uuid == None:
            self.uuid = uuid.uuid4().hex
        else:
            self.uuid = use_uuid

    def get_as_slist(self, *patterns):
        fl = []
        for _rootname, _dirnames, filenames in os.walk(self.dirname):
            if patterns:	# that means no args given
                use = []
                for filename in filenames:
                    if commonl.field_needed(filename, patterns):
                        use.append(filename)
            else:
                use = filenames
            for filename in use:
                if os.path.islink(os.path.join(self.dirname, filename)):
                    bisect.insort(fl, ( filename, self.get(filename) ))
        return fl


    def set(self, field, value, force = False):
        location = os.path.join(self.dirname, field)
        if value != None:
            # the storage is always a string, so encode what is not as
            # string as T:REPR, where T is type (b boolean, n number,
            # s string) and REPR is the textual repr, json valid
            if isinstance(value, numbers.Integral):
                # sadly, this looses precission in floats. A lot
                value = "i:%d" % value
            elif isinstance(value, numbers.Real):
                # sadly, this can loose precission in floats--FIXME:
                # better solution needed
                value = "f:%.10f" % value
            elif isinstance(value, bool):
                value = "b:" + str(value)
            elif isinstance(value, basestring):
                if value.startswith("i:") \
                   or value.startswith("f:") \
                   or value.startswith("b:") \
                   or value.startswith("s:") \
                   or value == "":
                    value = "s:" + value
            else:
                raise ValueError("can't store value of type %s" % type(value))
            assert len(value) < 1023
        if value == None:
            try:
                os.unlink(location)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            return True	# already wiped by someone else
        if force == False:
            try:
                os.symlink(value, location)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                # ignore if it already exists
                return False
            return True

        # New location, add a unique thing to it so there is no
        # collision if more than one process is trying to modify
        # at the same time; they can override each other, that's
        # ok--the last one wins.
        location_new = location + "-" + str(os.getpid())
        commonl.rm_f(location_new)
        os.symlink(value, location_new)
        os.rename(location_new, location)
        return True

    def get(self, field, default = None):
        location = os.path.join(self.dirname, field)
        try:
            value = os.readlink(location)
            # if the value was type encoded (see set()), decode it;
            # otherwise, it is a string
            if value.startswith("i:"):
                return json.loads(value.split(":", 1)[1])
            if value.startswith("f:"):
                return json.loads(value.split(":", 1)[1])
            if value.startswith("b:"):
                return bool(value.split(":", 1)[1])
            if value.startswith("s:"):
                # string that might start with s: or empty
                return value.split(":", 1)[1]
            return value	# other string
        except OSError as e:
            if e.errno == errno.ENOENT:
                return default
            raise

import ctypes
import ctypes.util

class ctype_timeval(ctypes.Structure):
    _fields_ = [
        ('tv_sec', ctypes.c_long),
        ('tv_usec', ctypes.c_long)
    ]

libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('libc'))
libc_lutimes = libc.lutimes
libc_lutimes.restype = ctypes.c_int
libc_lutimes.argtypes = [ ctypes.c_char_p, ctype_timeval * 2 ]

def lutime(filename, mtime, atime):
    times = (ctype_timeval * 2)()
    # access:
    times[0].tv_sec = mtime
    times[0].tv_usec = 0
    # modification:
    times[1].tv_sec = atime
    times[1].tv_usec = 0

    return libc_lutimes(filename, times)

class allocation_c(symlink_set_c):
    # FIXME: rethink all this class, not really needed?

    def __init__(self, allocationid, dirname):
        symlink_set_c.__init__(self, dirname, "allocation")
        self.path = dirname
        self.allocationid = allocationid

    def state_set(self, new_state):
        """
        :returns *True* if succesful, *False* if it was set by someone
          else
        """
        current_state = self._state_get()
        try:
            # Rename is a POSIX atomic operation that will override
            # the destination; we are banking on state.OLD ->
            # state.NEW being atomic and if someone has done it behind
            # our back, then state.OLD will not exist so the whole
            # operation will fail
            os.rename(os.path.join(self.path, current_state),
                      os.path.join(self.path, "state." + new_state))
            return True
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            # ignore if it already exists
            return False

    def _state_get(self):
        statel = self.get_as_slist("state.*")
        allocationid = self.allocationid
        if len(statel) > 1:
            _delete(self, "invalid")
            raise RuntimeError(
                "BUG: %s: more than one state found (%s);"
                " invalid, killing reservation"
                % (allocationid, [ x[0] for x in statel ]))
        if len(statel) == 0:
            _delete(self, "invalid")
            raise RuntimeError(
                "BUG: %s: no state found; invalid, killing reservation"
                % allocationid)
        return statel[0][0]

    def state_get(self):
        state = self._state_get()
        return state[6:]

    def timestamp(self):
        ts = time.strftime("%Y%m%d%H%M%S")
        self.set('timestamp', ts, force = True)
        return ts

    def timestamp_get(self):
        return self.get('timestamp')

    @classmethod
    @functools32.lru_cache(maxsize = 500)
    def get_from_cache(cls, allocationid):
        global path
        return allocation_c(allocationid,
                            os.path.join(path, allocationid))


def _check_is_user_creator_admin(db, user):
    # to query you must be user, creator or active guest
    userid = user.get_id()
    if userid == db.get("user") or userid == db.get("creator") \
       or user.is_admin():
        return True
    return False

def _check_is_guest(db, user):
    assert isinstance(user, basestring)
    guestid = commonl.mkid(user, l = 4)
    if db.get("guest." + guestid) == user:
        return True
    return False

def _check_query_permission(db, user):
    assert isinstance(user, ttbl.user_control.User)
    # to query you must be user, creator or active guest
    if _check_is_user_creator_admin(db, user):
        return True
    if _check_is_guest(db, user.get_id()):
        return True
    return False

def _to_dict(db, allocationid):
    d = {
        "state": db.state_get(),
        "user": db.get("user"),
        "creator": db.get("creator"),
    }
    reason = db.get("reason", None)
    if reason:
        d[reason] = reason
    guests = []
    for _id, name in db.get_as_slist("guest.*"):
        guests.append(name)
    if guests:
        d['guests'] = guests
    if d['state'] == 'active':
        d['targets'] = db.get('state.active')

    targets_all, groups = _target_groups(db, allocationid)
    d['targets_all'] = list(targets_all)
    d['target_group'] = {}
    for group_name, group in groups.iteritems():
        d['target_group'][group_name] = list(group)
    return d

def target_is_valid(target_name):
    # FIXME: validate with the inventory
    # FIXME: LRU cache this? target's won't change that much
    return target_name in ttbl.config.targets



target_db = None

def init():
    global target_db
    commonl.makedirs_p(path)
    target_db = symlink_set_c(ttbl.config.state_path, "target")


def request(groups, calling_user, obo_user, guests,
            priority = None, preempt = False,
            queue = False, shared = False,
            reason = None):
    """
    :params list(str) groups: list of groups of targets

    """

    #
    # Verify the groups argument
    #
    assert isinstance(groups, dict)		# gotta be a dict
    targets_all = set()
    groups_by_target_set = {}
    groups_clean = {}
    groups_clean_str = {}
    for group_name, target_list in groups.items():
        assert isinstance(group_name, basestring)	# name typing
        assert isinstance(target_list, list)		# target list...
        for target_name in target_list:			# ... of valid ones
            assert isinstance(target_name, basestring)
            if not target_is_valid(target_name):
                return {
                    "state": "rejected",
                    "message": "target %s in group '%s' does not exist" % (
                        target_name, group_name
                    )
                }

        # now check list is unique for each group (no two groups with
        # the same list, in maybe different orders)
        target_set = set(target_list)
        if len(target_set) < len(target_list):
            duplicates = target_set.difference(target_list)
            return {
                "state": "rejected",
                "message": "targets %s in group '%s' are duplicated" % (
                    ",".join(duplicates), group_name
                )
            }

        targets_all |= target_set
        # now check there is no group already defined in this
        # reservation for that list of trargets
        target_set_str = ",".join(target_set)
        original_group = groups_by_target_set.get(target_set_str, None)
        if original_group != None:
            return {
                "state": "rejected",
                "message": "targets in group '%s' are the same as in '%s'" % (
                    group_name, original_group
                )
            }
        groups_by_target_set[target_set_str] = group_name
        groups_clean[group_name] = target_set
        groups_clean_str[group_name] = target_set_str

    # Extract the creator and user that will own the reservation; the
    # creator might be different; privileges are granted to the
    # creator on behalf of the user
    assert isinstance(calling_user, ttbl.user_control.User)
    assert isinstance(obo_user, basestring)

    # Extract the guests
    assert isinstance(guests, list)
    count = 0
    for guest in guests:
        if not isinstance(guest, basestring):
            return {
                "state": "rejected",
                "message": "guest #%d in the guest lists must" \
                           " described by a string; got %s" \
                           % (count, type(guest).__name__)
            }
        count += 1

    if priority != None:
        priority_min = 0
        priority_max = 9999
        if priority < priority_min or priority > priority_max:
            return {
                "state": "rejected",
                "message": "invalid priority %d (expected %d-%d)" % (
                    priority, priority_min, priority_max)
            }
        # FIXME: verify calling user has this priority
    else:
        priority = 50 # FIXME: DEFAULT FROM POLICY
    # give us three digits of subpriorities
    priority *= 1000

    assert isinstance(preempt, bool)
    assert isinstance(queue, bool)
    assert reason == None or isinstance(reason, basestring)

    # Create an allocation record and from there, get the ID -- we
    # abuse python's tempdir making abilities for it
    allocationid_path = tempfile.mkdtemp(dir = path, prefix = "")
    allocationid = os.path.basename(allocationid_path)

    db = allocation_c.get_from_cache(allocationid)

    db.set("priority", priority)
    db.set("user", obo_user)
    db.set("creator", calling_user.get_id())
    for guest in guests:
        _guest_set(db, guest)

    ts = db.timestamp()
    db.set('state.queued', "timestamp")
    # FIXME: this is severly limited in size, we need a normal file to
    # set this info with one target per file
    db.set("targets_all", ",".join(targets_all))

    # At this point the allocation record is ready -- no target can
    # see it yet, so there is no danger the schedule() method will see it

    flags = "P" if preempt else "N"
    flags += "S" if shared else "E"
    for group, targets in groups_clean_str.items():
        # FIXME: this is severly limited in size, we need a normal
        # file to set this info with one target per file
        db.set("group." + group, targets)
        for target in groups_clean[group]:
            # FIXME: can we queue on this target? otherwise append to
            # rejected targets and cleanup

            # on each target, enter in the queue a link to the
            # timestamp file; name it PRIORITY-TIMESTAMP-FLAGS-ALLOCID
            #
            # PRIORITY is what help us short who will get it first;
            # highest wins, always 6 characters -- 0-999 * 1000 is the
            # user given priority; the extra three are to add a
            # subpriority to avoid starvation; we modify the priority
            # every T seconds with the allocation's prio speed value,
            # which gets modified from the keepalive's pressure
            # argument and it also increases as the age of the
            # allocation increases (calculated from the TIMESTAMP in
            # the name)
            #
            # TIMESTAMP is the time when the allocationid was created
            # (vs the ALLOCATIONID/timestamp field which we use to
            # mark keepalives); allows to:
            #
            #   (a) first-come-first-serve sort two allocations with
            #       the same priority
            #
            #   (b) calculate the age of an allocation to increase the
            #       prio speed to avoid starvation
            #
            #   (c) adjust the priority up or down based on pressure
            #       feedback during keepalive
            #
            # FLAGS are a sequence of ONE letters
            #
            #  - P or N: Preemption or no preemtion
            #
            #  - S or E: Shared or Exclusive; currently only Exclusive
            #    supported
            #
            # We don't use the GROUPNAME--if multiple groups of the
            # same allocation are trying to allocate the same target,
            # we want to share that position in the queue
            target_db.set(
                target + "/queue/%06d-%s-%s-%s" % (
                    priority, ts, flags, allocationid),
                "../../allocations/" + allocationid + "/timestamp")

    _run(targets_all, preempt)

    state = db.state_get()
    if queue == False and state != 'active':
        _delete(db, None)
        return  {
            "state": "busy",
            "message": states['busy']
        }

    result = {
        "state": state,
        "allocationid": allocationid,
        "message": states[state],
    }
    return result

def query(user_calling):
    assert isinstance(user_calling, ttbl.user_control.User)
    result = {}
    for _rootname, allocationids, _filenames in os.walk(path):
        #logging.error("DEBUG allocationids %s", allocationids)
        for allocationid in allocationids:
            # FIXME: check they match valid pattern
            #logging.error("DEBUG allocationid %s", allocationid)
            db = allocation_c.get_from_cache(allocationid)
            if not _check_query_permission(db, user_calling):
                continue
            result[allocationid ] = _to_dict(db, allocationid)
        return result	# only want the toplevel, thanks


def get(allocationid, user_calling):
    assert isinstance(user_calling, ttbl.user_control.User)
    db = allocation_c.get_from_cache(allocationid)
    if not _check_query_permission(db, user_calling):
        return {
            # could also just return invalid
            "message": "not allowed to read allocation"
        }
    return _to_dict(db, allocationid)


def keepalive(allocationid, expected_state, pressure, user_calling):
    """

    :param int pressure: how my system is doing so I might be able or
      not to take the extra job of the next allocation, so up and down
      my prio based on N -- this might move my allocations to lower
      priority if I know I won't be able to use them when I get them

    """
    assert isinstance(user_calling, ttbl.user_control.User), \
        "user_calling is unexpected type %s" % type(user_calling)
    db = None
    try:
        db = allocation_c.get_from_cache(allocationid)
    except allocation_c.invalid_e:
        return dict(state = "invalid", message = states['invalid'])
    if not _check_is_user_creator_admin(db, user_calling):
        # guests are *NOT* allowed to keepalive
        return dict(state = "rejected", message = states['rejected'])
    db.timestamp()	# first things first
    # FIXME: enforce starvation
    state = db.state_get()
    r = dict(state = state)
    if state == "active" and expected_state != 'active':
        r['targets'] = db.get("group")	# set in _run_target()
    return r

def _allocationid_link_validate(link_path):
    # given a owner link STATEDIR/TARGETNAME/owner that points to
    # ../../allocations/ALLOCATIONID/timestamp
    #
    # validate it is ok (timestamp file has to exist) and return the
    # ALLOCATIONID
    try:
        #logging.error("DEBUG link_path %s", link_path)
        os.readlink(link_path)
        normpath = os.path.normpath(link_path)
        allocation_path = os.path.dirname(normpath)
        allocationid = os.path.basename(allocation_path)
        return allocationid
    except OSError:
        # FIXME: downgrade, since this might refer to an
        # allocation that has been deleted
        return None

def _owner_link_validate(link_path):
    # FIXME: same as _allocationid_link_validate
    # given a owner link STATEDIR/TARGETNAME/owner that points to
    # ../../allocations/ALLOCATIONID/timestamp
    #
    # validate it is ok (timestamp file has to exist) and return the
    # ALLOCATIONID
    try:
        #logging.error("DEBUG link_path %s", link_path)
        os.readlink(link_path)
        normpath = os.path.normpath(link_path)
        allocation_path = os.path.dirname(normpath)
        allocationid = os.path.basename(allocation_path)
        return allocationid
    except OSError as e:
        # FIXME: downgrade, since this might refer to an
        # allocation that has been deleted
        return None

def _queue_file_validate(queue_path, filename):
    filepath = os.path.join(queue_path, filename)
    while True:
        try:
            # this will read ../../allocations/ALLOCATIONID/state
            dest = os.readlink(filepath)
        except OSError:
            # not even a symlink?...scoffs...
            logging.error("ALLOC: %s: removing invalid file (not symlink)",
                          filepath)
            break
        # is it pointing to a valid allocation?
        allocationid_linked = None
        try:
            # this shall be the state path, and it
            # has to exist
            # STATEDIR/TARGETNAME/queue/ ../../allocations/ALLOCATIONID/state
            # -> STATEDIR/allocations/ALLOCATIONID/state
            state_path = os.path.normpath(os.path.join(queue_path, dest))
            # it has to be a symlink, otherwise it is corrupted
            os.readlink(state_path)
            # STATEDIR/allocations/ALLOCATIONID/state
            # -> STATEDIR/allocations/ALLOCATIONID
            # -> ALLOCATIONID
            allocation_path = os.path.dirname(state_path)
            allocationid_linked = os.path.basename(allocation_path)
        except OSError as e:
            # FIXME: downgrade, since this might refer to an
            # allocation that has been deleted
            logging.error("ALLOC: %s: removing invalid file"
                          " (not pointing to a valid allocation: %s",
                          filename, e)
            break
        # could use a regex to validate this, but the fields are
        # so simple...
        fieldl = filename.split("-")
        if len(fieldl) != 4:
            logging.info("ALLOC: removed bad queue file %s", filename)
            break
        prio = fieldl[0]
        ts = fieldl[1]
        flags = fieldl[2]
        allocationid = fieldl[3]
        if len(prio) != 6 or set(prio) - _queue_number_valid:	# set in request()
            logging.info("ALLOC: %s: invalid priority %s", filepath, prio)
            break
        if len(ts) != 14 or set(ts) - _queue_number_valid:	# set in request()
            logging.info("ALLOC: %s: invalid timestamp %s", filepath, ts)
            break
        if len(flags) != 2 \
           or flags[0] not in [ 'P', 'N' ] \
           or flags[1] not in [ 'S', 'E' ]:
            logging.info("ALLOC: %s: invalid flags %s", filepath, flags)
            break
        if len(allocationid) != 6 or set(allocationid) - _allocationid_valid:
            logging.info("ALLOC: %s: invalid allocationid %s",
                         filepath, allocationid)
            break
        if allocationid != allocationid_linked:
            logging.info("ALLOC: %s: invalid expected allocationid %s",
                         filepath, allocationid)
            break
        return int(prio), ts, flags, allocationid

    os.unlink(os.path.join(queue_path, filename))
    return None, None, None, None

def _queue_load(queue_path):
    for _rootname, dirnames, filenames in os.walk(queue_path):
        for dirname in dirnames:
            # cleanup, this should not be here
            logging.error("%s: removing extraneous directory", dirname)
            commonl.rm_f(dirname)
        # sort alphabetically -- the format is so that a reverse
        # alphabetical sort gives us  the highest prio first and
        # within the same prio, sorted by the allocation creation
        # time.
        waiters = []
        preempt = False
        for filename in filenames:
            # could use a regex to validate this, but the fields are
            # so simple...
            prio, ts, flags, allocationid = \
                _queue_file_validate(queue_path, filename)
            if prio == None:	# bad entry, killed
                continue
            if 'P' in flags:
                preempt = True
            bisect.insort(waiters, ( prio, ts, flags, allocationid,
                                     filename ))
        return waiters, preempt
    # no waiters
    return None, None

def _starvation_recalculate(allocationid, target):
    logging.error("FIXME: not implemented")


@functools32.lru_cache(maxsize = 500)
def _target_groups(db, _allocationid):
    # FIXME: cached, needed because when we wrote it it was on process
    # #1, this might be process #N
    # Note the groups don't change after the thing is created, so it
    # is ok to cache it
    # FIXME: need to add allocation name so it doesn't cache by database
    groups = {}
    targets_all = set()
    for group_name, val in db.get_as_slist("group.*"):
        targets_group =  set(val.split(','))
        groups[group_name[6:]] = targets_group
        targets_all |= targets_group
#    logging.error("DEBUG: _target_groups(%s, %s) = %s",
#                  db, _allocationid, pprint.pformat(groups))
    return targets_all, groups


def _target_owner_get(target):
    # FIXME: this needs to be more efficient, we keep recalculating
    # it, bring it from ttbl.config.targets[target_name].state_path
    target_path = os.path.join(ttbl.config.state_path, target)
    current_owner = target_db.get(target + "/owner")
    if current_owner:
        if _allocationid_link_validate(
                os.path.join(target_path, current_owner)) == None:
            # owner was invalid and cleaned up;  allocation might been
            # removed; fall through
            # FIXME: race condition, similar to the one for preempt
            target_db.set(target + "/owner", None)
        else:
            return current_owner
    return None

def _target_deallocate(target, allocationid):
    # if target is owned by allocationid, release it
    # FIXME: this needs to be more efficient, we keep recalculating
    # it, bring it from ttbl.config.targets[target_name].state_path
    target_path = os.path.join(ttbl.config.state_path, target)
    current_owner = target_db.get(target + "/owner")
    if current_owner:
        if _allocationid_link_validate(
                os.path.join(target_path, current_owner)) == allocationid:
            # owner was invalid and cleaned up;  allocation might been
            # removed; fall through
            # FIXME: race condition, similar to the one for preempt
            target_db.set(target + "/owner", None)
        else:
            return current_owner
    return None


def _run_target(target, preempt):
    # preempt: True/False if enabled, when we find the current owner
    #   of the target's effective priority is lower than the first one
    #   in the queue, The intent of this is to remove any priority
    #   inversion that could be created by having a lower priority
    #   owner block higher priority ones when any of them has queed
    #   with preemption enabled.
    #
    #   *True* called only when calling off request() and the request
    #   has preemption enabled; other calls can use *False*.
    #
    #
    target_path = os.path.join(ttbl.config.state_path, target)
    queue_path = os.path.join(target_path, "queue")
    while True:
        waiters, preempt_in_queue = _queue_load(queue_path)
        #logging.error("DEBUG: %s: allocator, path %s waiters %s",
        #              target, queue_path, waiters)
        if not waiters:
            return
        preempt = preempt_in_queue or preempt
        #logging.error("DEBUG: %s: allocator, preempt %s", target, preempt)
        # so, now it is quite simple, the first entry who made
        # it here is the highest priority in the list, so
        # let's check the current target owner -- if the
        # current target owner has less prio that this one,
        # then we delete it and create a new owner lock.

        # If in the meantime another process has set the
        # owner, we just backoff and repeat the checking process

        # when an owner is assigned to the target, its
        # effective priority is recorded in the target object
        # (as the effective priority the owner had when the
        # target was acquired)

        priority_waiter = waiters[-1][0]
        # get and validate the owner (maybe wipe it if invalid)
        current_owner = _target_owner_get(target)
        if current_owner == None:
            # No owner, fall through; let's try to get it
            pass
        else:
            # Ok, we have what seems to be a valid owner
            priority_target = target_db.get(target + "/priority", None)
            if priority_target == None:
                # backoff, try again: there is an owner recorded, but no
                # priority, which means the ownership record is half
                # updated by some other thread
                logging.error("DEBUG: %s: allocator, back off, "
                              "priority_target None but current_owner %s",
                              target, current_owner)
                time.sleep(0.1)
                continue
            logging.error("DEBUG: %s: current_owner %s, prios target %s waiter %s",
                          target, current_owner, priority_target, priority_waiter)
            if priority_waiter > priority_target:
                if preempt:
                    # A lower priority owner has the target, a higher priority
                    # one is waiting and preemption is enabled; the lower prio
                    # holder gets booted out.
                    # FIXME: race condition: if someone has done
                    # this check in the middle, we toast
                    logging.error("DEBUG: %s: preemption, removing owner", target)
                    target_db.set(target + "/owner", None)
                    # fallthrough
                else:
                    logging.error("DEBUG: %s: busy w lower prio owner, but no preemption", target)
                    return
            else:
                # a higher prio owner has the target
                logging.error("DEBUG: %s: busy prio owner %d waiter %d",
                              target, priority_target, priority_waiter)
                return

        allocationid = waiters[-1][3]
        # try to assign the first waiter as owner; if the target is
        # owned by someone (the owner field already exist) it
        # will fail to update and just return False...so then
        # we leave it for the next run
        this_owner = "../allocations/" + allocationid + "/timestamp"
        logging.error("DEBUG: %s: assigining %s", target, this_owner)
        if target_db.set(target + "/owner", this_owner,
                         force = False) == False:
            # failed to update, this means there is a new
            # owner allocated, so next time
            # FIXME: calculate adjustments
            logging.error("DEBUG: %s: assigining %s failed", target, this_owner)
            _starvation_recalculate(allocationid, target)
            return
        # remove the waiter from the queue
        target_db.set(target + "/queue/" + waiters[-1][4], None)

        # ** This waiter is the owner now **
        #
        # update the priority--anyone who came in a parallel process
        # and saw no priority was set will wait and retry
        target_db.set(target + "/priority", priority_waiter)
        logging.error("DEBUG: %s: owner assigned, updating prio", target)

        # now we need to compute if this makes all the targets
        # needed for any of the groups in the allocationid
        db = allocation_c.get_from_cache(allocationid)
        # note these groups are specific to the allocationid, and they
        # are cached anyway--so it is fast
        targets_all, groups = _target_groups(db, allocationid)
        targets_allocated = set()
        for target_itr in targets_all:
            current_owner = _target_owner_get(target_itr)
            if current_owner == this_owner:
                targets_allocated.add(target_itr)
        logging.error("DEBUG: target allocated: %s", target)
        # FIXME: race condition? what happens if another process is
        # doing the same thing now?
        groups_incomplete = []
        for name, group in groups.iteritems():
            not_yet_allocated = group - targets_allocated
            if not_yet_allocated:
                # this group has still targets not allocated, will
                # have to do starvation recalculation later
                score = float(len(targets_allocated)) / len(group)
                bisect.insort(
                    groups_incomplete,
                    # calculate the percentage of the targets needed
                    # for each group that are allocated, this will be
                    # used later to boost prio of the missing ones
                    ( score, name )
                )
                logging.error("DEBUG: group %s incomplete, score %f [%d/%d]",
                              name, score, len(targets_allocated), len(group))
            else:
                logging.error("DEBUG: group %s complete", name)
                # all targets needed for this group have been
                # allocated, let's then use it--if we set the "group"
                # value, then we have it allocated
                target_group = ",".join(group)
                if db.set("group", target_group, force = False) == False:
                    # Ooops! conflict, another process already decided
                    # a group for us, back off
                    logging.error("DEBUG: backoff active setting")
                    return
                # release targets not in the group we allocated on the
                # way here
                targets_to_release = targets_allocated - group
                for target_name in targets_to_release:
                    _target_deallocate(target_name, allocationid)
                db.state_set("active")
                return

        # targets missing, so let's see we have to add starvation
        # control
        target_scores = collections.defaultdict(int)
        for score, _group_name in groups_incomplete:
            for target_name in not_yet_allocated:
                target_scores[target_name] = \
                    min(score, target_scores[target_name])
        for target_name, score in target_scores.items():
            logging.error(
                "FIXME: _starvation_recalculate(%s, %s)",
                allocationid, target_name
            )
        return

    assert True, "I should not be here"


def _run(target_list, preempt):
    if target_list == None:
        logging.error("FIXME: not sure this is really needed")
        target_list = ttbl.config.targets.keys()

    for target in target_list:
        _run_target(target, preempt)

def _maintenance_allocationid(ts_now, db, allocationid):
    logging.error("DEBUG: maint %d %s", ts_now, allocationid)
    ts_last_keepalive = int(db.timestamp_get())
    if ts_now - ts_last_keepalive > ttbl.config.target_max_idle:
        logging.error("DEBUG: %d: allocation %s timedout, deleting",
                      ts_now, allocationid)
        _delete(db, 'timedout')
        return
    ttl = int(db.get("ttl", "0"))
    if ttl > 0:
        # FIXME: we need to record ts_start
        ts_start = int(db.get('ts_start'))
        if ts_now - ts_start > ttl:
            logging.error("DEBUG: %s: allocation expired",
                          allocationid)
            _delete(db, 'overtime')
            return

def maintenance(t, user_calling):
    # this will be called by a parallel thread / process to run
    # cleanup activities, such as:
    #
    # - enforcing idle timeouts
    # - enforcing max allocation times
    # - removing stale records
    # - increase effective priorities to avoid starvation
    # - when priorities change, maybe reassign ownerships if
    #   preemption
    ts_now = int(time.strftime("%Y%m%d%H%M%S", time.localtime(t)))
    logging.error("DEBUG: maint %s", ts_now)
    assert isinstance(user_calling, ttbl.user_control.User)

    # expire allocations
    for _rootname, allocationids, _filenames in os.walk(path):
        for allocationid in allocationids:
            db = allocation_c.get_from_cache(allocationid)
            _maintenance_allocationid(ts_now, db, allocationid)
        break	# only want the toplevel, thanks

    # maint targets, do starvation control
    for target_name in ttbl.config.targets:
        # check each owner for validity, wipe it otherwise
        owner = _target_owner_get(target_name)
        #logging.error("DEBUG: maint target %s: %s", target_name, owner)
        if owner:
            # FIXME: starvation control
            pass
        else:
            # FIXME: check to power off
            pass

def _delete(db, _state):
    targets_all = db.get("targets_all")
    # wipe the whole tree--this will render all the records that point
    # to it invalid and the next _run() call will clean them
    shutil.rmtree(db.dirname, True)
    # FIXME: implement a DB of recently deleted reservations so anyone
    # trying to use it gets a state invalid/timedout/overtime/removed
    # release all queueing/owning targets
    if targets_all:
        _run(targets_all.split(","), False)	# clean state on targets

def delete(allocationid, user_calling):
    assert isinstance(allocationid, basestring)
    assert isinstance(user_calling, ttbl.user_control.User)
    db = allocation_c.get_from_cache(allocationid)

    userid = user_calling.get_id()
    if _check_is_user_creator_admin(db, user_calling):
        _delete(db, "removed")
        return {
            "state": "removed",
            "message": states['removed']
        }
    elif _check_is_guest(db, userid):
        # a guest is trying to delete, which just removes the user
        guestid = commonl.mkid(userid, l = 4)
        # same as guest_remove()
        db.set("guest." + guestid, None)
        return {
            "message": "%s: user removed from allocation" % userid
        }
    else:
        return {
            "message": "no permission to remove other's allocation"
        }


def _guest_set(db, guest):
    # we can't really validate if the user exists, because we
    # don't have their password to run it across the auth systems;
    # so we'll just record it's presence and if anyone auths as
    # that user, then ... it's ok
    #
    # we are making the almost reaonsable assumption that the number
    # of guests will be low (generally < 5) and thus a base32 ID space of
    # four digits will do more than enough to guarantee there is no
    # collissions. FLWs.
    guestid = commonl.mkid(guest, l = 4)
    db.set("guest." + guestid, guest)

def guest_add(allocationid, user_calling, guest):
    assert isinstance(user_calling, ttbl.user_control.User)
    if not isinstance(guest, basestring):
        return {
            "state": "rejected",
            "message": "guest must be described by a string; got %s" \
            % type(guest).__name__
        }
    assert isinstance(allocationid, basestring)
    db = allocation_c.get_from_cache(allocationid)
    # verify user is owner/creator
    if not _check_is_user_creator_admin(db, user_calling):
        # guests are *NOT* allowed to set more guests
        return { "message": "not allowed to set guests in allocation" }
    _guest_set(db, guest)
    return {}

def guest_remove(allocationid, user_calling, guest):
    assert isinstance(user_calling, ttbl.user_control.User)
    if not isinstance(guest, basestring):
        return {
            "state": "rejected",
            "message": "guest must be described by a string;"
                       " got %s" % type(guest).__name__
        }
    assert isinstance(allocationid, basestring)
    db = allocation_c.get_from_cache(allocationid)
    guestid = commonl.mkid(guest, l = 4)
    if user_calling.get_id() != guest \
       and not _check_is_user_creator_admin(db, user_calling):
        return { "message": "not allowed to remove guests from allocation" }
    # just wipe the guestid, ignore if it didn't exist (same as delete/guest)
    db.set("guest." + guestid, None)
    return {}

