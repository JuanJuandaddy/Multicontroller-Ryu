# -*-coding:utf-8-*-
import subprocess
import sys
import time
import re
import contextlib as con
port=sys.argv[1]
find_order="lsof -i:"+port
class kill(object):
    def __init__(self):
        self.find_order=find_order
        self.find=subprocess.Popen(self.find_order,shell=True,stdout=subprocess.PIPE)
        self.kill=None
        self.pid=[]
        self.status=True
    def find_pid(self):
        index=0
        re_compile=re.compile(r'\d*\s*root')
        r=self.find.stdout.readlines()
        if r:
            for i in iter(r):
                if index==0:
                    index+=1
                    continue
                else:
                    res=re.findall(re_compile,str(i))
                    if len(res)!=0:
                        self.pid.append(int(str(re.findall(re_compile,str(i))[0]).split(" ")[0]))
            print("{}的PID号为:{}".format(str(sys.argv[1]), list(set(self.pid))))
            self.wait()
        else:
            print("此端口:{}无PID".format(port))
            return

    def kill_pid(self):
        if len(self.pid):
            pids=""
            for i in iter(list(set(self.pid))):
                pids+=" "+str(i)
            subprocess.Popen("kill -9"+pids, shell=True)
            print("清除端口：{} PID：{}完毕".format(port,list(set(self.pid))))
        else:
            return
    def wait(self):
        self.find.wait()
    def close(self):
        self.find.stdout.close()
with con.closing(kill()) as k:
    k.find_pid()
    time.sleep(0.5)
    k.kill_pid()
