#
# TCF: create known network configuration files for systemd
#
# tcf-live-extra-*.ks files are just imported verbatim by the
# kickstarter file
#
# One entry per physical host

# When a virtual host gets an NAT upstream connection, we configure it
# with MAC address 02:01:01:01:01:01

cat <<EOF > /etc/systemd/network/nat_host.network
[Match]
MACAddress = 02:01:01:01:01:01

[Network]
DHCP = yes
EOF
