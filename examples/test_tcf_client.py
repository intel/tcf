#! /usr/bin/python
#

import re

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _base(tcfl.tc.tc_c):

    def deploy_10(self, ic, target):
        ic.power.cycle()
        tcfl.pos.deploy_image(ic, target, self.image)

    def start_10(self, target):
        # If there are errors, exceptions will come,but otherwise we
        # are here, still in the service OS, so reboot into our new OS
        target.power.cycle()
        self._targets_active()
        target.shell.linux_shell_prompt_regex = re.compile('root@.*# ')
        target.shell.up(user = 'root')
        target.report_pass("booted")
        self._targets_active()


    def eval_10_setup(self, ic, target):
        """
        Sets the target up:

        - export a proxy if one needed in /etc/bashrc
        - install python-pip2
        - add a testuser, login into it
        """
        if 'http_proxy' in ic.kws:
            target.shell.run("""\
cat >> /etc/bashrc <<EOF
export http_proxy=%s
export HTTP_PROXY=%s
""" % ic.kws.get('http_proxy'), ic.kws.get('http_proxy'))

        if 'https_proxy' in ic.kws:
            target.shell.run("""\
cat >> /etc/bashrc <<EOF
export https_proxy=%s
export HTTPS_PROXY=%s
""" % ic.kws.get('https_proxy'), ic.kws.get('https_proxy'))

        self.tls.expecter.timeout = 120
        target.shell.run("dnf install -y python2-pip")
        self.tls.expecter.timeout = 30

        target.shell.run("useradd testuser")
        target.shell.linux_shell_prompt_regex = re.compile(r'testuser@.*\$ ')
        target.shell.run("su - testuser")
        target.shell.up()
        # Note the proxy setting in /etc/bashrc is now picked up automagically


    def server_install(self, ic, target):
        """
        Install the server following the same steps as the
        :ref:`server installation guide <install_tcf_server_rpms>`
        """
        target.shell.run("git clone http://github.com/intel/tcf tcf.git")
        target.shell.run("cd tcf.git")
        git_version = target.shell.run("git describe", output = True)
        # this comes as:
        # git describe
        # v0.11-69-g9900ff2
        # [testuser@localhost tcf.git]$
        self.git_version = git_version.split('\n')[1].strip()
        self.report_info("git version: %s" % self.git_version)

        target.shell.run("pip2 install --user -r requirements.txt")
        target.shell.run("python2 setup.py install --user")
        target.shell.run("cd zephyr")
        target.shell.run("python2 setup.py install --user")


    def client_quickstart_install(self, ic, target):
        """
        Install the client following the same  steps as the
        :ref:`quickstart <install_tcf_client>`
        """
        target.shell.run("git clone http://github.com/intel/tcf tcf.git")
        target.shell.run("cd tcf.git")
        git_version = target.shell.run("git describe", output = True)
        # this comes as:
        # git describe
        # v0.11-69-g9900ff2
        # [testuser@localhost tcf.git]$
        self.git_version = git_version.split('\n')[1].strip()
        self.report_info("git version: %s" % self.git_version)

        target.shell.run("pip2 install --user -r requirements.txt")
        target.shell.run("python2 setup.py install --user")
        target.shell.run("cd zephyr")
        target.shell.run("python2 setup.py install --user")


    def client_bat(self, ic, target):
        target.shell.run("cd")
        tcf_version = target.shell.run("tcf --version", output = True)
        # this comes as:
        # tcf --version
        # 0.11-68-g067c78f-dirty
        # [testuser@localhost tcf.git]$
        tcf_version = tcf_version.split("\n")[1].strip()
        if tcf_version != self.git_version:
            raise tcfl.tc.failed_e(
                "running version (%s) of tcf doesn't match "
                "checked out version (%s)" % (self.git_version, tcf_version))
        target.shell.run("tcf --help")
        target.shell.run("tcf list")


    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)


class _clear_client_install(_base):

    image = "clear"

    def eval_30_client_bat(self, ic, target):
        self.client_quickstart_install(ic, target)
        self.client_bat(ic, target)


# FIXME: add decorator to ignore a testcase
#class _fedora_client_install(_base):
#
#    image = "fedora"
#
#    def eval_30_client_bat(self, ic, target):
#        self.client_quickstart_install(ic, target)
#        self.client_bat(ic, target)
#
