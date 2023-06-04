"""
Server唯一外部处理类
服务器对于每个控制器的处理方法,
"""
import json
from functools import reduce
import networkx as nx
from StreamInfo import InfoProcess
class ClientMsgProcess(object):
    def __init__(self,client):
        self.client=client
        self.log=InfoProcess()


    def process(self,msg):
        type=msg["msg_type"]

        if type=="sw_register":
            self._sw_register(msg) #交换机注册事件
            return

        if type=="get_topo":
            self._get_topo(msg)
            return

        if type=="shortest_path":
            self._shortest_path(msg)
            return

        if type=="register_acc_info":
            self._register_acc_info(msg)
            return

        if type=="packet_out":
            self._packet_out(msg)
            return

        if type=="arp_cross_ip":
            self._arp_cross_ip(msg)
            return

        if type=="register_arp_table":
            self._register_arp_table(msg)
            return

        if type=="register_edge_sw":
            self._register_edge_sw(msg)
            return

    """
       消息入口类
    """
    def _sw_register(self,msg):
        gra = self.client.server.graph

        dpid = msg["dpid"]
        master_controller = msg["master_controller"]

        self.client.server.switches[dpid] = master_controller
        gra.add_node(dpid) #给图添加节点

    def _get_topo(self,msg):
        """
            画出每个控制器自己的area拓扑，但是并不能画出边界交换机之间的连接关系，处理该类连接关系的方法在register_edge_sw
        """
        gra=self.client.server.graph

        if msg["topo_type"]=="link_list":
            link=msg["data"]

            src_dpid = link["src_dpid"]
            dst_dpid = link["dst_dpid"]
            src_port = link["src_port"]
            dst_port = link["dst_port"]

            #给图添加边
            gra.add_edge(src_dpid, dst_dpid,src_port=src_port,dst_port=dst_port)

            self.client.server.topo[(src_dpid,dst_dpid)]=(src_port,dst_port)

    def _shortest_path(self,msg):
        """
        处理控制器发出的跨域IP请求，当收到的请求在全域路径表中，返回路径，否则就计算最短路径。返回路径表
        处理返回的路径表，通过交换机从属表判断路径表中各个交换机的从属状况，将路径分为n个域
        比如[1,2,3,4,5] 当4,5属于域2,且1,2,3属于域1中，则将路径表分为2个域，[1,2,3]、[4,5]，随后分别
        将这2个域中的控制器下发消息即可完成


        由于packet_out的时候，一般是接入层交换机先触发packet_in，随后再去计算路径，通过给路径的中间节点
        下发流表，给接入层交换机下发packet_out来让网络互通，正常情况来说中间节点不会再触发packet_in，但是由于流表下发的顺序性质
        在下发接入层的packet_out时，数据包发出到达下一转发节点的ovs的时候，此时中间节点的安装不及时，并没有流表，故也会触发packet_in
        故也需要对此类ovs进行处理，所以创建了dpath来处理该类packet_in

        nx的最短路径算法存在bug，该方法可能导致计算后的路径不包含首节点
        """
        gra=self.client.server.graph
        data=msg["data"]
        ip_src,ip_dst=data["ip_src"],data["ip_dst"]


        key_ip=(ip_src,ip_dst)


        src_dpid,dst_dpid=data["src_dpid"],data["dst_dpid"]

        buffer_id,msg_data=data["buffer_id"],data["msg_data"]

        key_dpid=(src_dpid,dst_dpid)
        paths=self.client.server.paths
        dpaths=self.client.server.dpaths
        switches=self.client.server.switches


        """
            下方两种校验用途如下
            即存在一个交换机下存在1个以上的主机
            对于两个不同交换机下不同主机进行通信，采取的路径相同即可不考虑负载均衡的情况
            对此需要收集不同主机之间的路径以及不同交换机之间的路径，方便后续直接拿出
        """

        if key_ip not in paths.keys():

            #不存在于全域IP路径表
            path = nx.shortest_path(gra, src_dpid, dst_dpid)
            while path[0] != src_dpid:#校验路径表的合法性
                path = nx.shortest_path(gra, src_dpid, dst_dpid)
                if path[0] == src_dpid:
                    break
            paths[key_ip]=path #存储计算后的路径表
            dpaths[key_dpid]=path #存储该dpid路径表


        if key_dpid not in dpaths.keys():
            #不存在全域dpid路径表
            path = nx.shortest_path(gra, src_dpid, dst_dpid)
            while path[0] != src_dpid:#校验路径表是否正确
                path = nx.shortest_path(gra, src_dpid, dst_dpid)
                if path[0] == src_dpid:
                    break
            dpaths[key_dpid] = path  # 存储计算后dpid路径表

        #以dpaths为主，paths为辅
        p=dpaths[key_dpid]
        #存在于全域路径表
        cid_nodelist_map=self.search_controller_pathnode_map(path=p,switches=switches)
        """
            cid_nodelist_map:
            假设switches的映射为：{1:1,2:1,3:1,4:2,5:2,6:2,7:3,8:3}
            假设path为[1,2,4,5,7,8]
            返回map为:{1:[1,2],2:[4,5],3:[7,8]},即是控制器掌管的交换机与路径中的节点之间的关系  
            返回res为:{1:2,2:2,3:2},key为控制器ID，value为该控制器所控制的node在path所占的路径长度，方便后续跨域下发流表  
            由于要下发packet_out与安装流表，故8节点去除，得到最终map为{1:[1,2],2:[4,5],3:[7]}
            当对于中间节点下发流表时，为了方便才将末尾节点去除，到7节点安装流表时，只需要寻找7到8的out_port即可
            在for阶段省去了对尾节点的判断
        """

        self.build_packetout(controller_id=int(switches[p[0]]),data=msg_data,f=p[0],s=p[1],buffer_id=buffer_id)

        """
            首先需要对首节点与次节点进行packet_out,再进行中间节点的流表下发
        """
        self.distribute_flowmod(gra,key_ip,cid_nodelist_map,p)

        """
            依次让map中存在的控制器进行下发相关流表命令
            self.client.server.controller_obj  {controller_id:该controller的socket句柄} 
        """

    def _register_acc_info(self,msg):
        """
        ovs与IP之间的映射唯一，不需要做判断处理
        :param msg: 消息体
        :return: 注册ovs与IP的映射
        """
        data=msg["data"]
        dpid,in_port,ip,area_id=data["dpid"],data["in_port"],data["ip"],data["area_id"]


        key=(dpid,in_port)


        self.client.server.sw_ip.setdefault(key,{})


        self.client.server.sw_ip[key]["ip"] = ip
        self.client.server.sw_ip[key]["area_id"] = area_id

    def _arp_cross_ip(self,msg):
        """
        :param msg: arp的跨域请求
        :return:
        """
        data=msg["data"]
        dpid,in_port,src_ip,dst_ip,msg_data=data["dpid"],data["in_port"],data["src_ip"],data["dst_ip"],data["msg_data"]

        #源area
        src_area=self.client.server.switches[dpid]-1


        #目的area,如果已经存储了ip与dpid的映射关系，则根据dst_ip找到目的area,否则向除了src_area的其他area发送FLOOD
        #同时可以更新ip与dpid的映射关系


        # 返回目的IP的areaID也等同于目的dp的master控制器、目的交换机、IP与交换机连接的端口
        dst_dpid,port,dst_area,flag=self.find_dst_area(dst_ip)


        if flag:
            #当找到目的IP的相关信息
            self.log.info(f'根据IP：{dst_ip} 找到目标area：{dst_area} 进行packetout')
            self.build_packetout(controller_id=dst_area,data=msg_data,f=dst_dpid,out_port=port)#下发packet_out
        else:
            self.log.info(f'根据IP：{dst_ip} 未找到目标area：{dst_area} 进行flood')
            #未找到目的IP的相关信息，说明Server也没有存储，进行FLOOD，找到目的IP的相关信息，向除了src_area的其他area下发FLOOD
            msg=json.dumps({
                "msg_type":"flood",
                "data":{
                    "msg_data":msg_data
                }
            })

            area_dict=self.client.server.switches.copy()
            area_list=list(set(area_dict.values()))
            area_list.remove(src_area)

            def sub_one(x):
                return x-1

            for controller in map(sub_one,area_list):
                self.log.info(f'进行FLOOD的area：{controller}')
                self.hook_handler(controller_id=controller,msg=msg)

    def _packet_out(self,msg):
        """
            由Server代理发送packetout，用于处理跨域ARP请求
        """
        data=msg["data"]
        dst_ip,msg_data=data["dst_ip"],data["msg_data"]

        dst_dpid, port, dst_area, flag = self.find_dst_area(dst_ip)

        if flag:
            self.log.info(f'Server代理发送packetout：dst_dpid:{dst_dpid} port:{port} dst_area:{dst_area}')
            self.build_packetout(controller_id=dst_area, data=msg_data, f=dst_dpid, out_port=port)
        else:
            self.log.info(f'代理发送packetout失败：dst_dpid:{dst_dpid} port:{port} dst_area:{dst_area}')

    def _register_arp_table(self,msg):

        #注册IP:MAC
        data=msg["data"]
        ip,mac=data["ip"],data["mac"]

        self.client.server.arp_table[ip]=mac

    def _register_edge_sw(self,msg):

        #初始化网络拓扑的边界交换机，后续迁移过程中，边界交换机的更改将会改变

        data=msg["data"]
        dpid,port,area_id=data["dpid"],data["port"],data["area_id"]


        self.client.server.edge_sw[(dpid,port)]=area_id


    """
        消息处理类
    """

    @staticmethod
    def search_controller_pathnode_map(path,switches):
        """
        :param path: 路径表
        :param switches: 交换机与其控制的主控制器之间的map映射
        """
        s = []
        res = {}
        #path=path[:-1]
        for id in path:
            if id in switches.keys():
                s.append(switches[id])
        #去重
        f = lambda x, y: x if y in x else x + [y]
        s = reduce(f, [[], ] + s)
        for cid in s:
            res[cid] = []
        for node in path:
            for sw, con in switches.items():
                if sw == node:
                    res[con].append(node)  #{controller_id: [pathnode,pathnode]....}
        for k, v in res.items():
            res[k] = len(v)
        return res

    def build_packetout(self,controller_id,data,f=None,s=None,out_port=None,buffer_id=None):
        if f and s:
            #处理IP packetout
            gra = self.client.server.graph
            out_port=gra[f][s]["src_port"]

        else:
            #处理ARP packetout
            out_port=out_port

        msg=json.dumps({
            "msg_type":"packet_out",
            "data":{
                "dpid":f,
                "out_port":out_port,
                "msg_data":data,
                "buffer_id":buffer_id
            }
        })
        self.hook_handler(controller_id,msg)

    def distribute_flowmod(self,gra,key_ip,cid_nodelist_map,path):
        g_index=0 #全局索引
        self.log.info(f'node_map:{cid_nodelist_map}')
        for cid,t in cid_nodelist_map.items():

            t+=g_index

            for index in range(g_index,t):
                if index<len(path)-1:#处理头节点以及中间节点

                    out_port=gra[path[index]][path[index+1]]["src_port"]
                    dpid=path[index]
                    self.send_flow_mod(cid,dpid,key_ip,out_port)#调用cid的句柄，发送流表下发命令

            g_index=t

    def send_flow_mod(self,controller_id,dpid,key_ip,out_port):
        """
        :param controller_id: 控制器对象
        :param dpid: ovsID
        :param key_ip: （ipsrc,ipdst）
        :param out_port: dpid匹配到该key_ip的出端口
        """
        msg=json.dumps({
            "msg_type":"flow_mod",
            "data":{
                "dpid": dpid,
                "ip_src": key_ip[0],
                "ip_dst":key_ip[1],
                "out_port":out_port
            }
        })
        self.hook_handler(controller_id,msg)

    def hook_handler(self,controller_id,msg):
        """
        :param controller_id: controller的ID
        :param msg: 消息体
        :return: 发送给指定controller的消息
        """
        # 调用controller_id的发送消息句柄
        self.client.server.controller_obj[controller_id].send_to_queue(msg)

    def get_controller_id(self,dpid):
        return self.client.server.switches[dpid]

    def find_dst_area(self,dst_ip):
        for key, value in self.client.server.sw_ip.items():
            if dst_ip == value["ip"]:
                # 找到了目的IP的area_id
                return key[0], key[1], int(value["area_id"]), True
        return None, None, None, False




