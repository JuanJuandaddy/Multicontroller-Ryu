import netifaces
def run():
    interface_list = netifaces.interfaces()
    mac_list = {}
    for face in interface_list:
        mac = netifaces.ifaddresses(face)[netifaces.AF_LINK][0]["addr"]
        f = list(face)
        if len(f) == 2:
            g = lambda x: ''.join(f) if (x[0] != 'l') else ''
            if g(f) != '':
                mac_list[g(f)] = mac
    return mac_list