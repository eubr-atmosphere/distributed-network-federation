"""
Copyright 2018 Andrea Marchini
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
     http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib.packet import ethernet
from ryu.lib.packet import arp
from ryu.lib.packet.packet import Packet
from ryu.lib.packet.ethernet import ethernet
from ryu.lib.packet.vlan import vlan
from ryu.lib.packet.arp import arp
from ryu.ofproto import ofproto_v1_3
import networkx as nx

IP_OFFSET = 100


class GatewayVM(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(GatewayVM, self).__init__(*args, **kwargs)
        # keeps datapaths indexed by datacenter ID
        self.devices = dict()
        # indexed by [vlan_id] and [ip address], value mac address
        self.arp_table = dict()
        # indexed by [vlan_id] and [mac_src], value datacenter ID
        self.mac_table = dict()
        # graph of the network: the nodes are the datacenters ID, the edges tare associated with the switch port numbers
        self.topo = nx.DiGraph()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto_parser = datapath.ofproto_parser
        remote_ip, remote_port = datapath.address
        print "New Switch connected! Dpid=", datapath.id, "Address=", remote_ip, "port=", remote_port
        dc_id = get_dc_from_dp(datapath)
        self.devices[dc_id] = datapath
        req = ofproto_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dc_id = get_dc_from_dp(datapath)
        self.topo.add_node(dc_id)
        for p in ev.msg.body:
            if p.name[0:3] == "gre":
                remote_dc_id = int(p.name[3:])
                self.topo.add_edge(dc_id, remote_dc_id, port=p.port_no)
            else:
                self.topo.add_edge(dc_id, dc_id, port=p.port_no)
        self.install_default_rules(datapath)

    def install_default_rules(self, datapath):
        dc_id = get_dc_from_dp(datapath)
        dc_port = self.topo[dc_id][dc_id]["port"]
        # match everything
        match_normal = datapath.ofproto_parser.OFPMatch()
        # match only packets coming from local datacenter port
        match = datapath.ofproto_parser.OFPMatch(in_port=dc_port)
        # match ARP packets coming from the local datacenter port
        match2 = datapath.ofproto_parser.OFPMatch(in_port=dc_port, eth_type=0x806)

        action_go2controller = [datapath.ofproto_parser.OFPActionOutput(
                datapath.ofproto.OFPP_CONTROLLER,
                datapath.ofproto.OFPCML_NO_BUFFER)]
        action_normal = [datapath.ofproto_parser.OFPActionOutput(
                datapath.ofproto.OFPP_NORMAL)]
        # process packet using the non-OF pipeline
        add_flow(datapath=datapath, priority=0, match=match_normal, actions=action_normal)
        # send packets from dc port to the controller
        add_flow(datapath=datapath, priority=1, match=match, actions=action_go2controller)
        # send ARP packets from dc port to the controller
        add_flow(datapath=datapath, priority=3, match=match2, actions=action_go2controller)

        # install default rules: all packets coming from GRE tunnels go to the local datacenter port
        action_go2dc = [datapath.ofproto_parser.OFPActionOutput(dc_port)]
        n_dc = len(self.topo.nodes())
        dc_list = [i for i in range(1, n_dc+1) if i != dc_id]
        for remote_dc_id in dc_list:
            match = datapath.ofproto_parser.OFPMatch(in_port=self.topo[dc_id][remote_dc_id]["port"])
            add_flow(datapath=datapath, priority=1, match=match, actions=action_go2dc)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        dc_id = get_dc_from_dp(datapath)
        pkt = Packet(msg.data)

        etherframe = pkt.get_protocol(ethernet)
        mac_src = etherframe.src
        mac_dst = etherframe.dst
        try:
            vlan_id = pkt.get_protocol(vlan).vid
        except:
            print "WARNING: not VLAN packet -> dropping this packet."
            return

        self.mac_table.setdefault(vlan_id, dict())
        self.arp_table.setdefault(vlan_id, dict())

        if mac_src not in self.mac_table[vlan_id] or \
                (mac_src in self.mac_table[vlan_id] and dc_id != self.mac_table[vlan_id][mac_src]):
            self.mac_table[vlan_id][mac_src] = dc_id
            print "Learned that host with mac_src", mac_src, "of VLAN", vlan_id, "is in DC", dc_id

        arp_pkt = pkt.get_protocol(arp)
        data = msg.data
        if arp_pkt:
            sender_ip = arp_pkt.src_ip
            sender_mac = arp_pkt.src_mac
            target_ip = arp_pkt.dst_ip
            self.arp_table[vlan_id][sender_ip] = sender_mac
            if arp_pkt.opcode == 1:
                if target_ip in self.arp_table[vlan_id]:
                    # ARP Request.
                    print "*PROXY ARP* - Received ARP request packet: creating reply..."
                    target_mac = self.arp_table[vlan_id][target_ip]
                    data = self.create_arp_reply(vlan_id, sender_ip, sender_mac, target_ip, target_mac)
                    mac_dst = mac_src
                else:
                    # If it not able to answer, it drops the packet.
                    return

            elif arp_pkt.opcode == 2:
                # ARP Reply.
                print "*PROXY ARP* - Received ARP reply packet: sniffing reply..."
                target_mac = arp_pkt.dst_mac
                self.arp_table[vlan_id][target_ip] = target_mac

        if mac_dst not in self.mac_table[vlan_id] or mac_dst == "ff:ff:ff:ff:ff:ff":
            print "Need to flood a packet with vlan id", vlan_id, "and mac_src / mac_dst", mac_src, "/", mac_dst
            n_dc = len(self.topo.nodes())
            dc_list = [i for i in range(1, n_dc+1) if i != dc_id]
            for remote_dc_id in dc_list:
                actions = [parser.OFPActionOutput(self.topo[dc_id][remote_dc_id]["port"])]
                out = datapath.ofproto_parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                    in_port=datapath.ofproto.OFPP_CONTROLLER,
                    actions=actions,
                    data=data)
                print "Flooding packet to datacenter", remote_dc_id
                datapath.send_msg(out)
        else:
            remote_dc_id = self.mac_table[vlan_id][mac_dst]
            path = nx.shortest_path(self.topo, dc_id, remote_dc_id)
            if dc_id != remote_dc_id:
                out_port = self.topo[path[0]][path[1]]["port"]
            else:
                if arp_pkt:
                    # ARP request case.
                    out_port = self.topo[dc_id][dc_id]["port"]
                else:
                    print "Dropping packet..."
                    return

            print "Direct forwarding packet with vlan id", vlan_id, "and mac_src", mac_src, ",mac_dst", \
                mac_dst, "out_port", out_port
            actions = [parser.OFPActionOutput(out_port)]
            out = datapath.ofproto_parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                in_port=datapath.ofproto.OFPP_CONTROLLER,
                actions=actions,
                data=data)
            datapath.send_msg(out)
            if not arp_pkt:
                print "Installing flow rules for connecting host with mac_src", mac_src, \
                    "to host with mac_dst", mac_dst, "of VLAN", vlan_id
                self.apply_routing(path=path, vlan_id=vlan_id, mac_src=mac_src, mac_dst=mac_dst, priority=2,
                                   idle_timeout=10)

    def create_arp_reply(self, vlan_id, sender_ip, sender_mac, target_ip, target_mac):
        # Create an ARP reply packet, tagged with the correct VLAN ID.
        e = ethernet(sender_mac, target_mac, 0x8100)
        v = vlan(vid=vlan_id, ethertype=0x806)
        a = arp(1, 0x0800, 6, 4, 2, target_mac, target_ip, sender_mac, sender_ip)
        p = Packet()
        p.add_protocol(e)
        p.add_protocol(v)
        p.add_protocol(a)
        p.serialize()
        return p.data

    def apply_routing(self, path, vlan_id, mac_src, mac_dst, priority=0, hard_timeout=0, idle_timeout=0):
        # Given a path, installs the flow rules for that path.
        path.insert(0, path[0])
        for previous_hop, hop, next_hop in list(zip(path, path[1:], path[2:])):
            dp = self.devices[hop]
            parser = dp.ofproto_parser
            add_flow(dp, 0, priority, parser.OFPMatch(vlan_vid=0x1000 | vlan_id,
                                                      eth_src=mac_src,
                                                      eth_dst=mac_dst,
                                                      in_port=self.topo[hop][previous_hop]['port']),
                     [parser.OFPActionOutput(self.topo[hop][next_hop]['port'])],
                     hard_timeout=hard_timeout, idle_timeout=idle_timeout)


def add_flow(datapath, table_id=0, priority=0, match=[], actions=[], inst2=None, hard_timeout=0, idle_timeout=0):
    # install an OF flow inside the switch.
    actions = filter(lambda x: x is not None, actions)
    if len(actions) > 0:
        inst = [datapath.ofproto_parser.OFPInstructionActions(datapath.ofproto.OFPIT_APPLY_ACTIONS, actions)]
    else:
        inst = []
    if inst2 is not None:
        inst += inst2
    mod = datapath.ofproto_parser.OFPFlowMod(datapath=datapath, table_id=table_id, priority=priority,
                                             match=match, instructions=inst, hard_timeout=hard_timeout,
                                             idle_timeout=idle_timeout)
    datapath.send_msg(mod)


def get_dc_from_dp(dp):
    # Extracts the last octect, which is the datacenter ID.
    return int(dp.address[0].split(".")[3]) - IP_OFFSET
