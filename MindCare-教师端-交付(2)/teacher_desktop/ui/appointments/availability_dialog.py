# -*- coding: utf-8 -*-
"""教师周期可用时段弹窗（RFC 7953 VAVAILABILITY 式）。

勾选 = 该节次可约；取消勾选 = 不可约（存显式不可约行，缺行默认可约）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QPushButton, QVBoxLayout,
)

from desktop_common.widgets import make_label

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_PERIODS = [f"第{i}节" for i in range(1, 9)]


class AvailabilityDialog(QDialog):
    def __init__(self, teacher_name: str, availability: List[dict],
                 parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("可用时段")
        self.setModal(True)
        self.setMinimumWidth(640)

        self._checks: Dict[Tuple[int, int], QCheckBox] = {}
        unavailable = {(int(a.get("weekday")), int(a.get("period")))
                       for a in availability if not bool(a.get("active", True))}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label(f"{teacher_name} 的每周可用时段", "CardTitle", word_wrap=False))
        layout.addWidget(make_label("勾选 = 可约；取消勾选 = 该节次不可约", "Hint"))

        grid = QGridLayout()
        grid.setSpacing(6)
        for col, wd in enumerate(_WEEKDAYS, start=1):
            grid.addWidget(make_label(wd, "Body", word_wrap=False), 0, col)
        for row, period in enumerate(_PERIODS, start=1):
            grid.addWidget(make_label(period, "Body", word_wrap=False), row, 0)
            for col in range(1, 8):
                weekday = col
                cb = QCheckBox("")
                cb.setChecked((weekday, row) not in unavailable)
                self._checks[(weekday, row)] = cb
                grid.addWidget(cb, row, col)
        layout.addLayout(grid)

        quick = QHBoxLayout()
        all_btn = QPushButton("全部可约")
        all_btn.setObjectName("GhostButton")
        all_btn.clicked.connect(self._set_all)
        none_btn = QPushButton("全部不可约")
        none_btn.setObjectName("GhostButton")
        none_btn.clicked.connect(self._set_none)
        quick.addWidget(all_btn)
        quick.addWidget(none_btn)
        quick.addStretch(1)
        layout.addLayout(quick)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self) -> None:
        for cb in self._checks.values():
            cb.setChecked(True)

    def _set_none(self) -> None:
        for cb in self._checks.values():
            cb.setChecked(False)

    @property
    def items(self) -> List[dict]:
        out = []
        for (weekday, period), cb in sorted(self._checks.items()):
            if not cb.isChecked():
                out.append({"weekday": weekday, "period": period, "active": False})
        return out
