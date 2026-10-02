# -*- coding: utf-8 -*-
"""候补队列适配器：统一走数据网关（DataGateway）。"""
from __future__ import annotations

import uuid
from typing import List, Optional

from .base import WaitlistAdapter
from ..data_gateway import DataGateway
from ..models import WaitlistEntry


def _to_entry(raw: dict) -> WaitlistEntry:
    return WaitlistEntry(
        wait_id=raw.get("wait_id", ""),
        student_id=raw.get("student_id", ""),
        student_name=raw.get("student_name", ""),
        class_name=raw.get("class_name", ""),
        ticket_id=raw.get("ticket_id", ""),
        year=raw.get("year", ""),
        month=raw.get("month", ""),
        day=raw.get("day", ""),
        period=raw.get("period", ""),
        teacher_id=raw.get("teacher_id"),
        room_id=raw.get("room_id"),
        status=raw.get("status", "waiting"),
        filled_apt_id=raw.get("filled_apt_id"),
        reason=raw.get("reason"),
        created_ts=raw.get("created_ts"),
    )


class HttpWaitlistAdapter(WaitlistAdapter):
    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def list(self, params: Optional[dict] = None) -> List[WaitlistEntry]:
        data = self.gateway.read("waitlist.list", params or {})
        return [_to_entry(r) for r in (data or {}).get("items", [])]

    def join(self, student_id: str, year: str, month: str, day: str,
             time_text: str, teacher_id: Optional[str],
             room_id: Optional[str], reason: Optional[str]) -> dict:
        return self.gateway.write("waitlist.join", {
            "wait_id": "wl_" + uuid.uuid4().hex[:12],
            "student_id": student_id,
            "year": year, "month": month, "day": day, "time": time_text,
            "teacher_id": teacher_id, "room_id": room_id, "reason": reason,
        })

    def cancel(self, wait_id: str) -> dict:
        return self.gateway.write("waitlist.cancel", {"wait_id": wait_id})
