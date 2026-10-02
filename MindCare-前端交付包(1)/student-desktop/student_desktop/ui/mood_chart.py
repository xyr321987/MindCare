# -*- coding: utf-8 -*-
"""情绪折线图控件（学生端「我的档案」→ 情绪可视化）。

纵轴：沮丧=1 / 平淡=2 / 高兴=3（从低到高）；横轴：一周 7 天（周一 → 周日）。
每一天一个点；**相邻两天都有记录才连线**，中间空一天则两侧不连。

本控件是纯 `QPainter` 画布（非 QSS），配色取自 `desktop_common.theme` 语义色，
不做内联样式；面向用户的文字（情绪名 / 星期名）一律从 `COPY` 取。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from desktop_common import theme
from desktop_common.copy import COPY

__all__ = ["MoodChartWidget", "MOOD_LEVEL", "MOOD_COLOR"]

#: mood → 纵轴数值（低→高）
MOOD_LEVEL = {"down": 1, "plain": 2, "happy": 3}

#: mood → 点色（语义色，来自主题）
MOOD_COLOR = {
    "down": theme.DANGER_SOFT,      # 柔珊瑚（沮丧）
    "plain": theme.FOCUS_RING,      # 雾蓝加深（平淡）
    "happy": theme.SLOT_MINE_LINE,  # 嫩芽绿加深（高兴）
}

#: 纵轴三档的文案键（底→顶，与 MOOD_LEVEL 对齐）
_LEVEL_KEYS = {
    1: "s.q1.option.down",
    2: "s.q1.option.plain",
    3: "s.q1.option.happy",
}

_LEFT_GUTTER = 52
_RIGHT_GUTTER = 18
_TOP_GUTTER = 18
_BOTTOM_GUTTER = 46
_POINT_R = 6


class MoodChartWidget(QWidget):
    """一周情绪折线图。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MoodChartWidget")
        self.setMinimumHeight(280)
        #: 7 天日期（周一 → 周日，`YYYY-MM-DD`）
        self._days: List[str] = []
        #: date -> mood（只含有记录的天）
        self._mood: Dict[str, str] = {}

    # ------------------------------------------------------------------ 数据
    def set_week(self, days: List[str]) -> None:
        self._days = [str(d) for d in (days or [])]
        self.update()

    def set_mood(self, mood_map: Dict[str, str]) -> None:
        self._mood = {str(k): str(v) for k, v in (mood_map or {}).items()}
        self.update()

    def has_data(self) -> bool:
        return any(d in self._mood for d in self._days)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.CARD))

        if not self._days:
            painter.end()
            return

        plot_w = self.width() - _LEFT_GUTTER - _RIGHT_GUTTER
        plot_h = self.height() - _TOP_GUTTER - _BOTTOM_GUTTER
        if plot_w <= 0 or plot_h <= 0:
            painter.end()
            return

        # ---- 网格线 + 纵轴标签（底 1 → 顶 3）----
        grid_pen = QPen(QColor(theme.LINE))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        label_font = QFont(self.font())
        label_font.setPointSize(theme.FONT_SMALL)
        painter.setFont(label_font)
        for level in (1, 2, 3):
            y = self._y_for(level, plot_h)
            painter.drawLine(_LEFT_GUTTER, int(y), _LEFT_GUTTER + plot_w, int(y))
            painter.setPen(QColor(theme.INK_SOFT))
            painter.drawText(
                QRectF(0, y - 10, _LEFT_GUTTER - 8, 20),
                Qt.AlignRight | Qt.AlignVCenter,
                COPY[_LEVEL_KEYS[level]],
            )
            painter.setPen(grid_pen)

        # ---- 横轴（7 天）标签 + 竖网格 ----
        col_w = plot_w / 7.0
        for i, day in enumerate(self._days):
            x = _LEFT_GUTTER + (i + 0.5) * col_w
            painter.setPen(grid_pen)
            painter.drawLine(int(x), _TOP_GUTTER, int(x), _TOP_GUTTER + plot_h)
            painter.setPen(QColor(theme.INK_SOFT))
            weekday = COPY.get(f"c.schedule.weekday.{i + 1}", "")
            md = day[5:].replace("-", "/") if len(day) >= 10 else day
            painter.drawText(
                QRectF(x - col_w / 2, _TOP_GUTTER + plot_h + 6, col_w, 18),
                Qt.AlignHCenter | Qt.AlignTop, weekday)
            painter.drawText(
                QRectF(x - col_w / 2, _TOP_GUTTER + plot_h + 24, col_w, 16),
                Qt.AlignHCenter | Qt.AlignTop, md)

        # ---- 点 + 连线（相邻两天都有记录才连）----
        line_pen = QPen(QColor(theme.INK_SOFT))
        line_pen.setWidth(2)
        points = []          # (x, y, mood)
        for i, day in enumerate(self._days):
            mood = self._mood.get(day)
            if not mood:
                continue
            x = _LEFT_GUTTER + (i + 0.5) * col_w
            y = self._y_for(MOOD_LEVEL.get(mood, 2), plot_h)
            points.append((x, y, mood))
        painter.setPen(line_pen)
        for a, b in zip(points, points[1:]):
            painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
        for x, y, mood in points:
            painter.setBrush(QColor(MOOD_COLOR.get(mood, theme.FOCUS_RING)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(int(x - _POINT_R), int(y - _POINT_R),
                                _POINT_R * 2, _POINT_R * 2)

        painter.end()

    @staticmethod
    def _y_for(level: int, plot_h: int) -> float:
        # level 1 → 底部，level 3 → 顶部
        return _TOP_GUTTER + (3 - level) * (plot_h / 2.0)
