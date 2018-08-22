#
# TCF: create known network configuration files for systemd
#
# tcf-live-extra-*.ks files are just imported verbatim by the
# kickstarter file
#
# One entry per physical host

# Example: for target name TARGET (which would be lowercase)

#cat <<EOF > /etc/systemd/network/TARGET.network
#[Match]
#MACAddress = b8:ae:ed:79:ca:9e
#
#[Network]
#DHCP = no
#Address = 192.168.254.101/24
#Address = fc00::fe:fe/112
#EOF
