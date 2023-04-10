#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""
Target handling utilities
-------------------------

Initialize the simple way to do it (synchronous):

>>> import tcfl.targets
>>> tcfl.targets.subsystem_setup()

(this takes care of initializing its dependencies, the server
subsystem and the configuration subsystem).

An asynchronous way to initialize this module:

1. Initialize dependencies:

   >>> import tcfl.servers
   >>> tcfl.servers.subsystem_setup()      # initializes configuration

2. Create a discovery agent

   >>> import tcfl.targets
   >>> discovery_agent = discovery_agent_c()

3. Start the discovery in the background:

   >>> discovery_agent.update_start()      # starts in background
   >>> ... do something else...

4. Wait for the discovery to complete:

   >>> discovery_agent.update_complete(update_globals = True)


Target selecttion specification, *targetspecs*
----------------------------------------------

.._ targetspecs:

A target specification is a boolean expression that allows to
specificy what target/s are to be selected.

It uses values from the target's inventory to decide if a target is a
match or not with the operators are: and, or, not, (, ), ==, !=, <,
<=, >, >= , in and : (regular expression match) (see
:mod:`commonl.expr_parser` for more details).

Each value from the inventory is a symbol (eg:
interfaces.power.AC.instrument); a missing symbol evaluates as
*False*. Thus examples can be:

 - *owner*: evaluates to true on any target that is currently
   allocated to anyone

 - *ram.size_gib > 2 and disks.count > 1*: evaluates to true on any
   target that has any RAM more than 2 GiB and two installed disks.


See also :func:`tcfl.targets.select_by_ast` :mod:`commonl.expr_parser`
for implementation details.

"""
# FIXME:
#
# - needs to support a proper aync Python API
# - the discovery_agent_c object shall be able to take servers from a
#   tcfl.server.discover_agent_c object (pending)

import bisect
import collections
import concurrent.futures
import logging

import commonl.expr_parser
import tcfl
import tcfl.servers

keys_from_inventory = collections.defaultdict(set)
target_inventory = None

logger = logging.getLogger("targets")


class discovery_agent_c:
    """
    Discover targers in a remote server and cache them

    :param list(str) projections: (optional; default all) list of
      fields to load

      Depending on the operation that is to be performed, not all
      fields might be needed and depending on network conditions
      and how many remote targets are available and how much data
      is in their inventory, this can considerably speed up
      operation.

      For example, to only list the target names:

      >>> discovery_agent = tcfl.targets.discover_agent_c(projections = [ 'id' ])
      >>> discovery_agent.update_start()
      >>> discovery_agent.update_complete()

      Only targets that have the field defined will be fetched
      (PENDING: prefix field name with a period `.` will gather
      all targets irrespective of that field being defined or
      not).

    """

    def __init__(self, projections = None):


        #: Remote target inventory (cached)
        self.rts = dict()

        #: Remote target inventory in deep and flat format
        self.rts_flat = dict()

        #: All the keys that have been found in all the targets (flat
        #: key) and all the values collected
        self.inventory_keys = collections.defaultdict(set)

        #: Sorted list of remote target full IDs (SERVER/NAME)
        #:
        #: This is used for iteration algorithms so we can reproduce the
        #: iterations if wished without needing to resort all the time.
        self.rts_fullid_sorted = list()
        self.rts_fullid_disabled = set()
        self.rts_fullid_enabled = set()

        self.projections = projections

        self.executor = None
        self.rs = {}



    def _cache_rt_handle(self, fullid, rt):
        # Given a new remote target descriptor rt, insert/update into
        # the local tables indexed by fullif
        #
        # this accesses the *rts* data without locks, to
        # be executed sequential only
        position = bisect.bisect_left(self.rts_fullid_sorted, fullid)
        if not self.rts_fullid_sorted or self.rts_fullid_sorted[-1] != fullid:
            self.rts_fullid_sorted.insert(position, fullid)
        if rt.get('disabled', None):
            self.rts_fullid_disabled.add(fullid)
            self.rts_fullid_enabled.discard(fullid)
        else:
            self.rts_fullid_disabled.discard(fullid)
            self.rts_fullid_enabled.add(fullid)



    def update_start(self):
        """
        Starts the asynchronous process of updating the target information
        """
        logger.info("caching target information")
        self.rts.clear()
        self.rts_flat.clear()
        self.rts_fullid_sorted.clear()
        self.inventory_keys.clear()
        # load all the servers at the same time using a thread pool
        if not tcfl.server_c.servers:
            logger.info("found no servers, will find no targets")
            return
        if self.executor or self.rs:	# already started
            return
        self.executor = concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers))
        self.rs = self.executor.map(
            lambda server: server.targets_get(projections = self.projections),
            tcfl.server_c.servers.values())
        logger.info("server inventory update started")



    def update_complete(self, update_globals = False, shorten_names = True):
        """
        Waits for the target update process to finish
        """
        for server_rts, server_rts_flat, server_inventory_keys in self.rs:
            #server_rts, server_rts_flat = self.rs.get()
            # do this here to avoid multithreading issues; only one
            # thread updating the sorted list
            for fullid, rt in server_rts.items():
                self._cache_rt_handle(fullid, rt)
            self.rts.update(server_rts)
            self.rts_flat.update(server_rts_flat)
            self.inventory_keys.update(server_inventory_keys)
        logger.info(f"read {len(self.rts)} targets"
                    f" from {len(tcfl.server_c.servers)} servers found")
        self.executor = None
        self.rs = {}

        # shall we flatten IDs? normally all the names are
        # SERVERSHORTNAME/TARGETNAME, so if two servers have the same
        # TARGETNAME, it is easy to determine which one to
        # use. However, sometimes this yields very long names and is
        # not desirable. So unique names, we can refer to them just
        # with the TARGETNAME
        if shorten_names:
            # for each TARGETNAME, count how many times it happens in
            # different servers
            targetid_counts = collections.Counter(rt['id'] for rt in self.rts.values())
            for rtfullid, rt in list(self.rts.items()):
                rtid = rt['id']
                if targetid_counts[rtid] != 1:	# this target appears
                    continue			# more than once, skip
                # rename SERVERSHORTNAME/TARGETNAME -> TARGETNAME
                disabled = rt.get('disabled', False)
                self.rts[rtid] = self.rts[rtfullid]
                del self.rts[rtfullid]
                self.rts_flat[rtid] = self.rts_flat[rtfullid]
                del self.rts_flat[rtfullid]
                self.rts_fullid_sorted.remove(rtfullid)
                bisect.insort(self.rts_fullid_sorted, rtid)
                if disabled:
                    self.rts_fullid_disabled.remove(rtfullid)
                    self.rts_fullid_disabled.add(rtid)
                else:
                    self.rts_fullid_enabled.remove(rtfullid)
                    self.rts_fullid_enabled.add(rtid)

        if update_globals:
            tcfl.rts = self.rts
            tcfl.rts_flat = self.rts_flat
            tcfl.inventory_keys = self.inventory_keys

            tcfl.rts_fullid_sorted = self.rts_fullid_sorted
            tcfl.rts_fullid_disabled = self.rts_fullid_disabled
            tcfl.rts_fullid_enabled = self.rts_fullid_enabled


def select_by_ast(rt_flat: dict,
                  expr_ast: tuple, include_disabled: bool):
    """
    Given a conditional AST expression, return if a target matches it or not.

    :param dict rt_flat: remote target descriptor in flat format (as
       from :data:`tcfl.targets.discovery_agent.rts_flat`), eg:

       >>> tcfl.targets.discovery_agent.rts_flat['SERVER/TARGETNAME']

    :param tuple expr_ast: compiled targetspec AST expression

       >>> expr_ast = commonl.expr_parser.precompile("ram.size_gib > 2")

       The fields in the expression are inventory fields; the expression
       is compiled with :func:`commonl.expr_parser.precompile`. See
       more information on :ref:`targetspecs <targetspecs>`.

    :param bool include_disabled: consider disabled targets or not
       (disabled targets are those that have a *disabled* field set to
       anything)

    :returns bool: *True* if the target matches the conditional
      expression, *False* otherwise

    For example, to use Python's :class:`filter`:

    >>> tcfl.targets.subsystem_setup()
    >>> expr_ast = commonl.expr_parser.precompile("ram.size_gib > 2")
    >>> for rtfullid in filter(
    >>>         lambda rtfullid: tcfl.targets.select_by_ast(
    >>>             tcfl.targets.discovery_agent.rts_flat[rtfullid],
    >>>             expr_ast, False),
    >>>         tcfl.targets.discovery_agent.rts_fullid_sorted:
    >>>     print(f"{rtfullid} matches")

    """
    if not include_disabled and rt_flat.get('disabled', False):
        return False
    if expr_ast and not commonl.expr_parser.parse("", rt_flat, expr_ast):
        return False
    return True



def setup_by_spec(targetspecs: list[str], verbosity: int = 0,
                  project: set[str] = None, targets_all: bool = False):
    """
    Setup the target system and discover just targets that match a
    condition.

    This can be way faster when only a few fields are needed, since
    full inventories don't have to be downloaded. It is useful for
    command line tools that don't need the whole inventory.

    In most conditions, the most basic fields needed are:

    - *id*
    - *disabled*
    - *type*

    which is enough for most operations; f a :ref:`target spec
    <targetspec>` is provided , then the fields needed for evaluating
    it are also pulled.

    Upon return, *tcfl.targets.discovery_agent* is initialized with
    possibly a limited amount of targets and fields as per the
    specifications.

    :param list[str] targetspecs: list of target specifications to use
      to filter (all the target specificatons are ORed together; in
      most cases, a single one is all that is needed)

      See more information on :ref:`targetspecs <targetspecs>`.

    :param int verbosity: (optional; default 0) verbosity the system
      will implement; this is needed so we can calculate which fields
      are to be pulled from the inventories.

      A verbosity higher than 0 needs all the fields from the
      inventory (because it will report on them). A verbosity of zero
      needs only the most basic fields plus those needed to evaluate
      the filter expression.

    :param set[str] project: (optional; default guess) set of fields
      from the inventory to load.

    :param bool targets_all: (optional; default *False*) consider also
      *disabled* targets (ignored by default).

    """
    # let's do some voodoo (for speed) -- we want to load (project)
    # only the minimum amount of fields we need for doing what we need
    # so, guess those.
    if project == None:
        if verbosity >= 1:
	    # we want verbosity, no fields were specified, so ask for
            # all fields (None); makes no sense with verbosity <=1, since it
            # only prints ID, owner
            project = None
        else:
            project = { 'id', 'disabled', 'type' }
    else:
        assert isinstance(project, set), \
            "project: expected set of strings; got {type(set)}"

    # ensure the name and the disabled fields (so we can filter on it)
    # if we are only doing "tcf ls" to list target NAMEs, then
    # we don't care whatsoever by the rest of the fields, so
    # don't get them, except for disabled, to filter on it.
    logger.info(f"original projection list: {project}")
    if project != None:
        project.update({ 'id', 'disabled', 'type' })
        if verbosity >= 0:
            project.add('interfaces.power.state')
            project.add('owner')
    logger.info(f"updated projection list: {project}")

    # parse TARGETSPEC, if any -- because this will ask for extra
    # fields from the inventory, so we'll have to add those to what we
    # are asking from the server
    # we need to decide which fields are requested by the
    # targetspec specification
    expressionl = [ ]
    for spec in targetspecs:
        expressionl.append("( " + spec + " ) ")
        # combine expressions in the command line with OR, so
        # something such as
        #
        #   $ tcf ls TARGET1 TARGET2
        #
        # lists both targets
    if expressionl:
        expression = "(" + " or ".join(expressionl) + ")"
        logger.info(f"filter expression: {expression}")
        expr_ast = commonl.expr_parser.precompile(expression)
        expr_symbols = commonl.expr_parser.symbol_list(expr_ast)
        logger.info(f"symbols from target filters: {', '.join(expr_symbols)}")
    else:
        logger.info("no extra symbols from target filters")
        expr_ast = None
        expr_symbols = []

    # aah...projections -- we want the minimum amount of fields so we
    # can pull the data as fast as possible; need the following
    # minimum deck of fields:
    #
    # - id, disabled
    #
    # - any field we are testing ("ram.size == 32")
    fields = project
    if expr_symbols:		# bring anything from fields we are testing
        if fields == None:
            # if fields is None, keep it as None as it will pull ALL of them
            logger.info(f"querying all fields, so not upating from filter"
                        f" expression ({', '.join(expr_symbols)})")
        else:
            fields.update(expr_symbols)
            logger.info(f"fields from filter expression: {', '.join(fields)}")

    # so now we are actually querying the servers; this will
    # initialize the servers, discover them and them query them for
    # the target list and the minimum amount of inventory needed to
    # filter and display
    if fields:
        logger.info(f"querying inventories with fields: {', '.join(fields)}")
    else:
        logger.info("querying inventories with all fields")
    # FIXME: setup to an specific object and return it?
    tcfl.targets.subsystem_setup(projections = fields)

    # filter targets: because this discovery agent is created just for
    # us, we can directly modify its lists, deleting any target that
    # doesn't match the critera

    for rtfullid in filter(
            lambda rtfullid: not tcfl.targets.select_by_ast(
                tcfl.targets.discovery_agent.rts_flat[rtfullid],
                expr_ast, targets_all
            ),
            list(tcfl.targets.discovery_agent.rts_fullid_sorted)):
        tcfl.targets.discovery_agent.rts_fullid_sorted.remove(rtfullid)
        del tcfl.targets.discovery_agent.rts[rtfullid]
        del tcfl.targets.discovery_agent.rts_flat[rtfullid]



#: Global targets discovery agent, containing the list of discovered targets
#:
#: The list of target full names (*SERVER/TARGETID*):
#:
#: >>> tcfl.targets.discovery_agent.rts_fullid_sorted
#: >>> tcfl.targets.discovery_agent.rts_fullid_disabled
#: >>> tcfl.targets.discovery_agent.rts_fullid_enabled
#:
#: For example, the target data for each target in dictionary format:
#:
#: >>> tcfl.targets.discovery_agent.rts
#:
#: For example, the target data for each target in dictionary format,
#: but also flattened (*a[b]* would look like *a.b*):
#
#: >>> tcfl.targets.discovery_agent.rts_flat
#:
#: Note this gets initializd by tcfl.targets.subsystem_setup()
discovery_agent = None


_subsystem_setup = False



def subsystem_setup(*args, projections = None, **kwargs):
    """
    Initialize the target discovery subsystem in a synchronous way

    Check the module documentation for an asynchronous one.

    Same arguments as:

    - :class:`tcfl.targets.discovery_agent_c`

      Note using *projections* for anything else than just listing
      will limit the amount of information that is loaded from servers
      during the instance lifecycle.

    - :func:`tcfl.config.subsystem_setup`

    Note this initialize all the required dependencies
    (:mod:`tcfl.config` and :mod:`tcfl.servers )` if not already
    initialized).

    """
    # ensure discovery subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    tcfl.servers.subsystem_setup()

    # FIXME: move server discovery here, since it is a requirement
    # tcfl.server.discover()

    # discover targets
    global discovery_agent
    discovery_agent = discovery_agent_c(*args, projections = projections, **kwargs)
    discovery_agent.update_start()
    discovery_agent.update_complete(update_globals = True)

    _subsystem_setup = True
