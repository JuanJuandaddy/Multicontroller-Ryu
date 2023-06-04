#!/usr/bin/python
import time

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import  RemoteController
from mininet.node import  Host
from mininet.node import OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink#设置链路带宽的选项
from subprocess import Popen
from multiprocessing import Process
import numpy as np
"""
此为全连接多控制器，表示每个控制器都连接到了所有交换机
"""
class multicon_topo(Topo):
    #可选参数的值为sw_link，sw_host,switches,hosts,分别代表ovs之间的连接链路，连接了主机的ovs，所有ovs列表，所有主机列表
    #均与controller中的控制器进行对齐
    #参数形式为multicon_topo('127.0.0.1','OpenFlow13',['c1','c2'],[6653,6654],{tuple(sw1,sw2):[port1,port2]},{acc_sw:host}，
    # [[s1,s2...],[sj,sj+1...]],[[h1,h2...],[hj,hj+1...]])
    def __init__(self, remote_ip, ofp_version, controllers, ports, *args, **kwargs):
        self.net=Mininet(controller=RemoteController)
        self.ip=remote_ip
        self.version=ofp_version
        self.cons=controllers
        self.ports=ports
        self.con_obj=[]
        self.sw_obj=[]
        self.args=kwargs#传递的多余参数列表，类型为tuple，**kwargs为字典
        self.subnets=self.split_controllers()#子网ID
    def split_controllers(self): #返回控制器数目，作为子网数，子网ID由控制器ID为主
        subnets=[]
        for c in self.cons:
            subnets.append(list(c)[1])
        return subnets
    def create_controller(self):
        for index,c in enumerate(self.cons):
            con=self.net.addController(name=c,controller=RemoteController,ip=self.ip,port=self.ports[index],protocol='tcp')
            self.con_obj.append(con)
    def create_switch(self):#创建交换机实例
        for index,sw in enumerate(self.args["switches"]):
            sws=[]
            for s in sw:
                s=self.net.addSwitch(s,protocols=self.version,cls=OVSKernelSwitch)
                sws.append(s)
            self.sw_obj.append(sws)
    def create_host(self):
        for index,host in enumerate(self.args["hosts"]):#[h1,h2,h3...]
            for i,h in enumerate(host):#h3..
                h=self.net.addHost(h,cls=Host,ip="192.168."+self.subnets[index]+"."+str(i+1))
    def create_link(self):
        #创建主机与ovs连接的链路，ovs连接host的端口为1
        for sw,host in self.args["sw_host"].items():
            self.net.addLink(sw,host,1)
        #创建ovs之间的连接链路
        for sw,port in self.args["sw_link"].items():
            self.net.addLink(sw[0],sw[1],port[0],port[1])
    def start_sw_con(self):
        sws=[]
        for sw in self.sw_obj:
            sws.extend(sw)
        for s in sws:
            s.start([self.con_obj[0],self.con_obj[1]])
    def start_con(self):
        for con in self.con_obj:
            con.start()
    def build_topo(self):
        self.create_controller()
        self.create_host()
        self.create_switch()
        self.create_link()
    def CLI(self):
        CLI(self.net)
    def stop(self):
        self.net.stop()
def run(ip,version,cons,ports,swl,swh,sws,h):
    topo=multicon_topo(
        remote_ip=ip,ofp_version=version,controllers=cons,ports=ports,
        sw_link=swl,sw_host=swh,switches=sws,hosts=h
    )
    topo.build_topo()
    topo.net.build()
    topo.start_con()
    topo.start_sw_con()
    topo.CLI()
    topo.stop()
if __name__ == '__main__':
    IP='127.0.0.1' #控制器IP
    OFP_VERSION='OpenFlow13' #openflow版本
    CONTROLLERS=['c0','c1'] #控制器ID
    PORTS=[6653,6654] #控制器端口
    SW_LINK={("s1","s5"):[2,2],("s5","s2"):[3,2],
             ("s3","s6"):[2,2],("s6","s4"):[3,2],("s2","s3"):[3,3]}#交换机之间的链路
    SW_HOST={"s1":"h1","s2":"h2","s3":"h3","s4":"h4"}#交换机与主机之间的映射
    SWS=[["s1","s5","s2"],["s3","s6","s4"]]#全体交换机，区分控制器
    HOSTS=[["h1","h2"],["h3","h4"]]#全体主机，区分控制器
    run(IP,OFP_VERSION,CONTROLLERS,PORTS,SW_LINK,SW_HOST,SWS,HOSTS)
