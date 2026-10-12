"""顶部 HUD：双方比分、目标图案（高亮闪烁）与大号倒计时。

布局（总高 100 像素）：

* 顶部细行：左"第 N 回合"、右"已进行时长"（对局无时间限制）；
* 左右两侧：红 / 蓝比分（大号数字）与剩余生命点；
* 中央：当前目标图案（脉动闪烁）+ 大号倒计时数字 + 倒计时进度条。
"""

import pygame

from config import (COLOR_HUD_BG, COLOR_HUD_LINE, COLOR_TEXT, COLOR_TEXT_DIM,
                    COLOR_TEAM, COLOR_WARN, HUD_HEIGHT, PATTERN_COLORS,
                    TEAM_NAMES, WINDOW_WIDTH)
from ui.render import draw_pattern, load_font


class Hud:
    """顶部信息栏。"""

    def __init__(self, width=WINDOW_WIDTH, height=HUD_HEIGHT):
        """构造 HUD（字体在构造时一次性加载并缓存）。"""
        self.width = width
        self.height = height
        self.font_small = load_font(13)
        self.font_label = load_font(15)
        self.font_score = load_font(34, bold=True)
        self.font_count = load_font(27, bold=True)

    # ============================================================ 入口
    def draw(self, surface, state):
        """绘制 HUD。

        ``state`` 需要包含：
        ``red_score`` / ``blue_score`` / ``red_lives`` / ``blue_lives`` /
        ``target`` / ``time_left`` / ``round_time`` / ``round_index`` /
        ``elapsed``（已进行秒数）/ ``pulse``。
        """
        # 面板背景与底部发丝线
        pygame.draw.rect(surface, COLOR_HUD_BG, (0, 0, self.width, self.height))
        pygame.draw.line(surface, COLOR_HUD_LINE,
                         (0, self.height - 1), (self.width, self.height - 1), 2)

        # 顶部细行
        small = self.font_small
        round_txt = small.render("第 %d 回合" % state["round_index"],
                                 True, COLOR_TEXT_DIM)
        surface.blit(round_txt, (14, 8))
        elapsed = max(0, int(state["elapsed"]))
        time_txt = small.render("已进行 %d:%02d" % (elapsed // 60, elapsed % 60),
                                True, COLOR_TEXT_DIM)
        surface.blit(time_txt, (self.width - time_txt.get_width() - 14, 8))

        # 左右比分块
        self._draw_side(surface, 16, "red",
                        state["red_score"], state["red_lives"], True)
        self._draw_side(surface, self.width - 16, "blue",
                        state["blue_score"], state["blue_lives"], False)

        # 中央目标图案 + 倒计时
        self._draw_center(surface, state)

    # ============================================================ 分区绘制
    def _draw_side(self, surface, x, team, score, lives, align_left):
        """绘制一侧的比分、阵营名与剩余生命点。"""
        color = COLOR_TEAM.get(team, (200, 200, 200))
        label = self.font_label.render(TEAM_NAMES.get(team, team), True,
                                       COLOR_TEXT_DIM)
        score_txt = self.font_score.render(str(score), True, color)
        if align_left:
            surface.blit(label, (x, 28))
            surface.blit(score_txt, (x, 46))
            self._draw_lives(surface, x, 90, lives, color, True)
        else:
            surface.blit(label, (x - label.get_width(), 28))
            surface.blit(score_txt, (x - score_txt.get_width(), 46))
            self._draw_lives(surface, x, 90, lives, color, False)

    def _draw_lives(self, surface, x, y, lives, color, align_left):
        """绘制剩余生命点（实心圆 × 剩余数，最多显示 9 个）。"""
        for i in range(max(0, min(9, int(lives)))):
            offset = 5 + i * 13
            cx = x + offset if align_left else x - offset
            pygame.draw.circle(surface, color, (cx, y), 4)

    def _draw_center(self, surface, state):
        """绘制中央目标图案（闪烁）、大号倒计时与进度条。"""
        center_x = self.width // 2
        target = state["target"]
        pulse = max(0.0, min(1.0, float(state.get("pulse", 1.0))))

        # 目标图案（亮度随脉动闪烁）
        if target is not None:
            base = PATTERN_COLORS.get(target, (255, 255, 255))
            flicker = tuple(int(c * (0.55 + 0.45 * pulse)) for c in base)
            icon = pygame.Rect(center_x - 16, 14, 32, 32)
            draw_pattern(surface, target, icon, flicker, 3)

        # 大号倒计时数字（低于 1.5 秒时红色快闪）
        time_left = max(0.0, float(state["time_left"]))
        warning = time_left <= 1.5
        blink_on = int(time_left * 8) % 2 == 0
        if warning and blink_on:
            count_color = COLOR_WARN
        elif warning:
            count_color = (255, 190, 190)
        else:
            count_color = COLOR_TEXT
        count_txt = self.font_count.render("%.1f" % time_left, True, count_color)
        surface.blit(count_txt, count_txt.get_rect(center=(center_x, 58)))

        # 倒计时进度条
        round_time = max(0.001, float(state["round_time"]))
        ratio = min(1.0, max(0.0, time_left / round_time))
        bar_bg = pygame.Rect(center_x - 70, 80, 140, 4)
        pygame.draw.rect(surface, (40, 47, 62), bar_bg, border_radius=2)
        width = int(bar_bg.width * ratio)
        if width > 0:
            if ratio > 0.5:
                bar_color = (86, 200, 120)
            elif ratio > 0.25:
                bar_color = (240, 190, 70)
            else:
                bar_color = (235, 90, 90)
            pygame.draw.rect(surface, bar_color,
                             pygame.Rect(bar_bg.x, bar_bg.y, width, bar_bg.height),
                             border_radius=2)
