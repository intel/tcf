#! /usr/bin/env python
"""
Example report driver
"""
import threading
import time
import tcfl.report
import tcfl.tc

class report_ex_c(tcfl.report.report_c):
    """
    Example report driver
    """

    def __init__(self, log_file_name):
        tcfl.report.report_c.__init__(self)
        self.log_file_name = log_file_name
        with open(log_file_name, "w") as f:
            f.write("%f started" % time.time())
        self.lock = threading.Lock()

    def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
        """
        Report data

        Note this can be called concurrently, so the file could be
        overriden; measures to avoid that involve a lock, like what is
        used here.

        """
        # We don't operate on the global reporter
        if getattr(_tc, "skip_reports", False) == True:
            return
        # The top level completion message starts with COMPLETION
        if not message.startswith("COMPLETION"):
            return

        # _tc can be a target_c, but not for COMPLETION
        assert isinstance(_tc, tcfl.tc.tc_c)

        # Write it down!
        with self.lock, open(self.log_file_name, "w") as f:
            f.write("%s DEBUG HASHID %s TC %s RESULT %s\n" %
                    (time.time(), _tc.ticket, _tc.name, tag))
            for twn, target in _tc.targets.items():
                f.write("DEBUG    TARGET %s = %s:%s\n" % (twn, target.fullid,
                                                          target.bsp_model))

tcfl.report.report_c.driver_add(report_ex_c("results.log"))
