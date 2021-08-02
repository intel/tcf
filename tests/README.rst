Bitrotten tests
---------------

- Zephyr build / deploy

  - zephyr hello_world

- test reporting with bad UTF

- basic console

- basic debug

Features
--------

- extend release hooks -> tt_interface_impl_c
- current testcase set in msgid/context
- report_*() add to the counts of the current testcase
  
- remove tests/symlinks, hardcode paths
  
- FIXME: hack no arguments to @tcfl.tc.target so no () are needed http://stackoverflow.com/a/3932122

- signalling up and down for verbosity control

- mix report_c with exception types: XYZ_e / report_c

- deprecate/remove test_*

  
Failing
-------

- failing catches server error messages, patch up
  - test_buttons.py
  - test_store_paths
  - test_tunnels.py
  - test_images_parallel.py
  - test_store_paths
  - test_power_sequence: gets stuck too
  - test_power_fake
  - test_alloc_release_on_rm
  - test_alloc_timesout.py
    
- gets stuck allocation/queued
  - test_images_parallel_retry.py
  - test_images_parallel.py
  - test_capture_tcpdump

- test_images_flash_shell.py 
- test_alloc_basic.py 
