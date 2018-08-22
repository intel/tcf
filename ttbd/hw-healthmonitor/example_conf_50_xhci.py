# pylint: disable = missing-docstring, undefined-variable

# Watch all XHCI HCD controllers
#
# The brand of XHCI controllers we have crash when subject to plenty
# of turture and these are their symptoms.
#
# When that happens, just rebind the driver to reset them.
config_watch_add("pci", "xhci_hcd", None, {
    # Apr 20 01:46:12 ... kernel: xhci_hcd 0000:00:14.0: HC died; cleaning up
    #
    # Just reload the thing
    'HC died; cleaning up': action_driver_rebind,
    # Apr 24 01:51:36 ... kernel: xhci_hcd 0000:00:14.0: Timeout while waiting
    #                             for setup device command
    #
    # If more than five of these happen in 1 minute (60 seconds),
    # rebind the driver
    'Timeout while waiting for setup device command': (
        action_driver_rebind_threshold, 5, 60
    ),
    # Apr 20 14:35:55 ... kernel: xhci_hcd 0000:02:00.0: Host halt failed, -110
    #
    # Just reload the thing
    'Host halt failed': action_driver_rebind,
})
