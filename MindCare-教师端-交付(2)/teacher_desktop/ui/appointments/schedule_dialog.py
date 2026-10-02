# -*- coding: utf-8 -*-
"""定预约时间弹窗。

老师选定日期 + 时间（可选备注），确认后由页面写入预约数据库（适配层）。
时间格式：本地时区 ISO8601（+08:00），与服务端时间口径一致。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QLineEdit, QTimeEdit, QVBoxLayout,
)

from desktop_common.widgets import make_label

_TZ = timezone(timedelta(hours=8))


class ScheduleDialog(QDialog):
    """给某条求助请求约定时间。accepted 后读 scheduled_iso / note。"""

    def __init__(self, student_name: str, class_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("约定预约时间")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        layout.addWidget(make_label(f"为 {student_name}（{class_name}）安排心理约谈",
                                    "CardTitle", word_wrap=False))
        layout.addWidget(make_label("确定的时间会写入预约数据库，并展示在当日单线流程中",
                                    "Hint"))

        # ---- 日期 + 时间一行
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(make_label("日期", "Body", word_wrap=False))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setMinimumDate(QDate.currentDate())
        # 去掉原生微调按钮（与圆角输入框样式冲突）；可直接键入日期，或按 F4 唤起日历
        self.date_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        row.addWidget(self.date_edit, 1)

        row.addWidget(make_label("时间", "Body", word_wrap=False))
        # 默认取下一个整点
        now = datetime.now(_TZ).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        self.time_edit = QTimeEdit(QTime(now.hour, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        row.addWidget(self.time_edit, 1)
        layout.addLayout(row)

        layout.addWidget(make_label("备注（地点/方式，可选）", "Body", word_wrap=False))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("如：心理辅导室 / 线上语音")
        layout.addWidget(self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定预约")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
