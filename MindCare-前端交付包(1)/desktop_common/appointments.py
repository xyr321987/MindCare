"""预约时间**本地演示存储**（与 `desktop_common/session.py` 同一套"本机用户级、不写工程目录"纪律）。

背景
----

契约 v1.0 只有 11 个端点，**没有预约时间**。本次新增「预约时间数据库」的落库与老师端读取
在**服务端**（不在本交付包内），对应结构见 `docs/预约时间-数据库与接口契约.md`。

前端按「前端 + 契约文档」方案落地：学生端在本机以 **JSON Lines**（与服务端同款：
一行一个 JSON object，键名/时间格式/ID 前缀都对齐契约 §1 的口径）持久化一份预约记录，
作为**可演示、可被自检断言的本地事实**；联调时由服务端按契约文档实现同名端点后无缝替换。

存储位置
--------

`%LOCALAPPDATA%\\MindCare\\appointments.jsonl`（用户级本地目录，**绝不写进工程目录**）。

* 路径不写死：`LOCALAPPDATA` → `XDG_DATA_HOME` → `~/.local/share` → 临时目录依次兜底；
* 测试覆盖钩子：`MINDCAKE_APPOINTMENT_DIR` 可整体改目录（自检隔离用）。

文件格式
--------

    每行一个预约记录（JSON Lines，与服务端契约 §1 口径一致）：

        {"apt_id": "apt_...", "student_id": "stu_...", "name": "…", "class_name": "…",
         "year": "2026", "month": "10", "day": "2", "time": "09:00",
         "share_questionnaire": true, "share_treehole": false,
         "created_ts": "2026-10-02T22:31:05+08:00"}

    v1.1 追加（**课表定位**，见 `docs/预约时间-数据库与接口契约.md` §5）：
    `period`（第几节 1~8）、`weekday`（1~7，1=周一）、`time_start` / `time_end`、
    `slot`（`YYYY-MM-DD#P`，冗余索引）。v1.0 那 9 个字段**一个字都没改**，
    老记录（只有 `time`）仍可读（`record_slot()` 按起始钟点回推节次）。

失败一律静默
------------

无权限 / 磁盘满 / 半截写入 —— 一律**不抛异常**，不影响问卷主流程。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # 包内导入
    from . import schedule as schedule_mod
    from . import session as session_mod
    from .api import new_id, now_iso
except ImportError:  # pragma: no cover - 直接以脚本路径导入时的兜底
    import schedule as schedule_mod  # type: ignore
    import session as session_mod  # type: ignore
    from api import new_id, now_iso  # type: ignore

__all__ = [
    "APPOINTMENT_FILE_NAME", "DIR_ENV_VAR", "ID_PREFIX",
    "appointment_dir", "appointment_file", "new_appointment_id",
    "build_appointment_record", "append_appointment", "list_appointments",
    "record_slot", "appointment_slots", "appointments_at",
]

#: 契约 v1.0 `id_prefixes` 之外新增的预约 ID 前缀（与契约文档一致）。
ID_PREFIX = "apt_"

APPOINTMENT_FILE_NAME = "appointments.jsonl"

#: 覆盖存储目录（自检 / 多实例隔离用；与 session 的 `MINDCAKE_SESSION_DIR` 同款）
DIR_ENV_VAR = "MINDCAKE_APPOINTMENT_DIR"


# --------------------------------------------------------------------------- 路径


def appointment_dir() -> Path:
    """预约数据目录（默认复用 `session_dir()` 的 `%LOCALAPPDATA%\\MindCare`）。"""
    override = (os.environ.get(DIR_ENV_VAR) or "").strip()
    if override:
        return Path(override)
    return session_mod.session_dir()


def appointment_file() -> Path:
    """预约数据文件全路径：`<appointment_dir()>/appointments.jsonl`。"""
    return appointment_dir() / APPOINTMENT_FILE_NAME


# --------------------------------------------------------------------------- ID / 记录


def new_appointment_id() -> str:
    """客户端生成的幂等键：`apt_` + 随机串（沿用 `api.new_id` 的随机口径）。"""
    return new_id(ID_PREFIX)


def build_appointment_record(*, student_id: str, name: str,
                             class_name: Optional[str],
                             appointment: Optional[dict]) -> Optional[dict]:
    """把界面选出的预约载荷，组装成一条完整预约记录。

    `appointment` 来自 `AppointmentPage.confirmed` 发出、`FlowState.appointment`
    透传的 dict，形如::

        {"year": "2026", "month": "10", "day": "2", "period": "3",
         "weekday": "5", "time": "09:55", "time_start": "09:55",
         "time_end": "10:40",
         "share_questionnaire": True, "share_treehole": False}

    缺 `appointment` 时返回 `None`（表示没有预约，调用方跳过落库）。

    ⚠️ **v1.1 追加的 4 个字段**（`period` / `weekday` / `time_start` / `time_end`）
    是**增量**：v1.0 那 9 个字段的键名、类型、取值口径一个字都没改，
    老记录照样读得出来（`record_slot()` 会按 `time` 回推节次）。
    """
    if not isinstance(appointment, dict):
        return None
    record: Dict[str, Any] = {
        "apt_id": new_appointment_id(),
        "student_id": str(student_id or ""),
        "name": str(name or ""),
        "class_name": class_name,
        "year": str(appointment.get("year", "")),
        "month": str(appointment.get("month", "")),
        "day": str(appointment.get("day", "")),
        "time": str(appointment.get("time", "")),
        "share_questionnaire": bool(appointment.get("share_questionnaire", False)),
        "share_treehole": bool(appointment.get("share_treehole", False)),
        "created_ts": now_iso(),
    }

    # --- 课表定位（第几节 / 星期几 / 起止钟点）--------------------------------
    # 界面给的是 `period`（1~8）；`weekday` 与起止钟点**由 `schedule.PERIODS`
    # 和真实日历推导**，不信任客户端传值 —— 否则不同端算出不同的表。
    period = _coerce_period(appointment.get("period"))
    if period is None:
        period = schedule_mod.period_of_time(record["time"])
    if period is not None:
        record["period"] = str(period)
        record["time_start"] = str(appointment.get("time_start")
                                   or schedule_mod.period_start(period))
        record["time_end"] = str(appointment.get("time_end")
                                 or schedule_mod.period_end(period))
        if not record["time"]:
            record["time"] = record["time_start"]
    weekday = schedule_mod.weekday_from_date(_as_int(record["year"]),
                                             _as_int(record["month"]),
                                             _as_int(record["day"]))
    if 1 <= weekday <= 7:
        record["weekday"] = str(weekday)
    record["slot"] = record_slot(record)
    return record


def _as_int(value: Any, default: int = 0) -> int:
    """尽力转 int（转不出来给 `default`，**不抛异常**）。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _coerce_period(value: Any) -> Optional[int]:
    """把 `period` 规范成 1~8；非法返回 `None`。"""
    try:
        period = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if schedule_mod.PERIOD_INDEX_MIN <= period <= schedule_mod.PERIOD_INDEX_MAX:
        return period
    return None


def record_slot(record: dict) -> str:
    """一条预约记录 → 格子 ID `YYYY-MM-DD#P`（界面定位用，不是数据库主键）。

    * 记录自带 `slot` 就用它；
    * 有 `period` 就直接拼；
    * **v1.0 老记录**没有 `period`，按 `time`（起始钟点）回推落在哪一节；
    * 回推不出来返回 `""`（调用方按"定位不到"处理，绝不猜）。
    """
    if not isinstance(record, dict):
        return ""
    slot = str(record.get("slot") or "").strip()
    if slot:
        return slot
    year = _as_int(record.get("year"))
    month = _as_int(record.get("month"))
    day = _as_int(record.get("day"))
    if not (year and month and day):
        return ""
    period = _coerce_period(record.get("period"))
    if period is None:
        period = schedule_mod.period_of_time(str(record.get("time") or ""))
    if period is None:
        return ""
    if schedule_mod.weekday_from_date(year, month, day) < 0:
        return ""
    return schedule_mod.slot_id(year, month, day, period)


def appointment_slots(*, student_id: Optional[str] = None,
                      path: Optional[Path] = None) -> Dict[str, dict]:
    """`格子 ID -> 预约记录`（同一格多条时取**最后一条**，与 blocks 同款口径）。

    :param student_id: 给了就只看这位同学的（学生端用它标"我的预约"）
    """
    out: Dict[str, dict] = {}
    for item in list_appointments(path=path):
        if student_id is not None and str(item.get("student_id") or "") != str(student_id):
            continue
        slot = record_slot(item)
        if slot:
            out[slot] = item
    return out


def appointments_at(year: Any, month: Any, day: Any, period: Any,
                    *, path: Optional[Path] = None) -> List[dict]:
    """某个格子上的全部预约记录（按写入顺序；教师端看"谁约了"用）。"""
    target = schedule_mod.slot_id(year, month, day, period)
    return [item for item in list_appointments(path=path)
            if record_slot(item) == target]


# --------------------------------------------------------------------------- 读写


def append_appointment(record: Optional[dict], *, path: Optional[Path] = None) -> bool:
    """把一条预约记录**追加**到本地 JSON Lines 文件。**不抛异常**。

    :param record: `build_appointment_record()` 的返回值；`None` 时直接返回 `False`
    :param path: 覆盖文件路径（自检用）
    :return: 是否真的写入了（失败 / 空记录时返回 `False`）
    """
    if not isinstance(record, dict):
        return False
    target = Path(path) if path is not None else appointment_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except OSError:
        return False


def list_appointments(*, path: Optional[Path] = None) -> List[dict]:
    """读取本地全部预约记录（按写入顺序）。**不抛异常**。

    半截写入 / 单行损坏的行会被跳过（其余行照常返回），与 session 的
    "坏数据不崩、宁可缺一条"同一纪律。
    """
    target = Path(path) if path is not None else appointment_file()
    out: List[dict] = []
    try:
        raw_lines = target.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return out
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out