#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
#  - allocationid / allocationdb -> allocid / allocd
#  - _alloc* fields to _alloc.
#  - alloc-monitor broken
#  - reject messages to carry a 40x code?
#  - each target allocation carries a max TTL per policy
#  - starvation control missing
#  - forbid fsdb writing to alloc fields
#  - check lock order taking, always target or allocationid,target
#  * LRU caches needs being able to invalidate to avoid data
#    contamination, consider https://pastebin.com/LDwMwtp8
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

'Foundation for rolling your own LRU cache variants'

import collections
import time

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
    
class allocation_c(ttbl.fsdb_symlink_c):
    """
    Backed by state in disk

    Move backend symlink_set_c -> impl so it can be transitioned to a
    Mongo or whatever
    """
    def __init__(self, allocationid):
        dirname = os.path.join(path, allocationid)
        ttbl.fsdb_symlink_c.__init__(self, dirname, concept = "allocationid")
        self.allocationid = allocationid
        # protects writing to most fields
        # - group
        # - state
        self.lock = ttbl.process_posix_file_lock_c(
            os.path.join(dirname, "lockfile"))
        # FIXME: load state object from STATEDIR/allocations/ALLOCATIONID
        # loaded by target_info_reload()
        self.targets_all = None
        self.groups = None
        self.target_info_reload()

    @staticmethod
    def __init_from_cache__(allocationid):
        # yeah, yeah, I could make lru_aged_c be smarter and know how
        # to call methods, but it's late        
        return allocation_c(allocationid)

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
            self.targets_all[target_name] = ttbl.config.targets[target_name]

    def delete(self, _state = "removed"):
        targets_all = []
        try:
            # if the reservation DB is messed up, this might fail --
            # it is fine, we will then just wipe it
            with self.lock:
                if self.state_get == 'active':
                    # FIXME: only need to run on currently acquired targets
                    targets = self.targets_all
                else:
                    targets = self.targets_all
        finally:
            # wipe the whole tree--this will render all the records that point
            # to it invalid and the next _run() call will clean them
            logging.error("DEBUG:ALLOC: rmtree %s", self.location)
            shutil.rmtree(self.location, True)
            lru_aged_cache_allocation_c.invalidate(self.allocationid)
        # FIXME: implement a DB of recently deleted reservations so anyone
        # trying to use it gets a state invalid/timedout/overtime/removed
        # release all queueing/owning targets to it
        # FIXME: remove from get_from_cache cache
        if targets:
            logging.error("DEBUG:ALLOC: %s delete runs scheduler on %s",
                          self.allocationid, targets.keys())
            _run(targets.values(), False)

    def state_set(self, new_state):
        """
        :returns *True* if succesful, *False* if it was set by someone
          else
        """
        self.set('state', new_state)

    def state_get(self):
        return self.get('state')

    def timestamp(self):
        ts = time.strftime("%Y%m%d%H%M%S")
        self.set('timestamp', ts, force = True)
        return ts

    def timestamp_get(self):
        # if there is no timestamp, forge the beginning of time
        return self.get('timestamp', "00000000000000")	# follow %Y%m%d%H%M%S

    def maintenance(self, ts_now):
        logging.error("DEBUG: %s: maint %s", self.allocationid, ts_now)

        # Check if it has been idle for too long
        ts_last_keepalive = int(self.timestamp_get())
        if ts_now - ts_last_keepalive > ttbl.config.target_max_idle:
            logging.error("DEBUG: %d: allocation %s timedout, deleting",
                          ts_now, self.allocationid)
            self.delete('timedout')
            return

        # Check if it has been alive too long
        ttl = self.get("ttl", 0)
        if ttl > 0:
            # FIXME: we need to record ts_start
            ts_start = int(self.get('_alloc.ts_start'))
            if ts_now - ts_start > ttl:
                logging.error("DEBUG: %s: allocation expired",
                              self.allocationid)
                self.delete('overtime')
                return

    def calculate_stuff(self):
        # lock so we don't have two processes doing the same
        # processing after acquiring diffrent targets of our group the
        # same time
        with self.lock:
            # We need to know if we have completely allocated all of
            # the targets of any of the groups of targets this
            # allocationid requested

            # Lookup all the targets this allocationid has allocated
            targets_allocated = set()
            for target_name, target in self.targets_all.iteritems():
                allocationid = target.allocationid_get_bare()
                if allocationid == self.allocationid:
                    targets_allocated.add(target_name)

            # Iterate all the groups, see which are incomplete; for
            # each target, collect their max boot score
            targets_to_boost = collections.defaultdict(int)
            for group_name, group in self.groups.iteritems():
                not_yet_allocated = group - targets_allocated
                if not_yet_allocated:
                    # this group has still targets not allocated, will
                    # have to do starvation recalculation later
                    score = float(len(targets_allocated)) / len(group)
                    logging.error(
                        "DEBUG: group %s incomplete, score %f [%d/%d]",
                        group_name, score, len(targets_allocated), len(group))
                    for target_name in not_yet_allocated:
                        targets_to_boost[target_name] = \
                            min(targets_to_boost[target_name], score)
                else:
                    logging.error("DEBUG: group %s complete",
                                  group_name)
                    # This group is complete, so we don't need the
                    # other targets tentatively allocated, so return
                    # the list so they can be released
                    # all targets needed for this group have been
                    # allocated, let's then use it--if we set the "group"
                    # value, then we have it allocated
                    target_group = ",".join(group)
                    self.set("group", target_group)
                    self.set("ts_start", time.time())
                    self.state_set("active")
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

    def check_userid_is_user_creator_guest(self, userid):
        assert isinstance(userid, basestring)
        guestid = commonl.mkid(userid, l = 4)
        if userid == self.get("user") or userid == self.get("creator") \
           or userid == self.get("guest." + guestid):
            return True
        return False

    def check_userid_is_guest(self, userid):
        assert isinstance(userid, basestring)
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
        }
        reason = self.get("reason", None)
        if reason:
            d[reason] = reason
        guests = self.guest_list()
        if guests:
            d['guests'] = guests
        targets = self.get('targets')
        if targets:
            d['targets'] = targets

        d['targets_all'] = list(self.targets_all.keys())
        d['target_group'] = {}
        for group_name, group in self.groups.iteritems():
            d['target_group'][group_name] = list(group)
        return d
    
lru_aged_cache_allocation_c = lru_aged_c(
    allocation_c.__init_from_cache__,
    120, 256)

def get_from_cache(allocationid):
    # get an *existing* allocation, if possible from the cache
    global path
    alloc_path = os.path.join(path, allocationid)
    #logging.error("DEBUG:CACHE: cache loading allocationid %s", allocationid)
    if not os.path.isdir(alloc_path):
        # if we are given an allocationid that exists in the cache but
        # has no corresponding entry in the database, wipe it from the
        # cache and return invalid
        lru_aged_cache_allocation_c.invalidate(allocationid)
        raise allocation_c.invalid_e("%s: invalid allocation" % allocationid)
    return lru_aged_cache_allocation_c(allocationid)

def target_is_valid(target_name):
    # FIXME: validate with the inventory
    # FIXME: move to a target inventory service
    return ttbl.config.targets.get(target_name, None)


def init():
    commonl.makedirs_p(path)


def _allocationid_validate(allocationid):
    # FIXME: move to allocation_c? or deprecate and move all users to
    # use the returned object
    try:
        return get_from_cache(allocationid)
    except allocation_c.invalid_e:
        return None

def _waiter_validate(target, waiter_string, value):
    # waiter_string: _alloc.queue.PRIO-TIMESTAMP-FLAGS
    # value: ALLOCATIONID
    while True:
        prefix1, prefix2, rest = waiter_string.split('.', 2)
        if ( prefix1, prefix2 ) != ( "_alloc", "queue" ):
            logging.info("ALLOC: %s: removed bad waiter entry;"
                         " invalid prefix: %s", waiter_string, prefix)
            break
        # could use a regex to validate this, but the fields are
        # so simple...
        fieldl = rest.split("-")
        if len(fieldl) != 3:
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
        if len(value) != 6 or set(value) - _allocationid_valid:
            logging.info("ALLOC: %s: invalid value to queue entry: %s",
                         waiter_string, value)
            break
        # no need verify allocationid, since _target_allocate_locked()
        # will try to create an entry out of it and remove it if invalid
        return int(prio), ts, flags, value

    target.fsdb.set(waiter_string, None)	# invalid entry, wipe
    return None, None, None, None

def _target_queue_load(target):
    waiters = []
    preempt = False
    for waiter_string, value in target.fsdb.get_as_slist("_alloc.queue.*"):
        # get_as_slist returns an alphabetical sort by key
        # alphabetical sort gives us  the highest prio first and
        # within the same prio, sorted by the allocation creation
        # time.
        # could use a regex to validate this, but the fields are
        # so simple...
        prio, ts, flags, allocationid = \
            _waiter_validate(target, waiter_string, value)
        if prio == None:	# bad entry, killed
            continue
        if 'P' in flags:
            preempt = True
        bisect.insort(waiters, ( prio, ts, flags, allocationid,
                                 waiter_string ))
    return waiters, preempt

def _target_starvation_recalculate(allocationdb, target, score):
    logging.error("FIXME: %s: %s: %s",
                  allocationdb.allocationid, target.id, score)

def _target_allocate_locked(target, current_allocationid, waiters, preempt):
    # return: allocationdb from waiter that succesfully took it
    #         None if the allocation was not changed
    # FIXME: move to test_target
    # DON'T USE target.log here, it needs to take the lock [FIXME]
    assert target.lock.locked()	    # Must have target.lock taken!

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
    allocationdb = None
    for waiter in reversed(waiters):
        try:
            allocationdb = get_from_cache(waiter[3])
            # valid highest prio waiter!
            # FIXME: ops -- timestamps have to be sorted low to high,
            # let's change the whole prio system to be 0 highest, 1000
            # max. 
            logging.error("DEBUG:ALLOC: %s: higuest prio waiter is %s",
                          target.id, allocationdb.allocationid)
            break
        except allocation_c.invalid_e as e:
            logging.error("DEBUG:ALLOC: %s: waiter %s: invalid: %s",
                          target.id, waiter, e)
            target.fsdb.set(waiter[4], None)	# invalid, remove it, try next
    else:
        logging.error("DEBUG:ALLOC: %s: no waiters", target.id)
        return None	        # no valid waiter, nothing to dox

    # waiter at this point is
    #
    # #0: priority of this waiter for this target
    # #1: timestamp when the waiter started waiting
    # #2: flags
    # #3: allocationid
    # #4: name of original queue file

    priority_waiter = waiter[0]	# get prio, maybe boosted

    if current_allocationid:
        # FIXME
        # Ok, it is owned by a valid allocation (if it wasn't,
        # target._allocationid_get()) has cleaned it up.

        # Let's verify if we need to boot the current owner due to a
        # preemption request.
        priority_target = target.fsdb.get("_alloc.priority", None)
        if priority_target == None:
            logging.error("%s: BUG: ALLOC: no priority recorded", target.id)
            priority_target = 500
        logging.error(
            "DEBUG: %s: current allocationid %s, prios target %s waiter %s",
            target.id, current_allocationid, priority_target, priority_waiter)
        if priority_waiter <= priority_target:
            # a higher or equal prio owner has the target
            logging.error("DEBUG: %s: busy w %s higher/equal prio owner"
                          " (owner %d >=  waiter %d)",
                          target.id, current_allocationid,
                          priority_target, priority_waiter)
            return None
        # a lower prio owner has the target with a higher prio target waiting
        if not preempt:
            # preemption is not enabled, so the higher prio waiter waits
            logging.error("DEBUG: %s: busy w %s lower prio owner"
                          " (owner %d  < waiter  %d)",
                          target.id, current_allocationid,
                          priority_target, priority_waiter)
            return None
        # A lower priority owner has the target, a higher priority one
        # is waiting and preemption is enabled; the lower prio holder
        # gets booted out.
        logging.error("DEBUG: %s: preempting %s over current owner %s",
                      target.id, allocationdb.allocationid,
                      current_allocationid)
        target._deallocate(current_allocationid)
        # FIXME: set owning allocationid to reset-needed
        # fallthrough

    # The target is not allocated either because it was free, the
    # allocation was invalid and got cleaned up or it got preempted;
    # let's latch it
    # FIXME: cleanup status? target._status_cleanup?
    # if invalid, just ignore it and move on
    # try to assign the first waiter as owner; if the target is
    # owned by someone (the owner field already exist) it
    # will fail to update and just return False...so then
    # we leave it for the next run
    target.fsdb.set("_alloc.priority", priority_waiter)
    target.fsdb.set("owner", allocationdb.get('user'))
    target.fsdb.set("_allocationid", allocationdb.allocationid)
    target.fsdb.set("_alloc.ts_start", time.strftime("%Y%m%d%H%M%S"))
    # remove the waiter from the queue
    target.fsdb.set(waiter[4], None)
    # ** This waiter is the owner now **
    logging.error("DEBUG: %s: target allocated to %s",
                  target.id, allocationdb.allocationid)
    return allocationdb


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
        logging.error("DEBUG: ALLOC: %s: waiters %s", target.id, len(waiters))
        # always run, even if there are no waiters, since we might
        # need to change the target's allocation (release it)
        preempt = preempt_in_queue or preempt
        with target.lock:
            # get and validate the current owner -- if invalid owner
            # (allocation removed, it'll be wiped)
            logging.error("DEBUG:ALLOC: %s: getting current owner", target.id)
            current_allocationid =  target._allocationid_get()
            logging.error("DEBUG:ALLOC: %s: current owner %s",
                          target.id, current_allocationid)
            allocationdb = _target_allocate_locked(
                target, current_allocationid, waiters, preempt_in_queue)
        if allocationdb:
            logging.error("DEBUG: ALLOC: %s: new owner %s",
                          target.id, allocationdb.allocationid)
            # the target was allocated to allocationid
            # now we need to compute if this makes all the targets
            # needed for any of the groups in the allocationid

            # FIXME: adjust the priority of waiters for other target
            # in the allocation
            targets_to_boost, targets_to_release = \
                allocationdb.calculate_stuff()

            for target_name in targets_to_release:
                target = ttbl.config.targets[target_name]
                with target.lock:
                    target._deallocate_simple(allocationdb.allocationid)
            for target_name, score in targets_to_boost.iteritems():
                _target_starvation_recalculate(allocationdb, target, score)
        else:
            logging.error("DEBUG: ALLOC: %s: ownership didn't change",
                          target.id)
        return

    assert True, "I should not be here"

def _run(targets, preempt):
    # Main scheduler run
    if targets == None:
        logging.error("FIXME: not sure this is really needed")
        targets = ttbl.config.targets.values()

    for target in targets:
        _run_target(target, preempt)



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
    targets_all = {}
    groups_by_target_set = {}
    groups_clean = {}
    groups_clean_str = {}
    for group_name, target_list in groups.items():
        assert isinstance(group_name, basestring)	# name typing
        assert isinstance(target_list, list)		# target list...
        for target_name in target_list:			# ... of valid ones
            assert isinstance(target_name, basestring)
            target = target_is_valid(target_name)
            if not target:
                return {
                    "state": "rejected",
                    "message": "target %s in group '%s' does not exist" % (
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
                "message": "targets %s in group '%s' are duplicated" % (
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

    db = get_from_cache(allocationid)

    db.set("priority", priority)
    db.set("user", obo_user)
    db.set("creator", calling_user.get_id())
    for guest in guests:
        db.guest_add(guest)

    ts = db.timestamp()
    db.state_set('queued')
    # FIXME: these is severly limited in size, we need a normal file to
    # set this info with one target per file
    db.set("targets_all", ",".join(targets_all.keys()))
    for group, targets in groups_clean_str.items():
        db.set("group." + group, targets)
    db.target_info_reload()

    # At this point the allocation record is ready -- no target can
    # see it yet, so there is no danger the _run() method will see it

    # Add waiting record to each target; maybe we add
    flags = "P" if preempt else "N"
    flags += "S" if shared else "E"
    for target in targets_all.values():
        # FIXME: policy: can we queue on this target? otherwise append to
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
        target.fsdb.set("_alloc.queue.%06d-%s-%s" % (priority, ts, flags),
                        allocationid)

    _run(targets_all.values(), preempt)

    state = db.state_get()
    result = {
        "state": state,
        "allocationid": allocationid,
        "message": states[state],
    }
    if queue == False:
        if result == 'active':
            result['targets'] = db.get("group")	# set in calculate_stuff()
        elif state == 'queued':
            db.delete(None)
            return  {
                "state": "busy",
                "message": states['busy']
            }
        else:
            # something else didn't work, just pass it along
            db.delete(None)
    return result

def query(calling_user):
    assert isinstance(calling_user, ttbl.user_control.User)
    result = {}
    for _rootname, allocationids, _filenames in os.walk(path):
        for allocationid in allocationids:
            try:
                db = get_from_cache(allocationid)
                if not db.check_query_permission(calling_user):
                    continue
                result[allocationid] = db.to_dict()
            except allocation_c.invalid_e:
                result[allocationid] = { "status" : "invalid" }
        return result	# only want the toplevel, thanks


def get(allocationid, calling_user):
    assert isinstance(calling_user, ttbl.user_control.User)
    db = get_from_cache(allocationid)
    if not db.check_query_permission(calling_user):
        return {
            # could also just return invalid
            "message": "not allowed to read allocation"
        }
    return db.to_dict()


def keepalive(allocationid, expected_state, _pressure, calling_user):
    """

    :param int pressure: how my system is doing so I might be able or
      not to take the extra job of the next allocation, so up and down
      my prio based on N -- this might move my allocations to lower
      priority if I know I won't be able to use them when I get them

    """
    assert isinstance(calling_user, ttbl.user_control.User), \
        "calling_user is unexpected type %s" % type(calling_user)
    db = None
    try:
        db = get_from_cache(allocationid)
    except allocation_c.invalid_e:
        return dict(state = "invalid", message = states['invalid'])
    if not db.check_user_is_creator_admin(calling_user):
        # guests are *NOT* allowed to keepalive
        return dict(state = "rejected", message = states['rejected'])

    db.timestamp()				# first things first
    state = db.state_get()
    r = dict(state = state)
    if state == "active" and expected_state != 'active':
        r['targets'] = db.get("group")	# set in calculate_stuff()
    return r


def maintenance(t, calling_user):
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
    ts_now = int(time.strftime("%Y%m%d%H%M%S", time.localtime(t)))
    logging.error("DEBUG: maint %s", ts_now)
    assert isinstance(calling_user, ttbl.user_control.User)

    # allocations: run maintenance (expire, check overtimes)
    for _rootname, allocationids, _filenames in os.walk(path):
        for allocationid in allocationids:
            try:
                db = get_from_cache(allocationid)
                db.maintenance(ts_now)
            except allocation_c.invalid_e:
                continue
        break	# only want the toplevel, thanks

    # targets: starvation control, check overtimes
    for target_name, target in ttbl.config.targets.iteritems():
        owner = target.owner_get()
        if owner:	# if queue entries
            pass
            #logging.error("FIXME: starvation control %s: %s",
            #              target_name, owner)
            #_target_starvation_recalculate()
	else:
            pass
            #logging.error("FIXME: idle-power-off control %s: %s", target_name, owner)

    # Finally, do an schedule run on all the targets, see what has to move
    _run(ttbl.config.targets.values(), False)


def delete(allocationid, calling_user):
    assert isinstance(allocationid, basestring)
    assert isinstance(calling_user, ttbl.user_control.User)
    db = get_from_cache(allocationid)
    userid = calling_user.get_id()
    if db.check_user_is_creator_admin(calling_user):
        logging.error("DEBUG:ALLOC: %s removing" % allocationid)
        db.delete("removed")
        logging.error("DEBUG:ALLOC: %s removed" % allocationid)
        return {
            "state": "removed",
            "message": states['removed']
        }

    if db.check_userid_is_guest(userid):
        db.guest_remove(userid)
        return { "message": "%s: guest removed from allocation" % userid }

    return { "message": "no permission to remove other's allocation" }


def guest_add(allocationid, calling_user, guest):
    assert isinstance(calling_user, ttbl.user_control.User)
    if not isinstance(guest, basestring):
        return {
            "state": "rejected",
            "message": "guest must be described by a string; got %s" \
            % type(guest).__name__
        }
    assert isinstance(allocationid, basestring)
    db = get_from_cache(allocationid)
    # verify user is owner/creator
    if not db.check_user_is_creator_admin(calling_user):
        return { "message": "guests not allowed to set guests in allocation" }
    db.guest_add(guest)
    return {}


def guest_remove(allocationid, calling_user, guest):
    assert isinstance(calling_user, ttbl.user_control.User)
    if not isinstance(guest, basestring):
        return {
            "state": "rejected",
            "message": "guest must be described by a string;"
                       " got %s" % type(guest)
        }
    assert isinstance(allocationid, basestring)
    db = get_from_cache(allocationid)
    guestid = commonl.mkid(guest, l = 4)
    if calling_user.get_id() != guest \
       and not db.check_user_is_creator_admin(calling_user):
        return { "message": "not allowed to remove guests from allocation" }
    db.guest_remove(guest)
    return {}

