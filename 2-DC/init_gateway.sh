#!/bin/bash

atomix_version="3.0.8"
onos_version="1.14.1"
ovs_version="2.11"

ipsec_psk="atmosphere_psw"

function install_docker {
	sudo apt-get update
	sudo apt-get install apt-transport-https ca-certificates curl gnupg-agent software-properties-common -y
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
	sudo add-apt-repository \
	   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
	   $(lsb_release -cs) \
	   stable"
	sudo apt-get update
	sudo apt-get install docker-ce -y
}

function build_ovs {
	sudo apt-get install python git build-essential fakeroot dkms strongswan -y
	git clone https://github.com/openvswitch/ovs
	cd ovs
	git checkout origin/branch-$ovs_version
	sudo apt-get install $(python ../../utils/parse_ovs_deps.py) -y
	DEB_BUILD_OPTIONS='parallel=8 nocheck' fakeroot debian/rules binary
	cd ..
}

function install_ovs {
	sudo dpkg -i libopenvswitch_*.deb openvswitch-common_*.deb \
	openvswitch-switch_*.deb openvswitch-datapath-dkms_*.deb \
	python-openvswitch_*.deb openvswitch-pki_*.deb \
	openvswitch-ipsec_*.deb
}

function clean_containers {
	sudo docker kill $(sudo docker ps -q) >/dev/null
	sudo docker rm $(sudo docker ps -a -q) >/dev/null
}

function pull_onos_image {
	sudo docker pull onosproject/onos:$onos_version
}

function run_onos_container {
	folder="config"
	if [ ! -d $folder ]; then
		mkdir $folder
	fi
	python ../utils/onos-gen-config.py $local_node_ip $folder/cluster.json --nodes $nodes_ips
	containerID="$(sudo docker create -p 6653:6653 -p 9876:9876 -p 8181:8181 onosproject/onos:$onos_version)"
	sudo docker cp $folder $containerID:/root/onos/$folder
	sudo docker start $containerID
}

function clean_gateway_bridges {
	sudo ovs-vsctl --if-exists del-br br-dc
	sudo ovs-vsctl --if-exists del-br br-interdc
}

function interconnect_gateways {
	i=1
	for ip in $nodes_ips
		do
			if [[ $ip != $local_node_ip ]]; then
				sudo ovs-vsctl add-port br-interdc gre-DC$i -- set interface gre-DC$i type=gre \
				options:remote_ip=$ip options:psk=$ipsec_psk
				((i++))
			fi
		done
}

function configure_gateway {
	ONOS_IP=127.0.0.1
	sudo ovs-vsctl add-br br-dc
	sudo ovs-vsctl add-br br-interdc
	sudo ovs-vsctl set-controller br-interdc tcp:$ONOS_IP:6653

	sudo ovs-vsctl add-port br-dc patch-out 2>/dev/null
	sudo ovs-vsctl set interface patch-out type=patch
	sudo ovs-vsctl set interface patch-out options:peer=patch-in
	sudo ovs-vsctl add-port br-interdc patch-in 2>/dev/null
	sudo ovs-vsctl set interface patch-in type=patch
	sudo ovs-vsctl set interface patch-in options:peer=patch-out
}

function main {
	#onos app push!
	ubuntu_vers="$(lsb_release -r | awk '{print $2}')"
		if [[ $ubuntu_vers != "16.04" ]]; then
				echo "Distro must be Ubuntu 16.04"
				exit 1
		else
			echo "Distro: Ok!"
		fi

	ovs_vers="$(dpkg -s openvswitch-switch | grep -i version |  awk '{print $2}')"
	if [[ $ovs_vers != "2.11.0-1" ]]; then
		echo "OvS: Build phase..."
		build_ovs
		echo "OvS: Install phase..."
		install_ovs
	else
		echo "OVS: Installed!"
	fi

	if [[ -z "$(docker -v)" ]]; then
		echo "Docker: Install phase..."
		install_docker
	else
		echo "Docker: Installed!"
	fi

	if [[ -z "$(sudo docker images | grep onos)" ]]; then
		echo "ONOS: Pull image..."
		pull_onos_image
	else
		echo "ONOS: Already pulled!"
	fi

	echo "Docker: Cleaning all containers..."
	clean_containers

	echo "ONOS: Running container..."
	run_onos_container

	echo "Gateway: Cleaning bridges..."
	clean_gateway_bridges

	echo "Gateway: Starting configuration..."
	configure_gateway

	echo "Gateway: Starting interDC IPsec connection..."
	interconnect_gateways
}

local_node_ip=$1
nodes_ips="$*"
main
