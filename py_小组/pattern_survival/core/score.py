"""计分板模块：分数聚合、排名与胜负判定。

计分规则：
* 计分来源有且只有一种：每回合结算时，站在目标图案格上的单位
  存活 ``+SURVIVE_SCORE``（+1 分）；
* 死亡不扣分，只掉一条命；
* 红蓝分别统计团队总分（HUD 显示），全体单位（含人机）参与排名。

结束条件（按优先级）：
1. ``players_down`` —— 红蓝双方全部被淘汰（仅剩人机）：立即结束展示分数；
2. ``last_stand``   —— 全场只剩一个未淘汰单位：该单位获胜；
3. ``score``        —— 有单位分数达到 ``WIN_SCORE``（20 分）：立即获胜。

对局没有总时长限制（不设超时结束）。
"""

from config import WIN_SCORE

# 结束原因常量
END_PLAYERS_DOWN = "players_down"
END_LAST_STAND = "last_stand"
END_SCORE = "score"


class ScoreBoard:
    """分数聚合、排名与胜负判定服务。"""

    def __init__(self, units, win_score=WIN_SCORE):
        """绑定单位列表（分数实时读取自单位对象，无需同步）。"""
        self.units = units
        self.win_score = win_score

    # ============================================================ 聚合
    def team_total(self, team):
        """某阵营的团队总分（红 / 蓝）。"""
        return sum(u.score for u in self.units if u.team == team)

    @property
    def red_total(self):
        """红方总分。"""
        return self.team_total("red")

    @property
    def blue_total(self):
        """蓝方总分。"""
        return self.team_total("blue")

    def ranking(self):
        """全体单位按（分数, 剩余生命, 编号）降序排名。

        返回列表，每项为字典：rank / unit / name / team / score / lives / status。
        """
        ordered = sorted(self.units,
                         key=lambda u: (-u.score, -u.lives, u.uid))
        rows = []
        for index, unit in enumerate(ordered):
            rows.append({
                "rank": index + 1,
                "unit": unit,
                "name": unit.name,
                "team": unit.team,
                "score": unit.score,
                "lives": unit.lives,
                "status": "淘汰" if unit.eliminated else "存活",
            })
        return rows

    # ============================================================ 胜负
    def check_end(self):
        """检查对局是否结束（无总时长限制，不会因时间超时结束）。

        返回 ``(ended, reason, winner)``：
        * ``ended``  —— 是否结束；
        * ``reason`` —— 结束原因（END_* 常量之一），未结束为 ``None``；
        * ``winner`` —— 获胜单位（``players_down`` 时无获胜者可返回 ``None``）。
        """
        players = [u for u in self.units if u.team in ("red", "blue")]
        if players and all(u.eliminated for u in players):
            return True, END_PLAYERS_DOWN, None

        alive = [u for u in self.units if not u.eliminated]
        if len(alive) <= 1:
            return True, END_LAST_STAND, (alive[0] if alive else None)

        top = max(self.units, key=lambda u: (u.score, -u.uid))
        if top.score >= self.win_score:
            return True, END_SCORE, top

        return False, None, None
