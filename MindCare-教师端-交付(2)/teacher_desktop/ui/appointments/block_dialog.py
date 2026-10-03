# -*- coding: utf-8 -*-
"""设定不可预约时段弹窗（老师设红框，学生端只读）。"""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialogButtonBox,
    QHBoxLayout, QLineEdit,
)

from desktop_common.widgets import make_label

from ..common.dialog_base import BaseDialog

_PERIODS = [f"第{i}节" for i in range(1, 9)]


class BlockDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设定不可预约时段")
        self.setMinimumWidth(360)

        self.set_header("设定不可预约时段", "把某一节设为不可预约，学生端会看到红框")

        row = QHBoxLayout()
        row.addWidget(make_label("日期", "Body", word_wrap=False))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(self.date_edit, 1)
        self.add_content_layout(row)

        row2 = QHBoxLayout()
        row2.addWidget(make_label("节次", "Body", word_wrap=False))
        self.period_combo = QComboBox()
        self.period_combo.addItems(_PERIODS)
        row2.addWidget(self.period_combo, 1)
        self.add_content_layout(row2)

        self.add_to_content(make_label("原因（可选）", "Body", word_wrap=False))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("如：老师不在 / 已排满")
        self.add_to_content(self.reason_edit)

        self.blocked_check = QCheckBox("设为不可预约（取消勾选 = 恢复可预约）")
        self.blocked_check.setChecked(True)
        self.add_to_content(self.blocked_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.set_buttons(buttons)

    @property
    def year(self) -> int:
        return self.date_edit.date().year()

    @property
    def month(self) -> int:
        return self.date_edit.date().month()

    @property
    def day(self) -> int:
        return self.date_edit.date().day()

    @property
    def period(self) -> int:
        return self.period_combo.currentIndex() + 1

    @property
    def active(self) -> bool:
        return self.blocked_check.isChecked()

    @property
    def reason(self):
        return self.reason_edit.text().strip() or None
