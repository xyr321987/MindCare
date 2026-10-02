# -*- coding: utf-8 -*-
"""自定义回复自由条目库适配器（老师 CRUD）：统一走数据网关（DataGateway）。

条目 = 文案正文 + 场景标签（happy_end/plain_tips/help_sent/self_care）+ 启用开关。
学生端如何匹配是服务端的事，教师端只维护库。
"""
from __future__ import annotations

from typing import List, Optional

from .base import ReplyAdapter
from ..data_gateway import DataGateway
from ..models import ReplyEntry


def _to_entry(raw: dict) -> ReplyEntry:
    return ReplyEntry(
        reply_id=raw.get("reply_id", ""),
        text=raw.get("text", ""),
        scenes=list(raw.get("scenes") or []),
        enabled=bool(raw.get("enabled", True)),
        updated_at=raw.get("updated_at"),
    )


class HttpReplyAdapter(ReplyAdapter):
    """回复数据全部走统一网关：read / db/write。"""

    def __init__(self, gateway: DataGateway) -> None:
        self.gateway = gateway

    def list_all(self) -> List[ReplyEntry]:
        data = self.gateway.read("replies.list")
        rows = sorted((data or {}).get("items", []),
                      key=lambda r: r.get("updated_at") or "", reverse=True)
        return [_to_entry(r) for r in rows]

    def create(self, text: str, scenes: List[str]) -> ReplyEntry:
        data = self.gateway.write("replies.create", {
            "text": text,
            "scenes": list(scenes),
        })
        return _to_entry(data or {})

    def update(self, reply_id: str, *, text: Optional[str] = None,
               scenes: Optional[List[str]] = None,
               enabled: Optional[bool] = None) -> ReplyEntry:
        body: dict = {"reply_id": reply_id}
        if text is not None:
            body["text"] = text
        if scenes is not None:
            body["scenes"] = list(scenes)
        if enabled is not None:
            body["enabled"] = enabled
        data = self.gateway.write("replies.update", body)
        return _to_entry(data or {})

    def delete(self, reply_id: str) -> None:
        self.gateway.write("replies.delete", {"reply_id": reply_id})
