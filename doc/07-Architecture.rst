=============
 Architecture
=============

The test framework is composed of the following parts:

 * :term:`test case`\s
 * :term:`test case finder` and :term:`test runner`
 * :term:`target broker`
 * :term:`test target`\s

The TCF client
==============

The ``tcf`` client is the frontend to the user; it provides commands
for the user to locate test cases and execute them on targets, as well
as an interface to interact with one or more target brokers and manage
targets.

The ``tcf`` script mainly offers the interaction to the user on the
command line. It just loads its configuration (from
`{/etc/tcf,~/.tcf,.tcf}/conf_*.py`) with pointers to the brokers to
use and interprets the command line to execute whichever action the
user requested. The actual functionality is implemented by modules in
the ``tcfl`` subdirectory:

- :mod:`tcfl.tc`: implements the backbone test case finder and runner
  and the TCF specific testcase-driver; other drivers may be created
  by subclassing :class:`tcfl.tc.tc_c` and adding them with
  :func:`tcfl.tc.tc_c.driver_add`.

- :mod:`tcfl.config`: is a quick wrapper of the configuration
  directives that can be put in TCF's configuration files.

- :mod:`tcfl.ttb_client`: implements the the remote interaction of
  ``tcf`` with the target broker as an HTTP API, using the Python
  ``requests`` module. This API can be used by anyone, not just
  the ``tcf`` script. It also implements the basic glue to be able to
  execute most of those commands via the command line.

  For some target interfaces, those are implemented in the different
  `tcfl.target_ext_*.py` files that implemnt all relative to said
  interface.

The testcase finder and runner
------------------------------

The *tcf run* testcase (`tcfl.tc._run()`) will:

- With `tcfl.tc.testcases_discover()`, find testcases on the given
  locations with all the testcase drivers registered in the system and
  filter them based on command line specification

- With `tcfl.tc._targets_discover()` find all the remote test targets
  available and filter them based on command line specificaton

- for each testcase, determine on which test targets or groups of test
  targets it shall (`tcfl.tc._run_on_targets()`).

  If a testcase requires no target (a *static* testcase), then it is
  assumed to work on the *local* target group.

  This process might include finding many permutations of the same
  group of test targets (eg: targets A, B and C on the roles of
  server, client1 and client2 will be permuted as ABC, ACB, BAC, BCA,
  CAB, CBA by default).

  Depending on the instructions given by the testcase, further
  simplication of the amount of permutations might happen depending on
  the types of targets (eg: if B and C are the same type and the
  testcase indicates that for the role of clients, only one of each
  type shall be considered, this would reduce the permutations to ABC,
  BAC, CAB.

- a test case is any instance of :class:`tcfl.tc.tc_c`

- once a testcase is paired with a group of targets, jobs are spawned
  to a threadpool (which limits the amount of concurency) to run
  `tcfl.tc.tc_c._run()` which will call
  `tcfl.tc.tc_c._run_on_target_group()`.

  This method will sequentially run the six phases of a test case
  (configuration, build, target assignment, deployment to target,
  evaluation, cleanup) by invoking the testcase's class methods
  defined with matchin name (*config\**, *build\**, *deploy\**,
  *cleanup\**). See :class:`tcfl.tc.tc_c` for more details.

  The testcase, in general, will build some software taking as input
  assigned target information, deploy to the target, the *eval\**
  functions will interact with the target to determine if it passes or
  fails and return a result. The :class:`result <tcfl.tc.result_c>`
  object contains a count of passed, failed, blocked or skipped
  testcases that is aggregated by the main process as testcases finish
  execution.

  For evaluation, the system relies on the concept of expectations
  (things that have to happen to pass, things that don't have to
  happen else it fails), implemented by a
  per-testcase/group-of-targets object (the :mod:`expecter
  <tcfl.expecter>`), a loop which ensures what is expected to
  happen happens.


The Test Target Broker
======================

The user configures his client to access one ore more target brokers,
which are daemons running on different machines that provide:

- access to one or more pieces of target hardware on which runtime
  tests can be executed

- means to manage the target hardware (discover, reserve, power
  on/off, deploy software, debug, etc)

Different target hardware has different capabilities and different
ways to do operations; the broker provides abstractions over the
differences for common operations like powering on, off, uploading
firmware or an OS image (when said abstractions make sense), as well
as providing access to hardware-specific details--all these are
implemented by the different drivers that run in the server.

It follows that other interfaces can be easily added by plugins. This
is implemented by either:

- subclassing, which is limited to targets of which all instances will
  share the same interfaces

- dynamic addition of interfaces to each target instance
  (:meth:`ttbl.test_target.interface_add`). See
  (:meth:`ttbl.buttons.interface` as an example of an interface
  implemented on the daemon and it's counterpart,
  :meth:`tcfl.target_ext_buttons.buttons` for the client side).

Note details about the actual drivers that implement the interfaces do
not necessarily belong here and are detailed in the actual driver code.

Daemon internals
----------------

The daemon is implemented in Python, using the Flask framework to
implement the REST API to access the targets. It loosely follows the
WSGI application mode, in which one HTTP request may be serviced by
one process, while the next might be served by another process. The
daemon thus is a collection of multiple processes and no state is kept
internally in it. See `Maintaining state`_ below.

The file ``ttbd`` provides handling of the command line arguments
and setup and then deploys the main Flask loop into a web server,
which takes care of all the HTTP request handling (currently the
Tornado web server).

Flask calls into the different functions decorated with ``@app.route``
which represent calls to manipulate ``ttbd``'s objects. Each of those
functions extracts arguments and translates the call to the internal
representation of the objects (encapsulated in :mod:`ttbl` and
:mod:`ttbl.config`).

In Linux, the daemon is set as a process reaper, so that any child
processes that are alive while their parents died are reassigned to
the daemon (this happens when a subprocess starts a daemon as part of
servicing a request, like for example starting a QEMU target or a
target that needs OpenOCD running in the background while powered up).

The daemon starts two subprocesses:

 - a cleanup thread, that will scan for idle targets to power them off
 - a console-monitor logger, that reads from file descriptors to write
   to log files (more on `Console Management`_ below).

It will then parse configuration files in ``~/.ttbd/conf_*.py``,
obtaining from there more operational parameters and the list of test
targets, which are subclasses of :class:`ttbl.test_target`; this
represents the lowest common denominator of test targets: something
that can be named, acquired (by a user) and released (by the same user
or an admin).

For a test target to be useful, it has to add interfaces (called
*mixin*\s in Python parlance)--and depending on the hardware that the
test target implements or how it is connected, the interfaces will be
implemented on one way or another--however, the client accessing over
the HTTP API needs not to be concerned about those details as s/he
always sees the same interface.

Maintaining state
-----------------

State is maintained in a lightweight filesystem database which is
accessed with the :class:`ttbl.fsdb.fsdb` class.

Each target has a :attr:`ttbl.test_target.fsdb` member that implements
``set()`` and ``get()`` methods to store and access key/value
pairs. They are stored in a state directory given at startup time
(that defaults to ``~/.ttbd/state/TARGETNAME/``). Target drivers shall
use said data member to store data, bearing in mind that their code
might be called again by *another* process and thus the data they need
has to be accessed from the filesystem.

A good rule of thumb is: if a method of a driver for target *T* would
store *X* in ``self.x`` to use it later in another method of the same
driver for target *T*, that *has* to be stored in the file system
database, so instead use::

  self.fsdb.set('KEY', 'VALUE')	# To store
  self.fsdb.set('KEY', None)		# To delete
  value = self.fsdb.get('KEY')	# To retrieve

Note this database is:

- atomic (so multiple processes can set/get without interfering with
  each other)
- geared towards storing small pieces of text

The current implementation uses the target of symbolic links to store
the value, as it is a POSIXly atomic operation that requires very
little overhead. The file name of the symbolic link is the key.
As of such, the data is very much accesible to anyone
that has read access to the directory.

The *mutex* that describes who currently owns a target works
similarly; we could not use POSIX advisory locking because it is tied
to running processes and the daemon works as a loose collection of
processes with undertermined life cycles.

Interfaces
----------

Power control
^^^^^^^^^^^^^

Allows powering on, off resetting or power cycling hardware
(:class:`ttbl.tt_power_control_mixin`).

This interface can be implemented by:

- subclassing :class:`ttbl.tt_power_control_mixin` and overloading
  the methods ``*_do_*()``.

- implementing a power control driver as a subclass of
  :class:`ttbl.tt_power_control_impl` and passing that to
  :class:`ttbl.tt_power_control_mixin`, who will call the
  implementation's ``*_do_*()``'s methods.

  Note these drivers normally interface with physical devices, but
  are also be used to alter the power up sequence (like delay until
  a file or USB device appears in the file system (eg: a serial
  ports' node), start/stop a program (eg: QEMU, OpenOCD), etc...

- same as before, but passing a list of them; this is called a *power
  control rail* and it is very useful when many objects have to be
  powered on or off in order to fire up a target.

  For example: power up a power brick, a device that is connected to
  the target to measure temperature, start a daemon
  process needed to be able to connect to the

There are currently a few implementations:

* QEMU targets (:class:`ttbl.tt_qemu.tt_qemu`) implement power
  control by starting/stopping QEMU daemons.

* `Digital Logger's Web Power Switch 7
  <http://www.digital-loggers.com/lpc.html>`_
  (:class:`ttbl.pc.dlwps7`): network connected controllers, are
  implemented by .

* `YKush power-switch USB hub
  <https://www.yepkit.com/products/ykush>`_ (:class:`ttbl.pc_ykush`):
  These are USB hubs that can completely cut off a USB connected
  device, thus useful for USB-powered devices.

* Manual (:class:`ttbl.pc.manual`): used for testing, allows the user
  to manually power on/off the device based on daemon's printed
  messages.

* Miscellaneous delays: :class:`ttbl.pc.delay` ,
  :class:`ttbl.pc.delay_til_file_appears`,
  :class:`ttbl.pc.delay_til_file_gone`,
  :class:`ttbl.pc.delay_til_usb_device`

Console management
^^^^^^^^^^^^^^^^^^
This interface is used to list serial consoles, read from them
(logging their output) and writing to them. It is implemented by
:class:`ttbl.test_target_console_mixin`.

To log, the daemon starts a logger process
(:func:`ttbl.cm_logger.setup`). When a target is powered up, the
driver instructs the logger process to read from ports attached to the
thread (using :func:`ttbl.cm_logger.spec_add`). The output is stored
in a log file named after the *console* name in the target's state
dir. When a client requests to read from the serial port, it is
actually given the log file.

Writing is currently not implemented, it remains a missing feature.

The class :class:`ttbl.cm_serial.cm_serial` implements a driver for
serial ports (over serial, TCP and others as supported by the PySerial
submodule).

File deployment
^^^^^^^^^^^^^^^

A user can upload files to a TTBD daemon which are stored in a user's
specifc area. This is used for the image deployment interface, for
example, so the user can upload a file than then is going to be
flashed or deployed into a target.

This interface is not target-specific and provides three primitives:
- file upload
- file removal
- file list

*ttbd* implements it directly in Flask routing methods
``_file_upload``, ``_file_delete`` and ``_files_list``.

Image deployment
^^^^^^^^^^^^^^^^

This interface is used to deploy files available to the daemon into a
target.

The implementation takes image types (eg: kernel, initram, rom, ...)
and a file (previously uploaded with the *file deployment* interface)
and how the driver flashes/uploads/deploys said file is target
specific, as well as the interpretation of the image type.

The current target types that are commonly recognized are:

 - *kernel[-CORENAME]*: a zephyr kernel that is flashed to the core
   (or when more than one core is available, flashed so *CORENAME*
   would execute it.

 - *rom*: the ROM/bootloader

Debugging
^^^^^^^^^

This interface is used to start and stop debugging support in the
target, so a debugger can be connected to it to single step, examine
etc. It is implemented by :class:`ttbl.tt_debug_mixin`.

Most commonly this will start some sort of a GDB server for which a
GDB can connect.

The driver implementations can be done subclassing
:class:`ttbl.tt_debug_mixin` and overriding the ``*_do_*()`` functions
or suclassing :class:`ttbl.tt_debug_impl` and feeding that to
:class:`ttbl.tt_debug_mixin`\'s constructor as implementation.

Execution details will vary but they usually open a TCP port per core
in the host that is left open for GDB to connect to (most commonly
OpenOCD and QEMU).

There is then three primitives:

* debug-start: start the debugging support (when this is required);
  when started before powering up the target, the debugger would hold
  the target stopped until the debugger connects and lets it run,
  effectively starting execution. Otherwise, the target will start
  free and when the debugger connects, it will stop.
* debug-stop: stop the debugging support
* debug-info: print information about how to connect to the debugging
  interface (eg: host name and TCP ports, etc).


Things
^^^^^^

Things are entities that can be connected to a target, for example:

- a USB device to a host
- an ejectable drive
- a cable to a receptacle

each driver is responsible to implement the different thing
plug/unplug methods by adding methods and their handling functions to
the :attr:`ttbl.test_target.thing_methods` dictionary.

Then the target client can plug or unplug those things using the
API :meth:`tcfl.tc.target_c.thing_plug` or
:meth:`tcfl.tc.target_c.thing_plug`.

.. _authentication:

Authentication
--------------

There are currently three different authenticating modules that can be
used:

- :mod:`ttbl.auth_localdb.authenticator_localdb_c`: for creating a local
  database of users to authenticate against

- :mod:`ttbl.auth_ldap.authenticator_ldap_c`: for authenticating against an
  LDAP server (use HTTPS!)

- :mod:`ttbl.auth_party.authenticator_party_c`: for authenticating
  anybody coming from a certain host (used for localhost
  authentication)

.. _provisioning_os:
  
Provisioning
============

FIXME: describe better

For targets which are capable of doing so, TCF supports a
*Provisioning mode*, in which the target boots into a *Provisioning
OS* (normally rooted in a network file system) which can be used to
partition and install an OS into the permanent storage.

The most common setup is the target PXE-booting to the Provisioning OS
but other variations are also possible.

Provisioning OS is configured following the steps described in the
:ref:`guide <pos_setup>`. Usage examples are described in FIXME.

.. _security_considerations:

Security considerations
=======================

General
-------

- It is not safe or recommended to run this on the open internet:

  - random ports will be opened for access to GDB, OpenOCD, QEMU and
    other daemons who will listen on all interfaces of the server with
    no way to perform access control (as the daemons do not implement
    it). Firewalling can be used to avoid access to that, but it will
    also reduce/kill target-debugging capabilities.

  - to ease diagnosing of issues, the server will send the client
    diagnosis information which will include things such as paths in
    the server, output of server side processes, timing information,
    etc (never authentication data or keys).

- Default deployment has HTTPS enabled and any setup should work like
  this

- The default configuration allows no access to hardware as it just
  instantiates targets implemented by virtual machines to run Zephyr
  and Linux on them (furthermore, Linux VMs need extra configuration
  work to enable).

  To enable physical hardware access, configuration has to be done as
  per the steps in the :ref:`server deplyment guide
  <server_deployment_guide>`.

- The default configuration allows any user coming from the local
  machine over the 127.0.0.1 (loopback interface) to connect and
  manage.

  **Why?**
    
  The server(s) available to implement the daemon do not support unix
  sockets, which would allow a simple way to tell if a user is local
  and thus, already authenticated into the system.

  Otherwise, to authenticate using PAM we'd have to hook up in the PAM
  rules for the system, which are distro/site specific and we can't
  know them ahead of time.

  So we defer to leave it to your deployment to configure different
  (more strict / less strict) authentication mechanisms as described
  in :ref:`Authentication <authentication>` and removing
  `/etc/ttbd-production/conf_05_auth_local.py`.
  
  As described in the point before, all the resources exported in the
  default configuration are virtual targets, which furthermore, have
  very strict invocation command lines that are sanitized, so a user
  has way more power to DoS the machine from their own account than
  by trying to subvert TCF.
  
- TCF will not protect or police the flow of data from the client to
  test targets in the daemon, and viceversa--the daemon basically
  gives you the same access to the target you would have physically,
  with the added onus of it being shared by anyone with login access to
  the server.

  Thus, assume that if you store a piece of information in a target by
  flashing it, other people can read it.

  Compartimentalization can be done by instantiating other servers
  (even in the same physical machine, but different port) with
  different login controls.

Client
------

- TCF client will run whichever code given wiht the same privilege as
  the user invoking it. No attempts at sandboxing are done. Assume the
  same risk level as running a Makefile from a source package you
  download off the Internet.

Daemon
------

The daemon runs as non-root user *ttbd* with the following elevated privileges:

- group *ttbd*: to be able to access files in ``/etc/ttbd*`` and have
  write access to anything in
  ``{/var/run,/var/lib/,/var/cache}/ttbd*`` created by other *ttbd*
  admins
- group *dialout*: to be able to access serial ports
- group *root*: to be able to access USB device nodes in
  ``/dev/bus/usb``
- capability *CAP_NET_ADMIN*: to be able to manipulate network
  interfaces (needed to setup IP test networks)

- When instantiating networks for testing networking amongst targets,
  it is crucial to keep them separated from any networking
  infrastructure used to control the targets (:ref:`rationale
  <separated_networks>`).

Daemon access control
^^^^^^^^^^^^^^^^^^^^^

Access to the daemon main interface is over HTTP (S), controlled by
authentication, with most of the operations requiring active
authentication. Authentication control inside the daemon is
plugin-based, allowing different user mapping mechanisms to be used
(currently LDAP, local database, IP-based).

The different targets can be acquired by a single user at a time. A
single user can acquire using tickets, which allows the user to have
multiple threads of execution mutually excluding each other from the
same resource.

File permissions
^^^^^^^^^^^^^^^^
The daemon is designed to run under a dedicated user and group
(*ttbd*) and will create all its files with Unix permission bits set
to allow any member of the group to read and write.

Exception to this rule are the crypto key for cookie handling
(`/var/lib/ttbd/INSTANCE/session.key`) and the ad-hoc SSL certificates
in `/var/run-ttbd/INSTANCE`.

Other processes started by the daemon
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The daemon starts several daemons and runs certain utilities under it
to implement functionality and control targets.

These might open TCP ports that will be accessible in the machine
outside of the daemon's auth control and in some cases can enable
remote execution, and thus have to be firewalled accordingly in
non-trusted environments (future releases will implement a safe way to
redirect ports taking authentication into consideration):

*bossac*
~~~~~~~~

This is a tool used to flash Arduino Due MCU boards, which is accessed
using the USB TTY interface it provides.

**Privilege needed**

- *dialout* group to access ``/dev/tty/*``

**Attack vectors**

n/a

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *root*


*dfu-util*
~~~~~~~~~~

This is a tool used to flash USB DFU (Device Firmware Update)
compliant devices over a well-defined standard USB protocol.

**Privilege needed**

- *root* group to access ``/dev/bus/usb/*``

**Attack vectors**

n/a

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *dialout*


*genisoimage*
~~~~~~~~~~~~~

Invoked by the QEMU target driver to generate transient ISO
filesystems to use as cloud-init data sources at target
powers-up time.

**Privilege needed**

- *ttbd* user/group to access ``/var/run/ttbd-*/*``

**Attack vectors**

n/a

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *dialout*, *root*

*ip*
~~~~

This tool is used to configure the system's network interfaces and
networking routes.

The daemon's configuration uses it to add virtual network devices,
virtual bridges and tie them up to physical network devices, as well
as to assign IPv4 and IPv6 addresses and routes.

**Privilege needed**

- capability *CAP_NET_ADMIN* to manipulate network interfaces

**Attack vectors**

- a set of interconnect and target names could be crafted that would
  result in an interface name that overrides the configuration of an
  existing network interface. However, this requires the admin's
  intervention, so it is moot.

**Mitigation**

n/a

FIXME: group *dialout*, *root*


*QEMU*
~~~~~~

**Privilege needed**

- capability *CAP_NET_ADMIN* to manipulate and access network interfaces

**Attack vectors**

- TCP socket for GDB interface is open with no access control

- Multiple UDP ports opened/closed as a result of implementing
  networking with the *-user* option
  (https://stackoverflow.com/questions/22161240/why-qemu-open-a-lot-of-udp-port).


**Mitigation**

Firewalling is the only option to limit access to these ports.

**Consequences of mitigation**

No GDB-based debugging of target

FIXME: drop group *dialout*, *root*

*qemu-img*
~~~~~~~~~~

Tool used to generate copy-on-write images of QEMU virtual machine
disks upon target power-on.

**Privilege needed**

- user/group *ttbd* to access ``/var/run/ttbd*``

**Attack vectors**

n/a

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *dialout*, *root*

*OpenOCD*
~~~~~~~~~

*OpenOCD* is used to control and flash some MCU boards, providing
also a GDB interface. It will be always running as each of those MCU
boards is turned on.

**Privilege needed**

- group *dialout* to access ``/dev/tty*``

- group *root* to access ``/dev/bus/usb``

**Attack vectors**

- TCP sockets for command execution and GDB are exposed.

- telnet script interface offers multiple vectors of
  attack, such as the commands:

  - add_script_search_dir: scan arbitrary directories

  - dump_image: potentially write files

  - *image*, *load*, script and program: read arbitrary files

  - find: locate files in OpenOCD's tree structure

  - \*_port: set ports where the daemon listens to

  - shutdown: stop the daemon

  - different commadns that can alter the system and are sometimes
    enabled or not (http://openocd.org/doc/html/General-Commands.html)

**Mitigation**

There is no way to make OpenOCD behave properly form a security
standpoint without major modifications that are not feasible; thus, a
site operator will have to consider firewalling if trusting clients
cannot happen. Definitely access to anyone in a open deployment on the
Internet is discouraged.

**Consequences of mitigation**

- Inability to run GDB against the taget
- Inability to run *debug-openocd* command

FIXME: drop CAP_NET_ADMIN

*socat*
~~~~~~~

Tool used to create tunnels from the server to a target using TCP, UDP
or SCTP.

None; tunnels are made on demand and only to ports belonging to a
given target. Destination is verified upon creation and can't be
subverted.

Tunnels are torn down upon target release from a user, so a new
acquirer has to recreate them as neeed.

**Attack vectors**

n/a

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *root* *dialout*


*tunslip6*
~~~~~~~~~~

Tool used to implement networking on QEMU Zephyr virtual machines
using the SLIP protocol; a virtual char device is created to speak the
SLIP protocol and this daemon converts the frames sent/received over
the virtual char device and sends them to a macvlan interface.

**Privilege needed**

- access to ``/dev/tap*`` devices, configured with udev to allow group
  *ttbd*

**Attack vectors**

The code for the *tunslip6* daemon could have issues that can be
subverted by crafting packets from the test target that crash the
daemon or drive buffer overflow attacks.

**Mitigation**

n/a

FIXME: drop CAP_NET_ADMIN, group *root* *dialout*, run as user with
access to /dev/tap* but nothing else

Networking
^^^^^^^^^^

Networks used by targets have to be strictly separated from networks
used for accessing the server where the daemon is or those dedicated
to infrastructure, as described in the :ref:`rationale
<separated_networks>`.

Taxonomy of test cases
======================

To test, the test case has to be *executed*, and based on where they
can execute, they are divided in two main categories:

 * *static*: do no require a target system, can be executed anywhere

  Examples of this would be code scans, binary object size checks,
  syntax verifiers, etc

 * *dynamic*: require target hardware to run (the :term:`test target`)

   Examples of this would be API functionality check, integration and
   end-to-end tests, performance tests, stress tests, etc

   * *test image*: a OS + test code that conforms a whole image that
     gets loaded onto the target hardware for the sole purpose of
     testing

   * *image + test script*: a script interacts with the image
     (combination of a program and OS) loaded on the test hardware;
     the program's purpose is other than just testing, but it is
     assumed that its features can be tested and it might have
     interfaces for testing/debugging
