# -*- coding: utf-8 -*-
"""空状态/加载占位（居中、次要文字色）。对应 HTML 雏形 #placeholder。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_common.widgets import make_label


class EmptyState(QWidget):
    """占满父容器的居中文案；set_text 切换"加载中…/暂无数据/错误说明"。"""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self._label = make_label(text, "Hint", parent=self)
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
