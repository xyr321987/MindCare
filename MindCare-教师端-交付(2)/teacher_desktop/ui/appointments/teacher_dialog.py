# -*- coding: utf-8 -*-
"""教师账号管理弹窗：新建 / 重命名 / 重置密码 / 删除。

与咨询室管理同理，弹窗只收集改动、不发网络；`accepted` 后由页面逐条落库。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_hint, make_label

from .reason_dialog import ReasonDialog

#: 预置教师不可删除（避免锁死唯一账号）
_PRESET_TEACHER_ID = "tch_T001"


class _TeacherRow:
    def __init__(self, teacher: dict) -> None:
        self.teacher_id = str(teacher.get("teacher_id") or "")
        self.original_name = str(teacher.get("name") or "")
        self.name_edit = QLineEdit(self.original_name)
        self.deleted = False

    def name(self) -> str:
        return self.name_edit.text().strip()

    def changed(self) -> bool:
        return self.name() != self.original_name


class TeacherManageDialog(QDialog):
    def __init__(self, teachers: List[dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("教师管理")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._rows: List[_TeacherRow] = []
        self._new_teachers: List[Dict[str, str]] = []
        self._resets: List[Dict[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label("管理教师账号", "CardTitle", word_wrap=False))
        layout.addWidget(make_hint("新建账号后该教师即可用其账号密码登录"))

        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(8)
        layout.addLayout(self._list_box)
        self._rebuild_rows(teachers)

        # ---- 新建区
        layout.addSpacing(4)
        layout.addWidget(make_label("新建教师", "Heading", word_wrap=False))
        new_row = QHBoxLayout()
        new_row.setSpacing(8)
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("姓名，如：李老师")
        new_row.addWidget(self.new_name_edit, 1)
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setPlaceholderText("初始密码（≥4位）")
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        new_row.addWidget(self.new_pwd_edit, 1)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("GhostButton")
        add_btn.setFocusPolicy(Qt.StrongFocus)
        add_btn.clicked.connect(self._add_new)
        new_row.addWidget(add_btn)
        layout.addLayout(new_row)
        self._new_label = make_hint("")
        layout.addWidget(self._new_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 行
    def _rebuild_rows(self, teachers: List[dict]) -> None:
        while self._list_box.count():
            item = self._list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        if not teachers:
            self._list_box.addWidget(make_hint("暂无教师"))
            return
        for t in teachers:
            self._list_box.addWidget(self._make_row(t))

    def _make_row(self, teacher: dict) -> QFrame:
        r = _TeacherRow(teacher)
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        lay.addWidget(make_label(r.teacher_id, "Hint", word_wrap=False))
        lay.addWidget(r.name_edit, 1)
        reset_btn = QPushButton("重置密码")
        reset_btn.setObjectName("GhostButton")
        reset_btn.setFocusPolicy(Qt.StrongFocus)
        reset_btn.clicked.connect(lambda _=False, row=r: self._ask_reset(row))
        lay.addWidget(reset_btn)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("GhostButton")
        del_btn.setFocusPolicy(Qt.StrongFocus)
        del_btn.setEnabled(r.teacher_id != _PRESET_TEACHER_ID)
        del_btn.clicked.connect(lambda _=False, row=r, fr=frame: self._mark_deleted(row, fr))
        lay.addWidget(del_btn)
        return frame

    def _ask_reset(self, row: _TeacherRow) -> None:
        d = ReasonDialog("重置密码", f"为 {row.name()} 设置新密码", "确定", parent=self)
        d.edit.setEchoMode(QLineEdit.Password)
        if d.exec() != ReasonDialog.Accepted:
            return
        pwd = d.text or ""
        if len(pwd) < 4:
            return
        self._resets = [x for x in self._resets if x["teacher_id"] != row.teacher_id]
        self._resets.append({"teacher_id": row.teacher_id, "new_password": pwd})

    def _mark_deleted(self, row: _TeacherRow, frame: QFrame) -> None:
        row.deleted = True
        frame.hide()

    def _add_new(self) -> None:
        name = self.new_name_edit.text().strip()
        pwd = self.new_pwd_edit.text().strip()
        if not name or len(pwd) < 4:
            return
        self._new_teachers.append({"name": name, "password": pwd})
        self.new_name_edit.clear()
        self.new_pwd_edit.clear()
        self._new_label.setText("待新建：" + "、".join(t["name"] for t in self._new_teachers))

    # ------------------------------------------------------------------ 结果
    @property
    def new_teachers(self) -> List[Dict[str, str]]:
        return list(self._new_teachers)

    @property
    def updates(self) -> List[Dict[str, str]]:
        out = []
        for r in self._rows:
            if not r.deleted and r.changed() and r.name():
                out.append({"teacher_id": r.teacher_id, "name": r.name()})
        return out

    @property
    def resets(self) -> List[Dict[str, str]]:
        return list(self._resets)

    @property
    def deletes(self) -> List[str]:
        return [r.teacher_id for r in self._rows if r.deleted]
