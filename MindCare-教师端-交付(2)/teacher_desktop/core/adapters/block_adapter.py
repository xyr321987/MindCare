# -*- coding: utf-8 -*-
"""不可预约时段适配器：统一走数据网关（DataGateway）。"""
from __future__ import annotations

from typing import List, Optional

from .base import BlockAdapter
from ..data_gateway import DataGateway


class HttpBlockAdapter(BlockAdapter):
    """不可预约段全部走统一网关：read blocks.list / write blocks.set。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def list_all(self) -> List[dict]:
        data = self.gateway.read("blocks.list")
        return list((data or {}).get("items", []))

    def set(self, year: int, month: int, day: int, period: int,
            active: bool, reason: Optional[str] = None) -> dict:
        return self.gateway.write("blocks.set", {
            "year": str(year), "month": str(month), "day": str(day),
            "period": str(period), "active": bool(active), "reason": reason,
        })

    def batch_set(self, items: List[dict], active: bool,
                  reason: Optional[str] = None) -> dict:
        return self.gateway.write("blocks.batch_set", {
            "items": items, "active": bool(active), "reason": reason,
        })
