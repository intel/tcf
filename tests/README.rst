Bitrotten tests
---------------

- Zephyr build / deploy

  - zephyr hello_world

- test reporting with bad UTF

- basic console

- basic debug

Features
--------

- remove tests/symlinks, hardcode paths
  
- FIXME: hack no arguments to @tcfl.tc.target so no () are needed http://stackoverflow.com/a/3932122

- signalling up and down for verbosity control

- mix report_c with exception types: XYZ_e / report_c



  
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
    
- test_tcfl_tc_run_method_return_values.py - not working ok

- test_server_version

- test_properties

- gets stuck allocation/queued
  - test_images_parallel_retry.py
  - test_images_parallel.py
  - test_capture_tcpdump

- test_images_estimated_duration.py
- test_images_flash_shell.py 
- test_fsdb_symlink.py 
- test_debug_loopback: needs readjustment on how it tests debug state
  is cleared on release
- test_alloc_basic.py 
