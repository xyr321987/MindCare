# -*- coding: utf-8 -*-
"""连续沮丧不求助预警适配器：统一走数据网关（DataGateway）。

口径（服务端计算真值，教师端只读 + 消除）：
- 连续 mood=down 且 request_help=false 满 3 次 → active 预警；
- 中途提交其他分支（happy/plain/down+求助）→ 服务端计数清零，预警不再出现；
- dismiss 表示老师已约谈，服务端清零并保留消除记录。
"""
from __future__ import annotations

from typing import List, Optional

from .base import WarningAdapter
from ..data_gateway import DataGateway
from ..models import WarningRecord


def _to_warning(raw: dict) -> WarningRecord:
    return WarningRecord(
        warning_id=raw.get("warning_id", ""),
        student_id=raw.get("student_id", ""),
        student_name=raw.get("student_name", ""),
        class_name=raw.get("class_name", ""),
        rule=raw.get("rule", "silent_down_streak"),
        streak_count=int(raw.get("streak_count") or 3),
        latest_ts=raw.get("latest_ts"),
        status=raw.get("status", "active"),
        dismissed_at=raw.get("dismissed_at"),
        dismiss_note=raw.get("dismiss_note"),
    )


def _sorted_active_first(rows: List[dict]) -> List[WarningRecord]:
    active = sorted((r for r in rows if r.get("status") == "active"),
                    key=lambda r: r.get("latest_ts") or "", reverse=True)
    dismissed = sorted((r for r in rows if r.get("status") != "active"),
                       key=lambda r: r.get("dismissed_at") or "", reverse=True)
    return [_to_warning(r) for r in active + dismissed]


class HttpWarningAdapter(WarningAdapter):
    """预警数据全部走统一网关：read / db/write。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def list_all(self) -> List[WarningRecord]:
        data = self.gateway.read("warnings.list")
        return _sorted_active_first((data or {}).get("items", []))

    def dismiss(self, warning_id: str, note: Optional[str]) -> WarningRecord:
        data = self.gateway.write("warnings.dismiss", {
            "warning_id": warning_id,
            "note": note,
        })
        return _to_warning(data or {})
