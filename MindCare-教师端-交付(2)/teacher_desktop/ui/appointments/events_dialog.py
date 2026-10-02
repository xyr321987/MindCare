# -*- coding: utf-8 -*-
"""预约操作日志弹窗（只读展示取消/改期/爽约/完成等留痕）。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_hint, make_label

from ...core import enums


def _fmt(ts: str | None) -> str:
    if not ts:
        return ""
    return str(ts)[:16].replace("T", " ")


class EventsDialog(QDialog):
    def __init__(self, title: str, events: List[dict],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("操作记录")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label(title, "CardTitle", word_wrap=False))

        box = QVBoxLayout()
        box.setSpacing(6)
        if not events:
            box.addWidget(make_hint("暂无操作记录"))
        for ev in events:
            box.addWidget(self._row(ev))
        layout.addLayout(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _row(ev: dict) -> QFrame:
        action = enums.APPT_EVENT_ACTION.get(ev.get("action"), str(ev.get("action") or ""))
        note = ev.get("note")
        line = action + (f"：{note}" if note else "")
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(make_label(_fmt(ev.get("created_ts")), "Hint", word_wrap=False))
        lay.addWidget(make_label(line, "Body"))
        lay.addStretch(1)
        return frame
