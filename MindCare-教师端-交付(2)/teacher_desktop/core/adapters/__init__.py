# -*- coding: utf-8 -*-
"""【分区 C】新功能适配层。

所有新能力（预约/预警/回复库/导出）的唯一实现：Http*Adapter，
统一走 core.data_gateway.DataGateway（POST /db/read + POST /db/write）。

ui/ 只 import 本包 base.py 的协议与 core.models 的数据类。
"""
from .appointment_adapter import HttpAppointmentAdapter
from .export_adapter import HttpExportAdapter
from .reply_adapter import HttpReplyAdapter
from .warning_adapter import HttpWarningAdapter

__all__ = [
    "HttpAppointmentAdapter",
    "HttpWarningAdapter",
    "HttpReplyAdapter",
    "HttpExportAdapter",
]
