from functools import reduce
path=[4,5,2,1]
switches={1:"1",2:"1",3:"1",4:"2",5:"2",6:"2"}
def search_controller_pathnode_map(path, switches):
    """
    :param path: 路径表
    :param switches: 交换机与其控制的主控制器之间的map映射
    :return: 根据path的顺序返回映射
    """
    s = []
    res = {}
    # path=path[:-1]
    for id in path:
        if id in switches.keys():
            s.append(switches[id])
    # 去重
    f = lambda x, y: x if y in x else x + [y]
    s = reduce(f, [[], ] + s)
    for cid in s:
        res[cid] = []
    for node in path:
        for sw, con in switches.items():
            if sw == node:
                res[con].append(node)  # {controller_id: [pathnode,pathnode]....}
    for k, v in res.items():
        res[k] = len(v)
    return res
for k,v in search_controller_pathnode_map(path,switches).items():
    print(k,v)