# -*- coding: utf-8 -*-
"""Excel / CSV 写出（**零正文**：列集合由 ExportRow.COLUMNS 唯一定义）。

- 优先 openpyxl 写 .xlsx；
- openpyxl 不可用或写 xlsx 失败时回退 .csv（utf-8-sig，Excel 直接打开不乱码），
  回退后文件名会变成 .csv，返回值如实告知实际写出路径。
"""
from __future__ import annotations

import csv
from typing import List, Tuple

from ...core import enums
from ...core.models import ExportRow

#: 工单状态 → 导出展示值
_TICKET_TEXT = {"pending": "待处理", "accepted": "已受理", "done": "已完成"}


def to_display_row(row: ExportRow) -> List[str]:
    """一行的可展示字符串（预览表与导出文件共用，保证两处完全一致）。"""
    return [
        row.student_id,
        row.name,
        row.class_name,
        row.date,
        enums.short_time(row.ts) or row.ts,
        enums.MOOD.get(row.mood, (row.mood or "", ""))[0],
        enums.CAUSE.get(row.cause_category or "", row.cause_category or ""),
        "是" if row.request_help else "否",
        "是" if row.consent_share else "否",
        _TICKET_TEXT.get(row.ticket_status, row.ticket_status),
    ]


def _header() -> List[str]:
    return [label for _key, label in ExportRow.COLUMNS]


def _table(rows: List[ExportRow]) -> List[List[str]]:
    return [_header()] + [to_display_row(r) for r in rows]


# ------------------------------------------------------------------ xlsx
def _write_xlsx(table: List[List[str]], path: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "问卷汇总"
    for line in table:
        ws.append(line)

    # 表头样式（雾蓝底）
    fill = PatternFill("solid", fgColor="DCE9F1")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 列宽按内容粗估（中文按 2 个宽度计）
    for col_idx, key in enumerate(ExportRow.COLUMNS, start=1):
        width = max([len(str(line[col_idx - 1])) for line in table] or [8])
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(
            max(width * 1.6 + 4, 10), 42)
    ws.freeze_panes = "A2"
    wb.save(path)


# ------------------------------------------------------------------ csv 回退
def _write_csv(table: List[List[str]], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(table)


def export_file(rows: List[ExportRow], chosen_path: str) -> Tuple[str, str]:
    """写出文件。返回 (实际路径, 格式 'xlsx'|'csv')。

    :param chosen_path: 用户在保存对话框选的路径（期望 .xlsx）
    """
    table = _table(rows)
    if chosen_path.lower().endswith(".xlsx"):
        try:
            _write_xlsx(table, chosen_path)
            return chosen_path, "xlsx"
        except ImportError:
            pass  # openpyxl 未安装 → 回退 CSV
    # 回退：同名 .csv
    csv_path = chosen_path
    if csv_path.lower().endswith(".xlsx"):
        csv_path = chosen_path[:-5] + ".csv"
    _write_csv(table, csv_path)
    return csv_path, "csv"
