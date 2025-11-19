#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Control power with Raritan PX PDUs
----------------------------------

This interface provides means to power on/off outlets in Raritan PX PDUs

"""

import logging
import re

import pexpect

import commonl
import ttbl


class pc(ttbl.power.impl_c):
    """Driver for Raritan PX2 Smart PDU over SSH

    :param str device_spec: *USERNAME:PASSWORD@HOSTNAME:OUTLET* PDU
      hostname, username and password to access and outlet number to
      toggle.

    >>> import ttbl.raritan_px
    >>>
    >>> pc = ttbl.raritan_px.pc('USERNAME:PASSWORD@HOSTNAME:OUTLET')
    >>>
    >>> target.interface_add("power", ttbl.power.interface(AC = pc))

    **Requirements**

    Requires the *pexpect* package, the standard openssh client and
    the *sshpass* package.

    **Architecture**
    
    It works by spawning an SSH connection to the PDU, which needs
    to be configured to allow it and then issue the commands to get,
    turn on and off::

      # show outlets 20
      Outlet 20: 20 (no name)
      Power state: On
    
      # power outlets 20 on
      Do you wish to turn outlet 20 on? [y/n] y

    Note this is a multiprocess server, so multiple processes will
    have an ongoing expect object that runs the SSH connection process
    under it.

    The commands dynamically create a connection as needed and if
    there is a failure, will try to restart it automatically three
    times, before failing.

    **Rationale:** I was not able to find any JSON-RPC APIs that would
    work with old PDUs.
    """
    def __init__(self, device_spec: str,
                 prompt_regex: re.Pattern = re.compile(br".*[>#]\s*\Z", re.MULTILINE),
                 **kwargs):

        assert isinstance(prompt_regex, re.Pattern), \
            f"prompt_regex: expected re.Pattern, got [{type(prompt_regex)}] '{prompt_regex}'"

        ttbl.power.impl_c.__init__(self, **kwargs)
        self.user = None
        self.password = None
        self.hostname = None

        self.p = None
        self.device_spec = device_spec

        self.user_orig, self.password_orig, self.hostname_orig = \
            commonl.split_user_pwd_hostname(device_spec, expand_password = False)

        if not self.password_orig:
            password_publish = None
        elif self.password_orig.split(":", 1)[0] in ( "KEYRING", "FILE", "ENVIRONMENT" ):
            # this means the password is taken off a keyring, it is
            # safe to publish, since it is a reference to the storage place
            password_publish = self.password_orig
        else:		            # this is a plain text passsword
            password_publish = "<plain-text-password-censored>"
        hostname_nopasswd = f"{self.user_orig}@{self.hostname_orig}"
        self.prompt_regex = prompt_regex
        self.upid_set(f"Raritan PX PDU {hostname_nopasswd}",
                      hostname = hostname_nopasswd,
                      # not publishing the outlet number since it will
                      # make it confusing on how to update it - we
                      # want to update the min
                      password = password_publish)



    class exception(RuntimeError):
        pass



    def _resolve(self, target: ttbl.test_target) -> tuple:
        # resolve the parameters for the connection, since they might
        # have been updated in the inventory DB; default to whatever
        # was configured
        # we expect USER:PASSWORD@HOSTNAME:OUTLET
        device_spec = target.fsdb.get(
            f"instrumentation.{self.upid_index}.device_spec", self.device_spec)

        # by default, inventory
        # instrumentation.{self.upid_index}.hostname will always be
        # set to USER@HOSTNAME:OUTLET, whatever we configured; we
        # censored whatever password it had. So if splitting yields an
        # empty password but the rest of hte fields are the same, we
        # need to redo with self.device_spec
        user, password, hostname = \
            commonl.split_user_pwd_hostname(device_spec)
        if self.password == None \
           and user == self.user_orig \
           and hostname == self.hostname_orig:
            user, self.password, hostname = \
                commonl.split_user_pwd_hostname(device_spec)
        if ':' not in hostname:
            raise self.exception(
                f"{device_spec}: missing :OUTLETNUMBER specification")
        try:
            hostname, outlet = hostname.split(":", 1)
            self.outlet = int(outlet)
        except ValueError as e:
            raise self.exception(
                f"{hostname}: can't parse '{outlet}' as an integer: {e}") from e

        # did the username/pwd change from the last time we ran? if it
        # did...remove the expect object so we create a new connection
        if hostname != self.hostname \
           or user != self.user \
           or password != self.password:
            del self.p
            self.p = None
        self.user = user
        self.password = password
        self.hostname = hostname

        if self.password == None:
            raise self.exception(
                f"{device_spec}: missing :PASSWORD@ specification")


    def _open_maybe(self, target: ttbl.test_target, component: str, log):
        if self.p:
            log.info("reusing connection")
            try:
                self.p.send(b"\r")
                self.p.expect(self.prompt_regex)
                log.info("found prompt")
                return
            except Exception as e:
                self.p = None
                log.info(f"reopening connection because {e}")

        try:
            log.info("opening connection")
            self.p = pexpect.spawn(
                "sshpass",
                [
                    # FIXME: move to environment, leaks in logs, etc
                    "-p", self.password,
                    "ssh",
                    # be verbose (for debugging) and allocate a terminal
                    "-vtt",
                    # We place the control file for the shared
                    # connection in /var/cache/ttbd-production/ssh-NAME-HOSTNAME.control;
                    # this way is shared by all targets that same the
                    # same PDU and username to it.
                    #
                    # IF DISABLED IT WILL OVERWHELM THE PDU WITH CONNECTIONS
                    "-oControlMaster no",
                    f"-oControlPath {ttbl.test_target.files_path}/ssh-{self.user}-{self.hostname}.control",
                    # old SSH impl in the PDU requires old algorithms
                    "-oPubkeyAcceptedAlgorithms +ssh-rsa,ssh-dss",
                    "-oHostKeyAlgorithms +ssh-rsa,ssh-dss",
                    # we can't do any of this registering, so we
                    # disable it so SSH doesn't ask for it
                    # interactively and makes a mess
                    "-oUserKnownHostsFile /dev/null",
                    "-oCheckHostIP no",
                    "-oStrictHostKeyChecking no",
                    f"{self.user}@{self.hostname}"
                ],
                # this timeout seems to overtake the rest we specify
                # manually, so we set the max, what it takes to get
                # the Welcome message which is longish
                timeout = 30)
            # ok, problem--if we have multiple connections from
            # different processes, they will step over each other--in
            # theory only one processes shall open for each
            # component. cross fingers.
            self.p.logfile = open(f"{target.state_dir}/{component}-ssh.log", 'wb')
            log.info("opened connection")
            self.p.expect(
                re.compile(b"Welcome to PX.* CLI!", re.MULTILINE | re.DOTALL),
                # original prompt message takes longish
                timeout = 30)
            log.info("found welcome message")
            self.p.send(b'\r')
            self.p.expect(self.prompt_regex)
            log.info("found prompt")
            return

        except Exception as e:
            log.info(f"opening connection to {self.user}@{self.hostname} failed: {e}")
            del self.p	# connection died, so clean it up so it is redone
            self.p = None
            raise



    def _expect(self, expectation, timeout: int = 5, log = logging):
        try:
            log.info(f"expecting {expectation}")
            self.p.expect(expectation, timeout = timeout)
            return self.p.match.group(0)
        except pexpect.exceptions.EOF as e:
            log.info(f"didn't find (EOF): {expectation}")
            del self.p	# connection died, so clean it up so it is redone
            self.p = None
            raise self.exception(
                f"{self.user}@{self.hostname}: connection died; is it on?") \
                from e
        except pexpect.exceptions.TIMEOUT as e:
            log.info(f"didn't find (TIMEOUT): {expectation}")
            raise self.exception(
                f"{self.user}@{self.hostname}: timeout ({timeout}s)"
                f" receiving '{expectation}'") from e



    regex_get = re.compile(rb"Power state: (?P<state>\w+)")

    def get(self, target: ttbl.test_target, component: str):
        self._resolve(target)
        log = logging.getLogger(f"target-{target.id}[{target.owner_get()}]|px_ssh|{self.user}@{self.hostname}")
        last_e = None
        for _count in range(3):
            try:
                self._open_maybe(target, component, log)
                # this would be
                ## # show outlets 20
                ## Outlet 20: 20 (no name)
                ## Power state: On
                self.p.send(f"show outlets {self.outlet}\r")
                s = self._expect(self.regex_get, log = log)
                # s now would be *Power state: On*
                self._expect(self.prompt_regex, log = log)
                log.info("got response to 'show outlets': %s", s)
                m = self.regex_get.search(s)
                if not m:
                    raise self.exception(
                        f"can't get state: can't parse response: {s}")
                state = m.groupdict().get('state', None)
                if not state:
                    raise self.exception(
                        "can't get state: can't extract state from response")
                state = state.decode().lower()
                if state.lower() == "on":
                    return True
                if state.lower() == "off":
                    return False
                raise self.exception(
                    f"can't get state: unknown state {state}")
            except self.exception as e:
                last_e = e
            except Exception as e:
                log.error("BUG? error: %s", e, exc_info = commonl.debug_traces)
                last_e = e
            finally:
                if self.p:
                    self.p.close()
                    del self.p
                    self.p = None

        raise self.exception(
            f"{self.user}@{self.hostname}: can't get state:"
            f" {last_e}") from last_e



    def on(self, target: ttbl.test_target, component: str):
        self._resolve(target)
        log = logging.getLogger(f"target-{target.id}[{target.owner_get()}]|px_ssh|{self.user}@{self.hostname}")
        last_e = None
        for _count in range(3):
            try:
                self._open_maybe(target, component, log)
                self.p.send(f"power outlets {self.outlet} on /y\r")
                ## # power outlets 20 on /y
                ## #
                self._expect(	# verify the echo as a way of "we got it"
                    re.compile(b"power outlets [0-9]+ on /y"),
                    log = log)
                self._expect(self.prompt_regex, log = log)
                return
            except Exception as e:
                last_e = e
            finally:
                if self.p:
                    self.p.close()
                    del self.p
                    self.p = None

        raise self.exception(f"can't turn on: {last_e}") from last_e



    def off(self, target: ttbl.test_target, component: str):
        self._resolve(target)
        log = logging.getLogger(f"target-{target.id}[{target.owner_get()}]|px_ssh|{self.user}@{self.hostname}")
        last_e = None
        for _count in range(3):
            try:
                self._open_maybe(target, component, log)
                self.p.send(f"power outlets {self.outlet} off /y\r")
                ## # power outlets 20 off
                ## #
                self._expect(	# verify the echo as a way of "we got it"
                     re.compile(b"power outlets [0-9]+ off /y"),
                    log = log)
                self._expect(self.prompt_regex, log = log)
                return
            except Exception as e:
                last_e = e
            finally:
                if self.p:
                    self.p.close()
                    del self.p
                    self.p = None

        raise RuntimeError(
            f"{self.user}@{self.hostname}: can't turn off:"
            f" {last_e}") from last_e
