#!/bin/bash

ipsec_psk="atmosphere_psw"
prefix="gre-DC"

i=$(sudo python ../utils/get_progressive_index.py $prefix)
for ip in $*
	do
			sudo ovs-vsctl add-port br-interdc $prefix$i -- set interface $prefix$i type=gre \
			options:remote_ip=$ip options:psk=$ipsec_psk
			((i++))
	done
