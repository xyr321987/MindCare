# -*- coding: utf-8 -*-
"""回复库页面：自由条目的增 / 改 / 启停 / 删（CRUD）。

每条卡片：正文 + 场景标签 + 状态（启用中/已停用）+ 操作按钮。
数据来自 ReplyAdapter；保存后服务端按场景标签把文案下发给学生端结束页。
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_label, make_primary_button, wrap_scroll,
)

from ...core import enums
from ...core.models import ReplyEntry
from ..common.async_mixin import PageBase
from .reply_editor import ReplyEditDialog


class RepliesPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._entries: List[ReplyEntry] = []
        self._build_ui()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("回复库", "PageTitle", word_wrap=False))
        titles.addWidget(make_label(
            "编辑学生完成小测评后看到的回复与心情小贴士，保存即对学生端生效",
            "PageSub", word_wrap=False))
        head.addLayout(titles)
        head.addStretch(1)
        new_btn = make_primary_button("＋ 新建条目")
        new_btn.clicked.connect(self._create)
        head.addWidget(new_btn, 0, Qt.AlignTop)
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
        self.call(self.ctx.adapters.reply.list_all, on_ok=self._on_loaded)

    def _on_loaded(self, entries: List[ReplyEntry]) -> None:
        self._entries = entries
        self._render()

    # ------------------------------------------------------------------ 渲染
    def _render(self) -> None:
        self._clear()
        if not self._entries:
            self._content_box.addWidget(
                self._inline_hint("回复库还是空的，点右上角「新建条目」开始"))
        for entry in self._entries:
            self._content_box.addWidget(self._card(entry))
        self._content_box.addStretch(1)

    def _card(self, entry: ReplyEntry) -> QFrame:
        card = QFrame()
        card.setObjectName("ReplyCard")
        card.setProperty("enabled", "true" if entry.enabled else "false")
        card.style().unpolish(card)
        card.style().polish(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        # 正文
        body = make_label(entry.text, "Body")
        body.setEnabled(entry.enabled)
        lay.addWidget(body)

        # 场景 chips + 状态
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for scene in entry.scenes:
            chip_row.addWidget(make_label(
                enums.RESULT_SCENES.get(scene, scene), "ChipMist", word_wrap=False))
        chip_row.addStretch(1)
        chip_row.addWidget(make_label(
            "启用中" if entry.enabled else "已停用",
            "ChipSprout" if entry.enabled else "TableHead", word_wrap=False))
        lay.addLayout(chip_row)

        # 操作
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        edit_btn = make_button("编辑", "ghost")
        edit_btn.clicked.connect(lambda: self._edit(entry))
        action_row.addWidget(edit_btn)

        toggle_btn = make_button(
            "停用" if entry.enabled else "启用", "ghost")
        toggle_btn.clicked.connect(lambda: self._toggle(entry))
        action_row.addWidget(toggle_btn)

        del_btn = make_button("删除", "ghost")
        del_btn.clicked.connect(lambda: self._delete(entry))
        action_row.addWidget(del_btn)
        lay.addLayout(action_row)
        return card

    @staticmethod
    def _inline_hint(text: str) -> QWidget:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 22, 18, 22)
        label = make_label(text, "Hint")
        label.setAlignment(Qt.AlignCenter)
        lay.addWidget(label)
        return box

    # ------------------------------------------------------------------ CRUD
    def _create(self) -> None:
        dialog = ReplyEditDialog(self)
        if dialog.exec() != ReplyEditDialog.Accepted:
            return
        self.call(lambda: self.ctx.adapters.reply.create(
                      dialog.text_value, dialog.scenes),
                  on_ok=lambda _e: (self.show_toast("已新建条目"), self.refresh()),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "保存失败，请再试一次")))

    def _edit(self, entry: ReplyEntry) -> None:
        dialog = ReplyEditDialog(self, text=entry.text, scenes=entry.scenes)
        if dialog.exec() != ReplyEditDialog.Accepted:
            return
        self.call(lambda: self.ctx.adapters.reply.update(
                      entry.reply_id,
                      text=dialog.text_value, scenes=dialog.scenes),
                  on_ok=lambda _e: (self.show_toast("已保存修改"), self.refresh()),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "保存失败，请再试一次")))

    def _toggle(self, entry: ReplyEntry) -> None:
        self.call(lambda: self.ctx.adapters.reply.update(
                      entry.reply_id, enabled=not entry.enabled),
                  on_ok=lambda _e: self.refresh(),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "操作失败，请再试一次")))

    def _delete(self, entry: ReplyEntry) -> None:
        answer = QMessageBox.question(
            self, "删除回复",
            f"确定删除这条回复吗？此操作在连接的数据库上不可撤销。\n\n「{entry.text[:24]}…」")
        if answer != QMessageBox.Yes:
            return
        self.call(lambda: self.ctx.adapters.reply.delete(entry.reply_id),
                  on_ok=lambda _r: (self.show_toast("已删除"), self.refresh()),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "删除失败，请再试一次")))

    # ------------------------------------------------------------------ 工具
    def _clear(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
