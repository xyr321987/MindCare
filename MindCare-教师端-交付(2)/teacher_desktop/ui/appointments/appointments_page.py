# -*- coding: utf-8 -*-
"""今日预约页。

布局（自上而下）：
1. 日期选择 + 刷新；
2. 待预约求助（来自求助工单，虚线珊瑚卡，「约定时间」打开弹窗写入预约数据库）；
3. 当日单线时间轴：已预约（雾蓝节点）→ 已完成（嫩芽节点），约谈结束可一键标记完成。

数据全部来自 AppointmentAdapter 协议；数据源切换对本页透明。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_hint, make_label, make_primary_button, wrap_scroll,
)

from ...core import enums
from ...core.models import Appointment
from ..common.async_mixin import PageBase
from .block_dialog import BlockDialog
from .schedule_dialog import ScheduleDialog


class AppointmentsPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._date = enums.today_str()
        self._build_ui()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("今日预约", "PageTitle", word_wrap=False))
        titles.addWidget(make_label("先处理待预约求助，再沿单线时间轴完成当日约谈",
                                    "PageSub", word_wrap=False))
        head.addLayout(titles)
        head.addStretch(1)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.dateChanged.connect(self._on_date_changed)
        head.addWidget(self.date_edit)

        today_btn = make_button("回到今天", "ghost")
        today_btn.clicked.connect(
            lambda: self.date_edit.setDate(QDate.currentDate()))
        head.addWidget(today_btn)

        refresh_btn = make_primary_button("刷新")
        refresh_btn.clicked.connect(self.refresh)
        head.addWidget(refresh_btn)

        block_btn = make_button("设不可预约", "ghost")
        block_btn.clicked.connect(self._open_block)
        head.addWidget(block_btn)
        self._root.addLayout(head)

        # 滚动内容区（待预约 + 时间轴两个分区动态重建）
        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._content)
        self._content_box.setContentsMargins(0, 4, 0, 0)
        self._content_box.setSpacing(18)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 加载
    def refresh(self) -> None:
        adapter = self.ctx.adapters.appointment
        date = self._date

        def _job():
            return adapter.pending_requests(), adapter.list_by_date(date)

        self.call(_job, on_ok=self._render)

    def _on_date_changed(self, qdate: QDate) -> None:
        self._date = qdate.toString("yyyy-MM-dd")
        # 只重新拉当日流程；待预约区不随日期变，refresh 会一起更新也无妨
        self.refresh()

    # ------------------------------------------------------------------ 渲染
    def _render(self, payload: Tuple[List[Appointment], List[Appointment]]) -> None:
        pendings, day_appts = payload
        self._clear_content()

        self._content_box.addWidget(
            make_label(f"待预约求助（{len(pendings)}）", "Heading", word_wrap=False))
        if pendings:
            for appt in pendings:
                self._content_box.addWidget(self._pending_card(appt))
        else:
            self._content_box.addWidget(self._inline_hint("暂无待预约求助，新的求助会出现在这里"))

        self._content_box.addSpacing(4)
        self._content_box.addWidget(
            make_label(f"{self._date} 单线流程", "Heading", word_wrap=False))

        scheduled = sorted([a for a in day_appts if a.status == "scheduled"],
                           key=lambda a: a.scheduled_at or "")
        done = sorted([a for a in day_appts if a.status == "done"],
                      key=lambda a: a.scheduled_at or "")
        if not scheduled and not done:
            self._content_box.addWidget(
                self._inline_hint("这一天还没有预约，可以在上方为待预约求助约定时间"))
        for appt in scheduled:
            self._content_box.addWidget(self._timeline_node(appt, done_flag=False))
        for appt in done:
            self._content_box.addWidget(self._timeline_node(appt, done_flag=True))

        self._content_box.addStretch(1)

    def _pending_card(self, appt: Appointment) -> QFrame:
        card = QFrame()
        card.setObjectName("PendingCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(make_label(f"{appt.student_name} · {appt.class_name}",
                                 "CardTitle", word_wrap=False))
        row.addStretch(1)
        row.addWidget(self._status_badge("待预约", "StatusPend"))
        lay.addLayout(row)

        if appt.help_text_preview:
            lay.addWidget(make_label(appt.help_text_preview, "Body"))
        lay.addWidget(make_label(
            f"发起时间：{enums.relative_day_text(appt.created_at, self._date)}"
            f"{enums.short_time(appt.created_at) and ' ' + enums.short_time(appt.created_at) or ''}",
            "Hint"))

        btn = make_primary_button("约定时间")
        btn.clicked.connect(lambda: self._open_schedule(appt))
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn)
        lay.addLayout(btn_row)
        return card

    def _timeline_node(self, appt: Appointment, *, done_flag: bool) -> QWidget:
        node = QWidget()
        h = QHBoxLayout(node)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(12)

        # 左侧：圆点 + 竖轨（单线）
        rail_col = QVBoxLayout()
        rail_col.setContentsMargins(0, 0, 0, 0)
        rail_col.setSpacing(0)
        dot_row = QHBoxLayout()
        dot = QFrame()
        dot.setObjectName("TimelineNodeDone" if done_flag else "TimelineNode")
        dot.setFixedSize(13, 13)
        dot_row.addWidget(dot, 0, Qt.AlignHCenter)
        rail_col.addLayout(dot_row)
        rail = QFrame()
        rail.setObjectName("TimelineRail")
        rail_col.addWidget(rail, 1)
        rail_wrap = QWidget()
        rail_wrap.setFixedWidth(24)
        rail_wrap.setLayout(rail_col)
        h.addWidget(rail_wrap, 0)

        # 右侧：预约卡
        card = QFrame()
        card.setObjectName("ApptCardDone" if done_flag else "ApptCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(make_label(enums.short_time(appt.scheduled_at),
                                 "CardTitle", word_wrap=False))
        row.addWidget(make_label(f"{appt.student_name} · {appt.class_name}",
                                 "Body", word_wrap=False))
        row.addStretch(1)
        row.addWidget(self._status_badge("已完成" if done_flag else "已预约",
                                         "StatusDone" if done_flag else "StatusSched"))
        lay.addLayout(row)

        if appt.note:
            lay.addWidget(make_label(f"备注：{appt.note}", "Hint"))
        if appt.help_text_preview:
            lay.addWidget(make_label(appt.help_text_preview, "Hint"))
        for rec in (appt.questionnaire or []):
            mood_hit = enums.MOOD.get(rec.get("mood") or "")
            head = "共享问卷" + (f" · {mood_hit[0]}" if mood_hit else "")
            if rec.get("cause_category"):
                head += f" · {enums.CAUSE.get(rec.get('cause_category'), rec.get('cause_category'))}"
            lay.addWidget(make_label(head, "Hint"))
            if rec.get("detail"):
                lay.addWidget(make_label(rec.get("detail"), "Body"))
        for entry in (appt.treehole or []):
            lay.addWidget(make_label("共享树洞", "Hint"))
            lay.addWidget(make_label(entry.get("content") or "", "Body"))

        if not done_flag:
            btn = make_button("约谈完成，标记已完成", "ghost")
            btn.clicked.connect(lambda: self._complete(appt.appointment_id))
            action_row = QHBoxLayout()
            action_row.addStretch(1)
            action_row.addWidget(btn)
            lay.addLayout(action_row)

        h.addWidget(card, 1)
        return node

    @staticmethod
    def _status_badge(text: str, object_name: str) -> QFrame:
        badge = make_label(text, object_name, word_wrap=False)
        return badge

    @staticmethod
    def _inline_hint(text: str) -> QWidget:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 18, 18, 18)
        label = make_label(text, "Hint")
        label.setAlignment(Qt.AlignCenter)
        lay.addWidget(label)
        return box

    # ------------------------------------------------------------------ 动作
    def _open_schedule(self, appt: Appointment) -> None:
        dialog = ScheduleDialog(appt.student_name, appt.class_name, self)
        if dialog.exec() != ScheduleDialog.Accepted:
            return
        iso = dialog.scheduled_iso
        note = dialog.note

        def _job():
            return self.ctx.adapters.appointment.schedule(
                appt.student_id, appt.ticket_id, iso, note)

        def _ok(new_appt: Appointment):
            # 预约可能定在别的日期：把日期选择器同步过去，让老师立刻看到
            if new_appt.scheduled_at:
                target = QDate.fromString(new_appt.scheduled_at[:10], "yyyy-MM-dd")
                if target.isValid():
                    self.date_edit.blockSignals(True)
                    self.date_edit.setDate(target)
                    self.date_edit.blockSignals(False)
                    self._date = new_appt.scheduled_at[:10]
            self.show_toast("预约时间已写入预约数据库")
            self.refresh()

        self.call(_job, on_ok=_ok,
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "写入失败，请再试一次")))

    def _complete(self, appointment_id: str) -> None:
        self.call(lambda: self.ctx.adapters.appointment.complete(appointment_id),
                  on_ok=lambda _a: (self.show_toast("已标记完成"), self.refresh()),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "操作失败，请再试一次")))

    def _open_block(self) -> None:
        dialog = BlockDialog(self)
        if dialog.exec() != BlockDialog.Accepted:
            return

        def _job():
            return self.ctx.adapters.block.set(
                dialog.year, dialog.month, dialog.day, dialog.period,
                dialog.active, dialog.reason)
        self.call(_job, on_ok=lambda _d: self.show_toast("已更新不可预约时段"),
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "更新失败，请再试一次")))

    # ------------------------------------------------------------------ 工具
    def _clear_content(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
