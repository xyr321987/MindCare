# -*- coding: utf-8 -*-
"""提示横幅：断网/同步失败时显示，默认隐藏。对应 HTML 雏形 #banner。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from desktop_common.widgets import make_label


class Banner(QFrame):
    """暖米色横条；set_message 显示，clear 隐藏。无动画（仅显隐）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setFocusPolicy(Qt.NoFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self._label = make_label("", "BannerText", parent=self)
        layout.addWidget(self._label)
        self.setVisible(False)

    def set_message(self, text: str) -> None:
        self._label.setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self._label.setText("")
        self.setVisible(False)
