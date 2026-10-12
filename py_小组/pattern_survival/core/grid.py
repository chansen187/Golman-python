"""格子地图模块：图案随机铺满、目标过滤（移除）与坐标换算。"""

import random

from config import CELL_SIZE, GRID_SIZE, PATTERNS


class Grid:
    """13×13 图案网格。

    每回合开始时 :meth:`randomize` 把全部格子重新随机铺满 ×、○、□、△
    四种图案；倒计时结束后 :meth:`remove_except` 只保留目标图案格，其余
    格子变为虚空（此时 :meth:`pattern_at` 返回 ``None``）。
    """

    def __init__(self, size=GRID_SIZE, cell_size=CELL_SIZE, rng=None):
        """构造网格并立即随机铺满一次。

        参数：
        * ``size``      —— 地图边长（格）
        * ``cell_size`` —— 单格边长（像素）
        * ``rng``       —— 随机数发生器（可注入固定种子用于测试）
        """
        self.size = size
        self.cell_size = cell_size
        self.rng = rng if rng is not None else random.Random()
        self.cells = [[PATTERNS[0] for _ in range(size)] for _ in range(size)]
        self.randomize()

    # ------------------------------------------------------------ 铺图
    def randomize(self):
        """重新随机铺满全部格子（每格在四种图案间均匀随机）。"""
        total = self.size * self.size
        flat = self.rng.choices(PATTERNS, k=total)
        self.cells = [
            flat[i * self.size:(i + 1) * self.size]
            for i in range(self.size)
        ]

    def remove_except(self, pattern):
        """把所有"非目标图案"的格子变为虚空。

        返回被移除的格子列表 ``[(col, row, pattern), ...]``，
        供渲染层播放淡出 / 碎裂动画。
        """
        removed = []
        for row in range(self.size):
            line = self.cells[row]
            for col in range(self.size):
                pat = line[col]
                if pat is not None and pat != pattern:
                    removed.append((col, row, pat))
                    line[col] = None
        return removed

    # ------------------------------------------------------------ 查询
    def in_bounds(self, col, row):
        """格坐标是否在地图内。"""
        return 0 <= col < self.size and 0 <= row < self.size

    def pattern_at(self, col, row):
        """返回格内图案；越界或虚空返回 ``None``。"""
        if not self.in_bounds(col, row):
            return None
        return self.cells[row][col]

    def matches(self, col, row, pattern):
        """格内图案是否等于 ``pattern``（虚空 / 越界一律为 False）。"""
        return self.pattern_at(col, row) == pattern

    def count(self, pattern):
        """统计某种图案的格子数（统计 / 调试用）。"""
        return sum(1 for line in self.cells for pat in line if pat == pattern)

    # ------------------------------------------------------------ 坐标换算
    def cell_center(self, col, row):
        """格中心的像素坐标（世界坐标系）。"""
        half = self.cell_size / 2.0
        return (col * self.cell_size + half, row * self.cell_size + half)

    def cell_from_px(self, x, y):
        """像素坐标 → 整数格坐标（越界时夹取到地图内）。"""
        col = int(x // self.cell_size)
        row = int(y // self.cell_size)
        col = max(0, min(self.size - 1, col))
        row = max(0, min(self.size - 1, row))
        return (col, row)

    def fcell_from_px(self, x, y):
        """像素坐标 → 浮点格坐标（供 AI 观测与推人判定）。"""
        return (x / self.cell_size, y / self.cell_size)

    # ------------------------------------------------------------ 随机位置
    def random_free_cell(self, occupied=None):
        """随机返回一个不在 ``occupied`` 集合中的格坐标（用于单位重生）。

        若所有格都被占用（几乎不可能发生），退化为随机返回任意格。
        """
        occupied = occupied or set()
        candidates = [
            (col, row)
            for row in range(self.size)
            for col in range(self.size)
            if (col, row) not in occupied
        ]
        if not candidates:
            candidates = [
                (col, row)
                for row in range(self.size)
                for col in range(self.size)
            ]
        return self.rng.choice(candidates)
