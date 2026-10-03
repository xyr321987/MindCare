# -*- coding: utf-8 -*-
"""今日预约页（多教师 / 多咨询室调度版）。

布局（自上而下）：
1. 日期选择 + 刷新 + 咨询室管理 + 批量停诊 + 单格设停诊；
2. 待预约求助（来自求助工单，虚线珊瑚卡，「约定时间」打开弹窗写入预约数据库）；
3. 当日单线时间轴：已预约（雾蓝节点）→ 已完成（嫩芽节点）/ 已取消 / 爽约（灰节点），
   约谈可改期 / 取消 / 标记爽约 / 标记完成，全程留痕可查看操作记录。

数据全部来自 AppointmentAdapter / SchedulingAdapter / BlockAdapter 协议；数据源切换对本页透明。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_hint, make_label, make_primary_button, wrap_scroll,
)

from ...core import enums
from ...core.models import Appointment, WaitlistEntry
from ..common.async_mixin import PageBase
from .batch_block_dialog import BatchBlockDialog
from .block_dialog import BlockDialog
from .events_dialog import EventsDialog
from .reason_dialog import ReasonDialog
from .room_dialog import RoomManageDialog
from .schedule_dialog import ScheduleDialog


class AppointmentsPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._date = enums.today_str()
        self._rooms: List[dict] = []
        self._teachers: List[dict] = []
        self._refreshing = False
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

        rooms_btn = make_button("咨询室管理", "ghost")
        rooms_btn.clicked.connect(self._open_rooms)
        head.addWidget(rooms_btn)

        batch_btn = make_button("批量停诊", "ghost")
        batch_btn.clicked.connect(self._open_batch_block)
        head.addWidget(batch_btn)

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

        # 页面可见时轮询刷新，学生端新预约能及时出现在教师端（切走即停）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10_000)
        self._poll_timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------ 可见性
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._poll_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll_timer.stop()

    # ------------------------------------------------------------------ 加载
    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        adapter = self.ctx.adapters.appointment
        scheduling = self.ctx.adapters.scheduling
        waitlist = self.ctx.adapters.waitlist
        date = self._date

        def _job():
            return (adapter.pending_requests(), adapter.list_by_date(date),
                    scheduling.rooms(), scheduling.teachers(),
                    waitlist.list({"status": "waiting"}))

        self.call(_job, on_ok=self._on_refresh_done,
                  on_fail=self._on_refresh_failed)

    def _on_refresh_done(self, payload) -> None:
        self._refreshing = False
        self._render(payload)

    def _on_refresh_failed(self, exc: Exception) -> None:
        self._refreshing = False
        self._default_fail(exc)

    def _on_date_changed(self, qdate: QDate) -> None:
        self._date = qdate.toString("yyyy-MM-dd")
        self.refresh()

    # ------------------------------------------------------------------ 渲染
    def _render(self, payload: Tuple[List[Appointment], List[Appointment],
                                     List[dict], List[dict],
                                     List[WaitlistEntry]]) -> None:
        pendings, day_appts, rooms, teachers, waitlist = payload
        self._rooms = list(rooms or [])
        self._teachers = list(teachers or [])
        self._clear_content()

        self._content_box.addWidget(
            make_label(f"待预约求助（{len(pendings)}）", "Heading", word_wrap=False))
        if pendings:
            for appt in pendings:
                self._content_box.addWidget(self._pending_card(appt))
        else:
            self._content_box.addWidget(self._inline_hint("暂无待预约求助，新的求助会出现在这里"))

        self._content_box.addSpacing(4)
        self._render_waitlist(waitlist)

        self._content_box.addSpacing(4)
        self._content_box.addWidget(
            make_label(f"{self._date} 单线流程", "Heading", word_wrap=False))

        ordered = sorted(day_appts, key=lambda a: a.scheduled_at or "")
        if not ordered:
            self._content_box.addWidget(
                self._inline_hint("这一天还没有预约，可以在上方为待预约求助约定时间"))
        for appt in ordered:
            self._content_box.addWidget(self._timeline_node(appt))

        self._content_box.addStretch(1)

    def _render_waitlist(self, waitlist: List[WaitlistEntry]) -> None:
        self._content_box.addWidget(
            make_label(f"候补队列（{len(waitlist)}）", "Heading", word_wrap=False))
        if not waitlist:
            self._content_box.addWidget(self._inline_hint("暂无候补，取消/爽约会自动递补这里的同学"))
            return
        for w in waitlist:
            self._content_box.addWidget(self._waitlist_card(w))

    def _waitlist_card(self, w: WaitlistEntry) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(make_label(
            f"{w.student_name} · {w.class_name}", "CardTitle", word_wrap=False))
        info.addWidget(make_label(
            f"候补：{w.year}-{w.month}-{w.day} 第{int(w.period or 0)}节", "Hint"))
        lay.addLayout(info, 1)
        cancel_btn = make_button("退候补", "ghost")
        cancel_btn.clicked.connect(lambda: self._cancel_waitlist(w.wait_id))
        lay.addWidget(cancel_btn)
        return card

    def _cancel_waitlist(self, wait_id: str) -> None:
        self.call(lambda: self.ctx.adapters.waitlist.cancel(wait_id),
                  on_ok=lambda _d: (self.show_toast("已退候补"), self.refresh()),
                  on_fail=self._schedule_fail)

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
        row.addWidget(self._status_badge(*enums.APPT_STATUS["pending_request"]))
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

    def _timeline_node(self, appt: Appointment) -> QWidget:
        status = appt.status or "scheduled"
        if status == "done":
            dot_obj, card_obj = "TimelineNodeDone", "ApptCardDone"
        elif status in ("cancelled", "no_show"):
            dot_obj, card_obj = "TimelineNodeMuted", "ApptCardMuted"
        else:
            dot_obj, card_obj = "TimelineNode", "ApptCard"

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
        dot.setObjectName(dot_obj)
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
        card.setObjectName(card_obj)
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
        badge_text, badge_obj = enums.APPT_STATUS.get(
            status, ("已预约", "StatusSched"))
        row.addWidget(self._status_badge(badge_text, badge_obj))
        lay.addLayout(row)

        # 教师 / 咨询室（始终显示；空则显式标「未分配」，避免看起来像数据丢失）
        teacher_text = appt.teacher_name or "未分配教师"
        room_text = appt.room_name or "未分配咨询室"
        lay.addWidget(make_label(f"{teacher_text} · {room_text}", "Hint"))

        if appt.note:
            lay.addWidget(make_label(f"备注：{appt.note}", "Hint"))
        if status == "cancelled" and appt.cancel_reason:
            lay.addWidget(make_label(f"取消原因：{appt.cancel_reason}", "Hint"))
        if status == "no_show" and appt.no_show_note:
            lay.addWidget(make_label(f"爽约备注：{appt.no_show_note}", "Hint"))
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

        # 动作区（按状态）
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        if status == "scheduled":
            for text, handler in (
                ("改期", lambda: self._open_reschedule(appt)),
                ("取消", lambda: self._cancel(appt)),
                ("标记爽约", lambda: self._no_show(appt)),
                ("标记已完成", lambda: self._complete(appt.appointment_id)),
            ):
                btn = make_button(text, "ghost")
                btn.clicked.connect(handler)
                action_row.addWidget(btn)
        record_btn = make_button("查看记录", "ghost")
        record_btn.clicked.connect(lambda: self._view_events(appt))
        action_row.addWidget(record_btn)
        lay.addLayout(action_row)

        h.addWidget(card, 1)
        return node

    @staticmethod
    def _status_badge(text: str, object_name: str) -> QFrame:
        return make_label(text, object_name, word_wrap=False)

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
        dialog = ScheduleDialog(appt.student_name, appt.class_name,
                                self._teachers, self._rooms, parent=self)
        if dialog.exec() != ScheduleDialog.Accepted:
            return
        iso = dialog.scheduled_iso
        note = dialog.note
        teacher_id = dialog.teacher_id
        room_id = dialog.room_id

        def _job():
            return self.ctx.adapters.appointment.schedule(
                appt.student_id, appt.ticket_id, iso, note, teacher_id, room_id)

        def _ok(new_appt: Appointment):
            self._jump_to(new_appt.scheduled_at)
            self.show_toast("预约时间已写入预约数据库")
            self.refresh()

        self.call(_job, on_ok=_ok,
                  on_fail=lambda e: self._schedule_fail_or_waitlist(
                      appt, iso, teacher_id, room_id, e))

    def _schedule_fail_or_waitlist(self, appt: Appointment, iso: str,
                                   teacher_id, room_id, exc: Exception) -> None:
        msg = getattr(exc, "message", "") or ""
        if msg not in ("该时段已被预约", "该教师此时段已有预约", "该咨询室此时段已被占用"):
            self._schedule_fail(exc)
            return
        box = QMessageBox(self)
        box.setWindowTitle("时段已满")
        box.setText(f"{msg}\n是否将 {appt.student_name} 加入该时段候补？")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() != QMessageBox.Yes:
            return
        year, month, day, time_text = iso[:4], iso[5:7], iso[8:10], iso[11:16]

        def _job():
            return self.ctx.adapters.waitlist.join(
                appt.student_id, year, month, day, time_text,
                teacher_id, room_id, "教师加入候补")
        self.call(_job,
                  on_ok=lambda _w: (self.show_toast("已加入候补"), self.refresh()),
                  on_fail=self._schedule_fail)

    def _open_reschedule(self, appt: Appointment) -> None:
        dialog = ScheduleDialog(appt.student_name, appt.class_name,
                                self._teachers, self._rooms, existing=appt, parent=self)
        if dialog.exec() != ScheduleDialog.Accepted:
            return

        def _job():
            return self.ctx.adapters.appointment.reschedule(
                appt.appointment_id, dialog.scheduled_iso,
                dialog.teacher_id, dialog.room_id, dialog.note)

        def _ok(new_appt: Appointment):
            self._jump_to(new_appt.scheduled_at)
            self.show_toast("已改期")
            self.refresh()

        self.call(_job, on_ok=_ok, on_fail=self._schedule_fail)

    def _cancel(self, appt: Appointment) -> None:
        dialog = ReasonDialog("取消预约", "填写取消原因（会写入操作记录）", "确定取消",
                              "如：学生临时有事", parent=self)
        if dialog.exec() != ReasonDialog.Accepted:
            return
        reason = dialog.text or ""
        self.call(lambda: self.ctx.adapters.appointment.cancel(
                      appt.appointment_id, reason),
                  on_ok=lambda _a: (self.show_toast("已取消预约"), self.refresh()),
                  on_fail=self._schedule_fail)

    def _no_show(self, appt: Appointment) -> None:
        dialog = ReasonDialog("标记爽约", "填写爽约备注（会写入操作记录）", "确定标记",
                              "如：未到未请假", parent=self)
        if dialog.exec() != ReasonDialog.Accepted:
            return
        note = dialog.text or ""
        self.call(lambda: self.ctx.adapters.appointment.no_show(
                      appt.appointment_id, note),
                  on_ok=lambda _a: (self.show_toast("已标记爽约"), self.refresh()),
                  on_fail=self._schedule_fail)

    def _complete(self, appointment_id: str) -> None:
        self.call(lambda: self.ctx.adapters.appointment.complete(appointment_id),
                  on_ok=lambda _a: (self.show_toast("已标记完成"), self.refresh()),
                  on_fail=self._schedule_fail)

    def _view_events(self, appt: Appointment) -> None:
        title = f"{appt.student_name}（{appt.class_name}）的操作记录"

        def _job():
            return self.ctx.adapters.scheduling.events(appt.appointment_id)

        def _ok(events):
            EventsDialog(title, events, parent=self).exec()

        self.call(_job, on_ok=_ok, on_fail=self._schedule_fail)

    def _open_rooms(self) -> None:
        dialog = RoomManageDialog(self._rooms, parent=self)
        if dialog.exec() != RoomManageDialog.Accepted:
            return

        scheduling = self.ctx.adapters.scheduling

        def _job():
            for r in dialog.new_rooms:
                scheduling.create_room(r["name"], r["location"], r["features"])
            for upd in dialog.updates:
                scheduling.update_room(upd["room_id"], name=upd["name"],
                                       location=upd["location"], features=upd["features"],
                                       active=upd["active"])
            for room_id in dialog.deletes:
                scheduling.delete_room(room_id)
            return True

        self.call(_job, on_ok=lambda _d: (self.show_toast("咨询室已更新"), self.refresh()),
                  on_fail=self._schedule_fail)

    def _open_batch_block(self) -> None:
        dialog = BatchBlockDialog(self)
        if dialog.exec() != BatchBlockDialog.Accepted:
            return
        if not dialog.items:
            self.show_toast("未勾选任何节次")
            return

        def _job():
            return self.ctx.adapters.block.batch_set(
                dialog.items, dialog.active, dialog.reason)

        self.call(_job, on_ok=lambda _d: self.show_toast("已批量更新停诊时段"),
                  on_fail=self._schedule_fail)

    def _open_block(self) -> None:
        dialog = BlockDialog(self)
        if dialog.exec() != BlockDialog.Accepted:
            return

        def _job():
            return self.ctx.adapters.block.set(
                dialog.year, dialog.month, dialog.day, dialog.period,
                dialog.active, dialog.reason)
        self.call(_job, on_ok=lambda _d: self.show_toast("已更新不可预约时段"),
                  on_fail=self._schedule_fail)

    # ------------------------------------------------------------------ 工具
    def _jump_to(self, scheduled_at: str | None) -> None:
        if not scheduled_at:
            return
        target = QDate.fromString(scheduled_at[:10], "yyyy-MM-dd")
        if target.isValid():
            self.date_edit.blockSignals(True)
            self.date_edit.setDate(target)
            self.date_edit.blockSignals(False)
            self._date = scheduled_at[:10]

    def _schedule_fail(self, exc: Exception) -> None:
        self.show_toast(getattr(exc, "message", "操作失败，请再试一次"))

    def _clear_content(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
