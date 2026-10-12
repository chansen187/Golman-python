"""视觉特效系统：粒子、光环、飘字、横幅、屏幕震动与格子碎裂。

本模块只负责"好看"，不参与任何游戏规则计算。全部特效按渲染帧
（60 FPS）更新，与 20 Hz 的逻辑帧互不干扰。

坐标系：与游戏区一致（像素，原点在游戏区左上角）；绘制时统一
叠加屏幕震动偏移与 HUD 高度偏移。
"""

import math
import random

import pygame

from config import CELL_SIZE, HUD_HEIGHT, PATTERN_COLORS, WINDOW_WIDTH
from ui.render import load_font


class Effects:
    """特效管理器：所有子特效的创建、推进与分层绘制。"""

    def __init__(self, rng=None):
        """构造空的特效系统。``rng`` 可注入固定种子用于测试。"""
        self.rng = rng if rng is not None else random.Random()
        self.particles = []          # 粒子（迸发 / 碎屑）
        self.rings = []              # 扩散光环（重生 / 死亡 / 被推）
        self.floaters = []           # 飘字（+1 / -1 / 淘汰）
        self.banners = []            # 屏幕中央横幅（回合开始 / 区域塌陷）
        self.fades = []              # 格子碎裂淡出块
        self._shake_time = 0.0       # 屏幕震动剩余时间
        self._shake_duration = 0.0   # 本次震动的总时长（用于衰减）
        self._shake_strength = 0.0   # 屏幕震动强度（像素）
        self._block_surface = None   # 懒创建的共享色块 surface（淡出用）

    # ============================================================ 触发接口
    def burst(self, x, y, color, count=14, speed=(40, 200), life=0.55,
              size_range=(2, 4)):
        """在 ``(x, y)`` 迸发一簇粒子（爆炸 / 死亡 / 被推 / 碎屑）。

        参数：``count`` 粒子数、``speed`` 初速范围（像素/秒）、
        ``life`` 基础寿命（秒）、``size_range`` 粒子边长范围（像素）。
        """
        for _ in range(count):
            angle = self.rng.uniform(0.0, math.tau)
            velocity = self.rng.uniform(speed[0], speed[1])
            span = life * self.rng.uniform(0.6, 1.2)
            self.particles.append({
                "x": x, "y": y,
                "vx": math.cos(angle) * velocity,
                "vy": math.sin(angle) * velocity - 30.0,
                "life": span, "max_life": span,
                "size": self.rng.uniform(size_range[0], size_range[1]),
                "color": color,
                "gravity": 260.0,
            })

    def ring(self, x, y, color, radius=28, life=0.35):
        """扩散光环（重生 / 被推 / 死亡）。"""
        self.rings.append({"x": x, "y": y, "color": color,
                           "radius": radius, "life": life, "max_life": life})

    def floating_text(self, x, y, text, color, life=0.9, size=16):
        """飘字（+1 / -1 / 淘汰），从 ``(x, y)`` 向上飘散。"""
        self.floaters.append({"x": x, "y": y, "text": text, "color": color,
                              "life": life, "max_life": life, "size": size})

    def banner(self, text, color, life=1.0, size=30):
        """屏幕中央横幅（同时最多保留最近两条）。"""
        self.banners.append({"text": text, "color": color,
                             "life": life, "max_life": life, "size": size})
        self.banners = self.banners[-2:]

    def cell_break(self, col, row, pattern):
        """格子碎裂：淡出块 + 少量图案色碎屑。

        ``pattern`` 为图案名（"x"/"o"/"square"/"triangle"）或颜色元组。
        """
        if isinstance(pattern, str):
            color = PATTERN_COLORS.get(pattern, (200, 200, 200))
        else:
            color = pattern
        rect = pygame.Rect(col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        life = 0.45
        self.fades.append({"rect": rect, "color": color,
                           "life": life, "max_life": life})
        if len(self.fades) > 220:                       # 保险：限制总量
            self.fades = self.fades[-220:]
        if self.rng.random() < 0.4 and len(self.particles) < 600:
            cx, cy = rect.center
            self.burst(cx, cy, color, count=self.rng.randint(2, 3),
                       speed=(20, 90), life=0.5, size_range=(2, 3))

    def shake(self, strength=4.0, duration=0.18):
        """触发屏幕震动（强度 / 时长取当前与新值的最大者）。"""
        self._shake_strength = max(self._shake_strength, float(strength))
        self._shake_duration = max(self._shake_duration, float(duration))
        self._shake_time = max(self._shake_time, float(duration))

    # ============================================================ 更新
    def update(self, dt, text_only=False):
        """按渲染帧推进全部特效（``dt`` 为真实帧间隔，秒）。

        ``text_only=True`` 时只推进文字类特效（飘字 / 横幅）让提示自然
        淡出，而粒子、光环等世界特效保持定格——用于暂停 / 窗口未激活时。
        """
        if text_only:
            for f in self.floaters:
                f["life"] -= dt
                f["y"] -= 26.0 * dt
            self.floaters = [f for f in self.floaters if f["life"] > 0.0]
            for item in self.banners:
                item["life"] -= dt
            self.banners = [b for b in self.banners if b["life"] > 0.0]
            return

        # 粒子：重力 + 位移 + 生命
        alive = []
        for p in self.particles:
            p["life"] -= dt
            if p["life"] <= 0.0:
                continue
            p["vy"] += p["gravity"] * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            alive.append(p)
        self.particles = alive

        # 飘字：向上漂浮
        for f in self.floaters:
            f["life"] -= dt
            f["y"] -= 26.0 * dt
        self.floaters = [f for f in self.floaters if f["life"] > 0.0]

        # 光环 / 横幅 / 淡出块：仅倒计时
        for group in (self.rings, self.banners, self.fades):
            for item in group:
                item["life"] -= dt
            group[:] = [item for item in group if item["life"] > 0.0]

        # 震动衰减
        if self._shake_time > 0.0:
            self._shake_time = max(0.0, self._shake_time - dt)
            if self._shake_time <= 0.0:
                self._shake_strength = 0.0

    def shake_offset(self):
        """返回当前帧的屏幕震动偏移 ``(dx, dy)``（像素）。"""
        if self._shake_time <= 0.0 or self._shake_strength <= 0.0:
            return (0, 0)
        decay = self._shake_time / max(1e-6, self._shake_duration)
        strength = self._shake_strength * decay
        return (int(self.rng.uniform(-strength, strength)),
                int(self.rng.uniform(-strength, strength)))

    # ============================================================ 绘制
    def _screen_pos(self, x, y, offset):
        """世界坐标 + 震动偏移 → 屏幕坐标。"""
        return (int(x + offset[0]), int(y + HUD_HEIGHT + offset[1]))

    def draw_fades(self, surface, offset):
        """绘制格子碎裂淡出块（在地图之后、单位之前调用）。"""
        if not self.fades:
            return
        if self._block_surface is None:
            self._block_surface = pygame.Surface(
                (CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
        ox, oy = offset
        for item in self.fades:
            ratio = max(0.0, item["life"] / item["max_life"])
            alpha = int(150 * ratio)
            color = item["color"]
            self._block_surface.fill((color[0], color[1], color[2], alpha))
            rect = item["rect"]
            surface.blit(self._block_surface,
                         (rect.x + ox, rect.y + HUD_HEIGHT + oy))

    def draw_particles(self, surface, offset):
        """绘制粒子（尺寸随生命缩小、颜色随生命变暗）。"""
        for p in self.particles:
            ratio = max(0.0, p["life"] / p["max_life"])
            size = max(1, int(p["size"] * (0.4 + 0.6 * ratio)))
            color = (int(p["color"][0] * (0.35 + 0.65 * ratio)),
                     int(p["color"][1] * (0.35 + 0.65 * ratio)),
                     int(p["color"][2] * (0.35 + 0.65 * ratio)))
            x, y = self._screen_pos(p["x"], p["y"], offset)
            pygame.draw.rect(surface, color, (x, y, size, size))

    def draw_rings(self, surface, offset):
        """绘制扩散光环（半径随时间扩散、颜色随时间变暗）。"""
        for item in self.rings:
            ratio = max(0.0, item["life"] / item["max_life"])
            radius = int(item["radius"] * (1.05 - ratio))
            if radius < 2:
                continue
            color = tuple(int(c * ratio) for c in item["color"])
            pygame.draw.circle(surface, color,
                               self._screen_pos(item["x"], item["y"], offset),
                               radius, 2)

    def draw_floaters(self, surface, offset):
        """绘制飘字（渐隐）。"""
        for item in self.floaters:
            ratio = max(0.0, item["life"] / item["max_life"])
            font = load_font(item["size"], bold=True)
            text = font.render(item["text"], True, item["color"])
            text.set_alpha(int(255 * min(1.0, ratio * 1.6)))
            rect = text.get_rect(
                center=self._screen_pos(item["x"], item["y"], offset))
            surface.blit(text, rect)

    def draw_banner(self, surface):
        """绘制屏幕中央横幅（不随震动移动）。"""
        for index, item in enumerate(self.banners):
            ratio = max(0.0, item["life"] / item["max_life"])
            font = load_font(item["size"], bold=True)
            text = font.render(item["text"], True, item["color"])
            text.set_alpha(int(255 * min(1.0, ratio * 2.2)))
            rect = text.get_rect(
                center=(WINDOW_WIDTH // 2, HUD_HEIGHT + 210 + index * 46))
            surface.blit(text, rect)
