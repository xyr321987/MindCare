# -*- coding: utf-8 -*-
"""调度平台辅助适配器：咨询室 CRUD / 教师列表 / 预约统计 / 操作日志。

全部统一走数据网关（DataGateway /db/read + /db/write），对应服务端资源：
    rooms.list / teachers.list / appointments.events / stats.appointments
及动作：rooms.create / rooms.update / rooms.delete。
"""
from __future__ import annotations

from typing import List, Optional

from .base import SchedulingAdapter
from ..data_gateway import DataGateway


class HttpSchedulingAdapter(SchedulingAdapter):
    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def rooms(self) -> List[dict]:
        data = self.gateway.read("rooms.list")
        return list((data or {}).get("items", []))

    def create_room(self, name: str) -> dict:
        return self.gateway.write("rooms.create", {"name": name})

    def update_room(self, room_id: str, *, name: Optional[str] = None,
                    active: Optional[bool] = None) -> dict:
        payload = {"room_id": room_id}
        if name is not None:
            payload["name"] = name
        if active is not None:
            payload["active"] = bool(active)
        return self.gateway.write("rooms.update", payload)

    def delete_room(self, room_id: str) -> dict:
        return self.gateway.write("rooms.delete", {"room_id": room_id})

    def teachers(self) -> List[dict]:
        data = self.gateway.read("teachers.list")
        return list((data or {}).get("items", []))

    def stats(self, start: str, end: str) -> dict:
        return self.gateway.read("stats.appointments", {
            "start": start, "end": end,
        })

    def events(self, appointment_id: str) -> List[dict]:
        data = self.gateway.read("appointments.events", {
            "appointment_id": appointment_id,
        })
        return list((data or {}).get("items", []))
