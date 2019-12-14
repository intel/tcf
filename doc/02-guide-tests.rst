.. _tcf_guide_tests:

Creating testcases
==================

Most of the testcases use the APIs provided with :class:`tcfl.tc.tc_c`
and :class:`tcfl.tc.target_c`, plus any other Python module library.

Going back to the very simple testcase used :ref:`here
<tcf_run_test_file_exists>`:

.. literalinclude:: ../examples/test_file_exists.py

this is a testcase that just checks for a file existing in the local
directory. It inherits from :class:`tcfl.tc.tc_c` to create a
testcase:

>>> class _test(tcfl.tc.tc_c):

this providing the basic glue to the meta test runner. The class can
be name whatever suits your needs.

Note this testcase declares no targets; it is an *static* testcase,
which evaluates by running on the local system with an *eval()*
function:

>>>    def eval(self):
>>>        filename = "testfile"
>>>        if os.path.exists(filename):
>>>            self.report_info("file '%s': exists! test passes" % filename)
>>>        else:
>>>            raise tcfl.tc.failed_e("file '%s': does not exist" % filename)

Multiple evaluation functions may be specified, as long as they are
called *evalSOMETHING*. You could add:

>>>     def eval_2(self):
>>>         self.shcmd_local("cat /etc/passwd")

this would use :meth:`tcfl.tc.tc_c.shcmd_local` to run a system
command. If it fails, it will raise a :exc:`tcfl.tc.failed_e`
exception that will fail the testcase. When running again, it will run
both functions in *alphabetical* order. For the testcase to pass, both
functions have to pass.

Running the modified version::

  $ cp /usr/share/tcf/examples/test_file_exists.py .
  # Edit test_file_exists.py to add eval_2
  $ tcf run -vv test_file_exists.py
  INFO2/	toplevel @local: scanning for test cases
  INFO2/ryvi	test_file_exists.py#_test @local: will run on target group 'local'
  FAIL2/ryviE#1	test_file_exists.py#_test @local: eval failed: file 'testfile': does not exist
  FAIL0/ryvi	test_file_exists.py#_test @local: evaluation failed
  FAIL0/	toplevel @local: 1 tests (0 passed, 1 failed, 0 blocked, 0 skipped) - failed

.. note:: ignore git errors/warnings, they are harmless and is a
          known issue.

It fails because the file *testfile* does not exist; *eval()* comes
before *eval_02()* in alphabetical order, so it is run first. As soon
as it fails the testcase execution is terminated, so *eval_2()* never
gets to run.

Create *testfile* in the local directory and re-run it, so *eval()*
passes and *eval_2()* also runs::

  $ touch testfile
  INFO2/	toplevel @local: scanning for test cases
  INFO2/ryvi	test_file_exists.py#_test @local: will run on target group 'local'
  INFO2/ryviE#1	test_file_exists.py#_test @local: file 'testfile': exists! test passes
  PASS2/ryviE#1	test_file_exists.py#_test @local: eval passed: 'cat /etc/passwd' @test_file_exists.py:14
  PASS1/ryvi	test_file_exists.py#_test @local: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

that *E#1*? those are messages relative to the *E*\valuation phase; the
number means the index of the evaluation. We can ask *tcf run* to
repeat the evaluation two times adding *-r 2*.

Zephyr OS's *Hello World!*
--------------------------

Let's move on now to testcases that use targets, using the Zephyr OS
as a test subject. Ensure the *tcf-zephyr* package was installed (with
*dnf install -y tcf-zephyr*) and clone the Zephyr OS (or used an
existing cloned tree)::

  # dnf install -y tcf-zephyr	# If not yet installed
  $ git clone http://github.com/zephyrproject-rtos/zephyr
  $ cd zephyr
  $ export ZEPHYR_BASE=$PWD

This is a very simple test case that cheks that the target where it
runs prints *Hello World!*; :

.. literalinclude:: ../examples/test_zephyr_hello_world.py

running it on whichever suitable target (*-y*)::

  $ cp /usr/share/tcf/examples/test_zephyr_hello_world.py .
  $ tcf run -vvy test_zephyr_hello_world.py
  INFO2/	toplevel @local: scanning for test cases
  INFO2/9orv	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: will run on target group 'ixgq (target=server2/arduino2-01:arm)'
  PASS2/9orv	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: configure passed
  PASS1/9orv	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: build passed
  PASS2/9orv	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: deploy passed
  INFO2/9orvE#1	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: Reset
  PASS2/9orvE#1	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: found expected `Hello World! arm` in console `default` at 1.23s
  PASS2/9orvE#1	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: eval pass: found expected `Hello World! arm` in console `default` at 1.23s
  PASS1/9orv	test_zephyr_hello_world.py#_test @server2/arduino2-01:arm: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

This testcase:

- declares it needs a target on which to run with the
  :func:`tcfl.tc.target` class decorator, which by default will be
  called *target*:

  >>> @tcfl.tc.target("zephyr_board",
  >>>                 app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
  >>>                                           "samples/hello_world"))

  the target will need to satisfy the :ref:`specification
  <target_specification>` given in the first parameter (*spec*) which
  requires it exposes a tag *zephyr_board* (which indicates it can run
  Zephyr Apps and gives the name of board for the Zephyr's build
  system with the *BOARD* parameter).

- the target will be loaded with a Zephyr app which is available in
  *$ZEPHYR_BASE/samples/hello_world*. Note how *ZEPHYR_BASE* is defined,
  instead of pulling it out straight from the environment with
  *os.environ[ZEPHYR_BASE]*--this makes it easier to tell when the
  testcase is ignored because *ZEPHYR_BASE* is not defined.

  *app_zephyr* is a plugin that indicates *tcf* how to build
  applications for different environments, how to load them into
  targets and how to start the targets.

- creates an evaluation function to be ran during the evaluation phase:

  >>>     def eval(self, target):
  >>>         target.expect("Hello World! %s" % target.bsp_model)

  This function is passed arguments that represent the targets it has
  to operate on. Because we only declared a single target with
  :func:`tcfl.tc.target` and we didn't specify a name with the
  *name* argument, it defaults to *target* (if you pass an argument
  that cannot be recognized like the name of a declared target, it
  will error out).

  For evaluating, we use :meth:`tcfl.tc.target_c.expect` which
  expects to receive in the target's console the string *Hello World!
  BSPMODEL*; the :term:`BSP model` describes in which mode we are running
  the target when it has multiple cores/BSPs incorporated (such as the
  *Arduino 101*, which includes an *x86* and *arc* BSPs).

  So for a target with an ARM BSP declared on its tags, it will expect
  to receive *Hello World! ARM*; if the string is received, the
  function returns and the testcase is considered to pass. Otherwise,
  it raises a failure exception :exc:`tcfl.tc.failed_e`, which is used
  by the test runner to mark the test case as a failure. If any other
  exception is raised (or :exc:`tcfl.tc.blocked_e`), the meta test
  runner will consider the test blocked.


A test case with multiple targets
---------------------------------

Consider the following made up test case, where we have two Zephyr
applications in two subdirectories of where the testcase file is
located. They are a simple (and fake) apps that allow one board to
connect to another (for simplicity of argument, we'll omit how they
connect).

Declare the need for two Zephyr OS capable targets that are
interconnected and indicate where to go to build the sources for them:

>>> @tcfl.tc.interconnect()
>>> @tcfl.tc.target("zephyr_board", app_zephyr = "node1")
>>> @tcfl.tc.target("zephyr_board", app_zephyr = "node0")
>>> class _test(tcfl.tc.tc_c):

Setup some hooks -- if when receiving from the console on any target
it prints a fatal fault, fail the test (this will be evaluated when
calling :meth:`tcfl.tc.target_c.expect` or the full testcase expect
loop calling :meth:`run() <tcfl.expecter.expecter_c.run>` on
:class:`tcfl.tc.tc_c.tls.expecter <tcfl.expecter.expecter_c>`

>>>     def setup(self, target, target1):
>>>         target.on_console_rx("FAILURE", result = 'fail')
>>>         target1.on_console_rx("FAILURE", result = 'fail')

When the evaluation phase is to start, power cycle the interconnect
(to ensure it is fresh). Note we don't do such with the Zephyr
targets, as the *app_zephyr* plugin has inserted two *start()*
functions to do it for us. Why? because he knows how to do start them
better (as some boards might lose the flashed image if we power cycle
them). It is possible to :ref:`override
<tcf_guide_app_builder_override>` the default actions that
*app_zephyr* (and other Application Builders introduce).

>>>     def start(self):
>>>         ic.power.cycle()

Now we are going to wait for both targets to boot and report readiness

>>>     def eval_0(self, target):
>>>         target.expect("I am ready")
>>>         target.report_pass("target ready")
>>>
>>>     def eval_1(self, target1):
>>>         target1.expect("I am ready")
>>>         target1.report_pass("target1 ready")

Now we are going to do the actual connection test by requesting
*target* to connect to *target1* and then *target1* is told to  to
accept the connection request--note each target exposes its address in
the network in a tag called *address* -- we can use
:attr:`tcfl.tc.target_c.kws` to format messages:

>>>     def eval_3(self, target, target1):
>>>         target.send("connect to %(address)s" % target1.kws)
>>>         target.expect("connecting to %(address)s" % target1.kws)
>>>
>>>         target1.expect("connect request from %(address)s" % target.kws)
>>>         target1.send("connect accept from %(address)s" % target.kws)
>>>
>>>         target1.expect("accepted connect from %(address)s" % target.kws)
>>>         target.expect("connected to %(address)s" % target1.kws)

Now we wait for both targets to print a heartbeat that they emit
every five seconds--if we have to wait more than ten seconds for both
heartbeats, it will consider it a failure:

>>>     def eval_4(self, target, target1):
>>>         target.on_console_rx(re.compile("heartbeat #[0-9]+ ok"))
>>>         target1.on_console_rx(re.compile("heartbeat #[0-9]+ ok"))
>>>         self.expecter.run(10)

The :class:`tcfl.tc.tc_c.tls.expecter <tcfl.expecter.expecter_c>` is a
generic expectation loop to which anything can be attach to poll and
check while the loop runs. It will run until all the things it has
been asked to expect have ocurred or fail with a timeout.

It can be also used with context managers:

>>>    def eval_5(self, target):
>>>         times = 4
>>>         with target.on_console_rx_cm(re.compile("heartbeat #[0-9]+ failure")
>>>                                     result = "fail"):
>>>             target.send("do_some_lengthy_operation")
>>>             target1.send("do_some_lengthy_operation")
>>>             target.on_console_rx(re.compile("completed"))
>>>             target1.on_console_rx(re.compile("completed"))
>>>             self.expecter.run()

APIs :meth:`tcfl.tc.target_c.expect` and :meth:`tcfl.tc.target_c.wait`
are an example of doing something similar to this.

With the test concluded, we power down all the targets in reverse
order:

>>>     def teardown(self):
>>>         for _n, target in reversed(self.targets.iteritems()):
>>>             target.power.off()

Or not, it can also be left to *ttbd* to decide if they have to be
powered down and when.

Connecting to network ports
---------------------------

A well designed target setup will have the test targets in an isolated
network, so the client cannot access remotely. However, using the
:class:`IP tunnel <tcfl.target_ext_tunnel.tunnel>` extension, the
client can access the target's network ports. This also allows to
establish :class:`SSH connections <tcfl.target_ext_ssh.ssh>`.

Consider this example:

>>> r = target.ssh.check_output("echo -n %s > somefile" % self.ts)
>>> if r == 0:
>>>    self.report_pass("created a file with SSH command")

This is an excerpt of a longer :download:`example
<../examples/test_linux_ssh.py>` that shows how to do different SSH
and SCP operations.

Tunnels are only valid while the target is acquired.

Network test cases
------------------

FIXME: this needs a good intro

Capturing *tcpdumps* of network traffic
---------------------------------------

When using the network setups controlled by the TCF server, *ttbd*, it
is possible to capture the network traffic that the server sees for
further analysis.

A well designed test network will interconnect one or more targets and
also will include one server interface, which usually is associated to
the *interconnect* target that defines said test network.

Using in the server the :class:`conf_00_lib.vlan_pci` to bring up the
network, like with the configuration functions
:func:`conf_00_lib.nw_default_targets_add` to create networks, those
targets will have the tcpdump capability.

To use, you would, declare a test that uses an interconnect and before
powering the interconnect, in any *start()* method, you would set the
*tcpdump* property in the interconnect to unique file name:

>>> @tcfl.tc.interconnect(spec = "ipv4_addr")
>>> @tcfl.tc.target()
>>> @tcfl.tc.target()
>>> class something(tcfl.tc.tc_c):
>>>     ...
>>>     def start(self, ic, target, target1):
>>>         # Tell the interconnect we want to capture network data to a
>>>         # file named after self.kws['tc_hash'] (to avoid conflicts)
>>>         ic.property_set('tcpdump', self.kws['tc_hash'] + ".cap")
>>>         ic.power.cycle()
>>>         ...

Later on, in the *teardown()* methods, bring the data back from the
server to a file in the current work directory called
*tcpdump-RUNID:HASHID.cap*:

>>>     def teardown(self, ic):
>>>         ic.power.off()	# ensure tcpdump flushes
>>>         # Get the TCP dump from the interconnect to a file in the CWD
>>>         # called tcpdump-HASH.cap
>>>         ic.broker_files.dnload(self.kws['tc_hash'] + ".cap",
>>>                                "tcpdump-%(runid)s:%(tc_hash)s.cap" % self.kws)


From the command line, this would be::

  $ tcf acquire NETWORKTARGET
  $ tcf propert-set NETWORKTARGET tcpdump CAPTURENAME
  $ tcf power-cycle NETWORKTARGET
  ... do network operations ...
  $ tcf power-off NETWORKTARGET
  $ tcf broker-file-dnload NETWORKTARGET CAPTURENAME myfile.cap
  $ tcf release NETWORKTARGET

now *myfile.cap* can be opened with *Wireshark* or processed with any
other tool for further analysis.


Saving data and files to a location
-----------------------------------

Sometimes there is a need to keep files around for post analysis,
there are different ways to do this:

- provide ``--no-remove-tmpdir`` to *tcf run*; it will provide the
  name of the temporary directory where all the temporary files are
  maintained and will not delete it upon exit (as it does by default)

- provide ``--tmpdir=DIR``, where ``DIR`` is an existing, empty
  directory where *tcf run* will place all the temporary files.


Whichever is the temporary directory (autogenerated or specified), the
files are placed in subdirectories named after each test case run's
:ref:`*HASH* <tc_id>`.

If you need to create files (or copy files, etc) in the testcase,
use to the :attr:`tmpdir <tcfl.tc.tc_c.tmpdir>` variable to generate
or copy files to the directory assigned to the testcase, for example:

.. code-block:: python

  with open(os.path.join(self.tmpdir, "somefile.orig")) as f:
     f.write("original file")
  target.ssh.copy_from(os.path.join(self.tmpdir, "somefile.orig"))
  # ... do something on the target
  target.ssh.copy_to("somefile", self.tmpdir)
  # compare files


.. _connecting_things:

Connecting things
-----------------

Some targets supports things (other targets) that can be connected or
disconnected. If they do, their tags will show::

  $ tcf list -vv qlf04a
  ...
  things: [u'a101-05', u'usb-key0']
  ...

How this is done is specific to the driver given in the configuration,
but it might be a target that is physically connected to another via a
USB cutter. The USB cutter is an object implementing a :class:`plugger
interface <ttbl.things.impl_c>` which is configured as described in
:mod:`ttbl.things` in the config files.

- to find available things to connect, use the `tcf thing-list` or
  within a test script, :meth:`tcfl.things.list
  <tcfl.target_ext_things.extension.list>`

- to connect, use `thing-plug` or within a test script,
  :meth:`tcfl.things.plug <tcfl.target_ext_things.extension.plug>`

- to disconnect, use `thing-unplug` or within a test script,
  :meth:`tcfl.things.unplug <tcfl.target_ext_things.extension.unplug>`

Note you must own both the target and the thing to be able to plug one
into another.
