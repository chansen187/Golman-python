"""《图案生存战》主入口：应用主循环与四个场景。

场景（Scene）：
* :class:`MainMenuScene`  —— 主页面：开始游戏 / 游戏设置 / 退出游戏；
* :class:`SettingsScene`  —— 游戏设置：人机数量、难度、生命数、回合倒计时；
* :class:`GameScene`      —— 对局：组装世界对象，20 Hz 推进逻辑、60 FPS 渲染；
* :class:`GameOverScene`  —— 结算：结束原因、完整排名与再来一局。

运行方式（二者等价）：
    cd pattern_survival && python main.py
    python pattern_survival/main.py
"""

import os
import sys

# 确保包目录位于 sys.path：无论从包内还是包外启动都能正确导入子包
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 高 DPI 屏幕下保持画面清晰（必须在 pygame 初始化之前设置）
os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "1")

import math
import random
import time

import pygame

from config import (AI_COUNT_MAX, AI_COUNT_MIN, CELL_SIZE, COLOR_BG, COLOR_BLUE,
                    COLOR_GREEN, COLOR_PANEL, COLOR_PANEL_HOVER, COLOR_RED,
                    COLOR_TEXT, COLOR_TEXT_DIM, COLOR_TEAM, COLOR_WARN,
                    COLOR_YELLOW, DIFFICULTY_NAMES, DIFFICULTY_ORDER, FPS,
                    GRID_SIZE, HUD_HEIGHT, KEYMAP, LIVES_MAX, LIVES_MIN,
                    PATTERN_COLORS, PATTERNS, ROUND_TIME_MAX, ROUND_TIME_MIN,
                    ROUND_TIME_STEP, SPAWN_POINTS, TICK_DT,
                    WINDOW_HEIGHT, WINDOW_TITLE, WINDOW_WIDTH, WIN_SCORE,
                    GameSettings)
from ai.bot import SurvivalBot
from core.grid import Grid
from core.push import resolve_push
from core.round_manager import PHASE_COUNTDOWN, RoundManager
from core.score import (END_LAST_STAND, END_PLAYERS_DOWN, END_SCORE,
                        ScoreBoard)
from core.unit import Unit
from replay.recorder import Recorder
from ui.effects import Effects
from ui.hud import Hud
from ui.render import Renderer, draw_pattern, load_font


# ==================================================================== 通用控件
class Button:
    """简单按钮：悬停高亮 + 左键点击回调。"""

    def __init__(self, rect, label, action, accent=None, font_size=22):
        """构造按钮。

        * ``rect``   —— 位置与尺寸 ``(x, y, w, h)``；
        * ``label``  —— 文字；
        * ``action`` —— 点击回调（无参数）；
        * ``accent`` —— 主色（None 使用默认面板色）。
        """
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action
        self.accent = accent
        self.font_size = font_size
        self.hovered = False

    def handle_event(self, event):
        """处理一个事件；被点击时执行回调并返回 ``True``。"""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
              and self.rect.collidepoint(event.pos)):
            self.action()
            return True
        return False

    def draw(self, surface):
        """绘制按钮（悬停时提亮）。"""
        if self.accent is not None:
            base = self.accent
            hover = tuple(min(255, int(c * 1.16)) for c in base)
            border = tuple(min(255, int(c * 1.30)) for c in base)
        else:
            base = COLOR_PANEL
            hover = COLOR_PANEL_HOVER
            border = (62, 72, 92)
        color = hover if self.hovered else base
        pygame.draw.rect(surface, color, self.rect, border_radius=9)
        pygame.draw.rect(surface, border, self.rect, 2, border_radius=9)
        font = load_font(self.font_size, bold=True)
        text = font.render(self.label, True, COLOR_TEXT)
        surface.blit(text, text.get_rect(center=self.rect.center))


def _make_icon():
    """生成窗口图标（四个图案色的描边小方块）。"""
    icon = pygame.Surface((32, 32))
    icon.fill(COLOR_PANEL)
    colors = (COLOR_RED, COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW)
    for index, color in enumerate(colors):
        x = (index % 2) * 16 + 3
        y = (index // 2) * 16 + 3
        pygame.draw.rect(icon, color, pygame.Rect(x, y, 10, 10), 2,
                         border_radius=2)
    return icon


def _disable_ime():
    """Windows：切断输入法与游戏窗口的关联，避免中文输入法"吞掉"游戏按键。

    中文输入法处于激活状态时，字母键（WASD）与空格会被输入法抢先处理
    （表现为"部分按键失灵"，而方向键往往不受影响）。本函数把游戏窗口的
    IME 上下文置空，等效于让游戏窗口彻底无视输入法；只对当前进程的窗口
    生效，游戏退出后自动恢复，不影响系统其他程序。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = pygame.display.get_wm_info().get("window")
        if hwnd:
            ctypes.windll.imm32.ImmAssociateContext(int(hwnd), 0)
    except Exception:      # noqa: BLE001 —— 任何失败都不应影响游戏启动
        pass


# 窗口焦点相关事件 → 场景钩子（对局场景借此实现"失焦自动暂停"）
_FOCUS_EVENTS = {
    pygame.WINDOWFOCUSLOST: "on_focus_lost",
    pygame.WINDOWMINIMIZED: "on_focus_lost",
    pygame.WINDOWFOCUSGAINED: "on_focus_gained",
}


# ==================================================================== 应用外壳
class App:
    """应用外壳：窗口、主循环与场景切换。"""

    def __init__(self):
        """初始化 pygame、窗口、字体与首个场景（主菜单）。"""
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_icon(_make_icon())
        _disable_ime()          # 防止中文输入法吞掉 WASD / 空格等游戏按键
        self.clock = pygame.time.Clock()
        self.settings = GameSettings()
        self.scene = None
        self.running = True
        self.switch(MainMenuScene(self))

    def switch(self, scene):
        """切换当前场景。"""
        self.scene = scene

    def quit(self):
        """请求退出主循环。"""
        self.running = False

    def run(self):
        """主循环：稳定 60 FPS 渲染；各场景自行按 20 Hz 步进逻辑。"""
        while self.running:
            dt = min(0.05, self.clock.tick(FPS) / 1000.0)
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                    continue
                if event.type == pygame.WINDOWFOCUSGAINED:
                    # 少数输入法会在窗口重新激活时尝试重新关联，补一刀
                    _disable_ime()
                handler_name = _FOCUS_EVENTS.get(event.type)
                if handler_name:
                    handler = getattr(self.scene, handler_name, None)
                    if callable(handler):
                        handler()
            if not self.running:
                break
            self.scene.handle_events(events)
            self.scene.update(dt)
            self.scene.render()
            pygame.display.flip()
        pygame.quit()


# ==================================================================== 主菜单
class MainMenuScene:
    """主页面：标题、装饰图案与"开始游戏 / 游戏设置 / 退出游戏"入口。"""

    def __init__(self, app):
        self.app = app
        self.time = 0.0
        self.buttons = [
            Button((150, 322, 220, 54), "开始游戏", self._start, accent=(64, 96, 150)),
            Button((150, 390, 220, 46), "游戏设置", self._settings),
            Button((150, 448, 220, 46), "退出游戏", self._quit),
        ]
        # 背景装饰：固定种子的随机图案矩阵（低亮度绘制）
        rng = random.Random(20261011)
        self.decor = [[rng.choice(PATTERNS) for _ in range(GRID_SIZE)]
                      for _ in range(GRID_SIZE)]

    # ---- 入口动作
    def _start(self):
        self.app.switch(GameScene(self.app, self.app.settings))

    def _settings(self):
        self.app.switch(SettingsScene(self.app))

    def _quit(self):
        self.app.quit()

    # ---- 场景接口
    def handle_events(self, events):
        for event in events:
            for button in self.buttons:
                button.handle_event(event)

    def update(self, dt):
        self.time += dt

    def render(self):
        surface = self.app.screen
        surface.fill(COLOR_BG)

        # 背景装饰图案（低亮度）
        cell = CELL_SIZE
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                pattern = self.decor[row][col]
                rect = pygame.Rect(col * cell, row * cell, cell, cell)
                tint = tuple(int(c * 0.16) for c in PATTERN_COLORS[pattern])
                draw_pattern(surface, pattern, rect, tint, 2)

        # 标题与副标题
        title_font = load_font(52, bold=True)
        title = title_font.render("图案生存战", True, COLOR_TEXT)
        surface.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 128)))
        sub_font = load_font(16)
        subtitle = sub_font.render("PATTERN  SURVIVAL", True, COLOR_TEXT_DIM)
        surface.blit(subtitle, subtitle.get_rect(center=(WINDOW_WIDTH // 2, 174)))

        # 四个图案样本（脉动闪烁）
        pulse = 0.5 + 0.5 * math.sin(self.time * 2.4)
        for index, pattern in enumerate(PATTERNS):
            rect = pygame.Rect(WINDOW_WIDTH // 2 - 78 + index * 44, 222, 32, 32)
            color = tuple(int(c * (0.6 + 0.4 * pulse))
                          for c in PATTERN_COLORS[pattern])
            draw_pattern(surface, pattern, rect, color, 3)

        # 菜单按钮
        for button in self.buttons:
            button.draw(surface)

        # 底部操作说明
        hint_font = load_font(13)
        hints = (
            "红方：WASD 移动 · 空格推人",
            "蓝方：方向键移动 · 回车 / 小键盘 0 推人",
            "站在目标图案格上存活，把对手推向深渊",
        )
        for index, line in enumerate(hints):
            text = hint_font.render(line, True, COLOR_TEXT_DIM)
            surface.blit(text, text.get_rect(
                center=(WINDOW_WIDTH // 2, 546 + index * 22)))


# ==================================================================== 设置
class SettingsScene:
    """游戏设置：人机数量 / 人机难度 / 生命数 / 回合倒计时。

    所有修改即时生效，返回主菜单后点击"开始游戏"即按当前配置开新局。
    """

    ROW_H = 74
    TOP = 150

    def __init__(self, app):
        """构造设置界面（行配置均为闭包，直接读写 ``app.settings``）。"""
        self.app = app
        settings = app.settings

        def shift(field, delta, lo, hi, step=1):
            value = getattr(settings, field) + delta * step
            setattr(settings, field, max(lo, min(hi, value)))

        self.rows = [
            {"label": "人机数量",
             "text": lambda: str(settings.ai_count),
             "dec": lambda: shift("ai_count", -1, AI_COUNT_MIN, AI_COUNT_MAX),
             "inc": lambda: shift("ai_count", +1, AI_COUNT_MIN, AI_COUNT_MAX)},
            {"label": "人机难度",
             "text": lambda: DIFFICULTY_NAMES.get(settings.ai_difficulty,
                                                  settings.ai_difficulty),
             "dec": lambda: self._cycle_difficulty(-1),
             "inc": lambda: self._cycle_difficulty(+1)},
            {"label": "生命数",
             "text": lambda: str(settings.lives),
             "dec": lambda: shift("lives", -1, LIVES_MIN, LIVES_MAX),
             "inc": lambda: shift("lives", +1, LIVES_MIN, LIVES_MAX)},
            {"label": "回合倒计时",
             "text": lambda: "%.1f 秒" % settings.round_time,
             "dec": lambda: shift("round_time", -1, ROUND_TIME_MIN,
                                  ROUND_TIME_MAX, ROUND_TIME_STEP),
             "inc": lambda: shift("round_time", +1, ROUND_TIME_MIN,
                                  ROUND_TIME_MAX, ROUND_TIME_STEP)},
        ]
        self.back_button = Button((150, 516, 220, 46), "返回主菜单", self._back)

    # ---- 内部动作
    def _cycle_difficulty(self, step):
        """循环切换人机难度（简单 → 普通 → 困难）。"""
        settings = self.app.settings
        try:
            index = DIFFICULTY_ORDER.index(settings.ai_difficulty)
        except ValueError:
            index = 1
        settings.ai_difficulty = DIFFICULTY_ORDER[
            (index + step) % len(DIFFICULTY_ORDER)]

    def _back(self):
        self.app.switch(MainMenuScene(self.app))

    # ---- 布局工具
    def _row_rect(self, index):
        """第 ``index`` 行的面板矩形。"""
        return pygame.Rect(60, self.TOP + index * self.ROW_H, 400, 54)

    @staticmethod
    def _arrow_rects(row_rect):
        """一行内左右两个箭头按钮的矩形。"""
        cy = row_rect.centery
        left = pygame.Rect(row_rect.right - 178, cy - 17, 36, 34)
        right = pygame.Rect(row_rect.right - 54, cy - 17, 36, 34)
        return left, right

    # ---- 场景接口
    def handle_events(self, events):
        for event in events:
            self.back_button.handle_event(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._back()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, row in enumerate(self.rows):
                    left, right = self._arrow_rects(self._row_rect(index))
                    if left.collidepoint(event.pos):
                        row["dec"]()
                    elif right.collidepoint(event.pos):
                        row["inc"]()

    def update(self, dt):
        pass

    def render(self):
        surface = self.app.screen
        surface.fill(COLOR_BG)

        title = load_font(40, bold=True).render("游戏设置", True, COLOR_TEXT)
        surface.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 76)))

        mouse = pygame.mouse.get_pos()
        label_font = load_font(19, bold=True)
        value_font = load_font(22, bold=True)
        for index, row in enumerate(self.rows):
            rect = self._row_rect(index)
            pygame.draw.rect(surface, COLOR_PANEL, rect, border_radius=9)
            pygame.draw.rect(surface, (52, 61, 80), rect, 1, border_radius=9)

            label = label_font.render(row["label"], True, COLOR_TEXT)
            surface.blit(label, (rect.x + 20,
                                 rect.centery - label.get_height() // 2))

            value = value_font.render(row["text"](), True, (150, 200, 255))
            surface.blit(value, value.get_rect(
                center=(rect.right - 98, rect.centery)))

            left, right = self._arrow_rects(rect)
            self._draw_arrow(surface, left, -1, left.collidepoint(mouse))
            self._draw_arrow(surface, right, +1, right.collidepoint(mouse))

        self.back_button.draw(surface)

        # 底部说明
        note_font = load_font(13)
        notes = (
            "难度影响人机的反应速度、寻路精度与推人欲望",
            "设置即时生效，返回主菜单后点击「开始游戏」即按此配置开局",
        )
        for index, line in enumerate(notes):
            text = note_font.render(line, True, COLOR_TEXT_DIM)
            surface.blit(text, text.get_rect(
                center=(WINDOW_WIDTH // 2, 452 + index * 22)))

    @staticmethod
    def _draw_arrow(surface, rect, direction, hovered):
        """绘制 ◀ / ▶ 箭头按钮。"""
        color = COLOR_TEXT if hovered else COLOR_TEXT_DIM
        cx, cy = rect.center
        if direction < 0:
            points = ((cx + 5, cy - 8), (cx - 5, cy), (cx + 5, cy + 8))
        else:
            points = ((cx - 5, cy - 8), (cx + 5, cy), (cx - 5, cy + 8))
        pygame.draw.polygon(surface, color, points)


# ==================================================================== 对局
class GameScene:
    """对局场景：组装全部世界对象，驱动逻辑与渲染。

    * 逻辑固定 20 Hz（``TICK_DT``）步进，渲染 60 FPS；
    * 人类输入每逻辑帧采样一次；AI 每逻辑帧构建观测并请求决策；
    * 渲染使用"上一逻辑帧 → 当前逻辑帧"的位置插值，保证移动平滑。
    """

    def __init__(self, app, settings):
        """按 ``settings``（深拷贝 + 范围校正）创建一局新游戏。"""
        self.app = app
        self.settings = settings.copy().clamp()
        self.rng = random.Random()
        self.board_px = GRID_SIZE * CELL_SIZE
        self.time = 0.0            # 渲染累计时间（动画用）
        self.acc = 0.0             # 逻辑帧累加器
        self.paused = False
        self._paused_by_focus = False   # 暂停是否由"窗口失焦"触发
        self._active = bool(pygame.key.get_focused())   # 窗口是否已可接收按键
        self.finished = False
        self._push_queue = []      # 本逻辑帧待处理的推人请求（单位列表）

        # ---- 世界对象
        self.grid = Grid(GRID_SIZE, CELL_SIZE, rng=self.rng)
        self.units = []
        self.bots = {}
        self._build_units()

        # ---- 服务对象
        self.effects = Effects()
        self.recorder = Recorder(enabled=True)
        self.recorder.set_meta(
            started=time.strftime("%Y-%m-%d %H:%M:%S"),
            settings={
                "ai_count": self.settings.ai_count,
                "ai_difficulty": self.settings.ai_difficulty,
                "lives": self.settings.lives,
                "round_time": self.settings.round_time,
            },
            units=[{"name": u.name, "team": u.team} for u in self.units],
        )
        self.scoreboard = ScoreBoard(self.units)
        self.round_manager = RoundManager(
            self.grid, self.units, self.settings,
            effects=self.effects, recorder=self.recorder, rng=self.rng)
        self.renderer = Renderer(GRID_SIZE, CELL_SIZE, HUD_HEIGHT)
        self.hud = Hud()

        self.round_manager.start()

    # ------------------------------------------------------------ 组装
    def _build_units(self):
        """创建红方 / 蓝方玩家单位与若干人机单位（人机为中立灰色）。"""
        lives = self.settings.lives
        red_col, red_row = SPAWN_POINTS[0]
        blue_col, blue_row = SPAWN_POINTS[1]
        self.units.append(Unit(0, "red", "红方", red_col, red_row, lives,
                               is_human=True))
        self.units.append(Unit(1, "blue", "蓝方", blue_col, blue_row, lives,
                               is_human=True))
        for index in range(self.settings.ai_count):
            uid = 2 + index
            col, row = SPAWN_POINTS[2 + index]
            name = "人机 %d" % (index + 1)
            unit = Unit(uid, "ai", name, col, row, lives, is_ai=True)
            self.units.append(unit)
            self.bots[uid] = SurvivalBot(
                name=name, difficulty=self.settings.ai_difficulty,
                seed=uid * 7919 + 13)

    # ------------------------------------------------------------ 窗口焦点
    def on_focus_lost(self):
        """窗口失去键盘焦点（切到其他窗口 / 最小化）：自动暂停。

        同时把"因失焦而暂停"的状态记下，遮挡层会提示"点击游戏窗口继续"，
        避免出现"按键突然失灵"的困惑。
        """
        if not self.finished and not self.paused:
            self.paused = True
            self._paused_by_focus = True

    def on_focus_gained(self):
        """窗口重新获得键盘焦点：保持暂停，等待点击窗口 / ESC 明确继续。

        故意不做自动恢复——避免玩家切回窗口时按着的按键让单位冲出。
        """

    def _check_activation(self):
        """兜底：若窗口从未激活，则每帧探测一次焦点状态。"""
        if not self._active and pygame.key.get_focused():
            self._active = True

    # ------------------------------------------------------------ 事件
    def handle_events(self, events):
        """键盘 / 鼠标事件。

        * 未激活时点击窗口 → 解锁（开始游戏）；
        * 失焦暂停时点击窗口 → 继续；
        * ESC 暂停 / 继续、M 返回主菜单（暂停时）、推人键。
        """
        if self.finished:
            return
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                # 点击窗口即视为激活（不依赖焦点检测的兜底）
                self._active = True
                if self._paused_by_focus:
                    self._paused_by_focus = False
                    self.paused = False
                continue
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                self.paused = not self.paused
                self._paused_by_focus = False
            elif self.paused and event.key == pygame.K_m:
                self.app.switch(MainMenuScene(self.app))
            elif not self.paused:
                self._queue_human_push(event.key)

    def _queue_human_push(self, key):
        """把人类玩家的推人按键翻译成一次推人请求（逻辑帧消费）。"""
        if self.round_manager.phase != PHASE_COUNTDOWN:
            return
        for unit in self.units:
            if not unit.is_human or not unit.in_play():
                continue
            if key in KEYMAP[unit.team]["push"]:
                self._push_queue.append(unit)

    # ------------------------------------------------------------ 更新
    def update(self, dt):
        """渲染帧更新：按固定步长推进逻辑帧，其余交给特效系统。

        窗口尚未激活（收不到按键）时先停住逻辑并提示点击窗口，
        避免开局"倒计时已经在跑、人却动不了"的困惑。
        """
        self.time += dt
        if self.finished:
            return
        if not self._active:
            self._check_activation()
            if not self._active:
                self.effects.update(dt, text_only=True)
                return
        if self.paused:
            self.effects.update(dt, text_only=True)
            return
        self.acc += dt
        steps = 0
        while self.acc >= TICK_DT and steps < 4:
            self._tick(TICK_DT)
            self.acc -= TICK_DT
            steps += 1
            if self.finished:
                break
        self.effects.update(dt)

    def _tick(self, dt):
        """单个逻辑帧（20 Hz）：输入 → AI → 推人 → 状态 → 回合 → 判定。"""
        for unit in self.units:
            unit.begin_tick()

        counting = self.round_manager.phase == PHASE_COUNTDOWN
        if counting:
            self._apply_human_input(dt)
            self._apply_ai(dt)
            self._resolve_pushes()
        else:
            self._push_queue.clear()      # 停顿期间不接受任何操作

        for unit in self.units:
            unit.update(dt)
        self.round_manager.update(dt)
        self._check_end()

    def _apply_human_input(self, dt):
        """采样键盘状态，驱动红 / 蓝两个玩家单位移动。"""
        pressed = pygame.key.get_pressed()
        for unit in self.units:
            if not unit.is_human or not unit.in_play():
                continue
            keys = KEYMAP[unit.team]
            dx = ((1 if pressed[keys["right"]] else 0)
                  - (1 if pressed[keys["left"]] else 0))
            dy = ((1 if pressed[keys["down"]] else 0)
                  - (1 if pressed[keys["up"]] else 0))
            if dx or dy:
                unit.apply_move((dx, dy), dt, self.units,
                                self.board_px, self.board_px)

    def _apply_ai(self, dt):
        """驱动全部人机单位：构建观测 → 请求决策 → 执行移动 / 推人。"""
        for unit in self.units:
            bot = self.bots.get(unit.uid)
            if bot is None or not unit.in_play():
                continue
            obs = self._build_observation(unit)
            decision = bot.think(obs, dt)
            move = decision.get("move", (0.0, 0.0))
            if move[0] or move[1]:
                unit.apply_move(move, dt, self.units,
                                self.board_px, self.board_px)
            if decision.get("push") and unit.push_ready:
                self._push_queue.append(unit)

    def _build_observation(self, unit):
        """构建 AI 观测字典（字段定义见 ``ai/base_agent.py`` 模块文档）。"""
        others = []
        for other in self.units:
            if other is unit:
                continue
            others.append({
                "id": other.uid,
                "pos": other.fcell(),
                "cell": other.cell(),
                "team": other.team,
                "stunned": other.stunned,
                "in_play": other.in_play(),
                "lives": other.lives,
            })
        return {
            "self": {
                "id": unit.uid,
                "pos": unit.fcell(),
                "cell": unit.cell(),
                "stunned": unit.stunned,
                "push_ready": unit.push_ready,
                "facing": unit.facing,
                "lives": unit.lives,
            },
            "target": self.round_manager.target,
            "grid": [list(row) for row in self.grid.cells],
            "units": others,
            "countdown": max(0.0, self.round_manager.time_left),
            "round": self.round_manager.round_index,
        }

    def _resolve_pushes(self):
        """消费推人请求队列：结算命中与连锁，并播放反馈特效。"""
        if not self._push_queue:
            return
        for unit in self._push_queue:
            if not unit.push_ready:
                continue
            result = resolve_push(unit, self.units, self.grid)
            self._push_feedback(result)
            self.recorder.log(
                "push", by=unit.name, direction=list(result.direction),
                hit=result.hit,
                targets=[t.unit.name for t in result.targets],
                moved=[t.moved_cells for t in result.targets])
        self._push_queue.clear()

    def _push_feedback(self, result):
        """推人视觉反馈：短促屏幕震动 + 击退尘屑；推空时轻量灰尘。"""
        if not result.hit:
            fx, fy = result.pusher.facing
            x = result.pusher.px + fx * CELL_SIZE * 0.8
            y = result.pusher.py + fy * CELL_SIZE * 0.8
            self.effects.burst(x, y, (150, 160, 180), count=4,
                               speed=(20, 70), life=0.28, size_range=(1, 2))
            return
        self.effects.shake(4.5, 0.16)
        for target in result.targets:
            unit = target.unit
            if target.moved_cells > 0:
                self.effects.ring(unit.px, unit.py, (255, 255, 255),
                                  radius=22, life=0.3)
            else:
                self.effects.burst(unit.px, unit.py, (255, 230, 200), count=6,
                                   speed=(30, 90), life=0.3, size_range=(1, 3))

    def _check_end(self):
        """检查胜负；结束时导出对局记录并切换到结算场景。"""
        ended, reason, winner = self.scoreboard.check_end()
        if not ended:
            return
        self.finished = True
        replay_path = self.recorder.save()
        ranking = self.scoreboard.ranking()
        self.app.switch(GameOverScene(self.app, reason, winner, ranking,
                                      replay_path))

    # ------------------------------------------------------------ 渲染
    def render(self):
        """按层次绘制：地图 → 特效 → 单位 → 飘字 → HUD → 横幅。"""
        surface = self.app.screen
        surface.fill(COLOR_BG)
        offset = self.effects.shake_offset()
        alpha = min(1.0, self.acc / TICK_DT)          # 位置插值系数
        pulse = 0.5 + 0.5 * math.sin(self.time * 6.0)

        self.renderer.draw_board(surface, self.grid, self.round_manager.target,
                                 pulse, offset)
        self.effects.draw_fades(surface, offset)
        self.effects.draw_particles(surface, offset)
        self.effects.draw_rings(surface, offset)
        self.renderer.draw_units(surface, self.units, alpha, self.time, offset)
        self.effects.draw_floaters(surface, offset)
        self.hud.draw(surface, self._hud_state(pulse))
        self.effects.draw_banner(surface)
        overlay = self._overlay_content()
        if overlay is not None:
            self._draw_overlay(surface, overlay)

    def _hud_state(self, pulse):
        """组装 HUD 所需的状态字典。"""
        red = next((u for u in self.units if u.team == "red"), None)
        blue = next((u for u in self.units if u.team == "blue"), None)
        manager = self.round_manager
        return {
            "red_score": red.score if red else 0,
            "blue_score": blue.score if blue else 0,
            "red_lives": red.lives if red else 0,
            "blue_lives": blue.lives if blue else 0,
            "target": manager.target,
            "time_left": manager.time_left,
            "round_time": self.settings.round_time,
            "round_index": manager.round_index,
            "elapsed": manager.elapsed,
            "pulse": pulse,
        }

    def _overlay_content(self):
        """返回当前需要显示的遮罩文案 ``(标题, 提示, 标题字号)``。

        * 未激活（窗口收不到按键）→ 引导点击窗口；
        * 失焦暂停 → 提示点击继续；
        * 手动暂停 → ESC 继续 / M 返回主菜单；
        * 正常运行 → ``None``（不显示遮罩）。
        """
        if not self._active:
            return ("点击游戏窗口开始", "游戏会在窗口激活后开始运行", 34)
        if self.paused:
            if self._paused_by_focus:
                return ("窗口失去焦点 · 已暂停", "点击游戏窗口继续", 30)
            return ("已暂停", "ESC 继续　·　M 返回主菜单", 44)
        return None

    @staticmethod
    def _draw_overlay(surface, content):
        """绘制半透明遮罩与提示文字。"""
        title_text, hint_text, title_size = content
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT),
                                 pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 168))
        surface.blit(overlay, (0, 0))
        title = load_font(title_size, bold=True).render(title_text, True,
                                                        COLOR_TEXT)
        surface.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 262)))
        hint = load_font(17).render(hint_text, True, COLOR_TEXT_DIM)
        surface.blit(hint, hint.get_rect(center=(WINDOW_WIDTH // 2, 316)))


# ==================================================================== 结算
class GameOverScene:
    """结算场景：结束原因 + 完整排名（含人机）+ 再来一局 / 返回主菜单。"""

    def __init__(self, app, reason, winner, ranking, replay_path=None):
        """记录对局结果并创建两个操作按钮。"""
        self.app = app
        self.reason = reason
        self.winner = winner
        self.ranking = ranking
        self.replay_path = replay_path
        self.buttons = [
            Button((150, 492, 220, 48), "再来一局", self._again,
                   accent=(64, 96, 150)),
            Button((150, 550, 220, 44), "返回主菜单", self._menu),
        ]

    # ---- 入口动作
    def _again(self):
        self.app.switch(GameScene(self.app, self.app.settings))

    def _menu(self):
        self.app.switch(MainMenuScene(self.app))

    # ---- 场景接口
    def handle_events(self, events):
        for event in events:
            for button in self.buttons:
                button.handle_event(event)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self._again()
                elif event.key == pygame.K_ESCAPE:
                    self._menu()

    def update(self, dt):
        pass

    def _reason_text(self):
        """结束原因文案与配色。"""
        if self.reason == END_PLAYERS_DOWN:
            return "红蓝双方已全部出局 —— 人机接管了战场", COLOR_WARN
        if self.reason == END_LAST_STAND:
            if self.winner is None:
                return "全员淘汰，无人幸存", COLOR_WARN
            return "%s 成为最后的幸存者！" % self.winner.name, \
                COLOR_TEAM.get(self.winner.team, COLOR_TEXT)
        if self.reason == END_SCORE:
            return "%s 率先达到 %d 分！" % (self.winner.name, WIN_SCORE), \
                COLOR_TEAM.get(self.winner.team, COLOR_TEXT)
        return "对局结束", COLOR_TEXT

    def render(self):
        surface = self.app.screen
        surface.fill(COLOR_BG)

        big = load_font(44, bold=True).render("游戏结束", True, COLOR_TEXT)
        surface.blit(big, big.get_rect(center=(WINDOW_WIDTH // 2, 72)))

        reason_text, reason_color = self._reason_text()
        mid = load_font(19, bold=True).render(reason_text, True, reason_color)
        surface.blit(mid, mid.get_rect(center=(WINDOW_WIDTH // 2, 122)))

        # 排名表
        row_font = load_font(18)
        name_font = load_font(19, bold=True)
        top = 168
        for entry in self.ranking:
            rect = pygame.Rect(70, top + (entry["rank"] - 1) * 46, 380, 38)
            pygame.draw.rect(surface, COLOR_PANEL, rect, border_radius=7)
            if self.winner is not None and entry["unit"] is self.winner:
                pygame.draw.rect(surface, COLOR_YELLOW, rect, 2,
                                 border_radius=7)
            rank_txt = row_font.render("#%d" % entry["rank"], True,
                                       COLOR_TEXT_DIM)
            surface.blit(rank_txt, (rect.x + 14, rect.y + 9))
            color = COLOR_TEAM.get(entry["team"], COLOR_TEXT)
            name_txt = name_font.render(entry["name"], True, color)
            surface.blit(name_txt, (rect.x + 62, rect.y + 8))
            status = entry["status"]
            if entry["lives"] > 0:
                status += " · 生命 %d" % entry["lives"]
            status_txt = row_font.render(status, True, COLOR_TEXT_DIM)
            surface.blit(status_txt, (rect.right - status_txt.get_width() - 108,
                                      rect.y + 10))
            score_txt = name_font.render("%d 分" % entry["score"], True,
                                         COLOR_TEXT)
            surface.blit(score_txt, (rect.right - score_txt.get_width() - 14,
                                     rect.y + 8))

        # 对局记录提示
        if self.replay_path:
            note = load_font(12).render(
                "对局记录已保存至 replays/%s" % os.path.basename(self.replay_path),
                True, COLOR_TEXT_DIM)
            surface.blit(note, note.get_rect(center=(WINDOW_WIDTH // 2, 456)))

        # 操作按钮与快捷键提示
        for button in self.buttons:
            button.draw(surface)
        tip = load_font(12).render("快捷键：R 再来一局 · ESC 返回主菜单",
                                   True, COLOR_TEXT_DIM)
        surface.blit(tip, tip.get_rect(center=(WINDOW_WIDTH // 2, 608)))


# ==================================================================== 入口
def main():
    """程序入口：创建应用并进入主循环。"""
    app = App()
    app.run()


if __name__ == "__main__":
    main()
