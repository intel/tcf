#! /usr/bin/python
import ttbl.config
import ttbl.power

target = ttbl.test_target('local_test')
ttbl.config.target_add(target)


pc = ttbl.power.fake_c()

target.interface_add(
    "power",
    ttbl.power.interface(
        ( "IOC/YK23406-2", pc ),
        ( "ADB/YK23406-3", pc ),
        ( "main/sp7/8", pc ),
        ( "wait /dev/tty-gp-64b-soc", pc ),
        ( "serial0_soc", pc ),
        ( "wait /dev/tty-gp-64b-ioc", pc ),
        ( "serial1_ioc", pc ),
    )
)
