# -*- coding: utf-8 -*-
"""教师端轻量图表工厂（基于 QtCharts）。

把 QtCharts 的重复样板收拢到一处，页面只管喂数据、拿 QChart / QChartView：

* 统一配色（延续教师端「浅蓝灰 + 克制暖色」体系）；
* 统一坐标轴 / 图例 / 网格 / 无动画；
* 统一悬停 tooltip（折线 / 柱状 / 环图）；
* 环图 `RingGauge`：单值环形进度 + 居中百分比文字。

纪律：QtCharts 的描边 / 填充走 QBrush/QPen，**不走 QSS**；本模块不写任何
`setStyleSheet`，保证「全控件树无内联 QSS」的自检纪律不破。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView,
    QLineSeries, QPieSeries, QStackedBarSeries, QValueAxis,
)
from PySide6.QtWidgets import QFrame, QLabel, QToolTip, QVBoxLayout, QWidget

# --------------------------------------------------------------------------- 配色
# 情绪三态（折线 / 柱状共用）
C_POSITIVE = "#5B9A7B"   # 积极：柔和绿
C_STABLE = "#4E7FAE"     # 平稳：品牌蓝
C_LOW = "#C9836B"        # 低落：克制暖红

# 预警三等级（P1/P2/P3 的**图表填充**色，比徽标底色更深一档、图里才看得清）
C_P1 = "#D97A63"         # P1：珊瑚
C_P2 = "#E8A87C"         # P2：杏橙
C_P3 = "#9FB2C8"         # P3：灰蓝

C_GRID = "#E4E9F0"       # 网格线
C_AXIS_INK = "#64748B"   # 轴文字（次要灰）
C_CARD = "#FFFFFF"       # 图表底（与卡片同色，避免透明底在 offscreen 下变黑）
C_RING_REST = "#EEF2F6"  # 环形剩余段

#: 情绪三态配色（顺序固定：积极 / 平稳 / 低落）
MOOD_COLORS = (C_POSITIVE, C_STABLE, C_LOW)

#: 预警三等级配色（顺序固定：P1 / P2 / P3）
PRIORITY_COLORS = (C_P1, C_P2, C_P3)


# --------------------------------------------------------------------------- 基础


def _base_chart() -> QChart:
    chart = QChart()
    chart.setBackgroundBrush(QColor(C_CARD))
    chart.setBackgroundRoundness(0)
    chart.setMargins(QMargins(6, 6, 6, 6))
    chart.setAnimationOptions(QChart.NoAnimation)
    legend = chart.legend()
    legend.setVisible(True)
    legend.setAlignment(Qt.AlignBottom)
    legend.setLabelColor(QColor(C_AXIS_INK))
    legend.setBackgroundVisible(False)
    return chart


def _add_xy_axes(chart: QChart, categories: Sequence[str],
                 series_list: List[QLineSeries]) -> None:
    """折线图 XY 轴：x 为分类（日期/周），y 为数值。"""
    axis_x = QBarCategoryAxis()
    axis_x.append(list(categories))
    axis_x.setLabelsColor(QColor(C_AXIS_INK))
    axis_x.setGridLineVisible(False)
    axis_y = QValueAxis()
    axis_y.setLabelFormat("%d")
    axis_y.setLabelsColor(QColor(C_AXIS_INK))
    axis_y.setGridLineColor(QColor(C_GRID))
    chart.addAxis(axis_x, Qt.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignLeft)
    for series in series_list:
        chart.addSeries(series)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)


def make_chart_view(chart: QChart, *, min_height: int = 260) -> QChartView:
    """把 QChart 包成无边框、抗锯齿、固定最小高度的 QChartView。"""
    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    view.setFrameShape(QFrame.NoFrame)
    view.setMouseTracking(True)
    view.setMinimumHeight(min_height)
    # 关掉自身滚动：wheel 事件会向上抛给外层 QScrollArea，页面整体滚动
    view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return view


# --------------------------------------------------------------------------- 折线图


def build_line_chart(categories: Sequence[str],
                     series_specs: Sequence[Tuple[str, Sequence[float], str]],
                     axis_labels: Optional[Sequence[str]] = None,
                     ) -> QChart:
    """多系列折线图。

    :param categories: 完整横轴标签（用于悬停 tooltip，与各系列值等长）
    :param series_specs: [(名称, 数值列表, 颜色), ...]
    :param axis_labels: 横轴实际显示的标签（点数多时抽稀留空；缺省同 categories）
    """
    if axis_labels is None:
        axis_labels = categories
    chart = _base_chart()
    series_list: List[QLineSeries] = []

    for name, values, color in series_specs:
        line = QLineSeries()
        line.setName(name)
        line.setColor(QColor(color))
        pen = line.pen()
        pen.setWidthF(2.4)
        line.setPen(pen)
        line.setPointsVisible(False)
        for i, value in enumerate(values):
            line.append(float(i), float(value))
        series_list.append(line)

    _add_xy_axes(chart, axis_labels, series_list)

    def _hover(point, state: bool) -> None:
        if not state:
            QToolTip.hideText()
            return
        i = int(round(point.x()))
        if 0 <= i < len(categories):
            lines = [str(categories[i])]
            for name, values, _color in series_specs:
                lines.append(f"{name} {int(values[i])}")
            QToolTip.showText(QCursor.pos(), "\n".join(lines))

    for line in series_list:
        line.hovered.connect(_hover)
    return chart


# --------------------------------------------------------------------------- 柱状图


def _bar_chart(categories: Sequence[str],
               set_specs: Sequence[Tuple[str, Sequence[float], str]],
               *, stacked: bool,
               axis_labels: Optional[Sequence[str]] = None) -> QChart:
    if axis_labels is None:
        axis_labels = categories
    chart = _base_chart()
    series = QStackedBarSeries() if stacked else QBarSeries()
    sets = []
    for name, values, color in set_specs:
        bar_set = QBarSet(name)
        for value in values:
            bar_set.append(float(value))
        bar_set.setColor(QColor(color))
        bar_set.setBorderColor(QColor(C_CARD))
        series.append(bar_set)
        sets.append(bar_set)

    axis_x = QBarCategoryAxis()
    axis_x.append(list(axis_labels))
    axis_x.setLabelsColor(QColor(C_AXIS_INK))
    axis_x.setGridLineVisible(False)
    axis_y = QValueAxis()
    axis_y.setLabelFormat("%d")
    axis_y.setLabelsColor(QColor(C_AXIS_INK))
    axis_y.setGridLineColor(QColor(C_GRID))
    chart.addSeries(series)
    chart.addAxis(axis_x, Qt.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_x)
    series.attachAxis(axis_y)

    def _hover(status: bool, _bar_set, index: int) -> None:
        if not status:
            QToolTip.hideText()
            return
        if 0 <= index < len(categories):
            lines = [str(categories[index])]
            total = 0
            for name, values, _color in set_specs:
                value = int(values[index])
                total += value
                lines.append(f"{name} {value}")
            lines.append(f"合计 {total}")
            QToolTip.showText(QCursor.pos(), "\n".join(lines))

    series.hovered.connect(_hover)
    return chart


def build_stacked_bar(categories: Sequence[str],
                      set_specs: Sequence[Tuple[str, Sequence[float], str]],
                      axis_labels: Optional[Sequence[str]] = None) -> QChart:
    """堆叠柱状图（如：P1/P2/P3 预警趋势）。"""
    return _bar_chart(categories, set_specs, stacked=True,
                      axis_labels=axis_labels)


def build_grouped_bar(categories: Sequence[str],
                      set_specs: Sequence[Tuple[str, Sequence[float], str]],
                      axis_labels: Optional[Sequence[str]] = None) -> QChart:
    """分组柱状图（如：各年级情绪状态对比）。"""
    return _bar_chart(categories, set_specs, stacked=False,
                      axis_labels=axis_labels)


# --------------------------------------------------------------------------- 环图


def build_donut(slices: Sequence[Tuple[str, float, str]]) -> QChart:
    """环形图。

    :param slices: [(名称, 数值, 颜色), ...]
    """
    chart = _base_chart()
    series = QPieSeries()
    series.setHoleSize(0.56)
    series.setPieSize(0.88)
    total = sum(value for _name, value, _color in slices) or 1.0

    for name, value, color in slices:
        sl = series.append(name, value)
        sl.setColor(QColor(color))
        sl.setBorderColor(QColor(C_CARD))
        sl.setLabelVisible(False)
        sl.hovered.connect(
            lambda state, n=name, v=value, t=total: _pie_hover(state, n, v, t))

    chart.addSeries(series)
    return chart


def _pie_hover(state: bool, name: str, value: float, total: float) -> None:
    if not state:
        QToolTip.hideText()
        return
    pct = round(value / total * 100, 1)
    QToolTip.showText(QCursor.pos(), f"{name}\n{int(value)} 人次 · {pct}%")


# --------------------------------------------------------------------------- 单值环


class RingGauge(QWidget):
    """单值环形进度：一个彩色弧段 + 居中百分比文字（用于「完成率」）。"""

    def __init__(self, color: str, *, size: int = 116,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

        self._series = QPieSeries()
        self._series.setHoleSize(0.62)
        self._series.setPieSize(0.92)
        self._value_slice = self._series.append("value", 0.0)
        self._value_slice.setColor(QColor(color))
        self._value_slice.setBorderColor(QColor(C_CARD))
        self._rest_slice = self._series.append("rest", 100.0)
        self._rest_slice.setColor(QColor(C_RING_REST))
        self._rest_slice.setBorderColor(QColor(C_CARD))

        chart = _base_chart()
        chart.legend().setVisible(False)
        chart.addSeries(self._series)

        view = make_chart_view(chart, min_height=size)
        view.setMinimumWidth(size)
        view.setMaximumWidth(size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)

        # 居中百分比文字（透明底、盖在环上）
        self._label = QLabel("0%", self)
        self._label.setObjectName("RingValue")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setGeometry(0, 0, size, size)

    def set_percent(self, percent: float) -> None:
        p = max(0, min(100, int(round(percent))))
        self._value_slice.setValue(float(p))
        self._rest_slice.setValue(float(100 - p))
        self._label.setText(f"{p}%")
