#! /usr/bin/python3
import ttbl.config

class fake_if(ttbl.tt_interface):

    def _target_setup(self, target, _):
        target.fsdb.set("release_hook_called", None)

    def _release_hook(self, target, _force):
        target.fsdb.set("release_hook_called", True)

ttbl.config.target_max_idle = 2
t0 = ttbl.test_target('t0')
ttbl.config.target_add(t0)
t0.interface_add("fake", fake_if())
