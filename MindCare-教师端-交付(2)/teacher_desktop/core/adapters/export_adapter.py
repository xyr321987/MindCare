# -*- coding: utf-8 -*-
"""跨班汇总导出适配器：统一走数据网关（DataGateway）。

隐私红线（硬约束）：**零正文** —— 服务端查询不取 detail/plain_note/treehole，
只返回枚举/标记列（见 core.models.ExportRow.COLUMNS）。
"""
from __future__ import annotations

from typing import List, Optional

from .base import ExportAdapter
from ..data_gateway import DataGateway
from ..models import ExportRow


def _to_row(raw: dict) -> ExportRow:
    return ExportRow(
        student_id=raw.get("student_id", ""),
        name=raw.get("name", ""),
        class_name=raw.get("class_name", ""),
        date=raw.get("date", ""),
        ts=raw.get("ts", ""),
        mood=raw.get("mood", ""),
        cause_category=raw.get("cause_category"),
        request_help=bool(raw.get("request_help")),
        consent_share=bool(raw.get("consent_share")),
        ticket_status=raw.get("ticket_status", "") or "",
    )


class HttpExportAdapter(ExportAdapter):
    """导出数据全部走统一网关：read / db/write。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def classes(self) -> List[str]:
        data = self.gateway.read("export.classes")
        return list((data or {}).get("items", []))

    def fetch_rows(self, start: str, end: str,
                   class_name: Optional[str] = None) -> List[ExportRow]:
        data = self.gateway.read("export.rows", {
            "start": start,
            "end": end,
            "class_name": class_name,
        })
        rows = (data or {}).get("items", [])
        rows.sort(key=lambda r: (r.get("date", ""), r.get("class_name", ""), r.get("ts", "")))
        return [_to_row(r) for r in rows]
