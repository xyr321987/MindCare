# -*- coding: utf-8 -*-
"""数据分析页 —— 学校心理健康数据可视化驾驶舱。

自上而下：
1. 顶部：时间筛选（最近 7 / 30 / 90 天、本学期）
2. 核心指标卡：参与学生数 / 情绪状态 / 心理预警数 / 待处理求助数 / 心理支持完成率
3. 全校情绪变化趋势（三态折线）
4. 全校情绪分布 + 心理预警来源（两个环形图）
5. 心理预警趋势（P1/P2/P3 堆叠柱）+ 各年级情绪状态对比（分组柱）
6. 心理支持工作（完成率环 + 待跟进 + 平均响应时间）

数据来自 `analytics_data.load_analytics()`（当前为模拟数据；接入真实接口只换那一层）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    Card, Progress, make_hint, make_label, make_title, wrap_scroll,
)

from ..common.async_mixin import PageBase
from ..common.chartkit import (
    C_LOW, C_P1, C_P2, C_P3, C_POSITIVE, C_STABLE,
    RingGauge, build_donut, build_grouped_bar, build_line_chart,
    build_stacked_bar, make_chart_view,
)
from .analytics_data import load_analytics, range_options

#: 指标卡配置：(key, 标题)。「情绪状态」额外给一条说明。
_METRIC_SPECS = (
    ("students", "参与学生数"),
    ("mood", "情绪状态"),
    ("warnings", "心理预警数"),
    ("pending", "待处理求助数"),
    ("completion", "心理支持完成率"),
)


class _MetricCard(Card):
    """顶部核心指标卡：大数值 + 标题 + 可选说明。"""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        inner = self.body_layout()
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(4)
        self.value_label = make_label("—", "StatValue", word_wrap=False)
        inner.addWidget(self.value_label)
        inner.addWidget(make_label(title, "StatTitle", word_wrap=False))
        self.hint_label = make_label("", "Hint", word_wrap=False)
        self.hint_label.setVisible(False)
        inner.addWidget(self.hint_label)

    def set(self, value: str, hint: Optional[str] = None) -> None:
        self.value_label.setText(value)
        if hint:
            self.hint_label.setText(hint)
            self.hint_label.setVisible(True)
        else:
            self.hint_label.setVisible(False)


class AnalyticsPage(PageBase):
    """数据分析驾驶舱。"""

    PAGE_TITLE = "数据分析"

    def __init__(self, ctx, parent: Optional[QWidget] = None) -> None:
        super().__init__(ctx, parent)
        self._range_key = "30d"
        self._metric_cards: Dict[str, _MetricCard] = {}
        self._filter_buttons: Dict[str, QPushButton] = {}

        self._build_header()
        self._build_metrics()
        self._build_scroll()

        # 首次进入默认按 30 天渲染
        self._filter_buttons[self._range_key].setChecked(True)
        self._apply_range(self._range_key)

    # ------------------------------------------------------------------ 构建
    def _build_header(self) -> None:
        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(make_title("数据分析"))
        title_col.addWidget(make_hint("从全校视角看情绪、预警与心理支持的整体走向"))
        header.addLayout(title_col)
        header.addStretch(1)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for index, (key, label) in enumerate(range_options()):
            btn = QPushButton(label)
            btn.setObjectName("RangeChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.clicked.connect(lambda _=False, k=key: self._apply_range(k))
            self._filter_group.addButton(btn, index)
            self._filter_buttons[key] = btn
            header.addWidget(btn)
        self._root.addLayout(header)

    def _build_metrics(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)
        for key, title in _METRIC_SPECS:
            card = _MetricCard(title)
            self._metric_cards[key] = card
            row.addWidget(card, 1)
        self._root.addLayout(row)

    def _build_scroll(self) -> None:
        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._content)
        self._content_box.setContentsMargins(0, 4, 0, 0)
        self._content_box.setSpacing(14)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 数据
    def _apply_range(self, key: str) -> None:
        self._range_key = key
        data = load_analytics(key)
        self._render(data)

    def refresh(self) -> None:
        # 复用时间筛选（on_show 首次进入也会走这里）
        self._apply_range(self._range_key)

    # ------------------------------------------------------------------ 渲染
    def _render(self, data: Dict) -> None:
        self._render_metrics(data)
        self._rebuild_charts(data)

    def _render_metrics(self, data: Dict) -> None:
        m = data["metrics"]
        self._metric_cards["students"].set(f"{int(m['students'])} 人")
        self._metric_cards["mood"].set(
            f"{int(round(m['positive_ratio'] * 100))}%", "积极情绪占比")
        self._metric_cards["warnings"].set(str(int(m["warnings"])))
        self._metric_cards["pending"].set(str(int(m["pending_help"])))
        self._metric_cards["completion"].set(
            f"{int(round(m['completion_rate'] * 100))}%")

    def _rebuild_charts(self, data: Dict) -> None:
        self._clear_content()

        # 1) 情绪变化趋势（折线，通栏）
        self._content_box.addWidget(self._mood_trend_card(data))

        # 2) 情绪分布 + 预警来源（两个环形图）
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(self._donut_card(
            "全校情绪分布", data["mood_distribution"],
            [("positive", "积极", C_POSITIVE),
             ("stable", "平稳", C_STABLE),
             ("low", "低落", C_LOW)]), 1)
        row2.addWidget(self._donut_card(
            "心理预警来源", data["warning_source"],
            [("连续低落", "连续低落", C_P1),
             ("病史关注", "病史关注", C_P2),
             ("求助待处理", "求助待处理", C_P3)]), 1)
        self._content_box.addLayout(row2)

        # 3) 预警趋势（堆叠柱）+ 年级情绪对比（分组柱）
        row3 = QHBoxLayout()
        row3.setSpacing(14)
        row3.addWidget(self._warning_trend_card(data), 1)
        row3.addWidget(self._grade_card(data), 1)
        self._content_box.addLayout(row3)

        # 4) 心理支持工作（完成率环 + 待跟进 + 平均响应）
        self._content_box.addWidget(self._support_card(data))
        self._content_box.addStretch(1)

    # ------------------------------------------------------------------ 图表卡
    def _card(self, title: str, hint: Optional[str] = None) -> "tuple[Card, QVBoxLayout]":
        card = Card()
        inner = card.body_layout()
        inner.setContentsMargins(18, 14, 18, 16)
        inner.setSpacing(8)
        inner.addWidget(make_label(title, "SectionTitle", word_wrap=False))
        if hint:
            inner.addWidget(make_label(hint, "Hint", word_wrap=False))
        return card, inner

    def _mood_trend_card(self, data: Dict) -> Card:
        card, inner = self._card(
            "全校情绪变化趋势", "积极 / 平稳 / 低落 的每日提交人次")
        t = data["mood_trend"]
        series = [
            ("积极", t["positive"], C_POSITIVE),
            ("平稳", t["stable"], C_STABLE),
            ("低落", t["low"], C_LOW),
        ]
        chart = build_line_chart(t["labels"], series, t["display_labels"])
        inner.addWidget(make_chart_view(chart, min_height=280))
        return card

    def _donut_card(self, title: str, distribution: Dict,
                    spec: List) -> Card:
        card, inner = self._card(title)
        slices = [(display, float(distribution[key]), color)
                  for key, display, color in spec]
        chart = build_donut(slices)
        inner.addWidget(make_chart_view(chart, min_height=240))
        return card

    def _warning_trend_card(self, data: Dict) -> Card:
        card, inner = self._card("心理预警趋势", "P1 / P2 / P3 关注等级")
        t = data["warning_trend"]
        sets = [
            ("P1", t["p1"], C_P1),
            ("P2", t["p2"], C_P2),
            ("P3", t["p3"], C_P3),
        ]
        chart = build_stacked_bar(t["labels"], sets, t["display_labels"])
        inner.addWidget(make_chart_view(chart, min_height=250))
        return card

    def _grade_card(self, data: Dict) -> Card:
        card, inner = self._card("各年级情绪状态对比")
        g = data["grade_mood"]
        sets = [
            ("积极", g["positive"], C_POSITIVE),
            ("平稳", g["stable"], C_STABLE),
            ("低落", g["low"], C_LOW),
        ]
        chart = build_grouped_bar(g["labels"], sets)
        inner.addWidget(make_chart_view(chart, min_height=250))
        return card

    def _support_card(self, data: Dict) -> Card:
        card, inner = self._card("心理支持工作")
        s = data["support"]
        rate = float(s["completion_rate"]) * 100

        body = QHBoxLayout()
        body.setSpacing(20)

        gauge = RingGauge(C_POSITIVE, size=128)
        gauge.set_percent(rate)
        body.addWidget(gauge)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(make_label("心理支持完成率", "StatTitle", word_wrap=False))
        bar = Progress()
        bar.set_progress(int(round(rate)), 100)
        right.addWidget(bar)
        right.addWidget(make_label(f"已完成 {int(round(rate))}%", "Hint", word_wrap=False))

        pending = QHBoxLayout()
        pending.addWidget(make_label("待跟进任务", "StatTitle", word_wrap=False))
        pending.addStretch(1)
        pending.addWidget(make_label(f"{int(s['pending_tasks'])} 项", "Heading", word_wrap=False))
        right.addLayout(pending)

        resp = QHBoxLayout()
        resp.addWidget(make_label("平均响应时间", "StatTitle", word_wrap=False))
        resp.addStretch(1)
        resp.addWidget(make_label(f"{int(s['avg_response_min'])} 分钟", "Heading", word_wrap=False))
        right.addLayout(resp)
        right.addStretch(1)

        body.addLayout(right, 1)
        inner.addLayout(body)
        return card

    # ------------------------------------------------------------------ 工具
    def _clear_content(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif child.layout() is not None:
                AnalyticsPage._clear_layout(child.layout())
