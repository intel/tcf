========
Glossary
========

.. glossary::

   BSP

     A board support package supported by a :term:`test target`

   BSP model

     A combination of BSPs on which a :term:`test target` works.

     For example, the Arduino 101 `x86` and `arc` BSPs that can work
     independently or together, the following BSP models would be
     supported: `x86`, `arc` and `x86+arc`.

   hash

     In the context of *tcf run*, a hash is a four character code that
     uniquely identifies the test case name and the target where it ran.

   herd

     Group of TCF servers that are meant to be used together, they all
     provide redundancy for targets of the same style.

   RunID

     A unique identifier for a run of testcases that groups the output
     and results of testcases. When specified, it will be prefixed to
     testcase output to clarify when it was generated.

   site
   
     Server herds can be split into *sites*, which is a subgroup of
     servers of the same herd that are physically located in the same
     place and might be sharing physical infrastructure
     
   static testcase

     A :term:`test case` that doesn't run on remote targets but in the
     local host where the test runner is executing.

   NUT

     Network Under Test or test network, to which :term:`test target`\s
     are connected. Usually isolated from the test infrastructure
     itself.

   POS

     Provisioning OS; operating system running on the :term:`test
     target` that is used to provision the target's drive.

   test case

     A test case is a flow to evaluate a single requirement, feature
     or functionality.

     A test case can be a program or a script

   test target

     Something that can be used to run a test case; this can be a
     group of actual HW units, not just a single one. It can be a
     computer, a light switch or a toaster.

     Each test target has a name, a type and it might support zero or
     more BSPs (think for example, a board that has an x86 and an ARC
     processor, like the Arduino 101); as well it has a list of tags
     and values that describe its capabilities.

   target controller

     A piece of software that understands how to talk to a target

   test target broker

     A service/machine to which one or more :term:`test target`\s are
     connected. It offers an abstracted API to manipulate and operate
     them; the API is implemented via target-specific :term:`target
     controller`\s.

   target broker

     See :term:`test target broker`.

   target driver

     Same as :term:`target controller`

   test finder

     A piece of software that locates test cases by looking at tag
     strings that define them as such.

   test case finder

     Same as :term:`test finder`

   test runner

     Linux machine that can drive the running and execution of test
     cases or command a target hardware to execute test cases.

   test case driver

     this is the entity that runs on the :term:`test runner`
     that understands how different test cases can be run.

     eg: knows how to launch a *@static* test case

     eg: knows how to interpret the output of a cetain type of test
     cases to decide what it is

   ttbd

     See :term:`test target broker`

   run ID

     An identification tag for a particular run of a sequence of test
     cases in a set of targets
