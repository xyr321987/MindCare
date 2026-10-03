# -*- coding: utf-8 -*-
"""回复条目编辑弹窗（新建/编辑共用）。

条目 = 正文（必填）+ 场景标签（至少 1 个）。场景与学生端 result_scene 对齐：
happy_end / plain_tips / help_sent / self_care。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QCheckBox, QDialogButtonBox, QGridLayout,
)

from desktop_common.widgets import TextArea, make_error, make_label

from ...core import enums
from ..common.dialog_base import BaseDialog


class ReplyEditDialog(BaseDialog):
    def __init__(self, parent=None, *, text: str = "",
                 scenes: Optional[List[str]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("回复条目")
        self.setMinimumWidth(460)

        is_edit = bool(text)
        self.set_header(
            "编辑回复" if is_edit else "新建回复",
            "学生会在完成小测评后的结束页看到这段话，也可以是让心情变好的小技巧")

        self.text_area = TextArea(
            placeholder="写下回复内容…（语气温和，避免诊断性措辞）",
            min_height=130)
        self.text_area.set_text_value(text)
        self.add_to_content(self.text_area)

        self.add_to_content(make_label("用于哪些场景（至少选一个）", "Body",
                                       word_wrap=False))
        self._scene_checks = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        selected = set(scenes or [])
        for index, (key, label_text) in enumerate(enums.RESULT_SCENES.items()):
            check = QCheckBox(label_text)
            check.setChecked(key in selected)
            self._scene_checks[key] = check
            grid.addWidget(check, index // 2, index % 2)
        self.add_content_layout(grid)

        self.error_label = make_error("")
        self.add_to_content(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        self.set_buttons(buttons)

    def _validate_and_accept(self) -> None:
        if not self.text_area.text_value():
            self.error_label.setText("请先填写回复内容")
            return
        if not self.scenes:
            self.error_label.setText("请至少选择一个使用场景")
            return
        self.accept()

    @property
    def text_value(self) -> str:
        return self.text_area.text_value()

    @property
    def scenes(self) -> List[str]:
        return [key for key, check in self._scene_checks.items() if check.isChecked()]
