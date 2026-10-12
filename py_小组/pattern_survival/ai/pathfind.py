"""网格寻路工具：BFS 距离场与 A* 最短路。

AI 主要使用"距离场"方案：从自身格出发做一次广度优先搜索得到全图最短
步数，据此选择最近的"安全格"并取出第一步移动方向（单次 O(N)，13×13
地图开销可忽略）。A* 作为通用最短路实现，供扩展与测试使用。
"""

import heapq
from collections import deque


def neighbors(col, row, size):
    """生成 ``(col, row)`` 的四邻格坐标（仅地图内）。"""
    if col > 0:
        yield (col - 1, row)
    if col < size - 1:
        yield (col + 1, row)
    if row > 0:
        yield (col, row - 1)
    if row < size - 1:
        yield (col, row + 1)


def distance_field(start, size, blocked=None):
    """从 ``start`` 出发的 BFS 距离场（四邻、单位步长）。

    返回 ``{(col, row): 最短步数}``。

    参数：
    * ``blocked`` —— 不可通行格集合（默认空；游戏中地面无绝对墙，
      阻挡主要来自其他单位的软避让，故一般情况下不阻塞）。
    """
    start = (int(start[0]), int(start[1]))
    blocked = blocked or set()
    if start in blocked:
        return {}
    dist = {start: 0}
    queue = deque([start])
    while queue:
        col, row = queue.popleft()
        step = dist[(col, row)]
        for nxt in neighbors(col, row, size):
            if nxt in dist or nxt in blocked:
                continue
            dist[nxt] = step + 1
            queue.append(nxt)
    return dist


def first_step(field, start, goal, size):
    """在距离场中把 ``goal`` 回溯到起点附近，返回第一步方向 ``(dx, dy)``。

    * ``field`` —— :func:`distance_field` 的返回值（起点距离为 0）；
    * 返回值为四向单位向量；``goal`` 不可达时返回 ``None``。
    """
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))
    if goal not in field or start not in field:
        return None
    cur = goal
    guard = field[goal] + 2
    while field[cur] > 1 and guard > 0:
        guard -= 1
        for nxt in neighbors(cur[0], cur[1], size):
            if field.get(nxt) == field[cur] - 1:
                cur = nxt
                break
        else:
            return None                     # 距离场异常（理论上不会发生）
    dx = cur[0] - start[0]
    dy = cur[1] - start[1]
    return (max(-1, min(1, dx)), max(-1, min(1, dy)))


def nearest_target(start, targets, size, blocked=None):
    """在 ``targets``（格坐标集合）中找距 ``start`` 最近的目标格。

    返回 ``(goal, field)``；全部不可达时 ``goal`` 为 ``None``。
    """
    field = distance_field(start, size, blocked)
    best, best_dist = None, None
    for cell in targets:
        cell = (int(cell[0]), int(cell[1]))
        dist = field.get(cell)
        if dist is None:
            continue
        if best_dist is None or dist < best_dist:
            best, best_dist = cell, dist
    return best, field


def astar(start, goal, size, blocked=None):
    """A* 最短路（四邻、单位代价、曼哈顿启发）。

    返回包含起点与终点的路径列表 ``[start, ..., goal]``；
    不可达或起终点被阻挡时返回 ``None``。
    """
    blocked = blocked or set()
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))
    if start in blocked or goal in blocked:
        return None

    open_heap = [(0, start)]
    came = {start: None}
    cost = {start: 0}
    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur == goal:
            path = []
            node = cur
            while node is not None:
                path.append(node)
                node = came[node]
            path.reverse()
            return path
        for nxt in neighbors(cur[0], cur[1], size):
            if nxt in blocked:
                continue
            new_cost = cost[cur] + 1
            if nxt not in cost or new_cost < cost[nxt]:
                cost[nxt] = new_cost
                came[nxt] = cur
                heuristic = abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1])
                heapq.heappush(open_heap, (new_cost + heuristic, nxt))
    return None
