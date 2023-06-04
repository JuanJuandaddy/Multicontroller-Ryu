"""
    日志处理器
"""
import logging
import colorlog
class Logger(object):
    def __init__(self):
        self.logger=None
    def run(self,type):
        self.logger = logging.getLogger('ROOT')
        stream_handler = logging.FileHandler('test.log',mode='w')
        self.logger.setLevel(level=logging.DEBUG)
        fmt_string = '%(log_color)s[{}]=> %(message)s'.format(type)
        log_colors = {
            'DEBUG': 'white',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'purple'
        }
        fmt = colorlog.ColoredFormatter(fmt_string, log_colors=log_colors)
        stream_handler.setFormatter(fmt)
        self.logger.addHandler(stream_handler)
        return self.logger


