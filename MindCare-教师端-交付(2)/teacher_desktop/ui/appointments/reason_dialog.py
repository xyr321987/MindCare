# -*- coding: utf-8 -*-
"""单行文本输入弹窗（取消原因 / 爽约备注等）。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLineEdit, QVBoxLayout,
)

from desktop_common.widgets import make_label


class ReasonDialog(QDialog):
    """输入一条原因/备注。accepted 后读 text。"""

    def __init__(self, title: str, label: str, ok_text: str,
                 placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        layout.addWidget(make_label(label, "CardTitle", word_wrap=False))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def text(self) -> Optional[str]:
        value = self.edit.text().strip()
        return value or None
