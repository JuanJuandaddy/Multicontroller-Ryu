
"""
    Info处理器
    print("\033[显示方式；前景颜色；背景颜色m…\033[0m")
    显示方式：        前景颜色、背景颜色：
    高亮  1           黑色：30 40
    下划线 4          红色：31 41
    闪烁  5          绿色：32 42
    反白显示  7      黄色：33 43
    不可见 8        蓝色：34 44
    默认  0        紫红色：35 45
                  青蓝色：36 56
                  白色：37 47
"""
class InfoProcess(object):
    def __init__(self):
        pass
    def info(self,msg,*args):
        if len(args)==0:
            print("\033[0;33m[{}]{}\033[0m".format("INFO",msg))
        else:
            print("\033[0;33m[{}]{}\033[0m".format(args[0], msg))
    def error(self,msg,*args):
        if len(args) == 0:
            print("\033[0;31m[{}]{}\033[0m".format("ERROR",msg))
        else:
            print("\033[0;31m[{}]{}\033[0m".format(args[0], msg))
    def warning(self,msg,*args):
        if len(args)==0:
            print("\033[0;35m[{}]{}\033[0m".format("WARNING",msg))
        else:
            print("\033[0;35m[{}]{}\033[0m".format(args[0], msg))