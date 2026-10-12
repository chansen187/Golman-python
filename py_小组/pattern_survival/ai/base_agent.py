"""AI 基类：统一决策接口、观测解析、难度参数与反应节流。

AI 与游戏引擎的契约（引擎每个逻辑帧调用 :meth:`BaseAgent.think`）：

**观测字典 ``obs``**：

.. code-block:: python

    {
        "self": {                        # 自身信息
            "id": int,
            "pos": (fc, fr),             # 浮点格坐标
            "cell": (col, row),          # 整数格坐标
            "stunned": bool,             # 是否眩晕
            "push_ready": bool,          # 推人冷却是否就绪
            "facing": (dx, dy),          # 面朝方向（四向之一）
            "lives": int,
        },
        "target": "x" | "o" | "square" | "triangle",   # 当前目标图案
        "grid": [[图案, ...], ...],      # 每格图案二维数组（13×13）
        "units": [                       # 其他单位（不含自己）
            {"id", "pos", "cell", "team", "stunned", "in_play", "lives"},
            ...
        ],
        "countdown": float,              # 本回合剩余秒数
        "round": int,                    # 当前回合序号
    }

**返回值**：``{"move": (dx, dy), "push": bool}``

* ``move`` —— 期望移动方向向量；长度 ≤ 1 时按比例降速（用于微调 / 转向），
  > 1 时归一化为全速；零向量表示原地不动；
* ``push`` —— 本决策周期是否请求推人（每次决策只会生效一次）。
"""

import random

from config import AI_DIFFICULTY, DIFFICULTY_PRESETS


class BaseAgent:
    """人机代理基类。

    子类只需实现 :meth:`decide`；基类负责：
    * 按难度预设加载反应速度 / 寻路精度 / 推人欲望 / 逃生阈值；
    * 以"反应间隔"节流地刷新决策（难度越低，反应越慢）；
    * 对移动方向加入扰动（难度越低，寻路精度越差）；
    * 保证 ``push`` 请求在每次决策中只下发一次。
    """

    def __init__(self, name="人机", difficulty=AI_DIFFICULTY, seed=None):
        """构造代理。

        参数：
        * ``name``       —— 显示名；
        * ``difficulty`` —— "easy" / "normal" / "hard"；
        * ``seed``       —— 随机种子（便于复现行为）。
        """
        self.name = name
        self.difficulty = difficulty if difficulty in DIFFICULTY_PRESETS else AI_DIFFICULTY
        preset = DIFFICULTY_PRESETS[self.difficulty]
        self.reaction = preset["reaction"]          # 反应间隔（秒）
        self.precision = preset["precision"]        # 寻路精度 0~1
        self.aggression = preset["aggression"]      # 推人欲望 0~1
        self.escape_time = preset["escape_time"]    # 逃生阈值（秒）

        self.rng = random.Random(seed)
        self.state = "idle"                         # 当前行为状态（供调试）
        self._timer = 0.0                           # 距下次决策的剩余时间
        self._decision = {"move": (0.0, 0.0), "push": False}
        self._push_fired = True                     # 本轮决策的 push 是否已下发

    # ============================================================ 对外接口
    def think(self, obs, dt):
        """每帧调用：节流刷新决策并返回本帧指令（见模块文档）。"""
        self._timer -= dt
        if self._timer <= 0.0:
            self._timer = self.reaction * self.rng.uniform(0.8, 1.2)
            decision = self.decide(obs) or {}
            move = decision.get("move", (0.0, 0.0))
            try:
                move = (float(move[0]), float(move[1]))
            except (TypeError, ValueError, IndexError):
                move = (0.0, 0.0)
            self._decision = {
                "move": self.add_noise(move),
                "push": bool(decision.get("push", False)),
            }
            self._push_fired = False

        push = False
        if self._decision["push"] and not self._push_fired:
            push = True
            self._push_fired = True
        return {"move": self._decision["move"], "push": push}

    def decide(self, obs):
        """根据观测生成决策（子类实现）。

        返回 ``{"move": (dx, dy), "push": bool}``。
        """
        raise NotImplementedError("子类必须实现 decide()")

    # ============================================================ 通用工具
    def add_noise(self, move):
        """按寻路精度对移动方向加入扰动（低难度 AI 会走歪 / 绕路）。"""
        mx, my = move
        if abs(mx) < 1e-6 and abs(my) < 1e-6:
            return (mx, my)
        miss = 1.0 - self.precision
        if miss <= 0.0:
            return (mx, my)
        roll = self.rng.random()
        if roll < miss * 0.30:
            return (-my, mx)                    # 逆时针偏 90°
        if roll < miss * 0.50:
            return (my, -mx)                    # 顺时针偏 90°
        if roll < miss * 0.58:
            return (0.0, 0.0)                   # 短暂发呆
        return (mx, my)

    @staticmethod
    def is_safe_cell(grid, cell, target):
        """格坐标 ``cell`` 是否为（等于目标图案的）安全格。"""
        col, row = int(cell[0]), int(cell[1])
        if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
            return grid[row][col] == target
        return False

    @staticmethod
    def find_safe_cells(grid, target):
        """列出全图所有安全格坐标。"""
        cells = []
        for row, line in enumerate(grid):
            for col, pattern in enumerate(line):
                if pattern == target:
                    cells.append((col, row))
        return cells
