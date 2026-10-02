"""Tab2「树洞」：列表（按天）+ 编辑器（大输入框 + 保存）。

**L0 绝对私密**（契约 §2.6/§2.7 + UI约定 §5.1）：

* 界面上**不存在**任何"分享 / 公开 / 让老师看 / 可见性"控件或文案；
* 请求体里**没有** `visibility` 字段（契约没有这个字段——树洞没有授权开关）；
  本模块的模块级常量 `VISIBILITY` 仅用于把"恒为私密"这件事写成可断言的代码事实；
* 文案一律来自文案表（`s.treehole.*`），本文件不出现中文界面字面量。

列表区架构（2026-10-03 修复文字截断）：
旧实现 `QListWidget + item.setSizeHint(row.sizeHint())` 在条目 widget
尚未被赋予列表宽度时就计算 sizeHint，正文（wordWrap 的 `QLabel`）按错误
宽度换行、高度被低估，最终列表项高度不足、文字被裁剪。现改为与
「我的档案」`ProfileTab` 一致的 `QScrollArea + QVBoxLayout`：布局管理器
在真实宽度下逐条计算高度，窗口缩放时自动重排。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from desktop_common.api import format_ts_human
from desktop_common.copy import COPY
from desktop_common.widgets import (
    Card,
    ChoiceGroup,
    TextArea,
    make_badge,
    make_body,
    make_error,
    make_ghost_button,
    make_hint,
    make_primary_button,
    make_title,
    wrap_scroll,
)

__all__ = ["TreeholeTab", "TreeholeEntryRow", "VISIBILITY", "MOODTAG_COPY"]

#: 树洞的可见性恒为私密（契约里树洞**没有**可见性字段；这里是"无开关"的代码事实）
VISIBILITY = "private"

#: 情绪标记 → 文案 ID（与编辑器 `mood_group` 的选项同源，保证卡片与选项措辞一致）
MOODTAG_COPY: Dict[str, str] = {
    "happy": "s.treehole.moodtag.option.happy",
    "plain": "s.treehole.moodtag.option.plain",
    "down": "s.treehole.moodtag.option.down",
}

#: 情绪标记 → 徽标色调（happy=平静绿 / plain=雾蓝 / down=柔珊瑚，与教师端心情圆点一致）
MOODTAG_TONE: Dict[str, str] = {
    "happy": "calm",
    "plain": "mist",
    "down": "coral",
}


def moodtag_text(mood_tag: Optional[str]) -> str:
    """情绪标记 → 可读文案；不在映射里的值（含 `None`）一律返回空串。"""
    return COPY[MOODTAG_COPY[mood_tag]] if mood_tag in MOODTAG_COPY else ""


class TreeholeEntryRow(Card):
    """一条树洞条目：时间 + **可见的情绪卡片** + 正文。

    情绪标记（`mood_tag`）此前只被放进 tooltip，悬停才看得到；现在渲染成常驻的
    可见徽标（情绪卡片），学生扫一眼列表就能看到自己当时标记的心情。
    """

    def __init__(self, entry: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.entry_id = str(entry.get("entry_id") or "")
        self.mood_tag = entry.get("mood_tag")

        head = QHBoxLayout()
        head.setSpacing(10)
        ts = format_ts_human(entry.get("ts"))
        if ts:
            head.addWidget(make_hint(ts))
        head.addStretch(1)
        self.badge: Optional[QLabel] = None
        text = moodtag_text(self.mood_tag)
        if text:
            self.badge = make_badge(text, tone=MOODTAG_TONE.get(self.mood_tag, "mist"))
            head.addWidget(self.badge)
        self.add_layout(head)

        content = str(entry.get("content") or "")
        if content:
            self.add(make_body(content))

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化后按新宽度锁定最小高度（防 wordWrap 正文被压成单行）。

        wordWrap 的 `QLabel` 其 `minimumSizeHint` 只有**单行**高度：布局
        纵向空间不足时正文会被压回单行、滚动区也不给足纵向空间 → 截断。
        这里每次 resize 都用 `totalHeightForWidth(width)` 算出该宽度下
        整卡内容（时间行 + 徽标 + 换行正文）真实需要的高度，显式设为
        最小高度；滚动区据此出现纵向滚动条，而不是压缩内容。
        """
        super().resizeEvent(event)
        lay = self.layout()
        if lay is None or self.width() <= 0:
            return
        self.setMinimumHeight(lay.totalHeightForWidth(self.width()))

    @property
    def mood_badge_text(self) -> str:
        """情绪卡片文本（自检按此断言，不依赖 Qt 渲染）；无标记返回空串。"""
        return self.badge.text() if self.badge is not None else ""


class TreeholeTab(QWidget):
    """树洞 Tab。网络请求通过信号交给主窗口的 `QThreadPool`。"""

    #: 请求我的树洞日期列表
    dates_requested = Signal()
    #: 请求某天的条目
    entries_requested = Signal(str)
    #: 保存一条新条目（body 已按契约构造好）
    save_requested = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("TreeholeTab")
        #: 让 QWidget 绘制 QSS 背景（树洞「暮蓝」环境光渐变，见 theme.build_qss）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dates: List[str] = []
        self._rows: List[TreeholeEntryRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        header = Card()
        header.add(make_title(COPY["s.treehole.entry.title"]))
        header.add(make_hint(COPY["s.treehole.entry.subtitle"]))
        header.add(make_badge(COPY["s.treehole.list.item.privacyBadge"], tone="calm"))
        header.add(make_hint(COPY["s.treehole.list.privacyNote"]))
        header.add(make_hint(COPY["s.treehole.list.noReadReceipt"]))
        outer.addWidget(header)

        body_row = QHBoxLayout()
        body_row.setSpacing(14)

        # ---------------- 左：列表 ----------------
        list_card = Card(title=COPY["s.treehole.list.title"])
        self.day_picker = QComboBox()
        self.day_picker.setObjectName("DayPicker")
        self.day_picker.setFocusPolicy(Qt.StrongFocus)
        self.day_picker.currentTextChanged.connect(self._on_day_changed)
        list_card.add(self.day_picker)

        # 条目列表：QScrollArea + 垂直布局（与 ProfileTab 同架构，见模块 docstring）。
        # `wrap_scroll` 的 `widgetResizable=True` 让 rows_host 始终与可视区同宽，
        # 布局在该宽度下逐条计算 wordWrap 正文高度，杜绝 setSizeHint 快照截断。
        self.rows_host = QWidget()
        self.rows_host.setObjectName("TreeholeRowsHost")
        self.list_layout = QVBoxLayout(self.rows_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)
        self.empty_label = make_hint(COPY["s.treehole.list.empty"])
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        self.list_scroll = wrap_scroll(self.rows_host)
        self.list_scroll.setObjectName("TreeholeScroll")
        list_card.add(self.list_scroll, 1)

        self.new_button = make_primary_button(COPY["s.treehole.list.new"])
        self.new_button.clicked.connect(self.open_editor)
        list_card.add(self.new_button)
        body_row.addWidget(list_card, 3)

        # ---------------- 右：编辑器 ----------------
        self.editor_card = Card(title=COPY["s.treehole.compose.title"])
        self.editor_area = TextArea(
            placeholder=COPY["s.treehole.compose.placeholder"], min_height=220)
        self.editor_card.add(self.editor_area)
        self.editor_card.add(make_badge(COPY["s.treehole.compose.privacyLabel"],
                                        tone="calm"))
        self.editor_card.add(make_hint(COPY["s.treehole.compose.privacyNote"]))
        self.editor_card.add(make_hint(COPY["s.treehole.moodtag.label"]))
        self.mood_group = ChoiceGroup((
            ("none", COPY["s.treehole.moodtag.option.none"]),
            ("happy", COPY["s.treehole.moodtag.option.happy"]),
            ("plain", COPY["s.treehole.moodtag.option.plain"]),
            ("down", COPY["s.treehole.moodtag.option.down"]),
        ), vertical=False)
        self.mood_group.set_value("none")
        self.editor_card.add(self.mood_group)
        self.editor_error = make_error("")
        self.editor_card.add(self.editor_error)
        self.editor_status = make_hint("")
        self.editor_status.setVisible(False)
        self.editor_card.add(self.editor_status)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.save_button = make_primary_button(COPY["s.treehole.compose.action.save"])
        self.save_button.clicked.connect(self._on_save)
        self.cancel_button = make_ghost_button(COPY["s.treehole.compose.action.cancel"])
        self.cancel_button.clicked.connect(self.close_editor)
        actions.addWidget(self.save_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        self.editor_card.add_layout(actions)
        body_row.addWidget(self.editor_card, 4)

        outer.addLayout(body_row, 1)
        self.close_editor()

    # ---------------------------------------------------------------- 对外

    @property
    def visibility(self) -> str:
        """恒为 `private`（树洞没有授权开关）。"""
        return VISIBILITY

    def open_editor(self) -> None:
        """打开编辑器（结果页「写树洞」深链的落点）。"""
        self.editor_card.setVisible(True)
        self.editor_area.setFocus(Qt.OtherFocusReason)
        self.editor_status.setVisible(False)
        self.editor_error.setVisible(False)

    def close_editor(self) -> None:
        self.editor_card.setVisible(False)
        self.editor_area.set_text_value("")
        self.mood_group.set_value("none")
        self.editor_error.setVisible(False)

    @property
    def editor_open(self) -> bool:
        return self.editor_card.isVisible()

    def set_dates(self, dates: List[str]) -> None:
        """更新有记录的日期。

        ⚠️ 与 `ProfileTab.set_dates()` 同一条纪律：**同一份日期列表重复传入时
        不重发 `entries_requested`**，避免同一个 `date` 有两个请求在飞、
        互相覆盖结果（详见 `ui/profile.py` 里那段说明）。
        """
        incoming = list(dates)
        if incoming == self._dates and incoming:
            return
        self._dates = incoming
        self.day_picker.blockSignals(True)
        self.day_picker.clear()
        for day in self._dates:
            self.day_picker.addItem(day)
        self.day_picker.blockSignals(False)
        if self._dates:
            self.day_picker.setCurrentIndex(len(self._dates) - 1)
            self.entries_requested.emit(self._dates[-1])

    def current_date(self) -> str:
        return self.day_picker.currentText()

    def set_entries(self, entries: List[dict]) -> None:
        """渲染某天的条目（逐条插到布局末尾 stretch 之前，最新在后）。"""
        self._clear_rows()
        if not entries:
            self.empty_label.setVisible(True)
            return
        self.empty_label.setVisible(False)
        for entry in entries:
            row = TreeholeEntryRow(entry)
            # 布局末尾固定挂着一个 stretch：新行插在它前面；隐藏的
            # empty_label 仍占布局位但不显示、不占空间。
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)

    def _clear_rows(self) -> None:
        """立即摘除旧条目卡片控件（`removeWidget` 摘布局 + `deleteLater` 回收；
        stretch 与空状态标签是布局骨架，不在清理范围）。"""
        for row in self._rows:
            self.list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def rows(self) -> List[TreeholeEntryRow]:
        """当前渲染的所有条目卡片（自检按此断言）。"""
        return list(self._rows)

    def show_saved(self, text: str) -> None:
        self.editor_area.set_text_value("")
        self.editor_error.setVisible(False)
        self.editor_status.setText(text)
        self.editor_status.setVisible(True)
        self.close_editor()

    def show_error(self, text: str) -> None:
        self.editor_status.setVisible(False)
        self.editor_error.setText(text)
        self.editor_error.setVisible(True)

    # ---------------------------------------------------------------- 内部

    def _on_day_changed(self, day: str) -> None:
        if day:
            self.entries_requested.emit(day)

    def _on_save(self) -> None:
        content = self.editor_area.text_value()
        if not content:
            self.show_error(COPY["s.treehole.compose.error.empty"])
            return
        mood = self.mood_group.value()
        body = {
            "content": content,
            "mood_tag": None if mood in (None, "none") else mood,
        }
        self.editor_error.setVisible(False)
        self.save_requested.emit(body)
