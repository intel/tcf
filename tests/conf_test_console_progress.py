#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import os
import time

try:
    import setproctitle
except ImportError:
    logging.warning(
        "module `setproctitle` not available;"
        " doing without")
    class setproctitle:
        def setproctitle(s: str):
            pass

import commonl
import ttbl
import ttbl.console

class console_progress_c(ttbl.console.generic_c):
    """
    Console debug class that prints messages periodically and one at
    the end

    :param dict messages: dict keyed by string message, values are
      periods at which to print; negative numbers are periods,
      positive at after X seconds print that and stop. Follows that
      only one of those is needed.

      >>> c0 = console_progress_c(
      >>>      messages = {
      >>>          "message_1": -1,    # print every second
      >>>          "message_2": -2,    # print every two seconds
      >>>          "message_3": 30,    # print only once after 30 seconds
      >>> }
    """
    def __init__(self, messages: dict, *args, **kwargs):
        ttbl.console.generic_c.__init__(self, *args, **kwargs)
        self.messages = messages


    def _write_loop(self, target, component):
        setproctitle.setproctitle(
            f"console_progress:{target.id}:{component}:"
            f" message generator"
        )
        write_file_name = os.path.join(target.state_dir,
                                       "console-%s.read" % component)
        timestamps = dict()
        ts0 = time.time()
        while True:
            ts = time.time()
            ellapsed = ts - ts0
            for message, period in self.messages.items():
                if period < 0:	# periodic
                    ts_last = timestamps.get(message, ts0)
                    ellapsed_message = ts - ts_last
                    if ellapsed_message >= abs(period):
                        target.log.info("console_progress: writing periodic message %s", message)
                        with open(write_file_name, "a") as wf:
                           wf.write(message + "\n")
                        timestamps[message] = ts
                elif period > 0 and ellapsed > period and not message in timestamps:
                    target.log.info("console_progress: writing final message %s", message)
                    with open(write_file_name, "a") as wf:
                        wf.write(message + "\n")
                    return
            time.sleep(0.5)



    def enable(self, target, component):
        read_file_name = os.path.join(target.state_dir,
                                       "console-%s.read" % component)
        write_file_name = os.path.join(target.state_dir,
                                       "console-%s.write" % component)
        # force it being created so we can pretend to write
        with open(read_file_name, "wb") as f:
            f.write(b"")
        # now symlink the read to the write file, so what we write is
        # read right away
        commonl.rm_f(write_file_name)
        os.symlink(
            read_file_name,
            write_file_name,
        )
        ttbl.console.generation_set(target, component)
        generation = target.property_get("interfaces.console." + component + ".generation")
        target.log.error(f"DEBUG: resetting {generation=}")
        c = commonl.fork_c(self._write_loop, target, component)
        c.start()
        ttbl.console.generic_c.enable(self, target, component)


    def disable(self, target, component):
        ttbl.console.generic_c.disable(self, target, component)


    def disable(self, target, component):
        ttbl.console.generic_c.disable(self, target, component)


    def state(self, target, component):
        return target.property_get(
            "interfaces.console." + component + ".state", False)



target = ttbl.test_target("t0")
target.interface_add(
    "console",
    ttbl.console.interface(
        c0 = console_progress_c(
            messages = {
                "message_1": -1,    # prints evert second
                "message_2": -2,    # prints every -2 seconds
                "message_3": 15,    # prints only once after 30 seconds
            }
        )
    )
)
ttbl.config.target_add(target)
