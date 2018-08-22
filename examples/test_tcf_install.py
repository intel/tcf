#/usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import tcfl.tc

branch = os.environ.get("TCF_BRANCH_SHORT", "master")

# Pick up repos
RPM_REPO_URL = os.getenv("RPM_REPO_URL", None)
TCF_RPM_REPO_URL = os.getenv("TCF_RPM_REPO_URL")

# Pick up proxying
HTTP_PROXY = os.getenv("HTTP_PROXY", os.getenv("http_proxy", None))
HTTPS_PROXY = os.getenv("HTTPS_PROXY", os.getenv("https_proxy", None))
NO_PROXY = os.getenv("NO_PROXY", os.getenv("no_proxy", None))

@tcfl.tc.tags(ignore_example = True)
@tcfl.tc.target(
    name = 'linux',
    spec = 'type:"^qemu-linux-fedora.*" and nat_host')
class _test(tcfl.tc.tc_c):
    """
    Test script to test installing TTBD & TCF in a freshly installed
    Fedora machine and running a few Zephyr tests on it.

    This relies on the default qlf* virtual machines installed
    by a defaul TTBD install.

    Requires:

    - upstream connectivity to the Internet (*nat_host*)
      (will acknoledge {HTTP[S],NO}_PROXY
    """

    def start(self, linux):
        self.linux = linux	# for _cmd()
        linux.power.cycle()
        linux.on_console_rx("Out of memory: Kill process",
                            result = "fail", timeout = False)


    def _cmd(self, cmd, expect = None):
        self.linux.send(cmd)
        if expect:
            if isinstance(expect, list):
                for item in expect:
                    self.linux.expect(item)
            else:
                self.linux.expect(expect)
        self.linux.expect(re.compile(r" [0-9]+ \$ "))

    def eval_01_shell_up(self, linux):
        # Network updates/downloads take long
        self.expecter.timeout = 2800
        linux.expect(re.compile(r" [0-9]+ \$ "))

    def eval_02_setup(self, linux):

        # fix term, disable editing, to get proper console reporting
        # Trap the shell to complain loud if a command fails, and catch it
        self._cmd("echo 'set horizonal-scroll-mode Off' >> /etc/inputrc")
        self._cmd("""\
cat <<EOF >> /etc/bashrc
export TERM="dumb"
tset
trap 'echo ERROR-IN-SHELL' ERR
EOF
""")

        # Need proxy, to access external hosts
        if True:
            # Inject proxy environment
            if HTTP_PROXY:
                self._cmd("echo 'export HTTP_PROXY=" + HTTP_PROXY
                          + "' >> /etc/bashrc")
            if HTTPS_PROXY:
                self._cmd("echo 'export HTTPS_PROXY=" + HTTPS_PROXY
                          + "' >> /etc/bashrc")
            if NO_PROXY:
                self._cmd("echo 'export NO_PROXY=" + NO_PROXY
                          + "' >> /etc/bashrc")

            # sudo + proxy
            self._cmd("""\
tee /etc/sudoers.d/proxy <<EOF
# Keep proxy configuration through sudo, so we don't need to specify -E
# to carry it
Defaults env_keep += "ALL_PROXY FTP_PROXY HTTPS_PROXY HTTP_PROXY NO_PROXY"
EOF
""")

            # exit the shell so the shell gets the proxy stuff when the
            # console re-logins
            self._cmd("exit")

        # match on beginning of line to make sure we don't match on
        # the command that is setting up the trap.
        linux.on_console_rx(re.compile("^ERROR-IN-SHELL", re.MULTILINE),
                            result = 'fail', timeout = False)

    def eval_04_dnf_update_stuff(self, linux):

        # Set a new RPM repository from the RPM_REPO_URL
        # environment variable.
        #
        # This is used so the target fetches updates from a server
        # that is closer to you in the network topology
        # sense. Otherwise, default to Fedora's default.
        #
        # *http://SERVERNAME/PATH* has to point to a
        # location that contains the *fedora* subdirectory.
        if RPM_REPO_URL:
            linux.report_info("Updating RPM repository to %s" % RPM_REPO_URL,
                              dlevel = -1)
            self._cmd("sed -i 's|^metalink=|#metalink=|' /etc/yum.repos.d/*.repo")
            self._cmd("sed -i 's|#baseurl=http://download.fedoraproject.org/pub|baseurl=%s|' /etc/yum.repos.d/*.repo" % RPM_REPO_URL)
            self._cmd("for v in /etc/yum.repos.d/*.repo; do echo; echo --- $v ---; cat $v; done")


        # Network operations take a long time
        self.expecter.timeout = 800
        # This takes for ever and is not that needed
        self._cmd("dnf config-manager --set-disabled updates")

        if False:
            # This takes too long and is not necessary
            self._cmd("dnf update -y")

    def eval_10_tcf_install(self, linux):
        self._cmd("echo insecure > ~/.curlrc")
        self._cmd("rpm -i %s/repo/tcf-repo-%s-1-1.noarch.rpm"
                  % (TCF_RPM_REPO_URL, branch))

        # DEBUG
        self._cmd("ip addr show")

        # DNF install takes for ever, because it has to update the
        # stupd caches, so dep on the network connection, this might
        # fail. Heh.
        self._cmd("dnf install -y --downloadonly --allowerasing ttbd-zephyr")
        # Broken in two parts, first download, then run-sometimes it
        # gets stuck and this helps avoid that and diagnose
        self._cmd("dnf install -y --allowerasing ttbd-zephyr")

        # RPM configuraton has local auth local server enabled
        self._cmd("systemctl enable ttbd@production")
        self._cmd("systemctl start ttbd@production")

    def eval_11_user_test(self, linux):
        # Create a non-priviledged user to run tests, login as that
        self._cmd("useradd test")
        self._cmd("su -l test")

    def eval_12_tcf_run(self, linux):
        self.linux.send("tcf login test")
        self.linux.expect("Password: ")
        self._cmd("")

        self._cmd("tcf list", [
            # Check for a few of the targets defined by default
            re.compile(r"local/nwa"),
            re.compile(r"local/ql06a"),
            re.compile(r"local/qz49a-riscv32"),
            re.compile(r" [0-9]+ \$ "),
        ])

        self._cmd("tcf healthcheck nwa")
        if False:
            # Can't do these, cloud image not uploaded
            self._cmd("tcf healthcheck ql06b")
            # Can't do these, because they have no image assigned
            self._cmd("tcf healthcheck qz30a-x86")
            self._cmd("tcf healthcheck qz35a-arm")
            self._cmd("tcf healthcheck qz40a-nios2")
            self._cmd("tcf healthcheck qz45a-riscv32")

    def eval_13_tcf_zephyr_run(self, linux):
        self._cmd("git clone -q http://github.com/zephyrproject-rtos/zephyr zephyr.git")
        self._cmd("cd zephyr.git")
        self._cmd("export ZEPHYR_BASE=$PWD")
        self._cmd("time tcf run -t 'bsp and bsp != \"riscv32\"' -v /usr/share/tcf/examples/test_zephyr_hello_world.py",
                  "PASS0/")
        self._cmd("time tcf run -v /usr/share/tcf/examples/test_zephyr_echo.py", "PASS0/")

    def eval_13_tcf_unit_tests(self, linux):
        if True:
            return
        self._cmd("export TTBD_PATH=/usr/bin/ttbd")
        self._cmd("cd /usr/share/tcf/tests")
        self._cmd("./run.sh")

    # FIXME:
    #  - prime Zephyr
    #  - set an address
    #  - dumb terminal

    # test local stuff, networking
