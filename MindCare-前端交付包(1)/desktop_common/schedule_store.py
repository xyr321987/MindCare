"""**不可预约时段**库（教师端设定、学生端实时同步；`schedule_blocks.jsonl`）。

背景
----
教师可以在课表上把某一格设成「不可预约」（那节课老师不在/已排满），
设定必须**立刻**出现在学生端的同一张表上（红框 + 不可点）。
服务端实现见 `docs/预约时间-数据库与接口契约.md` §6；联调前前端用本机
JSON Lines 落库，字段与服务端同名表逐字节对齐。

存储与格式纪律（与 `appointments.py` **同一套**）
----------------------------------------------
* **JSON Lines**（一行一个 JSON object）；
* 位置 `%LOCALAPPDATA%\\MindCare\\schedule_blocks.jsonl`（`MINDCAKE_BLOCK_DIR` 可整体改目录）；
* **失败一律静默**：无权限 / 磁盘满 / 半截写入都不抛异常；
* **坏行跳过**：单行损坏不影响其余行。

为什么是 **append-only + `active` 开关**，而不是"删除那一行"
---------------------------------------------------------
JSON Lines 的删除=重写整个文件，多端同时开着（教师端在改、学生端在读）时
会读到半截文件。`active` 只追加、不改写，`is_blocked()` 取**该格子最后一条**
记录的 `active` —— 追加写天然原子（单行 `O_APPEND`），双端都不会读到撕裂数据。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:  # 包内导入
    from . import schedule as schedule_mod
    from . import session as session_mod
    from .api import new_id, now_iso
except ImportError:  # pragma: no cover - 直接以脚本路径导入时的兜底
    import schedule as schedule_mod  # type: ignore
    import session as session_mod  # type: ignore
    from api import new_id, now_iso  # type: ignore

__all__ = [
    "BLOCK_FILE_NAME", "DIR_ENV_VAR", "ID_PREFIX",
    "block_dir", "block_file", "new_block_id",
    "build_block_record", "append_block", "list_blocks",
    "blocked_slots", "is_blocked", "set_blocked", "toggle_block",
]

#: 与 `apt_` 并列的新增前缀（不可预约时段记录）
ID_PREFIX = "blk_"

BLOCK_FILE_NAME = "schedule_blocks.jsonl"

#: 覆盖存储目录（自检 / 多实例隔离用；与 `MINDCAKE_APPOINTMENT_DIR` 同款）
DIR_ENV_VAR = "MINDCAKE_BLOCK_DIR"


# --------------------------------------------------------------------------- 路径


def block_dir() -> Path:
    """不可预约时段库的目录（默认复用 `session_dir()` 的 `%LOCALAPPDATA%\\MindCare`）。"""
    override = (os.environ.get(DIR_ENV_VAR) or "").strip()
    if override:
        return Path(override)
    return session_mod.session_dir()


def block_file() -> Path:
    """`<block_dir()>/schedule_blocks.jsonl`。"""
    return block_dir() / BLOCK_FILE_NAME


# --------------------------------------------------------------------------- 记录


def new_block_id() -> str:
    """`blk_` + 随机串（沿用 `api.new_id` 的随机口径）。"""
    return new_id(ID_PREFIX)


def build_block_record(*, year: Any, month: Any, day: Any, period: Any,
                       active: bool = True, reason: Optional[str] = None,
                       operator: str = "") -> Optional[Dict[str, Any]]:
    """组装一条不可预约时段记录。

    `year/month/day/period` 任一为 `None` / 非法（月份不在 1~12、节次不在 1~8、
    日期是 2 月 30 日这种）时返回 `None`，**不写库** —— 宁可"设不上"也不要
    在库里留一条定位不到的记录。
    """
    try:
        year_i, month_i, day_i, period_i = (
            int(year), int(month), int(day), int(period))
    except (TypeError, ValueError):
        return None
    if not 1 <= month_i <= 12:
        return None
    if not schedule_mod.PERIOD_INDEX_MIN <= period_i <= schedule_mod.PERIOD_INDEX_MAX:
        return None
    if schedule_mod.weekday_from_date(year_i, month_i, day_i) < 0:
        return None
    return {
        "blk_id": new_block_id(),
        "year": f"{year_i:04d}",
        "month": f"{month_i:02d}",
        "day": f"{day_i:02d}",
        "period": str(period_i),
        "weekday": str(schedule_mod.weekday_from_date(year_i, month_i, day_i)),
        "slot": schedule_mod.slot_id(year_i, month_i, day_i, period_i),
        "active": bool(active),
        "reason": reason,
        "operator": str(operator or ""),
        "created_ts": now_iso(),
    }


# --------------------------------------------------------------------------- 读写


def append_block(record: Optional[dict], *, path: Optional[Path] = None) -> bool:
    """追加一条记录（**原子追加，不改写既有行**）。失败静默返回 `False`。"""
    if not isinstance(record, dict):
        return False
    target = Path(path) if path is not None else block_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except OSError:
        return False


def list_blocks(*, path: Optional[Path] = None) -> List[dict]:
    """按写入顺序读取全部记录（坏行跳过）。**不抛异常**。"""
    target = Path(path) if path is not None else block_file()
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


def blocked_slots(*, path: Optional[Path] = None) -> Set[str]:
    """当前**处于不可预约**状态的格子集合（`{"2026-10-05#3", ...}`）。

    判定：同一格子取**最后一条**记录的 `active`。这样"设 → 取消 → 再设"
    只追加三行，读出来永远是当前状态。
    """
    latest: Dict[str, bool] = {}
    for item in list_blocks(path=path):
        slot = str(item.get("slot") or "").strip()
        if not slot:
            continue
        latest[slot] = bool(item.get("active", True))
    return {slot for slot, active in latest.items() if active}


def is_blocked(year: Any, month: Any, day: Any, period: Any,
               *, path: Optional[Path] = None) -> bool:
    """该格子是否被教师设成不可预约。"""
    try:
        slot = schedule_mod.slot_id(int(year), int(month), int(day), int(period))
    except (TypeError, ValueError):
        return False
    return slot in blocked_slots(path=path)


def set_blocked(year: Any, month: Any, day: Any, period: Any, active: bool,
                *, reason: Optional[str] = None, operator: str = "",
                path: Optional[Path] = None) -> bool:
    """把某格设为「不可预约」(`active=True`) 或「恢复可预约」(`active=False`)。

    **只追加一条新记录**，不改写历史行（见模块 docstring 的 append-only 说明）。
    """
    record = build_block_record(year=year, month=month, day=day, period=period,
                                active=active, reason=reason, operator=operator)
    return append_block(record, path=path)


def toggle_block(year: Any, month: Any, day: Any, period: Any, *,
                 operator: str = "", path: Optional[Path] = None) -> Optional[bool]:
    """切换某格的不可预约状态。

    :return: 切换**之后**该格是否不可预约；格子非法时返回 `None`
    """
    try:
        year_i, month_i, day_i, period_i = (
            int(year), int(month), int(day), int(period))
    except (TypeError, ValueError):
        return None
    record_check = build_block_record(year=year_i, month=month_i, day=day_i,
                                      period=period_i, active=True)
    if record_check is None:
        return None
    target = not is_blocked(year_i, month_i, day_i, period_i, path=path)
    written = set_blocked(year_i, month_i, day_i, period_i, target,
                          operator=operator, path=path)
    return target if written else None
