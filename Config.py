import sys
"""
配置文件，根据端口选择对应初始主交换机，即交换机对于该端口的控制器状态为master
"""
PORT=[6653,6654]
Switches=[
    [1,2,5],
    [3,4,6]
          ]
args=sys.argv[1]
class Init_Switches(object):
    def __init__(self):
        pass
    def run(self):
        for index, p in enumerate(PORT):
            if int(args.__eq__(str(p))):
                return Switches[index]
if __name__ == '__main__':
    sw=Init_Switches().run()
    with open('/home/ryu/多控制器方面的代码/zoomulti/Switches_For_Each_Controller','w') as file:
        file.write(str(sw))


