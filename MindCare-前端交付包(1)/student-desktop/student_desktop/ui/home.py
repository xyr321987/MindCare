# -*- coding: utf-8 -*-
"""「见山」学生端首页（第一/二轮 UI 还原：整体布局 + SVG 插画资源）。

结构（自上而下）:
    ① 顶部欢迎区：左侧欢迎文字，右侧山峦插画
    ② 核心功能区：问卷 / 树洞 / 预约 / 我的档案 四张卡片横向排列
    ③ 内容辅助区：最近活动（左）+ 今日的小纸条（右）并列
    ④ 底部提示区：「慢慢来，也算在前进。」+ 山峰装饰

纪律：
* 本页**不产生中文界面字面量**，全部从 `COPY` 取（见 `desktop_common/copy.py`）。
* 本页**不发网络请求**：欢迎语 / 最近活动由主窗口注入（`set_profile` / `set_activity`），
  小纸条文案从文案表轮换，保证主线程零传输（UI约定 §3）。
* 插画用**本地 SVG 资源**（`assets/`），经 `QSvgRenderer` 渲染，风格统一、便于替换维护。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_common.copy import COPY
from desktop_common.widgets import Card, make_hint, make_label

__all__ = ["HomePage", "svg_pixmap"]

#: 本地 SVG 插画资源目录（`student_desktop/assets/`）
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

#: 小纸条轮换文案键（顺序即轮换顺序）
_NOTE_KEYS = ("home.note.1", "home.note.2", "home.note.3", "home.note.4")

#: 四张功能卡片：`tone` 动态属性 → 主题 QSS；`art` 是 SVG 插画资源
_CARD_SPECS = (
    {"key": "questionnaire", "title": "c.tab.questionnaire", "desc": "home.card.questionnaire.desc",
     "art": "card_weather.svg"},
    {"key": "treehole", "title": "s.treehole.tab.title", "desc": "home.card.treehole.desc",
     "art": "card_treehole.svg"},
    {"key": "appointment", "title": "c.tab.appointment", "desc": "home.card.appointment.desc",
     "art": "card_calendar.svg"},
    {"key": "profile", "title": "c.tab.profile", "desc": "home.card.profile.desc",
     "art": "card_diary.svg"},
)


# --------------------------------------------------------------------------- SVG 工具


def svg_pixmap(name: str, width: int, height: int) -> QPixmap:
    """把 `assets/` 下的 SVG 渲染成透明底 `QPixmap`（文件缺失时返回空位图，不抛异常）。"""
    path = ASSETS_DIR / name
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
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


class _SvgArt(QWidget):
    """按控件尺寸等比缩放渲染一张 SVG 插画（本地资源，透明底）。"""

    def __init__(self, name: str, *, min_height: int = 88,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._name = name
        path = ASSETS_DIR / name
        self._renderer = QSvgRenderer(str(path)) if path.exists() else None
        self.setMinimumSize(120, min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._renderer is None or not self._renderer.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = self._renderer.defaultSize()
        if size.width() > 0 and size.height() > 0:
            scale = min(self.width() / size.width(), self.height() / size.height())
            w = size.width() * scale
            h = size.height() * scale
            x = (self.width() - w) / 2.0
            y = (self.height() - h) / 2.0
            self._renderer.render(painter, QRectF(x, y, w, h))
        painter.end()


# --------------------------------------------------------------------------- 功能卡片


class _FeatureCard(QFrame):
    """核心功能卡片：插画 + 标题 + 描述 + 圆形箭头。"""

    clicked = Signal(str)

    def __init__(self, key: str, title: str, desc: str, art: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeFeatureCard")
        self._key = key
        self.setProperty("tone", key)
        self.setCursor(Qt.PointingHandCursor)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 20, 20, 20)
        inner.setSpacing(10)

        self.art = _SvgArt(art, min_height=96)
        inner.addWidget(self.art, 1)

        self.title_label = make_label(title, "HomeCardTitle", word_wrap=False)
        inner.addWidget(self.title_label)
        self.desc_label = make_label(desc, "HomeCardDesc")
        inner.addWidget(self.desc_label)

        arrow_row = QHBoxLayout()
        arrow_row.addStretch(1)
        self.arrow = QPushButton("→", self)
        self.arrow.setObjectName("HomeCardArrow")
        self.arrow.setCursor(Qt.PointingHandCursor)
        self.arrow.setFocusPolicy(Qt.StrongFocus)
        self.arrow.clicked.connect(lambda: self.clicked.emit(self._key))
        arrow_row.addWidget(self.arrow)
        inner.addLayout(arrow_row)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 点卡片任意处（除箭头按钮）也进入对应功能
        self.clicked.emit(self._key)
        super().mousePressEvent(event)


# --------------------------------------------------------------------------- 首页


class HomePage(QWidget):
    """「见山」首页。"""

    #: 请求切换到某个功能页：questionnaire / treehole / appointment / profile
    navigate = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._note_index = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("HomeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        content = QWidget()
        content.setObjectName("HomeScrollContent")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(40, 36, 40, 28)
        self._content_layout.setSpacing(24)
        self.scroll.setWidget(content)

        self._build_welcome()
        self._build_cards()
        self._build_aux()
        self._build_footer()
        self._content_layout.addStretch(1)

        self._relayout_cards()

    # ---------------------------------------------------------------- 构建

    def _build_welcome(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addStretch(1)
        self.hello_label = make_label("", "HomeHello", word_wrap=False)
        left.addWidget(self.hello_label)
        self.subtitle_label = make_label(COPY["home.welcome.subtitle"], "HomeSubtitle")
        left.addWidget(self.subtitle_label)
        left.addStretch(1)
        row.addLayout(left, 3)

        self.welcome_art = _SvgArt("welcome_scene.svg", min_height=170)
        self.welcome_art.setMaximumWidth(500)
        row.addWidget(self.welcome_art, 2)

        self._content_layout.addLayout(row)

    def _build_cards(self) -> None:
        self._cards_grid = QGridLayout()
        self._cards_grid.setHorizontalSpacing(20)
        self._cards_grid.setVerticalSpacing(20)
        self._cards: List[_FeatureCard] = []
        for spec in _CARD_SPECS:
            card = _FeatureCard(
                spec["key"], COPY[spec["title"]], COPY[spec["desc"]],
                spec["art"])
            card.clicked.connect(self.navigate.emit)
            self._cards.append(card)
        self._content_layout.addLayout(self._cards_grid)

    def _build_aux(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(20)

        # 最近活动（左）
        self.activity_card = Card()
        self.activity_card.setObjectName("HomeActivity")
        activity_inner = self.activity_card.body_layout()
        activity_inner.setContentsMargins(22, 22, 22, 22)
        activity_inner.setSpacing(10)
        self.activity_title = make_label(COPY["home.activity.title"], "HomeSectionTitle")
        activity_inner.addWidget(self.activity_title)
        self._activity_rows = QVBoxLayout()
        self._activity_rows.setSpacing(0)
        activity_inner.addLayout(self._activity_rows)
        self.activity_empty = make_hint(COPY["home.activity.empty"])
        self._activity_rows.addWidget(self.activity_empty)
        activity_inner.addStretch(1)
        row.addWidget(self.activity_card, 3)

        # 今日的小纸条（右）
        self.note_card = Card()
        self.note_card.setObjectName("HomeNote")
        note_inner = self.note_card.body_layout()
        note_inner.setContentsMargins(26, 26, 26, 26)
        note_inner.setSpacing(14)
        note_head = QHBoxLayout()
        note_head.addWidget(make_label(COPY["home.note.title"], "HomeNoteTitle", word_wrap=False))
        note_head.addStretch(1)
        self.note_change = QPushButton(COPY["home.note.change"], self.note_card)
        self.note_change.setObjectName("GhostButton")
        self.note_change.setCursor(Qt.PointingHandCursor)
        self.note_change.setFocusPolicy(Qt.StrongFocus)
        self.note_change.clicked.connect(self._cycle_note)
        note_head.addWidget(self.note_change)
        note_inner.addLayout(note_head)
        self.note_text = make_label("", "HomeNoteText")
        self.note_text.setWordWrap(True)
        note_inner.addWidget(self.note_text)
        # 底部：署名（左）+ 植物小插画（右下角，呼应「手写便签」）
        note_bottom = QHBoxLayout()
        self.note_sign = make_label(COPY["home.note.sign"], "HomeNoteSign")
        note_bottom.addWidget(self.note_sign)
        note_bottom.addStretch(1)
        plant = QLabel(self.note_card)
        plant.setPixmap(svg_pixmap("note_plant.svg", 56, 48))
        plant.setFixedSize(56, 48)
        note_bottom.addWidget(plant)
        note_inner.addLayout(note_bottom)
        note_inner.addStretch(1)
        row.addWidget(self.note_card, 2)

        self._content_layout.addLayout(row)
        self._apply_note()

    def _build_footer(self) -> None:
        footer = QHBoxLayout()
        footer.addStretch(1)
        mark = QLabel(self)
        mark.setObjectName("HomeFooterMark")
        mark.setPixmap(svg_pixmap("footer_mark.svg", 44, 26))
        mark.setFixedSize(44, 26)
        footer.addWidget(mark)
        footer.addSpacing(8)
        footer.addWidget(make_label(COPY["home.footer.line"], "HomeFooter"))
        footer.addStretch(1)
        self._content_layout.addLayout(footer)

    # ---------------------------------------------------------------- 响应式

    def _relayout_cards(self) -> None:
        """四张卡片：宽窗口横向四列，窄窗口自动两列（禁止横向溢出）。"""
        cols = 4 if self.width() >= 1080 else 2
        for i, card in enumerate(self._cards):
            row, col = divmod(i, cols)
            self._cards_grid.addWidget(card, row, col)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_cards()

    # ---------------------------------------------------------------- 数据注入

    def set_profile(self, profile: Optional[dict]) -> None:
        """登录后由主窗口注入：刷新欢迎语里的学生姓名。"""
        profile = profile or {}
        name = str(profile.get("name") or "").strip()
        self.hello_label.setText(
            COPY["home.welcome.hello"].replace("{name}", name))

    def set_activity(self, items: List[dict]) -> None:
        """刷新「最近活动」（每项 `{text, time}`；无数据时显示友好空状态）。"""
        while self._activity_rows.count():
            item = self._activity_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not items:
            self.activity_empty = make_hint(COPY["home.activity.empty"])
            self._activity_rows.addWidget(self.activity_empty)
            return
        for entry in items:
            row = QFrame()
            row.setObjectName("HomeActivityRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 10, 0, 10)
            lay.setSpacing(8)
            lay.addWidget(make_label(str(entry.get("text") or ""), "HomeActivityText"))
            lay.addStretch(1)
            lay.addWidget(make_label(str(entry.get("time") or ""), "HomeActivityTime"))
            self._activity_rows.addWidget(row)

    # ---------------------------------------------------------------- 内部

    def _apply_note(self) -> None:
        key = _NOTE_KEYS[self._note_index % len(_NOTE_KEYS)]
        self.note_text.setText(COPY[key])

    def _cycle_note(self) -> None:
        self._note_index += 1
        self._apply_note()
