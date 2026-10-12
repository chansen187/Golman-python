"""对局记录器（可选模块）：按回合记录地图布局与关键事件，导出 JSON。

默认在每局正常结束时把记录写入 ``pattern_survival/replays/`` 目录；
写入失败（权限 / 磁盘等原因）时静默返回 ``None``，不影响游戏运行。
"""

import json
import os
import time

# 图案 → 单字符缩写（用于紧凑地编码每回合地图，169 字符 = 一眼看清布局）
_SHORT = {"x": "x", "o": "o", "square": "s", "triangle": "t"}


class Recorder:
    """对局记录器。

    * :meth:`start_round` —— 记录每回合初始布局与目标图案；
    * :meth:`log`         —— 记录推人 / 死亡 / 重生等关键事件；
    * :meth:`round_end`   —— 记录回合结算快照（分数 / 生命）；
    * :meth:`save`        —— 对局结束时导出 JSON 文件。
    """

    def __init__(self, enabled=True, out_dir=None):
        """构造记录器；``out_dir`` 默认指向包目录下的 ``replays/``。"""
        self.enabled = enabled
        self.out_dir = out_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "replays")
        self.meta = {}
        self.rounds = []
        self.events = []

    # ============================================================ 记录
    def set_meta(self, **kwargs):
        """记录对局元信息（设置快照、参战单位等）。"""
        if not self.enabled:
            return
        self.meta.update(kwargs)

    def start_round(self, index, target, cells):
        """记录一回合的初始地图布局。

        地图编码为字符串行（每行 13 个字符）：
        ``x`` = 叉、``o`` = 圈、``s`` = 方块、``t`` = 三角。
        """
        if not self.enabled:
            return
        lines = ["".join(_SHORT.get(pat, "?") for pat in row) for row in cells]
        self.rounds.append({"round": index, "target": target, "map": lines})

    def log(self, kind, **data):
        """记录一个事件（推人 / 死亡 / 重生）。"""
        if not self.enabled:
            return
        entry = {"event": kind}
        for key, value in data.items():
            if isinstance(value, tuple):
                value = list(value)
            entry[key] = value
        self.events.append(entry)

    def round_end(self, index, snapshot):
        """记录回合结算快照（各单位分数 / 生命 / 淘汰状态）。"""
        if not self.enabled:
            return
        self.events.append({"event": "round_end", "round": index,
                            "units": snapshot})

    # ============================================================ 导出
    def save(self, path=None):
        """把记录导出为 JSON 文件。

        返回实际写入的文件路径；未启用或写入失败时返回 ``None``。
        """
        if not self.enabled:
            return None
        if path is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.out_dir, "replay_%s.json" % stamp)
        payload = {
            "meta": self.meta,
            "rounds": self.rounds,
            "events": self.events,
        }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=1)
            return path
        except OSError:
            return None
