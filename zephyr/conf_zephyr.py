#
# TCF configuration for Zephyr
#
# Adapt values as needed and place in ~/.tcf/
#

import os

# Zephyr TC driver registration moved for init performance reaosns to
# tcfl.tc.run(); will be moved to orchestrator specific config

# Set Zephyr's build environment (use .setdefault() to inherit existing values)
os.environ.setdefault('ZEPHYR_TOOLCHAIN_VARIANT', 'zephyr')

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


# Bitrotten code removed since the Zephyr code base has changed
# radically and they have not been maintained:
#
# - tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_tags
# - tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.patch_hw_requires
# - Definitions of data harversters from Sanity Checks
#
# See change after commit  on 6/25
#
# dbff386b: tcf/console-write: move to new UI CLI framework for consistency
