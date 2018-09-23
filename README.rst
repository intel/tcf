.. this document is in Restructured Text Format;
   http://sphinx-doc.org/rest.html. BTW, this is a comment that won't
   show up in formatted output

===
TCF
===
   
TCF is a system that simplifies the creation and execution of test
cases (automation, for that matter) with minimal setup effort by
engineers (SW, QA and release) and autobuilders alike across a wide
amount of hardware platforms. It is distributed under the terms of the
Apache 2.0 license.

The test framework provides means to:

 - Discover and run one or many unit, integration, end-to-end automated
   test cases or samples with a single command line; these test cases
   may need no target (run in the local host) or one or
   more targets on which to operate.

 - Locate, manage and share target hardware to maximize
   resource efficiency

A developer will create a feature and as part of that will create unit
test cases which will be executed while developing the features until
the feature is complete. Other engineers (eg: QA) might create more
unit tests, integration and end-to-end tests to validate different
features working together. Testcase metadata added to the test cases
indicates how to build it, where can it be run and how to determine if
it is succesful or not, or how to extract significant data (like
resource consumption, performance, etc) for postprocessing. These test
cases can then be commited as part of the code so that other
people/agents can run them. The testcase can request targets, power
them up/down, connect/disconnect things to/from it, etc

When is time to run the testcases, a developer, QA engineer, or
CI/automation system launches *tcf*, which locates them, locates
remote targets where to execute them them, builds and evaluate them,
parallelizing as much as possible and generating reports about the
execution.

The system consists of two parts:

 - *tcf*: the client and test runner; this command line utility it is
   used to manage the test targets exported by the test target brokers
   (servers) and to execute test cases on said targets.

 - *ttbd*: the server; this manages test targets connected to them,
   serving as a proxy to the test cases being run by *tcf* on behalf
   of users.

TCF focuses only on execution, leaving reporting, coverage analysis,
etc, to other tools, providing means to feed data into them. It is
designed with the goal of having a small footprint and little
dependencies. 

Report issues and contact the authors by filling issues in
https://github.com/intel/tcf/issues.

Installation
============

Visit the quickstart `instructions
<https://intel.github.io/tcf/02-QUICKSTART.html>`_.

Documentation
=============

Available at http://intel.github.io/tcf

Best practices for contributing available at the `guide
<https://intel.github.io/tcf/doc/02-guides.html#contributing>`_.
