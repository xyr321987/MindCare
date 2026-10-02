# -*- coding: utf-8 -*-
"""预约适配器：统一走数据网关（DataGateway）。

单线流程：pending_requests（待预约求助）→ schedule → scheduled（已预约）→ complete → done。
"""
from __future__ import annotations

from typing import List, Optional

from .base import AppointmentAdapter
from ..data_gateway import DataGateway
from ..models import Appointment


def _to_appointment(raw: dict) -> Appointment:
    return Appointment(
        appointment_id=raw.get("appointment_id", ""),
        student_id=raw.get("student_id", ""),
        student_name=raw.get("student_name", ""),
        class_name=raw.get("class_name", ""),
        ticket_id=raw.get("ticket_id", ""),
        scheduled_at=raw.get("scheduled_at"),
        status=raw.get("status", "scheduled"),
        note=raw.get("note"),
        created_at=raw.get("created_at"),
        help_text_preview=raw.get("help_text_preview", ""),
        questionnaire=raw.get("questionnaire"),
        treehole=raw.get("treehole"),
    )


class HttpAppointmentAdapter(AppointmentAdapter):
    """预约数据全部走统一网关：read / db/write。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def pending_requests(self) -> List[Appointment]:
        data = self.gateway.read("appointments.pending")
        return [_to_appointment(r) for r in (data or {}).get("items", [])]

    def list_by_date(self, date: str) -> List[Appointment]:
        data = self.gateway.read("appointments.by_date", {"date": date})
        return [_to_appointment(r) for r in (data or {}).get("items", [])]

    def schedule(self, student_id: str, ticket_id: str,
                 scheduled_at: str, note: Optional[str]) -> Appointment:
        data = self.gateway.write("appointments.schedule", {
            "student_id": student_id,
            "ticket_id": ticket_id,
            "scheduled_at": scheduled_at,
            "note": note,
        })
        return _to_appointment(data or {})

    def complete(self, appointment_id: str) -> Appointment:
        data = self.gateway.write("appointments.complete", {
            "appointment_id": appointment_id,
        })
        return _to_appointment(data or {})
