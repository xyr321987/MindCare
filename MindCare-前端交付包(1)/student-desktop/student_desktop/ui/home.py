# -*- coding: utf-8 -*-
"""「见山」学生端首页（第一轮 UI 还原：整体布局 + 视觉基调）。

结构（自上而下）:
    ① 顶部欢迎区：左侧欢迎文字，右侧山峦插画
    ② 核心功能区：问卷 / 树洞 / 预约 / 我的档案 四张卡片横向排列
    ③ 内容辅助区：最近活动（左）+ 今日的小纸条（右）并列
    ④ 底部提示区：「慢慢来，也算在前进。」+ 山峰装饰

纪律：
* 本页**不产生中文界面字面量**，全部从 `COPY` 取（见 `desktop_common/copy.py`）。
* 本页**不发网络请求**：欢迎语 / 最近活动由主窗口注入（`set_profile` / `set_activity`），
  小纸条文案从文案表轮换，保证主线程零传输（UI约定 §3）。
* 插画用 `QPainter` 本地绘制（无外部图片资源、无远程链接），风格统一为简约线稿 + 柔和色块。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
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

from desktop_common import theme
from desktop_common.copy import COPY
from desktop_common.widgets import Card, make_hint, make_label

__all__ = ["HomePage"]

#: 小纸条轮换文案键（顺序即轮换顺序）
_NOTE_KEYS = ("home.note.1", "home.note.2", "home.note.3", "home.note.4")

#: 四张功能卡片的配色（`tone` 动态属性 → 主题 QSS；`accent` 是插画主色）
_CARD_SPECS = (
    {"key": "questionnaire", "title": "c.tab.questionnaire", "desc": "home.card.questionnaire.desc",
     "accent": "#6E8B7E"},
    {"key": "treehole", "title": "s.treehole.tab.title", "desc": "home.card.treehole.desc",
     "accent": "#8A7A62"},
    {"key": "appointment", "title": "c.tab.appointment", "desc": "home.card.appointment.desc",
     "accent": "#355B4C"},
    {"key": "profile", "title": "c.tab.profile", "desc": "home.card.profile.desc",
     "accent": "#7E8A82"},
)


# --------------------------------------------------------------------------- 插画


class _MountainScene(QWidget):
    """简约山峦插画：太阳 + 云朵 + 两层山峰（QPainter 手绘，柔和色块）。"""

    def __init__(self, *, accent: str = "#355B4C", far: str = "#7E9A8E",
                 sun: str = "#E9C98F", cloud: str = "#FFFFFF",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self._far = QColor(far)
        self._sun = QColor(sun)
        self._cloud = QColor(cloud)
        self.setMinimumSize(140, 96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(Qt.NoPen)

        # 太阳（右上）
        r = w * 0.14
        painter.setBrush(self._sun)
        painter.drawEllipse(QRectF(w * 0.72, h * 0.06, r, r))

        # 云朵（左上，三枚椭圆叠加）
        painter.setBrush(self._cloud)
        painter.drawEllipse(QRectF(w * 0.06, h * 0.16, w * 0.20, h * 0.16))
        painter.drawEllipse(QRectF(w * 0.14, h * 0.08, w * 0.16, h * 0.20))
        painter.drawEllipse(QRectF(w * 0.20, h * 0.16, w * 0.18, h * 0.14))

        # 远山（浅）
        painter.setBrush(self._far)
        far_path = QPainterPath()
        far_path.moveTo(0, h)
        far_path.lineTo(w * 0.18, h * 0.42)
        far_path.lineTo(w * 0.36, h * 0.66)
        far_path.lineTo(w * 0.55, h * 0.40)
        far_path.lineTo(w * 0.74, h * 0.72)
        far_path.lineTo(w, h * 0.55)
        far_path.lineTo(w, h)
        far_path.closeSubpath()
        painter.drawPath(far_path)

        # 近山（深，主色）
        painter.setBrush(self._accent)
        near_path = QPainterPath()
        near_path.moveTo(0, h)
        near_path.lineTo(w * 0.28, h * 0.58)
        near_path.lineTo(w * 0.52, h * 0.82)
        near_path.lineTo(w * 0.76, h * 0.60)
        near_path.lineTo(w, h * 0.78)
        near_path.lineTo(w, h)
        near_path.closeSubpath()
        painter.drawPath(near_path)


class _MountainMark(QWidget):
    """极简山峰线稿（底部提示区的小装饰）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 26)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = painter.pen()
        pen.setColor(QColor(theme.BRAND))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(4, self.height() - 3)
        path.lineTo(self.width() * 0.36, 6)
        path.lineTo(self.width() * 0.52, self.height() * 0.55)
        path.lineTo(self.width() * 0.66, self.height() * 0.30)
        path.lineTo(self.width() - 4, self.height() - 3)
        painter.drawPath(path)


# --------------------------------------------------------------------------- 功能卡片


class _FeatureCard(QFrame):
    """核心功能卡片：插画 + 标题 + 描述 + 圆形箭头。"""

    clicked = Signal(str)

    def __init__(self, key: str, title: str, desc: str, accent: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeFeatureCard")
        self._key = key
        self.setProperty("tone", key)
        self.setCursor(Qt.PointingHandCursor)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(18, 18, 18, 18)
        inner.setSpacing(10)

        self.art = _MountainScene(accent=accent, far="#C4CFC8", sun="#E9C98F")
        self.art.setMinimumHeight(90)
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
        self._content_layout.setContentsMargins(32, 28, 32, 28)
        self._content_layout.setSpacing(20)
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
        left.setSpacing(8)
        left.addStretch(1)
        self.hello_label = make_label("", "HomeHello", word_wrap=False)
        left.addWidget(self.hello_label)
        self.subtitle_label = make_label(COPY["home.welcome.subtitle"], "HomeSubtitle")
        left.addWidget(self.subtitle_label)
        left.addStretch(1)
        row.addLayout(left, 3)

        self.welcome_art = _MountainScene(
            accent=theme.BRAND, far="#7E9A8E", sun="#E9C98F")
        self.welcome_art.setMinimumHeight(150)
        self.welcome_art.setMaximumWidth(460)
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
                spec["accent"])
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
        activity_inner.setContentsMargins(20, 20, 20, 20)
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
        note_inner.setContentsMargins(24, 24, 24, 24)
        note_inner.setSpacing(12)
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
        self.note_sign = make_label(COPY["home.note.sign"], "HomeNoteSign")
        note_inner.addWidget(self.note_sign)
        note_inner.addStretch(1)
        row.addWidget(self.note_card, 2)

        self._content_layout.addLayout(row)
        self._apply_note()

    def _build_footer(self) -> None:
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(_MountainMark())
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
