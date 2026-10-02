# -*- coding: utf-8 -*-
"""教师个人日历页：某教师一周预约/停诊网格 + 教师账号管理与周期可用时段。

数据来自 `teacher_admin.calendar` / `scheduling.teachers`，点击空单元格设个人停诊、
点停诊单元格恢复，点预约单元格查看提示。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QPushButton,
    QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_hint, make_label, wrap_scroll,
)

from ..common.async_mixin import PageBase
from ..appointments.availability_dialog import AvailabilityDialog
from ..appointments.teacher_dialog import TeacherManageDialog

_PERIODS = [f"第{i}节" for i in range(1, 9)]
_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class TeacherCalendarPage(PageBase):
    PAGE_TITLE = "教师日历"

    def __init__(self, ctx, parent: Optional[QWidget] = None) -> None:
        super().__init__(ctx, parent)
        self._teachers: List[dict] = []
        self._availability: List[dict] = []
        self._build_ui()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(make_label("教师日历", "PageTitle", word_wrap=False))
        title_col.addWidget(make_label("查看/维护某教师一周预约与停诊",
                                       "PageSub", word_wrap=False))
        header.addLayout(title_col)
        header.addStretch(1)

        header.addWidget(make_label("教师", "Body", word_wrap=False))
        self.teacher_combo = QComboBox()
        self.teacher_combo.currentIndexChanged.connect(self._on_teacher_changed)
        header.addWidget(self.teacher_combo)

        header.addWidget(make_label("周起始", "Body", word_wrap=False))
        self.start_edit = QDateEdit(QDate.currentDate())
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.dateChanged.connect(self._on_range_changed)
        header.addWidget(self.start_edit)

        manage_btn = make_button("教师管理", "ghost")
        manage_btn.clicked.connect(self._open_manage)
        header.addWidget(manage_btn)
        avail_btn = make_button("可用时段", "ghost")
        avail_btn.clicked.connect(self._open_availability)
        header.addWidget(avail_btn)
        refresh_btn = make_button("刷新", "primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        self._root.addLayout(header)

        self._content = QWidget()
        self._content.setObjectName("PageScrollContent")
        self._content_box = QVBoxLayout(self._content)
        self._content_box.setContentsMargins(0, 4, 0, 0)
        self._content_box.setSpacing(12)
        scroll = wrap_scroll(self._content)
        scroll.setObjectName("PageScroll")
        self._root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ 数据
    def refresh(self) -> None:
        if not self._teachers:
            self._load_teachers()
        else:
            self.refresh_calendar()

    def _load_teachers(self) -> None:
        self.call(lambda: self.ctx.adapters.scheduling.teachers(),
                  on_ok=self._on_teachers_loaded, on_fail=self._fail)

    def _on_teachers_loaded(self, teachers: List[dict]) -> None:
        self._teachers = list(teachers or [])
        self._repopulate_combo()
        if self._teachers:
            self.refresh_calendar()

    def _repopulate_combo(self) -> None:
        current = self.teacher_combo.currentData()
        self.teacher_combo.blockSignals(True)
        self.teacher_combo.clear()
        for t in self._teachers:
            self.teacher_combo.addItem(
                t.get("name") or t.get("teacher_id", ""), t.get("teacher_id"))
        idx = self.teacher_combo.findData(current) if current else -1
        if idx < 0:
            idx = 0
        self.teacher_combo.setCurrentIndex(idx)
        self.teacher_combo.blockSignals(False)

    def refresh_calendar(self) -> None:
        tid = self.teacher_combo.currentData()
        if not tid:
            return
        start = self.start_edit.date()
        end = start.addDays(6)

        def _job():
            return self.ctx.adapters.teacher_admin.calendar(
                tid, start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd"))
        self.call(_job, on_ok=self._render_grid, on_fail=self._fail)

    def _on_teacher_changed(self, _index: int) -> None:
        if self._teachers:
            self.refresh_calendar()

    def _on_range_changed(self, _qdate: QDate) -> None:
        if self._teachers:
            self.refresh_calendar()

    # ------------------------------------------------------------------ 渲染
    def _render_grid(self, cal: dict) -> None:
        self._clear_content()
        self._availability = list(cal.get("availability") or []) if cal else []
        if not cal:
            self._content_box.addWidget(make_hint("暂无数据"))
            return

        start = self.start_edit.date()
        days = [start.addDays(i) for i in range(7)]

        appt_by = {}
        for a in (cal.get("appointments") or []):
            d = a.get("date") or (a.get("scheduled_at") or "")[:10]
            p = a.get("period")
            if d and p is not None:
                appt_by[(d, int(p))] = a
        block_by = {}
        for b in (cal.get("blocks") or []):
            slot = b.get("slot") or ""
            if "#" in slot and bool(b.get("active")):
                d, p = slot.split("#")
                block_by[(d, int(p))] = b

        grid = QGridLayout()
        grid.setSpacing(6)
        for col, qd in enumerate(days, start=1):
            grid.addWidget(make_label(
                f"{qd.toString('MM-dd')}\n{_WEEKDAY_CN[qd.dayOfWeek() - 1]}",
                "TableHead", word_wrap=False), 0, col)
        for row, period in enumerate(range(1, 9), start=1):
            grid.addWidget(make_label(_PERIODS[row - 1], "Body", word_wrap=False), row, 0)
            for col, qd in enumerate(days, start=1):
                d = qd.toString("yyyy-MM-dd")
                cell = QPushButton()
                cell.setObjectName("CalCell")
                cell.setFocusPolicy(Qt.StrongFocus)
                cell.setMinimumHeight(40)
                appt = appt_by.get((d, period))
                block = block_by.get((d, period))
                if appt:
                    cell.setText(self._appt_text(appt))
                    cell.setProperty("state", "appt")
                    cell.clicked.connect(lambda _=False, a=appt: self.show_toast(
                        f"{a.get('student_name', '')} · {a.get('status', '')}"))
                elif block:
                    if block.get("teacher_id"):
                        cell.setText("停诊")
                        cell.setProperty("state", "block")
                        cell.clicked.connect(lambda _=False, dd=d, pp=period: self._unblock(dd, pp))
                    else:
                        cell.setText("全校停诊")
                        cell.setProperty("state", "block")
                        cell.clicked.connect(
                            lambda: self.show_toast("全校停诊，请在今日预约页维护"))
                else:
                    cell.setText("")
                    cell.setProperty("state", "free")
                    cell.clicked.connect(lambda _=False, dd=d, pp=period: self._block(dd, pp))
                grid.addWidget(cell, row, col)
        grid_host = QWidget()
        grid_host.setObjectName("PageScrollContent")
        grid_host.setLayout(grid)
        self._content_box.addWidget(grid_host)
        self._content_box.addWidget(make_hint("点击空单元格 = 设个人停诊；点击「停诊」= 恢复可预约"))
        self._content_box.addStretch(1)

    @staticmethod
    def _appt_text(a: dict) -> str:
        status = a.get("status")
        name = a.get("student_name", "")
        if status == "done":
            return f"{name}·完成"
        if status == "cancelled":
            return "已取消"
        if status == "no_show":
            return "爽约"
        return name

    # ------------------------------------------------------------------ 动作
    def _block(self, date_str: str, period: int) -> None:
        tid = self.teacher_combo.currentData()

        def _job():
            return self.ctx.adapters.block.batch_set(
                [{"year": date_str[:4], "month": date_str[5:7], "day": date_str[8:10],
                  "period": str(period)}], True, "个人停诊", tid)
        self.call(_job, on_ok=lambda _d: (self.show_toast("已设个人停诊"), self.refresh_calendar()),
                  on_fail=self._fail)

    def _unblock(self, date_str: str, period: int) -> None:
        tid = self.teacher_combo.currentData()

        def _job():
            return self.ctx.adapters.block.batch_set(
                [{"year": date_str[:4], "month": date_str[5:7], "day": date_str[8:10],
                  "period": str(period)}], False, None, tid)
        self.call(_job, on_ok=lambda _d: (self.show_toast("已恢复可预约"), self.refresh_calendar()),
                  on_fail=self._fail)

    def _open_manage(self) -> None:
        dialog = TeacherManageDialog(self._teachers, parent=self)
        if dialog.exec() != TeacherManageDialog.Accepted:
            return
        adm = self.ctx.adapters.teacher_admin

        def _job():
            for t in dialog.new_teachers:
                adm.create(t["name"], t["password"])
            for upd in dialog.updates:
                adm.update(upd["teacher_id"], upd["name"])
            for rst in dialog.resets:
                adm.reset_password(rst["teacher_id"], rst["new_password"])
            for tid in dialog.deletes:
                adm.delete(tid)
            return True
        self.call(_job, on_ok=lambda _d: (self.show_toast("教师已更新"), self._load_teachers()),
                  on_fail=self._fail)

    def _open_availability(self) -> None:
        tid = self.teacher_combo.currentData()
        if not tid:
            return
        dialog = AvailabilityDialog(self.teacher_combo.currentText(),
                                    self._availability, parent=self)
        if dialog.exec() != AvailabilityDialog.Accepted:
            return

        def _job():
            return self.ctx.adapters.teacher_admin.set_availability(tid, dialog.items)
        self.call(_job, on_ok=lambda _d: (self.show_toast("可用时段已保存"), self.refresh_calendar()),
                  on_fail=self._fail)

    # ------------------------------------------------------------------ 工具
    def _fail(self, exc: Exception) -> None:
        self.show_toast(getattr(exc, "message", "操作失败，请再试一次"))

    def _clear_content(self) -> None:
        while self._content_box.count():
            item = self._content_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
