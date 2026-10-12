"""回合管理模块：铺图、倒计时、结算（塌陷与死亡判定）、停顿与重生。

回合流程（状态机）：

1. ``countdown``    —— 新回合开始：重新随机铺满地图、随机目标图案、
   单位可自由移动与推人，HUD 倒计时 ``settings.round_time`` 秒；
2. 倒计时归零 (``_settle``) —— 只保留目标图案格、其余变虚空，
   站在消失格上的单位立即死亡（掉命、下回合重生；死亡不扣分），
   存活单位 +1 分（唯一的加分来源）；随后进入 ``intermission``；
3. ``intermission`` —— 约 1 秒停顿（播放碎裂 / 死亡动画），结束后回到 1。
"""

import random

from config import (COLOR_TEAM, PATTERN_COLORS, PATTERN_GLYPHS, PATTERNS,
                    ROUND_PAUSE, SURVIVE_SCORE)

# 回合阶段常量
PHASE_COUNTDOWN = "countdown"          # 倒计时进行中
PHASE_INTERMISSION = "intermission"    # 结算后的停顿


class RoundManager:
    """管理回合节奏与结算。

    本类直接持有 :class:`~core.grid.Grid` 与单位列表的引用，并在关键
    节点调用可选的 ``effects``（视觉特效）与 ``recorder``（对局记录）。
    """

    def __init__(self, grid, units, settings, effects=None, recorder=None, rng=None):
        """构造回合管理器（不会立即开始回合，需调用 :meth:`start`）。

        参数：
        * ``grid``     —— 地图网格；
        * ``units``    —— 全部单位列表；
        * ``settings`` —— :class:`config.GameSettings`（读取回合倒计时长度）；
        * ``effects``  —— 可选的 :class:`ui.effects.Effects`；
        * ``recorder`` —— 可选的 :class:`replay.recorder.Recorder`；
        * ``rng``      —— 随机数发生器（目标图案抽取 / 重生位置）。
        """
        self.grid = grid
        self.units = units
        self.settings = settings
        self.effects = effects
        self.recorder = recorder
        self.rng = rng if rng is not None else random.Random()

        self.phase = PHASE_COUNTDOWN
        self.round_index = 0            # 当前回合序号（从 1 开始）
        self.target = None              # 当前目标图案
        self.time_left = 0.0            # 倒计时剩余秒数
        self.pause_left = 0.0           # 停顿剩余秒数
        self.elapsed = 0.0              # 本局已进行时间（秒）

    # ============================================================ 流程控制
    def start(self):
        """开始第一回合（重置局内计时与回合序号）。"""
        self.elapsed = 0.0
        self.round_index = 0
        self._start_round()

    def _start_round(self):
        """开始新回合：铺图、抽目标、重置倒计时、重生等待中的单位。"""
        self.round_index += 1
        self.grid.randomize()
        self.target = self.rng.choice(PATTERNS)
        self.time_left = float(self.settings.round_time)
        self.pause_left = 0.0
        self.phase = PHASE_COUNTDOWN

        self._respawn_units()

        if self.recorder is not None:
            self.recorder.start_round(self.round_index, self.target, self.grid.cells)
        if self.effects is not None:
            self.effects.banner(
                "第 %d 回合 · 目标 %s" % (self.round_index, PATTERN_GLYPHS[self.target]),
                self._target_color(), life=0.9, size=30)

    def update(self, dt):
        """推进一个逻辑帧（20 Hz）：倒计时或停顿计时。"""
        self.elapsed += dt
        if self.phase == PHASE_COUNTDOWN:
            self.time_left -= dt
            if self.time_left <= 0.0:
                self.time_left = 0.0
                self._settle()
        elif self.phase == PHASE_INTERMISSION:
            self.pause_left -= dt
            if self.pause_left <= 0.0:
                self._start_round()

    # ============================================================ 结算
    def _settle(self):
        """倒计时结束的结算：

        1. 移除全部非目标图案格（变虚空）并播放碎裂动画；
        2. 站在消失格上的单位死亡，其余在场单位存活 +1 分；
        3. 进入约 1 秒的停顿，之后由 :meth:`update` 开启新回合。
        """
        removed = self.grid.remove_except(self.target)
        if self.effects is not None:
            for col, row, pattern in removed:
                self.effects.cell_break(col, row, pattern)
            self.effects.shake(3.5, 0.22)
            self.effects.banner("区域塌陷！", (255, 120, 120), life=0.9, size=34)

        for unit in self.units:
            if not unit.in_play():
                continue
            col, row = unit.cell()
            if self.grid.matches(col, row, self.target):
                # 站在目标图案格上 → 存活，+1 分
                unit.score += SURVIVE_SCORE
                if self.effects is not None:
                    self.effects.floating_text(unit.px, unit.py - 24,
                                               "+%d" % SURVIVE_SCORE, (120, 235, 140))
            else:
                self._kill(unit)

        self.phase = PHASE_INTERMISSION
        self.pause_left = ROUND_PAUSE
        if self.recorder is not None:
            self.recorder.round_end(self.round_index, self._snapshot())

    def _kill(self, unit):
        """击杀一个单位：掉一条命（不扣分）；命尽则淘汰，否则等待下回合重生。"""
        unit.lives -= 1
        unit.deaths += 1
        unit.reset_for_death()

        color = COLOR_TEAM.get(unit.team, (200, 200, 200))
        if self.effects is not None:
            self.effects.burst(unit.px, unit.py, color, count=22, speed=(60, 260))
            self.effects.ring(unit.px, unit.py, color, radius=30, life=0.4)
            self.effects.floating_text(unit.px, unit.py - 26,
                                       "阵亡", (255, 120, 120))

        if unit.lives <= 0:
            unit.eliminated = True
            unit.respawn = False
            if self.effects is not None:
                self.effects.burst(unit.px, unit.py, color, count=34, speed=(80, 320))
                self.effects.floating_text(unit.px, unit.py - 46, "淘汰", (255, 160, 160))
        else:
            unit.respawn = True
            unit.prev_px, unit.prev_py = unit.px, unit.py

        if self.recorder is not None:
            self.recorder.log("death", unit=unit.name, lives=unit.lives,
                              eliminated=unit.eliminated, pos=unit.cell(),
                              score=unit.score)

    # ============================================================ 重生
    def _respawn_units(self):
        """在新回合铺图后，把所有等待重生的单位放到随机空格。"""
        occupied = {u.cell() for u in self.units if u.in_play()}
        for unit in self.units:
            if not unit.respawn:
                continue
            col, row = self.grid.random_free_cell(occupied)
            occupied.add((col, row))
            unit.respawn_at(col, row)
            unit.respawn = False
            if self.effects is not None:
                self.effects.ring(unit.px, unit.py,
                                  COLOR_TEAM.get(unit.team, (200, 200, 200)),
                                  radius=26, life=0.45)
            if self.recorder is not None:
                self.recorder.log("respawn", unit=unit.name, pos=(col, row))

    # ============================================================ 杂项
    def _target_color(self):
        """当前目标图案的颜色（供横幅配色）。"""
        return PATTERN_COLORS.get(self.target, (255, 255, 255))

    def _snapshot(self):
        """所有单位的分数 / 生命快照（供录制）。"""
        return [
            {"name": u.name, "score": u.score, "lives": u.lives,
             "eliminated": u.eliminated}
            for u in self.units
        ]
