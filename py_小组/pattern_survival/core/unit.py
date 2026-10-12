"""单位模块：位置、朝向、生命、眩晕、冷却、击退与碰撞移动。"""

import math

from config import (CELL_SIZE, MOVE_SPEED, PUSH_ANIM_TIME, PUSH_COOLDOWN,
                    PUSH_READY_FLASH, PUSH_SLIDE_TIME, UNIT_RADIUS)

_TIMER_EPS = 1e-9          # 计时器浮点残值阈值（小于该值一律视为 0）


def _decay(value, dt):
    """把计时器递减 ``dt``，并把浮点残值（< 1e-9）钳制为 0。

    逐帧累减 0.05 这类非精确二进制小数会在多帧后留下 ±1e-17 量级的
    残值，若不钳制会导致"眩晕/冷却已到点但状态仍判定为进行中"。
    """
    value -= dt
    return value if value > _TIMER_EPS else 0.0


class Unit:
    """场上单位（玩家或人机）。

    单位使用连续像素坐标移动（速度 ``MOVE_SPEED`` 格/秒），拥有圆形碰撞
    体积（半径 ``UNIT_RADIUS`` 像素），彼此不可重叠、不可越出地图边界。

    生命周期字段：
    * ``lives``      —— 剩余生命数，归零即被淘汰（``eliminated``）；
    * ``respawn``    —— 本回合已死亡、等待下回合在随机位置重生；
    * ``in_play()``  —— 是否当前在场（既未淘汰、也未等待重生）。
    """

    def __init__(self, uid, team, name, col, row, lives, cell_size=CELL_SIZE,
                 is_human=False, is_ai=False):
        """在格 ``(col, row)`` 的中心创建一个单位。

        参数：
        * ``uid``    —— 唯一编号
        * ``team``   —— 阵营："red" / "blue" / "ai"
        * ``name``   —— 显示名称（如"红方""人机 1"）
        * ``lives``  —— 初始生命数
        """
        self.uid = uid
        self.team = team
        self.name = name
        self.is_human = is_human
        self.is_ai = is_ai
        self.cell_size = cell_size
        self.radius = UNIT_RADIUS
        self.speed = MOVE_SPEED

        half = cell_size / 2.0
        self.px = col * cell_size + half       # 中心像素坐标（世界坐标）
        self.py = row * cell_size + half
        self.prev_px = self.px                 # 上一逻辑帧位置（渲染插值用）
        self.prev_py = self.py

        self.facing = (0, 1)                   # 面朝方向（四向之一），默认朝下
        self.stun_timer = 0.0                  # 眩晕剩余时间（秒）
        self.push_timer = 0.0                  # 推人冷却剩余时间（秒）
        self.hit_flash = 0.0                   # 被推白闪计时（纯视觉）
        self.shake = 0.0                       # 推人动作震动计时（纯视觉）
        self.push_anim = 0.0                   # 推人时朝向指针伸出动画计时（纯视觉）
        self.ready_flash = 0.0                 # 冷却结束满环闪现计时（纯视觉）
        self.knock = None                      # 击退滑动状态（见 start_knock）

        self.lives = lives
        self.score = 0
        self.deaths = 0
        self.eliminated = False                # 生命耗尽，永久离场
        self.respawn = False                   # 等待下回合重生

    # ============================================================ 状态属性
    @property
    def stunned(self):
        """是否处于眩晕（眩晕期间不能移动、不能推人）。"""
        return self.stun_timer > 0.0

    @property
    def push_ready(self):
        """当前是否可发起推人（在场、未冷却、未眩晕、未处于击退中）。"""
        return (self.in_play() and self.push_timer <= 0.0
                and not self.stunned and self.knock is None)

    def in_play(self):
        """是否当前在场（既未淘汰、也未等待重生）。"""
        return (not self.eliminated) and (not self.respawn)

    def cell(self):
        """所在整数格坐标。"""
        return (int(self.px // self.cell_size), int(self.py // self.cell_size))

    def fcell(self):
        """浮点格坐标（供 AI 观测与推人判定使用）。"""
        return (self.px / self.cell_size, self.py / self.cell_size)

    # ============================================================ 状态操作
    def face(self, dx, dy):
        """根据方向更新面朝方向（取主导轴，结果始终为四向之一）。"""
        if dx == 0.0 and dy == 0.0:
            return
        if abs(dx) >= abs(dy):
            self.facing = (1 if dx > 0 else -1, 0)
        else:
            self.facing = (0, 1 if dy > 0 else -1)

    def set_stun(self, seconds):
        """施加眩晕（取较长的剩余时间，不叠加）。"""
        self.stun_timer = max(self.stun_timer, float(seconds))

    def note_push_used(self):
        """记录一次推人动作：进入冷却（圆环开始充能）并触发推人动画。

        动画包含：身体短促震动 + 朝向指针向外伸出（表示"推"的动作）。
        """
        self.push_timer = PUSH_COOLDOWN
        self.ready_flash = 0.0
        self.shake = 0.16
        self.push_anim = PUSH_ANIM_TIME

    def start_knock(self, tx, ty):
        """开始一段击退滑动动画：从当前位置滑向目标像素点。

        滑动在 ``PUSH_SLIDE_TIME``（默认 0.2 秒）内以 ease-out 曲线完成，
        期间单位不可自主移动（眩晕覆盖整个滑动过程）。
        """
        self.knock = {
            "sx": self.px, "sy": self.py,
            "tx": tx, "ty": ty,
            "t": 0.0, "dur": PUSH_SLIDE_TIME,
        }

    def respawn_at(self, col, row):
        """在指定格重生：落位到格中心并清除全部临时状态。"""
        half = self.cell_size / 2.0
        self.px = col * self.cell_size + half
        self.py = row * self.cell_size + half
        self.prev_px, self.prev_py = self.px, self.py
        self._clear_temp()

    def reset_for_death(self):
        """死亡清理：清空眩晕 / 冷却 / 击退等临时状态。"""
        self._clear_temp()

    def _clear_temp(self):
        """清除全部临时（非持久）状态。"""
        self.stun_timer = 0.0
        self.push_timer = 0.0
        self.hit_flash = 0.0
        self.shake = 0.0
        self.push_anim = 0.0
        self.ready_flash = 0.0
        self.knock = None

    # ============================================================ 逐帧推进
    def begin_tick(self):
        """逻辑帧开始：记录当前位置，供渲染插值使用。"""
        self.prev_px, self.prev_py = self.px, self.py

    def update(self, dt):
        """推进计时器与击退滑动（每个逻辑帧调用一次）。"""
        if self.stun_timer > 0.0:
            self.stun_timer = _decay(self.stun_timer, dt)
        if self.push_timer > 0.0:
            self.push_timer = _decay(self.push_timer, dt)
            if self.push_timer <= 0.0:
                self.ready_flash = PUSH_READY_FLASH   # 冷却完成：满环闪现
        if self.ready_flash > 0.0:
            self.ready_flash = _decay(self.ready_flash, dt)
        if self.hit_flash > 0.0:
            self.hit_flash = _decay(self.hit_flash, dt)
        if self.shake > 0.0:
            self.shake = _decay(self.shake, dt)
        if self.push_anim > 0.0:
            self.push_anim = _decay(self.push_anim, dt)

        knock = self.knock
        if knock is not None:
            knock["t"] += dt
            ratio = knock["t"] / knock["dur"]
            if ratio >= 1.0:
                self.px, self.py = knock["tx"], knock["ty"]
                self.knock = None
            else:
                ease = 1.0 - (1.0 - ratio) ** 3        # ease-out cubic
                self.px = knock["sx"] + (knock["tx"] - knock["sx"]) * ease
                self.py = knock["sy"] + (knock["ty"] - knock["sy"]) * ease

    # ============================================================ 移动
    def apply_move(self, vec, dt, units, board_w, board_h):
        """按方向向量移动单位。

        * ``vec``：期望移动方向 ``(dx, dy)``；长度 ≤ 1 时按比例降速（供
          AI 微调 / 转向用），长度 > 1 时归一化为全速；
        * 无论是否产生位移，只要输入非零就更新朝向（原地也能转身）；
        * 分轴解算 + 圆形碰撞：与其他在场单位的最小间距为
          ``2 * UNIT_RADIUS``，且不允许越出地图边界。

        返回是否产生了实际位移。
        """
        if not self.in_play() or self.stunned or self.knock is not None:
            return False
        dx, dy = float(vec[0]), float(vec[1])
        if dx == 0.0 and dy == 0.0:
            return False
        self.face(dx, dy)                          # 转向与位移互相独立

        length = math.hypot(dx, dy)
        if length > 1.0:
            dx, dy = dx / length, dy / length
        step = self.speed * self.cell_size * dt    # 本帧最大位移（像素）
        vx, vy = dx * step, dy * step

        moved = False
        nx = self.px + vx
        if not self._blocked(nx, self.py, units, board_w, board_h):
            self.px = nx
            moved = True
        ny = self.py + vy
        if not self._blocked(self.px, ny, units, board_w, board_h):
            self.py = ny
            moved = True
        return moved

    def _blocked(self, nx, ny, units, board_w, board_h):
        """检测位置 ``(nx, ny)`` 是否被地图边界或其他单位阻挡。"""
        r = self.radius
        if nx < r or ny < r or nx > board_w - r or ny > board_h - r:
            return True
        min_dist_sq = (2.0 * r) ** 2
        for other in units:
            if other is self or not other.in_play():
                continue
            ddx = other.px - nx
            ddy = other.py - ny
            if ddx * ddx + ddy * ddy < min_dist_sq:
                return True
        return False
