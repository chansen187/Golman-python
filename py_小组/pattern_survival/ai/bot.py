"""人机单位的行为控制器（SurvivalBot）。

行为状态机（与设计需求一一对应）：

* ``escape`` —— 逃生：倒计时低于逃生阈值且不在安全格 → 全速冲向最近安全格；
* ``seek``   —— 找安全格 / 抢格：时间尚可但不在安全格 → BFS 选择最近的
  安全格前往；对"已被对手占据"的格子施加额外代价，体现"抢"的取舍；
* ``push``   —— 推人：已站安全格、旁边有可推单位且倒计时 > 1.5 秒 →
  先转向目标再推（推人朝面朝方向进行）；
* ``chase``  —— 主动干扰：已站安全格、时间充裕且附近有"身处危险格"的
  对手 → 主动逼近，把对方推向深渊（最多追击一小段时间后回撤）；
* ``wander`` —— 随机扰动：无事可做时在所在格内做小幅随机调整。

难度（简单 / 普通 / 困难）通过基类的四个参数影响本控制器：
``reaction``（反应速度）、``precision``（寻路精度）、``aggression``
（推人欲望）、``escape_time``（逃生阈值）。
"""

from ai import pathfind
from ai.base_agent import BaseAgent


class SurvivalBot(BaseAgent):
    """图案生存战人机控制器。"""

    STATE_ESCAPE = "escape"
    STATE_SEEK = "seek"
    STATE_PUSH = "push"
    STATE_CHASE = "chase"
    STATE_WANDER = "wander"

    def __init__(self, name="人机", difficulty="normal", seed=None):
        """构造人机控制器（参数含义见 :class:`BaseAgent`）。"""
        super().__init__(name, difficulty, seed)
        self.state = self.STATE_WANDER
        self._chase_left = 0.0              # 剩余追击时间（秒）

    # ============================================================ 主决策
    def decide(self, obs):
        """根据观测输出本决策周期的移动方向与推人请求。"""
        me = obs["self"]
        grid = obs["grid"]
        target = obs["target"]
        countdown = float(obs["countdown"])
        size = len(grid)
        my_cell = (int(me["cell"][0]), int(me["cell"][1]))
        others = obs.get("units", [])
        on_safe = self.is_safe_cell(grid, my_cell, target)

        # ---- 1. 逃生（最高优先级）：时间紧迫且不在安全格
        if (not on_safe) and countdown <= self.escape_time:
            self.state = self.STATE_ESCAPE
            self._chase_left = 0.0
            return {"move": self._step_to_safe(my_cell, grid, target, size,
                                               others, urgent=True),
                    "push": False}

        # ---- 1.5 追击续程：正在主动干扰且条件仍成立
        if (not on_safe) and self._chase_left > 0.0 and countdown > 2.5:
            prey = self._pick_prey(me, others, grid, target, my_cell)
            if prey is not None:
                self._chase_left -= self.reaction
                self.state = self.STATE_CHASE
                return {"move": self._step_towards(my_cell, prey, size),
                        "push": False}
            self._chase_left = 0.0

        # ---- 2. 站在安全格上
        if on_safe:
            # 2.1 推人：倒计时 > 1.5 秒且旁边有可推的单位
            if countdown > 1.5:
                push_dir = self._pick_push(me, others, grid, target)
                if push_dir is not None and self.rng.random() < self.aggression:
                    self.state = self.STATE_PUSH
                    if tuple(me["facing"]) != push_dir:
                        # 先转向：小步移动即可改变朝向（不产生明显位移）
                        return {"move": (push_dir[0] * 0.25, push_dir[1] * 0.25),
                                "push": False}
                    return {"move": (0.0, 0.0), "push": True}
            # 2.2 主动干扰：时间充裕且附近有身处危险格的对手
            if countdown > 2.5 and self.rng.random() < self.aggression * 0.6:
                prey = self._pick_prey(me, others, grid, target, my_cell)
                if prey is not None:
                    self._chase_left = 0.8          # 开启一段追击
                    self.state = self.STATE_CHASE
                    return {"move": self._step_towards(my_cell, prey, size),
                            "push": False}
            # 2.3 随机扰动：在格内小幅调整站位
            self.state = self.STATE_WANDER
            return {"move": self._wander(me, my_cell), "push": False}

        # ---- 3. 不在安全格、时间尚可 → 找安全格（抢格）
        # 3.1 顺手推：旁边就有对手且时间足够时干扰一下
        if countdown > 2.0 and self.rng.random() < self.aggression * 0.4:
            push_dir = self._pick_push(me, others, grid, target)
            if push_dir is not None and tuple(me["facing"]) == push_dir:
                self.state = self.STATE_PUSH
                return {"move": (0.0, 0.0), "push": True}
        self.state = self.STATE_SEEK
        return {"move": self._step_to_safe(my_cell, grid, target, size, others),
                "push": False}

    # ============================================================ 移动工具
    def _step_towards(self, my_cell, goal_cell, size):
        """朝目标格迈出第一步（BFS 距离场 + 回溯），返回方向向量。"""
        field = pathfind.distance_field(my_cell, size)
        step = pathfind.first_step(field, my_cell, goal_cell, size)
        if step is None:
            return (0.0, 0.0)
        return (float(step[0]), float(step[1]))

    def _step_to_safe(self, my_cell, grid, target, size, others, urgent=False):
        """前往最近的"安全格"，返回第一步方向。

        * 对已被对手占据的格子施加 +2 步代价（能绕则绕，抢不到就换）；
        * 非紧急状态下按寻路精度加入随机代价（低难度选格更粗糙）；
        * ``urgent=True``（逃生）时只挑最近的安全格，不再权衡。
        """
        safe_cells = self.find_safe_cells(grid, target)
        if not safe_cells:
            return (0.0, 0.0)
        field = pathfind.distance_field(my_cell, size)
        occupied = {tuple(u["cell"]) for u in others if u.get("in_play", True)}
        noise = 0.0 if urgent else (1.0 - self.precision) * 4.0

        best, best_cost = None, None
        for cell in safe_cells:
            dist = field.get(cell)
            if dist is None:
                continue
            cost = float(dist)
            if not urgent and cell in occupied:
                cost += 2.0
            if noise > 0.0:
                cost += self.rng.random() * noise
            if best_cost is None or cost < best_cost:
                best, best_cost = cell, cost
        if best is None:
            return (0.0, 0.0)
        step = pathfind.first_step(field, my_cell, best, size)
        if step is None:
            return (0.0, 0.0)
        return (float(step[0]), float(step[1]))

    # ============================================================ 目标选择
    def _pick_push(self, me, others, grid, target):
        """挑选一个"推得中"的相邻单位，返回推的方向；没有则返回 ``None``。

        判定与游戏引擎的命中判定完全一致：方向投影 ``0 < t ≤ 1.5`` 且
        横向偏差 ``≤ 0.7`` 格。评分时优先：
        1. 对手不在安全格（推进坑最划算）；
        2. 对手被推后的落点不在安全格；
        3. 距离更近、角度更正。
        """
        mx, my = me["pos"]
        best_dir, best_score = None, None
        for u in others:
            if not u.get("in_play", True):
                continue
            ux, uy = u["pos"]
            dx, dy = ux - mx, uy - my
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                along = dx * d[0] + dy * d[1]
                perp = abs(dx * d[1] - dy * d[0])
                if not (0.0 < along <= 1.5 and perp <= 0.7):
                    continue
                score = 2.0 - perp - 0.2 * along
                cell = (int(u["cell"][0]), int(u["cell"][1]))
                if not self.is_safe_cell(grid, cell, target):
                    score += 2.0                    # 对手在危险格 → 值得补刀
                dest = (cell[0] + d[0], cell[1] + d[1])
                if not self.is_safe_cell(grid, dest, target):
                    score += 1.0                    # 落点危险 → 推进坑
                if best_score is None or score > best_score:
                    best_dir, best_score = d, score
        return best_dir

    def _pick_prey(self, me, others, grid, target, my_cell):
        """挑选一个"身处危险格、距离 ≤ 3 格"的对手作为干扰目标。

        没有合适的对手时返回 ``None``。
        """
        best, best_dist = None, None
        for u in others:
            if not u.get("in_play", True):
                continue
            cell = (int(u["cell"][0]), int(u["cell"][1]))
            if self.is_safe_cell(grid, cell, target):
                continue                            # 对手自己安全，不值得出击
            dist = max(abs(cell[0] - my_cell[0]), abs(cell[1] - my_cell[1]))
            if dist > 3:
                continue                            # 太远，跑过去不划算
            if best_dist is None or dist < best_dist:
                best, best_dist = cell, dist
        return best

    # ============================================================ 随机扰动
    def _wander(self, me, my_cell):
        """在所在格内做小幅随机调整（不会走出当前格）。"""
        if self.rng.random() < 0.45:
            return (0.0, 0.0)                       # 约一半时间保持静止
        cx = my_cell[0] + 0.5 + self.rng.uniform(-0.16, 0.16)
        cy = my_cell[1] + 0.5 + self.rng.uniform(-0.16, 0.16)
        dx = cx - me["pos"][0]
        dy = cy - me["pos"][1]
        if abs(dx) < 0.04 and abs(dy) < 0.04:
            return (0.0, 0.0)
        return (dx * 2.0, dy * 2.0)                 # 长度受限 → 慢速小幅挪动
