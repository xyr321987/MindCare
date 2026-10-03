# -*- coding: utf-8 -*-
"""数据分析页的**数据层**（当前为确定性模拟数据）。

结构约定：页面只认 `load_analytics(range_key)` 返回的这份 dict；所有数字字段
都是纯数据（不含颜色 / 文案），页面层再用 `chartkit` 的配色组装成图表。

**后续接入真实数据**：把 `load_analytics` 内部换成调用适配器（例如在
`core/adapters` 新增 `analytics_adapter`，返回同结构 dict）即可，页面与图表
零改动。本模块刻意不 import 任何网络层，保证可离线渲染 / 自检。
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Dict, List, Tuple

#: 时间范围键 -> (显示文案, 点数, 粒度)
_RANGES: Dict[str, Tuple[str, int, str]] = {
    "7d": ("最近 7 天", 7, "day"),
    "30d": ("最近 30 天", 30, "day"),
    "90d": ("最近 90 天", 90, "day"),
    "term": ("本学期", 18, "week"),
}

#: 固定年级顺序（覆盖初中 + 高中）
GRADES = ("初一", "初二", "初三", "高一", "高二", "高三")

#: 预警来源名称（环形图）
WARNING_SOURCES = ("连续低落", "病史关注", "求助待处理")

#: 学期周数（本学期按 18 周演示）
_TERM_WEEKS = 18


def range_options() -> List[Tuple[str, str]]:
    """时间筛选选项：[(key, 文案), ...]，顺序固定。"""
    return [(key, label) for key, (label, _n, _unit) in _RANGES.items()]


def _labels(n: int, unit: str, today: date) -> List[str]:
    labels: List[str] = []
    for i in range(n):
        if unit == "day":
            d = today - timedelta(days=n - 1 - i)
            labels.append(f"{d.month}/{d.day}")
        else:
            d = today - timedelta(weeks=n - 1 - i)
            labels.append(f"{d.month}/{d.day}")
    return labels


def _display_labels(labels: List[str], max_ticks: int = 7) -> List[str]:
    """横轴抽稀：点数多时只给少数位置标文字，其余留空，避免拥挤。"""
    n = len(labels)
    if n <= max_ticks:
        return list(labels)
    step = max(1, math.ceil(n / max_ticks))
    return [label if i % step == 0 else "" for i, label in enumerate(labels)]


def _smooth(n: int, base: float, amp: float, seed: int, *, wave: float = 0.5) -> List[int]:
    rng = random.Random(seed)
    phase = rng.uniform(0.0, 6.2832)
    out: List[int] = []
    for i in range(n):
        drift = math.sin(i * wave + phase) * amp
        noise = rng.uniform(-amp * 0.5, amp * 0.5)
        out.append(max(0, int(round(base + drift + noise))))
    return out


def load_analytics(range_key: str) -> Dict:
    """返回指定时间范围的分析数据（纯数据，无颜色/无文案拼装）。

    未来接真实接口时，保持返回结构不变即可。
    """
    key = range_key if range_key in _RANGES else "30d"
    label, n, unit = _RANGES[key]
    today = date.today()
    seed = {"7d": 11, "30d": 31, "90d": 91, "term": 42}[key]

    labels = _labels(n, unit, today)
    display_labels = _display_labels(labels)

    # 情绪三态（每日提交人次）
    positive = _smooth(n, 120, 26, seed, wave=0.5)
    stable = _smooth(n, 72, 16, seed + 100, wave=0.45)
    low = _smooth(n, 32, 12, seed + 200, wave=0.6)

    # 预警三等级（每日新增，P3>P2>P1 的常规金字塔）
    p1 = _smooth(n, 2, 1, seed + 300, wave=0.5)
    p2 = _smooth(n, 4, 2, seed + 400, wave=0.5)
    p3 = _smooth(n, 6, 3, seed + 500, wave=0.5)

    mood_total = sum(positive) + sum(stable) + sum(low)
    positive_ratio = (sum(positive) / mood_total) if mood_total else 0.0
    warnings = sum(p1) + sum(p2) + sum(p3)

    # 年级情绪对比（按年级拆三态，生成时稍作区分）
    grade_positive = _smooth(len(GRADES), 90, 14, seed + 600, wave=1.2)
    grade_stable = _smooth(len(GRADES), 55, 10, seed + 700, wave=1.1)
    grade_low = _smooth(len(GRADES), 22, 8, seed + 800, wave=1.0)

    # 预警来源（按比例拆总预警）
    src_continue = max(1, int(round(warnings * 0.46)))
    src_history = max(1, int(round(warnings * 0.34)))
    src_pending = max(1, warnings - src_continue - src_history)

    # 心理支持工作
    completion_rate = round(0.72 + (seed % 10) * 0.008, 2)
    completion_rate = max(0.6, min(0.92, completion_rate))
    pending_tasks = 5 + (seed % 7)
    avg_response_min = 28 + (seed % 16)

    return {
        "range_key": key,
        "range_label": label,
        "metrics": {
            "students": 440 + (seed % 40),
            "positive_ratio": round(positive_ratio, 3),
            "warnings": warnings,
            "pending_help": pending_tasks,
            "completion_rate": completion_rate,
        },
        "mood_trend": {
            "labels": labels,
            "display_labels": display_labels,
            "positive": positive,
            "stable": stable,
            "low": low,
        },
        "warning_trend": {
            "labels": labels,
            "display_labels": display_labels,
            "p1": p1,
            "p2": p2,
            "p3": p3,
        },
        "mood_distribution": {
            "positive": sum(positive),
            "stable": sum(stable),
            "low": sum(low),
        },
        "warning_source": {
            "连续低落": src_continue,
            "病史关注": src_history,
            "求助待处理": src_pending,
        },
        "grade_mood": {
            "labels": list(GRADES),
            "positive": grade_positive,
            "stable": grade_stable,
            "low": grade_low,
        },
        "support": {
            "completion_rate": completion_rate,
            "pending_tasks": pending_tasks,
            "avg_response_min": avg_response_min,
        },
    }
