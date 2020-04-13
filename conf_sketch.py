#
# TCF configuration for using Arduino Sketch

import os
import tcfl.config

# Configuration for RPM package arduino
if os.path.isdir("/opt/arduino-1.6.13/"):
    tcfl.config.arduino_bindir = "/opt/arduino-1.6.13/"
    tcfl.config.arduino_libdir = "/opt/arduino-1.6.13/"
else:
    tcfl.config.arduino_bindir = None
    tcfl.config.arduino_libdir = None

# Site specific
tcfl.config.arduino_extra_libdir = os.path.expanduser("~/.arduino15/")
