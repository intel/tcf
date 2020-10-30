#! /usr/bin/python3

import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Report an string with invalid UTF-8, see what happens.

    All the paths should succeed and ignore/map the bad UTF-8 to a
    character.
    """
    def eval(self):
        self.report_info("pass bad UTF-8\xff",
                         dict(message = "pass bad UTF-8\xff"))
