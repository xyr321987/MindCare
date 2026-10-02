# -*- coding: utf-8 -*-
"""本地 SVG 资源加载（教师端统一线性图标 + 插画）。

`assets/` 下的 SVG 经 `QSvgRenderer` 渲染成透明底 `QPixmap`。缺资源不抛异常，
返回空位图（界面不崩）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def svg_pixmap(name: str, width: int, height: int) -> QPixmap:
    """渲染 `assets/<name>` 到 `width×height` 透明底位图。"""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    path = ASSETS_DIR / name
    if not path.exists():
        return pixmap
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return pixmap
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return pixmap
