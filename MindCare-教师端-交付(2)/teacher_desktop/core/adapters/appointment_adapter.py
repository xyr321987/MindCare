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
        teacher_id=raw.get("teacher_id"),
        teacher_name=raw.get("teacher_name"),
        room_id=raw.get("room_id"),
        room_name=raw.get("room_name"),
        cancel_reason=raw.get("cancel_reason"),
        rescheduled_from=raw.get("rescheduled_from"),
        no_show_note=raw.get("no_show_note"),
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
                 scheduled_at: str, note: Optional[str],
                 teacher_id: Optional[str] = None,
                 room_id: Optional[str] = None) -> Appointment:
        data = self.gateway.write("appointments.schedule", {
            "student_id": student_id,
            "ticket_id": ticket_id,
            "scheduled_at": scheduled_at,
            "note": note,
            "teacher_id": teacher_id,
            "room_id": room_id,
        })
        return _to_appointment(data or {})

    def reschedule(self, appointment_id: str, scheduled_at: str,
                   teacher_id: Optional[str], room_id: Optional[str],
                   note: Optional[str]) -> Appointment:
        data = self.gateway.write("appointments.reschedule", {
            "appointment_id": appointment_id,
            "scheduled_at": scheduled_at,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "note": note,
        })
        return _to_appointment(data or {})

    def cancel(self, appointment_id: str, reason: str) -> Appointment:
        data = self.gateway.write("appointments.cancel", {
            "appointment_id": appointment_id,
            "reason": reason,
        })
        return _to_appointment(data or {})

    def no_show(self, appointment_id: str, note: str) -> Appointment:
        data = self.gateway.write("appointments.no_show", {
            "appointment_id": appointment_id,
            "note": note,
        })
        return _to_appointment(data or {})

    def complete(self, appointment_id: str) -> Appointment:
        data = self.gateway.write("appointments.complete", {
            "appointment_id": appointment_id,
        })
        return _to_appointment(data or {})
