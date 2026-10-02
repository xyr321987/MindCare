"""预约时间网格的**单一事实源**（学生端与教师端共用）。

背景
----
预约时间的界面形态是**一张课表**：横轴是星期几（周一 ~ 周日），纵轴是第 1 ~ 第 8 节。
双端必须看到**同一张表**（否则"学生选的时间同步到教师端"就是一句空话），
所以节次定义、星期口径、日历换算全部收敛在本模块，**任何一端都不许自己算一遍**。

节次定义（需求给定时段，08:00 起、17:00 前结束）::

    第1节 08:00~08:45   第2节 08:50~09:35   第3节 09:55~10:40   第4节 10:45~11:30
    第5节 13:30~14:15   第6节 14:20~15:05   第7节 15:11~16:00   第8节 16:05~16:50

⚠️ **第 8 节的笔误修正**：需求原文写的是「第8节 16:05~16:00」（结束早于开始）。
按前 7 节的时长口径（45 / 50 / 55 分钟不等，第 7 节 49 分钟）取最接近的 45 分钟，
修正为 **16:05~16:50**，仍在"上午 8 点到下午 5 点"的范围内。
`PERIODS[7].end` 是唯一写这个数的地方，改需求时只改这里。

星期口径
--------
* `weekday` 存 **1 ~ 7**（1=周一 … 7=周日），与 `datetime.weekday()` 的 `0 ~ 6` 相差 1；
* 换算只在 `weekday_from_date()` / `date_from_week()` 两个函数里做，其它地方一律用 1~7。

文案纪律
--------
本模块**不产生中文界面文案**：节次名与星期名只给出**文案表键**（`COPY[键]` 由界面取），
时间段是数字格式（`HH:MM`），两者都不是中文字面量。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PERIOD_COUNT", "PERIODS", "PERIOD_LABEL_KEYS", "PERIOD_INDEX_MIN",
    "PERIOD_INDEX_MAX", "WEEKDAY_COUNT", "WEEKDAY_KEYS",
    "period_label_key", "period_time_text", "period_start", "period_end",
    "period_of_time", "weekday_from_date", "days_in_month", "clamp_day",
    "week_start_date", "week_dates", "month_weeks", "week_index_in_month",
    "slot_id", "parse_slot_id", "date_text", "weekday_text", "is_past_slot",
    "CALENDAR_ANCHOR_YEAR",
]

#: 需求指定的基准年份（2026 年的真实日历：星期几按 2026 年编排）
CALENDAR_ANCHOR_YEAR = 2026

PERIOD_COUNT = 8
PERIOD_INDEX_MIN = 1
PERIOD_INDEX_MAX = PERIOD_COUNT

#: 8 节课。**唯一**定义处；`index` 是 1~8（与数据库 `period` 字段同值）。
PERIODS: Tuple[Dict[str, object], ...] = (
    {"index": 1, "start": "08:00", "end": "08:45", "label_key": "c.schedule.period.1"},
    {"index": 2, "start": "08:50", "end": "09:35", "label_key": "c.schedule.period.2"},
    {"index": 3, "start": "09:55", "end": "10:40", "label_key": "c.schedule.period.3"},
    {"index": 4, "start": "10:45", "end": "11:30", "label_key": "c.schedule.period.4"},
    {"index": 5, "start": "13:30", "end": "14:15", "label_key": "c.schedule.period.5"},
    {"index": 6, "start": "14:20", "end": "15:05", "label_key": "c.schedule.period.6"},
    {"index": 7, "start": "15:11", "end": "16:00", "label_key": "c.schedule.period.7"},
    # 原文「16:05~16:00」疑为笔误（结束早于开始），按前 7 节时长口径修正为 16:50
    {"index": 8, "start": "16:05", "end": "16:50", "label_key": "c.schedule.period.8"},
)

#: `period` → 该节的文案表键（界面取 `COPY[key]`）
PERIOD_LABEL_KEYS: Tuple[str, ...] = tuple(
    str(item["label_key"]) for item in PERIODS
)

WEEKDAY_COUNT = 7

#: 星期 → 文案表键（1=周一 … 7=周日）
WEEKDAY_KEYS: Tuple[str, ...] = (
    "c.schedule.weekday.1", "c.schedule.weekday.2", "c.schedule.weekday.3",
    "c.schedule.weekday.4", "c.schedule.weekday.5", "c.schedule.weekday.6",
    "c.schedule.weekday.7",
)


# --------------------------------------------------------------------------- 节次


def _period(index: int) -> Optional[Dict[str, object]]:
    if not isinstance(index, int) or index < PERIOD_INDEX_MIN or index > PERIOD_INDEX_MAX:
        return None
    return PERIODS[index - 1]


def period_label_key(index: int) -> str:
    """第 N 节的文案表键（越界时返回空串，界面会显示成「缺文案」而不是崩）。"""
    item = _period(index)
    return str(item["label_key"]) if item else ""


def period_start(index: int) -> str:
    """第 N 节的起始 `HH:MM`（越界返回空串）。"""
    item = _period(index)
    return str(item["start"]) if item else ""


def period_end(index: int) -> str:
    """第 N 节的结束 `HH:MM`（越界返回空串）。"""
    item = _period(index)
    return str(item["end"]) if item else ""


def period_time_text(index: int) -> str:
    """第 N 节的时间段文本 `HH:MM-HH:MM`（**数字格式**，不是中文文案）。"""
    item = _period(index)
    if not item:
        return ""
    return f"{item['start']}-{item['end']}"


def period_of_time(time_text: str) -> Optional[int]:
    """`HH:MM` → 落在哪一节（按起始钟点匹配；匹配不到返回 `None`）。

    只用于**兼容旧数据**：v1.0 的预约记录只有 `time`（09:00–17:00 整点），
    没有 `period`。本函数按"起始钟点落在哪一节的时间区间内"回推，
    回推不出来就返回 `None`（宁可显示成未知，也不猜一个错的节次）。
    """
    text = (time_text or "").strip()
    if len(text) != 5 or text[2] != ":" or not text.replace(":", "").isdigit():
        return None
    for item in PERIODS:
        if str(item["start"]) <= text <= str(item["end"]):
            return int(item["index"])
    return None


# --------------------------------------------------------------------------- 日历


def weekday_from_date(year: int, month: int, day: int) -> int:
    """日期 → 星期（**1=周一 … 7=周日**）。

    ⚠️ `datetime.weekday()` 是 0=周一；全应用只有这一处做 +1 换算。
    非法日期（如 2 月 30 日）返回 `-1`（**不抛异常**：日历控件可能短暂构造出这种值）。
    """
    try:
        return date(int(year), int(month), int(day)).weekday() + 1
    except (TypeError, ValueError):
        return -1


def days_in_month(year: int, month: int) -> int:
    """该月天数（非法月份返回 0）。"""
    try:
        year, month = int(year), int(month)
    except (TypeError, ValueError):
        return 0
    if month < 1 or month > 12:
        return 0
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def clamp_day(year: int, month: int, day: int) -> int:
    """把日号夹到该月合法范围内（1 ~ 当月天数）；非法月份返回 1。"""
    total = days_in_month(year, month)
    if total <= 0:
        return 1
    try:
        value = int(day)
    except (TypeError, ValueError):
        return 1
    return max(1, min(value, total))


def week_start_date(year: int, month: int, day: int) -> date:
    """该日期所在**周**的周一（`date` 对象）。"""
    try:
        current = date(int(year), int(month), clamp_day(year, month, day))
    except (TypeError, ValueError):
        current = date(CALENDAR_ANCHOR_YEAR, 1, 1)
    return current - timedelta(days=current.weekday())


def week_dates(year: int, month: int, day: int) -> List[Tuple[int, int, int]]:
    """该日期所在周的 7 天（周一起），返回 `[(y, m, d), ...]` 共 7 项。

    跨月/跨年都由 `date` 的算术保证正确（例：2026-10-01 那一周含 9 月的几天）。
    """
    monday = week_start_date(year, month, day)
    return [(d.year, d.month, d.day) for d in
            (monday + timedelta(days=offset) for offset in range(WEEKDAY_COUNT))]


def month_weeks(year: int, month: int) -> List[List[Tuple[int, int, int]]]:
    """该月覆盖的所有周（每周 7 天，周一起；首/末周会带上邻月的几天）。"""
    total = days_in_month(year, month)
    if total <= 0:
        return []
    weeks: List[List[Tuple[int, int, int]]] = []
    seen: set = set()
    for day in range(1, total + 1):
        week = week_dates(year, month, day)
        key = week[0]
        if key in seen:
            continue
        seen.add(key)
        weeks.append(week)
    return weeks


def week_index_in_month(year: int, month: int, day: int) -> int:
    """该日期是该月的第几周（0 起；用于月视图定位，当前不需要则可忽略）。"""
    for index, week in enumerate(month_weeks(year, month)):
        if (int(year), int(month), clamp_day(year, month, day)) in week:
            return index
    return 0


# --------------------------------------------------------------------------- 格子


def slot_id(year: int, month: int, day: int, period: int) -> str:
    """格子唯一 ID：`YYYY-MM-DD#P`（如 `2026-10-05#3`）。

    ⚠️ 只用于**内存索引与界面定位**，不是数据库主键（数据库主键仍是 `apt_` / `blk_`）。
    """
    return f"{int(year):04d}-{int(month):02d}-{clamp_day(year, month, day):02d}#{int(period)}"


def parse_slot_id(value: str) -> Optional[Tuple[int, int, int, int]]:
    """`slot_id()` 的逆运算；格式不符返回 `None`（不抛异常）。"""
    text = (value or "").strip()
    if "#" not in text:
        return None
    head, _, tail = text.partition("#")
    parts = head.split("-")
    if len(parts) != 3 or not tail.isdigit():
        return None
    try:
        year, month, day = (int(part) for part in parts)
        period = int(tail)
    except ValueError:
        return None
    if weekday_from_date(year, month, day) < 0:
        return None
    return year, month, day, period


def date_text(year: int, month: int, day: int) -> str:
    """日期 → `M/D` 形态（**数字格式**，列头显示用）。"""
    return f"{int(month)}/{int(day):02d}"


def weekday_text(year: int, month: int, day: int) -> str:
    """日期 → 星期几的**数字** `1~7`（界面拿它去取 `WEEKDAY_KEYS`）。"""
    return str(weekday_from_date(year, month, day))


def is_past_slot(year: int, month: int, day: int, period: int,
                 *, now: Optional[date] = None) -> bool:
    """该格子是否已经过去（**按当天日期**判断，不精确到分钟）。

    只挡"日期已过"：同一天里已上过的课不拦 —— 学生当天临时想约当天的时段
    是合理诉求，界面把它标灰更好，但**禁选**会误伤。
    """
    try:
        target = date(int(year), int(month), clamp_day(year, month, day))
    except (TypeError, ValueError):
        return False
    today = now or date.today()
    return target < today
