"""预约时间常量 —— 契约 §4.4 的单一事实源（与客户端 `desktop_common/schedule.py` 逐字节对齐）。

服务端据此派生 `period/weekday/time_start/time_end/slot`；客户端自检断言与此表一致。
同时承载时区/时间工具：契约 §1「时间戳 ISO 8601 带时区；日期 YYYY-MM-DD，时区 Asia/Shanghai」。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - 极老解释器兜底
    ZoneInfo = None  # type: ignore

TZ_NAME = "Asia/Shanghai"
CALENDAR_ANCHOR_YEAR = 2026

PERIOD_COUNT = 8
PERIOD_INDEX_MIN = 1
PERIOD_INDEX_MAX = PERIOD_COUNT

#: 8 节课（契约 §4.4 冻结常量；唯一定义处）。
PERIODS: Tuple[dict, ...] = (
    {"index": 1, "start": "08:00", "end": "08:45"},
    {"index": 2, "start": "08:50", "end": "09:35"},
    {"index": 3, "start": "09:55", "end": "10:40"},
    {"index": 4, "start": "10:45", "end": "11:30"},
    {"index": 5, "start": "13:30", "end": "14:15"},
    {"index": 6, "start": "14:20", "end": "15:05"},
    {"index": 7, "start": "15:11", "end": "16:00"},
    {"index": 8, "start": "16:05", "end": "16:50"},
)


# --------------------------------------------------------------------------- 时间
def _tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TZ_NAME)
        except Exception:  # pragma: no cover - 缺 tzdata 的 Windows 兜底
            pass
    from datetime import timedelta, timezone

    return timezone(timedelta(hours=8))


def today_str() -> str:
    """Asia/Shanghai 的 `YYYY-MM-DD`（契约 §1）。服务端是"今天"的唯一权威。"""
    return datetime.now(_tz()).strftime("%Y-%m-%d")


def now_iso() -> str:
    """ISO 8601 带时区（如 `2026-10-01T22:31:05+08:00`）。"""
    return datetime.now(_tz()).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- 节次
def period_start(index: int) -> str:
    if not PERIOD_INDEX_MIN <= index <= PERIOD_INDEX_MAX:
        return ""
    return str(PERIODS[index - 1]["start"])


def period_end(index: int) -> str:
    if not PERIOD_INDEX_MIN <= index <= PERIOD_INDEX_MAX:
        return ""
    return str(PERIODS[index - 1]["end"])


def period_of_time(time_text: str) -> Optional[int]:
    """`HH:MM` → 落在哪一节（按起始钟点匹配；匹配不到返回 None）。"""
    text = (time_text or "").strip()
    if len(text) != 5 or text[2] != ":" or not text.replace(":", "").isdigit():
        return None
    for item in PERIODS:
        if str(item["start"]) <= text <= str(item["end"]):
            return int(item["index"])
    return None


# --------------------------------------------------------------------------- 日历
def weekday_from_date(year: int, month: int, day: int) -> int:
    """日期 → 星期（1=周一 … 7=周日）；非法日期返回 -1。"""
    try:
        return date(int(year), int(month), int(day)).weekday() + 1
    except (TypeError, ValueError):
        return -1


def clamp_day(year: int, month: int, day: int) -> int:
    """日号夹到当月合法范围；非法月份返回 1。"""
    try:
        year_i, month_i = int(year), int(month)
        day_i = int(day)
    except (TypeError, ValueError):
        return 1
    if month_i < 1 or month_i > 12:
        return 1
    if month_i == 12:
        total = 31
    else:
        total = (date(year_i, month_i + 1, 1) - date(year_i, month_i, 1)).days
    return max(1, min(day_i, total))


def slot_id(year: int, month: int, day: int, period: int) -> str:
    """格子唯一 ID `YYYY-MM-DD#P`（仅内存索引/界面定位，非主键）。"""
    return f"{int(year):04d}-{int(month):02d}-{clamp_day(year, month, day):02d}#{int(period)}"
