"""推人结算模块。

推人规则（与设计需求对应）：
* 朝面朝方向进行，冷却 ``PUSH_COOLDOWN``（1 秒）；
* 命中前方相邻（1.5 格内、横向偏差 ≤ 0.7 格）的最近单位；
* 被推单位沿推的方向位移最多 ``PUSH_DIST``（2）格，位移在
  ``PUSH_SLIDE_TIME``（0.2 秒）内滑完，展示击退动画；
* 若被推单位身后是边界 / 墙，则推不动（位移 0），但仍施加眩晕；
* 身后有单位可连锁推（最多 ``PUSH_CHAIN_MAX`` 个单位），每个被推单位
  各自位移最多 2 格；
* 推人本身不造成伤害（不扣命、不扣分），但可以把对方推出安全格；
* 所有被影响的单位获得 ``PUSH_STUN``（0.5）秒眩晕，推人者进入 1 秒冷却
  （冷却状态以单位圆形外侧的圆环进度条展示）。
"""

from config import PUSH_CHAIN_MAX, PUSH_DIST, PUSH_LANE, PUSH_RANGE, PUSH_STUN


class PushTarget:
    """一次推人中某个被影响单位的位移记录（供特效 / 录制使用）。"""

    __slots__ = ("unit", "from_xy", "to_xy", "moved_cells", "blocked")

    def __init__(self, unit, from_xy, to_xy, moved_cells, blocked):
        self.unit = unit
        self.from_xy = from_xy              # 起始像素坐标 (x, y)
        self.to_xy = to_xy                  # 目标像素坐标 (x, y)
        self.moved_cells = moved_cells      # 实际位移格数（0 = 推不动）
        self.blocked = blocked              # 是否被边界或障碍挡住


class PushResult:
    """一次推人动作的完整结果。"""

    def __init__(self, pusher, hit, direction, targets):
        self.pusher = pusher
        self.hit = hit                      # 是否命中单位（False = 推空）
        self.direction = direction          # 推的方向 (dx, dy)，四向之一
        self.targets = targets              # list[PushTarget]，按距推人者由近到远


def resolve_push(pusher, units, grid):
    """执行一次推人并返回 :class:`PushResult`。

    副作用集中在本函数内执行：
    * 推人者进入冷却并触发动作震动（无论是否命中）；
    * 所有被影响的单位获得眩晕并开始击退滑动（推不动时仅眩晕）。

    参数：
    * ``pusher`` —— 发起推人的 :class:`core.unit.Unit`；
    * ``units``  —— 全部单位列表；
    * ``grid``   —— :class:`core.grid.Grid`（提供边界判断与格中心换算）。
    """
    fx, fy = pusher.facing
    if not pusher.push_ready:
        return PushResult(pusher, False, (fx, fy), [])

    pusher.note_push_used()                 # 无论命中与否都进入冷却

    first = _find_target(pusher, units, fx, fy, set())
    if first is None:
        return PushResult(pusher, False, (fx, fy), [])

    # 收集连锁链：沿推的方向逐个寻找"身后"的单位
    chain = [first]
    chain_ids = {first.uid}
    while len(chain) < PUSH_CHAIN_MAX:
        nxt = _find_target(chain[-1], units, fx, fy, chain_ids)
        if nxt is None:
            break
        chain.append(nxt)
        chain_ids.add(nxt.uid)

    # 障碍集合：非链单位的占位格；链上"没推动"的单位随后也会加入
    obstacles = set()
    for u in units:
        if u.in_play() and u.uid not in chain_ids:
            obstacles.add(u.cell())

    # 从链尾（最远处）向链头依次解算，保证前方的单位先让出位置
    results = {}
    for u in reversed(chain):
        results[u.uid] = _resolve_one(u, fx, fy, grid, obstacles)
        u.set_stun(PUSH_STUN)               # 无论推动与否都眩晕
        u.hit_flash = 0.25                  # 被推白闪

    ordered = [results[u.uid] for u in chain]
    return PushResult(pusher, True, (fx, fy), ordered)


# ================================================================ 内部工具
def _find_target(origin, units, fx, fy, exclude_ids):
    """在 ``origin`` 面朝方向 1.5 格内寻找最近的单位。

    ``exclude_ids`` 用于连锁收集时排除已入链的单位。
    """
    ox, oy = origin.fcell()
    best, best_t = None, None
    for u in units:
        if u is origin or u.uid in exclude_ids or not u.in_play():
            continue
        ux, uy = u.fcell()
        dx, dy = ux - ox, uy - oy
        along = dx * fx + dy * fy                   # 沿推方向的投影
        perp = abs(dx * fy - dy * fx)               # 横向偏差
        if 0.0 < along <= PUSH_RANGE and perp <= PUSH_LANE:
            if best_t is None or along < best_t:
                best, best_t = u, along
    return best


def _resolve_one(unit, fx, fy, grid, obstacles):
    """解算单个被推单位的位移：最多 ``PUSH_DIST`` 格，遇阻即停。

    同时更新 ``obstacles``：推动成功时加入落点、失败时加入原位，
    供链上更靠近推人者的单位判断阻挡。
    """
    base_col, base_row = unit.cell()
    step_ok = 0
    for step in range(1, PUSH_DIST + 1):
        cc = base_col + fx * step
        rr = base_row + fy * step
        if not grid.in_bounds(cc, rr):
            break
        if (cc, rr) in obstacles:
            break
        step_ok = step

    if step_ok == 0:
        obstacles.add((base_col, base_row))         # 推不动 → 原地成为障碍
        return PushTarget(unit, (unit.px, unit.py), (unit.px, unit.py), 0, True)

    dest_col = base_col + fx * step_ok
    dest_row = base_row + fy * step_ok
    tx, ty = grid.cell_center(dest_col, dest_row)
    obstacles.add((dest_col, dest_row))             # 落点占位
    unit.start_knock(tx, ty)
    return PushTarget(unit, (unit.px, unit.py), (tx, ty),
                      step_ok, step_ok < PUSH_DIST)
