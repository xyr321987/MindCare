# -*- coding: utf-8 -*-
"""枚举映射与展示口径（与 教师端3.html 的 COLOR/PRIORITY/MOOD/CAUSE 完全一致）。

⚠️ 本模块是教师端唯一允许出现"枚举→中文/配色"映射的地方；页面只消费这里的常量。
   调整措辞或配色只改本文件 + ui/teacher_qss.py，不动页面逻辑。

隐私措辞纪律（方案 §6.2/§10.6）：
- 预警一律用"需要关心/多一点关注"，禁止"问题学生/有问题"；
- masked 占位话术固定，不做任何推断性文字。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------------ 配色（与 HTML 雏形对齐）
# 雾蓝/珊瑚/嫩芽绿取自 desktop_common.theme；P2 深珊瑚与灰为 HTML 雏形既有值
COLOR_MIST = "#A8C5D6"        # 雾蓝：平淡 / 病史 chip
COLOR_CORAL = "#F2B8A0"       # 珊瑚：P1 / 低落
COLOR_CORAL_DEEP = "#E39B7F"  # 深珊瑚：P2
COLOR_SPROUT = "#B7D7B9"      # 嫩芽绿：高兴 / 求助待处理
COLOR_GREY = "#C9C4BD"        # 灰：P3
COLOR_WARN = "#B8A9C9"        # 紫灰：新预警「连续低落未求助」标记（独立于 P1/P2/P3）

#: priority → (中文文案, 徽标颜色)
PRIORITY = {
    1: ("需要优先关心", COLOR_CORAL),
    2: ("待响应求助", COLOR_CORAL_DEEP),
    3: ("常规", COLOR_GREY),
}

#: mood → (中文文案, 颜色)
MOOD = {
    "happy": ("还不错", COLOR_SPROUT),
    "plain": ("平平淡淡", COLOR_MIST),
    "down": ("有点低落", COLOR_CORAL),
}
MOOD_NONE_TEXT = "今天还没填写"

#: cause_category → 中文
CAUSE = {
    "study": "学业",
    "relationship": "人际关系",
    "family": "家庭",
}

#: 预警规则 → 中文（治愈话术，不贴标签）
ALERT_RULE = {
    "history_plus_recent_down": "有心理疾病史，且近期多次低落",
    "silent_down_streak": "连续多次低落且未求助，可以主动关心一下",
}

#: masked 固定占位（任何页面引用同一句话术）
MASKED_TEXT = "该生选择暂不分享，可通过线下方式关心"

#: 结束场景（回复库的标签集合，对应学生端 result_scene）
RESULT_SCENES = {
    "happy_end": "高兴时的回应",
    "plain_tips": "平淡时的小贴士",
    "help_sent": "求助后的回应",
    "self_care": "低落不求助时的自助建议",
}

_TZ = timezone(timedelta(hours=8))


# ------------------------------------------------------------------ 时间口径（与 HTML 一致）
def _day_basis(server_date: str = "") -> datetime:
    """所有"今天/距今"以服务端日期为准（HTML 雏形冲突 C-17 的处理）；缺省回退本机。"""
    if server_date:
        try:
            return datetime.strptime(server_date, "%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now(_TZ)


def relative_day_text(ts: str | None, server_date: str = "") -> str:
    """只比日期部分（避免时区偏移）：今天 / 昨天 / N 天前 / 暂无记录。"""
    if not ts:
        return "暂无记录"
    try:
        day = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
    except ValueError:
        return "暂无记录"
    delta = (_day_basis(server_date).date() - day.date()).days
    if delta <= 0:
        return "今天"
    if delta == 1:
        return "昨天"
    return f"{delta} 天前"


def short_time(ts: str | None) -> str:
    """ISO ts → HH:MM（用于卡片头）。"""
    return str(ts)[11:16] if ts else ""


def today_str() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")
