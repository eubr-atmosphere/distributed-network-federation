#!/bin/bash

#public IP address of the local gateway
gateway_ip=$1
#vlanID of the network federation
vlanID=$2
#the private address for the host in the federated network
host_fn_ip=$3
#Ip address of the host, able to reach the gateway
local_ip=$4

#get interface name given the local ip
if=$(ifconfig | grep -B1 $local_ip | grep -o "^\w*")
sudo ip link add tun$vlanID type gretap local $local_ip remote $gateway_ip key $vlanID dev $if
sudo ip addr add $host_fn_ip/24 dev tun$vlanID
sudo ip link set tun$vlanID up
