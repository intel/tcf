#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
#
#
# Long:
#
# jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle14
#
# Individual:
#
# jdk8u.git/hotspot/agent/test/jdi/sagtest.java
# jdk11u.git/test/hotspot/jtreg/vmTestbase/vm/compiler/coverage/parentheses/
#
# 64 subcases under TEST.ROOT
#
# jdk8u.git/langtools/test/tools/javap/
#
# 2 failing subcases above TEST.ROOT
#
# jdk8u.git/hotspot/agent/test
#
# example with @ignore:
#
# jdk8u.git/langtools/test/tools/javac/annotations/typeAnnotations/failures/AnnotatedPackage1.java
# jdk8u.git/langtools/test/tools/javac/annotations/typeAnnotations/failures/AnnotatedImport.java
# jdk8u.git/langtools/test/tools/javac/annotations/typeAnnotations/failures/CantAnnotateStaticClass3.java
#
#
# Suite:
#
# jdk11u.git/test/hotspot
# jdk11u.git/test/hotspot
# jdk8u.git/hotspot/test
# jdk8u.git/hotspot/agent/test	# No TEST.ROOT, shall fail
#
# - blocked TCs because we can't find, if it says "Total tests run: 0,
#   Failures: 0, Skips: 0", then ignore it, just log it, not rpeort
#   subcase.
#
#   javax/sql/testng/util/StubContext.java
#
# - When eval_10_execute times out, we need to parse whichever jtrs
#   finished (pass/faield etc) to report them properly instead of err
#
# - parse timeout tags / factor // @run CODE/CODE/@timeout
#
# - some tests are marked @ignore but still processed

"""\
TCF client driver to load JTReg testcases
-----------------------------------------

This driver is work in progress

This driver scans for .java or .sh testcases that can be considered
a JTReg testcase and executes them in a remote target.

.. _jtreg_workspace:

.. warning: bugs/limitations

   - as of now, this only works with a ClearLinux image; method
     *eval_00_dependencies_install()* has to be modified to know how to
     add dependencies for other distros.

   - an absolute path to the testcase file/directory will not be
     decoded properly; use relative paths.

Workspace preparation
^^^^^^^^^^^^^^^^^^^^^

Make sure you have a GIT tree of OpenJDK 11 cloned in a
directory called *jdk11u.git* (similar for v12, v8)::

  $ git clone https://github.com/openjdk/jdk11u.git jdk11u.git
  $ git clone https://github.com/openjdk/jdk12u.git jdk12u.git
  $ git clone https://github.com/AdoptOpenJDK/openjdk-jdk8u.git jdk8u.git

For each version you want to run, export the location of Java (eg for v11)::

  $ export JAVA11_HOME=/usr/lib/jvm/java-11

Install a built JTReg in a directory called *jtreg*::

  $ wget https://ci.adoptopenjdk.net/view/all/job/jtreg/lastSuccessfulBuild/artifact/jtreg-4.2-b14.tar.gz
  $ tar xf jtreg-4.2-b14.tar.gz
  $ export JTREG_DIR=$HOME/jtreg

(optional) If native testcases are to be executed, ensure you have the
native builds and export their paths in *JDK<VERSION>_BINDIR* (eg:
*JDK11_BINDIR*). Each tree must look like (eg: for v11)::

   openjdk_test_jdk11/
       exclude.list
       native/
           FPRegs
           invoke
           lib*.so
           ...

thus you can, for example::

  $ export JDK11_BINDIR=$HOME/openjdk_test_jdk11

In general, the names of the directories do not matter, but to speed
up deployment to the target from the client, they need to match
whatever has been set in the :ref:`server`s caches
<jtreg_server_cache>`.

Client usage
^^^^^^^^^^^^

TCF will scan for testcases in any top level directories given as
parameters; it will paralellize execution by running the testcases on
each directory in a separate target (if available, otherwise they will
be queued).

Thus::

  $ tcf run -v jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle*

[note the run up to prepare can take a long time as the directory
trees are scanned]

this will launch a bunch of parallel testcases; TCF assigns a target
to each (in this example, some targets overlap)::

  INFO1/lpg6	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle29 @wjg7-mrp3: will run on target group 'ic=jfsotc11/nwo target=jfsotc11/nuc-74o:x86_64'
  INFO1/9es7	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle28 @lnss-eq2f: will run on target group 'ic=jfsotc21/nwC target=jfsotc21/nuc-03C:x86_64'
  INFO1/k06f	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle23 @ehgg-fnk5: will run on target group 'ic=jfsotc21/nwN target=jfsotc21/nuc-14N:x86_64'
  INFO1/2q36	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle22 @p5pb-cu2b: will run on target group 'ic=jfsotc21/nwO target=jfsotc21/nuc-15O:x86_64'
  INFO1/pow8	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle21 @ehgg-fnk5: will run on target group 'ic=jfsotc21/nwN target=jfsotc21/nuc-14N:x86_64'
  ...

the system will now flash a default Linux OS (*clear*, other's can be
chosen) on each target, send *jtreg* and the *jdku11.git* workspace to
the targets (note all this happens in parallel and is quite fast as it
uses rsync to refresh it--versus downloading it in the target)::

  ...
  INFO1/c0idDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle12 @o66n-ycu4|jfsotc20/nuc-09I: POS: rsyncing clear:server:30340::x86_64 from 192.168.73.1::images to /dev/sda4
  INFO1/ohxhDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle02 @pkuc-f3s2|jfsotc21/nuc-12L: POS: rsyncing clear:server:30340::x86_64 from 192.168.76.1::images to /dev/sda7
  DATA1/gmbaDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle01 @dfdm-w6tc|jfsotc11/nuc-73s: Deployment stats image clear:server:30340::x86_64::image rsync to jfsotc11/nuc-73s (s)::15.18
  DATA1/fjbpDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle31 @mf7f-icxv|jfsotc11/nuc-77v: Deployment stats image clear:server:30340::x86_64::image rsync to jfsotc11/nuc-77v (s)::11.19
  DATA1/lpg6DPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle29 @wjg7-mrp3|jfsotc11/nuc-74o: Deployment stats image clear:server:30340::x86_64::image rsync to jfsotc11/nuc-74o (s)::11.71
  INFO1/zjcuDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle19 @z3er-6bv5|jfsotc11/nuc-72p: POS: rsyncing clear:server:30340::x86_64 from 192.168.112.1::images to /dev/sda4
  INFO1/qvrwDPOS	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle32 @muj3-uswg|jfsotc11/nuc-76m: POS: rsyncing clear:server:30340::x86_64 from 192.168.109.1::images to /dev/sda5
  ...

and then start running the testcases, collecting then the output of
each individual subcase to report it (we gave only one *-v*, so not
much information will be printed except for failure reports and top
level informational messages).

Things that can happen now

- the test passes, because we didn't give too many *-v*, the system
  prints summaries, but it shows in the counts when it returns::

    ...
    PASS1/mrfg	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle29 @dfdm-w6tc: evaluation passed
    INFO1/njko	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle29/TestDescription.java @dfdm-w6tc: will run on target group 'ic=jfsotc11/nws target=jfsotc11/nuc-73s:x86_64'
    PASS1/njko	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle29/TestDescription.java @dfdm-w6tc: evaluation passed
    ...

- Failures are what JTreg calls errors, when a problem is detected::

    ...
    INFO1/noki	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle25/TestDescription.java @df3m-w6tc: will run on target group 'ic=jfsotc11/nws target=jfsotc11/nuc-73s:x86_64'
    PASS1/noki	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle25/TestDescription.java @df3m-w6tc: evaluation passed
    ...

  A file called *report-:noki.txt* will contain all the details from
  JTreport + JTwork.

- Errors, an unexpected negative result, like::

    ...
    INFO1/i6q2	vmTestbase/gc/vmTestbase/gc/g1/unloading/tests/unloading_reflection_classloading_inMemoryCompilation_keep_class/TestDescription.java @ehgg-fnk5: will run on target group 'ic=jfsotc21/nwN target=jfsotc21/nuc-14N:x86_64'
    ERRR0/i6q2	vmTestbase/gc/vmTestbase/gc/g1/unloading/tests/unloading_reflection_classloading_inMemoryCompilation_keep_class/TestDescription.java @ehgg-fnk5: evaluation errored
    ...

  A file called *report-:i6q2.txt* will contain all the details from
  the system.

  most common this is a timeout, the system waited too much for the
  testcase  to finish executing (FIXME: defauls to 400s
  now).

  If it is taking too long and not taking advantage of other targets
  to parallelize, select smaller top level directories a few TCs each,
  or individual testcases.

  Other issues might be failure to install the necessary bundles due
  to network timeouts, disk space constraints, etc...

- Blockage can happen, where an infrastructure problem disallows to
  execute the test case, for example::

    ...
    BLCK1/jpfa	jdk11u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle24 @zmgs-k55x: deploy blocked
    ...

You can login via SSH to the target (the driver with start the SSH
server) to poke around while the testcase is running (:ref:`more info
<tunnels_linux_ssh>`).


Controlling bundle installation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This driver uses :func:`tcfl.tl.swupd_bundle_add` to install Clear
Linux OS dependencies; look at its documentation for environment
settings that can be used to modify its behaviour (like selecting
mirrors, etc).


Selecting major Java versions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The system will try to guess the java version under which to run a
testcase by its path, but it can be forced by JAVA_VERSION::

  $ JAVA_VERSION=12 tcf run -v jdk12u.git/test/hotspot/jtreg/vmTestbase/gc/ArrayJuggle/Juggle*

.. _jtreg_server_cache:

Server setup (performance optimization for deployment)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

During deployment of the testcases, the test content (Java test suite
and (optionally the natively built parts of it) plus the built JTreg
code need to be deployed to the target. This is done by rsyncing from
the client to the target via the server.

To optimize deployment, the test content can be placed in the server.
The deployment first sends it from the server to the target, the
fastest option being as close as possible in network topology terms to
the target and then from the client to the target only the differences
are rsynced.

To setup the server cache area in */home/ttbd/image/misc*, login to
the server and setup the caches::

  $ cd /home/ttbd/images/misc

- Cache *JTreg*::

    $ wget https://ci.adoptopenjdk.net/view/all/job/jtreg/lastSuccessfulBuild/artifact/jtreg-4.2-b14.tar.gz
    $ tar xf jtreg-4.2-b14.tar.gz
    $ rm -f jtreg-4.2-b14.tar.gz

- cache *JDK*'s multiple version::

    $ git clone https://github.com/openjdk/jdk11u.git jdk11u.git
    $ git clone https://github.com/openjdk/jdk12u.git jdk12u.git

  note we use the git trees but we don't transfer the *.git*
  directories to the targets for performance (as different clones will
  have different .

- for the native built parts cache *jdk11u.git*'s multiple version, place:

  - */home/ttbd/images/misc/openjdk_test_jdk11*
  - */home/ttbd/images/misc/openjdk_test_jdk12*
  - */home/ttbd/images/misc/openjdk_test_jdk13*
  - ...

note it is possible to use different names; what matters is to use the
same directory names in the server so that they match the
:ref:`client's workspace <jtreg_workspace>`.

Architecture
^^^^^^^^^^^^

Entry points:

 - the TCF testcase discovery engine will call
   :meth:`driver.is_testcase <tcfl.tc.tc_c.is_testcase>` for every
   `*.(java|sh)` file found from the list given in the command line.

   For each valid TC found, the driver will create a :class:`driver`
   testcase object and give it to the TCF core to execute later

 - the TCF testcase runner pairs testcase objects with targets where
   to execute and tells them to run.

 - when a testcase object is told to run, it gets to the
   *driver.eval_10_execute* function, which uses JTReg to execute the
   testcase and collect the output; the output is then parsed to tell
   if the TC passed/failed/errored/skipped/blocked.

 - The test class inherits tc_pos_base, which declares it needs a
   target and a network target (for flashing, SSH access, etc)

 - deploy_00 configures the sending of the workspace using the
   deployment infrastructure defined by the tc_pos_base class
   template. This will flash the distro and then rsync the workspace.

 - After deployment, the target is booted and ends up in
   eval_00_bundle_add(), which will setup the network access, install
   java11-basic, etc.

 - then eval_10_execute() is ran,w hich will run the testplan assigned
   to this testcase and parse the results, reporting each subcase
   individually.

Listing testcases
^^^^^^^^^^^^^^^^^

You can figure out where test suites are by finding `TEST.ROOT`::

  $ find jdk11u.git/ -iname TEST.ROOT
  jdk11u.git/make/langtools/test/TEST.ROOT
  jdk11u.git/test/jdk/TEST.ROOT
  jdk11u.git/test/nashorn/TEST.ROOT
  jdk11u.git/test/jaxp/TEST.ROOT
  jdk11u.git/test/langtools/TEST.ROOT
  jdk11u.git/test/failure_handler/test/TEST.ROOT
  jdk11u.git/test/hotspot/jtreg/TEST.ROOT

now to list the testcases in a suite::

  $ java -jar $JTREG_DIR/lib/jtreg.jar -l jdk11u.git/test/hotspot/jtreg/
  Testsuite: /home/inaky/j/jdk11u.git/test/hotspot/jtreg
  applications/ctw/modules/java_base_2.java
  applications/ctw/modules/java_base.java
  ...
  vmTestbase/vm/runtime/defmeth/scenarios/SuperCall_v52_syncstrict_invoke_redefine/TestDescription.java
  vmTestbase/vm/runtime/defmeth/scenarios/SuperCall_v52_syncstrict_reflect_noredefine/TestDescription.java
  vmTestbase/vm/runtime/defmeth/scenarios/SuperCall_v52_syncstrict_reflect_redefine/TestDescription.java
  Tests found: 17,491

PENDING
^^^^^^^

 - means to analyze the testsuite to suggest parallelization
   maybe record execution times of each?

 - pending if I give overlapping from_paths, error out

 - understand and select the filtering of testcases better, now I just
   hardcoded -k:'!headful&!printer', but I have no idea what it does...

"""
import codecs
import contextlib
import errno
import logging
import mmap
import os
import re
import subprocess

import commonl
import tcfl.tc

jtreg_concurrency = os.environ.get("JTREG_CONCURRENCY", "1")
# if JTREG_DIR is not defined, be ok -- just complain if we are trying
# to use it, later in driver._list()
jtreg_dir = os.environ.get("JTREG_DIR", None)
if jtreg_dir:
    jtreg_dirname = os.path.basename(jtreg_dir)

def _file_scan_regex(filename, regex):
    with open(filename) as f:
        stat_info = os.fstat(f.fileno())
        if stat_info.st_size == 0:
            return None				# empty, ignore
        with contextlib.closing(mmap.mmap(f.fileno(), 0, mmap.MAP_PRIVATE,
                                          mmap.PROT_READ, 0)) as data:
            return regex.search(data)

@tcfl.tc.interconnect("ipv4_addr",
                      mode = os.environ.get('MODE', 'one-per-type'))
@tcfl.tc.target("pos_capable")
class driver(tcfl.pos.tc_pos0_base):
    """Execute JTreg JDK testcases on remote targets


    .. _jtreg_directory_layout:

    ** Directory layout, grouping testcases and path terminology **

    The JDK JTreg tests (*jdkXu.git*, where X matches the major Java
    version) are a collection of testsuites at different levels of the
    directory tree.

    The beginning of each testsuite is defined by a file called
    *TEST.ROOT* in a subdirectory of *jdXu.git* (e.g.:
    *jdk8.git/hotspot/test/TEST.ROOT*) [term: test root path]

    This driver will make *tcf run* run testcases in toplevel
    containers (which will flash a target and run a sequence of
    subcases) depending on the path given in the commandline [term:
    command line path]:

    A. when *tcf run* is given a path in the command line, then it will
       run all the testcases found under that directory in the same
       toplevel container

    B. we *tcf run* is given a path in the command line above a
       testsuite (*jdk8u.git/hotspot* has at *test/* and at *test/* and
       *agent/test/jdi*), it will unfold on a toplevel container for
       each test root that will be run in parallel in multiple targets
       (if available).

    Thus, in the code we keep track of the following:

    - *path_cmdline*: the path given to run in the commad line
    - *path_test_root*: the path where the TEST.ROOT is
    - *path_toplevel*: path from which the toplevel is running testcases
      (if B, it matches *path_test_root*)
    - *path_jdk*: is the top of the *jdkX*

    """
    def __init__(self, path_toplevel, path_test_root,
                 java_version, native_bindir):
        tcfl.pos.tc_pos0_base.__init__(self, path_toplevel, path_toplevel,
                                       path_toplevel)
        self.path_toplevel = path_toplevel
        self.path_test_root = path_test_root
        self.path_jdk = None
        self.path_jdk_to_test_root = None
        self.java_version = java_version
        self.native_bindir = native_bindir

    @tcfl.tc.serially()
    def deploy_00(self, target):
        # the format is still a wee bit pedestrian, we'll improve the
        # argument passing
        target.deploy_path_src = [
            self.path_jdk,
            jtreg_dir,
        ]
        # deploy whichever native bindir we need to use (if available)
        if self.native_bindir:
            target.deploy_path_src.append(self.native_bindir)
        target.deploy_path_dest = "/opt/"
        target.deploy_rsync_extra = "--exclude '.git/*'"
        self.deploy_image_args = dict(extra_deploy_fns = [
            tcfl.pos.deploy_path ])

    def eval_00_dependencies_install(self, ic, target):
        ic.power.on()

        tcfl.tl.linux_ssh_root_nopwd(target)	# allow remote access
        target.shell.run("systemctl restart sshd")
        target.shell.run(		# wait for sshd to fully restart
            # this assumes BASH
            "while ! exec 3<>/dev/tcp/localhost/22; do"
            " sleep 1s; done", timeout = 15)
        if hasattr(target.console, 'select_preferred'):
            target.console.select_preferred(user = 'root')

        if self.java_version == '8':
            bundle = 'java-basic'	# yeah, exception...
        else:
            bundle = "java%s-basic" % self.java_version
        # this will wait for online and set proxy for us and do the
        # clear certificate fix
        # diffutils: needed for some testcases
        tcfl.tl.swupd_bundle_add(ic, target, [
            # some test content requires ld for AOT compiler
            'binutils',
            # some test content requires `diff` to compare the resut
            # with golden references
            'diffutils',
            # basic java support for the version
            bundle
        ])

    def _output_subcase_parse(self, tcname, result,
                              failures, other_errors):
        if result == 'Error' and tcname == 'Some tests failed or other problems occurred.':
            # parsing artifact
            return

        # NAME.ext#idN testcases are called NAME_idN.jtr in the
        # reports, so let's generate the report file name here
        # based on knowing that.
        if '#id' in tcname:
            name, idN = tcname.split("#", 1)	 # NAME.ext#idN -> NAME.ext, idN
            base, _ext = os.path.splitext(name) # NAME.ext -> NAME, .ext
            # recompose as NAME_idN.jtr
            jtr_name = base + "_" + idN + ".jtr"
        else:
            base, _ext = os.path.splitext(tcname)
            jtr_name = base + ".jtr"

        # the JTwork/SUBTESTCASEPATH/NAME.jtr contains execution
        # details, let's read it to report in the subcase
        # We copied those files from the target and untarred it in
        # self.tmpdir.
        line = None
        jtr_content = ""
        output_file_name = os.path.join(self.tmpdir, "JTwork/%s") % jtr_name
        try:
            with codecs.open(output_file_name,
                             encoding = 'utf-8', errors = 'ignore') as f:
                for _line in f:
                    _line = _line.strip()
                    if not _line:
                        continue
                    jtr_content += _line + "\n"
                    line = _line
                # last line is the summary
                jtr_summary = line
        except IOError as e:
            if e.errno == errno.ENOENT:
                result = "BUG"
                jtr_summary = "output file %s missing" % output_file_name
                jtr_content = "n/a"
        # from the command line output of execting jtref, parse each
        # line and map it to a subcase, report as such
        _result = tcfl.tc.result_c()
        if result == 'FAILED':
            if tcname not in failures:
                self.report_error("%s failed but not in newfailures.txt"
                                  % tcname)
            _result.failed += 1
        elif result == 'Error':
            if 'execStatus=Error. Test ignored' in jtr_content:
                # this means it was skipped
                _result.skipped += 1
                self.report_skip("expected error skipped per @ignore tag")
            else:
                _result.failed += 1
                if tcname not in other_errors:
                    self.report_error("%s errored but not in other_errors.txt"
                                      % tcname)
        elif result == 'Passed':
            _result.passed += 1
        elif result == 'BUG':
            _result.blocked += 1
        else:
            raise AssertionError("unknown result from command output '%s'"
                                 % result)

        if tcname not in self.subtc:
            self.report_error("ERROR subtc %s not found in self.subtcs"
                              % tcname)
            path_tc = os.path.join(self.path_test_root, tcname)
            path_tc = os.path.relpath(path_tc)	# relative to working dir
            subtc = tcfl.tc.subtc_c(path_tc, self.name, self.name, self)
            self.subtc[tcname] = subtc
            jtr_summary = "subtc wasn't found on testcase's subcase list"
            jtr_content = ""
            _result = tcfl.tc.result_c()
            _result.blocked += 1
        self.subtc[tcname].update(_result, jtr_summary, jtr_content)

    def eval_10_execute(self, ic, target):
        self.report_info("subtc count %d" % len(self.subtc), dlevel = 1)
        target.shell.shell_prompt_regex = re.compile("JTREG-PROMPT% ")
        target.shell.run(
            "export PS1='JTREG-PROMPT% '  # a simple prompt is "
            "harder to confuse with general output")

        path_jdk_remote = os.path.join("/opt", os.path.basename(self.path_jdk))
        if self.native_bindir:
            # if we have bindirs with native code built, we have put
            # them in /opt/SOMETHING; do the string so we can run
            # those testcases
            target_native_bindir = os.path.basename(self.native_bindir)
            native_cmdline = \
                " -exclude:/opt/%s/exclude.list -nativepath:/opt/%s/native" \
                % (target_native_bindir, target_native_bindir)
        else:
            native_cmdline = ""
        if self.java_version == '8':
            java_cmd = 'java'
        else:
            java_cmd = 'java' + self.java_version
        # we might take time to print the output or to run based on
        # how many subtcs we have
        # DEFAULT timeout per testcases in JTREG is 120 seconds
        # FIXME: some TCs might declare a multiplier; find how to
        # extract it -> @run SOMETHING/SOMETHING/timeout=NNN/SOMETHING...
        timeout = 120 * len(self.subtc)

        # Now we have to figure out where thing are in the remote
        # machine vs in the local one. path_toplevel
        #
        # /some/path/jdk8u.git/a/b/c
        #
        # has to become
        #
        # /opt/jdk8u.git/a/b/c
        target.report_info("# of subtestcases %d, timeout %s"
                           % (len(self.subtc), timeout))
        if '/' in self.path_toplevel:
            path_toplevel = os.path.join(*self.path_toplevel.split("/")[1:])
        else:
            path_toplevel = self.path_toplevel
        # We have forced /opt/$JTREG_DIRNAME to be installed there from the
        # server's cache or from the client
        # FIXME: this only runs then at directory level...hmmm, if we
        # only want to run one from the directory it still runs
        # them'all
        #print "DEBUG path_jdk_remote", path_jdk_remote
        #print "DEBUG path_toplevel", path_toplevel
        output = target.shell.run(
            # We use -p so the format is the POSIX standard as
            # defined in
            # https://pubs.opengroup.org/onlinepubs/009695399/utilities
            # /time.html
            # STDERR section
            "time -p"
            " %(java_cmd)s -jar /opt/%(jtreg_dirname)s/lib/jtreg.jar"
            " -a -ea -esa -avm -v1 -retain"
            # FIXME: hardcoded
            " -k:'!headful&!printer'"
            " %(native_cmdline)s"
            " -conc:%(concurrency)s -timeout:1"
            " %(ts_path)s || true"	# ignore retval, since we'll parse
            % dict(
                java_cmd = java_cmd,
                jtreg_dirname = jtreg_dirname,
                concurrency = jtreg_concurrency,
                native_cmdline = native_cmdline,
                ts_path = os.path.join(path_jdk_remote,
                                       path_toplevel)
            ),
            output = True, timeout = timeout)
        self.targets_active()

        # see above on time -p
        kpi_regex = re.compile(r"^real[ \t]+(?P<seconds>[\.0-9]+)$",
                               re.MULTILINE)
        m = kpi_regex.search(output)
        if not m:
            raise tcfl.tc.error_e(
                "Can't find regex %s in output" % kpi_regex.pattern,
                dict(output = output))
        target.report_data("Java testcase execution stats",
                           "runtime for %s @%s (seconds)"
                           % (self.name, target.type),
                           float(m.groupdict()['seconds']))

        # FIXME: failing for non-existing testcases because this is
        # running all, not just what told

        # Pack and compress all the files we need to analyze and
        # copy them to the client for it to do the post analysis; way
        # faster than then catting all the log over the serial line.
        target.shell.run(
            r"find JTreport JTwork -name \*.jtr"
            " -o -name newfailures.txt -o -name other_errors.txt"
            " | tar cJf logs.tar.xz -T/dev/stdin")
        # we are assuming we have SSH support, so defaulting to that;
        # therwise we'd do:
        #target.shell.file_copy_from(local_name, "logs.tar.xz")
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
        target.ssh.copy_from("logs.tar.xz", self.tmpdir)
        subprocess.check_output(
            [ "tar", "xf", "logs.tar.xz" ],
            stderr = subprocess.STDOUT, cwd = self.tmpdir)

        # Go over the list of failures and errors
        failures = []
        try:
            with codecs.open(
                    os.path.join(self.tmpdir, "JTreport/text/newfailures.txt"),
                    encoding = 'utf-8', errors = 'ignore') as f:
                first = False
                for line in f:
                    if not first:
                        continue
                    failures.append(line.strip())
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
        other_errors = []
        try:
            with codecs.open(
                    os.path.join(self.tmpdir, "JTreport/text/other_errors.txt"),
                    encoding = 'utf-8', errors = 'ignore') as f:
                first = False
                for line in f:
                    if not first:
                        continue
                    other_errors.append(line.strip())
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise

        # Parse over the output, which lists each individual TC result
        ## java -jar /opt/jtreg/lib/jtreg.jar -a -ea -esa -avm -v1 -retain -k:'!headful&!printer'  -conc:1 -timeout:1 /opt/jdk8u.git/jdk/test/java/sql/testng/test/sql || true
        ## Directory "JTwork" not found: creating
        ## Directory "JTreport" not found: creating
        ## Passed: java/sql/testng/test/sql/BatchUpdateExceptionTests.java
        ## Passed: java/sql/testng/test/sql/DataTruncationTests.java
        ## Passed: java/sql/testng/test/sql/DateTests.java
        ## Passed: java/sql/testng/test/sql/DriverManagerPermissionsTests.java
        ## Passed: java/sql/testng/test/sql/DriverManagerTests.java
        ## Passed: java/sql/testng/test/sql/SQLClientInfoExceptionTests.java
        ## Passed: tools/javac/policy/test2/Test.java#id0
        ## Passed: tools/javac/policy/test2/Test.java#id1
        ## Passed: tools/javac/policy/test2/Test.java#id2
        ## ...
        regex = re.compile(
            r"^(?P<result>(FAILED|Passed|Error)):\s+(?P<tcname>.*)$",
            re.MULTILINE)
        for line in output.splitlines():
            m = regex.search(line)
            if m == None:
                continue
            d = m.groupdict()
            result = d['result']
            tcname = d['tcname']
            _result = tcfl.tc.result_c()
            self._output_subcase_parse(tcname, result, failures, other_errors)
        # for the toplevel test container, if we are here, we are
        # good. If any failure/error/skip, it will be reported by the
        # subcases
        return


    #
    # Linkage to the test discovery API
    #
    @classmethod
    def _list(cls, dirname, native_bindir, java_home, java_version):
        # List testsuites' testcases with jtreg

        if jtreg_dir == None:
            raise tcfl.tc.blocked_e(
                "please export env JTREG_DIR to point to the path "
                "of the built JTreg package; see documentation")

        # expand .. /  ... etc
        _dirname = os.path.realpath(dirname)
        logging.error("WIP: scanning test suite %s, will take a few secs",
                      dirname)
        if native_bindir:
            # if we have bindirs with native code built, we have put
            # them in /opt/SOMETHING; do the string so we can run
            # those testcases
            native_cmdline = "-exclude:%s/exclude.list" % native_bindir
        else:
            native_cmdline = ""
        _env = dict(os.environ)
        _env["JAVA_HOME"] = java_home
        _env["PATH"] = java_home + "/bin:" + _env.get("PATH", "")
        # we have set JAVA_HOME and the PATH to *that* JAVA_HOME,
        # so `java`  shall run that version period the end.
        # We need to specify a JTWork directory that is specific to
        # the version of java we are running, so when we are executing
        # things from different versions at the same time they do not
        # conflict with each other
        jtwork_dir = os.path.join(
            cls.tmpdir,
            commonl.file_name_make_safe(dirname),
            "JTWork-%s" % commonl.file_name_make_safe(java_version))
        output = subprocess.check_output(
            "java -jar %s/lib/jtreg.jar %s -l -w:'%s' '%s'" % (
                jtreg_dir, native_cmdline, jtwork_dir, dirname),
            shell = True, env = _env, stderr = subprocess.STDOUT)
        # So that thing prints
        #
        ## $ java -jar %s/lib/jtreg.jar -l PATH/DIRNAME/def/1.java
        ## output 0 Directory "JTwork" not found: creating
        ## Testsuite: PATH
        ## ....
        ## dirname/DEF/1.java#id0
        ## dirname/DEF/1.java#id1
        ## dirname/DEF/1.java#id2
        ## ...
        ## Tests found: 3
        #
        # All merged on stdout, yay
        #
        tcs = []
        ts = None
        for line in output.splitlines():
            if line.startswith("Testsuite: "):
                ts = line[len("Testsuite: "):]
            elif line.startswith("Tests found: "):
                continue	# bleh
            else:
                tcs.append(line.strip())
        return ts, tcs

    _filename_regex = re.compile(r"^.*\.(java|sh)$")
    # if the file has a comment @test, being .sh or .java, chances are
    # it is a java test, this has to match:
    _test_regex = re.compile(
        rb"^\s*("
        # This tries to match all the combinations of @test inside
        # some Java or Shell comment block:
        # # @test
        # ## @test
        # ### @test
        # /* @test
        # /**@test
        # /*
        #  * @test
        #  ** @test
        #   @test
        # ...
        # usually to this there can be some name following
        rb"(#+|/\*+|\*+|\s)\s*@test\s.*"
        rb"|"
        # this matches the @Test tag in the NG testcases, which
        # standalone as part of code, not comments
        rb"@Test"
        rb")\s*$",
        re.MULTILINE)

    # Dictionary of testsuites and the testcases they declare, as
    # found by _list() above.
    _test_suites = { }

    testcases = {}
    path_jdk = {}
    test_roots = {}

    @staticmethod
    def _test_root_find(path):
        # find which parent of `path` has a TEST.ROOT file, definining
        # a JTReg test suite
        head = os.path.realpath(path)
        _head, _tail = os.path.split(head)
        location = None
        while _head != head:
            head = _head
            location = os.path.join(head, 'TEST.ROOT')
            if os.path.exists(location):
                return head
            _head, _tail = os.path.split(head)
        return None

    java_version_regex = re.compile("[0-9]+")
    jdk_path_version_regex = re.compile("jdk(?P<version>[0-9]+)u")

    # FIXME: move to new signature
    @classmethod
    def is_testcase(cls, path, path_cmdline):
        """Detect if a file is a JTREG testcase and create a testcase
        object for it.

        Groups the cases for execution by the original path on which
        they were called in the TCF command line; look at the
        :ref:`reference for the directory
        layout<jtreg_directory_layout>` to get context for this
        process.

        """
        if not cls._filename_regex.match(path):
            logging.debug("%s: ignored for not matching name %s",
                          path, cls._filename_regex.pattern)
            return []
        if not _file_scan_regex(path, cls._test_regex):
            logging.debug("%s: ignored for not containing %s",
                          path, cls._test_regex.pattern)
            return []

        # remove trailing backslashes and find abs
        path_cmdline = os.path.normpath(path_cmdline)
        path_cmdline_abs = os.path.abspath(path_cmdline)
        path_cmdline_dirname = os.path.dirname(path_cmdline_abs)
        # Find the testsuite top level, where the TEST.ROOT is;
        # later we'll cache the testsuite-under-TEST.ROOT scanning for
        # other calls, as it takes time.
        if path_cmdline_dirname in cls.test_roots:
            # someone already resolved this directory
            path_test_root_abs = cls.test_roots[path_cmdline_dirname]
            # yeah, this could be smarter and also resolve anything
            # removing components until path_test_root_abs. Tomorrow.
        else:
            # slow, let's resolve it
            path_test_root_abs = cls._test_root_find(path)
            if path_test_root_abs == None:
                logging.debug("%s: ignoring, no TEST.ROOT file"
                              " found in parents", path)
                return [ ]
            cls.test_roots[path_cmdline_dirname] = path_test_root_abs

        # Is path_cmdline_abs above or below path_test_root? If it is
        # above, then the toplevel will be at the TEST.ROOT level,
        # otherwise at the path_cmdline level. A vs B in the
        # documentation.
        if os.path.commonprefix([ path_cmdline_abs, path_test_root_abs ]) \
           == path_cmdline_abs:
            # we were called above the testsuite level (TEST.ROOT), so
            # we are going to unfold into a testcase per TEST.ROOT
            # contained under path_cmdline
            # path_cmdline                 b/
            # path_cmdline_abs             $PWD/b
            # TEST.ROOT is                 b/c/TEST.ROOT
            path_toplevel_abs = path_test_root_abs
            path_toplevel = os.path.normpath(os.path.join(
                # normpath needed to remove trailing/leading [/.] etc
                path_cmdline,
                os.path.relpath(path_test_root_abs, path_cmdline)
            ))
            logging.info("%s: running above TEST.ROOT directory %s",
                         path_cmdline, path_toplevel)
        else:
            # we were called below the testsuite level (TEST.ROOT), so
            # path_cmdline                  b/c/d/e/f
            # path_cmdline_abs              $PWD/b/c/d/e/f
            # TEST.ROOT                     $PWD/b/c/TEST.ROOT
            path_toplevel_abs = path_cmdline_abs
            path_toplevel = path_cmdline
            logging.info("%s: running under TEST.ROOT directory %s",
                         path_cmdline, path_toplevel)
        logging.info("JTREG paths toplevel %s", path_toplevel)

        # unfold all possible symlinks and stuff to calculate the
        # relative path in the testsuite (which we also unfolded above)
        path_real = os.path.realpath(path)

        java_version = os.environ.get('JAVA_VERSION', None)
        if java_version and not cls.java_version_regex.match(java_version):
            raise tcfl.tc.blocked_e(
                "JAVA_VERSION environment variable is not in the "
                "format of a single decimal digit matching %s (got '%s')"
                % (cls.java_version_regex.pattern, java_version))

        while java_version == None:
            # guess based on the TC's path; only recognizes so far
            # things called SOMETHING/jdkVERSIONu/SOMETHINGelse

            # guess first on the abspath given by the TCF testcase
            # explorer from the top level command line
            # (without undoing any possible symlinks)
            m = cls.jdk_path_version_regex.search(os.path.abspath(path))
            if m:
                java_version = m.groupdict()['version']
                break

            # if that didn't work, try the same but expanding symlinks
            # see if that yields extra info? This seems like overkill
            # but I had the code already...
            m = cls.jdk_path_version_regex.search(path_real)
            if m:
                java_version = m.groupdict()['version']
                break

            raise tcfl.tc.blocked_e(
                "%s: can't determine major Java version from path;"
                " export JAVA_VERSION or name path"
                " PATH/jdkVERSIONu/SOMETHING" % path)

        # Is there a native built tree for this version? it will
        # enable executing the testcases that need native built
        # components
        if 'JDK%s_BINDIR' % java_version in os.environ:
            native_bindir = os.environ['JDK%s_BINDIR' % java_version]
        else:
            native_bindir = None

        # We need JAVE_HOME defined properly for the version
        java_home = os.environ.get("JAVA%s_HOME" % java_version, None)
        if java_home == None:
            raise tcfl.tc.blocked_e(
                "export location of Java v%s in environment JAVA%s_HOME"
                % (java_version, java_version))

        # Okies, got a root for the testuite, so let's list in there.
        # It might take a long time to load/scan, so when we do it,
        # cache it to reuse for the next file we are evaluating.
        #
        # Note we key the testsuite name by real absolute path, to
        # avoid confusions when jtreg decides to absolutize things
        if not path_test_root_abs in cls._test_suites:
            # the returned test root is normalized; we ignore the
            # returned test root, as we want to keep the
            # one we have, derived from the command line (because
            # that's what the user wants to see, with no symlinks or
            # whatever expanded)
            _, tcs = cls._list(path_test_root_abs, native_bindir,
                               java_home, java_version)
            cls._test_suites[path_test_root_abs] = set(tcs)
        else:
            tcs = cls._test_suites[path_test_root_abs]

        # Now, check the `path` we were given by the scanner; the path
        # relative to the test root has to be contained in the list of
        # testcases the test suite jtreg declared when listing
        path_tc_rel_to_test_root = os.path.relpath(path_real,
                                                   path_test_root_abs)
        # some testcases are listead as PATH#id0, PATH#id1 ... because
        # they contain multiple cases, so let's see if it is the case
        # with this path
        ids = filter(lambda i: i.startswith(path_tc_rel_to_test_root
                                            + "#id"),
                     tcs)
        if ids == [] and path_tc_rel_to_test_root not in tcs:
            logging.debug("%s: ignored, path %s not in testsuite",
                          path, path_tc_rel_to_test_root)
            return [ ]

        path_test_root = os.path.relpath(path_test_root_abs,
                                         os.path.dirname(path))

        # We got a valid case; the file is recognized by jtreg

        # Now, we are creating a testcase object per each
        # path_toplevel that we have figured out above (either from
        # the command line or found); this testcase object will run
        # anything found under `path_toplevel` as subcases in a a single
        # instance of Java.
        #
        # so, if the toplevel is already registered, we use that,
        # otherwise create a new one.
        # This way the caller can decide the level of parallelization
        # by toggling the command line.
        if path_toplevel_abs not in cls.testcases:
            # we pass the path where we are supposed to start
            # executing relative to the testsuite
            tc = cls(path_toplevel, path_test_root,
                     java_version, native_bindir)
            cls.testcases[path_cmdline_abs] = tc
            r = [ tc ] # we'll tell the core about this testcase

            # Figure out where the top of the JDK tree is
            tc.path_jdk = subprocess.check_output(
                [
                    'git', 'rev-parse', '--flags', '--show-toplevel', path,
                ],
                stderr = subprocess.STDOUT,
                # CDing into the toplevel dir makes it work if we are
                # calling from inside the git tree or from outside
                cwd = os.path.dirname(path)
            ).strip()
            tc.path_jdk_to_test_root = os.path.relpath(
                path_test_root_abs, os.path.dirname(tc.path_jdk))
            # --by saving it here we don't have to run the git command
            # for every single testcase.
            cls.path_jdk[path_cmdline_abs] = tc.path_jdk
        else:
            tc = cls.testcases[path_cmdline_abs]
            r = []  # no need to tell the core, we did already when we
                    # created it

        # Find the relative path from the whaerver/jdkX.git to the
        # a/b/c/TEST.ROOT (the a/b/c)
        path_jdk = cls.path_jdk[path_cmdline_abs]
        path_jdk_to_test_root = os.path.relpath(path_test_root_abs,
                                                os.path.dirname(path_jdk))
        # now inform it it will also run this subcase -- we key the
        # subcase relative to the path to the test_root because in
        # eval_10_execute(), when we run them that's how we get the
        # results, so it will be eaiser to key.
        if ids:
            # tcs that generate NAME#id subtestcases, one subcase for each
            # remember i is TEST.ROOT/NAME#id, so NAME is rel to TEST.ROOT
            for i in ids:
                index_name = os.path.join(path_jdk_to_test_root, i)
                tc.subtc[i] = tcfl.tc.subtc_c(index_name, path, path, tc)
        else:
            tc.subtc[path_tc_rel_to_test_root] = tcfl.tc.subtc_c(
                os.path.join(path_jdk_to_test_root, path_tc_rel_to_test_root),
                path, path, tc)

        return r

# hook it up to the core
tcfl.tc.tc_c.driver_add(driver)
