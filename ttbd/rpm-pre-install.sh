#! /bin/sh
if [ x$(stat --format %U /var/run/ttbd-production 2> /dev/null) != xttbd ]; then
    # If the database dirs are not owned by ttbd, wipe them, they will
    # be re-created with the new user by systemd
    rm -rf /var/run/ttbd-* /var/cache/ttbd-*
fi
# if the group ttbd doesn't exist already, create it
getent group ttbd || groupadd ttbd
# if the user ttbd doesn't exist, create it adding it to the group
id ttbd >& /dev/null || useradd -r -d /var/lib/ttbd -c "TCF TTBD Server" -M -g ttbd ttbd > /dev/null
