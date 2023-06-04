# -*-coding:utf-8-*-
"""
该类为客户端处理类，每个连接上Server的客户端的消息处理都依靠此类实现
"""
from gevent import monkey;monkey.patch_all()
import json
import gevent
from gevent import spawn
from queue import Queue
from ClientMsgProcess import ClientMsgProcess
from StreamInfo import InfoProcess
import  settings
import time
CONTROLLER_NUM=settings.CONTROLLER_NUM
QUEUE_LEN=settings.QUEUE_LEN
class Client(object):#Controller客户端处理类
    def __init__(self, socket):
        #初始服务基类
        super(Client, self).__init__()
        self.queue = Queue(maxsize=CONTROLLER_NUM * QUEUE_LEN) #controller and server send message 创建消息队列，长度依据控制器数目而定
        self.status =None #已经建立连接
        self.server=None
        self.socket = socket  #socket处理类
        self.cur_id= None #当前客户端ID
        self.log=InfoProcess()
        self.MsgProcess=ClientMsgProcess(self)#处理消息的句柄

    # =========编码格式============
    def deco(self,msg):
        """
        :param msg: 需要加码的消息内容 bytes->str
        :return: 返回加码后的内容
        """
        return msg.decode(encoding='utf-8')

    def enco(self,msg):
        """

        :param msg: 需要解码的消息内容 str->bytes
        :return:  返回解码后的内容
        """
        return str(msg).encode(encoding='utf-8')

    # =========发送消息handle===========
    def send_msg(self,msg):
        """
        :param socket: 套接字对象，用于指明和谁发消息
        :param msg: 消息内容
        :return: 发送具体消息
        """
        self.socket.sendall(self.enco(msg))

    def send_to_queue(self,msg):
        """
        :param msg: 入队的 消息内容
        :return: 入队操作
        """
        #不为满，则入队
        if self.queue:  # 队列不为空
            msg+=settings.MsgBarrier#加入分隔符
            self.queue.put(msg)  # 入队列

    def send_msg_handle(self):#
        try:
            while self.status:
                msg = self.queue.get()
                self.send_msg(msg)
        finally:
            self.queue = None

    # =========接收消息handle============
    def rec_msg_handle(self):#
        """

        :param to_controller: 给某个控制器发消息的socket句柄
        :param addr: IP地址
        :return: 不停的监听该controller发来的请求
        """
        while self.status:
            try:
                message=self.socket.recv(1024)
                if message:
                    for msg in self.deco(message).split(settings.MsgBarrier):
                        if msg!='':
                            # 解析为python对象，为字典
                            self.MsgProcess.process(json.loads(msg))#根据种类，选择处理方式
                else:
                    break
            except Exception as e:
                raise e
                #self.log.info("Client JSON格式解析错误")

    # =========消息格式============
    def set_controller_id(self):
        """
        :param socket: socket句柄
        :param id: 设置给某控制器的 ID
        :return: 入队操作
        """
        msg=json.dumps({
            "status":1,
            "msg_type":"set_id",
            "controller_id":self.cur_id,
            "info": "控制器ID："+str(self.cur_id) + " has connected!"
        })
        self.send_to_queue(msg)

    # =========开启协程，关闭线程============
    def start_spawn(self):
        s=spawn(self.send_msg_handle)
        r=spawn(self.rec_msg_handle)
        gevent.joinall([s,r])

    def close(self):  # 重写contexglib.closing的close方法
        self.status = False
        self.socket.close()