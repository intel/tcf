#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
#  - if I release targets from a reservation, they need to be removed
#    from the group list, so it is not confusing in the listing when I
#    get/alloc-ls
#  - reject messages to carry a 40x code?
#  - each target allocation carries a max TTL per policy
#  - starvation control missing
#  - forbid fsdb writing to alloc fields
#  - check lock order taking, always target or allocid,target
#  * LRU caches needs being able to invalidate to avoid data
#    contamination, consider https://pastebin.com/LDwMwtp8
#
# This is a simple priority queue allocator; the resource(s) to be
# allocated are groups of one or more targets.
#
# A user places a request for any of multiple targets by calling
# request().
#
# _run() implements the actual scheduler runs by calling _run_target()
#
# _run() is triggered by:
#  
#  - a new request()
#
#  - an allocation deleted [allocdb.delete()]
#
#  - periodically by the maintenance() process, which is called from
#    the system's cleanup thread
#
"""
Dynamic preemptable queue multi-resource allocator

Highest priority is 0, lowest priority is > 0

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
import datetime
import filelock
import logging
import os
import re
import shutil
import tempfile
import time
import uuid


import commonl
import ttbl
import ttbl.config
import ttbl.user_control

path = None

_allocid_valid_regex = re.compile(r"^[_a-zA-Z0-9]+$")
# note this matches the valid characters that tmpfile.mkdtemp() will use
_allocid_valid = set("_0123456789"
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

import collections
import time

# HACK: allow the allocation module to access the audit module, see
# ttbl.allocation.audit; proper fix is to move the audit layer to its
# own module. pending
audit = None

class lru_aged_c(object):
    # very basic, different types not considered, neither kwargs
    
    def __init__(self, fn, ttl, maxsize):
        self.cache = collections.OrderedDict()
        self.fn = fn
        self.ttl = ttl
        self.maxsize = maxsize

    def __call__(self, *args):	# FIXME: support kwargs
        timestamp = time.time()
        if args in self.cache:
            result, result_timestamp = self.cache[args]
            if result_timestamp - timestamp <= self.ttl:                
                # FIXME: python 3 self.cache.move_to_end(args)
                item = self.cache.pop(args)
                self.cache[args] = item
                return self.cache[args][0]
            # fallthrough, item is too old, refresh
        result = self.fn(*args)
        self.cache[args] = (result, timestamp)
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last = False)
        return result

    def cache_hit(self, args):
        return args in self.cache
    
    def invalidate(self, entry = None):
        if entry == None:
            del self.cache
            self.cache = collections.OrderedDict()
        elif entry in self.cache:
            del self.cache[entry]
    
class allocation_c(commonl.fsdb_symlink_c):
    """
    Backed by state in disk

    Move backend symlink_set_c -> impl so it can be transitioned to a
    Mongo or whatever
    """
    def __init__(self, allocid):
        dirname = os.path.join(path, allocid)
        commonl.fsdb_symlink_c.__init__(self, dirname, concept = "allocid")
        self.allocid = allocid
        # protects writing to most fields
        # - group
        # - state
        self.lock = filelock.FileLock(os.path.join(dirname, "lockfile"),
                                      timeout = 5)
        self.targets_all = None
        self.groups = None
        self.target_info_reload()

    @staticmethod
    def __init_from_cache__(allocid):
        # yeah, yeah, I could make lru_aged_c be smarter and know how
        # to call methods, but it's late        
        return allocation_c(allocid)

    def target_info_reload(self):
        # Note the information about the targets and groups doesn't
        # change once it is commited to the fsdb, so it is safe to
        # load it just once
        self.groups = {}
        self.targets_all = {}
        target_names_all = set()
        for group_name, val in self.get_as_slist("group.*"):
            target_names_group = set(val.split(','))
            self.groups[group_name[6:]] = target_names_group
            target_names_all |= target_names_group
        for target_name in target_names_all:
            try:
                self.targets_all[target_name] = ttbl.test_target.get(target_name)
            except KeyError:
                raise self.invalid_e(
                    "%s: target no longer available" % target_name)

    def delete(self, _state = "removed"):
        try:
            # if the reservation DB is messed up, this might fail --
            # it is fine, we will then just wipe it
            with self.lock:
                if self.state_get() == 'active':
                    targets = {}
                    for target_name in self.get("group_allocated").split(","):
                        target = ttbl.test_target.get(target_name)
                        targets[target_name] = target
                        target_allocid_current = target.allocid_get_bare()
                        if self.allocid != target_allocid_current:
                            # this target was originally in this
                            # allocation but has been moved to
                            # another, so do not release it
                            # TEST: test_allocation_removal_keeps_new_owner
                            target.log.info(
                                f"deleting {self.allocid}: won't release"
                                f" target since it is now part of allocation"
                                f" {target_allocid_current}")
                            continue
                        # cleanup each of the involved targets when
                        # active; this is a sum up of
                        # ttbl.test_target._deallocate()+
                        # _deallocate_simple(), since we know the
                        # steps are the same
                        target._state_cleanup(True)
                        target._allocid_wipe()
                else:
                    targets = self.targets_all
        finally:
            # wipe the whole tree--this will render all the records that point
            # to it invalid and the next _run() call will clean them
            shutil.rmtree(self.location, True)
            lru_aged_cache_allocation_c.invalidate(self.allocid)
        # FIXME: implement a DB of recently deleted reservations so anyone
        # trying to use it gets a state invalid/timedout/overtime/removed
        # release all queueing/owning targets to it
        if targets:
            _run(targets.values(), False)

    def set(self, *args, force = True, **kwargs):
        # we default to forcing
        return commonl.fsdb_symlink_c.set(
            self, *args, force = force, **kwargs)

    def state_set(self, new_state):
        """
        :returns *True* if succesful, *False* if it was set by someone
          else
        """
        assert new_state in states
        self.set('state', new_state, force = True)

    def state_get(self):
        return self.get('state')

    def timestamp(self):
        # 20200323113030 is more readable than seconds since the epoch
        # and we still can do easy arithmentic with it.
        ts = time.strftime("%Y%m%d%H%M%S")
        self.set('timestamp', ts, force = True)
        return ts

    def timestamp_get(self):
        # if there is no timestamp, forge the Epoch
        return self.get('timestamp', "19700101000000")

    def maintenance(self, ts_now):
        #logging.error("DEBUG: %s: maint %s", self.allocid, ts_now)

        # pull the endtime from the disk database
        endtime = self.get("endtime", None)

        if endtime == "static":
            # this allocaiton is supposed to end only by API
            # termination
            return

        if endtime != None:
            # this is supposed to be a timestap in YYYYmmddHHMMSS (we
            # have verified it already) -- if we are past that, snip
            # it
            # ts_now is datetime.datetime.now(), let's get endtime
            # datetime format
            ts_endtime = datetime.datetime.strptime(endtime, "%Y%m%d%H%M%S")
            if ts_endtime > ts_now:
                logging.info(
                    "ALLOC: allocation %s expired @%s, deleting",
                    self.allocid, endtime)
            if audit:
                # FIXME: this is really messy -- audit.record needs to be better
                _auditor = audit("unused")
                # it is possible there will be no user if this is
                # timing out, in which case, calling_user will be None
                # and the audit layer needs to handle it appropiatedly
                _auditor.record("allocation/expired",
                                calling_user = self.get("user"),
                                allocid = self.allocid)
            self.delete('expired')
            return

        # Check if it has been idle for too long
        ts_last_keepalive = datetime.datetime.strptime(self.timestamp_get(),
                                                       "%Y%m%d%H%M%S")
        ts_idle = ts_now - ts_last_keepalive
        seconds_idle = ts_idle.seconds
        # days might be < 0 when the maintenance process has started
        # and before we got here somebody timestamped the target, thus
        # ts_last_keepalive > ts_now -> in this case, we are good, it
        # is fresh
        if ts_idle.days >= 0 and seconds_idle > ttbl.config.target_max_idle:
            # FIXME: make this per allocation?
            logging.info(
                "ALLOC: allocation %s timedout (idle %s/%s), deleting",
                self.allocid, seconds_idle, ttbl.config.target_max_idle)
            if audit:
                # FIXME: this is really messy -- audit.record needs to be better
                _auditor = audit("unused")
                # it is possible there will be no user if this is
                # timing out, in which case, calling_user will be None
                # and the audit layer needs to handle it appropiatedly
                _auditor.record("allocation/timeout",
                                calling_user = self.get("user"),
                                allocid = self.allocid)
            self.delete('timedout')
            return

        # Check if it has been alive too long
        # FIXME: define well how are we going to define the TTL
        ttl = self.get("ttl", 0)
        if ttl > 0:
            ts_start = int(self.get('_alloc.timestamp_start'))
            if ts_now - ts_start > ttl:
                self.delete('overtime')
                return

    def calculate_stuff(self):
        # lock so we don't have two processes doing the same
        # processing after acquiring diffrent targets of our group the
        # same time
        with self.lock:
            # We need to know if we have completely allocated all of
            # the targets of any of the groups of targets this
            # allocid requested

            # Lookup all the targets this allocid has allocated
            targets_allocated = set()
            for target_name, target in self.targets_all.items():
                allocid = target.allocid_get_bare()
                if allocid == self.allocid:
                    targets_allocated.add(target_name)

            # Iterate all the groups, see which are incomplete; for
            # each target, collect their max boot score
            targets_to_boost = collections.defaultdict(int)
            for group_name, group in self.groups.items():
                not_yet_allocated = group - targets_allocated
                if not_yet_allocated:
                    # this group has still targets not allocated, will
                    # have to do starvation recalculation later
                    score = float(len(targets_allocated)) / len(group)
                    #logging.error(
                    #    "DEBUG: group %s incomplete, score %f [%d/%d]",
                    #    group_name, score, len(targets_allocated), len(group))
                    for target_name in not_yet_allocated:
                        targets_to_boost[target_name] = \
                            min(targets_to_boost[target_name], score)
                else:
                    # This group is complete, so we don't need the
                    # other targets tentatively allocated, so return
                    # the list so they can be released
                    # all targets needed for this group have been
                    # allocated, let's then use it--if we set the "group"
                    # value, then we have it allocated
                    # Sort here because everywhere else we need a set
                    self.set("group_allocated", ",".join(sorted(group)))
                    self.set("timestamp_start", time.time())
                    self.set("ts_start", time.time())	# COMPAT
                    self.state_set("active")
                    #logging.error("DEBUG: %s: group %s complete, state %s",
                    #              self.allocid, group_name,
                    #              self.state_get())
                    return {}, targets_allocated - group

            # no groups are complete, nothing else to do
            return targets_to_boost, []

    def check_user_is_creator_admin(self, user):
        assert isinstance(user, ttbl.user_control.User)
        userid = user.get_id()
        if userid == self.get("user") or userid == self.get("creator") \
           or user.is_admin():
            return True
        return False

    def check_user_is_admin(self, user):
        assert isinstance(user, ttbl.user_control.User)
        return user.is_admin()

    def check_user_is_user_creator(self, user):
        assert isinstance(user, ttbl.user_control.User)
        userid = user.get_id()
        if userid == self.get("user") or userid == self.get("creator"):
            return True
        return False

    def check_userid_is_user_creator_guest(self, userid):
        assert isinstance(userid, str)
        guestid = commonl.mkid(userid, l = 4)
        if userid == self.get("user") or userid == self.get("creator") \
           or userid == self.get("guest." + guestid):
            return True
        return False

    def check_user_is_guest(self, user):
        assert isinstance(user, ttbl.user_control.User)
        userid = user.get_id()
        guestid = commonl.mkid(userid, l = 4)
        if self.get("guest." + guestid) == userid:
            return True
        return False

    def check_userid_is_guest(self, userid):
        assert isinstance(userid, str)
        guestid = commonl.mkid(userid, l = 4)
        if self.get("guest." + guestid) == userid:
            return True
        return False

    def check_user_is_creator_admin_guest(self, user):
        assert isinstance(user, ttbl.user_control.User)
        # to query you must be user, creator or active guest
        if self.check_user_is_creator_admin(user):
            return True
        if self.check_userid_is_guest(user.get_id()):
            return True
        return False

    def check_query_permission(self, user):
        assert isinstance(user, ttbl.user_control.User)
        # to query you must be user, creator or active guest
        if self.check_user_is_creator_admin(user):
            return True
        if self.check_userid_is_guest(user.get_id()):
            return True
        return False

    def guest_add(self, userid):
        # we can't really validate if the user exists, because we
        # don't have their password to run it across the auth systems;
        # so we'll just record it's presence and if anyone auths as
        # that user, then ... it's ok
        #
        # we are making the almost reaonsable assumption that the number
        # of guests will be low (generally < 5) and thus a base32 ID space of
        # four digits will do more than enough to guarantee there is no
        # collissions. FLWs.
        guestid = commonl.mkid(userid, l = 4)
        self.set("guest." + guestid, userid)

    def guest_remove(self, userid):
        # a guest is trying to delete, which just removes the user
        guestid = commonl.mkid(userid, l = 4)
        # same as guest_remove()
        self.set("guest." + guestid, None)


    def guest_list(self):
        guests = []
        for _id, name in self.get_as_slist("guest.*"):
            guests.append(name)
        return guests

    def to_dict(self):
        d = {
            "state": self.state_get(),
            "user": self.get("user"),
            "creator": self.get("creator"),
            "priority": self.get('priority'),
            "preempt": self.get('preempt'),
        }
        reason = self.get("reason", None)
        if reason:
            d['reason'] = reason
        guests = self.guest_list()
        if guests:
            d['guests'] = guests
        targets = self.get('group_allocated', [])
        if targets:
            d['group_allocated'] = targets

        d['targets_all'] = list(self.targets_all.keys())
        d['target_group'] = {}
        for group_name, group in self.groups.items():
            d['target_group'][group_name] = list(group)
        d['timestamp'] = self.get("timestamp")
        for key in self.keys("extra_data.*"):
            d[key] = self.get(key)

        return d
    
lru_aged_cache_allocation_c = lru_aged_c(
    allocation_c.__init_from_cache__,
    120, 256)

def get_from_cache(allocid):
    # get an *existing* allocation, if possible from the cache
    global path
    alloc_path = os.path.join(path, allocid)
    #logging.error("DEBUG:CACHE: cache loading allocid %s", allocid)
    if not os.path.isdir(alloc_path):
        # if we are given an allocid that exists in the cache but
        # has no corresponding entry in the database, wipe it from the
        # cache and return invalid
        lru_aged_cache_allocation_c.invalidate(allocid)
        raise allocation_c.invalid_e("%s: invalid allocation" % allocid)
    return lru_aged_cache_allocation_c(allocid)


def init(state_path):
    """
    Initialize the allocation subsytem
    """
    # These are initialization that need the ttbl.allocation.path set
    allocid_uuid_db_path = os.path.join(state_path, "cache", "allocid_uuid_db")
    commonl.makedirs_p(path)	# FIXME: move from ../ttbd
    global allocid_uuid_db
    commonl.makedirs_p(allocid_uuid_db_path)
    allocid_uuid_db = commonl.fs_cache_c(allocid_uuid_db_path)



def _waiter_validate(target, waiter_string, value):
    # waiter_string: _alloc.queue.PRIO-TIMESTAMP-FLAGS
    # value: ALLOCID
    while True:
        prefix1, prefix2, rest = waiter_string.split('.', 2)
        if ( prefix1, prefix2 ) != ( "_alloc", "queue" ):
            logging.info("ALLOC: %s: removed bad waiter entry;"
                         " invalid prefix: %s", waiter_string, prefix)
            break
        # could use a regex to validate this, but the fields are
        # so simple...
        fieldl = rest.split("-")
        if len(fieldl) != 4:
            logging.info("ALLOC: %s: removed bad waiter entry", waiter_string)
            break
        prio = fieldl[0]
        ts = fieldl[1]
        flags = fieldl[2]
        	# set in request()
        if len(prio) != 6 or set(prio) - _queue_number_valid:
            logging.info("ALLOC: %s: invalid priority %s",
                         waiter_string, prio)
            break
        allocid = fieldl[3]
        if allocid != value:
            logging.info("ALLOC: invalid allocid %s, differs from value %s",
                         allocid, value)
            break
        # set in request()
        if len(ts) != 14 or set(ts) - _queue_number_valid:
            logging.info("ALLOC: %s: invalid timestamp %s",
                         waiter_string, ts)
            break
        if len(flags) != 2 \
           or flags[0] not in [ 'P', 'N' ] \
           or flags[1] not in [ 'S', 'E' ]:
            logging.info("ALLOC: %s: invalid flags %s", waiter_string, flags)
            break
        if len(value) != 8 or set(value) - _allocid_valid:
            logging.info("ALLOC: %s: invalid value to queue entry: %s",
                         waiter_string, value)
            break
        # no need verify allocid, since _target_allocate_locked()
        # will try to create an entry out of it and remove it if invalid
        return int(prio), ts, flags, value

    target.fsdb.set(waiter_string, None)	# invalid entry, wipe
    return None, None, None, None

def _target_queue_load(target):
    # Load the target's queue
    waiters = []
    preempt = False
    for waiter_string, value in target.fsdb.get_as_slist("_alloc.queue.*"):
        # get_as_slist returns an alphabetical sort by key
        # alphabetical sort by the
        # prio/ts/flags/allocid/waiter_sstring gives us the highest
        # prio first and within the same prio, sorted by the
        # allocation creation time.  could use a regex to validate
        # this, but the fields are so simple...
        prio, ts, flags, allocid = \
            _waiter_validate(target, waiter_string, value)
        if prio == None:	# bad entry, killed
            continue
        if 'P' in flags:
            preempt = True
        bisect.insort(waiters, ( prio, ts, flags, allocid,
                                 waiter_string ))
    return waiters, preempt

def _target_starvation_recalculate(allocdb, target, score):
    # FIXME: don't print FIXME bc then it drives nuts all the unit
    # tests and it is not necessarily a problem
    logging.info("Not Implemented Yet: %s: %s: %s", allocdb, target.id, score)

def _target_allocate_locked(target, current_allocdb, waiters, preempt):
    # return: allocdb from waiter that succesfully took it
    #         None if the allocation was not changed
    # FIXME: move to test_target
    # DON'T USE target.log here, it needs to take the lock [FIXME]
    assert target.lock.is_locked	    # Must have target.lock taken!

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

    # Get the first, higher prio waiter that is valid (others might
    # have been removed while we were getting here)
    waiter = None
    allocdb = None
    for waiter in waiters:
        try:
            allocdb = get_from_cache(waiter[3])
            # valid highest prio waiter!
            #logging.error("DEBUG:ALLOC: %s: higuest prio waiter is %s",
            #              target.id, allocdb.allocid)
            break
        except allocation_c.invalid_e as e:
            #logging.error("DEBUG:ALLOC: %s: waiter %s: invalid: %s",
            #              target.id, waiter, e)
            target.fsdb.set(waiter[4], None)	# invalid, remove it, try next
    else:
        #logging.error("DEBUG:ALLOC: %s: no waiters", target.id)
        return None	        # no valid waiter, nothing to dox

    # waiter at this point is
    #
    # #0: priority of this waiter for this target
    # #1: timestamp when the waiter started waiting
    # #2: flags
    # #3: allocid
    # #4: name of original queue file

    priority_waiter = waiter[0]	# get prio, maybe boosted
    if current_allocdb:
        # Ok, it is owned by a valid allocation (if it wasn't,
        # target._allocid_get()) has cleaned it up.
        current_allocid = current_allocdb.allocid

        # Let's verify if we need to boot the current owner due to a
        # preemption request.
        priority_target = target.fsdb.get("_alloc.priority", None)
        if priority_target == None:
            logging.error("%s: BUG: ALLOC: no priority recorded", target.id)
            priority_target = 500
        #logging.error(
        #    "DEBUG: %s: current allocid %s, prios target %s waiter %s",
        #    target.id, current_allocid, priority_target, priority_waiter)
        if priority_target <= priority_waiter:
            # a higher or equal prio owner has the target
            #logging.error("DEBUG: %s: busy w %s higher/equal prio owner"
            #              " (owner %d >=  waiter %d)",
            #              target.id, current_allocid,
            #              priority_target, priority_waiter)
            return None
        # a lower prio owner has the target with a higher prio target waiting
        if not preempt:
            # preemption is not enabled, so the higher prio waiter waits
            #logging.error("DEBUG: %s: busy w %s lower prio owner w/o preemption"
            #              " (owner %d > waiter  %d)",
            #              target.id, current_allocid,
            #              priority_target, priority_waiter)
            return None
        # A lower priority owner has the target, a higher priority one
        # is waiting and preemption is enabled; the lower prio holder
        # gets booted out.
        #logging.error("DEBUG: %s: preempting %s over current owner %s",
        #              target.id, allocdb.allocid,
        #              current_allocid)
        target._deallocate(current_allocdb, 'restart-needed')
        # fallthrough

    # The target is not allocated either because it was free, the
    # allocation was invalid and got cleaned up or it got preempted;
    # let's latch on it
    target.fsdb.set("_alloc.priority", priority_waiter)
    target.fsdb.set("owner", allocdb.get('user'))
    target.fsdb.set("_alloc.id", allocdb.allocid)
    ts = time.strftime("%Y%m%d%H%M%S")
    target.fsdb.set("_alloc.ts_start", ts)	# COMPAT
    target.fsdb.set("_alloc.timestamp_start", ts)
    target.fsdb.set("timestamp", ts)
    # remove the waiter from the queue
    target.fsdb.set(waiter[4], None)
    # ** This waiter is the owner now **
    #logging.error("DEBUG: %s: target allocated to %s",
    #              target.id, allocdb.allocid)
    for iface_name, allocate_hook in target.allocate_hooks.items():
        allocate_hook(target, iface_name, allocdb)
    return allocdb


def _run_target(target, preempt):
    assert isinstance(target, ttbl.test_target)
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
    while True:
        waiters, preempt_in_queue = _target_queue_load(target)
        #logging.error("DEBUG: ALLOC: %s: waiters %s", target.id, len(waiters))
        # always run, even if there are no waiters, since we might
        # need to change the target's allocation (release it)
        preempt = preempt_in_queue or preempt
        with target.lock:
            # get and validate the current owner -- if invalid owner
            # (allocation removed, it'll be wiped)
            #logging.error("DEBUG:ALLOC: %s: getting current owner", target.id)
            current_allocdb = target._allocdb_get()
            current_allocid = current_allocdb.allocid if current_allocdb \
                else None
            #logging.error("DEBUG:ALLOC: %s: current owner %s",
            #              target.id, current_allocid)
            allocdb = _target_allocate_locked(
                target, current_allocdb, waiters, preempt_in_queue)
        if allocdb:
            #logging.error("DEBUG: ALLOC: %s: new owner %s",
            #              target.id, allocdb.allocid)
            # the target was allocated to allocid
            # now we need to compute if this makes all the targets
            # needed for any of the groups in the allocid

            targets_to_boost, targets_to_release = \
                allocdb.calculate_stuff()

            # we have all the targets we need, deallocate those we
            # got that we don't need
            for target_name in targets_to_release:
                target = ttbl.test_target.get(target_name)
                with target.lock:
                    target._deallocate_simple(allocdb.allocid)
            # we still need to allocate targets, maybe boost them
            for target_name, score in targets_to_boost.items():
                _target_starvation_recalculate(allocdb, target, score)
        else:
            #logging.error("DEBUG: ALLOC: %s: ownership didn't change",
            #              target.id)
            pass
        return

    assert True, "I should not be here"

def _run(targets, preempt):
    # Main scheduler run
    for target in targets:
        _run_target(target, preempt)


def _allocation_policy_check(
        calling_user: ttbl.user_control.User, obo_user: str, guests: list,
        priority: int, preempt: bool, queue: bool, shared: bool,
        endtime: str):
    calling_user_roles = calling_user.role_list()

    # This is a quick fix -- a proper policy implementation is still
    # in the works
    if preempt:
        if calling_user_roles.get('admin', False) != True:
            return f"user {calling_user.get_id()} cannot request preemption," \
                f" need 'admin' role"

    return None


#
# Allocation UUIDs
#
# Allocation UUIDs are a unique identifier for an allocation provided
# by the client; they are meant to be unique across multiple
# allocations across multiple servers for machines that are meant to
# work together in an execution.
#
# Example: a cluster of 100 machines itnerconnected by private networks
#
#  - each server has 10 machines, so we'd do 10 machine allocations
#    plus the network to 10 separate servers
#
#  - the client generates a UUID and includes it on all the allocation
#    requests
#
#  - the server drivers that configure the network, for example, use
#    the UUID to derive a tunnel ID and program all switches to
#    interconnect all the private networks with each other using the
#    tunnel ID.
#
#
# Allocation UUIDs can't be reused for a while, to avoid things
# lagging behind in the infrastrucvture that may not have been
# properly cleaned up. So we keep a DB of recently used UUIDs
#
# The database UUID<->timestamp records when was that we saw a UUID,
# so we can avoid it being reused too soon.
#
# initialized in init(), when we have a path already
allocid_uuid_db = None

#: Maximum allowed age for UUID's allocids before we allow them being
#: reused if we still know about them. About two days.
allocid_uuid_max_age_s = 2 * 24 * 60 * 60

#: Maximum number of entries in the UUID database
#:
#: Say we can do a practical max of 1 alloc / minute and we'd want to
#: keep info for about two days it'd be 2 * 24 * 60 per target, and
#: assuming a 30 number of targets in a server, this'd be ~86400
#: entries...
allocid_uuid_max_entries = 30 * 2 * 24 * 60


def _request_extra_data_verify_uuid(uuid_str):
    # verify this a a valid uuid
    try:
        uuid_validated = uuid.UUID(uuid_str, version = 4)
    except Exception as e:
        raise ValueError("invalid RCF4122 v4 UUID supplied: {e}") from e

    ts_now = time.strftime("%Y%m%d%H%M%S")
    # has it been used in the 'recent' past? check the cache
    ts_uuid, _ex = allocid_uuid_db.get(str(uuid_validated),
                                       default = None,
                                       max_age = allocid_uuid_max_age_s)
    if ts_uuid == None:
        # Not in the cache, means it is not known
        return

    ts_delta = int(ts_now) - int(ts_uuid)
    if ts_delta < 0:
        # this timestamp is in the future? WT?
        raise ValueError(
            f"{uuid_str}: UUID has been used already"
            " (caveat: timestamp in the future discrepancy)")
    if ts_delta < allocid_uuid_max_age_s:
        raise ValueError(
            f"{uuid_str}: UUID has been used already with"
            f" timestamp {ts_uuid}, {ts_delta}s ago")
    # valid UUID, get going
    return



def _request_extra_data_verify(extra):
    commonl.assert_dict_key_strings(extra, "extra data")
    for k, v in extra.items():
        assert isinstance(v, ( bool, int, str, float ) ), \
            f"allocation extra_data {k}: must be bool, int, str or float;" \
            f" got {type(v)}"
        if k == "uuid":
            _request_extra_data_verify_uuid(v)



def request(groups, calling_user, obo_user, guests,
            priority = None, preempt = False,
            queue = False, shared = False,
            extra_data = None,
            reason = None, endtime: str = None):
    """:params list(str) groups: list of groups of targets

    :param dict extra_data: dict of scalars with extra data, for
      implementation use; this extra data is client specifc, the
      server will record it in the allocation and some drivers might
      use it.

      - *uuid*: an RFC4122 v4 UUID for this allocation, used to
        coordinate across-server resources (eg: network tunneling)

        >>> import uuid
        >>> alloc_uuid = str(uuid.uuid4())
        >>> alloc_uuid = "a5e000a8-25ed-42a2-96c2-d9e361465367"

    :param str endtime: (optional, default *None*) at what time the
      allocation shall expire (in UTC) formatted as a string:

      - *None* (default): the allocation expires when it is deemed
        idle by the server or when deleted/destroyed by API call.

      - *static*: the allocation never expires, until manually
        deleted/destroyed by API call.

      - *YYYYmmddHHMMSS*: date and time when the allocation has to
        expire, in the same format as timestamps, ie:

        >>> datetime_now = datetime.datetime.utcnow()
        >>> delta_5min = datetime.timedelta(seconds = 5 * 60)
        >>> datetime_end = datetime_now  + delta_5min
        >>> datetime_end.strftime("%Y%m%d%H%M%S")

        If hours/minutes/seconds are not needed, set to zero, eg:

        >>> "20230930000000"
    """

    # FIXME: add other extra data
    #
    # - *timeout*: a maximum timeout (0 to disable, ACLed)

    #
    # Verify the groups argument
    #
    assert isinstance(groups, dict), \
        "groups: argument needs to be a dictionary, got %s" % type(groups)
    targets_all = {}
    groups_by_target_set = {}
    groups_clean = {}
    groups_clean_str = {}
    for group_name, target_list in groups.items():
        assert isinstance(group_name, str)	# name typing
        assert isinstance(target_list, list), \
            "group '%s': value to be a list of target names, got %s" % (
                group_name, type(target_list))
        for target_name in target_list:			# ... of valid ones
            assert isinstance(target_name, str)
            target = ttbl.test_target.get(target_name)
            if not target:
                return {
                    "state": "rejected",
                    "_message": "target %s in group '%s' does not exist" % (
                        target_name, group_name
                    )
                }
            targets_all[target_name] = target

        # now check list is unique for each group (no two groups with
        # the same list, in maybe different orders)
        target_set = set(target_list)
        if len(target_set) < len(target_list):
            duplicates = target_set.difference(target_list)
            return {
                "state": "rejected",
                "_message": "targets %s in group '%s' are duplicated" % (
                    ",".join(duplicates), group_name
                )
            }

        # now check there is no group already defined in this
        # reservation for that list of trargets
        target_set_str = ",".join(target_set)
        original_group = groups_by_target_set.get(target_set_str, None)
        if original_group != None:
            return {
                "state": "rejected",
                "_message": "targets in group '%s' are the same as in '%s'" % (
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
    assert isinstance(obo_user, str)

    # Extract the guests
    assert isinstance(guests, list)
    count = 0
    for guest in guests:
        if not isinstance(guest, str):
            return {
                "state": "rejected",
                "_message": "guest #%d in the guest lists must" \
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
                "_message": "invalid priority %d (expected %d-%d)" % (
                    priority, priority_min, priority_max)
            }
        # FIXME: verify calling user has this priority
    else:
        priority = 50 # FIXME: DEFAULT FROM POLICY
    # give us three digits of subpriorities
    priority *= 1000

    assert isinstance(preempt, bool)
    assert isinstance(queue, bool)
    assert reason == None or isinstance(reason, str)

    if extra_data == None:
        extra_data = {}		# simply other paths
    else:
        _request_extra_data_verify(extra_data)

    if endtime != None:
        assert isinstance(endtime, str), \
            "endtime: expected date/time in string YYYYmmddHHMMSS format;" \
            f" got {type(endtime)}"
        if endtime != "static":
            try:
                dt_endtime  = datetime.datetime.strptime(endtime, "%Y%m%d%H%M%S")
            except ValueError as e:
                raise AssertionError(
                    f"endtime: invalid date/time {endtime}: {e}") from e
            dt_now = datetime.datetime.utcnow()
            # was there no way to get the delta straight from the struct??
            delta = dt_endtime - dt_now
            if delta.days <= 0 and delta.seconds < 60:
                raise AssertionError(
                    "endtime: needs to be at least one minutes ahead"
                    " of curent time; got {delta}s")

    message = _allocation_policy_check(calling_user, obo_user, guests,
                                       priority, preempt, queue, shared,
                                       endtime)
    if message:
        return {
            "state": "rejected",
            "_message": message,
        }

    # Create an allocation record and from there, get the ID -- we
    # abuse python's tempdir making abilities for it
    allocid_path = tempfile.mkdtemp(dir = path, prefix = "")
    # we allow ttbd group (admins) to look into these dirs
    os.chmod(allocid_path, 0o2770)
    allocid = os.path.basename(allocid_path)

    allocdb = get_from_cache(allocid)

    allocdb.set("preempt", preempt)
    allocdb.set("priority", priority)
    allocdb.set("user", obo_user)
    allocdb.set("creator", calling_user.get_id())
    if endtime != None:
        allocdb.set("endtime", endtime)
    if reason:
        if len(reason) > ttbl.config.reason_len_max:
            reason = reason[:ttbl.config.reason_len_max]
        allocdb.set("reason", reason)
    for guest in guests:
        allocdb.guest_add(guest)
    ts = allocdb.timestamp()
    # The extra data is just recorded, that's it-- some drivers might
    # use it, some not
    for k, v in extra_data.items():
        allocdb.set(f"extra_data.{k}", v)
        if k == "uuid":
            with allocid_uuid_db.lock():
                allocid_uuid_db.set_unlocked(v, ts)
                allocid_uuid_db.lru_cleanup_unlocked(allocid_uuid_max_entries)

    allocdb.state_set('queued')
    # FIXME: these is severly limited in size, we need a normal file to
    # set this info with one target per file
    allocdb.set("targets_all", ",".join(targets_all.keys()))
    for group, targets in groups_clean_str.items():
        allocdb.set("group." + group, targets)
    allocdb.target_info_reload()

    # At this point the allocation record is ready -- no target can
    # see it yet, so there is no danger the _run() method will see it

    # Add waiting record to each target; maybe we add
    #
    #
    # on each target, enter in the queue a link to the timestamp file;
    # name it PRIORITY-TIMESTAMP-FLAGS-ALLOCID
    #
    # PRIORITY is what help us short who will get it first; highest
    # (0) wins, always 6 characters -- 0-999 * 1000 is the user given
    # priority; the extra three are to add a subpriority to avoid
    # starvation; we modify the priority every T seconds with the
    # allocation's prio speed value, which gets modified from the
    # keepalive's pressure argument and it also increases as the age
    # of the allocation increases (calculated from the TIMESTAMP in
    # the name)
    #
    # TIMESTAMP is the time when the allocid was created (vs the
    # ALLOCID/timestamp field which we use to mark keepalives); allows
    # to:
    #
    #   (a) first-come-first-serve sort two allocations with the same
    #       priority
    #
    #   (b) calculate the age of an allocation to increase the prio
    #       speed to avoid starvation
    #
    #   (c) adjust the priority up or down based on pressure feedback
    #       during keepalive
    #
    # FLAGS are a sequence of ONE letters
    #
    #  - P or N: Preemption or no preemtion
    #
    #  - S or E: Shared or Exclusive; currently only Exclusive
    #    supported
    #
    # We don't use the GROUPNAME--if multiple groups of the same
    # allocation are trying to allocate the same target, we want to
    # share that position in the queue
    flags = "P" if preempt else "N"
    flags += "S" if shared else "E"
    for target in targets_all.values():
        # FIXME: policy: can we queue on this target? otherwise append to
        # rejected targets and cleanup
        # target.check_user_is_allowed(calling_user)
        # target.check_user_is_allowed(obo_user)
        # IF there is a collision, things will get dropped randomly,
        # so besides the second level granularity timestamp (which is
        # not enough), add the allocation ID -- since there will be
        # ONE entry per allocation ID only.
        target.fsdb.set(
            "_alloc.queue.%06d-%s-%s-%s" % (priority, ts, flags, allocid),
            allocid)

    _run(targets_all.values(), preempt)

    state = allocdb.state_get()
    result = {
        "state": state,
        "allocid": allocid,
        "_message": states[state],
    }
    if queue == False:
        if state == 'active':		# we got it
            pass
        elif state == 'queued':		# busy but we wanted it now
            allocdb.delete(None)
            return  {
                "state": "busy",
                "_message": states['busy']
            }
        else:			     	# something wong
            allocdb.delete(None)
    if state == 'active':
        # group_allocated set in calculate_stuff()
        result['group_allocated'] = allocdb.get("group_allocated")
    return result


def query(calling_user):
    assert isinstance(calling_user, ttbl.user_control.User)
    result = {}
    for _rootname, allocids, _filenames in os.walk(path):
        for allocid in allocids:
            try:
                allocdb = get_from_cache(allocid)
                if not allocdb.check_query_permission(calling_user):
                    continue
                result[allocid] = allocdb.to_dict()
            except allocation_c.invalid_e:
                result[allocid] = { "state" : "invalid" }
        return result	# only want the toplevel, thanks


def get(allocid, calling_user):
    assert isinstance(calling_user, ttbl.user_control.User)
    allocdb = get_from_cache(allocid)
    if not allocdb.check_query_permission(calling_user):
        return {
            # could also just return invalid
            "_message": "not allowed to read allocation"
        }
    return allocdb.to_dict()


def keepalive(allocid, expected_state, _pressure, calling_user):
    """
    :param int pressure: how my system is doing so I might be able or
      not to take the extra job of the next allocation, so up and down
      my prio based on N -- this might move my allocations to lower
      priority if I know I won't be able to use them when I get them

    """
    assert isinstance(calling_user, ttbl.user_control.User), \
        "calling_user is unexpected type %s" % type(calling_user)
    allocdb = None
    try:
        allocdb = get_from_cache(allocid)
    except allocation_c.invalid_e:
        return dict(state = "invalid", _message = states['invalid'])
    if not allocdb.check_user_is_creator_admin(calling_user):
        # guests are *NOT* allowed to keepalive
        return dict(state = "rejected", _message = states['rejected'])

    allocdb.timestamp()				# first things first
    state = allocdb.state_get()
    r = dict(state = state)
    if state == "active" and expected_state != 'active':
        # set in calculate_stuff()
        r['group_allocated'] = allocdb.get("group_allocated")
    return r

def _idle_power_off(target, calling_user,
                    idle_power_off, idle_power_fully_off):
    assert isinstance(target, ttbl.test_target)
    assert isinstance(idle_power_off, int)
    assert isinstance(idle_power_fully_off, int)

    # get the target's timestamp before allocating it, since
    # allocating it will update the timestamp; then allocate it and
    # get its power state; turn it off it it has been on for too
    # long
    ts = target.timestamp_get()

    r = request(
        { "target": [ target.id ] },
        calling_user, calling_user.get_id(), [], queue = False,
        reason = "checking if need to power off due to idleness")
    if r['state'] != "active":
        # someone else got it, that's fine, means they are using it
        return
    allocdb = get_from_cache(r['allocid'])
    try:
        # the power interface is defined in ttbl.power
        power_state, _, power_substate = target.power._get(target)

        # calculate the idle time once we own the target, to be sure
        # none came in the middle and we are killing it for them...
        ts_now = datetime.datetime.now()
        idle_time = ts_now - datetime.datetime.strptime(ts, "%Y%m%d%H%M%S")

        if idle_time.seconds > idle_power_fully_off:
            # if it is already fully off or we fully power it off,
            # then we can exit, as it is automatically normal off
            if power_state == False and power_substate == 'full':
                return		# already fully off, so normal too
            target.log.info("powering fully off, idle for %ss (max %ss)",
                            idle_time, idle_power_fully_off)
            target.power.put_off(target, calling_user.get_id(),
                                 dict(explicit = True), {}, None)
            return

        if idle_time.seconds > idle_power_off:
            if power_state == False \
               and power_substate in [ 'normal', 'full' ]:
                return		            	# already off
            target.log.info("powering off, idle for %ss (max %ss)",
                            idle_time, idle_power_off)
            target.power.put_off(target, calling_user.get_id(),
                                 dict(explicit = False), {}, None)
    finally:
        allocdb.delete("removed")

def _maintain_released_target(target, calling_user):
    # a target that is released is not being used, so we power it all
    # off...unless it is configured to be left on
    if not hasattr(target, "power"):	# does it have power control?
        return

    # configured to be left on? okie
    skip_cleanup = target.property_get('skip_cleanup', False)
    if skip_cleanup:
        target.log.debug("ALLOC: skiping powering off, skip_cleanup defined")
        return

    idle_power_off = target.property_get(
        'idle_power_off',
        target.property_get(
            'idle_poweroff',	# COMPAT
            ttbl.config.target_max_idle
        )
    )
    idle_power_fully_off = target.property_get(
        'idle_power_fully_off',
        ttbl.config.target_max_idle_power_fully_off)
    if idle_power_off > 0 or idle_power_fully_off > 0:
        _idle_power_off(target, calling_user,
                        idle_power_off, idle_power_fully_off)


def maintenance(ts_now, calling_user, keepalive_fn = None):
    # this will be called by a parallel thread / process to run
    # cleanup activities, such as:
    #
    # - enforcing idle timeouts
    # - enforcing max allocation times
    # - enforcing max target allocation times
    # - removing stale records
    # - increase effective priorities to avoid starvation
    # - when priorities change, maybe reassign ownerships if
    #   preemption
    #logging.error("DEBUG: maint %s", ts_now)
    assert isinstance(calling_user, ttbl.user_control.User)
    assert keepalive_fn == None or callable(keepalive_fn)

    # allocations: run maintenance (expire, check overtimes)
    for _rootname, allocids, _filenames in os.walk(path):
        for allocid in allocids:
            try:
                allocdb = get_from_cache(allocid)
                allocdb.maintenance(ts_now)
            except allocation_c.invalid_e:
                continue
        break	# only want the toplevel, thanks

    # targets: starvation control, check overtimes
    for target in ttbl.test_target.known_targets():
        # FIXME: paralellize
        # Always keepalive first in case someting crashes and we need to skip
        if keepalive_fn:   	# run keepalives in between targets..
            keepalive_fn()	# ... some targets might take a long time
        try:
            owner = target.owner_get()
            if owner:
                _target_starvation_recalculate(None, target, 0)
            else:
                _maintain_released_target(target, calling_user)
        except Exception as e:
            logging.exception("%s: exception in cleanup: %s\n"
                              % (target.id, e))
            # fallthrough, continue running other targets

    # Finally, do an schedule run on all the targets, see what has to move
    _run(ttbl.test_target.known_targets(), False)


def delete(allocid, calling_user):
    assert isinstance(allocid, str)
    assert isinstance(calling_user, ttbl.user_control.User)
    allocdb = get_from_cache(allocid)
    userid = calling_user.get_id()
    if allocdb.check_user_is_creator_admin(calling_user):
        allocdb.delete("removed")
        return {
            "state": "removed",
            "_message": states['removed']
        }

    if allocdb.check_userid_is_guest(userid):
        allocdb.guest_remove(userid)
        return {
            "state": "removed",
            "_message": "%s: guest removed from allocation" % userid
        }

    return {
        "state": "rejected",
        "_message": "no permission to remove other's allocation"
    }


def guest_add(allocid, calling_user, guest):
    assert isinstance(calling_user, ttbl.user_control.User)
    if not isinstance(guest, str):
        return {
            "state": "rejected",
            "_message": "guest must be described by a string; got %s" \
            % type(guest).__name__
        }
    assert isinstance(allocid, str)
    allocdb = get_from_cache(allocid)
    # verify user is owner/creator
    if not allocdb.check_user_is_creator_admin(calling_user):
        return { "_message": "guests not allowed to set guests in allocation" }
    allocdb.guest_add(guest)
    return {}


def guest_remove(allocid, calling_user, guest):
    assert isinstance(calling_user, ttbl.user_control.User)
    if not isinstance(guest, str):
        return {
            "state": "rejected",
            "_message": "guest must be described by a string;"
                       " got %s" % type(guest)
        }
    assert isinstance(allocid, str)
    allocdb = get_from_cache(allocid)
    guestid = commonl.mkid(guest, l = 4)
    if calling_user.get_id() != guest \
       and not allocdb.check_user_is_creator_admin(calling_user):
        return { "_message": "not allowed to remove guests from allocation" }
    allocdb.guest_remove(guest)
    return {}

