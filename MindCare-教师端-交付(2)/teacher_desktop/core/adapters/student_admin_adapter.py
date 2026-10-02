# -*- coding: utf-8 -*-
"""学生管理适配器：病史标记 / 重置密码（统一走 DataGateway）。"""
from __future__ import annotations

from .base import StudentAdminAdapter
from ..data_gateway import DataGateway


class HttpStudentAdminAdapter(StudentAdminAdapter):
    """学生管理全部走统一网关：write students.set_history / students.reset_password。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def set_history(self, student_id: str, has_history: bool) -> dict:
        return self.gateway.write("students.set_history", {
            "student_id": student_id, "has_history": bool(has_history),
        })

    def reset_password(self, student_id: str, new_password: str) -> dict:
        return self.gateway.write("students.reset_password", {
            "student_id": student_id, "new_password": new_password,
        })
