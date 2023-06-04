# -*-coding:utf-8-*-
"""
由外部控制器类进行调用，用于发送消息
"""
import json
from StreamInfo import InfoProcess
import settings
class ConSend(object):
    def __init__(self,socket,controller):
        self.socket=socket
        self.controller=controller
        self.log=InfoProcess()
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
        if self.controller.queue:

            msg+=settings.MsgBarrier
            self.controller.queue.put(msg)

    def send_loop(self):
        try:
            while self.controller.status:

                msg=self.controller.queue.get()
                self.send_msg(msg)

        finally:
            self.controller.queue=None
