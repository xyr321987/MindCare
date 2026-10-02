# -*- coding: utf-8 -*-
"""预警记录页（独立于分诊台，分诊台的 P1/P2/P3 保持原样不动）。

规则（用户确认；真值由服务端扫描计算，教师端只展示 + 约谈消除）：
- 同一学生「连续」3 次提交 mood=down 且 request_help=false → 出现 active 预警；
- 中途选了其他分支（happy / plain / down+求助）→ 服务端计数清零，预警不再出现；
- 老师约谈后手动消除 → dismissed 留痕（含时间与可选备注），计数同时清零。
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_label, make_primary_button, wrap_scroll,
)

from ...core import enums
from ...core.models import WarningRecord
from ..common.async_mixin import PageBase


class WarningsPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._all: List[WarningRecord] = []
        self._show_dismissed = False
        self._build_ui()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("预警记录", "PageTitle", word_wrap=False))
        titles.addWidget(make_label(
            "规则：连续 3 次「有点低落」且未求助会出现在这里；中途选择其他心情或求助则自动清零",
            "PageSub", word_wrap=False))
        head.addLayout(titles)
        head.addStretch(1)
        refresh_btn = make_primary_button("刷新")
        refresh_btn.clicked.connect(self.refresh)
        head.addWidget(refresh_btn, 0, Qt.AlignTop)
        self._root.addLayout(head)

        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._content)
        self._content_box.setContentsMargins(0, 4, 0, 0)
        self._content_box.setSpacing(12)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 加载
    def refresh(self) -> None:
        self.call(self.ctx.adapters.warning.list_all,
                  on_ok=self._on_loaded)

    def _on_loaded(self, records: List[WarningRecord]) -> None:
        self._all = records
        self._render()

    # ------------------------------------------------------------------ 渲染
    def _render(self) -> None:
        self._clear()
        active = [w for w in self._all if w.status == "active"]
        dismissed = [w for w in self._all if w.status != "active"]

        self._content_box.addWidget(
            make_label(f"进行中（{len(active)}）", "Heading", word_wrap=False))
        if active:
            for w in active:
                self._content_box.addWidget(self._active_card(w))
        else:
            self._content_box.addWidget(self._inline_hint("当前没有进行中的预警"))

        self._content_box.addSpacing(6)
        toggle = make_button(
            f"{'收起' if self._show_dismissed else '展开'}已消除记录（{len(dismissed)}）",
            "ghost")
        toggle.clicked.connect(self._toggle_dismissed)
        self._content_box.addWidget(toggle)

        if self._show_dismissed:
            if not dismissed:
                self._content_box.addWidget(self._inline_hint("还没有已消除的预警记录"))
            for w in dismissed:
                self._content_box.addWidget(self._dismissed_card(w))

        self._content_box.addStretch(1)

    def _active_card(self, w: WarningRecord) -> QFrame:
        card = QFrame()
        card.setObjectName("WarnActiveCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(make_label(f"{w.student_name} · {w.class_name}",
                                 "WarnTitle", word_wrap=False))
        row.addStretch(1)
        streak = make_label(f"连续低落 {w.streak_count} 次未求助",
                            "ChipWarn", word_wrap=False)
        row.addWidget(streak)
        lay.addLayout(row)

        lay.addWidget(make_label(enums.ALERT_RULE.get(
            w.rule, "连续多次低落且未求助，可以主动关心一下"), "Body"))
        lay.addWidget(make_label(
            f"最近一次提交：{enums.relative_day_text(w.latest_ts)}"
            f" {enums.short_time(w.latest_ts)}", "Hint"))

        btn = make_primary_button("已约谈，消除预警")
        btn.clicked.connect(lambda: self._dismiss(w))
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn)
        lay.addLayout(btn_row)
        return card

    def _dismissed_card(self, w: WarningRecord) -> QFrame:
        card = QFrame()
        card.setObjectName("WarnDismissedCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(make_label(f"{w.student_name} · {w.class_name}",
                                 "WarnTitleOff", word_wrap=False))
        row.addStretch(1)
        row.addWidget(make_label(
            f"{enums.relative_day_text(w.dismissed_at)} 已约谈消除",
            "Hint", word_wrap=False))
        lay.addLayout(row)
        if w.dismiss_note:
            lay.addWidget(make_label(f"约谈记录：{w.dismiss_note}", "Hint"))
        return card

    @staticmethod
    def _inline_hint(text: str) -> QWidget:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 18, 18, 18)
        label = make_label(text, "Hint")
        label.setAlignment(Qt.AlignCenter)
        lay.addWidget(label)
        return box

    # ------------------------------------------------------------------ 动作
    def _toggle_dismissed(self) -> None:
        self._show_dismissed = not self._show_dismissed
        self._render()

    def _dismiss(self, w: WarningRecord) -> None:
        note, ok = QInputDialog.getMultiLineText(
            self, "约谈记录",
            f"记录与 {w.student_name} 的约谈情况（可选，留档可查）：", "")
        if not ok:
            return
        note = note.strip() or None

        def _ok(_record):
            self.show_toast("预警已消除，记录已保留")
            self.refresh()

        self.call(self.ctx.adapters.warning.dismiss, w.warning_id, note,
                  on_ok=_ok,
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "操作失败，请再试一次")))

    # ------------------------------------------------------------------ 工具
    def _clear(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
