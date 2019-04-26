#
# TCF configuration for Zephyr
#
# Adapt values as needed and place in ~/.tcf/
#

import os
import tcfl.app
import tcfl.tc

import tcfl.app_zephyr
import tcfl.tc_zephyr_sanity

# Zephyr-specific drivers
tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)
tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
tcfl.tc.tc_c.driver_add(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c)

# Don't scan for test cases in doc directories
tcfl.tc.tc_c.dir_ignore_add_regex("^doc$")
tcfl.tc.tc_c.dir_ignore_add_regex("^outdir.*$")

# Set Zephyr's build environment (use .setdefault() to inherit existing values)
os.environ.setdefault('ZEPHYR_TOOLCHAIN_VARIANT', 'zephyr')
os.environ.setdefault('USE_CCACHE', "1")

#: SDK mapping table
#:
#: Each key must be an SDK variant that Zephyr supports for building
#: with (as exported to environment variable to the make process
#: ZEPHYR_TOOLCHAIN_VARIANT)..
#:
#: Each entry then contains a dictionary on which the platforms
#: architecture can be translated to an SDK known one with the *arch*
#: key, the calling convention can be set with the *call_conv*
#: key. Defaults can be set on the key *default*, which has to at
#: least define the *prefix* to prefix the program path with (eg,
#: given program *nm*, concatenating *prefix* *nm* gets us a path to
#: the program that we can call.
zephyr_sdks = {
    "zephyr": {
        "default": {
            "call_conv": "zephyr-elf",
            # zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux/usr/bin/riscv32-zephyr-elf/riscv32-zephyr-elf-gcc-nm
            "prefix": os.environ.get('ZEPHYR_SDK_INSTALL_DIR', 'ZEPHYR_SDK_NOT_INSTALLED') + \
                      "/sysroots/x86_64-pokysdk-linux" \
                      "/usr/bin/%(arch)s-%(call_conv)s" \
                      "/%(arch)s-%(call_conv)s-"
        },
        "x86" : { "arch": "i586" },
        "arm" : { "call_conv": "zephyr-eabi" },
    },
    "issm": {
        "default": {
        },
        "x86" : {
            "arch": "i586",
            "call_conv": "intel-elfiamcu",
            # ISSM-TOOLCHAIN-LINUX-2017-02-07/tools/compiler/gcc-ia/5.2.1/bin/i586-intel-elfiamcu-gcc-nm
            "prefix": os.environ.get('ISSM_INSTALLATION_PATH', 'ISSM_NOT_INSTALLED') + \
                      "/tools/compiler/gcc-ia/5.2.1" \
                      "/bin/%(arch)s-%(call_conv)s-"
        },
        "arc" : {
            "call_conv": "elf32",
            "prefix": os.environ.get('ISSM_INSTALLATION_PATH', 'ISSM_NOT_INSTALLED') + \
                      "/tools/compiler/gcc-arc/4.8.5" \
                      "/bin/%(arch)s-%(call_conv)s-"
        },
    },
    "espressif": {
        "default": {
        },
        "xtensa": {
            "arch": "xtensa",
            "call_conv": "esp32-elf",
            "prefix": os.environ.get('ESPRESSIF_TOOLCHAIN_PATH', 'ESPRESSIF_NOT_INSTALLED') + \
            "/bin/%(arch)s-%(call_conv)s-"
        },
    },

}

# Until Zephyr is patched, manually tag these test cases
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_tags = {

    # < v1.9
    "tests/kernel/stackprot/testcase.ini#test": [ 'ignore_faults' ],
    "tests/legacy/kernel/test_stackprot/microkernel/testcase.ini#test": [
        'ignore_faults'
    ],
    "tests/legacy/kernel/test_stackprot/nanokernel/testcase.ini#test": [
        'ignore_faults'
    ],
    "tests/legacy/kernel/test_static_idt/microkernel/testcase.ini#test": [
        'ignore_faults'
    ],
    "tests/legacy/kernel/test_static_idt/nanokernel/testcase.ini#test": [
        'ignore_faults'
    ],
    "tests/drivers/spi/spi_basic_api/testcase.ini#test_spi": {
        'hw_requires': 'fixture_spi_basic_0'
    },

    # >= v1.9
    "tests/kernel/stackprot/testcase.yaml#test": [ 'ignore_faults' ],
    "tests/drivers/spi/spi_basic_api/testcase.yaml#test_spi": {
        'hw_requires': 'fixture_spi_basic_0'
    },
}

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_hw_requires = {
    # < v1.9
    "tests/drivers/spi/spi_basic_api/testcase.ini#test_spi": [
        'fixture_spi_basic_0'
    ],
    # >= v1.9
    "tests/drivers/spi/spi_basic_api/testcase.yaml#test_spi": [
        'fixture_spi_basic_0'
    ],
    "tests/drivers/i2c/i2c_api/testcase.yaml#test_i2c_x86": [
        'fixture_i2c_gy271'
    ],
    "tests/drivers/i2c/i2c_api/testcase.yaml#test_i2c_arc": [
        'fixture_i2c_gy271'
    ],
    "tests/drivers/pinmux/pinmux_basic_api/testcase.yaml#test_pinmux": [
        'fixture_gpio_loop'
    ],
    "tests/drivers/gpio/gpio_basic_api/testcase.yaml#test_gpio": [
        'fixture_gpio_loop'
    ],
    "tests/drivers/i2c/i2c_api/testcase.yaml#test_i2c_arc": [
        'fixture_i2c_ss_gy271'
    ],
}



#
# Definitions of data harversters from Sanity Checks
#

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Boot Time (%(zephyr_board)s)", "start (microseconds)",
    r"__start\s+: [0-9]+ cycles, (?P<value>[0-9]+) us$")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Boot Time (%(zephyr_board)s)", "start->main() (microseconds)",
    r"_start->main\(\): [0-9]+ cycles, (?P<value>[0-9]+) us$")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Boot Time (%(zephyr_board)s)", "start->task (microseconds)",
    r"_start->task\s+: [0-9]+ cycles, (?P<value>[0-9]+) us$")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Boot Time (%(zephyr_board)s)", "start->idle (microseconds)",
    r"_start->idle\s+: [0-9]+ cycles, (?P<value>[0-9]+) us$")

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Semaphore #1 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Semaphore #1")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Semaphore #2 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Semaphore #2")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Semaphore #3 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Semaphore #3")

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "LIFO #1 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: LIFO #1")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "LIFO #2 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: LIFO #3")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "LIFO #3 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: LIFO #3")

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "FIFO #1 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: FIFO #1")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "FIFO #2 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: FIFO #3")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "FIFO #3 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: FIFO #3")

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Stack #1 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Stack #1")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Stack #2 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Stack #3")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    r"Sys Kernel (%(zephyr_board)s)", "Stack #3 (ns)",
    r"DETAILS: Average time for 1 iteration: (?P<value>[0-9]+) nSec",
    main_trigger_regex = "MODULE: kernel API test",
    trigger_regex = "TEST CASE: Stack #3")

for field in [
        'Context switch',
        'Heap Free',
        'Heap Malloc',
        'Interrupt latency',
        'MailBox asynchronous put',
        'MailBox get without context switch'
        'MailBox get without context switch',
        'MailBox synchronous get',
        'MailBox synchronous put',
        'Message Queue get with context switch',
        'Message Queue get without context switch',
        'Message Queue Put with context switch',
        'Message Queue Put without context switch',
        'Mutex lock',
        'Mutex unlock',
        'Semaphore Give with context switch',
        'Semaphore Give without context switch',
        'Semaphore Take with context switch',
        'Semaphore Take without context switch',
        'Thread abort',
        'Thread cancel',
        'Thread Creation',
        'Thread Resume',
        'Thread Sleep',
        'Thread Suspend',
        'Thread Yield',
        'Tick overhead',
]:
    tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
        "Timing info (%(zephyr_board)s - %(tc_name_short)s)",
        "%s (ns)" % field,
        r"%s\s+:\s*[0-9]+ cycles\s*,\s*(?P<value>[0-9]+) ns" % field,
        main_trigger_regex = \
            r"(starting test|tc_start\(\)) - Time Measurement")


tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "time to switch from ISR back to interrupted thread (ns)",
    "switching time is [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|",
    trigger_regex = "1 - Measure time to switch from ISR back to interrupted thread")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "time from ISR to executing a different thread (rescheduled) (ns)",
    "switch time is [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|",
    trigger_regex = r"2 - Measure time from ISR to executing a different thread \(rescheduled\)")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average semaphore signal time (ns)",
    "Average semaphore signal time [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average semaphore test time (ns)",
    "Average semaphore test time [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average time to lock a mutex (ns)",
    "Average time to lock the mutex [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average time to unlock a mutex (ns)",
    "Average time to unlock the mutex [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average thread context switch time using k_yield() (ns)",
    "Average thread context switch using yield [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "Latency Benchmark (%(zephyr_board)s)",
    "average cooperative context switch time between threads (ns)",
    "Average context switch time is [0-9]+ tcs = (?P<value>[0-9]+) nsec",
    main_trigger_regex = r"|\s+Latency Benchmark\s+|")

for app_field in [
        'enqueue 1 byte msg in FIFO',
        'dequeue 1 byte msg in FIFO',
        'enqueue 4 bytes msg in FIFO',
        'dequeue 4 bytes msg in FIFO',
        'enqueue 1 byte msg in FIFO to a waiting higher priority task',
        'enqueue 4 bytes in FIFO to a waiting higher priority task',
        'signal semaphore',
        'signal to waiting high pri task',
        'signal to waiting high pri task, with timeout',
        'average lock and unlock mutex',
        'average alloc and dealloc memory page',
        'average alloc and dealloc memory pool block',
        'Signal enabled event',
        'Signal event & Test event',
        'Signal event & TestW event'
]:
    tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
        "App Kernel (%(zephyr_board)s)",
        "%s (ns)" % app_field,
        r"\| %s\s+\|\s+(?P<value>[0-9]+)\|" % app_field,
        main_trigger_regex = r"|\s+S I M P L E   S E R V I C E    " \
            r"M E A S U R E M E N T S\s+|\s+nsec\s+|")

tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "App Kernel (%(zephyr_board)s)",
    "message overhead (ns/packet)",
    r"\| message overhead:\s+(?P<value>[0-9]+)\s+nsec/packet\s+\|",
    main_trigger_regex = r"|\s+M A I L B O X   M E A S U R E M E N T S\s+|")
tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.data_harvest(
    "App Kernel (%(zephyr_board)s)",
    "raw transfer rate (KB/sec)",
    r"\| raw transfer rate:\s+(?P<value>[0-9]+) KB/sec \(without overhead\)\s+\|",
    main_trigger_regex = r"|\s+M A I L B O X   M E A S U R E M E N T S\s+|")


# EXPERIMENT: force the max10 to delay 3 seconds boot, as we are
# seeing too much lost early console output -- note this could be too
# a problem in the HW setup, with this we are trying isolate possible
# causes.
tcfl.app_zephyr.boot_delay['max10'] = 3000
