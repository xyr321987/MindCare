# -*- coding: utf-8 -*-
"""定预约时间弹窗（预约 + 改期共用）。

老师选定日期 + 时间 + 教师 + 咨询室（可选备注），确认后由页面写入预约数据库（适配层）。
时间格式：本地时区 ISO8601（+08:00），与服务端时间口径一致。

`existing` 传预约对象时进入「改期」模式：预填当前时间/教师/咨询室，按钮文案变为「确定改期」。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDialogButtonBox,
    QHBoxLayout, QLineEdit, QTimeEdit,
)

from desktop_common.widgets import make_label

from ...core.models import Appointment
from ..common.dialog_base import BaseDialog

_TZ = timezone(timedelta(hours=8))

#: 下拉里的「未分配」占位（teacher_id/room_id 传 None）
_UNSET = "（未分配）"


class ScheduleDialog(BaseDialog):
    """给某条求助请求约定时间 / 改期。accepted 后读 scheduled_iso / note / teacher_id / room_id。"""

    def __init__(self, student_name: str, class_name: str,
                 teachers: List[dict], rooms: List[dict],
                 existing: Optional[Appointment] = None, parent=None) -> None:
        super().__init__(parent)
        self._reschedule = existing is not None
        self.setWindowTitle("改期预约" if self._reschedule else "约定预约时间")
        self.setMinimumWidth(420)

        action = "改期" if self._reschedule else "安排"
        self.set_header(f"为 {student_name}（{class_name}）{action}心理约谈",
                        "确定的时间会写入预约数据库，并展示在当日单线流程中")

        # ---- 日期 + 时间一行
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(make_label("日期", "Body", word_wrap=False))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setMinimumDate(QDate.currentDate())
        self.date_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        row.addWidget(self.date_edit, 1)

        row.addWidget(make_label("时间", "Body", word_wrap=False))
        now = datetime.now(_TZ).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        self.time_edit = QTimeEdit(QTime(now.hour, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        row.addWidget(self.time_edit, 1)
        self.add_content_layout(row)

        # ---- 教师 + 咨询室一行
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(make_label("教师", "Body", word_wrap=False))
        self.teacher_combo = QComboBox()
        self.teacher_combo.addItem(_UNSET, None)
        for t in teachers or []:
            self.teacher_combo.addItem(str(t.get("name") or t.get("teacher_id") or ""),
                                       t.get("teacher_id"))
        row2.addWidget(self.teacher_combo, 1)

        row2.addWidget(make_label("咨询室", "Body", word_wrap=False))
        self.room_combo = QComboBox()
        self.room_combo.addItem(_UNSET, None)
        for r in rooms or []:
            name = str(r.get("name") or r.get("room_id") or "")
            if not bool(r.get("active", True)):
                name += "（停用）"
            self.room_combo.addItem(name, r.get("room_id"))
        row2.addWidget(self.room_combo, 1)
        self.add_content_layout(row2)

        # 默认选中首个教师 + 首个启用咨询室（多教师/多咨询室调度时冲突检测开箱即用）
        if self.teacher_combo.count() > 1:
            self.teacher_combo.setCurrentIndex(1)
        for r in rooms or []:
            if bool(r.get("active", True)) and r.get("room_id"):
                idx = self.room_combo.findData(r["room_id"])
                if idx >= 0:
                    self.room_combo.setCurrentIndex(idx)
                    break

        self.add_to_content(make_label("备注（地点/方式，可选）", "Body", word_wrap=False))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("如：线上语音 / 需家长陪同")
        self.add_to_content(self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定改期" if self._reschedule else "确定预约")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.set_buttons(buttons)

        # ---- 改期模式预填
        if existing is not None:
            self._prefill(existing)

    # ------------------------------------------------------------------ 预填
    def _prefill(self, appt: Appointment) -> None:
        if appt.scheduled_at:
            qd = QDate.fromString(appt.scheduled_at[:10], "yyyy-MM-dd")
            if qd.isValid():
                self.date_edit.setDate(qd)
            t = appt.scheduled_at[11:16]
            self.time_edit.setTime(QTime.fromString(t, "HH:mm"))
        if appt.note:
            self.note_edit.setText(appt.note)
        if appt.teacher_id:
            idx = self.teacher_combo.findData(appt.teacher_id)
            if idx >= 0:
                self.teacher_combo.setCurrentIndex(idx)
        if appt.room_id:
            idx = self.room_combo.findData(appt.room_id)
            if idx >= 0:
                self.room_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------ 结果
    @property
    def scheduled_iso(self) -> str:
        qd, qt = self.date_edit.date(), self.time_edit.time()
        dt = datetime(qd.year(), qd.month(), qd.day(), qt.hour(), qt.minute(),
                      tzinfo=_TZ)
        return dt.isoformat()

    @property
    def note(self) -> Optional[str]:
        text = self.note_edit.text().strip()
        return text or None

    @property
    def teacher_id(self) -> Optional[str]:
        return self.teacher_combo.currentData()

    @property
    def room_id(self) -> Optional[str]:
        return self.room_combo.currentData()
