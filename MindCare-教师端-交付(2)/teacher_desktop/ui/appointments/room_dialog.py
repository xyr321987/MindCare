# -*- coding: utf-8 -*-
"""咨询室管理弹窗（档案：名称 / 位置 / 特点 / 启用）。

老师在这里新增、编辑（名称/位置/特点/启用）、删除咨询室。为遵守「网络只在 worker
线程」的纪律，弹窗本身不请求网络：它收集本次改动，`accepted` 后由页面逐条落库。
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
        self.original_location = str(room.get("location") or "")
        self.original_features = str(room.get("features") or "")
        self.original_active = bool(room.get("active", True))
        self.name_edit = QLineEdit(self.original_name)
        self.name_edit.setPlaceholderText("名称")
        self.location_edit = QLineEdit(self.original_location)
        self.location_edit.setPlaceholderText("位置（如：三楼东侧）")
        self.features_edit = QLineEdit(self.original_features)
        self.features_edit.setPlaceholderText("特点（如：安静、采光好）")
        self.active_check = QCheckBox("启用")
        self.active_check.setChecked(self.original_active)
        self.deleted = False

    def name(self) -> str:
        return self.name_edit.text().strip()

    def location(self) -> Optional[str]:
        return self.location_edit.text().strip() or None

    def features(self) -> Optional[str]:
        return self.features_edit.text().strip() or None

    def active(self) -> bool:
        return self.active_check.isChecked()

    def changed(self) -> bool:
        return (self.name() != self.original_name
                or self.location() != self.original_location
                or self.features() != self.original_features
                or self.active() != self.original_active)


class RoomManageDialog(QDialog):
    def __init__(self, rooms: List[dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("咨询室管理")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._rows: List[_RoomRow] = []
        self._new_rooms: List[Dict[str, Optional[str]]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label("管理可预约的咨询室", "CardTitle", word_wrap=False))
        layout.addWidget(make_hint("记录名称、位置与特点；改动在点「保存」后写入"))

        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(8)
        layout.addLayout(self._list_box)
        self._rebuild_rows(rooms)

        # ---- 新增区
        layout.addSpacing(4)
        layout.addWidget(make_label("新增咨询室", "Heading", word_wrap=False))
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("名称（如：咨询室C）")
        layout.addWidget(self.new_name_edit)
        add_info = QHBoxLayout()
        add_info.setSpacing(8)
        self.new_location_edit = QLineEdit()
        self.new_location_edit.setPlaceholderText("位置（可选）")
        self.new_features_edit = QLineEdit()
        self.new_features_edit.setPlaceholderText("特点（可选）")
        add_info.addWidget(self.new_location_edit, 1)
        add_info.addWidget(self.new_features_edit, 1)
        layout.addLayout(add_info)
        self.new_name_edit.returnPressed.connect(self._add_new)
        self.new_features_edit.returnPressed.connect(self._add_new)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("GhostButton")
        add_btn.setFocusPolicy(Qt.StrongFocus)
        add_btn.clicked.connect(self._add_new)
        layout.addWidget(add_btn, 0, Qt.AlignRight)

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
            self._list_box.addWidget(self._make_row(room))

    def _make_row(self, room: dict) -> QFrame:
        r = _RoomRow(room)
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(r.name_edit, 1)
        top.addWidget(r.active_check)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("GhostButton")
        del_btn.setFocusPolicy(Qt.StrongFocus)
        del_btn.clicked.connect(lambda _=False, row=r, fr=frame: self._mark_deleted(row, fr))
        top.addWidget(del_btn)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(r.location_edit, 1)
        bottom.addWidget(r.features_edit, 1)
        lay.addLayout(bottom)

        self._list_box.addWidget(frame)
        return frame

    def _mark_deleted(self, row: _RoomRow, frame: QFrame) -> None:
        row.deleted = True
        frame.hide()

    def _add_new(self) -> None:
        name = self.new_name_edit.text().strip()
        if not name:
            return
        self._new_rooms.append({
            "name": name,
            "location": self.new_location_edit.text().strip() or None,
            "features": self.new_features_edit.text().strip() or None,
        })
        self.new_name_edit.clear()
        self.new_location_edit.clear()
        self.new_features_edit.clear()
        self._refresh_new_label()

    def _refresh_new_label(self) -> None:
        if not self._new_rooms:
            self._new_label.setText("")
        else:
            self._new_label.setText("待新增：" + "、".join(r["name"] for r in self._new_rooms))

    # ------------------------------------------------------------------ 结果
    @property
    def new_rooms(self) -> List[Dict[str, Optional[str]]]:
        return list(self._new_rooms)

    @property
    def updates(self) -> List[Dict[str, object]]:
        out = []
        for r in self._rows:
            if r.deleted:
                continue
            if r.changed() and r.name():
                out.append({"room_id": r.room_id, "name": r.name(),
                            "location": r.location(), "features": r.features(),
                            "active": r.active()})
        return out

    @property
    def deletes(self) -> List[str]:
        return [r.room_id for r in self._rows if r.deleted]
