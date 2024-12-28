#! /usr/bin/env python3
#
# Copyright (c) 2022-24 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

# FIXME: moving this from orch/tcfl/target_ext_run.py

"""Execution engine
================

The following is implemented by this module:

- discovery of testcases to run

- discovery of available targets where to run testcases

- pairing of testcase/target-groups

  - axes permutation generator

  - target group permutation generator

- allocation of targets needed by each testcase

- launching the testcase as target group is allocated

- collecting and reporting results


See :class:`executor_c` for execution details

Code roadmap
------------

run()
  for each testcase file
    for each testcase in the file
      _run_testcase_axes_discover()
        for axis perm in _testcase_axes_iterate()
          _tc_axes_names()
          tc_run_c()
    keep running until done

executor_c.__init__
  executor_c._tc_info_setup_all()
    for each filename
       for each tci(testcase) in filename
           executor_c._tc_info_setup(tci)
             executor_c._tc_info_randomizer_make()
             for each target role
               for each axis
                 executor_c._axes_expand_field()
            executor_c._axes_expand_field() [for testcase axes]

  executor_c._worker_tc_run_static
    executor_c.target_group_iterate_for_axes_permutation
      executor_c.target_group_iterate()
        for each target role + axes:
          executor_c.targets_valid_list()
            executor_c._spec_filter()
        executor_c._target_group_iterate_random()
        executor_c._target_group_iterate_sorted()
          executor_c._target_group_iterate_sorted_recurse()

FIXME/Pending
-------------

- tc_info_c shall be split to just be an spec of the TC and primitives
  and reporting -- pretty much tc_c and remove the concept of
  tc_info_c

- tc_run_c should have the info of the result of execting a TC in a
  apid/tgid--in a way, tc_run_c is what we should care most

target_c
    def _bind(self, rtb_aka, target_id, target_fullid, allocid):
        self.rtb_aka = rtb_aka
        self.id = target_id
        self.fullid = target_fullid
        self.allocid = allocid

"""

import copy
import pickle
import collections
import concurrent.futures
import contextlib
import itertools
import json
import os
import pprint
import queue
import logging
import random
import time
import types
import sys

import multiprocessing
import multiprocessing.pool
import multiprocessing.managers

import requests
import requests.exceptions

import tcfl
import tcfl.tc
import commonl


# FIXME: end goal target_c will be in tcfl.target_c
tcfl.target_c = tcfl.tc.target_c

logger = logging.getLogger("orchestrate")

#: Length of the hash used to identify groups or lists of targets
#:
#: Used to create a unique string that represents a dictionary of
#: role/targetname assignments and others for caching.
#:
#: The underlying implementation takes a sha512 hash of a string
#: that represents the data, base32 encodes it and takes the as
#: many characters as this length for the ID (for humans base32 it
#: is easier than base64 as it does not mix upperand lower
#: case).
#:
#: If there are a lot of target roles and/or targets, it might be
#: wise to increase it to avoid collisions...but how much is a lot
#: is not clear. 10 gives us a key space of 32^10 (1024 Peta)
hash_length = 10

#: How many times to retry to generate a group before giving up
#:
#: If the generation ess yields an empty group more than this
#: many times, stop trying and return.
spin_max = 3000



#FIXME: move to commonl
class cache_c(collections.OrderedDict):
    """
    Simple LRU cache

    Currently only used by :meth:`target_c.targets_valid_list`
    can't use functools.lru_cache() and friends because of the
    complexity of the arguments. Anyhoo, pretty simple implementation.

    """
    def __init__(self, size = 4000):
        collections.OrderedDict.__init__(self)
        self.size = size
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def set(self, cache_id, value):
        self[cache_id] = value
        # FIXME: move to a configurable size
        while len(self) > 5000:
            # pop the least recent item until under the right size
            self.evictions += 1
            self.popitem(False)

    def get(self, cache_id, default = None):
        try:	# move_to_end() will KeyError if not in the dictionary
            self.move_to_end(cache_id, last = True)
            self.hits += 1
            return self[cache_id]
        except KeyError:
            self.misses += 1
            return default



def groups_to_str(groups: dict[str]) -> str:
    """
    Creates a name out of a list of gropus

    :param list[str]: dictionary keyed by groupname, values being
      lists of names

    :returns str: formatted string `GROUP:TARGET,TARGET,... GROUP:TARGET,TARGET,...`
    """
    # FIXME: move to commonl.format_dict_as_str()
    l = []
    for name, target_list in groups.items():
        l.append(f"{name}:{','.join(target_list)}")
    return ' '.join(l)



class tc_run_c(tcfl.tc_info_c):
    """Defines a testcase execution

    Contains all the information relative to the execution of a
    testcase in an specific Axes Permutation and target group.

    The orchestrator has determined a particular axes permutation for
    executing a testcase and decided a target group (if it requires
    targets) where to run it:

    - don't want to pack this into tc_info_c because this shall
      contain only the orchestrator specific info

    - however, the result is in tc_info_c, so at the end we need one
      instance per run anyway

    - so pass as argument the "parent", copy its fields

    :param tcfl.tc_info_c testcase: testcase to run

    :param int apid: Axis Permutation ID, from the axes the testcase
      declares and those specified by the user

    :param dict axes: dictionary keyed by axis name with the values
      assigned to each for the given axis permutation.

    :param dict target_group: dictionary keyed by target role name of the
      targets used for this execution.

      Eg: if this testcase needed one interconnect target *ic* and two
      targets (*target* and *target1*), the orchestrator might have
      assigned to specific targets after allocating them:

      >>> { "ic": FIXMENETWORK1, "target": MACHINE1, "target1": MACHINE2 }

    """
    # FIXME: move all result info from tc_info_c
    def __init__(self,
                 testcase: tcfl.tc_info_c,
                 apid: int,
                 axes: dict,
                 tgid: int = None,
                 targets: dict = None):

        # hack shallow copy
        for attr, val in testcase.__dict__.items():
            setattr(self, attr, val)

        self.apid = apid
        self.axes = axes
        self.tgid = tgid
        self.targets = targets



class executor_c(contextlib.AbstractContextManager):
    """Testcase orchestrator

    Run one or more testcases in the targets available

    :params str logdir: (optional; default *None*, current) where to
      write logs to

    :params str tmpdir: (optional; default *None*, will be generated
      and deleted when done) where to write temporary files to.

    :params bool remove_tmpdir: (optional; default *None*) wether to
      remove the temporary file on completion.

      - *None*: will remove if *tmpdir* was *None* and we created it
      - *True*: will always remove
      - *False*: will never remove

    :param List[str] testcase_paths: (optional, default *None* which
      scans current directory recursively looking for testcases) list
      of filenames or directory paths that might contain testcases to execute.

      These can be any type of testcase for which there is a driver
      that can load and run it.

    :param List[str] testcase_manifests: list of filenames to testcase
      manifests that contain list of testcase files or path to scan
      for testcases.

      These are added to those in *testcase_paths* and treated the same.

    :param str testcase_filter_spec: (optional; default *None*)
      boolean expression to filter testcases that want to be
      included in execution.

    Other params as of :class:`tcfl.targets.discovery_agent_c`, are
    meant to refine the targets that will be used.

    Workflow
    --------

    This is done with the following processes:

    - main process (as many instances as needed can be created):

      - scans for servers

      - scans for targets, obtains inventories

      - scans for testcases: each scanned testcase file might spawn a
        server process that is waiting to be told what to do

      - for each testcase, decides which axes permutations are going
        to be spun.

        Eg: if testcase declares it spins on the target's type and
        then on an axes called *versions* with values 1, 2 and 3) and
        there are three targets available, two of type A, one of type
        B (two types), the executor will spin 6 (2 * 3) axes permutations::

          Type  Version
          ----  -------
          A     1
          A     2
          A     3
          B     1
          B     2
          B     3

      - With all the axes permutations decided for each testcase, the
        executor then decides which targets support each execution and
        decides decides pairing of testcases with 1 or more target
        grous based on what they declare they need and what targets
        are available

      - allocates targets for each testcase

      - notify server subprocesses when they can span execution
        subprocesses on each target group and axes permutation

      - send keepalives to the server for each active target group
        until execution completed

    - N testcase server subprocesses: for each discovered testcase,
      and depending on the testcase framework needs and other details

      when discovering each testcase, first thing is discovering its
      axes, so the execution will iterate all the possible
      permutations. (eg: on target type and OSes).

    Each discovered test case will be then run, for each Axes
    Permutation:

    - once with no access to targets (the static run)

    - N (>=0) on each Target Group that satisfies the testcase's
      conditions. N is determined by the user and is normally 1, but
      it can be anything (eg: to always run a testcase 3 times in
      different HW)


    FIXME: complete docs, explain how this works

    """

    def __init__(self,
                 *args,
                 logdir: str = None,
                 tmpdir: str = None,
                 remove_tmpdir: bool = None,
                 testcase_paths: list[str] = None,
                 testcase_manifests: list[str] = None,
                 testcase_filter_spec: str = None,
                 **kwargs
                 ):

        # FIXME:
        #
        # - make usable only once; once run is called, the object
        #   is a goner
        #
        # - make it take discovery agents as arguments, in case we
        #   want to reuse server or target or tc discovery results

        self.allocator_queue = None
        self.allocator_thread = None
        # only accessed on the allocator thread, see _worker_alloc
        ## { RTB: { ALLOCID: {
        ##   groups: GROUPS, state: STATE, testcase: TESTCASE
        ## } } }
        #
        # This is only access from the _worker_allocator() process thread
        self.allocation_map = None
        self.work_queue = None
        self.work_process = collections.OrderedDict()
        contextlib.AbstractContextManager.__init__(self)
        # used by allocator or work threads to cache the PID of their
        # process once they start
        self.pid = None


        # FIXME: add a name option
        self.log = logger.getChild(str(id(self)))

        # lazy imports, only if needed
        import tcfl.mrn
        import tcfl.discovery
        import tcfl.targets
        import tcfl.servers


        # FIXME: a lot of this should be moved to __enter__()?

        # FIXME: all the subsystem setups need to be broken up into async
        # (so far only the trgets one is) and into a discovery agent
        tcfl.servers.subsystem_setup()

        self.target_discovery_agent = tcfl.targets.discovery_agent_c(
            # no projections here, we need all the fields for orchestration
            *args, **kwargs)


        # this is confusing, shall remove tcfl.testcases
        tcfl.discovery.subsystem_setup(
            logdir = logdir,
            tmpdir = tmpdir,
            remove_tmpdir = remove_tmpdir)

        self.target_discovery_agent.update_start()	# get it rolling
        self.testcase_discovery_agent = tcfl.discovery.agent_c()

        # FIXME: split to run/complete
        self.testcase_discovery_agent.run(
            paths = testcase_paths,
            manifests = testcase_manifests,
            filter_spec = testcase_filter_spec,
        )

        if not self.testcase_discovery_agent.tcis:
            names = [ driver.__name__ for driver in tcfl.tc_c._tc_drivers ]
            logger.error("WARNING! No testcases found"
                         f" (tried drivers: {' '.join(names)})")
        self.testcases = self.testcase_discovery_agent.tcis


        # wait for target discovery to complete
        self.target_discovery_agent.update_complete(update_globals = True)

        # FIXME: do this in __init__?
        self._tc_info_setup_all()

        self.axes_permutation_filters = {}

        self.testcases_pending = collections.defaultdict(list)
        self.testcases_completed = collections.defaultdict(list)
        self.testcases_running = collections.defaultdict(list)

        #: Overall result of discovering testcases
        self.result_discovery = tcfl.result_c()
        #: Overall result of executing testcases (includes the
        #: discovery result) -- this allows us to keep tab on all
        #: testcase execution
        self.result = tcfl.result_c()



    # FIXME: make argument
    work_processes = 2


    def axes_permutation_filter_register(self, name, fn):
        """Register an axes permutation filter function that can be
        later used by testcases.

        An axes permutation filter is given a axes permutation to
        decide if it should be considered or not (by returning *True*
        or *False*.

        IMPORTANT: these execute in the contest of the orchestrator
        and are not accessible by the testcase code, so they have to
        be defined in any :ref:`TCF configuration file
        <tcf_client_configuration>` and registered from there.

        >>> def my_filter(axes_permutation):
        >>>     if axes_permutation[0] == 'valA0':
        >>>         return False
        >>>
        >>> executor.axes_permutation_filter_register("my_filter", my_filter)
        >>>

        FIXME: implement somethig to see the list of registered filters
        """
        assert isinstance(name, str), \
            f"name must be a string, got {type(name)}"
        assert callable(fn), \
            f"fn must be a callable, got {type(fn)}"
        self.axes_permutation_filters[name] = fn



    def _testcase_axes_iterate(self, testcase):
        """Iterate over permutations of values for the testcase and its
        target's roles.

        **Internal API for testcase/target pairing**

        This function provides iteration in sequential or random
        orders so that the iteration sequence can be repeated over
        executions if needed.

        The randomization can be controlled with :attr:`axes_randomizer`.

        For example, for a testcase with no targets and initialized
        with

        >>> testcase = tcfl.tc_c(
        >>>     axes = {
        >>>         'axisB': [ 'valB0', 'valB1' ],
        >>>         'axisA': [ 'valA1', 'valA0', 'valA2' ],
        >>> })

        The axes will, internally, be sorted alphabetically or
        numerically to

        >>> {
        >>>     'axisA': [ 'valA0', 'valA1', 'valA2' ],
        >>>     'axisB': [ 'valB0', 'valB1' ],
        >>> }

        and the iteration

        >>> for axes_permutation_id, axes_permutation in testcase.axes_iterate():
        >>>     print(axes_permutation_id, axes_permutation)

        produces::

          0 ['valA0', 'valB0']
          1 ['valA0', 'valB1']
          2 ['valA1', 'valB0']
          3 ['valA1', 'valB1']
          4 ['valA2', 'valB0']
          5 ['valA2', 'valB1']

        while using a random generator would give a pseudorandom sequence.

        If a target role is added to the testcase, any axes asociated
        to that role get taken into account.

        :return: iterator that yields tuples *( AXIS_PERMUTATION_ID,
          [ VALUE0, VALUE1 ... ] )*.

          The axis permutation ID is an integer.

          Each item in the list matches the list of axes names
          returned by :meth:`tcfl.orchestrate.executor_c._tc_axes_names`.

          For axes that correspond to target roles', the name is tuple
          *( ROLENAME, AXISNAME )*. The roles are described by a
          :class:`tcfl.target_c`

        """
        testcase.log.info("iterating over tc+role axes %s",
                          commonl.format_dict_as_str(testcase._axes_all))
        max_integer = testcase._axes_all_mr.max_integer()
        for i in range(max_integer):
            if testcase._axes_randomizer_impl:
                # FIXME: use an FFE/FPE pseudoranzomizer?
                i = testcase._axes_randomizer_impl.randrange(max_integer)
            axes = testcase._axes_all_mr.from_integer(i)

            # use this, not _axes_permutation_filter, so we can just
            # create a method.
            fn = testcase._axes_permutation_filter

            if fn != None:
                if isinstance(fn, types.MethodType):
                    if fn.__self__ == None:
                        r = fn(testcase, i, axes)
                    else:
                        # this was a function that was made a method
                        # (not sure why), undo that
                        r = fn.__func__(i, axes)
                else:
                    r = fn(i, axes)
                if r == False:
                    continue
            # note the Axes Permutation ID here is i; because we
            # always sort the testcase._axes_all dictionary by axis name
            # and axis value, the ordering is always the same
            # execution after execution as long as the axes are the
            # same.
            # Thus, every possible permutation has a unique natural
            # number associated to it (in the range [0, max_integer)).
            yield i, axes



    def _run_testcase_axes_discover(self, tci: tcfl.tc_info_c):
        #
        # Given all the axes a testcase needs to iterate over, go over
        # all their possible permutations (applying limits as needed)
        #
        ap_count = 0
        for axes_permutation_id, axes_permutation in self._testcase_axes_iterate(tci):
            if tci.axes_permutations > 0 and ap_count >= tci.axes_permutations:
                tci.log.error(f"stoping after {ap_count} permutations"
                              " due to knob *axes_permutations*")
                break

            # make a name out of this
            #
            # axes_permutation is a list of axis values (which come
            # from come from values in the inventory or fed in by the
            # user as a parameter) - they come from the axes name, so
            # let's create a dict of axis name / value
            axes_permutation_dict = collections.OrderedDict(zip(
                self._tc_axes_names(tci), axes_permutation))

            tci.log.info(
                f"APID {axes_permutation_id}:"
                f" FIXME scheduling run on axes {commonl.format_dict_as_str(axes_permutation_dict)}")
            # FIXME: now we have an axes permutation -- tell the
            # testcase server to spawn on this APID and then run
            # static
            # - how do we reach the server?
            # - this is APID/static execution; once APID execution is done,
            #   we can go dynamic
            # - FIXME: start allocation before APID/static is done
            #   controlling via variable
            tci_run_apid = tc_run_c(
                tci, axes_permutation_id, axes_permutation_dict)
            # FIXME: set this in some sort of static per APID so we
            # can easily tell when we can start dybamic?
            self._tc_pending(tci_run_apid)
            ap_count += 1
        return ap_count



    def run(self):
        """Run all the testcases, allocating any targets they might need

        This is a single thread process that mainly takes care of
        allocating targets and telling the sub-processes executing the
        testcases what to do.

        The testcase discovery process has spawned those subprocesses
        and they are all waiting for instructions on what to do.

        """
        # this has to
        # - find all the testcases that still need to run
        # - for each testcase, figure out their axis
        # - schedule an static run on each axis permutation
        #
        # current list of allocations per server (pending, active)
        self.allocation_map = collections.defaultdict(dict)
        logger = self.log.getChild("run")

        ts0 = time.time()
        period_keepalive = 5

        # filter testcases that can be run
        #
        # - those what are alredy considered done will be skipped
        #   (normally during discovery something happened and thus they
        #   are considered *completed*).
        #
        # - remember a single filename might have yielded more than
        #   one test-case-infos
        for filename, tcis in self.testcases.items():
            for tci in tcis:
                if tci.result:
                    self._tc_completed(tci)
                    continue
                self.testcases_pending[filename].append(tci)

        # take snapshot of what happened when we discovered testcases,
        # we'll need it later to compute final result
        self.result_discovery = copy.copy(self.result)

        # for each queued testcase, let's discover what axes
        # permutations they need, since a testcase might declare which
        # fields it needs to spin on
        #
        # FIXME: we do this linearly for clarity, might parallelize later
        for _filename, tcis in self.testcases_pending.items():
            for tci in tcis:
                self._run_testcase_axes_discover(tci)

        while True:
            ts = time.time()
            if not self.testcases_pending and not self.testcases_running:
                logger.error(f"no testcases pending nor running; done")
                break

            logger.error(f"FIXME: not implemented")

            # first send the keepalives, it's way more critical
            logger.error(f"INFO pulsing at +{ts-ts0:.1f}s, period {period_keepalive}s")
            if ts - ts0 > period_keepalive:
                self._execute_keepalive()
                ts0 = ts

            time.sleep(period_keepalive/5)

        self._execute_exit()



    def _targets_discover_json(static_filename):
        # Load the target inventory
        # Find out all the keys that we have in the targets
        tcfl.rts = {}
        tcfl.rts_flat = {}
        tcfl.rts_fullid_sorted = []
        with open(static_filename) as f:
            for target in json.load(open(f)):
                fullid = target['fullid']
                # we update so we have both the flat and nested values
                rt = dict(target)
                tcfl.rts[fullid] = rt
                tcfl.rts_flat[fullid] = dict(rt)
                # Note the empty_dict!! it's important; we want to
                # keep empty nested dictionaries, because even if
                # empty, the presence of the key might be used by
                # clients to tell things about the remote target
                tcfl.rts_flat[fullid].update(
                    commonl.dict_to_flat(rt, empty_dict = True))



    def __exit__(self, exc_type, exc_value, traceback):
        self.shutdown()



    def _axes_expand_field(self, testcase, role, field):
        valid_values = set()
        for fullid in tcfl.rts_fullid_sorted:
            target_rt = tcfl.rts_flat[fullid]
            r, _reason = self._spec_filter(testcase, role, role.spec, {},
                                          role.spec_args, target_rt)
            if not r:
                continue
            value = target_rt.get(field, None)
            if value == None:
                testcase.report_info(
                    f"role:{role.role}: {target_rt['fullid']}"
                    f" lacks field {field}", level = 5)
                continue
            valid_values.add(value)
        return sorted(list(valid_values))

    #
    # Testcase subapi (private)
    # -------------------------
    #
    #

    def _tc_info_randomizer_make(self, testcase, r, what):
        """
        Create a testcase randomizer

        **Internal API**

        :param tcfl.tc_info_c testcase: testcase for which we are
          creating the randomizer

        :param r: randomizer to use to sequence axis permutations

          - *sequential* (str): use a sequential randomizer; no
            randomization is done and elements are listed in their
            natural order.

          - *random* (str): use a randomizer with
            :class:`random.Random`.

          - VALUE (str): use a randomizer with
            :class:`random.Random` and feed it as seed *VALUE*.`q

          - object (:class:`random.Random`): use the randomizer
            *object*

        """
        if isinstance(r, str):
            if r == 'sequential':
                return None
            elif r == 'random':
                return random.Random()
            else:
                return random.Random(r)
        if isinstance(r, random.Random):	# internal
            return r
        raise AssertionError(
            f"{testcase.name}: {what}: expecting a string"
            f" ('sequential', 'random' or anything else to use"
            f" as a SEED); got {type(r)}")


    @staticmethod
    def _tc_axes_names(testcase):
        # Return the names of all the axes known for the testcase
        #
        # **Internal API for testcase/target pairing**
        #
        # returns list of axes for the testcase and each target roles.
        return list(testcase._axes_all.keys())



    def _tc_info_setup(self, testcase):
        #
        # initialize tc_info_c specific for executor_c
        #
        assert isinstance(testcase, tcfl.tc_info_c), \
            f"BUG: testcase: expected tcfl.tc_info_c, got {type(testcase)}"

        # FIXME: hack -- tc_info_c shall have very simple stuff so it
        # can be piped, so we need to initialize this when we run
        # FIXME: we need to move all the logging/reporting to tc_run_c
        # anyway
        testcase.log = logger.getChild(testcase.name)

        testcase._axes_randomizer_impl = self._tc_info_randomizer_make(
            testcase, testcase._axes_randomizer, "axes_randomizer")
        if testcase._axes_permutation_filter:
            testcase._axes_permutation_filter_impl = \
                self._axes_permutation_filters[testcase._axes_permutation_filter]
        #
        # Why this is not in tc_info_c? well, because this is very
        # specific to THIS orchestrator, and this allows tc_info_c to
        # be used by other orchestrators
        #
        # for each testcase, expand the values of all the axes it declares
        for role_name, role in testcase.target_roles.items():
            for field, values in role.axes.items():
                if values != None:
                    # this axis has values, we don't need to find them
                    continue
                values = self._axes_expand_field(testcase, role, field)
                testcase.report_info(
                    f"role:{role_name}: axis '{field}' expanded to"
                    f" '{values}' because it was given value *None*",
                    level = 3)
                role.axes[field] = values

            role.axes_from_inventory = role.axes.keys() \
                & self.target_discovery_agent.inventory_keys.keys()

        # now expand the testcase axes
        # FIXME: should be able to do this without this dummy
        dummy = tcfl.target_role_c("dummy")
        for field, values in testcase.axes.items():
            if values != None:
                # this axis has values, we don't need to find them
                continue
            values = self._axes_expand_field(testcase, dummy, field)
            testcase.report_info(
                f"axis '{field}' expanded to"
                f" '{values}' because it was given value *None*",
                level = 3)
            testcase.axes[field] = values

        testcase.axes_from_inventory = testcase.axes.keys() \
            & self.target_discovery_agent.inventory_keys.keys()


        # Now we update the unified list of axes [testcase + target roles's]
        #
        # Note we always have keep this as an ordered dictionary and
        # we sort the keys alphabetically and also the values.
        #
        # This is **important** because when we need to reproduce the
        # permutations by issuing the same random seed, they need to
        # start always from the same order.
        #
        # So ensure the order is always the same: sort everything,
        # don't use sets :/ because we don't have the OrderedSet in
        # the std. Anywhoo, these are short lists, so not a biggie
        testcase._axes_all.clear()
        for k, v in sorted(testcase.axes.items(), key = lambda k: k[0]):
            testcase._axes_all[k] = sorted(list(v))
        for role_name, role in sorted(testcase.target_roles.items(), key = lambda k: k[0]):
            if role.axes:
                for axis_name, axis_data in role.axes.items():
                    testcase._axes_all[( role, axis_name )] = sorted(list(axis_data))
        testcase._axes_all_mr = tcfl.mrn.mrn_c(*testcase._axes_all.values())



    def _tc_info_setup_all(self):
        #
        # Expand the axes for all testcases
        #
        # The testcases, with tcfl.axes() might have declared axes
        # which values need to be extracted from the inventory
        #
        # At this point, we assume we have the full inventory loaded
        # in self.target_discovery_agent, which means we also have all
        # the keys found and possible values in
        # self.target_discovery_agent.inventory_keys.
        for filename, tcis in self.testcase_discovery_agent.tcis.items():
            for testcase in tcis:
                self._tc_info_setup(testcase)



    def _tc_completed(self, tci: tcfl.tc):
        tci.log.info(f"complete: result {tci.result}")
        filename = tci.file_path
        self.testcases_completed[filename].append(tci)
        if tci in self.testcases_pending.get(filename, []):
            # it might not be in here if it was "completed" during
            # discovery
            self.testcases_pending[filename].remove(tci)
        self.result += tci.result


    def _tc_pending(self, tci: tcfl.tc_info_c):
        tci.log.info(f"marked pending for APID ")



    #
    # Target pairing engine / Group iterator
    # -------------------------------------
    #
    # See more descriptions above
    #
    # Code:
    #
    # - role_add(), target(), interconnect(): add a target role to a
    #   testcase; this is how you say a testcase needs a target to run
    #   on (or many)
    #
    # - tc_c.target_axes_iterate(): creates permutations of axes as
    #   specified by the targets
    #
    #     - target_c.permute_axes_itr(): iterates over permutations of
    #       the axes specific to this target role
    #
    # - tc_c.target_group_iterate(): given an axes permutation, iterate over
    #   a list of target groups that match said permutation
    #
    #   - target_c.target_iterator_for_axes_permutation(): creates an
    #     interator over a list of targets that match an axes permutation
    #     for the role.
    #
    #   - spec_filter(): decide if a given target is selected by a filter or
    #     not
    #
    #     -  _spec_filter_target_in_interconnect(): a spec filter that tests
    #        if a target is a member of an interconnect
    #



    # FIXME: rename to _, this shall be internal
    # FIXME: move to target_ext_run -> leave here only the actual
    #        filters, for reference
    @classmethod
    def _spec_filter(cls, testcase, role, spec, target_group, extra_args, target_rt):
        """
        Given a target specification, decide if the *spec* filtering
        selects or rejects it

        **Internal API for testcase/target pairing**

        The *target_rt* dictionary contains all the target's
        inventory, which we can use to filter against; the filter is
        specified as either:

        - a string containing a boolean expression::

            type == "SOMETYPE" and ram.size_gib >= 30

        - or as a callable which will be executed to determine
          ellegibility

        :param tc_c testcase: testcase this role is part of

        :param spec: (string or callable) filter specification

          FIXME: link to description

        :param dict target_group: dictionary keyed by role name of the
          target group that has been already selected. This is used
          mainly when we are selecting a group for an
          interconnect. FIXME:ellaborate.

        :param dict target_rt: entry describing the target we are
          evaluating; this is a dictionary keyed by strings which
          contain the target's inventory.
        """
        assert isinstance(testcase, tcfl.tc_info_c), \
            f"testcase: expected tc_info_c, got {type(testcase)}"
        assert isinstance(role, tcfl.target_role_c), \
            f"role: expected tcfl.target_role_c, got {type(role)}"
        if target_group:
            commonl.assert_dict_key_strings(target_group, "target_group")
        assert isinstance(target_rt, dict)

        if spec == None:
            return True, ""
        if isinstance(spec, str):
            return \
                commonl.expr_parser.parse(spec, target_rt), \
                f"target didn't match condition string '{spec}'"
        if callable(spec):
            r, reason = spec(testcase.target_roles, target_group,
                     role, extra_args, target_rt)
            assert isinstance(r, bool), \
                f"BUG: role:{role.role}: spec function {spec} shall" \
                f" return bool; got {type(r)}"
            return r, reason
        raise ValueError(
            f"role:{role.role} unknown filtering spec {type(spec)}")


    def targets_valid_list(
            self, testcase, valid_targets_cache, role, axes, target_group_ic):
        """List the targets that will match the axis specification and
        the spec for the role

        :param dict axes: values the targets need to match to be
          selected:

          >>> { AXIS1: VALUE1, AXIS2: VALUE2 ... }

          if *AXIS* is in the inventory, then for a target to be
          selected it has to have the key *AXIS* in the inventory
          matching the given value.

        :param dict target_group_ic: dictionary of targets keyed by
          role name that have been alredy selected. The values are
          dictonaries with the target's inventory.

        :returns list(dict): a list of dictionaries, each representing
          a target. Note we return a list insted of an iterator since
          the number of targets is finite and likely < 5000 and makes
          the rest of the code simpler / easier to maintain /
          conceptualize.

        """
        assert isinstance(testcase, tcfl.tc_c), \
            f"testcase: expected tc_c, got {type(testcase)}"
        assert isinstance(role, tcfl.target_c), \
            f"testcase: expected tc_c, got {type(testcase)}"
        commonl.assert_dict_key_strings(axes, "axis")
        if target_group_ic:
            commonl.assert_dict_key_strings(axes, target_group_ic)

        # when we specify values that are in the inventory, then we
        # use those to filter targets we need.
        axes_filter = dict()
        for key, value in axes.items():
            if key in role.axes_from_inventory:
                axes_filter[key] = value

        # Do we have this result looked up already and can we use the
        # cached entry?
        #
        # Generate an ID to cache the result using ALL the parameters
        # the would affect the lookup.
        #
        # We do not use the testcase id because the cache is already
        # testcase-specific [see _worker_tc_run_static()]
        cache_id = commonl.mkid(
            # axes_filter are the only axes used to filter
            "".join(k + str(v) for k, v in axes_filter.items())
            # the seed target group is used to filter ic_spec,
            # so we need to tie to them
            + ( "".join(k + str(v) for k, v in target_group_ic.items())
                if target_group_ic else "")
            + str(role.spec)
            + str(role.interconnect)
            + ( "".join(k + str(v) for k, v in role.spec_args.items())
                if role.spec_args else "")
            + str(role.ic_spec)
            + ( "".join(k + str(v) for k, v in role.ic_spec_args.items())
                if role.ic_spec_args else ""),
            l = role.hash_length
        )

        valid_targets = valid_targets_cache.get(cache_id)
        if valid_targets != None:
            return valid_targets

        # Not cached, let's lookup on each of the targets in the
        # inventory which targets meet the axes filter (they have to
        # contain the values in their inventory that match the
        # axes_filter dict), pass the spec filter and the ic_spec
        # filter.
        valid_targets = set()
        for fullid in tcfl.rts_fullid_sorted:
            target_rt = tcfl.rts_flat[fullid]
            # Does the target contain all the items in @axes  and they
            # match their values?
            # pythonic way to say if the dictionary D is a subset
            # of the dictionary TARGET -- and nope, not the same as
            # D.items() > TARGET.items() <FIXME: not sure why>
            testcase.report_info(f"role:{role.role}: {target_rt['fullid']}"
                                 " considering target", level = 5)
            if not axes_filter.items() <= target_rt.items():
                testcase.report_info(
                    f"role:{role.role}: {fullid}"
                    f" rejecting (doesn't fit axes permutation)",
                    level = 4)
                continue

            # FIXME: we can't just use spec_filter() here because it
            # requires target_roles and target_group, which we don't
            # even have as concept
            r, reason = self._spec_filter(testcase, role, role.spec, target_group_ic,
                                 role.spec_args, target_rt)
            if not r:
                testcase.report_info(
                    f"role:{role.role}: {target_rt['fullid']}"
                    f" rejecting by spec check ({reason})",
                    level = 4)
                continue
            r, reason = self._spec_filter(testcase, role, role.ic_spec, target_group_ic,
                                          role.ic_spec_args, target_rt)
            if not r:
                testcase.report_info(
                    f"role:{role.role}: {target_rt['fullid']}"
                    f" rejecting by interconnect check ({reason})",
                    level = 4)
                continue

            valid_targets.add(target_rt['fullid'])
            testcase.report_info(f"role:{role.role}: {target_rt['fullid']}"
                                 " is a valid target", level = 4)

        # cache this result and done
        valid_targets_cache.set(cache_id, valid_targets)
        return valid_targets


    def _target_group_iterate_random(
            self, targets_available, target_randomizer, groups_seen,
            permutations_max, spin_max):
        spin_count = 0
        # Given a list of roles and the targets available to fill those
        # roles, iterate to fill them out picking up targets at random
        # from each set of targets available.
        #
        # Basically this is producing permutations.  We can't use
        # itertools.product() because it will produce a lot of entries
        # that are invalid (since they will repeat entries) or
        # itertools.permutations() because (a) each of our rows/digits
        # might have different number targets.
        #
        # To avoid repeating using a target twice (roleA has target1 means
        # that roleB can't take target1, so if target1 is both in the list
        # of roleA and roleB available targets and we pick it for roleA,
        # then when we are picking for roleB, we need to remove it.
        #
        # Keep track of target groups selected and skip over those
        # discarded/already considered. Keep track of how many time we
        # spun without finding
        #
        # At some point we might be finding the same groups over and over
        # again; we set up a maximum limit of empty spins (*spin_max*)
        # that if we reach it, we consider we won't be able to find
        # more. Since the usage model of this is not to be complete, but
        # generate problaly < 20 permutations, this is usually good enough.
        spin_count = 0
        if not targets_available:
            yield 0, {}
            return spin_count
        for _ in range(permutations_max):
            target_group = collections.OrderedDict()
            if spin_count > spin_max:
                # this means we are having a hard time finding a new valid
                # permutation that has no repeated items, so we just give
                # up--we are not looking for completeness, but for a fast
                # algorithm to generate random target groups
                print(f"maximum spins {spin_max} reached")
                return spin_count

            selected = set()
            for role_name, targets in targets_available.items():
                targets_to_pick_from = list(targets - selected)
                if not targets_to_pick_from:
                    #print(f"DEBUG [ENDCONDITION] no more targets available for target role '{role_name}'"
                    #      f" after assigning"
                    #      f" {' '.join(k + ':' + v for k, v in target_group.items())}")
                    return

                target_name = target_randomizer.choice(
                    sorted(tuple(targets - selected)))
                selected.add(target_name)
                target_group[role_name] = target_name
            # We use a hash for the group ID instead of calculating it's
            # integer index (which we could do as a multiple radix
            # number).
            #
            # Rationale: if the next time we execute, some targets are not
            # available or more targets are available, the multiple radix
            # number would have different radixes and all the indexes
            # would change, so we would not be able to see the same
            # groupid numbers even if we are executing on the same
            # targets.
            #
            # By IDing by hashing on the names, we are inmune to that impact.
            groupid = commonl.dict_mkid(target_group, tcfl.target_c.hash_length)
            spin_count += 1
            if groupid in groups_seen:
                continue
            groups_seen.add(groupid)
            spin_count = 0
            yield groupid, target_group

        return spin_count


    def _target_group_iterate_sorted_recurse(
            self, target_group, targets_available, groups_seen,
            selected, spin_count, spin_max):
        # Implementing this recursive to the number of roles is way
        # simpler, as rare will be the case where we have > 2k roles
        # which would start straining the stack

        role, targets = targets_available[0]
        #print(f"DEBUG{depth}  start role:{role} {targets} valid {' '.join(sorted(targets - selected))}")
        # Note this SORT is key here--we use sets, so we can easily
        # remove what has been picked already, but then we always want to
        # iterate in sorted order--so we get repeateable results.
        for target in sorted(targets - selected):
            if spin_count > spin_max:
                # this means we are having a hard time finding a new valid
                # permutation that has no repeated items, so we just give
                # up--we are not looking for completeness, but for a fast
                # algorithm to target groups.
                print(f"maximum spins {spin_max} reached")
                #print(f"DEBUG{depth}  end {target_group} {selected}")
                return spin_count

            _selected = set(selected)
            _selected.add(target)
            _target_group = collections.OrderedDict(target_group)
            _target_group[role] = target
            if len(targets_available) > 1:
                spin_count = yield from self._target_group_iterate_sorted_recurse(
                    _target_group, targets_available[1:], groups_seen,
                    _selected, spin_count, spin_max)
            else:
                # See the documentation on _target_group_iterate_random()
                # on why we use a hashid vs integer index for the target
                # group ID.
                groupid = commonl.dict_mkid(_target_group, tcfl.target_c.hash_length)
                if groupid in groups_seen:
                    #print(f"DEBUG ERROR groupid {groupid} seen for non randomized? {spin_count}")
                    spin_count += 1
                    continue
                groups_seen.add(groupid)
                spin_count = 0
                yield groupid, _target_group
        #print(f"DEBUG{depth}  end NOS {target_group} {selected}")
        return spin_count


    def _target_group_iterate_sorted(self, targets_available,
                                     groups_seen, permutations_max, spin_max):
        # Given a list of roles and the targets available to fill those
        # roles, iterate to fill them out picking up targets at in
        # alphabetical order from each set of targets available.
        #
        # The easiest way to do this is recursively, and since the number
        # of roles is usually going to be low, it won't affect the stack
        # too much.
        spin_count = 0
        if not targets_available:
            yield 0, {}
            return spin_count

        for _ in range(permutations_max):
            target_group = collections.OrderedDict()
            already_selected = set()
            spin_count = yield from self._target_group_iterate_sorted_recurse(
                target_group, list(targets_available.items()), groups_seen,
                already_selected, spin_count, spin_max)
            if spin_count > spin_max:
                # this means we are having a hard time finding a new valid
                # permutation that has no repeated items, so we just give
                # up--we are not looking for completeness, but for a fast
                # algorithm to group targets.
                print(f"LOG:WARNING maximum spins {spin_max} reached")
                return spin_count
        return spin_count


    def target_group_iterate(
            self, testcase, valid_targets_cache,
            axes_permutation_id, axes_permutation,
            interconnects, target_randomizer,
            # FIXME: rename to target_group_ic
            target_group_seed = None):
        """
        Given an axes permutation, iterate over groups of targets that
        satisfy those axes and the conditions of each individual role.

        **Internal API for testcase/target pairing**

        Decide which targets can fulfill each role and with that
        information, give it to the random or sequential iterator to
        generate permutations of role/targetname pairs. Note they are
        permutations, so there will be no targets used twice on each
        group (eg: *targetA* assigned to both *role1* and *role2*)

        :param int axes_permutation_id: unique identification for the
          axes permutation

        :param list(str) axes_permutation: list of values for the
          axes; the axis names are as returned by
          :meth:`tcfl.orchestrate.executor_c._tc_axes_names`.

        :param bool interconnects: if *True* consider only the roles
          that refer to interconnects. Otherwise consider targets that
          are not interconnects.

        :param random.Random target_randomizer: object to randomize the
          target group iteration:

          - *None*: iteration will be in strict alphabetical order of
            the target role names and target names.

          - *random.Random()*: a a pseudo random object with the
            default seed (based on system's time or whichever is the
            Python default; see :func:`random.seed`) which will
            provide a random sequence of targets assigment to roles.

          - *random.Random(SEED)*: creates pseudo random object with
            the given seed, which will provide a random sequence of
            target assignemnt to roles which can be reproduced feeding
            the same *SEED* value.

        :param dict target_group_seed: dictionary keyed by role name
          (string) of targets that have been already selected.

          This is used when we are looking for a group of targets that
          match certain conditions but also need to match
          interconnectivity (such of being connected to one or more
          networks). See
          :meth:`target_group_iterate_for_axes_permutation`

        :return: yields an interator that produces

          - a string with the target group ID (this is a base32 hash;
            see :data:`tcfl.target_c.hash_length` for information
            on length vs collisions)

          - a dictionary with key/value *ROLENAME:TARGETNAME*

          Stops the generation when there are no more permutations to
          generate, or when it has tried more than :data:`spin_max`
          times to generate a group and it has yielded an empty group.

        :raises RuntimeError: If there are not enough targets to fill out a group,

        """
        # no help on error here, internal API, this should never trip
        assert isinstance(valid_targets_cache, cache_c)
        assert isinstance(axes_permutation_id, int)
        assert isinstance(axes_permutation, list)
        assert isinstance(interconnects, bool)
        if target_randomizer != None:
            assert isinstance(target_randomizer, random.Random)
        if target_group_seed != None:
            commonl.assert_dict_of_strings(target_group_seed, "target_group_seed")

        # map
        #
        # AXIS1VALUE AXIS2VALUE...(ROLEA,AXIS5)VALUE5..(ROLEA,AXIS6)VALUE6
        #
        # to the axes_names variable to decide which one belongs to a
        # role into a per-role dictionary *target_axes*
        #
        # [ROLEA][AXIS5] = VALUE5
        # [ROLEA][AXIS6] = VALUE6
        # ...
        # [ROLEC][AXIS31] = VALUE31
        # ...
        #
        # *axes_permutation* is a list of values for each axis in
        # *axes_names*
        #
        # Note the type (OrderedDict) is important for ordering
        # because we want to keep it stable from invocation to
        # invocation and the order at the end of the day is given by
        # tcfl.orchestrate.executor_c._tc_axes_names() which takes it
        # from tc_c._axes_all.
        #
        # FIXME: rename target_axes role_axes?
        count = 0
        axes_names = self._tc_axes_names(testcase)
        target_axes = collections.OrderedDict()
        for value in axes_permutation:
            name = axes_names[count]
            count += 1
            if not isinstance(name, tuple):	# testcase axis, ignore
                continue
            role = name[0]
            axis_name = name[1]
            target_axes.setdefault(role, {})[axis_name] = value

        # now, for each role, given the conditions from the axes and
        # the target role's per-target spec, filter which targets are
        # valid note here we just get a list, since we know the number
        # of targets are a finite length of maybe tops a few thousand
        # items in a very large deployment.
        targets_valid = collections.OrderedDict()
        roles = []
        permutations_max = 1

        for role, axes in target_axes.items():
            # if we are only considering interconnects, do only
            # interconnects, otherwise only non-interconnects
            if role.interconnect != interconnects:
                continue
            roles.append(role.role)
            targets_valid[role.role] = self.targets_valid_list(
                testcase, valid_targets_cache, role, axes, target_group_seed)
            if not targets_valid[role.role]:
                testcase.report_info(
                    f"APID {testcase.axes_permutation_id} cannot find any suitable target for"
                    f" role:{role.role}"
                    f" axes {' '.join(k + ':' + str(v) for k, v in axes.items())}",
                    level = 3)
                return
            permutations_max *= len(targets_valid[role.role])

        groups_seen = set()

        for role_name, targets in targets_valid.items():
            assert isinstance(targets, set), \
                f"targets_valid[{role_name}]: expected set of target" \
                f" names, got {type(targets)}"

        # Ok, let's iterate -- note if we want it random or
        # sequential, the algorithms are different enough in terms of
        # complexity that it is easier to make it one sequential, one
        # recursive...soo
        if target_randomizer:
            yield from self._target_group_iterate_random(
                targets_valid, target_randomizer,
                groups_seen, permutations_max, spin_max = tcfl.target_c.spin_max)
        else:
            yield from self._target_group_iterate_sorted(
                targets_valid, groups_seen,
                permutations_max, spin_max = tcfl.target_c.spin_max)
        return



    def target_group_iterate_for_axes_permutation(
            self, testcase, valid_targets_cache):
        """
        Interate over target groups that match a particular axes permutation

        **Internal API for testcase/target pairing**

        FIXME
        """
        axes_permutation = list(testcase.axes_permutation.values())
        axes_permutation_id = testcase.axes_permutation_id

        # if there are no interconnects, this iterator will yield
        # nothing and we'll catch it in the while True loop below
        ic_group_iterator = self.target_group_iterate(
            testcase, valid_targets_cache,
            axes_permutation_id, axes_permutation,
            True, testcase._target_group_randomizer)

        # store different target_group_iterators that are associated
        # to a permutation of interconnect targets
        target_group_iterators = dict()

        iterate_ics = True
        spin_count = 0
        spin_max = 3000
        while True:
            if spin_count > spin_max:
                self.log_alloc(f"DEBUG  spun {spin_max} times without finding a valid target group")
                break
            if iterate_ics:
                try:
                    groupid_ic, target_group_ic = next(ic_group_iterator)
                    testcase.report_info(
                        f"APID {testcase.axes_permutation_id}"
                        f" ICGID {groupid_ic}"
                        f" interconnects: {' '.join(r + ':' + t for r, t in target_group_ic.items())}",
                        level = 2)
                except StopIteration:
                    testcase.report_info(
                        f"APID {testcase.axes_permutation_id}"
                        " all interconnect groups iterated")
                    break
                if target_group_ic == {}:
                    # We have no interconnects, so don't try on next run
                    iterate_ics = False

            # groupid_ic is enough to tie the target_group_iterator to
            # the group of ICs descripted by the ic_group_iterator,
            # since the rest of the parameters will NOT change
            if groupid_ic in target_group_iterators:
                target_group_iterator = target_group_iterators[groupid_ic]
            else:
                target_group_iterator = self.target_group_iterate(
                    testcase, valid_targets_cache,
                    axes_permutation_id, axes_permutation,
                    False, testcase._target_group_randomizer,
                    target_group_seed = target_group_ic)
                target_group_iterators[groupid_ic] = target_group_iterator

            try:
                groupid, target_group = next(target_group_iterator)
                target_group.update(target_group_ic)
                if testcase.target_group_filter and testcase.target_group_filter(
                       groupid, groupid_ic, target_group) == False:
                    continue
                yield groupid, groupid_ic, target_group
                # reduce 20% our spin count
                spin_count *= 0.80
            except StopIteration:
                spin_count += 1		# ops, out of targets, no group
                testcase.report_info(
                    f"APID {testcase.axes_permutation_id} ICGID {groupid_ic}:"
                    f" no more targets for interconnect group ({int(spin_count)} spins)",
                    level = 2)
                if iterate_ics == False:	# if no interconnects...
                    break			# ... then we are done
                continue


    #
    # Executor Work dispatching
    # -------------------------

    def _worker_axes_discover(self, testcase):
        ap_count = 0
        for axes_permutation_id, axes_permutation in self.axes_iterate(testcase):
            if testcase.axes_permutations > 0 and ap_count >= testcase.axes_permutations:
                testcase.log(f"stoping after {ap_count} permutations"
                             " due to knob *axes_permutations*")
                break
            axes_permutation_dict = collections.OrderedDict(zip(
                self._tc_axes_names(testcase), axes_permutation))
            _testcase_ap = testcase._clone()

            _testcase_ap.axes_permutation = axes_permutation_dict
            _testcase_ap.axes_permutation_id = axes_permutation_id
            _testcase_ap.id += "-" + str(axes_permutation_id)
            _testcase_ap.report_info(
                f"APID {axes_permutation_id}:"
                f" scheduling run on axes {commonl.format_dict_as_str(axes_permutation_dict)}")

            self.work_queue.put((
                "_worker_tc_run_static", _testcase_ap,
                axes_permutation_id, axes_permutation_dict
            ))
            ap_count += 1


    # FIXME:REMOVE:UNUSED
    def _worker_tc_run_static(self, testcase,
                              axes_permutation_id, axes_permutation_dict):
        testcase.report_info(f"running _worker_tc_run_static APID {axes_permutation_id}")
        testcase._run_static()

        if not testcase.target_roles:
            # this is a static testcase, so we don't need to allocate
            # targets ... hence we done here.
            return

        # Create a cache specifict to this invocation--why here only?
        # because this way we don't have to pass the cache across
        # processes (which won't be that needed anyway) and this way
        # the cache is automatically specific to this testcase.
        #
        # Note anyway this coming for loop is going to be the main
        # user of all the cached content.
        valid_targets_cache = cache_c()

        # So, to backtrack, this being called for a single permutation
        # of AXES (eg: the set of this OS version, that FIRMWARE
        # version, this PARAMETERX value)
        #
        # Now we need to run M copies of this testcase, each on a
        # target group, ideally as disjoint from the rest as possible;
        # we call those each a tg-permutation. M comes from
        # testcase.target_group_permutations. Normally it is 1. So we
        # need to find M target groups where to run it.
        #
        # FIXME: disjointness....this might not be possible at all in
        # a practical way for test groups that repeat many
        # targets or when we don't have enough targets--the sollution
        # in this case might be to just overallocate more.
        #
        # Because we don't know what's going to be free or not
        # (because by the time we explore them, they might be taken
        # when we go for it), we just ask for way more target groups
        # (the overallocation factor) especulatively.
        #
        # We get queued up to allocate individual targets and things
        # get spread around; when the right resources get allocated
        # for M target groups to execute the testcase, we release the
        # left (which might still be queued).
        #
        # Overallocation factor: how many target groups we try to
        # allocate FIXME: this needs to be made a factor of how many
        # targets are in the groups
        if testcase.target_group_permutations == 0:
            # this wants us to use all the possible target
            # permutations

            # FIXME: this needs a safety cutoff so that only if you
            # pass something
            # --yes-I-really-know-what-I-am-doing-let-me-run-1-trillion-target-groups
            # this doesn't go bananas on runing permutations until the
            # end of time. legacy -P safety cutoff.
            target_group_counter = itertools.count()
            limit = 'all'
        else:
            # by default overallocate
            tg_allocation = int(
                testcase._target_groups_overallocation_factor
                * testcase.target_group_permutations)
            target_group_counter = range(tg_allocation)
            limit = f'{tg_allocation} [overallocated from {testcase.target_group_permutations} target group permutations]'

        testcase.report_info(f"will spin {limit} target groups")
        # create an iterator to spin up target groups
        target_group_iterator = self.target_group_iterate_for_axes_permutation(
            testcase, valid_targets_cache)

        groups = collections.OrderedDict()
        for tg_count in target_group_counter:

            # this thing has to allocate targets and then keep running
            # with the allocated targets, so generate the target groups
            # and give them to the allocator thread to allocate and keep
            # alive; when the allocation is ready, it'll queue up a job
            # for this to execute

            # FIXME: some of them might not need to be allocated
            # (acknoledge target_c.acquire)

            try:
                groupid, groupid_ic, target_group = next(target_group_iterator)
                group_name = f"{testcase.axes_permutation_id}.{groupid_ic}.{groupid}"
                # FIXME: here we need to keep the roles info
                groups[group_name] = target_group
                testcase.report_info(
                    f"{axes_permutation_id}#{tg_count} will request {group_name}"
                    f" {' '.join(k + ':' + v for k, v in target_group.items())}",
                    level = 1)

            except StopIteration:
                testcase.report_info(
                    f"early stop after {len(groups)} allocation groups"
                    f" [wanted {limit}]")
                break

        if groups:
            testcase.report_info(
                f"requesting allocation of {len(groups)} target groups")
            self.allocator_queue.put((
                commonl.origin_get(2),
                "_worker_alloc_create", testcase, groups ))

        # so nothing else happens here; the allocator thread has been
        # told to create an allocation for those groups on behalf of
        # testcase; when it is done allocating them it will schedule a
        # call on _worker_tc_run_tg() [see _worker_alloc_create() and
        # _worker_alloc_keepalive()]. Bye.


    def _allocator_remove_schedule(self, allocations):
        # testcase._allocations_complete is a dictionary
        #
        ## { GROUPNAME: { ( rtb.aka, allocid ) } }
        self.allocator_queue.put(( commonl.origin_get(2),
                                   "_worker_allocs_remove", allocations ))


    def _worker_tc_run_tg(self, testcase):
        role_name = 'target'
        testcase.report_info(
            f"running eval APID {testcase.axes_permutation_id}#{testcase.target_group_permutations}"
            f" on allocations {' '.join(f'{role_name}:{target.fullid}[{target.allocid}]' for role_name, target in testcase.target_roles.items()) }")

        # resolve the target's rtb links, now that there is no more
        # cross-process
        # FIXME: maybe just make it a property and calculate on the run?
        for role_name, target in testcase.target_roles.items():
            target.rtb = tcfl.rtb_c.rtbs[target.rtb_aka]

        # We are done executing, we do not need the allocation anymore, wipe it.
        #
        # We do it the  allocator thread, to simplify the management
        # of the data structues.
        # FIXME: support retrying N times after block
        self._allocator_remove_schedule(testcase._allocations_complete)
        testcase._allocations_complete = None


    def log_worker(self, *args, **kwargs):
        print(f"DEBUG:worker:{self.pid}: ", *args, **kwargs)

    def _worker_dispatcher(self):
        self.pid = os.getpid()

        while True:
            work_entry = self.work_queue.get()
            self.log_worker(f"dispatching {work_entry}")
            if work_entry == "EXIT":
                self.log_alloc("exiting")
                #self.allocator_queue.task_done()	# yup, twice
                self.work_queue.task_done()
                return
            fn = work_entry[0]
            # Yeah, we use names -- because this way we don't try to
            # pickle the whole executor object between the processes
            # and also forces us to unroll this, which makes the code
            # clearer instead of doing getattr(self, fn)(work_entry[1:])
            if fn == "_worker_axes_discover":	# FIXME:REMOVE:UNUSED
                self._worker_axes_discover(work_entry[1])
            elif fn == "_worker_tc_run_static":
                self._worker_tc_run_static(work_entry[1], work_entry[2],
                                           work_entry[3])
            elif fn == "_worker_tc_run_tg":
                self._worker_tc_run_tg(work_entry[1])
            else:
                self.log_worker(f"ERROR: unknown dispatch {work_entry}")
            if work_entry:
                self.work_queue.task_done()


    # Allocation and keepalive
    # ------------------------
    #
    # All starts with the _worker_allocator() thread; we queue
    # requests in self.allocator_queue() to:
    #
    #  - create an allocation [goes to _worker_alloc_create()]
    #  - remove an allocation [goes to _worker_allcos_remove()]
    #  - exit
    #
    # it also periodically calls the servers to keepalive our
    # reservations and be notified of state changes
    # [_worker_alloc_keepalive()]; this will also notice when an
    # allocation of a target group is complete and schedule a testcase
    # to run in a worker process on the target group.
    #
    # Functions called _worker_alloc*() run in the context of the
    # allocation process. They are the only ones who access
    # self.variables.
    #
    # They might run stuff in parallel in threads [_alloc*()], but
    # those won't touch global state. They'll return and the calling
    # thread will update the self.variables
    #
    # FIXME: more here

    def log_alloc(self, *args, **kwargs):
        print(f"DEBUG:allocator:{self.pid}: ", *args, **kwargs)

    def _worker_alloc_launch(self, testcase, group_allocated, target_group):
        # target_group: { ROLENAME: FULLID }
        testcase_tg = testcase._clone()
        testcase_tg.id += "#" + group_allocated	# FIXME: fugly
        # FIXME: keep a register of only what this testcase copy has,
        # so when it is done running it just releases those
        testcase_tg._allocations_complete = dict()
        testcase_tg._allocations_complete[group_allocated] = \
            testcase._allocations_complete[group_allocated]

        allocid_by_rtb_aka = dict()
        for rtb_aka, allocid in testcase._allocations_complete[group_allocated]:
            allocid_by_rtb_aka[rtb_aka] = allocid

        # bind the remote targets to targets roles
        tgnames = []
        for role_name, target_fullid in target_group.items():
            rtb_aka, target_id = target_fullid.split("/", 1)
            testcase_tg.target_roles[role_name]._bind(
                rtb_aka, target_id, target_fullid, allocid_by_rtb_aka[rtb_aka])
            tgnames.append(
                role_name + ":" + target_fullid + "["
                + testcase_tg.target_roles[role_name].allocid + "]" )
        # yes, report with testcase, since we are executing under that context
        testcase.report_info(
            f"ALLOC: {group_allocated}: all subgroups activated;"
            f" will run on {' '.join(tgnames)}")

        self.work_queue.put(( "_worker_tc_run_tg", testcase_tg ))


    def _worker_allocid_active(self, rtb, testcase, allocid, group_allocated):
        #
        # An allocation in a server has become active
        #
        # We know which testcase it belongs too and the server also
        # has told us which group of the N requested for *allocid* was
        # requestde.
        #
        # Look in the testcase's list of pending allocations [filled
        # out by _worker_alloc_create()] and see if we have something complete
        #
        # returns True if the caller is the allocator and needs to
        # stop trying to allocate because we have groups completed
        testcase.report_info(
            f"ALLOC: {group_allocated}:"
            f" allocation {rtb.aka}/{allocid} activated")

        # The allocation should be marked as pending in the testcase;
        # let's verify that's the case and remove it from there
        if group_allocated not in testcase._allocations_pending:
            self.log_alloc(
                f"BUG: {testcase.id}/{rtb.aka}/{allocid}: allocation activated"
                f" for {group_allocated}, which the testcase doesn't have "
                f" as pending")
            self._allocation_map_remove(rtb, allocid)
            return False
        testcase._allocations_pending[group_allocated].remove(( rtb.aka, allocid ))
        testcase._allocations_complete[group_allocated].add(( rtb.aka, allocid ))

        # are there any more allocations pending for this group? then
        # we are done here and keep waiting
        if testcase._allocations_pending[group_allocated]:
            self.log_alloc(f"{testcase.id}/{rtb.aka}/{group_allocated}:"
                           f" allocations still pending:"
                           f" {testcase._allocations_pending[group_allocated]}")
            return False

        # well, all allocations are done, so now we can tell this
        # testcase and ask the work queues to run it
        if testcase.target_group_permutations > 0 \
           and testcase._target_groups_launched >= testcase.target_group_permutations:
            testcase.report_info(
                f"ALLOC: {group_allocated}:"
                f" allocation {rtb.aka}/{allocid} releasing:"
                f" already activated enough groups")

            self._allocator_remove_schedule(
                { group_allocated: { (rtb.aka, allocid ) } }
            )
            return True
        testcase._target_groups_launched += 1

        # well, let's launch the testcase; we need the testgroup so
        # the launcher can fill out the information needed to bind the
        # targets
        am_entry = self.allocation_map[rtb][allocid]
        target_group = am_entry['groups'][group_allocated]

        self._worker_alloc_launch(testcase, group_allocated, target_group)


    def _worker_alloc_create(self, testcase, groups):

        print(f"DEBUG create groups {groups}")

        # Allocate targets for a testcase
        #
        # We are given a testcase that needs N *groups* of targets to
        # run on. We especulative will try to allocate all the groups
        # in *groups* (can be more than N) and then as they are
        # allocated, we'll ask the worker process pool to run
        # testcases on each.
        #
        # Once the N testcase copies are running each on their group,
        # we cancel the leftover allocations.
        #
        # Note we might be scheduling groups across servers, so we
        # split the groups across servers to submit a single request
        # per server. We track by group name (which are unique to this
        # testcase) and we get an allocid for each request for M
        # groups in server X
        #
        # We save that in:
        #
        #  allocation_map[RTB][ALLOCID] = [ GROUPS, STATE, TESTCASE ]
        #
        # this array is private to the allocation process and we
        # *ONLY* modify it there [funcions called _worker_alloc*()] so
        # we don't need to synchornize.
        #
        # Once the allocation requests are placed, we need to wait for
        # the server to tell us they are ready (or timeout). The
        # *_worker_allocator()* thread calls the *_worker_keepalive()*
        # function to check on the server's allocation and continue
        #the process.

        preempt = None # FIXME preempt = self.preempt,
        priority = None	# FIXME: self.priority
        # FIXME: expand with keywords
        #reason = self.reason % commonl.dict_missing_c(self.kws),
        reason = testcase.id
        obo_user = None	# FIXME: obo_user = self.obo

        def _alloc_create_rtb(rtb, groupd):
            # submit an allocation request to a single server
            # Send a request of multiple groups to a single server
            # groupd is a dicionary keyed by group name of lists of
            # targets.
            _seen = set()
            _groups = collections.defaultdict(list)
            # groupd has a list of sets keyed by group name; some of
            # them are identical and the server will reject
            # it.
            #
            # FIXME: WE NEED TO CHANGE THE SERVER TO SUPPORT THIS, OTHERWISE
            # THIS WILL DEADLOCK EASILY
            #
            # Convert to a dictionary of lists (since json can't
            # sequence sets anyway) with no duplicates
            for group_name, targets in groupd.items():
                # ok, this is quite fugly, we need a cheap hash
                hashid = hash(frozenset(targets))
                if hashid not in _seen:
                    _groups[group_name] = list(targets)
                    _seen.add(hashid)
            data = dict(
                queue = True,
                groups = _groups,
            )
            if priority != None:
                data['priority'] = priority
            if preempt != None:
                data['preempt'] = preempt
            if reason != None:
                data['reason'] = reason
            if obo_user != None:
                data['obo_user'] = obo_user

            r = rtb.send_request("PUT", "allocation", json = data)
            state = r.get('state', None)
            if state not in ( 'queued', 'active' ):
                raise RuntimeError(
                    f"allocation failed: {testcase.id}/{rtb.aka}:"
                    f" state {state}: {r.get('_message', 'message n/a')}")
            allocid = r['allocid']
            # even if active, don't call here to check on the
            # testcase, let the main thread do it
            return rtb, allocid, list(_groups.keys()), \
                state, r.get('group_allocated_name', None)


        # group the remote targets by the rtb they are at
        # groups is { GROUPNAME: { ROLE: FULLIDS } }
        # RTB: { GROUPNAME: IDLIST-OF-IDs }
        groups_by_rtb = collections.defaultdict(
            lambda: collections.defaultdict(set))
        for group, groupd in groups.items():
            for _role_name, fullid in groupd.items():
                aka, target_id = fullid.split("/", 1)
                groups_by_rtb[tcfl.rtb_c.rtbs[aka]][group].add(target_id)

        testcase.__init__allocation__()
        with concurrent.futures.ThreadPoolExecutor(len(groups_by_rtb)) \
             as executor:
            rs = executor.map(lambda x: _alloc_create_rtb(x[0], x[1]),
                              groups_by_rtb.items())
            cancel = False
            for rtb, allocid, _groups, state, group_allocated_name in rs:

                testcase.report_info(
                    f"ALLOC: {' '.join(_groups)}:"
                    f" allocation {rtb.aka}/{allocid}"
                    f" created [state:{state}]")
                self.allocation_map[rtb][allocid] = \
                    dict(groups = groups, state = state, testcase = testcase)
                if state == 'active':
                    testcase._allocations_pending[group_allocated_name].add(( rtb.aka, allocid ))
                    r = self._worker_allocid_active(rtb, testcase, allocid,
                                                group_allocated_name)
                    if r:
                        # note that this function might determine we have
                        # created enough groups already, so stop anything
                        # that has started; we still have to go over
                        # the loop for whatever has completed
                        executor.shutdown(cancel_futures = True,
                                          wait = False)
                elif state == 'queued':
                    for _group_name in _groups:
                        testcase._allocations_pending[_group_name].add(( rtb.aka, allocid ))
                    # well done here; when we keepalive against the
                    # server, we'll check on the status of these
                    # queued allocators and act -- read on at
                    # _worker_alloc_keepalive()
                elif state in ( 'invalid', 'removed', 'rejected',
                                'overtime', 'restart-needed', 'timedout' ):
                    self.log_alloc(f'FIXME: state {state} not implemented')
                else:
                    self.log_alloc(f'BUG: unknown state {state}')


    def _allocation_map_remove(self, rtb, allocid):
        if allocid in self.allocation_map[rtb]:
            del self.allocation_map[rtb][allocid]
        else:
            self.log_alloc(
                f"ERROR: {rtb.aka}/{allocid} tried"
                " to remove, but not in the allocation map")
        # if there is nothing, remove it so that the different
        # processes won't try to schedule a run for no reason
        if not self.allocation_map[rtb]:
            del self.allocation_map[rtb]


    def _alloc_delete_allocid(self, rtb_aka, allocids):
        rtb = tcfl.rtb_c.rtbs[rtb_aka]
        # FIXME: we need on call to remove multiple allocids
        try:
            rtb.send_request("DELETE", "allocation/%s" % allocid)
        except requests.exceptions.HTTPError as e:
            self.log_alloc(f"{rtb_aka}/{allocid}: ignoring error removing {e}")
        return rtb, allocid


    def _alloc_delete_allocids(self, rtb_aka, allocids, source = ""):
        rtb = tcfl.rtb_c.rtbs[rtb_aka]
        # FIXME: we need a protocol call to remove multiple allocids
        for allocid in allocids:
            try:
                rtb.send_request("DELETE", "allocation/%s" % allocid)
            except requests.exceptions.HTTPError as e:
                self.log_alloc(f"{rtb_aka}/{allocid}: ignoring error removing"
                               f" {e} {'source:' + source if source else ''}")
        return rtb, allocid


    def _worker_allocs_remove(self, allocations):
        # list(rtb.aka, ALLOCID) allocations: list of allocations to remove
        per_server = collections.defaultdict(set)
        # allocations is a dictionary GROUPNAME: SET-OF-(RTB_AKA,
        # ALLOCID) -- flatten to each allocation per server and call
        # on that
        for group_name, alloc_sets in allocations.items():
            for rtb_aka, allocid in alloc_sets:
                per_server[rtb_aka].add(allocid)

        with concurrent.futures.ThreadPoolExecutor(len(per_server)) \
             as executor:
            rs = executor.map(
                lambda x: self._alloc_delete_allocids(
                    x[0], x[1], source = "allocs_remove"),
                per_server.items())
            # remove from allocator_map, which only these functions
            # can touch
            for rtb, allocid in rs:
                self._allocation_map_remove(rtb, allocid)


    def _alloc_exit_rtb(self, rtb, allocids):
        self._alloc_delete_allocids(self, rtb, allocids, source = "exit_rtb")

    def _execute_exit(self):
        if not self.allocation_map:
            return
        with concurrent.futures.ThreadPoolExecutor(len(self.allocation_map)) \
             as executor:
            executor.map(lambda x: self._alloc_exit_rtb(x[0], x[1]),
                         self.allocation_map.items())

    def _worker_allocator(self):
        self.pid = os.getpid()



    # Executor public API
    def testcase_execute(self, testcase):
        self.work_queue.put(( "_worker_axes_discover", testcase ))

    def wait_for_done(self):
        # FIXME: how to tell all work is done correctly? -- this is missing
        # counting which allocations are pending, etc -- we need to count how
        # many TCs have been started and how many have finished

        # FIXME: this will do the same as _execute_exit(), so call it
        # if need it -- this shall help make an order exit of the
        # executor_c, telling all subprocesses to exit
        self.log.error(f"FIXME: wait_for_done not implemented")


    def _execute_keepalive(self):

        # Run the keepalive process in all the servers we have
        # reservations for; this is used to
        #
        # (a) tell the server we are still interested on those
        #     reservations, don't let them idle out and die--thus if
        #     this process is killed, they'll be recycled
        #
        # (b) be informed of status changes--for example, from queued
        #     -> active meaning we can start to execute a testcase on
        #     a target group
        #
        # This function just executes in one thread per server the
        # keepalive for each and then parallel for all servers and
        # then collects results to udpate global data.


        def _alloc_keepalive_rtb(rtb, allocids):
            # Sends a keepalive for this RTB and minimally process it
            #
            # allocids:
            #
            ## { ALLOCID: { groups: GROUPS, state: STATE, testcase: TESTCASE } }
            #
            # This is running on a thread and can't touch
            # self.variables. It also can't modify the testcase object
            # since other threads could be also operating on the same
            # object. Hence we defer to the main thread to do the lifting.
            #
            # Returns the server and the list of changes [see below]
            # so the _worker_alloc_keepalive() thread can process them
            data = dict()	# to send the server {ALLOCID: EXPECTED_STATE}
            allocid_to_testcase = dict()
            for allocid, allocd in allocids.items():
                state = allocd['state']
                data[allocid] = state
                allocid_to_testcase[allocid] = allocd['testcase']
            if not data:	# shortcut, no allocids, do nothing
                return rtb, {}
            # Send the keepalive request
            #
            # We'll get as response
            #
            ## { ALLOCID: { state: STATE, group_allocated_name: NAME } }
            #
            # for all the allocation IDs that have changed state (and
            # if a group has been allocated, its name).
            changes = {}
            try:
                r = collections.defaultdict(set)
                for allocid, state in data.items():
                    r[state].add(allocid)
                self.log_alloc(
                    f"{rtb.aka}: keepalive for"
                    f" {' '.join(k + ':' + ','.join(v) for k, v in r.items())}")
                changes = rtb.send_request("PUT", "keepalive-v2", json = data)
                # FIXME: verify this is a dictionary
            except requests.exceptions.RequestException as e:
                self.log_alloc(f"FIXME: keepalive ignoring error removing {e}")
                # FIXME: tolerate N failures before giving up
            return rtb, changes

        if not self.allocation_map: 	# there are no active allocations,
            self.log.info("keepalive: skipping, no active allocations")
            return

        ts0 = time.time()
        self.log_alloc("keepalive starting")

        with concurrent.futures.ThreadPoolExecutor(len(self.allocation_map)) \
             as executor:
            rs = executor.map(lambda x: _alloc_keepalive_rtb(x[0], x[1]),
                              self.allocation_map.items())
            # this is iterates over all the ( rtb, to_remove )
            # returned by _alloc_keepalive_rtb which so can access w/o
            # locking
            for rtb, changes in rs:

                for allocid, change in changes.items():
                    am_entry = self.allocation_map[rtb][allocid]
                    testcase = am_entry['testcase']
                    old_state = am_entry['state']
                    # allocid has changed state
                    new_state = change.get('state', None)
                    print(f"DEBUG change {change}")
                    if new_state == 'active':
                        self._worker_allocid_active(
                            rtb, testcase, allocid,
                            # active carries also this property
                            change['group_allocated_name'])
                    elif new_state == 'queued':
                        self.log_alloc(f"FIXME: {rtb.aka}/{allocid}: state changed to {new_state} NotImplemented")
                        self._allocation_map_remove(rtb, allocid)
                    elif new_state in ( 'invalid', 'removed', 'rejected',
                                        'overtime', 'restart-needed', 'timedout' ):
                        # FIXME: kill any running process
                        self.log_alloc(f'FIXME: state {new_state} not implemented')
                        self._allocation_map_remove(rtb, allocid)
                    else:
                        self.log_alloc(f'BUG {rtb.aka}/{allocid}: unknown state {new_state}')
                        self._allocation_map_remove(rtb, allocid)

        self.log_alloc(f"keepalive done in {time.time() - ts0:.1f}s")



    def shutdown(self):
        self._execute_exit()
        self.log.error(f"DEBUG shutdown() not properly implemented, unify with wait_for_done")


    def _debug_run(self, testcase):
        self.testcases.clear()
        self.testcases[testcase.id] = testcase
        self.target_discover()
        testcase.report_info("expanding axes [O(#roles,#axes)]")
        self.axes_expand()
        _tc_info(testcase)

        testcase.report_info("APID (Axes Permutation IDs): iterating Axes Permutations")
        valid_targets_cache = cache_c()
        aps = 0
        tgps = 0
        ts00 = time.time()
        for axes_permutation_id, axes_permutation in self.axes_iterate(testcase):
            # we might want a thread for each of these
            aps += 1

            axis_name_l = []
            count = 0
            for i in testcase._axes_all.keys():
                if isinstance(i, tuple):	# role axis: ( ROLE_NAME, FIELDNAME )
                    axis_name_l.append(f"{i[0]}:{i[1]}={axes_permutation[count]}")
                else:			# testcase axis: FIELDNAME
                    axis_name_l.append(f"{i}={axes_permutation[count]}")
                count += 1
            testcase.report_info(f"APID {axes_permutation_id} {' '.join(axis_name_l)}",
                                 level = 1)

            # FIXME: same as _worker_axes_discover
            testcase.axes_permutation = collections.OrderedDict(zip(
                self._tc_axes_names(testcase), axes_permutation))
            testcase.axes_permutation_id = axes_permutation_id
            if testcase.target_roles:
                # If we want to run N copies, we thread N, but FIXME: couldn't
                # we have it start at a different location in the key space
                # for axes_permutation rather than just go wild?
                iterator = self.target_group_iterate_for_axes_permutation(
                    testcase, valid_targets_cache)

                tgs_per_ap = 0
                for groupid, groupid_ic, target_group in iterator:
                    ts = time.time()
                    testcase.report_info(
                        "will run in target group"
                        f" {axes_permutation_id}.{groupid_ic}.{groupid}"
                        f" {' '.join([ r + ':' + t for r,t in target_group.items() ])}"
                        f" with axes {' '.join(axis_name_l)}")
                    tgs_per_ap += 1
                    tgps += 1
                    if testcase.target_group_permutations > 0 \
                       and tgs_per_ap >= testcase.target_group_permutations:
                        testcase.report_info(
                            f"APID {axes_permutation_id} stoped after generating"
                            f" {tgs_per_ap} target groups (per testcase.target_group_permutations)",
                            level = 1)
                        break
            else:
                testcase.report_info("will run statically (no targets")

        testcase.report_info(
            f"Statistics {len(tcfl.rts_fullid_sorted)} targets, "
            f" {aps} axes permutations, {tgps} target groups in "
            f" {time.time() - ts00:.1f}s")
        testcase.report_info(
            f"Statistics cache size {valid_targets_cache.size}"
            f" hits {valid_targets_cache.hits}"
            f" misses {valid_targets_cache.misses}"
            f" evictions {valid_targets_cache.evictions}")


def _debug_run(testcase):
    logging.basicConfig(level = int(os.environ.get("LOG_LEVEL", 20)))
    tcfl.initialize(config_paths = [ ".tcf" ])
    with executor_c() as executor:
        try:
            executor._debug_run(testcase)
        except Exception as e:
            print(f"DEBUG exception!", file = sys.stderr)
            print(e, file = sys.stderr)
            raise




_subsystem_setup = False

def subsystem_setup(*args, **kwargs):
    """
    Initialize the orchestration subsystem
    """

    global _subsystem_setup
    if _subsystem_setup:
        return

    # there is nothing really to do here, all is packed in the
    # orchestrator object, but we leave this for symmetry and in case
    # we find things that need initialization in the future

    _subsystem_setup = True
