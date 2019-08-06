#!/bin/bash

atomix_version="3.0.8"

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

function clean_containers {
	sudo docker kill $(sudo docker ps -q) >/dev/null
	sudo docker rm $(sudo docker ps -a -q) >/dev/null
}

function pull_atomix_image {
	sudo docker pull atomix/atomix:$atomix_version
}

function run_atomix_container {
	folder="atomix_config"
	config_fn="atomix_cluster.conf"
	path="/opt/atomix/conf"
	if [ ! -d $folder ]; then
		mkdir $folder
	fi
	python ../utils/atomix-gen-config.py $local_node_ip $folder/$config_fn $nodes_ips
  containerID="$(sudo docker create -p 5679:5679 atomix/atomix:$atomix_version -c $path/$config_fn)"
	sudo docker cp $folder/$config_fn $containerID:$path/$config_fn
	sudo docker start $containerID
}

function main {

	if [[ -z "$(docker -v)" ]]; then
		echo "Docker: Install phase..."
		install_docker
	else
		echo "Docker: Installed!"
	fi

	if [[ -z "$(sudo docker images | grep atomix)" ]]; then
		echo "Atomix: Pull image..."
		pull_atomix_image
	else
		echo "Atomix: Already pulled!"
	fi

	echo "Docker: Cleaning all containers..."
	clean_containers

	echo "Atomix: Running container..."
	run_atomix_container
}

local_node_ip=$1
nodes_ips="$*"
main
