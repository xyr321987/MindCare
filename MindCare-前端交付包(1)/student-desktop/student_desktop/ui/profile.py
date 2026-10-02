"""Tab3「我的档案」：按日选择 + 当日/历史提交列表 + 日期打点。

**契约口径（v1.0）**：`GET /profile/me?date=` 的 `submissions[]` 只有
`record_id / ts / mood / cause_category / detail / request_help` —— **不返回**
`consent_share`，也**不返回**"这条是否已改回只有本人可见"。

因此本页的显示依据只有一个：**`request_help`**（契约强制
`consent_share == request_help`，所以它同时也等价于"这条是否共享给了老师"）。
措辞直接取文案表里与求助选择同源的键：

* `request_help=true` → `s.help.selected.request`（「已选择：老师可以看到你这次写的内容。」）
* `request_help=false` → `s.help.selected.no`（「已选择：内容只留在你这里。」）

**v1.0 没有事后收回可见性的能力**：`PATCH /questionnaire/submissions/{record_id}`
不在契约的 11 个端点里（服务端对该方法直接回 HTTP 501），所以本页**没有**任何
记录级操作按钮、没有二次确认、没有成功提示，也没有本机状态台账（旧版的台账类
已随降级删除）。界面不出现任何"改回去"类的入口文案，避免承诺服务端做不到的事。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_common.api import format_ts_human
from desktop_common.copy import COPY
from desktop_common.widgets import (
    Card,
    hotline_label,
    make_badge,
    make_body,
    make_error,
    make_ghost_button,
    make_heading,
    make_hint,
    make_title,
)

__all__ = ["ProfileTab", "RecordRow", "MOOD_COPY", "CAUSE_COPY", "STATUS_COPY"]

#: 心情枚举 → 文案 ID（`copywriting.md` §1.1）
MOOD_COPY: Dict[str, str] = {
    "happy": "s.q1.option.happy",
    "plain": "s.q1.option.plain",
    "down": "s.q1.option.down",
}

#: 原因枚举 → 文案 ID
CAUSE_COPY: Dict[str, str] = {
    "study": "s.q2.option.study",
    "relationship": "s.q2.option.relationship",
    "family": "s.q2.option.family",
}

#: 记录状态标签 → 文案 ID。
#: **只用文案表里已有、且与求助选择同源的键**（见模块 docstring），不自造字样。
STATUS_COPY: Dict[bool, str] = {
    True: "s.help.selected.request",
    False: "s.help.selected.no",
}


def mood_text(mood: Optional[str]) -> str:
    return COPY[MOOD_COPY[mood]] if mood in MOOD_COPY else ""


def cause_text(cause: Optional[str]) -> str:
    return COPY[CAUSE_COPY[cause]] if cause in CAUSE_COPY else ""


def status_text(request_help: bool) -> str:
    """`request_help` → 状态标签文案（v1.0 里它就是"这次有没有请求老师帮助"）。"""
    return COPY[STATUS_COPY[bool(request_help)]]


# --------------------------------------------------------------------------- 单条记录


class RecordRow(Card):
    """一条问卷记录：心情 + 原因 + 时间 + **是否请求了老师帮助**的状态标签 + 正文预览。

    v1.0：**没有**按钮（记录级操作入口已随契约降级移除），只有只读展示。
    """

    def __init__(self, record: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.record_id = str(record.get("record_id") or "")
        self.request_help = bool(record.get("request_help"))

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(make_heading(f"{mood_text(record.get('mood'))}"))
        cause = cause_text(record.get("cause_category"))
        if cause:
            head.addWidget(make_hint(f"{COPY['s.feedback.mine.categoryPrefix']}{cause}"))
        head.addWidget(make_hint(format_ts_human(record.get("ts"))))
        head.addStretch(1)
        self.badge = make_badge(
            status_text(self.request_help),
            tone="mist" if self.request_help else "calm",
        )
        self.badge.setObjectName("RecordBadge")
        head.addWidget(self.badge)
        self.add_layout(head)

        detail = str(record.get("detail") or "")
        if detail:
            preview = detail if len(detail) <= 120 else detail[:120] + "…"
            self.add(make_body(preview))

    @property
    def status(self) -> str:
        """该行的状态标签文本（自检按此断言，不依赖 Qt 渲染）。"""
        return self.badge.text()

    @property
    def label_text(self) -> str:
        """`status` 的别名（语义更直白）。"""
        return self.badge.text()


# --------------------------------------------------------------------------- 档案页


class ProfileTab(QWidget):
    """「我的档案」：按日选择 + 历史列表 + 日期打点。"""

    dates_requested = Signal()
    #: 请求某天档案（含提交与树洞）
    profile_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProfileTab")
        self._rows: List[RecordRow] = []
        self._dates: List[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        header = Card()
        header.add(make_title(COPY["s.notice.title"]))
        header.add(make_hint(COPY["s.help.body"]))
        picker_row = QHBoxLayout()
        picker_row.setSpacing(10)
        self.day_picker = QComboBox()
        self.day_picker.setObjectName("ProfileDayPicker")
        self.day_picker.setFocusPolicy(Qt.StrongFocus)
        self.day_picker.currentTextChanged.connect(self._on_day_changed)
        picker_row.addWidget(self.day_picker)
        picker_row.addStretch(1)
        self.refresh_button = make_ghost_button(COPY["c.action.retry"])
        self.refresh_button.clicked.connect(self.dates_requested.emit)
        picker_row.addWidget(self.refresh_button)
        header.add_layout(picker_row)
        outer.addWidget(header)

        self.toast = make_hint("")
        self.toast.setObjectName("ProfileToast")
        self.toast.setVisible(False)
        outer.addWidget(self.toast)

        self.error_label = make_error("")
        outer.addWidget(self.error_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("ProfileScroll")
        holder = QWidget()
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)
        self.empty_label = make_hint(COPY["c.empty.profile.submissions"])
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll, 1)

        footer = Card()
        footer.add(make_hint(COPY["c.hotline.footer"]))
        footer.add(hotline_label(COPY.hotline_line()))
        outer.addWidget(footer)

    # ---------------------------------------------------------------- 数据

    def set_dates(self, dates: List[str]) -> None:
        """更新有记录的日期（日历打点）。

        ⚠️ **同一份日期列表重复传入时不再重发 `profile_requested`**：登录恢复
        路径上 `try_restore_session()` 会再调一次 `set_dates()`，若每次都 emit，
        同一个 `date` 就有两个 `/profile/me` 在飞 —— 先回来的成功、后回来的失败
        （或反之），界面会被后回来的那个覆盖（实测踩过：[2001] 用例里成功响应
        被覆盖成 1001，表现为"档案页明明有数据却跳去登录页"）。
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
        if not self._dates:
            self.empty_label.setText(COPY["c.empty.profile.dates"])
            self.empty_label.setVisible(True)
            return
        self.day_picker.setCurrentIndex(len(self._dates) - 1)
        self.profile_requested.emit(self._dates[-1])

    def set_profile(self, data: dict) -> None:
        """渲染某日档案（`GET /profile/me` 的 `data`）。"""
        self.error_label.setVisible(False)
        submissions = list(data.get("submissions") or [])
        self._clear_rows()
        if not submissions:
            self.empty_label.setText(COPY["c.empty.profile.submissions"])
            self.empty_label.setVisible(True)
            return
        self.empty_label.setVisible(False)
        for record in reversed(submissions):     # 最新在前
            row = RecordRow(record)
            self._rows.append(row)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def _clear_rows(self) -> None:
        """立即移除旧行控件。

        ⚠️ 只调 `deleteLater()` 不够：Qt 要等事件循环才真正销毁，
        而这期间旧行仍留在布局里（自检里表现为"旧标签文本还在"）。
        故这里 `removeWidget` + `setParent(None)` 立刻摘除，再交给 `deleteLater` 回收。
        """
        for row in self._rows:
            self.list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def show_toast(self, text: str) -> None:
        self.toast.setText(text)
        self.toast.setVisible(bool(text))

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    # ---------------------------------------------------------------- 查询助手

    def rows(self) -> List[RecordRow]:
        """当前渲染的所有记录行（自检按此断言）。"""
        return list(self._rows)

    def help_requested_rows(self) -> List[RecordRow]:
        """`request_help=true` 的行（= 契约里 `consent_share=true` 的那些）。"""
        return [row for row in self._rows if row.request_help]

    def status_labels(self) -> List[str]:
        """所有行的状态标签文本（按渲染顺序）。"""
        return [row.status for row in self._rows]

    def _on_day_changed(self, day: str) -> None:
        if day:
            self.profile_requested.emit(day)
