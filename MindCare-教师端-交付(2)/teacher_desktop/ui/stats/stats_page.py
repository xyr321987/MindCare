# -*- coding: utf-8 -*-
"""排班统计页 —— 按日期区间聚合预约量 / 完成率，并按教师 / 咨询室 / 状态分组。

数据全部来自服务端 `stats.appointments`（只读聚合），无模拟数据、不写库。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    Card, make_button, make_hint, make_label, wrap_scroll,
)

from ...core import enums
from ..common.async_mixin import PageBase


class _StatCard(Card):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatsCard")
        inner = self.body_layout()
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(6)
        self.value_label = make_label("0", "StatValue", word_wrap=False)
        inner.addWidget(self.value_label)
        inner.addWidget(make_label(title, "StatTitle", word_wrap=False))

    def set_text(self, text: str) -> None:
        self.value_label.setText(text)


class StatsPage(PageBase):
    PAGE_TITLE = "排班统计"

    def __init__(self, ctx, parent: Optional[QWidget] = None) -> None:
        super().__init__(ctx, parent)
        self._build_ui()

    def _build_ui(self) -> None:
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(make_label("排班统计", "PageTitle", word_wrap=False))
        title_col.addWidget(make_label("按日期区间查看预约量、完成率与教师/咨询室分布",
                                       "PageSub", word_wrap=False))
        header.addLayout(title_col)
        header.addStretch(1)

        self.start_edit = QDateEdit(QDate.currentDate().addDays(-29))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        header.addWidget(make_label("从", "Body", word_wrap=False))
        header.addWidget(self.start_edit)
        self.end_edit = QDateEdit(QDate.currentDate())
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        header.addWidget(make_label("到", "Body", word_wrap=False))
        header.addWidget(self.end_edit)

        refresh_btn = make_button("统计", "primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        self._root.addLayout(header)

        # ---- 统计卡
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        self.total_card = _StatCard("预约总量")
        self.done_card = _StatCard("已完成")
        self.rate_card = _StatCard("完成率")
        stats_row.addWidget(self.total_card, 1)
        stats_row.addWidget(self.done_card, 1)
        stats_row.addWidget(self.rate_card, 1)
        self._root.addLayout(stats_row)

        # ---- 分组明细
        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._content)
        self._content_box.setContentsMargins(0, 4, 0, 0)
        self._content_box.setSpacing(14)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 数据
    def refresh(self) -> None:
        start = self.start_edit.date().toString("yyyy-MM-dd")
        end = self.end_edit.date().toString("yyyy-MM-dd")
        if start > end:
            self.show_toast("起始日期不能晚于结束日期")
            return

        def _job():
            return self.ctx.adapters.scheduling.stats(start, end)

        self.call(_job, on_ok=self._render)

    def _render(self, data: dict) -> None:
        self._clear_content()
        total = int(data.get("total") or 0)
        done = int(data.get("done") or 0)
        rate = float(data.get("completion_rate") or 0)
        self.total_card.set_text(str(total))
        self.done_card.set_text(str(done))
        self.rate_card.set_text(f"{int(round(rate * 100))}%")

        self._content_box.addWidget(
            make_label("按咨询室", "Heading", word_wrap=False))
        self._content_box.addWidget(self._breakdown(data.get("by_room") or {}))

        self._content_box.addWidget(
            make_label("按教师", "Heading", word_wrap=False))
        self._content_box.addWidget(self._breakdown(data.get("by_teacher") or {}))

        self._content_box.addWidget(
            make_label("按状态", "Heading", word_wrap=False))
        self._content_box.addWidget(self._status_breakdown(data.get("by_status") or {}))

        self._content_box.addStretch(1)

    def _breakdown(self, mapping: Dict[str, int]) -> QFrame:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(6)
        if not mapping:
            lay.addWidget(make_hint("区间内暂无预约"))
            return box
        for name, cnt in sorted(mapping.items(), key=lambda kv: -kv[1]):
            row = QHBoxLayout()
            row.addWidget(make_label(str(name), "Body"))
            row.addStretch(1)
            row.addWidget(make_label(f"{int(cnt)} 次", "StatTitle", word_wrap=False))
            lay.addLayout(row)
        return box

    def _status_breakdown(self, mapping: Dict[str, int]) -> QFrame:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(6)
        if not mapping:
            lay.addWidget(make_hint("区间内暂无预约"))
            return box
        for status, cnt in sorted(mapping.items(), key=lambda kv: -kv[1]):
            label = enums.APPT_STATUS.get(status, (status, ""))[0]
            row = QHBoxLayout()
            row.addWidget(make_label(label, "Body"))
            row.addStretch(1)
            row.addWidget(make_label(f"{int(cnt)} 次", "StatTitle", word_wrap=False))
            lay.addLayout(row)
        return box

    def _clear_content(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
