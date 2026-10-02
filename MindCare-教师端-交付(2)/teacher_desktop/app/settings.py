# -*- coding: utf-8 -*-
"""全局配置 + 适配器工厂（**全应用唯一知道"数据从哪来"的地方**）。

已切换为纯真实接口模式（无 mock）：
    python -m teacher_desktop.app.main --server http://127.0.0.1:8080

纪律：
- 界面层只拿工厂产出的适配器协议对象（core.adapters.base.*），不得 import 具体实现；
- 预约/预警/回复/导出统一走 core.data_gateway.DataGateway（/db/read + /db/write）；
- 既有 5 个冻结接口（登录/分诊/详情/工单/健康检查）仍走 TriageClient → ApiClient。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Optional

#: 服务端地址（不含 /api/v1，ApiClient 内部拼接）
DEFAULT_SERVER = "http://127.0.0.1:8080"

#: 分诊轮询（契约/方案：30s；连续失败 3 次间隔翻倍 30→60→120，恢复重置）
POLL_SECONDS = 30
POLL_BACKOFF_STEPS = (30, 60, 120)
POLL_FAIL_THRESHOLD = 3


@dataclass
class Settings:
    server: str = DEFAULT_SERVER


def parse_args(argv: Optional[list] = None) -> Settings:
    parser = argparse.ArgumentParser(description="MindCare 教师端")
    parser.add_argument("--server", default=DEFAULT_SERVER,
                        help="服务端地址，如 http://192.168.1.100:8080")
    ns = parser.parse_args(argv)
    return Settings(server=ns.server.rstrip("/"))


# ------------------------------------------------------------------ 适配器工厂

def make_adapters(settings: Settings):
    """创建新功能适配器，统一注入 DataGateway。返回一个简单容器（属性访问）。"""
    from ..core.data_gateway import DataGateway
    from ..core.adapters.appointment_adapter import HttpAppointmentAdapter
    from ..core.adapters.block_adapter import HttpBlockAdapter
    from ..core.adapters.export_adapter import HttpExportAdapter
    from ..core.adapters.reply_adapter import HttpReplyAdapter
    from ..core.adapters.scheduling_adapter import HttpSchedulingAdapter
    from ..core.adapters.student_admin_adapter import HttpStudentAdminAdapter
    from ..core.adapters.teacher_admin_adapter import HttpTeacherAdminAdapter
    from ..core.adapters.waitlist_adapter import HttpWaitlistAdapter
    from ..core.adapters.warning_adapter import HttpWarningAdapter

    gateway = DataGateway(settings.server)
    return Adapters(
        appointment=HttpAppointmentAdapter(gateway),
        warning=HttpWarningAdapter(gateway),
        reply=HttpReplyAdapter(gateway),
        export=HttpExportAdapter(gateway),
        block=HttpBlockAdapter(gateway),
        student_admin=HttpStudentAdminAdapter(gateway),
        scheduling=HttpSchedulingAdapter(gateway),
        waitlist=HttpWaitlistAdapter(gateway),
        teacher_admin=HttpTeacherAdminAdapter(gateway),
    )


@dataclass
class Adapters:
    appointment: object
    warning: object
    reply: object
    export: object
    block: object
    student_admin: object
    scheduling: object
    waitlist: object
    teacher_admin: object
