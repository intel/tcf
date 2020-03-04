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
import errno
import json
import logging
import numbers
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
    "invalid": "allocation is not valid (might have expired)",
    "queued": "allocation is queued",
    "busy": "targets cannot be allocated right now and queuing not allowed",
    "removed": "allocation has been removed",
    "rejected": "allocation of %(targets)s not allowed: %(reason)s",
    "active": "allocation is being actively used",
    # one of your targets was kicked out and another one assigned on
    # its place, so go call GET /PREFIX/allocation/ALLOCATIONID to get
    # the new targets and restart your run
    "restart-needed": "allocation has been changed by a higher priority allocator",
    "expired": "allocation idle timer has expired and has been revoked",
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
            if isinstance(value, numbers.Real):
                # sadly, this can loose precission in floats--FIXME:
                # better solution needed

                value = "f:%.10f" % value
            elif isinstance(value, bool):
                value = "b:" + str(value)
            elif isinstance(value, basestring):
                if value.startswith("b:") \
                   or value.startswith("n:") \
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
        location_new = location + "-" + self.uuid
        commonl.rm_f(location_new)
        os.symlink(value, location_new)
        os.rename(location_new, field)
        return True

    def get(self, field, default = None):
        location = os.path.join(self.dirname, field)
        try:
            value = os.readlink(location)
            # if the value was type encoded (see set()), decode it;
            # otherwise, it is a string
            if value.startswith("b:"):
                return bool(value.split(":", 1)[1])
            if value.startswith("n:"):
              return json.loads(value.split(":", 1)[1])
            if value.startswith("s:"):
                return value.split(":", 1)[1]
            return value
        except OSError as e:
            if e.errno == errno.ENOENT:
                return default
            raise

if False:
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

    def timestamp(self):
        # FIXME: do lutime to set the symlink mtime
        state = self.get('state')
        set('state', state, force = True)

    def timestamp_get(self):
        # FIXME: get mtime 'state' link
        mtime = os.path.getmtime(os.path.join(self.dirname, "state"))
        return time.strftime("%Y%m%d%H%M%S", mtime)


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
        "state": db.get("state"),
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

    groups = _target_groups(db, allocationid)
    d['targets_all'] = list(groups.pop('all'))
    for name, group in groups.iteritems():
        if name == 'all':
            d['targets_all'] = list(group)
        else:
            d.setdefault('target_group', {})
            d['target_group'][name] = list(group)

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
                    "message": "targets %s in group '%s' does not exist" % (
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
        if priority >= priority_min and priority <= priority_max:
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

    db = allocation_c(allocationid, allocationid_path)

    db.set("priority", priority)
    db.set("user", obo_user)
    db.set("creator", calling_user.get_id())
    for guest in guests:
        _guest_set(db, guest)

    db.set('state', "queued")
    ts = time.strftime("%Y%m%d%H%M%S")
    # FIXME: this is severly limited in size, we need a normal file to
    # set this info with one target per file
    db.set("all_targets", ",".join(targets_all))

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
                "../../allocations/" + allocationid + "/state")

    _run(targets_all, preempt)

    state = db.get('state')
    #logging.error("DEBUG: queue %s state %s" % (queue, state))
    if queue == False and state != 'active':
        _delete(db)
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
            db = symlink_set_c(os.path.join(path, allocationid),
                               str(os.getpid()), "allocation")
            if not _check_query_permission(db, user_calling):
                continue
            result[allocationid ] = _to_dict(db, allocationid)
        return result	# only want the toplevel, thanks


def get(allocationid, user_calling):
    assert isinstance(user_calling, ttbl.user_control.User)
    db = symlink_set_c(os.path.join(path, allocationid),
                       str(os.getpid()), "allocation")
    if not _check_query_permission(db, user_calling):
        return {
            # could also just return invalid
            "message": "not allowed to read allocation"
        }
    return _to_dict(db, allocationid)


def keepalive(allocations, user_calling):
    assert isinstance(user_calling, ttbl.user_control.User)
    # {
    #     # optional: how my system is doing so I might be able or not
    #     # to take the extra job of the next allocation, so up and down
    #     # my prio based on N -- this might move my allocations to
    #     # lower priority if I know I won't be able to use them when I
    #     # get them
    #     "pressure": N,
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
    logging.error("FIXME: keepalive not implemented")
    return {
        "message": "FIXME: keepalive not implemented"
    }


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
            logging.error("ALLOC: %s: removing invalid file"
                          " (not pointing to a valid allocation: %s",
                          filename, e)
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
        for waiter in filenames:
            # could use a regex to validate this, but the fields are
            # so simple...
            prio, ts, flags, allocationid = \
                _queue_file_validate(queue_path, waiter)
            if prio == None:	# bad entry, killed
                continue
            if 'P' in flags:
                preempt = True
            bisect.insort(waiters, ( prio, ts, flags, allocationid ))
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
    groups['all'] = targets_all
    return groups


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
    queue_path = os.path.join(path, target, "queue")
    while True:
        waiters, preempt_in_queue = _queue_load(queue_path)
        if not waiters:
            return
        preempt = preempt_in_queue or preempt
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

        priority_target = target_db.get(target + "/priority", None)
        if priority_target == None \
           and target_db.get(target + "/owner") != None:
            # backoff, try again: there is an owner recorded, but no
            # priority, which means the ownership record is half
            # updated.
            time.sleep(0.1)
            continue
        priority_waiter = waiters[0][0]
        if preempt and priority_target < priority_waiter:
            # A lower priority owner has the target, a higher priority
            # one is waiting and preemption is enabled; the lower prio
            # holder gets booted out.
            # FIXME: unsolved race condition: if someone has done
            # this check in the middle, we toast
            target_db.set(target + "/owner", None)
        else:
            # a higher prio owner has the target
            return
        # try to assign the first as owner; if the target is
        # owned by someone (the owner field already exist) it
        # will fail to update and just return False...so then
        # we leave it for the next run
        this_owner = "../../allocations/" + allocationid + "/state"
        if target_db.set(target + "/owner", this_owner) == False:
            # failed to update, this means there is a new
            # owner allocated, so next time
            # FIXME: calculate adjustments
            _starvation_recalculate(allocationid, target)
            return

        # ** We are the owner now **
        #
        # update the priority--anyone who came in a parallel process
        # and saw no priority was set will wait and retry
        target_db.set(target + "/priority", priority_waiter)

        # FIXME: target is allocated! now we need to compute
        # if this makes all the targets needed for any of the
        # groups in the allocationid
        db = allocation_c(allocationid,
                          os.path.join(path, allocationid))
        groups = _target_groups(db, allocationid)
        targets_all = groups.pop('all')
        targets_allocated = set()
        for target_itr in targets_all:
            if target_db.get(target_itr + "owner") == this_owner:
                targets_allocated.add(target_itr)
        # FIXME: race condition? what happens if another process is
        # doing the same thing now?
        groups_incomplete = []
        for name, group in groups.iteritems():
            not_yet_allocated = group - targets_allocated
            if not_yet_allocated:
                # this group has still targets not allocated, will
                # have to do starvation recalculation later
                bisect.insort(
                    groups_incomplete,
                    ( len(not_yet_allocated), not_yet_allocated )
                )
            else:
                target_group = ",".join(group)
                if db.set("group", target_group, force = False) == False:
                    # Ooops! conflict, another process already decided
                    # a group for us, back off
                    return
                # FIXME: race condition? already set? -- makes more
                # sense to have a field named after the STATE and
                # another one for a timestamp so we can set this
                # without race conditioning and put the group in the
                # active field
                db.set('state', "active")
                # this group has them all allocated, lets use it!
        #_starvation_recalculate(allocationid, target)
        return

    assert True, "I should not be here"


def _run(target_list, preempt):
    if target_list == None:
        logging.error("DEBUG: not sure this is really needed")
        target_list = ttbl.config.targets.keys()

    for target in target_list:
        _run_target(target, preempt)


def maintenance():
    # this will be called by a parallel thread / process to run
    # cleanup activities, such as:
    #
    # - enforcing idle timeouts
    # - enforcing max allocation times
    # - removing stale records
    # - increase effective priorities to avoid starvation
    # - when priorities change, maybe reassign ownerships if
    #   preemption
    logging.error("FIXME: cleanup not implemented")


def _delete(db):
    all_targets = db.get("all_targets")
    # wipe the whole tree--this will render all the records that point
    # to it invalid and the next _run() call will clean them
    shutil.rmtree(db.dirname, True)
    # FIXME: if queued, remove all queuing of it if allocated,
    # release all targets
    if all_targets:
        _run(all_targets.split(","), False)	# clean state on targets

def delete(allocationid, user_calling):
    assert isinstance(allocationid, basestring)
    assert isinstance(user_calling, ttbl.user_control.User)
    db = symlink_set_c(os.path.join(path, allocationid),
                       str(os.getpid()), "allocation")

    userid = user_calling.get_id()
    if _check_is_user_creator_admin(db, user_calling):
        _delete(db)
        return {
            "state": "removed",
            "message": states['removed']
        }
    elif _check_is_guest(db, userid):
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
    db = symlink_set_c(os.path.join(path, allocationid),
                       str(os.getpid()), "allocation")
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
    db = symlink_set_c(os.path.join(path, allocationid),
                       str(os.getpid()), "allocation")
    guestid = commonl.mkid(guest, l = 4)
    if user_calling.get_id() != guest \
       and not _check_is_user_creator_admin(db, user_calling):
        return { "message": "not allowed to remove guests from allocation" }
    # just wipe the guestid, ignore if it didn't exist (same as delete/guest)
    db.set("guest." + guestid, None)
    return {}

