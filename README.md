# advanced-network-federation

## Introduction
This repository hosts the SDN controller apps that are responsible for managing the forwarding behaviour of the gateway software switches in the "advanced network federation" architecture.

## Ryu based SDN controller app:
This application is located inside the ryu_app folder. This application support only a single instance SDN controller.

## ONOS based SDN controller apps:
These applications are located inside the onos_app folder. These applications support a multi-instance SDN controller.
- fwd: this application performs a reactive forwarding. It was modified to be VLAN-aware.
- ifwd: this application performs a reactive forwarding, based on the ONOS intent framework. It was modified to be VLAN-aware.
