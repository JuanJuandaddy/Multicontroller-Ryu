import netifaces
#json消息分隔符
MsgBarrier='/'

#IP地址 Server的地址


#IP='192.168.44.129'
IP='127.0.0.1'

#监听端口
PORT=8888

#队列长度
QUEUE_LEN=100

#控制器数量
CONTROLLER_NUM=2


#角色对象
"""
    控制器角色代码
    OFPCR_ROLE_NOCHANGE = 0, /* 不改变当前角色. */
    OFPCR_ROLE_EQUAL = 1, /* 默认角色，完全读写. 一个ovs可以有多个equal*/
    OFPCR_ROLE_MASTER = 2, /* 完全读写，但是只能有一个master，一旦设置为master，其他所连接的控制器都为slave */
    OFPCR_ROLE_SLAVE = 3, /* 只具有只读权限，而且异步消息不能获取，只能获取Port-Status消息*/
"""
ID_ROLE_MAP={
    0:"NOCHANGE",
    1:"EQUAL",
    2:"MASTER",
    3:"SLAVE"
}
#Controller
ECHO=5#单位秒

CONTROLLER_IP='127.0.0.1'

OFP_VERSION='OpenFlow13'#openflow版本

ECHO_DELAY=1#几个周期后开始request

#Server
WAIT_CONNECT=10   #最大等待连接数

MONITOR=10        #打印消息周期

#TOPO
CONTROLLERS=['c0','c1']#控制器ID，代表有子网0和子网1，代表着有area0和area1两个控制area，
                            # 在Ryu源码中该配置极其重要，务必2者保持一致

CONTROLLER_PORTS=[6653,6654] #控制器端口

EDGE_LINK={("s3","s4"):[3,3]}#边缘交换机的连接端口，用于Server对全局拓扑的初始化

SW_LINK={("s1","s2"):[2,2],("s2","s3"):[3,2],
         ("s4","s5"):[2,2],("s6","s5"):[2,1]}#交换机之间的链路

SW_HOST={"s1":"h1","s3":"h2","s4":"h3","s6":"h4"}#交换机与主机之间的映射

SWS=[["s1","s3","s2"],["s5","s6","s4"]]#全体交换机，区分控制器

HOSTS=[["h1","h2"],["h3","h4"]]#全体主机，区分控制器

#MAC
UNKNOWN_MAC='00:00:00:00:00:00'#ARP请求的IP中默认的未知MAC

BROADCAST_MAC='ff:ff:ff:ff:ff:ff' #广播地址

#获取拓扑中交换机的MAC地址
def get_mac():
    interface_list = netifaces.interfaces()
    mac_list = {}
    for face in interface_list:
        mac = netifaces.ifaddresses(face)[netifaces.AF_LINK][0]["addr"]
        f = list(face)
        if len(f) == 2:
            g = lambda x: ''.join(f) if (x[0] != 'l') else ''
            if g(f) != '':
                mac_list[g(f)] = mac
    return list(mac_list.values())