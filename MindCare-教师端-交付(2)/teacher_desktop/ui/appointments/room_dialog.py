# -*- coding: utf-8 -*-
"""咨询室管理弹窗。

老师在这里新增 / 重命名 / 停用 / 删除咨询室。为遵守「网络只在 worker 线程」的纪律，
弹窗本身不请求网络：它收集本次改动，`accepted` 后由页面逐条调用适配器落库。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_hint, make_label


class _RoomRow:
    """一条已有咨询室的可编辑行。"""

    def __init__(self, room: dict) -> None:
        self.room_id = str(room.get("room_id") or "")
        self.original_name = str(room.get("name") or "")
        self.original_active = bool(room.get("active", True))
        self.name_edit = QLineEdit(self.original_name)
        self.active_check = QCheckBox("启用")
        self.active_check.setChecked(self.original_active)
        self.deleted = False

    def name(self) -> str:
        return self.name_edit.text().strip()

    def active(self) -> bool:
        return self.active_check.isChecked()

    def changed(self) -> bool:
        return (self.name() != self.original_name
                or self.active() != self.original_active)


class RoomManageDialog(QDialog):
    def __init__(self, rooms: List[dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("咨询室管理")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._rows: List[_RoomRow] = []
        self._new_names: List[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label("管理可预约的咨询室", "CardTitle", word_wrap=False))
        layout.addWidget(make_hint("新增、重命名、停用或删除；改动在点「保存」后写入"))

        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(8)
        layout.addLayout(self._list_box)
        self._rebuild_rows(rooms)

        # ---- 新增区
        layout.addSpacing(4)
        layout.addWidget(make_label("新增咨询室", "Heading", word_wrap=False))
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("如：咨询室C")
        self.new_name_edit.returnPressed.connect(self._add_new)
        add_row.addWidget(self.new_name_edit, 1)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("GhostButton")
        add_btn.setFocusPolicy(Qt.StrongFocus)
        add_btn.clicked.connect(self._add_new)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        self._new_label = make_hint("")
        layout.addWidget(self._new_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 行
    def _rebuild_rows(self, rooms: List[dict]) -> None:
        while self._list_box.count():
            item = self._list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        if not rooms:
            self._list_box.addWidget(make_hint("暂无咨询室，可在下方新增"))
            return
        for room in rooms:
            self._rows.append(self._make_row(room))

    def _make_row(self, room: dict) -> QFrame:
        r = _RoomRow(room)
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(r.name_edit, 1)
        lay.addWidget(r.active_check)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("GhostButton")
        del_btn.setFocusPolicy(Qt.StrongFocus)
        del_btn.clicked.connect(lambda _=False, row=r, fr=frame: self._mark_deleted(row, fr))
        lay.addWidget(del_btn)
        self._list_box.addWidget(frame)
        return frame

    def _mark_deleted(self, row: _RoomRow, frame: QFrame) -> None:
        row.deleted = True
        frame.hide()

    def _add_new(self) -> None:
        name = self.new_name_edit.text().strip()
        if not name:
            return
        self._new_names.append(name)
        self.new_name_edit.clear()
        self._refresh_new_label()

    def _refresh_new_label(self) -> None:
        if not self._new_names:
            self._new_label.setText("")
        else:
            self._new_label.setText("待新增：" + "、".join(self._new_names))

    # ------------------------------------------------------------------ 结果
    @property
    def new_rooms(self) -> List[str]:
        return list(self._new_names)

    @property
    def updates(self) -> List[Dict[str, object]]:
        out = []
        for r in self._rows:
            if r.deleted:
                continue
            if r.changed() and r.name():
                out.append({"room_id": r.room_id, "name": r.name(),
                            "active": r.active()})
        return out

    @property
    def deletes(self) -> List[str]:
        return [r.room_id for r in self._rows if r.deleted]
