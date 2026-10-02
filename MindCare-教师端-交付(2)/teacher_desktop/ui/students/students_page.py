# -*- coding: utf-8 -*-
"""学生管理页：病史标记 + 重置密码。

学生名单来自分诊列表（全部注册学生）；病史/密码操作走 StudentAdminAdapter（/db）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QInputDialog, QHBoxLayout, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_label, make_primary_button, wrap_scroll,
)

from ...core.triage_client import TriageClient
from ..common.async_mixin import PageBase


class StudentsPage(PageBase):
    PAGE_TITLE = "学生管理"

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._build_ui()

    def _build_ui(self) -> None:
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("学生管理", "PageTitle", word_wrap=False))
        titles.addWidget(make_label("标记病史（分诊 P1 依据）与重置学生密码", "PageSub", word_wrap=False))
        head.addLayout(titles)
        head.addStretch(1)
        refresh_btn = make_primary_button("刷新")
        refresh_btn.clicked.connect(self.refresh)
        head.addWidget(refresh_btn)
        self._root.addLayout(head)

        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._box = QVBoxLayout(self._content)
        self._box.setContentsMargins(0, 4, 0, 0)
        self._box.setSpacing(10)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 加载
    def refresh(self) -> None:
        def _job():
            data = self.ctx.triage.triage_list()
            return TriageClient.parse_items(data)
        self.call(_job, on_ok=self._render)

    def _render(self, items) -> None:
        self._clear()
        if not items:
            self._box.addWidget(make_label("还没有学生注册", "Hint"))
        for it in items:
            self._box.addWidget(self._row(it))
        self._box.addStretch(1)

    # ------------------------------------------------------------------ 行
    def _row(self, item) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(10)
        name = make_label(f"{item.name} · {item.class_name}", "Body", word_wrap=False)
        name.setMinimumWidth(180)
        h.addWidget(name)
        history = bool(item.flags.has_history)
        hist_btn = make_button("取消病史" if history else "标记病史",
                               "AccentButton" if history else "ghost")
        hist_btn.clicked.connect(lambda _=False, sid=item.student_id, cur=history:
                                 self._toggle_history(sid, cur))
        h.addWidget(hist_btn)
        reset_btn = make_button("重置密码", "ghost")
        reset_btn.clicked.connect(lambda _=False, sid=item.student_id, nm=item.name:
                                  self._reset_password(sid, nm))
        h.addWidget(reset_btn)
        h.addStretch(1)
        return w

    # ------------------------------------------------------------------ 动作
    def _toggle_history(self, student_id: str, current: bool) -> None:
        def _job():
            return self.ctx.adapters.student_admin.set_history(student_id, not current)
        self.call(_job, on_ok=lambda _d: (self.show_toast("已更新病史标记"), self.refresh()),
                  on_fail=lambda e: self.show_toast(getattr(e, "message", "操作失败")))

    def _reset_password(self, student_id: str, name: str) -> None:
        text, ok = QInputDialog.getText(self, "重置密码", f"为 {name} 设置新密码（至少 4 位）")
        if not ok or len(text.strip()) < 4:
            return

        def _job():
            return self.ctx.adapters.student_admin.reset_password(student_id, text.strip())
        self.call(_job, on_ok=lambda _d: self.show_toast("密码已重置"),
                  on_fail=lambda e: self.show_toast(getattr(e, "message", "重置失败")))

    # ------------------------------------------------------------------ 工具
    def _clear(self) -> None:
        while self._box.count():
            item = self._box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
