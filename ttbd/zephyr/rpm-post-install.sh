#! /bin/sh
# Let members of group ttbd deal with this directory
# HACK I can't do this feeding it to setup.py, so...post instal :/
chgrp ttbd /etc/ttbd-production
chmod g+ws /etc/ttbd-production
