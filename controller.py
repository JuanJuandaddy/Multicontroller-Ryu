import time
from subprocess import Popen
import socket
import json
import re
import networkx as nx
import sys
import numpy as np
from kazoo.client import KazooClient
from ConRec import ConRec
from ConSend import ConSend
import Logger
import StreamInfo
import settings


from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.topology.api import get_all_switch, get_link, get_switch
from ryu.base.app_manager import lookup_service_brick
from ryu.ofproto import ether
from ryu.topology import api as topo_api
from ryu.lib.packet import ipv4
from ryu.lib.packet import arp
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.stringify import StringifyMixin
from ryu.topology.switches import Switches
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER,CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3 as ofp_version
from ryu.lib.packet import *
from ryu.topology import api
from ryu.lib import hub
from ryu.topology.switches import LLDPPacket
""
    说明：
    程序在启动n个周期后进入信息获取状态，开始正常处理消息
    发送消息给Server时，使用json格式化消息必须带上msg_type字段
    在网络初始化时，会将网络中的所有主机的arp包进行记录，并且获取到所有边界交换机，即所有与其他外域
    所连接的交换机，初始化之后在进行跨域请求
"""

"""
    OpenFlow版本  ===> 1.5
"""
VERSION=1.3

"""
    服务器初始化参数
"""
QUEUE_LEN=settings.QUEUE_LEN  #队列长度

PORT=settings.PORT       #端口号

IP=settings.IP  #服务器IP

"""
    轮询周期
"""
ECHO=settings.ECHO #单位秒

ECHO_DELAY=settings.ECHO_DELAY #几个周期后开始request

ID_ROLE_MAP=settings.ID_ROLE_MAP #交换机角色表

UNKNOWN_MAC=settings.UNKNOWN_MAC

SW_MAC_LIST=settings.get_mac() #{"s1":xx:xx:xx:xx:xx....} 返回值为一个列表，值为sw的mac地址

class Controller(app_manager.RyuApp):
    OFP_VERSIONS = [ofp_version.OFP_VERSION]
    _CONTEXTS={
        #"Init_Switches":Switches_For_Each_Controller.Init_Switches,
        "Logger":Logger.Logger,
        "Info":StreamInfo.InfoProcess
    }
    def __init__(self, *args, **kwargs):
        super(Controller, self).__init__(*args, **kwargs)
        # =========================本域========================

        self.logger=kwargs["Logger"]
        self.log=kwargs["Info"]
        #=====服务器初始类=====
        self.HandleRecMsg=None #处理服务器消息句柄
        self.HandleSendMsg=None#发送给服务器的消息句柄
        self.status = False
        self.controller_id = None #控制器ID代表子网号
        self.queue = hub.Queue(QUEUE_LEN)#消息队列长度最大为16，因为客户端最大消息长度为32，有两台控制器，所以长度为32/2=16
        self.socket = socket.socket()
        self.start_server(IP, PORT)#连接server
        #=====控制器基类=====
        #self.Init_Switches=[int(num) for num in iter(re.findall(re.compile(r'\d'),kwargs["Init_Switches"].run()))] #初始的Master交换机
        self.Master_dpid={}#{dpid:datapath}
        #self.Slave_dpid={}#{dpid:datapath}
        # =====TOPO基类=====
        self.topology_api_app = self
        self.mac_list={}#本域IP {IP:MAC}
        self.link_to_port = {}  # (src_dpid,dst_dpid)->(src_port,dst_port) 端口的连接情况
        self.access_table = {}  # {(sw,port) : {area_id:xx,ip:host_ip} 边缘交换机的端口IP
        self.switch_port_table = {}  # {dpip : port_num} 交换机所拥有的端口表
        self.access_ports = {}  # {dpid : port_num}  连接主机的ovs的端口表
        self.interior_ports = {}  # {dpid : port_num} 交换机间的端口表
        self.dps = {}  # {dpid : datapath}
        self.switches = None
        # =====PATH基类=====
        self.route_table = {}  # {(ip_src,ip_dst):[path]}
        # =====Networkx基类=====
        self.graph=nx.DiGraph()   #每个控制器都拥有一个本地的全局拓扑，只有master才能被检测到，采用拓扑隔离
        # =====轮询类=====
        self.monitor_spawn()

        # =========================外域========================
        self.FLOOD_IP={}  #未知IP，存储未知的目的IP，即发往其他域的IP，结构为{IP:False}。所有的IP都要经过校验是否被泛洪过，如果是则为True，否则为False
                            #当为True时，如果该IP再次触发泛洪说明IP不在本域内，交由Server处理。
        self.f_mac_list={} #外域IP {IP：MAC}

        # =========================边界========================
        self.edge_sw={}#表示本域的边界交换机，结构为{(dpid,port):vlan_id}，表示dpid的port端口，连接着vlan_id的域
    # ===================================服务器初始类======================================
    def start_server(self, server_addr, server_port):
        """
        :param server_addr: 服务器地址
        :param server_port: 服务器端口
        """
        name=sys._getframe ().f_code.co_name
        try:
            controller=self

            self.log.info("socket:{} {}".format(server_addr,server_port))
            self.socket.connect((server_addr, server_port))#初始化连接
            self.status = True

            self.HandleRecMsg=ConRec(self.socket,controller)#初始化收消息句柄
            self.HandleSendMsg = ConSend(self.socket,controller)#初始化发消息的句柄


            self.start_spawn(self.HandleRecMsg.rec_loop,self.HandleSendMsg.send_loop)#开启携程
        except Exception as e:
            self.log.error("服务器未开启，取消连接中..... 请先开启服务器！！！")
            Popen("killall ryu-manager",shell=True)

    @staticmethod
    def start_spawn(r,s):
        """
        :param r: 携程1
        :param s: 携程2
        """
        hub.spawn(r)
        hub.spawn(s)
    # ===================================轮询======================================
    def monitor_spawn(self):
        name = sys._getframe().f_code.co_name

        self.log.warning(f'After {6*ECHO}\'s ,Start RequestInfoBase.......')


        hub.spawn(self._discover)

    def _discover(self):
        first=True
        while True:
            if first:
                hub.sleep(ECHO_DELAY*ECHO)
                first=False
            else:
                '''for datapath in self.dps.values():
                    self.request_stats(datapath)'''
                self.get_topology()
                hub.sleep(ECHO)

    @staticmethod
    def request_stats(datapath):
        """
            Sending request msg to datapath
        """
        '''ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)'''
        pass
    # ===================================TOPO获取类======================================
    def get_topology(self):
        """
        :return:拓扑信息
        """
        switch_list = get_all_switch(self)

        self.create_port_map(switch_list)

        self.switches = self.switch_port_table.keys()

        links = get_link(self.topology_api_app, None)

        self.create_interior_links(links)

        self.create_access_ports()

        self.get_graph()

    def get_host_location(self, host_ip):
        """
        :param host_ip: IP地址
        :return: 获取IP主机所连的ovs的ID以及端口
        """
        for key in self.access_table.keys():
            if self.access_table[key]["ip"] == host_ip:
                return key
        return None

    def get_switches(self):
        """
        :return: 返回拓扑中所有的交换机
        """
        return self.switches

    def get_sw(self, dpid, in_port, src, dst):
        """
        :param dpid: ovs的ID
        :param in_port: 消息的入端口
        :param src: 源IP
        :param dst: 目的IP
        :return: 返回源dpid到目的dpid，以及目的IP与目的ovs的连接端口
        """
        src_sw = dpid
        dst_sw = None
        dst_port = None

        src_location = self.get_host_location(src)  # 源交换机的id

        if in_port in self.access_ports[dpid]:
            if (dpid, in_port) == src_location:
                src_sw = src_location[0]
            else:
                return None


        dst_location = self.get_host_location(dst)  # 目的主机所连接的交换机的id，返回的是（dpid，in_port)

        if dst_location:
            dst_sw = dst_location[0]
            dst_port = dst_location[1]

        return src_sw, dst_sw, dst_port

    def get_links(self):
        return self.link_to_port

    def get_datapath(self, dpid):
        """
        :param dpid: ovs的ID
        :return: 返回dpid的实例对象
        """
        if dpid not in self.dps:
            switch = topo_api.get_switch(self, dpid)[0]
            self.dps[dpid] = switch.dp
            return switch.dp

        return self.dps[dpid]

    def create_port_map(self, switch_list):
        """
        :param switch_list: ovs集合
        :return: 创建一个端口映射表
        """
        for sw in switch_list:
            dpid = sw.dp.id
            self.graph.add_node(dpid)
            self.dps[dpid] = sw.dp

            self.switch_port_table.setdefault(dpid, set())
            self.interior_ports.setdefault(dpid, set())
            self.access_ports.setdefault(dpid, set())

            for p in sw.ports:
                self.switch_port_table[dpid].add(p.port_no)  # {dpid:(port_no:1.2.3.4.5)}

    def create_interior_links(self, link_list):
        """
        :param link_list: 链路的连接列表
        :return: 返回ovs之间的链路连接关系
        """
        for link in link_list:
            src = link.src
            dst = link.dst

            self.link_to_port[
                (src.dpid, dst.dpid)] = (src.port_no, dst.port_no)  # 1->2交换机的连接端口为：3->4

            if link.src.dpid in self.switches:
                self.interior_ports[link.src.dpid].add(link.src.port_no)

            if link.dst.dpid in self.switches:
                self.interior_ports[link.dst.dpid].add(link.dst.port_no)

    def create_access_ports(self):
        """
        :return: 创建主机与ovs之间的连接关系
        """
        for sw in self.switch_port_table:

            all_port_table = self.switch_port_table[sw]
            interior_port = self.interior_ports[sw]

            self.access_ports[sw] = all_port_table - interior_port  # 全部端口减去交换机互连端口得到主机端口

    def get_graph(self):
        """
        :return: 返回一张拓扑图，并用networkx画
        """
        name = sys._getframe().f_code.co_name
        link_list = topo_api.get_all_link(self)
        for link in link_list:
            src_dpid = link.src.dpid
            dst_dpid = link.dst.dpid
            src_port = link.src.port_no
            dst_port = link.dst.port_no

            self.graph.add_edge(src_dpid, dst_dpid,
                                src_port=src_port,
                                dst_port=dst_port,
                                )

            msg = json.dumps({
                "msg_type": "get_topo",
                "topo_type": "link_list",
                "data": {
                        "src_dpid":link.src.dpid,
                        "dst_dpid":link.dst.dpid,
                        "src_port":link.src.port_no,
                        "dst_port":link.dst.port_no
                        }
            })
            self.HandleSendMsg.send_to_queue(msg)

        return self.graph

    # ===================================主机、ovs信息注册类======================================
    def register_access_info(self, dpid, in_port, ip=None,area_id=None):
        """
        :param dpid: ovs的ID
        :param in_port: 消息进入的端口
        :param ip: IP地址
        :param area_id: 域ID
        :return: 完成本地与Server注册接入层的信息
        """

        key=(dpid,in_port)
        def send_reg():
            msg = json.dumps({
                "msg_type": "register_acc_info",
                "data": {
                    "dpid": dpid,
                    "in_port": in_port,
                    "ip": ip,
                    "area_id":area_id
                }
            })
            self.log.info(f'Table:{self.access_table}')
            self.HandleSendMsg.send_to_queue(msg)

        #校验ARP的源地址是否存在，ARP表的areaID变化只能由Server更改，无法通过ARP请求更改，
        # 控制器只能维护本地access_table，无法更改，但可初始化


        if in_port in self.access_ports[dpid]:
            if key in self.access_table:
                if self.access_table[key]["ip"] == ip and self.access_table[key]["area_id"]==area_id:
                    #如果该IP与域ID已经注册过，直接结束
                    return
                else:

                    #如果IP或者域ID发生变化，更新
                    self.access_table[key]["ip"] = ip
                    self.access_table[key]["area_id"] = area_id

                    send_reg()
                    return
            else:
                #如果未注册过，进行注册
                self.access_table.setdefault(key,{})

                self.access_table[key]["ip"] = ip
                self.access_table[key]["area_id"] = area_id

                send_reg()
                return

    def register_host_mac(self,ip,mac):
        if ip not in self.mac_list:
            self.mac_list[ip]=mac

            msg = json.dumps({
                "msg_type": "register_host_mac",
                "data": {
                    "ip": ip,
                    "mac": mac
                }
            })
            self.HandleSendMsg.send_to_queue(msg)

    def register_f_host_mac(self,ip,mac):
        if ip not in self.f_mac_list:
            self.f_mac_list[ip]=mac

            msg = json.dumps({
                "msg_type": "register_arp_table",
                "data": {
                    "ip": ip,
                    "mac": mac
                }
            })
            self.HandleSendMsg.send_to_queue(msg)

    def register_edge_sw(self,dpid,port,area_id):
        #注册边界交换机
        if (dpid,port) not in self.edge_sw:
            self.edge_sw[(dpid,port)]=area_id

        msg=json.dumps({
            "msg_type":"register_edge_sw",
            "data":{
                "dpid":dpid,
                "port":port,
                "area_id":area_id
            }
        })
        self.HandleSendMsg.send_to_queue(msg)
    # ===================================ARP处理类======================================
    def arp_forwarding(self, msg, dst_ip,result):
        #寻找目的IP，如果找不到，则泛洪
        if result:
            #找到目的IP，下发给目的ovs的packetout消息
            datapath_dst, out_port = result[0], result[1]
            datapath = self.dps[datapath_dst]
            self.send_packet_out(datapath, datapath.ofproto.OFP_NO_BUFFER,
                                        datapath.ofproto.OFPP_CONTROLLER,
                                        out_port, msg.data)

        else:
            # 开始泛洪
            self.flood_all(msg.data)

            #记录泛洪IP
            self.FLOOD_IP[dst_ip]=True

    def arp_process(self,Arp_pkt,dpid,in_port,msg):
        result = self.get_host_location(Arp_pkt.dst_ip)
        # 注册完毕arp包后,进入arp转发流程
        if (dpid, in_port) not in self.edge_sw.keys():

            if Arp_pkt.dst_mac != UNKNOWN_MAC:  # 不等于00::00
                if result:
                    # 如果地址对MAC构建完毕，如果目的IP在本地，正常进行本area的packetout下发
                    self.arp_forwarding(msg, Arp_pkt.dst_ip, result)
                else:
                    msg_proxy = json.dumps({
                        "msg_type": "packet_out",
                        "data": {
                            "dst_ip": Arp_pkt.dst_ip,
                            "msg_data": self.bytes_to_hexstr(msg.data)
                        }
                    })
                    self.HandleSendMsg.send_to_queue(msg_proxy)
            self.arp_forwarding(msg, Arp_pkt.dst_ip, result)

        else:
            self.arp_cross_ip(msg, dpid, in_port, Arp_pkt.src_ip, Arp_pkt.dst_ip)

    def arp_register(self,Arp_pkt,dpid,in_port):
        # 获取ARP注册的源地址
        # 判断当前arp消息是否被注册过，如果在本地的table中，那么直接取出来即可
        # 如果不在，那么判断当前请求地址的子网ID，并初始话本地table
        # 当不存在交换机迁移，那么src一定是本地子网ID，那么本地table存储的一定是本地的接入表
        # 当存在交换机迁移，服务器通过修改本地的table，将迁移的交换机所连主机的IP更改映射，改为迁入area的ID
        # 故当迁移过后的主机发送ARP请求，则会将其视为本地area的主机
        if (dpid, in_port) not in self.access_table:
            # 如果该arp未注册或arp过期，当接收到ARP请求，会将IP的子网ID划分到所属area
            arp_src_ip, area_id = Arp_pkt.src_ip, Arp_pkt.src_ip.split('.')[2]

            arp_src_mac = Arp_pkt.src_mac
        else:
            # 如果已经注册过，那么会直接取出areaID
            arp_src_ip, area_id = Arp_pkt.src_ip, self.access_table[(dpid, in_port)]["area_id"]

            arp_src_mac = Arp_pkt.src_mac

        # 判断源地址的子网是否为当前area
        if str(self.controller_id - 1) == area_id:

            # 如果是当前子网，那么进行注册ip:mac
            self.register_host_mac(arp_src_ip, arp_src_mac)

            # 注册(dpid:inport):ip
            self.log.info(f'注册本域:域ID=={area_id} 发起ovs：{dpid} in_port:{in_port} 注册IP：{arp_src_ip}')

            self.register_access_info(dpid=dpid, in_port=in_port, ip=arp_src_ip, area_id=area_id)
        else:
            # 如果不是当前子网的IP发生了ARP注册，说明是其他域发生的，则不发送packetout，不发送arp
            # 同时注册外域mac，并且注册边界交换机，不注册本地的access_table
            self.register_f_host_mac(arp_src_ip, arp_src_mac)

            # 注册边界交换机
            self.register_edge_sw(dpid, in_port, area_id)
    # ===================================交换机注册、角色控制类======================================
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features_handler(self, ev):
        """
        :param ev: 交换机上线事件
        """
        name = sys._getframe().f_code.co_name
        msg = ev.msg
        datapath = msg.datapath
        dpid = int(datapath.id)
        self.dps[dpid]=datapath
        self.log.info("switch {} connect to controller".format(dpid))

        #注册交换机
        self.sw_register(dpid)

        #安装默认table-miss
        self.install_table_miss(datapath)

        #安装IPV6忽视
        self.ignore_ipv6(datapath)

    def sw_register(self,dpid):
        #确认每个ovs所连接的控制器的所属角色

        msg=json.dumps({
            "msg_type":"sw_register",
            "dpid":dpid,
            "master_controller":self.controller_id
        })
        self.Master_dpid[dpid]=self.dps[dpid]
        self.HandleSendMsg.send_to_queue(msg)

        self.switch_role_request(dpid,"master")

    def switch_role_request(self,dpid,role):
        """

        :param dpid: ovs的ID
        :param role: 请求的角色
        :return:
        """
        datapath=self.dps[dpid]
        ofproto=datapath.ofproto
        parser=datapath.ofproto_parser

        if role=="master":
            req=parser.OFPRoleRequest(datapath,ofproto.OFPCR_ROLE_MASTER,0)

        elif role=="slave":
            req = parser.OFPRoleRequest(datapath, ofproto.OFPCR_ROLE_SLAVE, 0)

        elif role=="equal":
            req = parser.OFPRoleRequest(datapath, ofproto.OFPCR_ROLE_EQUAL, 0)

        elif role=="nochange":
            req = parser.OFPRoleRequest(datapath, ofproto.OFPCR_ROLE_NOCHANGE, 0)

        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPRoleReply,[MAIN_DISPATCHER,CONFIG_DISPATCHER])
    def _switch_role_reply_handler(self,ev):
        """
        OFPCR_ROLE_NOCHANGE = 0, /* Don’t change current role. */
        OFPCR_ROLE_EQUAL = 1, /* Default role, full access. */
        OFPCR_ROLE_MASTER = 2, /* Full access, at most one master. */
        OFPCR_ROLE_SLAVE = 3, /* Read-only access. */
        """
        name = sys._getframe().f_code.co_name
        self.log.info(f'dpid:{ev.msg.datapath.id},role:{ID_ROLE_MAP[int(ev.msg.role)]}')
    # ===================================Packet_in类======================================
    @set_ev_cls(ofp_event.EventOFPPacketIn,MAIN_DISPATCHER)
    def _packet_in_handler(self,ev):
        """
        网络发现阶段，边界ovs会触发大量的LLDP报文，但是不需要理会。
        并且收到跨域请求时，会触发源ovs的ARP报文

        msg的编码为utf-16
        code='utf-16'
        self.log.info(f'type:{type(msg.data)} msg.data:{msg.data}')
        self.log.info(f'type:{type(msg.data.hex())} hex msg.data:{msg.data.hex()}')
        self.log.info(f'type:{type(bytes.fromhex(msg.data.hex()))} msg.data:{bytes.fromhex(msg.data.hex())}')
        [INFO]type:<class 'bytes'> msg.data:b'\xff\xff\xff\xff\xff\xff\xc2\xdcZ\xc2\x91\x9f\x08\x06\x00\x01\x08\x00\x06\x04\x00\x01\xc2\xdcZ\xc2\x91\x9f\xc0\xa8\x00\x01\x00\x00\x00\x00\x00\x00\xc0\xa8\x01\x01'
        [INFO]type:<class 'str'> hex msg.data:ffffffffffffc2dc5ac2919f08060001080006040001c2dc5ac2919fc0a80001000000000000c0a80101
        [INFO]type:<class 'bytes'> msg.data:b'\xff\xff\xff\xff\xff\xff\xc2\xdcZ\xc2\x91\x9f\x08\x06\x00\x01\x08\x00\x06\x04\x00\x01\xc2\xdcZ\xc2\x91\x9f\xc0\xa8\x00\x01\x00\x00\x00\x00\x00\x00\xc0\xa8\x01\x01'
        msg消息不失真
        """
        name = sys._getframe().f_code.co_name
        msg=ev.msg
        datapath=msg.datapath
        dpid=datapath.id
        in_port=msg.match['in_port']

        pkt=packet.Packet(msg.data)
        Eth_type=pkt.get_protocols(ethernet.ethernet)[0].ethertype
        Eth_pkt=pkt.get_protocol(ethernet.ethernet)#以太网包
        Arp_pkt=pkt.get_protocol(arp.arp)#Arp包
        Ip_pkt=pkt.get_protocol(ipv4.ipv4)#IP包

        if Ip_pkt:
            src_ipv4 ,area_id= Ip_pkt.src,Ip_pkt.src.split('.')[2]
            if src_ipv4 == '0.0.0.0' and src_ipv4 == '255.255.255.255':
                pass

        if Arp_pkt:

            self.arp_register(Arp_pkt,dpid,in_port)

        if isinstance(Arp_pkt, arp.arp):

            self.arp_process(Arp_pkt,dpid,in_port,msg)


        if isinstance(Ip_pkt, ipv4.ipv4):
            #本地域转请求
            if len(pkt.get_protocols(ethernet.ethernet)):
                #self.log.info(f'IP转发{Ip_pkt.src} {Ip_pkt.dst}')
                self.shortest_forwarding(msg,Ip_pkt.src, Ip_pkt.dst)

        if Eth_type == ether_types.ETH_TYPE_LLDP:
            return
    # ===================================Path类======================================
    def shortest_forwarding(self,msg,ip_src,ip_dst):
        """
        只有域内请求，才会触发该方法
        :param msg: 触发packet_in的消息体
        :param ip_src: 源IP
        :param ip_dst: 目的IP
        :return:
        """
        #name = sys._getframe().f_code.co_name
        datapath = msg.datapath
        in_port = msg.match['in_port']
        result = self.get_sw(datapath.id, in_port, ip_src, ip_dst)
        if result:
            src_sw, dst_sw, to_dst_port = result[0], result[1], result[2]

            # to_dst_port指的是目的主机与交换机连接的端口,返回源dpid，目的dpid以及目的dpid到ip_dst出端口
            if dst_sw:#如果目的主机存在本area

                self.install_sw_to_host_flowmod(ether.ETH_TYPE_IP,dst_sw,ip_dst,to_dst_port)

                port_no = self.find_shortest_path(ip_src, ip_dst, src_sw, dst_sw)

                self.send_packet_out(datapath, msg.buffer_id, in_port, port_no, msg.data)
            else: #如果本地area不存在该目的IP，请求Server
                self.log.info(f'IP:{ip_src}=>{ip_dst}外部area 请求Server')

                self.server_path(ip_src, ip_dst, src_sw, dst_sw,msg)

    def find_shortest_path(self,ip_src,ip_dst,src_dpid,dst_dpid):
        """
        如果目的DPID存在于本控制器的控制域，那么不需要请求Server
        :param ip_src: 源IP
        :param ip_dst: 目的IP
        :param src_dpid: 源DPID
        :param dst_dpid: 目的DPID
        :return: 返回源DPID到第二跳的输出端口，供packet_out使用
        """
        return self.local_path(ip_src,ip_dst,src_dpid,dst_dpid)

    def server_path(self,ip_src,ip_dst,src_dpid,dst_dpid,msg):
        """
        {(ip_src,ip_dst):[path]} 路由表结构
        跨域请求，当dst_dpid不属于本地控制域时，则请求Server进行路径计算
        """
        cross_require=json.dumps({
            "msg_type":"shortest_path",
            "data":{
                "ip_src":ip_src,
                "ip_dst":ip_dst,
                "src_dpid": src_dpid,
                "dst_dpid": dst_dpid,
                "msg_data":self.bytes_to_hexstr(msg.data),
                "buffer_id":msg.buffer_id
            }
        })
        self.HandleSendMsg.send_to_queue(cross_require)

    def local_path(self,ip_src,ip_dst,src_dpid,dst_dpid):
        """
        {(ip_src,ip_dst):[path]} 路由表结构
        本地域请求，当本地控制器内存已存储路径消息，直接获取，当未存储路径消息，利用networkx计算
        """
        pair=(ip_src,ip_dst)
        if pair in self.route_table.keys():

            #存在路由表信息
            path=self.route_table[pair]
            self.install_interior_sw_flowmod(pair, path)
            port_no=self.graph[path[0]][path[1]]['src_port']

            return port_no
        else:

            #不存在路由表信息
            path=nx.shortest_path(self.graph,src_dpid,dst_dpid)
            while path[0]!=src_dpid:
                path=nx.shortest_path(self.graph,src_dpid,dst_dpid)
                if path[0]==src_dpid:
                    break
            self.route_table[pair]=path#加入本地路由表
            self.install_interior_sw_flowmod(pair,path)
            port_no=self.graph[path[0]][path[1]]['src_port']

            return port_no
    # ===================================Flow-Table类======================================
    def install_interior_sw_flowmod(self,pair,path):
        """
        :param pair: IP地址对
        :param path: IP地址对的路径
        :return:
        """
        ip_src,ip_dst=pair[0],pair[1]
        for index,dpid in enumerate(path[:-1]):
            out_port=self.graph[path[index]][path[index+1]]['src_port']
            datapath=self.get_datapath(dpid)
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match= parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ipv4_src=ip_src,ipv4_dst=ip_dst)
            actions=[parser.OFPActionOutput(out_port)]
            self.add_flow(dp=datapath,p=30,match=match,actions=actions,idle_timeout=20,hard_timeout=60)

    def install_sw_to_host_flowmod(self,type,dpid,ip,port):
        """
        不考虑双向，因为ping包属于ICMP包类型，会有回文包，会让src_dpid变成dst_dpid，故此时不需要安装src_dpid的flowmod
        :param type:匹配的包类型，一般为IPv4包
        :param dpid:目的地址的dpid
        :param ip:目的IP
        :param port:目的dpid到目的IP的出端口
        :return:
        """
        datapath=self.get_datapath(dpid)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match=parser.OFPMatch(eth_type=type,ipv4_dst=ip)
        actions=[parser.OFPActionOutput(port)]
        self.add_flow(dp=datapath, p=50, match=match, actions=actions, idle_timeout=0,hard_timeout=0)  # 接入层流表不过期
    # ===================================外域类======================================
    @staticmethod
    def bytes_to_hexstr(data):
        """
        :param data: 十六进制字节
        :return: 将字节型转为十六进制字符串型,方便json传输
        """
        return data.hex()

    def arp_cross_ip(self,body,dpid,in_port,src_ip,dst_ip):
        """假设迁移后192.168.1.1与192.168.1.2跑到area0，当前areaID为1，则直接通过判断src与dst的vlanid是不合适的
        如果是其他area内部IP转发，但是通过flood到边界交换机，那么不需要进行处理
        故在控制器判断是容易出错的，故需要交由Server处理"""
        msg=json.dumps({
            "msg_type":"arp_cross_ip",
            "data":{
                "dpid":dpid,
                "in_port":in_port,
                "src_ip":src_ip,
                "dst_ip":dst_ip,
                "msg_data":self.bytes_to_hexstr(body.data)
            }
        })
        self.HandleSendMsg.send_to_queue(msg)
    # ===================================add_flow======================================
    @staticmethod
    def add_flow(dp, p, match, actions, idle_timeout, hard_timeout):
        """
        :param dp: datapath实例
        :param p: 优先级
        :param match: 匹配规则
        :param actions: 动作集合
        :param idle_timeout: 空闲超时
        :param hard_timeout: 绝对超时
        :return: 添加流表
        """
        ofproto = dp.ofproto
        parser = dp.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=p,
                                idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout,
                                match=match, instructions=inst)
        dp.send_msg(mod)
    # ===================================table_miss======================================
    def install_table_miss(self,datapath):
        """
        :param datapath: 交换机实例对象
        :return: 安装table-miss表项
        """
        ofproto=datapath.ofproto
        parser=datapath.ofproto_parser
        match=parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp=datapath, p=0, match=match, actions=actions, idle_timeout=0, hard_timeout=0)
    # ===================================ignore_ipv6======================================
    def ignore_ipv6(self,datapath):
        """
        :param datapath: 交换机实例对象
        :return: 忽略IPV6报文
        """
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IPV6)
        actions = []
        self.add_flow(dp=datapath, p=65534, match=match, actions=actions,idle_timeout = 0,hard_timeout = 0)
    # ===================================Packet_Out类======================================
    @staticmethod
    def build_packet_out(datapath, buffer_id, src_port, dst_port, data):
        """
            Build packet out object.只需要对有主机的接入层交换机有用
        """
        actions = []
        if dst_port:
            actions.append(datapath.ofproto_parser.OFPActionOutput(dst_port))

        msg_data = None
        if buffer_id == datapath.ofproto.OFP_NO_BUFFER:
            if data is None:
                return None
            msg_data = data

        out = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath, buffer_id=buffer_id,
            data=msg_data, in_port=src_port, actions=actions)

        return out

    def send_packet_out(self, datapath, buffer_id, src_port, dst_port, data):
        """
            Send packet out packet to assigned datapath.
        """
        out = self.build_packet_out(datapath, buffer_id,
                                     src_port, dst_port, data)
        if out:
            datapath.send_msg(out)
    # ===================================flood======================================
    """
        泛洪分为2类
        1.flood_all
            泛洪除area内交换机互联的端口，向area内所有交换机包括边界交换机与边界交换机，边界交换机与主机的端口进行泛洪
            此时边界交换机会向其他area也下发flood
            
        2.flood_local
            只泛洪area内所有与主机相连接的交换机的端口，此方法是用来跨域获取ARP的，方法内部多了一个判断是否泛洪边界交换机与边界
            交换机相连接的端口
    """
    def flood_all(self, data):
        for dpid in self.access_ports:
            for port in self.access_ports[dpid]:
                if (dpid, port) not in self.access_table.keys():

                    datapath = self.dps[dpid]

                    out = self.build_packet_out(
                        datapath, datapath.ofproto.OFP_NO_BUFFER,
                        datapath.ofproto.OFPP_CONTROLLER, port, data)
                    datapath.send_msg(out)

    def flood_local(self,data):
        for dpid in self.access_ports:
            for port in self.access_ports[dpid]:
                key=(dpid,port)
                if (key not in self.access_table) and (key not in self.edge_sw):

                    datapath = self.dps[dpid]
                    out = self.build_packet_out(
                        datapath, datapath.ofproto.OFP_NO_BUFFER,
                        datapath.ofproto.OFPP_CONTROLLER, port, data)
                    datapath.send_msg(out)















