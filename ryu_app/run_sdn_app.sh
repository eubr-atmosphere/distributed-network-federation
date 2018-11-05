#!/bin/bash

echo "Upgrading packages...."
sudo apt-get install python python-pip -y
pip install ryu --user

echo "Starting SDN app...."
ryu-manager gw_sdn_controller.py

