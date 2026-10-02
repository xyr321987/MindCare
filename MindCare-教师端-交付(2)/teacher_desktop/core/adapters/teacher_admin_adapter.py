# -*- coding: utf-8 -*-
"""教师账号管理 + 个人日历适配器：统一走数据网关（DataGateway）。"""
from __future__ import annotations

from typing import List

from .base import TeacherAdminAdapter
from ..data_gateway import DataGateway


class HttpTeacherAdminAdapter(TeacherAdminAdapter):
    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def create(self, name: str, password: str) -> dict:
        return self.gateway.write("teachers.create", {
            "name": name, "password": password,
        })

    def update(self, teacher_id: str, name: str) -> dict:
        return self.gateway.write("teachers.update", {
            "teacher_id": teacher_id, "name": name,
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
