"""游戏区渲染：格子、图案、单位与字体工具。

绘制层次（由场景 main.py 组织，自下而上）：

1. 窗口底色
2. 地图格子与图案（:meth:`Renderer.draw_board`）
3. 格子碎裂淡出（``Effects.draw_fades``）
4. 粒子 / 光环（``Effects``）
5. 单位（:meth:`Renderer.draw_units`）
6. 飘字（``Effects``）
7. HUD（``ui.hud.Hud``）
8. 中央横幅（``Effects``）
"""

import math

import pygame

from config import (CELL_SIZE, COLOR_CELL_BG, COLOR_CELL_EDGE, COLOR_TEAM,
                    COLOR_VOID, PATTERN_COLORS, PATTERNS, PUSH_ANIM_TIME,
                    PUSH_COOLDOWN, PUSH_READY_FLASH)

_FONT_CACHE = {}


def load_font(size, bold=False):
    """加载支持中文的字体（带缓存）。

    优先使用微软雅黑 / 黑体 / 宋体等常见中文字体；均未找到时退回
    pygame 内置字体（此时中文会显示为方块，说明系统缺少中文字体）。
    """
    key = (int(size), bool(bold))
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    font = None
    for name in ("microsoftyahei", "microsoftyaheiui", "msyh", "simhei",
                 "simsun", "notosanscjksc", "arialunicodems"):
        path = pygame.font.match_font(name, bold=bold)
        if not path:
            continue
        try:
            font = pygame.font.Font(path, int(size))
            break
        except OSError:
            font = None
    if font is None:
        font = pygame.font.Font(None, int(size))
    _FONT_CACHE[key] = font
    return font


def draw_pattern(surface, pattern, rect, color, width=3):
    """在 ``rect`` 内绘制指定图案（几何绘制，无需字体支持）。

    * ``x``       → 交叉线；
    * ``o``      → 圆环；
    * ``square`` → 方框；
    * ``triangle`` → 三角形。
    """
    if pattern is None:
        return
    inset = max(6, rect.w // 5)                 # 40px 格 → 内缩 8px
    x0, y0 = rect.x + inset, rect.y + inset
    x1, y1 = rect.right - inset, rect.bottom - inset
    if pattern == "x":
        pygame.draw.line(surface, color, (x0, y0), (x1, y1), width)
        pygame.draw.line(surface, color, (x1, y0), (x0, y1), width)
    elif pattern == "o":
        radius = max(4, (x1 - x0) // 2)
        pygame.draw.circle(surface, color, rect.center, radius, width)
    elif pattern == "square":
        pygame.draw.rect(surface, color,
                         pygame.Rect(x0, y0, x1 - x0, y1 - y0),
                         width, border_radius=3)
    elif pattern == "triangle":
        mid_x = (x0 + x1) // 2
        pygame.draw.polygon(surface, color,
                            [(mid_x, y0), (x1, y1), (x0, y1)], width)


def draw_ring_progress(surface, center, radius, frac, color, width=2,
                       segments=48):
    """在圆周上绘制一段"进度弧"（用作单位圆外侧的冷却圆环进度条）。

    * ``center`` / ``radius`` —— 圆心与半径（像素）；
    * ``frac``   —— 0~1，自 12 点钟方向**顺时针**填充的比例；
    * 由多段短线段拼接而成，避免 ``pygame.draw.arc`` 的端点与浮点问题。
    """
    frac = max(0.0, min(1.0, float(frac)))
    if frac <= 0.0 or radius <= 1.0:
        return
    if frac >= 0.999:
        # 满环直接用圆绘制，更圆滑
        pygame.draw.circle(surface, color, center, int(radius), width)
        return
    count = max(3, int(segments * frac) + 1)
    total_angle = math.tau * frac
    start = -math.pi / 2                      # 12 点钟方向
    points = []
    for index in range(count + 1):
        angle = start + total_angle * index / count
        points.append((center[0] + math.cos(angle) * radius,
                       center[1] + math.sin(angle) * radius))
    pygame.draw.lines(surface, color, False, points, width)


class Renderer:
    """游戏区渲染器：负责地图格子与单位。"""

    def __init__(self, grid_size, cell_size, hud_height):
        """构造渲染器。

        * ``grid_size`` / ``cell_size`` —— 地图规模（13×13、每格 40px）；
        * ``hud_height`` —— 顶部 HUD 高度（游戏区整体下移该像素数）。
        """
        self.grid_size = grid_size
        self.cell_size = cell_size
        self.hud_height = hud_height
        self.board_px = grid_size * cell_size
        # 预生成半透明底色块（按图案着色，提升每帧绘制性能）
        self.cell_tints = {
            pat: self._make_tint(PATTERN_COLORS[pat], 26) for pat in PATTERNS
        }
        self.highlight_tints = {
            pat: self._make_tint(PATTERN_COLORS[pat], 55) for pat in PATTERNS
        }

    # ============================================================ 内部工具
    def _make_tint(self, color, alpha):
        """生成一张单色半透明色块（尺寸 = 单格）。"""
        surf = pygame.Surface((self.cell_size, self.cell_size), pygame.SRCALPHA)
        surf.fill((color[0], color[1], color[2], alpha))
        return surf

    @staticmethod
    def bright(color, factor=1.35):
        """把颜色按比例调亮（上限 255）。"""
        return tuple(min(255, int(c * factor)) for c in color)

    # ============================================================ 地图
    def draw_board(self, surface, grid, target, pulse, offset):
        """绘制整张地图（正常格 / 虚空格 / 目标格高亮）。

        参数：
        * ``grid``   —— :class:`core.grid.Grid`；
        * ``target`` —— 当前目标图案（脉动高亮这些格子）；
        * ``pulse``  —— 0~1 的脉动值（高亮闪烁用）；
        * ``offset`` —— 屏幕震动偏移 ``(dx, dy)``。
        """
        ox, oy = offset
        top = self.hud_height + oy
        cell = self.cell_size
        size = self.grid_size

        if target is not None:
            # 目标格的高亮块透明度随脉动变化（所有目标格同步闪烁）
            self.highlight_tints[target].set_alpha(int(30 + pulse * 70))

        for row in range(size):
            for col in range(size):
                x = col * cell + ox
                y = row * cell + top
                rect = pygame.Rect(x, y, cell, cell)
                pattern = grid.pattern_at(col, row)
                if pattern is None:
                    # 虚空格：底色 + 极弱格线（保持网格感）
                    pygame.draw.rect(surface, COLOR_VOID, rect)
                    pygame.draw.rect(surface, (24, 28, 38), rect, 1)
                    continue
                pygame.draw.rect(surface, COLOR_CELL_BG, rect)
                surface.blit(self.cell_tints[pattern], (x, y))
                draw_pattern(surface, pattern, rect,
                             PATTERN_COLORS[pattern], 3)
                pygame.draw.rect(surface, COLOR_CELL_EDGE, rect, 1)
                if pattern == target:
                    surface.blit(self.highlight_tints[pattern], (x, y))
                    pygame.draw.rect(surface,
                                     self.bright(PATTERN_COLORS[pattern]),
                                     rect, 2)

        # 游戏区外框
        pygame.draw.rect(surface, COLOR_CELL_EDGE,
                         pygame.Rect(ox, top, self.board_px, self.board_px), 2)

    # ============================================================ 单位
    def draw_units(self, surface, units, alpha, time, offset):
        """绘制全部在场单位。

        * ``alpha`` —— 渲染插值系数（``逻辑累加器 / TICK_DT``，0~1），
          在上一逻辑帧与当前逻辑帧位置之间平滑过渡；
        * ``time``  —— 渲染累计时间（眩晕动画等使用）。
        """
        ox, oy = offset
        for unit in units:
            if not unit.in_play():
                continue
            x = unit.prev_px + (unit.px - unit.prev_px) * alpha
            y = unit.prev_py + (unit.py - unit.prev_py) * alpha
            if unit.shake > 0.0:                    # 推人动作震动
                x += math.sin(time * 72.0) * 2.4
                y += math.cos(time * 65.0) * 2.4
            self._draw_unit(surface, unit,
                            x + ox, y + self.hud_height + oy, time)

    def _draw_unit(self, surface, unit, x, y, time):
        """绘制单个单位：圆形本体 + 朝向指针 + 推人冷却环 + 状态标记。"""
        radius = unit.radius
        color = COLOR_TEAM.get(unit.team, (200, 200, 200))
        center = (int(x), int(y))
        # 底部阴影
        pygame.draw.circle(surface, (10, 12, 18), (int(x), int(y) + 2), radius + 1)
        # 主体与描边
        pygame.draw.circle(surface, color, center, radius)
        pygame.draw.circle(surface, self.bright(color, 0.6), center, radius, 2)
        # 被推白闪
        if unit.hit_flash > 0.0:
            pygame.draw.circle(surface, (255, 255, 255), center, radius + 2, 2)
        # 推人冷却环（圆形外侧）
        self._draw_push_ring(surface, unit, center, radius)
        # 朝向指示（从圆心伸向朝向的小箭头；推人时向外伸出）
        fx, fy = unit.facing
        angle = math.atan2(fy, fx)
        extend = 0.0
        if unit.push_anim > 0.0:
            # 伸出-收回：sin 曲线 0 → 1 → 0
            progress = 1.0 - unit.push_anim / PUSH_ANIM_TIME
            extend = math.sin(math.pi * progress) * 6.5
        base_x = x + math.cos(angle) * extend
        base_y = y + math.sin(angle) * extend
        tip = (base_x + math.cos(angle) * (radius + 4),
               base_y + math.sin(angle) * (radius + 4))
        left = (base_x + math.cos(angle + 2.6) * radius * 0.62,
                base_y + math.sin(angle + 2.6) * radius * 0.62)
        right = (base_x + math.cos(angle - 2.6) * radius * 0.62,
                 base_y + math.sin(angle - 2.6) * radius * 0.62)
        pygame.draw.polygon(surface, (245, 248, 255), (tip, left, right))
        # 眩晕：头顶环绕的小圆点（旋转动画）
        if unit.stunned:
            for i in range(3):
                orbit = time * 6.5 + i * 2.094
                sx = x + math.cos(orbit) * 10.0
                sy = y - radius - 9 + math.sin(orbit) * 3.0
                pygame.draw.circle(surface, (255, 255, 255), (int(sx), int(sy)), 2)

    @staticmethod
    def _draw_push_ring(surface, unit, center, radius):
        """绘制推人冷却圆环（位于单位圆形外侧）。

        * 冷却中：暗色轨道 + 冰蓝色进度弧（自 12 点钟顺时针充满）；
        * 冷却完成：满环一闪（约 0.45 秒内淡出）表示技能就绪；
        * 就绪且闪现结束后不绘制圆环。
        """
        ring_radius = radius + 3
        if unit.push_timer > 0.0:
            progress = 1.0 - unit.push_timer / PUSH_COOLDOWN
            pygame.draw.circle(surface, (58, 66, 84), center,
                               ring_radius, 2)
            draw_ring_progress(surface, center, ring_radius, progress,
                               (120, 210, 255), 2)
        elif unit.ready_flash > 0.0:
            ratio = unit.ready_flash / PUSH_READY_FLASH
            color = (int(120 * ratio), int(210 * ratio), int(255 * ratio))
            draw_ring_progress(surface, center, ring_radius, 1.0, color, 2)
