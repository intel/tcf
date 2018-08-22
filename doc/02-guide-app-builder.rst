.. _tcf_guide_app_builder:

App Builders
============

FIXME

.. _tcf_guide_app_builder_override:

Overriding actions
------------------

Any defined application builder will insert in the testcase, for each
named target (*targetX*) declared with :func:`tcfl.tc.target` (or
:func:`tcfl.tc.interconnect`) the following methods:

- ``configure_50_targetX(self, targetX)``
- ``build_50_targetX(self, targetX)``
- ``deploy_50_targetX(self, targetX)``
- ``setup_50_targetX(self, targetX)``
- ``start_50_targetX(self, targetX)``
- ``teardown_50_targetX(self, targetX)``
- ``clean_50_targetX(self, targetX)``

however, you can override any by defining it yourself in your test
class:

.. code-block:: python

   def build_50_targetX(self, targetX):
       targetX.report_info("Doing something else for building")
       ...

while you can still call the overriden function by its new name,
``overriden_build_50_target()``.

.. code-block:: python

   def build_50_targetX(self, targetX):
       targetX.report_info("Doing something else before building")
       ...
       self.overriden_build_50_target(self, targetX)

so the functionality is quite quick to reuse.

See ``test_zephyr_override.py``, where that is done to build Zephyr's
*Hello World!*:

.. literalinclude:: ../examples/test_zephyr_override.py

