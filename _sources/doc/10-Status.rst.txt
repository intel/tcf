.. _status:

========================
Current status and plans
========================

TCF is currently being used to drive HW testing of the `Zephyr OS
<https://zephyrproject.org>`_ inside Intel; while it was desigined with
it in mind, it is by no means restricted to running Zephyr
testcases.

Our current deployment looks like:

- six target servers spread around two continents
- Jenkins launching the runs on six different slaves in a matrix build
- around 70 MCU targets of 16 different types, covering x86, ARC,
  ARM and NIOS2 architectures plus PC-class machines, network
  (ethernet and bluetooth setups)
- power switches, `YKUSH <https://www.yepkit.com/products/ykush>`_
  power switching hubs, serial consoles, etc
- ansible used to keep all the servers setup correctly
  
Depending on how many runs are competing for the hardware, it usually
runs all of Zephyr Sanity Check plus a bunch of other internal
testcases, samples and combinations (totalling about 14000 testcases)
in 95min (~150 TCs/min).

This allows us to get almost realtime feedback on a continuous
integration manner. We are looking into extending this to commit
verification to provide feedback to developers on their proposed
changes.

Challenges
----------

Achieving high target-per-server density to reduce cost is possible,
the main problems being:

- USB bandwidth gets consumed rapidly, so more USB Host Controllers
  need to be added to the system

- these rates speed places huge strain on the USB host controllers (as
  the system is basically plugging/unplugging/resetting multiple
  devices way many times per minute) and some of them will just die
  and provide no feedback to the matter.  All that is left is a USB
  serial port that seems connected but provides no output, no signs in
  the kernel to tell what is going on.

  when this happens, a driver reenumeration sometimes helps, others
  just a server power-cycle will fix it. Enterprise class USB Host
  Controller hardware seems to take it better, but YMMV. Or reduce
  density...

The code
--------

The code base has evolved a lot over time and has multiple places
where it can use improvements, refactoring and rethought.

Main areas of improvement:

- the web server (Tornado) is hardwired to start N servers and
  requests bounce on them across targets; it'd be a good idea to have
  N be dynamic and even bound to a single target, as most usage models
  do sequential access on a target.

- the target acquisition mechanism is currently based on a very
  simplistic random poll mechanism, which puts a unnecesary strain on
  the network when there is a lot of contention. As well, there is no
  way to configure prioritization (a developer over Jenkins, for
  example). [tbdl.tt.targets_assign]

  This needs to be replaced with a simple queue and event mechanism
  that lets the client known when their request for assignment is
  completed and can start operating on the target. This will require
  changes in both server and client.

- the code that generates target groups for testcases / testgroup
  pairing needs to be broken up and extended to take more advantage of
  more possibilities (in the case of target groups with
  interconnects) [tcfl.tt._run_on_targets]

- it will make sense also to abstract the ttbd_client access layer
  into something that would allow other target servers to be used by
  the client to run testcases on, not just the ttbd server.
