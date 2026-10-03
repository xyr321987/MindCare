# -*- coding: utf-8 -*-
"""批量停诊/恢复弹窗：一次勾选同一日多个节次。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QLineEdit,
)

from desktop_common.widgets import make_label

from ..common.dialog_base import BaseDialog

_PERIODS = [f"第{i}节" for i in range(1, 9)]


class BatchBlockDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量停诊 / 恢复")
        self.setMinimumWidth(400)

        self.set_header("批量停诊 / 恢复", "一次设定同一日多个节次（学生端只读）")

        row = QHBoxLayout()
        row.addWidget(make_label("日期", "Body", word_wrap=False))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(self.date_edit, 1)
        self.add_content_layout(row)

        self.add_to_content(make_label("勾选要设定的节次", "Body", word_wrap=False))
        grid = QGridLayout()
        grid.setSpacing(8)
        self._checks: List[QCheckBox] = []
        for i, label in enumerate(_PERIODS):
            cb = QCheckBox(label)
            cb.setChecked(False)
            self._checks.append(cb)
            grid.addWidget(cb, i // 4, i % 4)
        self.add_content_layout(grid)

        self.add_to_content(make_label("原因（可选）", "Body", word_wrap=False))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("如：教师会议 / 临时外出")
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

    # ------------------------------------------------------------------ 结果
    @property
    def items(self) -> List[dict]:
        qd = self.date_edit.date()
        out = []
        for i, cb in enumerate(self._checks):
            if cb.isChecked():
                out.append({"year": str(qd.year()), "month": str(qd.month()),
                            "day": str(qd.day()), "period": str(i + 1)})
        return out

    @property
    def active(self) -> bool:
        return self.blocked_check.isChecked()

    @property
    def reason(self) -> Optional[str]:
        return self.reason_edit.text().strip() or None
