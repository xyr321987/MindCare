# -*- coding: utf-8 -*-
"""既有冻结接口客户端（教师端 5 个接口：login/health/triage 三个）。

只走真实 HTTP：desktop_common.ApiClient（信封解包/token 持久化/超时重试）。
页面只依赖本类的方法签名，不直接持有 ApiClient。
"""
from __future__ import annotations

from typing import Optional

from desktop_common.api import ApiClient

from .models import StudentToday, TriageItem


class TriageClient:
    """页面使用的统一入口。全部走真实服务端。"""

    def __init__(self, server: str = "http://127.0.0.1:8080") -> None:
        self.profile: Optional[dict] = None
        self._http = ApiClient(server)

    # ---------------------------------------------------------------- 登录
    def login(self, work_id: str, password: str) -> dict:
        data = self._http.login_teacher(work_id, password)
        self.profile = self._http.profile
        return data

    def logout(self) -> None:
        self._http.clear_session()
        self.profile = None

    # ---------------------------------------------------------------- 分诊列表
    def triage_list(self, since: Optional[str] = None) -> dict:
        return self._http.triage_list(since)

    def student_today(self, student_id: str) -> dict:
        return self._http.student_today(student_id)

    def ack_ticket(self, ticket_id: str, action: str, note: Optional[str] = None) -> dict:
        return self._http.ack_ticket(ticket_id, action, note)

    # ---------------------------------------------------------------- 便捷工厂
    @staticmethod
    def parse_items(data: dict) -> list[TriageItem]:
        return [TriageItem.from_api(raw) for raw in (data.get("items") or [])]

    @staticmethod
    def parse_today(data: dict) -> StudentToday:
        return StudentToday.from_api(data)
