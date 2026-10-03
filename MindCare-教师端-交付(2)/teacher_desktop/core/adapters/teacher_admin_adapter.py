# -*- coding: utf-8 -*-
"""教师账号管理 + 个人日历适配器：统一走数据网关（DataGateway）。"""
from __future__ import annotations

from typing import List, Optional

from .base import TeacherAdminAdapter
from ..data_gateway import DataGateway


class HttpTeacherAdminAdapter(TeacherAdminAdapter):
    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def create(self, name: str, password: str,
               teacher_no: Optional[str] = None) -> dict:
        return self.gateway.write("teachers.create", {
            "name": name, "password": password, "teacher_no": teacher_no,
        })

    def update(self, teacher_id: str, name: Optional[str] = None,
               teacher_no: Optional[str] = None) -> dict:
        return self.gateway.write("teachers.update", {
            "teacher_id": teacher_id, "name": name, "teacher_no": teacher_no,
        })

    def reset_password(self, teacher_id: str, new_password: str) -> dict:
        return self.gateway.write("teachers.reset_password", {
            "teacher_id": teacher_id, "new_password": new_password,
        })

    def delete(self, teacher_id: str) -> dict:
        return self.gateway.write("teachers.delete", {"teacher_id": teacher_id})

    def set_availability(self, teacher_id: str, items: List[dict]) -> dict:
        return self.gateway.write("teachers.availability.set", {
            "teacher_id": teacher_id, "items": items,
        })

    def calendar(self, teacher_id: str, start: str, end: str) -> dict:
        return self.gateway.read("teacher_calendar", {
            "teacher_id": teacher_id, "start": start, "end": end,
        })
