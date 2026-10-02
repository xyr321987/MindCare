# -*- coding: utf-8 -*-
"""「工作预览」首页 —— 教师登录后的默认概览页。

只做**只读聚合展示**，数据全部来自既有接口（预约适配器 / 预警适配器），
不新增业务、不写库、不伪造：没有数据就显示 0 或友好空状态。

统计口径：
* 待处理求助 = 预约适配器 `pending_requests()`（学生发起、老师尚未定时间的求助工单）
* 今日预约 = 今天 `scheduled` 状态的预约数
* 待跟进事项 = `active` 状态的预警数
* 已完成任务 = 今天 `done` 状态的预约数
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from desktop_common.api import format_ts_human, today_str
from desktop_common.widgets import Card, Progress, make_hint, make_label, make_title

from ..common.async_mixin import PageBase
from ..common.svg import svg_pixmap

#: 统计卡配置：key -> (标题, 图标, tone)
_STAT_SPECS = (
    ("pending_help", "待处理求助", "icon_user.svg", "help"),
    ("today_appt", "今日预约", "icon_appointment.svg", "appointment"),
    ("active_warn", "待跟进事项", "icon_bell.svg", "warning"),
    ("done", "已完成任务", "icon_check.svg", "done"),
)


class _StatCard(Card):
    """顶部统计卡：线性图标（柔和底色圆）+ 数值 + 标题。"""

    def __init__(self, title: str, icon: str, tone: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("OverviewStat")

        inner = self.body_layout()
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.icon = QLabel(self)
        self.icon.setObjectName("StatIcon")
        self.icon.setProperty("tone", tone)
        self.icon.setPixmap(svg_pixmap(icon, 22, 22))
        self.icon.setFixedSize(36, 36)
        self.icon.setAlignment(Qt.AlignCenter)
        row.addWidget(self.icon)
        row.addStretch(1)
        inner.addLayout(row)

        self.value_label = make_label("0", "StatValue", word_wrap=False)
        inner.addWidget(self.value_label)
        self.title_label = make_label(title, "StatTitle", word_wrap=False)
        inner.addWidget(self.title_label)

    def set_value(self, value: int) -> None:
        self.value_label.setText(str(int(value or 0)))


class OverviewPage(PageBase):
    """工作预览首页。"""

    PAGE_TITLE = "工作预览"

    def __init__(self, ctx, parent: Optional[QWidget] = None) -> None:
        super().__init__(ctx, parent)
        self._stats: Dict[str, _StatCard] = {}

        # ---- 标题行 ----
        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(make_title("工作预览"))
        title_col.addWidget(make_hint("把每一次关注，变成及时而温柔的支持"))
        header.addLayout(title_col)
        header.addStretch(1)
        self.refresh_button = QPushButton("刷新", self)
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.setFocusPolicy(Qt.StrongFocus)
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        self._root.addLayout(header)

        # ---- 四个统计卡 ----
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        for key, title, icon, tone in _STAT_SPECS:
            card = _StatCard(title, icon, tone)
            self._stats[key] = card
            stats_row.addWidget(card, 1)
        self._root.addLayout(stats_row)

        # ---- 中部：待办事项 + 今日工作进度 ----
        middle = QHBoxLayout()
        middle.setSpacing(16)

        # 待办事项（左，大卡）
        self.todo_card = Card()
        self.todo_card.setObjectName("OverviewTodo")
        todo_inner = self.todo_card.body_layout()
        todo_inner.setContentsMargins(20, 18, 20, 18)
        todo_inner.setSpacing(10)
        todo_inner.addWidget(make_label("待办事项", "SectionTitle", word_wrap=False))
        self._todo_rows = QVBoxLayout()
        self._todo_rows.setSpacing(0)
        todo_inner.addLayout(self._todo_rows)
        self.todo_empty = make_hint("今天没有待处理的事项，先喝口水吧。")
        self._todo_rows.addWidget(self.todo_empty)
        todo_inner.addStretch(1)
        middle.addWidget(self.todo_card, 3)

        # 右侧：今日工作进度 + 近期动态
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        self.progress_card = Card()
        self.progress_card.setObjectName("OverviewProgress")
        prog_inner = self.progress_card.body_layout()
        prog_inner.setContentsMargins(20, 18, 20, 18)
        prog_inner.setSpacing(10)
        prog_inner.addWidget(make_label("今日工作进度", "SectionTitle", word_wrap=False))
        self.progress_value = make_label("0 / 0", "StatValue", word_wrap=False)
        prog_inner.addWidget(self.progress_value)
        self.progress_bar = Progress()
        prog_inner.addWidget(self.progress_bar)
        self.progress_hint = make_hint("")
        prog_inner.addWidget(self.progress_hint)
        right_col.addWidget(self.progress_card)

        self.activity_card = Card()
        self.activity_card.setObjectName("OverviewActivity")
        act_inner = self.activity_card.body_layout()
        act_inner.setContentsMargins(20, 18, 20, 18)
        act_inner.setSpacing(8)
        act_inner.addWidget(make_label("近期动态", "SectionTitle", word_wrap=False))
        self._activity_rows = QVBoxLayout()
        self._activity_rows.setSpacing(0)
        act_inner.addLayout(self._activity_rows)
        self.activity_empty = make_hint("暂无动态记录。")
        self._activity_rows.addWidget(self.activity_empty)
        act_inner.addStretch(1)
        right_col.addWidget(self.activity_card, 1)

        middle.addLayout(right_col, 2)
        self._root.addLayout(middle, 1)

        # ---- 底部温柔提示 ----
        footer = QHBoxLayout()
        footer.addStretch(1)
        mark = QLabel(self)
        mark.setPixmap(svg_pixmap("footer_mark.svg", 44, 26))
        mark.setFixedSize(44, 26)
        footer.addWidget(mark)
        footer.addSpacing(8)
        footer.addWidget(make_hint("先看见，再理解；每一次及时回应都很重要。"))
        footer.addStretch(1)
        self._root.addLayout(footer)

    # ------------------------------------------------------ 数据
    def refresh(self) -> None:
        self.call(self._load, on_ok=self._render)

    def _load(self) -> Dict[str, Any]:
        today = today_str()
        appointment = self.ctx.adapters.appointment
        warning = self.ctx.adapters.warning
        pending = appointment.pending_requests()
        todays = appointment.list_by_date(today)
        warnings = warning.list_all()

        scheduled = [a for a in todays if getattr(a, "status", "") == "scheduled"]
        done = [a for a in todays if getattr(a, "status", "") == "done"]
        active_warn = [w for w in warnings if getattr(w, "status", "") == "active"]

        todos: List[Dict[str, str]] = []
        for p in pending:
            todos.append({
                "kind": "appointment",
                "title": "待确认预约",
                "desc": f"{getattr(p, 'student_name', '')} 发起了求助",
            })
        for w in active_warn:
            todos.append({
                "kind": "warning",
                "title": "需要响应的预警",
                "desc": f"{getattr(w, 'student_name', '')} 出现连续低落",
            })

        return {
            "pending_help": len(pending),
            "today_appt": len(scheduled),
            "active_warn": len(active_warn),
            "done": len(done),
            "todos": todos,
            "total": len(pending) + len(scheduled) + len(active_warn) + len(done),
            "done_count": len(done),
        }

    def _render(self, data: Dict[str, Any]) -> None:
        self._stats["pending_help"].set_value(data.get("pending_help", 0))
        self._stats["today_appt"].set_value(data.get("today_appt", 0))
        self._stats["active_warn"].set_value(data.get("active_warn", 0))
        self._stats["done"].set_value(data.get("done", 0))

        self._render_todos(list(data.get("todos") or []))
        total = int(data.get("total") or 0)
        done = int(data.get("done_count") or 0)
        self.progress_value.setText(f"{done} / {total}")
        self.progress_bar.set_progress(done, total)
        percent = int(round(done / total * 100)) if total else 0
        self.progress_hint.setText(f"已完成 {percent}%")

    def _render_todos(self, todos: List[Dict[str, str]]) -> None:
        while self._todo_rows.count():
            item = self._todo_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not todos:
            self.todo_empty = make_hint("今天没有待处理的事项，先喝口水吧。")
            self._todo_rows.addWidget(self.todo_empty)
            return
        for todo in todos:
            row = QFrame()
            row.setObjectName("OverviewTodoRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 10, 0, 10)
            lay.setSpacing(8)
            lay.addWidget(make_label(todo["title"], "StatTitle", word_wrap=False))
            lay.addWidget(make_label(todo["desc"], "OverviewTodoDesc"))
            lay.addStretch(1)
            self._todo_rows.addWidget(row)
