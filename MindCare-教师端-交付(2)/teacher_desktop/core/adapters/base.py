# -*- coding: utf-8 -*-
"""适配器协议（抽象基类）—— UI 只依赖这里的方法签名。

对应协议提案：docs/教师端新增接口协议提案.md
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import Appointment, ExportRow, ReplyEntry, WarningRecord


class AppointmentAdapter(ABC):
    """预约（老师定时间）。待预约来源 = 学生的求助工单。"""

    @abstractmethod
    def pending_requests(self) -> List[Appointment]:
        """待预约的求助请求（scheduled_at=None，status='pending_request'）。"""

    @abstractmethod
    def list_by_date(self, date: str) -> List[Appointment]:
        """某日全部预约/完成记录（单线流程的已预约+已完成两段）。"""

    @abstractmethod
    def schedule(self, student_id: str, ticket_id: str,
                 scheduled_at: str, note: Optional[str]) -> Appointment:
        """老师选定预约时间 → 写入预约数据库。"""

    @abstractmethod
    def complete(self, appointment_id: str) -> Appointment:
        """标记预约已完成（约谈结束）。"""


class WarningAdapter(ABC):
    """连续沮丧不求助预警（满 3 次连续触发；老师约谈后消除）。"""

    @abstractmethod
    def list_all(self) -> List[WarningRecord]:
        """全部预警记录（active 在前，dismissed 在后，按最近时间倒序）。"""

    @abstractmethod
    def dismiss(self, warning_id: str, note: Optional[str]) -> WarningRecord:
        """约谈后手动消除预警（服务端同时把该生连续计数清零并留痕）。"""


class ReplyAdapter(ABC):
    """自定义回复自由条目库（老师 CRUD；学生端展示由服务端按场景标签匹配）。"""

    @abstractmethod
    def list_all(self) -> List[ReplyEntry]:
        """全部条目（updated_at 倒序）。"""

    @abstractmethod
    def create(self, text: str, scenes: List[str]) -> ReplyEntry:
        """新建条目。"""

    @abstractmethod
    def update(self, reply_id: str, *, text: Optional[str] = None,
               scenes: Optional[List[str]] = None,
               enabled: Optional[bool] = None) -> ReplyEntry:
        """编辑正文/标签/启用状态。"""

    @abstractmethod
    def delete(self, reply_id: str) -> None:
        """删除条目。"""


class ExportAdapter(ABC):
    """跨班问卷数据汇总导出（**只取枚举/标记，服务端不得返回正文**）。"""

    @abstractmethod
    def classes(self) -> List[str]:
        """可选班级列表（下拉筛选用）。"""

    @abstractmethod
    def fetch_rows(self, start: str, end: str,
                   class_name: Optional[str] = None) -> List[ExportRow]:
        """按日期区间 [start, end]（YYYY-MM-DD）与班级取汇总行。"""


class BlockAdapter(ABC):
    """不可预约时段（教师端设定，学生端只读）。"""

    @abstractmethod
    def list_all(self) -> List[dict]:
        """全部不可预约段。"""

    @abstractmethod
    def set(self, year: int, month: int, day: int, period: int,
            active: bool, reason: Optional[str] = None) -> dict:
        """设定/取消某格不可预约。"""


class StudentAdminAdapter(ABC):
    """学生管理（病史标记 / 重置密码）。"""

    @abstractmethod
    def set_history(self, student_id: str, has_history: bool) -> dict:
        """标记/取消学生心理疾病史。"""

    @abstractmethod
    def reset_password(self, student_id: str, new_password: str) -> dict:
        """重置学生密码。"""
