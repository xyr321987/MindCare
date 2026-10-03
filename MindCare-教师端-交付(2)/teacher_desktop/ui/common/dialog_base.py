# -*- coding: utf-8 -*-
"""弹窗基类：高度自适应 + 内容纵向滚动 + 头部可拖拽 + 右下角可缩放。

全部业务弹窗统一继承 `BaseDialog`，四件事开箱即用：

1. **高度自适应**：最大高度 = 屏幕可用高度 × 0.8（防底部教师信息/按钮溢出视口）；
2. **内部滚动**：内容区放进 QScrollArea（overflow-y: auto），内容多时纵向滚动；
3. **头部拖拽**：按住头部标题/说明区域拖动即可移动整个弹窗（`DialogHeader`）；
4. **缩放**：右下角 QSizeGrip 调整大小；原生标题栏自带最小化/最大化。

用法（子类）::

    class XxxDialog(BaseDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("…")
            self.setMinimumWidth(400)
            self.set_header("标题", "说明")        # 可拖拽头部
            self.add_to_content(...)               # 内容进滚动区
            self.set_buttons(buttons)              # 按钮固定在底部，不随内容滚动

QSS（见 ui/teacher_qss.py）：`QFrame#DialogHeader`（头部样式）、
`QScrollArea#PageScroll` / `QWidget#PageScrollContent`（透明滚动区）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QScrollArea, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_hint, make_label

__all__ = ["BaseDialog", "DialogHeader"]


class DialogHeader(QFrame):
    """可拖拽的弹窗头部：按住标题/说明区域拖动即可移动整个弹窗。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DialogHeader")
        self.setCursor(Qt.SizeAllCursor)
        self._drag_offset: Optional[QPoint] = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.window().frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class BaseDialog(QDialog):
    """弹窗基类（高度自适应 + 内部滚动 + 可拖拽 + 可缩放）。"""

    #: 最大高度 = 屏幕可用高度 × 该比例（防溢出视口）
    MAX_HEIGHT_RATIO = 0.8

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)

        # 1) 高度自适应：不超过屏幕可用高度 80%
        avail_h = QGuiApplication.primaryScreen().availableGeometry().height()
        self.setMaximumHeight(int(avail_h * self.MAX_HEIGHT_RATIO))
        # 4) 右下角调整大小手柄（缩放）
        self.setSizeGripEnabled(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)

        # 3) 可拖拽头部（标题/说明由 set_header 填充）
        self._header = DialogHeader(self)
        self._header_box = QVBoxLayout(self._header)
        self._header_box.setContentsMargins(0, 0, 0, 8)
        self._header_box.setSpacing(2)
        outer.addWidget(self._header)

        # 2) 内容滚动区（overflow-y: auto）
        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._scroll_content)
        self._content_box.setContentsMargins(0, 0, 0, 0)
        self._content_box.setSpacing(10)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("PageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setWidget(self._scroll_content)
        outer.addWidget(self._scroll, 1)

        # 底部固定区（按钮等，不随内容滚动）
        self._footer_box = QVBoxLayout()
        self._footer_box.setSpacing(10)
        outer.addLayout(self._footer_box)

    # ------------------------------------------------------------------ 头部
    def set_header(self, title: str, hint: Optional[str] = None) -> None:
        """设置头部标题（+ 可选说明）。文字透传鼠标事件，按住文字也能拖动。"""
        title_label = make_label(title, "CardTitle", word_wrap=False)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._header_box.addWidget(title_label)
        if hint:
            hint_label = make_hint(hint)
            hint_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._header_box.addWidget(hint_label)

    # ------------------------------------------------------------------ 内容区
    def content_layout(self) -> QVBoxLayout:
        """滚动区内侧的布局：内容都加到这里。"""
        return self._content_box

    def add_to_content(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._content_box.addWidget(widget, stretch)
        return widget

    def add_content_layout(self, layout) -> None:
        self._content_box.addLayout(layout)

    # ------------------------------------------------------------------ 底部
    def footer_layout(self) -> QVBoxLayout:
        return self._footer_box

    def add_to_footer(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._footer_box.addWidget(widget, stretch)
        return widget

    def add_footer_layout(self, layout) -> None:
        self._footer_box.addLayout(layout)

    def set_buttons(self, buttons: QDialogButtonBox) -> QDialogButtonBox:
        """把按钮盒固定在底部（不随内容滚动）。"""
        self._footer_box.addWidget(buttons)
        return buttons
