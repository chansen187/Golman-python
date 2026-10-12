"""《图案生存战》全局配置。

本模块集中管理窗口、网格、回合、单位、推人、AI 与配色等全部可调参数。
游戏内"游戏设置"界面会在运行时覆盖其中一部分参数（AI 数量、难度、
生命数、回合倒计时），这些经由 :class:`GameSettings` 传递。

坐标系约定：
* 世界坐标（像素）以游戏区左上角为原点；游戏区为
  ``GRID_SIZE * CELL_SIZE`` 的正方形，绘制时整体下移 ``HUD_HEIGHT``。
* 格坐标 ``(col, row)`` 为整数索引，范围为 ``0 ~ GRID_SIZE - 1``。
* 浮点格坐标（fcell）为像素坐标除以 ``CELL_SIZE``，供 AI 观测使用。
"""

from dataclasses import dataclass

import pygame

# ---------------------------------------------------------------- 网格与窗口
GRID_SIZE = 13                  # 地图边长（格）
CELL_SIZE = 40                  # 单格边长（像素）
HUD_HEIGHT = 100                # 顶部 HUD 高度（像素）

WINDOW_WIDTH = GRID_SIZE * CELL_SIZE                # 520
WINDOW_HEIGHT = HUD_HEIGHT + GRID_SIZE * CELL_SIZE  # 620
BOARD_PX = GRID_SIZE * CELL_SIZE                    # 游戏区边长（像素）
WINDOW_TITLE = "图案生存战 Pattern Survival"

# ---------------------------------------------------------------- 主循环
TICK_RATE = 20                  # 逻辑帧率（Hz）
FPS = 60                        # 渲染帧率
TICK_DT = 1.0 / TICK_RATE       # 单次逻辑步长（秒）

# ---------------------------------------------------------------- 回合与胜负
ROUND_TIME = 5.0                # HUD 目标图案倒计时（秒，默认值，可配置）
ROUND_PAUSE = 1.0               # 回合结算后的停顿（秒）
WIN_SCORE = 20                  # 达到该分数立即获胜
SURVIVE_SCORE = 1               # 唯一加分来源：每回合结算存活 +1 分
# 说明：对局没有总时长限制（不设超时）；死亡不扣分，只掉一条命。

# ---------------------------------------------------------------- 单位
PLAYER_LIVES = 3                # 每个单位的生命数（默认值，可配置）
MOVE_SPEED = 5.0                # 移动速度（格/秒）
UNIT_RADIUS = 13                # 单位碰撞圆半径（像素）

# ---------------------------------------------------------------- 推人
PUSH_COOLDOWN = 1.0             # 推人冷却（秒）：单位圆环进度条 1 秒充满即就绪
PUSH_STUN = 0.5                 # 被推单位眩晕时长（秒）
PUSH_DIST = 2                   # 推人位移上限（格）
PUSH_SLIDE_TIME = 0.2           # 击退滑动动画时长（秒）：推开 2 格在此期间滑完
PUSH_RANGE = 1.5                # 命中判定：面朝方向 1.5 格内
PUSH_LANE = 0.7                 # 命中判定：垂直于朝向的最大偏差（格）
PUSH_CHAIN_MAX = 4              # 连锁推最多影响的单位数（含首个目标）
PUSH_ANIM_TIME = 0.18           # 推人时朝向指针的伸出动画时长（秒，纯视觉）
PUSH_READY_FLASH = 0.45         # 冷却结束时的满环闪现时长（秒，纯视觉）

# ---------------------------------------------------------------- AI
AI_COUNT = 2                    # 人机数量（默认值，可配置）
AI_DIFFICULTY = "normal"        # 人机难度（默认值，可配置）

AI_COUNT_MIN, AI_COUNT_MAX = 0, 4
LIVES_MIN, LIVES_MAX = 1, 9
ROUND_TIME_MIN, ROUND_TIME_MAX, ROUND_TIME_STEP = 1.0, 30.0, 0.5

DIFFICULTY_ORDER = ("easy", "normal", "hard")
DIFFICULTY_NAMES = {"easy": "简单", "normal": "普通", "hard": "困难"}

# 难度对 AI 的影响（三个方面）：
#   reaction    —— 反应速度：两次决策之间的间隔（秒），越小反应越快
#   precision   —— 寻路精度：0~1，越低移动方向抖动越多、选格越粗糙
#   aggression  —— 推人欲望：0~1，满足推人条件时执行的概率
#   escape_time —— 逃生阈值：倒计时低于该值且不在安全格时进入逃生（秒）
DIFFICULTY_PRESETS = {
    "easy":   {"reaction": 0.40, "precision": 0.55, "aggression": 0.45, "escape_time": 1.0},
    "normal": {"reaction": 0.18, "precision": 0.80, "aggression": 0.70, "escape_time": 1.5},
    "hard":   {"reaction": 0.06, "precision": 1.00, "aggression": 0.95, "escape_time": 2.2},
}

# ---------------------------------------------------------------- 图案
PATTERNS = ("x", "o", "square", "triangle")
PATTERN_GLYPHS = {"x": "×", "o": "○", "square": "□", "triangle": "△"}
PATTERN_LABELS = {"x": "叉号", "o": "圆圈", "square": "方块", "triangle": "三角"}

# ---------------------------------------------------------------- 配色
COLOR_BG = (15, 18, 26)          # 窗口底色 / 虚空
COLOR_VOID = (17, 20, 28)        # 虚空格底色
COLOR_CELL_BG = (34, 40, 54)     # 普通格底色
COLOR_CELL_EDGE = (47, 55, 73)   # 格线
COLOR_HUD_BG = (21, 25, 34)      # HUD 面板底色
COLOR_HUD_LINE = (45, 53, 71)    # HUD 分隔线
COLOR_TEXT = (232, 236, 244)     # 主文字
COLOR_TEXT_DIM = (146, 156, 174) # 次级文字
COLOR_PANEL = (32, 38, 51)       # 按钮底色
COLOR_PANEL_HOVER = (48, 57, 76) # 按钮悬停色
COLOR_WARN = (255, 96, 96)       # 警示色

COLOR_RED = (239, 68, 68)
COLOR_BLUE = (86, 148, 248)
COLOR_GREEN = (52, 199, 89)
COLOR_YELLOW = (245, 197, 66)

# 图案 → 颜色（× 红、○ 蓝、□ 绿、△ 黄）
PATTERN_COLORS = {
    "x": COLOR_RED,
    "o": COLOR_BLUE,
    "square": COLOR_GREEN,
    "triangle": COLOR_YELLOW,
}

# 阵营 → 颜色（红方红、蓝方蓝、人机灰）
COLOR_TEAM = {"red": COLOR_RED, "blue": COLOR_BLUE, "ai": (158, 168, 182)}
TEAM_NAMES = {"red": "红方", "blue": "蓝方", "ai": "人机"}

# ---------------------------------------------------------------- 出生点
# 依次为：红方、蓝方、人机 1~4 的初始出生位置（列, 行）
SPAWN_POINTS = [(1, 11), (11, 1), (1, 1), (11, 11), (6, 6), (6, 1)]

# ---------------------------------------------------------------- 按键映射
KEYMAP = {
    "red": {
        "up": pygame.K_w, "down": pygame.K_s,
        "left": pygame.K_a, "right": pygame.K_d,
        "push": (pygame.K_SPACE,),                     # 空格推人
    },
    "blue": {
        "up": pygame.K_UP, "down": pygame.K_DOWN,
        "left": pygame.K_LEFT, "right": pygame.K_RIGHT,
        "push": (pygame.K_RETURN, pygame.K_KP0),       # 回车 / 小键盘 0 推人
    },
}


# ---------------------------------------------------------------- 设置对象
@dataclass
class GameSettings:
    """一局游戏的可配置项（对应主菜单中的"游戏设置"界面）。"""

    ai_count: int = AI_COUNT
    ai_difficulty: str = AI_DIFFICULTY
    lives: int = PLAYER_LIVES
    round_time: float = ROUND_TIME

    def clamp(self) -> "GameSettings":
        """把各字段限制到合法范围内，返回自身（便于链式调用）。"""
        self.ai_count = max(AI_COUNT_MIN, min(AI_COUNT_MAX, int(self.ai_count)))
        if self.ai_difficulty not in DIFFICULTY_PRESETS:
            self.ai_difficulty = AI_DIFFICULTY
        self.lives = max(LIVES_MIN, min(LIVES_MAX, int(self.lives)))
        rt = max(ROUND_TIME_MIN, min(ROUND_TIME_MAX, float(self.round_time)))
        # 对齐到步长（默认 0.5 秒）
        self.round_time = round(rt / ROUND_TIME_STEP) * ROUND_TIME_STEP
        return self

    def copy(self) -> "GameSettings":
        """返回一份拷贝（开局时使用，避免设置界面的改动影响进行中的对局）。"""
        return GameSettings(self.ai_count, self.ai_difficulty, self.lives, self.round_time)

    @property
    def difficulty_name(self) -> str:
        """难度的中文显示名。"""
        return DIFFICULTY_NAMES.get(self.ai_difficulty, self.ai_difficulty)
