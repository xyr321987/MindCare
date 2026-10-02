"""Tab2「树洞」：列表（按天）+ 编辑器（大输入框 + 保存）。

**L0 绝对私密**（契约 §2.6/§2.7 + UI约定 §5.1）：

* 界面上**不存在**任何"分享 / 公开 / 让老师看 / 可见性"控件或文案；
* 请求体里**没有** `visibility` 字段（契约没有这个字段——树洞没有授权开关）；
  本模块的模块级常量 `VISIBILITY` 仅用于把"恒为私密"这件事写成可断言的代码事实；
* 文案一律来自文案表（`s.treehole.*`），本文件不出现中文界面字面量。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
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
    make_error,
    make_ghost_button,
    make_hint,
    make_primary_button,
    make_title,
)

__all__ = ["TreeholeTab", "VISIBILITY"]

#: 树洞的可见性恒为私密（契约里树洞**没有**可见性字段；这里是"无开关"的代码事实）
VISIBILITY = "private"


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
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("TreeholeList")
        self.list_widget.setFocusPolicy(Qt.StrongFocus)
        list_card.add(self.list_widget, 1)
        self.empty_label = make_hint(COPY["s.treehole.list.empty"])
        list_card.add(self.empty_label)
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
        self.list_widget.clear()
        if not entries:
            self.empty_label.setVisible(True)
            return
        self.empty_label.setVisible(False)
        for entry in entries:
            # 机器格式的 `2026-10-02T21:40:00+08:00` 不给人看：统一走
            # `format_ts_human()`（全应用唯一的格式化点，见 `desktop_common/api.py`）
            ts = format_ts_human(entry.get("ts"))
            content = str(entry.get("content") or "")
            mood_tag = entry.get("mood_tag")
            item = QListWidgetItem(f"{ts}\n{content}" if ts else content)
            if mood_tag:
                item.setToolTip(str(mood_tag))
            item.setData(Qt.UserRole, entry.get("entry_id"))
            self.list_widget.addItem(item)

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
