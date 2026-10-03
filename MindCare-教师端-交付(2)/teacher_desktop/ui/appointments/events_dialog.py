# -*- coding: utf-8 -*-
"""预约操作日志弹窗（只读展示取消/改期/爽约/完成等留痕）。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QDialogButtonBox, QFrame, QHBoxLayout, QWidget,
)

from desktop_common.widgets import make_hint, make_label

from ...core import enums
from ..common.dialog_base import BaseDialog


def _fmt(ts: str | None) -> str:
    if not ts:
        return ""
    return str(ts)[:16].replace("T", " ")


class EventsDialog(BaseDialog):
    def __init__(self, title: str, events: List[dict],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("操作记录")
        self.setMinimumWidth(440)

        self.set_header(title)

        if not events:
            self.add_to_content(make_hint("暂无操作记录"))
        for ev in events:
            self.add_to_content(self._row(ev))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        self.set_buttons(buttons)

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
