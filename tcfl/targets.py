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
import traceback

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

    def __init__(self, projections = None, targetid: str = None):

        if targetid != None:
            assert isinstance(targetid, str), \
                f"targetid: expected str, got {type(targetid)}"
        self.targetid = targetid

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

        if projections != None:
            self.projections = set(projections)
        else:
            self.projections = None

        self.executor = None
        self.rs = {}



    def _cache_rt_handle(self, fullid, rt):
        # Given a new remote target descriptor rt, insert/update into
        # the local tables indexed by fullif
        #
        # this accesses the *rts* data without locks, to
        # be executed sequential only
        position = bisect.bisect_right(self.rts_fullid_sorted, fullid)
        # make sure we are not dupplicating it
        #
        ##  If x is already present in a, the insertion point
        ##  will be before (to the left of) any existing
        ##  entries.
        #
        # We use _right, but same thing applies -- if we the previous
        # one is the same, then it's a dup, we don't need it.
        #
        if position == 0 or self.rts_fullid_sorted[position-1] != fullid:
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
            lambda server: server.targets_get(
                target_id = self.targetid,
                projections = self.projections),
            tcfl.server_c.servers.values())
        logger.info("server inventory update started")



    def update_complete(self, update_globals = False,
                        shorten_names: bool = True):
        """Waits for the target update process to finish

        :param bool shorten_names: (optional, default *True*)

          The discovery agent object will offer in the objects
          :data:`rts`, :data:`rts_flat`, :data:`rts_fullid_disabled`
          :data:`rts_fullid_sorted` the list of targets discovered, in
          the long format *SEVERAKA/TARGETNAME*.

          If this is *True* (default), then these names get simplified
          to *TARGETNAME* when that target is only accessible via one
          server (so it is a unique name). If accessible via multiple
          servers (eg: SERVERAKA-A/target-1 and SERVERAKA-B/target-1), then
          the long name is maintained.

          If this is *False*, the names are always long.

        """
        for server_rts, server_rts_flat, server_inventory_keys in self.rs:
            #server_rts, server_rts_flat = self.rs.get()
            # do this here to avoid multithreading issues; only one
            # thread updating the sorted list
            for fullid, rt in server_rts.items():
                self._cache_rt_handle(fullid, rt)
            self.rts.update(server_rts)
            self.rts_flat.update(server_rts_flat)
            # server_inventory_keys is a dictionary keyed by flat
            # inventory field name, value a set of seen values--we'll
            # sort it, since it is stored as as dict and Python3
            # defaults to sorted dicts
            for key, values in sorted(server_inventory_keys.items()):
                self.inventory_keys[key] |= values
        logger.info("discovered %d targets from %d servers found",
                    len(self.rts), len(tcfl.server_c.servers))
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
                rt['fullid_always'] = rt['fullid']
                if targetid_counts[rtid] != 1:	# this target appears
                    continue			# more than once, skip
                # rename SERVERSHORTNAME/TARGETNAME -> TARGETNAME
                disabled = rt.get('disabled', False)
                rt['fullid'] = rt['id']		# shorten this, it's unique
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



# COMPAT: removing list[str] so we work in python 3.8
def setup_by_spec(targetspecs: list, verbosity: int = 1,
                  project: set = None, targets_all: bool = False,
                  shorten_names: bool = True):
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

    :param bool shorten_names: see :meth:`update_complete`
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
            f"project: expected set of strings; got {type(project)}"
        project = set(project)	# copy! don't modify caller's

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
        try:
            expr_ast = commonl.expr_parser.precompile(expression)
        except SyntaxError as e:
            raise RuntimeError(
                f"compilation of target filter expression '{expression}'"
                f" failed: {e}") from e

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
    tcfl.targets.subsystem_setup(projections = fields,
                                 shorten_names = shorten_names)

    # filter targets: because this discovery agent is created just for
    # us, we can directly modify its lists, deleting any target that
    # doesn't match the critera

    # the filter() function is fed a filtering agent
    # `tcfl.targets.select_by_ast()`; we use an adaptor function
    # instead of a lambda for clarity, since select_by_ast() function
    # needs the ast expression and targets_all.

    def _filter_rtfullid_by_ast(rtfullid):

        if rtfullid not in tcfl.targets.discovery_agent.rts_flat:
            logger.error(f"BUG/FIXME: {rtfullid} is not in rts_flat")
            return True

        if tcfl.targets.select_by_ast(
                tcfl.targets.discovery_agent.rts_flat[rtfullid],
                expr_ast, targets_all):
            # if the selection matches, we return False so the for
            # loop next block does not remove it from the list, we
            # want to keep it
            return False
        # If the select does not match we return True so the for loop
        # next block removes it from the list
        return True

    for rtfullid in filter(_filter_rtfullid_by_ast,
                           # note we create another list since we are
                           # going to modify it
                           list(tcfl.targets.discovery_agent.rts_fullid_sorted)):
        tcfl.targets.discovery_agent.rts_fullid_sorted.remove(rtfullid)
        if rtfullid in tcfl.targets.discovery_agent.rts: # BUG/FIXME
            del tcfl.targets.discovery_agent.rts[rtfullid]
        if rtfullid in tcfl.targets.discovery_agent.rts_flat: # BUG/FIXME
            del tcfl.targets.discovery_agent.rts_flat[rtfullid]


def _run_fn_on_targetid(
        targetid: str, iface: str, ifaces: list, extensions_only: list,
        fn: callable, *args, **kwargs):
    # call the function on the target; note we create a target
    # object for the targetid and give it to the function, so
    # they don't have to do it.
    #
    # this function has to be separate (not inside
    # run_fn_on_each_targetspec) so we can call it with thread and
    # process pools
    try:
        target = tcfl.tc.target_c.create(
            targetid,
            iface = iface, ifaces = ifaces, extensions_only = extensions_only,
            target_discovery_agent = discovery_agent)
        return fn(target, *args, **kwargs), None, None
    except Exception as e:
        # note we don't print/log here, we let that be done by
        # tcl.ui_cli.run_fn_on_each_targetspec(), since that
        # is a UI matter.
        # FIXME: tcfl API will attach target objects to the exception
        # attachments, which it is a nono because they can't be
        # pickled, so let's remove them until we fix that API
        if len(e.args) > 1:
            attachments = e.args[1]
            if isinstance(attachments, dict):
                for k, v in list(attachments.items()):
                    if isinstance(v, tcfl.tc.target_c):
                        del attachments[k]
        # we can't pickle tracebacks, so we send them as a
        # formated traceback so we can at least do some debugging
        tb = traceback.format_exception(type(e), e, e.__traceback__)
        return None, e, tb


def run_fn_on_each_targetspec(
        fn: callable, targetspecl: list,	# COMPAT: list[str]
        *args,
        iface: str = None,
        # COMPAT: removing list[str] so we work in python 3.8
        ifaces: list = None,
        extensions_only: list = None,
        only_one: bool = False,
        one_per_server: bool = False,
        projections_minimize: bool = True,
        projections = None, targets_all = False, verbosity = 0,
        parallelization_factor: int = -4,
        pool_type: type = concurrent.futures.ThreadPoolExecutor,
        **kwargs):
    """Initialize the target discovery and run a function on each target
    that matches a specification

    This is mostly used to quickly implement CLI functionality, which
    all follows a very common pattern; see for example
    :download:`ui_cli_power.py`.

    :param callable fn: function to call, with the signature::

        >>> def fn(target: tcfl.tc.target_c, *args, **kwargs):
        >>>     ...

    :param bool only_one: (optional; default *False*) ensure the
      target specification resolves to a single target, complain
      otherwise.

    :param bool one_per_server: (optional; default *False*) if *True*,
      when running over multiple targets, will pick only one target
      per server.

      This is useful to do operations that are wide for the server but
      driven via a target interface (eg: storage management).

    :param bool projections_minimize: (optional, default *True*)
      minimize the amount of data we download from the inventory to the
      bare minimum, which is guessed based on the *projections*,
      *verbosity*, *interfaces*, *extensions_only* parameters. To
      ensure the whole inventory is downloaded, set to *False*.

    :param list[str] projections: list of fields to download from the
      inventory; normally this function tries to download as little a
      possible (faster), including:

      - *id*
      - *disabled* state
      - *type*

      If an interface, was specified, also that interface is
      downloaded:

      - *interfaces.NAME*

      Any extra fields (and their subfields) specified here are also
      downloaded; eg:

      >>> [ "instrumentation", "pci" ]

    :param str iface: (optional) target must support the given
      interface, otherwise an exception is raised.

    :param list[str] ifaces: (optional) target must support the given
      interfaces, otherwise an exception is raised.

    :param concurrent.futures._base.Executor pool_type: (optional,
      default :class:`concurrent.futures.ThreadPoolExecutor`); what
      kind of pool will be created to run parallel jobs

      If using :class:`concurrent.futures.ProcessPoolExecutor`, it
      requires the function *fn* to be pickable and thus it won't be
      possible for it to be inside another function and possibly other
      restrictions.

    :param *args: extra arguments for *fn*

    :param **kwargs: extra keywords arguments for *fn*

    *iface* and *extensions_only* same as :meth:`tclf.tc.target_c.create`.

    :returns dict: 0 dictionary of tuples *( result, exception,
      traceback )* keyed by *targetid*; *traceback* is a list of
      strings, each a formatted trace entry.


    Note this function is exactly the same as
    :func:'tcfl.ui_cli.run_fn_on_each_targetspec`; however they differ
    on the return value.

    """
    # FIXME: change keying to be ALWAYS by fullid so clients can use
    # target.fullid to key
    import tcfl.tc

    assert isinstance(targets_all, bool), \
        f"targets_all: expected bool; got {type(targets_all)}"

    with tcfl.msgid_c("ui_cli"):

        if not projections_minimize:
            # force setup_by_spec to download all fields
            project = None
            verbosity = 1
        else:
            project = { 'id', 'disabled', 'type' }
            if iface:
                project.add('interfaces.' + iface)
            if ifaces:
                for _iface in ifaces:
                    project.add('interfaces.' + _iface)
            if extensions_only != None:
                commonl.assert_list_of_strings(
                    extensions_only, "extensions_only", "extension")
                for extension in extensions_only:
                    project.add('interfaces.' + extension)
            if projections:
                commonl.assert_list_of_strings(projections,
                                               "projections", "field")
                for projection in projections:
                    project.add(projection)
        # Discover all the targets that match the specs in the command
        # line and pull the minimal inventories as specified per
        # arguments
        setup_by_spec(
            targetspecl, verbosity,
            project = project,
            targets_all = targets_all)

        # FIXMEh: this should be grouped by servera, but since is not
        # that we are going to do it so much, (hence the meh)
        targetids = discovery_agent.rts_fullid_sorted
        if not targetids:
            return {}

        if one_per_server:
	    # run only on one target per server -> filter the list to
	    # only pick one target per server
            filtered_targetids = []
            seen_servers = set()
            for targetid in targetids:
                rt = discovery_agent.rts_flat[targetid]
                server = rt['server']
                if server in seen_servers:
                    continue
                seen_servers.add(server)
                filtered_targetids.append(targetid)
            targetids = filtered_targetids

        if only_one and len(targetids) > 1:
            raise RuntimeError(
                f"please narrow down target specification"
                f" {' '.join(targetspecl)}; it matches more than one target: "
                + " ".join(discovery_agent.rts_fullid_sorted ))

        processes = min(
            len(targetids),
            commonl.processes_guess(parallelization_factor))

        logger.warning(f"targetspec resolves to %d targets", len(targetids))

        results = {}
        with pool_type(processes) as executor:
            futures = {
                # for each target id, queue a thread that will call
                # _run_on_by_targetid(), who will call fn taking care
                # of exceptions
                executor.submit(
                    _run_fn_on_targetid,
                    targetid, iface, ifaces, extensions_only,
                    fn, *args, **kwargs): targetid
                for targetid in targetids
            }
            # and as the finish, collect status (pass/fail)
            for future in concurrent.futures.as_completed(futures):
                targetid = futures[future]
                try:
                    results[targetid] = future.result()
                except Exception as e:
                    # this should not happens, since we catch in
                    # _run_on_by_targetid()
                    logger.error("%s: BUG! exception: %s", targetid, e,
                                 exc_info = True)
                    # we can't pickle tracebacks, so we send them as a
                    # formated traceback so we can at least do some debugging
                    tb = traceback.format_exception(type(e), e, e.__traceback__)
                    results[targetid] = ( None, e, tb )
                    continue
        return results



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



def subsystem_setup(*args, projections = None, shorten_names: bool = True,
                    tcfl_servers_subsystem_setup_kwargs: dict = None,
                    **kwargs):
    """Initialize the target discovery subsystem in a synchronous way

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

    :param bool shorten_names: see :meth:`update_complete`

    :param dict tcfl_servers_subsystem_setup_kwargs: (optional,
      default *None*) arguments for
      :func:`tcfl.servers.subsystem_setup`; see below for common usage
      of this.

    To discover a single target that is known ahead of time:

    >>> tcfl.targets.subsystem_setup(targetid = "TARGETNAME")

    in general for this case you want to also discover only a single server
    where the target is located, which can be achieved by passing
    arguments for the different subsystems:

    >>> tcfl.targets.subsystem_setup(
    >>>     targetid = "TARGETNAME",
    >>>     tcfl_servers_subsystem_setup_kwargs = dict(
    >>>         tcfl_server_c_discover_kwargs = dict(
    >>>             seed_url = ["https://SERVERNAME:5000" ],
    >>>             ignore_cache = True,
    >>>             loops_max = 0
    >>>         )
    >>>     )
    >>> )

    or just doing separate calls:

    >>> tcfl.servers.subsystem_setup(
    >>>     tcfl_server_c_discover_kwargs = dict(
    >>>         seed_url = ["https://SERVERNAME:5000" ],
    >>>         ignore_cache = True,
    >>>         loops_max = 0
    >>>     )
    >>> )
    >>> tcfl.targets.subsystem_setup(targetid = "TARGETNAME")

    """
    # ensure discovery subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    if tcfl_servers_subsystem_setup_kwargs == None:
        tcfl_servers_subsystem_setup_kwargs = {}
    tcfl.servers.subsystem_setup(**tcfl_servers_subsystem_setup_kwargs)

    # FIXME: move server discovery here, since it is a requirement
    # tcfl.server.discover()

    # discover targets
    global discovery_agent
    discovery_agent = discovery_agent_c(*args, projections = projections, **kwargs)
    discovery_agent.update_start()
    discovery_agent.update_complete(update_globals = True,
                                    shorten_names = shorten_names)

    _subsystem_setup = True
