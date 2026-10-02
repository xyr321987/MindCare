# -*- coding: utf-8 -*-
"""数据导出页：班级 + 日期范围筛选 → 零正文预览表 → 导出 Excel/CSV。

隐私红线：预览与导出**只有**学号/姓名/班级/日期/时间/心情/原因分类/是否求助/
是否授权共享/工单状态十列，没有 detail / plain_note / 树洞任何正文。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout,
    QWidget,
)

from desktop_common.widgets import (
    make_error, make_label, make_primary_button,
)

from ...core.models import ExportRow
from ..common.async_mixin import PageBase
from .xlsx_writer import export_file, to_display_row

ALL_CLASSES = "全部班级"


class ExportPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._rows: List[ExportRow] = []
        self._build_ui()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(make_label("数据导出", "PageTitle", word_wrap=False))
        head.addWidget(make_label(
            "汇总不同班级的问卷数据；导出表只含枚举与状态，不含任何正文内容",
            "PageSub", word_wrap=False))
        self._root.addLayout(head)

        # ---- 筛选区
        filter_card = QFrame()
        filter_card.setObjectName("Panel")
        fl = QHBoxLayout(filter_card)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.setSpacing(12)

        fl.addWidget(make_label("班级", "Body", word_wrap=False))
        self.class_combo = QComboBox()
        self.class_combo.addItem(ALL_CLASSES)
        fl.addWidget(self.class_combo)

        fl.addWidget(make_label("日期", "Body", word_wrap=False))
        today = QDate.currentDate()
        self.start_edit = QDateEdit(today.addDays(-6))
        self.end_edit = QDateEdit(today)
        for edit in (self.start_edit, self.end_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
        fl.addWidget(self.start_edit)
        fl.addWidget(make_label("至", "Body", word_wrap=False))
        fl.addWidget(self.end_edit)

        self.query_btn = make_primary_button("查询")
        self.query_btn.clicked.connect(self.query)
        fl.addWidget(self.query_btn)
        fl.addStretch(1)

        self.export_btn = make_primary_button("导出 Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export)
        fl.addWidget(self.export_btn)
        self._root.addWidget(filter_card)

        self.error_label = make_error("")
        self._root.addWidget(self.error_label)

        # ---- 预览表
        self.count_label = make_label("尚未查询", "Hint", word_wrap=False)
        self._root.addWidget(self.count_label)

        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget
        self.table = QTableWidget(0, len(ExportRow.COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [label for _k, label in ExportRow.COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        header_view = self.table.horizontalHeader()
        # 枚举列（0-4）给固定宽度保证不截断学号/日期；文本列（5-9）均分剩余
        fixed_widths = {0: 132, 1: 78, 2: 102, 3: 120, 4: 80}
        for col in range(len(ExportRow.COLUMNS)):
            if col in fixed_widths:
                header_view.setSectionResizeMode(col, QHeaderView.Interactive)
                self.table.setColumnWidth(col, fixed_widths[col])
            else:
                header_view.setSectionResizeMode(col, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(False)
        self._root.addWidget(self.table, 1)

    # ------------------------------------------------------------------ 生命周期
    def refresh(self) -> None:
        # 首次进入：拉班级下拉，再自动查一次近 7 天
        if self.class_combo.count() <= 1:
            self.call(self.ctx.adapters.export.classes, on_ok=self._on_classes)
        else:
            self.query()

    def _on_classes(self, classes: List[str]) -> None:
        for name in classes:
            self.class_combo.addItem(name)
        self.query()

    # ------------------------------------------------------------------ 查询
    def _date_range(self):
        start = self.start_edit.date().toString("yyyy-MM-dd")
        end = self.end_edit.date().toString("yyyy-MM-dd")
        return start, end

    def query(self) -> None:
        start, end = self._date_range()
        if start > end:
            self.error_label.setText("开始日期不能晚于结束日期")
            return
        self.error_label.setText("")
        class_name = self.class_combo.currentText()
        class_name = None if class_name == ALL_CLASSES else class_name
        self.query_btn.setEnabled(False)
        self.query_btn.setText("查询中…")

        self.call(self.ctx.adapters.export.fetch_rows, start, end, class_name,
                  on_ok=self._on_rows, on_fail=self._on_query_fail)

    def _on_rows(self, rows: List[ExportRow]) -> None:
        self._rows = rows
        self.query_btn.setEnabled(True)
        self.query_btn.setText("查询")
        self._fill_table()
        self.export_btn.setEnabled(bool(rows))
        start, end = self._date_range()
        scope = self.class_combo.currentText()
        self.count_label.setText(
            f"{scope} · {start} 至 {end} · 共 {len(rows)} 条（无正文列）")

    def _on_query_fail(self, exc: Exception) -> None:
        self.query_btn.setEnabled(True)
        self.query_btn.setText("查询")
        self.error_label.setText(getattr(exc, "message", "查询失败，请再试一次"))

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            for c, value in enumerate(to_display_row(row)):
                from PySide6.QtWidgets import QTableWidgetItem
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.student_id)
                item.setToolTip(value)
                self.table.setItem(r, c, item)

    # ------------------------------------------------------------------ 导出
    def export(self) -> None:
        if not self._rows:
            return
        default_name = f"MindCare问卷汇总_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出汇总表", default_name,
            "Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)")
        if not path:
            return
        rows = list(self._rows)   # 快照，避免后台线程读 UI 状态

        def _job():
            return export_file(rows, path)

        def _ok(result):
            actual_path, fmt = result
            if fmt == "csv":
                self.show_toast(f"未安装 openpyxl，已导出 CSV：{actual_path}")
            else:
                self.show_toast(f"已导出：{actual_path}")

        self.call(_job, on_ok=_ok,
                  on_fail=lambda e: self.show_toast(
                      getattr(e, "message", "导出失败，请再试一次")))
