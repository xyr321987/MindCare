# -*- coding: utf-8 -*-
"""统一数据网关 —— 全应用读取/上传数据库的唯一出口（当前为 **待填充** 状态）。

接口已经留好，数据库对接同学只需填充 `read()` / `write()` 两个方法体：

    gateway.read(resource, params)   → 从数据库读
    gateway.write(action, payload)   → 向数据库写（所有上传都走这一个入口）

填充方式二选一（详见 docs/数据库接入指南.md）：
  A) HTTP 网关：服务端实现 POST /db/read、POST /db/write 两个端点后，
     把 read()/write() 方法体换成 `_http_read()` / `_http_write()` 调用即可；
  B) 直连数据库：在 read()/write() 里改用你们的数据库驱动实现
     （UI 已保证所有调用都在 worker 线程，方法体同步阻塞即可，不要弹 UI）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from desktop_common.api import ApiClient


class InterfacePendingError(NotImplementedError):
    """接口待填充：数据库对接尚未完成。message 会被 UI 原样提示。"""


# ---------------------------------------------------------------------------
# 资源注册表（read）—— key 即协议中的 resource 字符串，value 为中文说明
# ---------------------------------------------------------------------------
RESOURCE_REGISTRY: Dict[str, str] = {
    "appointments.pending":   "待预约的求助工单列表（status=pending_request）",
    "appointments.by_date":   "某日全部预约/完成记录（按 scheduled_at 升序）",
    "blocks.list":            "全部不可预约时段（教师端维护，学生端只读）",
    "warnings.list":          "全部预警记录（active 在前，dismissed 在后）",
    "replies.list":           "全部回复条目（updated_at 倒序，含停用）",
    "export.classes":         "可选班级下拉列表",
    "export.rows":            "跨班问卷汇总行（零正文，仅枚举/标记列）",
    "rooms.list":             "全部咨询室（含启用状态）",
    "teachers.list":          "全部教师（供预约选择教师）",
    "appointments.events":    "某预约的操作日志（取消/改期/爽约等留痕）",
    "stats.appointments":     "按日期区间统计预约量/完成率/教师/咨询室/状态",
    "waitlist.list":          "候补队列（按日期/状态筛选）",
    "teacher_calendar":       "某教师区间内的预约/停诊/周期可用性",
}

# ---------------------------------------------------------------------------
# 动作注册表（write）—— key 即协议中的 action 字符串
# ---------------------------------------------------------------------------
ACTION_REGISTRY: Dict[str, str] = {
    "appointments.schedule":  "老师选定预约时间，写入预约库（含教师/咨询室/冲突检测）",
    "appointments.complete":  "标记预约已完成（约谈结束）",
    "appointments.reschedule": "改期预约（教师/咨询室/时间），检测冲突并留痕",
    "appointments.cancel":    "取消预约（记录原因，工单回退 pending）",
    "appointments.no_show":   "标记学生爽约（记录备注）",
    "blocks.set":             "设定/取消某格不可预约",
    "blocks.batch_set":       "批量设定/关闭多个时段",
    "rooms.create":           "新建咨询室",
    "rooms.update":           "编辑咨询室（名称/启用）",
    "rooms.delete":           "删除咨询室",
    "waitlist.join":          "把学生加入某时段候补",
    "waitlist.cancel":        "取消候补（退候补）",
    "teachers.create":        "新建教师（含初始密码与工号）",
    "teachers.update":        "编辑教师（名称/工号）",
    "teachers.reset_password": "重置教师密码",
    "teachers.delete":        "删除教师",
    "teachers.availability.set": "批量设定教师周期可用时段",
    "warnings.dismiss":       "老师约谈后消除预警，留痕",
    "replies.create":         "新建回复条目",
    "replies.update":         "编辑回复条目（正文/标签/启用）",
    "replies.delete":         "删除回复条目",
    "students.set_history":   "标记/取消学生心理疾病史",
    "students.reset_password": "重置学生密码",
}


class DataGateway:
    """读取与上传的唯一入口。适配层注入同一个实例；UI 不感知本类。"""

    def __init__(self, server: str) -> None:
        self.server = server
        self.client = ApiClient(server, role="teacher")

    # ================================================================ 待填充
    def read(self, resource: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """从数据库读取。resource 必须在 RESOURCE_REGISTRY 中。"""
        if resource not in RESOURCE_REGISTRY:
            raise ValueError(f"未注册的资源: {resource}")
        return self._http_read(resource, params)

    def write(self, action: str, payload: Dict[str, Any]) -> Any:
        """向数据库写入。action 必须在 ACTION_REGISTRY 中。"""
        if action not in ACTION_REGISTRY:
            raise ValueError(f"未注册的动作: {action}")
        return self._http_write(action, payload)

    # ------------------------------------------------- 参考实现（HTTP 网关方案）
    # 服务端实现 POST /db/read、POST /db/write 后，把上面两个方法体换成这里即可。
    def _ensure_token(self) -> None:
        """与 TriageClient 共享磁盘登录态；调用前确保 token 已恢复。"""
        if not self.client.token:
            self.client.load_session()

    def _http_read(self, resource: str, params: Optional[Dict[str, Any]]) -> Any:
        self._ensure_token()
        return self.client.post("/db/read", body={
            "resource": resource,
            "params": params or {},
        })

    def _http_write(self, action: str, payload: Dict[str, Any]) -> Any:
        self._ensure_token()
        return self.client.post("/db/write", body={
            "action": action,
            "payload": payload or {},
        })
