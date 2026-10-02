# -*- coding: utf-8 -*-
"""教师端扩展样式表。

纪律（方案 §9）：
- desktop_common/theme.py 的 build_qss() 是基础样式，**不改它**；
- 教师端特有控件的样式集中在本文件，主入口把两段 QSS 拼接后一次性 setStyleSheet；
- 页面只写 objectName，不出现内联 setStyleSheet；改视觉只改本文件。
"""
from __future__ import annotations

from desktop_common import theme as T

#: 教师端特有色（见山统一蓝灰体系）
BANNER_BG = "#EAF1F7"      # 提示横幅：浅蓝
SIDEBAR_BG = "#FFFFFF"
SELECTED_BG = "#EAF1F7"    # 选中行/选中导航：浅蓝（品牌选中）
HOVER_BG = "#F0F4F8"       # 悬停：浅蓝灰
DRAWER_BG = "#F7F9FC"      # 抽屉：极浅
CORAL_DEEP = "#FBE9D8"     # P2（柔和橙）
GREY = "#EDF1F5"           # P3（浅灰蓝）
WARN = "#B85C55"           # 预警：克制红
WARN_TINT = "#F7E4E1"      # 预警浅底
DISMISSED_BG = "#F4F6F9"   # 已处理浅灰


def build_teacher_qss() -> str:
    """返回教师端扩展 QSS（拼在 theme.build_qss() 之后，同选择器后定义优先）。"""
    return f"""
/* ================= 侧边导航 ================= */
QFrame#Sidebar {{
    background-color: {SIDEBAR_BG};
    border: none; border-right: 1px solid {T.LINE};
}}
QLabel#AppName {{ font-size: 18px; font-weight: 600; color: {T.PRIMARY_INK}; }}
QLabel#AppSub  {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}
QLabel#ModeTag  {{
    font-size: 12px; color: {T.PRIMARY_INK}; background-color: {T.MIST};
    border-radius: 9px; padding: 2px 10px;
}}
QPushButton#NavButton {{
    text-align: left;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 11px 14px;
    font-size: {T.FONT_BODY}px;
    color: {T.INK};
}}
QPushButton#NavButton:hover {{ background-color: {HOVER_BG}; }}
QPushButton#NavButton:checked {{
    background-color: {SELECTED_BG};
    color: {T.PRIMARY_INK};
    font-weight: 600;
    border: 1px solid {T.MIST};
}}

/* ================= 页面骨架 ================= */
QWidget#PageRoot {{ background-color: {T.BG}; }}
QLabel#PageTitle {{ font-size: {T.FONT_TITLE}px; font-weight: 600; color: {T.INK}; }}
QLabel#PageSub   {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}
QLabel#SyncHint  {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}

QFrame#Banner {{
    background-color: {BANNER_BG};
    color: {T.INK};
    border: 1px solid #E5D8BE;
    border-radius: 10px;
}}
QLabel#BannerText {{ background: transparent; font-size: {T.FONT_SMALL}px; color: {T.INK}; }}

QFrame#Panel {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-radius: {T.RADIUS}px;
}}
QLabel#TableHead {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}

/* ================= 分诊台：学生行 ================= */
QFrame#StudentRow {{
    background-color: {T.CARD};
    border: none; border-bottom: 1px solid {T.LINE};
}}
QFrame#StudentRow:hover {{ background-color: {HOVER_BG}; }}
QFrame#StudentRow[selected="true"] {{ background-color: {SELECTED_BG}; }}

/* 优先级徽标（HTML 雏形 P1/P2/P3 配色，保持不变） */
QLabel#PrioBadge1 {{ font-size: 12px; color: {T.INK}; background-color: {T.CORAL};
                     border-radius: 10px; padding: 3px 14px; }}
QLabel#PrioBadge2 {{ font-size: 12px; color: {T.INK}; background-color: {CORAL_DEEP};
                     border-radius: 10px; padding: 3px 14px; }}
QLabel#PrioBadge3 {{ font-size: 12px; color: {T.INK}; background-color: {GREY};
                     border-radius: 10px; padding: 3px 14px; }}
/* 标记 chips */
QLabel#ChipMist  {{ font-size: 12px; color: {T.INK}; background-color: {T.MIST};
                    border-radius: 8px; padding: 2px 10px; }}
QLabel#ChipCoral {{ font-size: 12px; color: {T.INK}; background-color: {T.CORAL};
                    border-radius: 8px; padding: 2px 10px; }}
QLabel#ChipSprout {{ font-size: 12px; color: {T.INK}; background-color: {T.SPROUT};
                     border-radius: 8px; padding: 2px 10px; }}
QLabel#ChipWarn  {{ font-size: 12px; color: {T.INK}; background-color: {WARN_TINT};
                    border: 1px solid {WARN}; border-radius: 8px; padding: 2px 10px; }}

/* ================= 学生抽屉 ================= */
QPushButton#AccentButton {{
    background-color: {T.CORAL};
    color: {T.INK};
    border: 1px solid {T.CORAL};
    font-weight: 600;
}}
QPushButton#AccentButton:hover {{ background-color: {CORAL_DEEP}; border-color: {CORAL_DEEP}; }}
QPushButton#AccentButton:disabled {{ background-color: {GREY}; color: #FFFFFF;
                                      border-color: {GREY}; }}

QFrame#Drawer {{
    background-color: {DRAWER_BG};
    border: none; border-left: 1px solid {T.LINE};
}}
QScrollArea#DrawerScroll {{ background: transparent; border: none; }}
QWidget#DrawerContent {{ background: transparent; }}
QScrollArea#PageScroll {{ background: transparent; border: none; }}
QWidget#PageScrollContent {{ background: transparent; }}
QLabel#DrawerTitle {{ font-size: 19px; font-weight: 600; color: {T.INK}; }}
QLabel#DrawerHint  {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}
QLabel#SectionCaption {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}
QLabel#MaskedText {{ font-size: {T.FONT_SMALL}px; color: {T.INK_SOFT}; }}

QFrame#DrawerCard {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-radius: 12px;
}}
QFrame#AlertCard {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-left: 4px solid {T.CORAL};
    border-radius: 12px;
}}
/* 心情圆点（颜色靠 objectName 切换，不用内联样式） */
QLabel#MoodDotHappy, QLabel#MoodDotPlain, QLabel#MoodDotDown, QLabel#MoodDotNone {{
    min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
    border-radius: 6px;
}}
QLabel#MoodDotHappy {{ background-color: {T.SPROUT}; }}
QLabel#MoodDotPlain {{ background-color: {T.MIST}; }}
QLabel#MoodDotDown  {{ background-color: {T.CORAL}; }}
QLabel#MoodDotNone  {{ background-color: {GREY}; }}

/* ================= 预约时间轴 ================= */
QFrame#TimelineRail {{ background-color: {T.MIST}; border: none;
                       min-width: 3px; max-width: 3px; }}
QLabel#TimelineNode {{
    min-width: 13px; max-width: 13px; min-height: 13px; max-height: 13px;
    border-radius: 7px; background-color: {T.MIST};
}}
QLabel#TimelineNodeDone {{
    min-width: 13px; max-width: 13px; min-height: 13px; max-height: 13px;
    border-radius: 7px; background-color: {T.SPROUT};
}}
QLabel#TimelineNodeMuted {{
    min-width: 13px; max-width: 13px; min-height: 13px; max-height: 13px;
    border-radius: 7px; background-color: #C4CCD6;
}}
QFrame#ApptCard {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-top: 3px solid {T.MIST};
    border-radius: 12px;
}}
QFrame#ApptCardDone {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-top: 3px solid {T.SPROUT};
    border-radius: 12px;
}}
QFrame#ApptCardMuted {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-top: 3px solid #C4CCD6;
    border-radius: 12px;
}}
QFrame#PendingCard {{
    background-color: {T.CARD};
    border: 1px dashed {CORAL_DEEP};
    border-radius: 12px;
}}
QLabel#StatusPend {{ font-size: 12px; color: {T.INK}; background-color: {T.CORAL};
                     border-radius: 9px; padding: 2px 10px; }}
QLabel#StatusSched {{ font-size: 12px; color: {T.PRIMARY_INK}; background-color: {T.MIST};
                      border-radius: 9px; padding: 2px 10px; }}
QLabel#StatusDone {{ font-size: 12px; color: {T.INK}; background-color: {T.SPROUT};
                     border-radius: 9px; padding: 2px 10px; }}
QLabel#StatusCancel {{ font-size: 12px; color: {T.INK_SOFT}; background-color: {DISMISSED_BG};
                       border: 1px solid {T.LINE}; border-radius: 9px; padding: 2px 10px; }}
QLabel#StatusNoShow {{ font-size: 12px; color: {WARN}; background-color: {WARN_TINT};
                       border: 1px solid {WARN}; border-radius: 9px; padding: 2px 10px; }}

/* ================= 预警记录 ================= */
QFrame#WarnActiveCard {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-left: 4px solid {WARN};
    border-radius: 12px;
}}
QFrame#WarnDismissedCard {{
    background-color: {DISMISSED_BG};
    border: 1px solid {T.LINE};
    border-radius: 12px;
}}
QLabel#WarnTitle {{ font-size: {T.FONT_HEADING}px; font-weight: 600; color: {T.INK}; }}
QLabel#WarnTitleOff {{ font-size: {T.FONT_HEADING}px; font-weight: 600; color: {T.INK_SOFT}; }}

/* ================= 回复库 ================= */
QFrame#ReplyCard {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-radius: 12px;
}}
QFrame#ReplyCard[enabled="false"] {{ background-color: {DISMISSED_BG}; }}

/* ================= 表格（导出预览） ================= */
QTableWidget {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    border-radius: {T.RADIUS}px;
    gridline-color: {T.LINE};
    selection-background-color: {SELECTED_BG};
    selection-color: {T.PRIMARY_INK};
    outline: none;
}}
QTableWidget::item {{ padding: 6px 8px; border: none; }}
QHeaderView::section {{
    background-color: #F5F1EA;
    color: {T.INK_SOFT};
    border: none;
    border-right: 1px solid {T.LINE};
    border-bottom: 1px solid {T.LINE};
    padding: 8px;
    font-size: {T.FONT_SMALL}px;
}}
QTableCornerButton::section {{ background-color: #F5F1EA; border: none; }}

/* ================= 下拉 / 日期时间输入 ================= */
QComboBox, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {T.CARD};
    color: {T.INK};
    border: 1px solid {T.LINE};
    border-radius: {T.RADIUS_SMALL}px;
    padding: 6px 10px;
    min-height: {T.MIN_TAP - 12}px;
}}
QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border: 2px solid {T.FOCUS_RING};
}}
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{
    border: none; width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {T.CARD};
    border: 1px solid {T.LINE};
    selection-background-color: {SELECTED_BG};
    selection-color: {T.PRIMARY_INK};
    outline: none;
}}
QCalendarWidget QWidget {{ alternate-background-color: {T.BG}; }}
QCalendarWidget QToolButton {{
    color: {T.PRIMARY_INK}; background: transparent; border: none; font-weight: 600;
}}
QCalendarWidget QMenu {{ background: {T.CARD}; color: {T.INK}; }}
QCalendarWidget QAbstractItemView {{
    background: {T.CARD}; color: {T.INK};
    selection-background-color: {T.MIST}; selection-color: {T.PRIMARY_INK};
}}

/* ================= 工作预览 ================= */
QLabel#SectionTitle {{ font-size: 18px; font-weight: 600; color: {T.INK}; }}QLabel#StatValue {{ font-size: 26px; font-weight: 600; color: {T.INK}; }}
QLabel#StatTitle {{ font-size: 13px; color: {T.INK_SOFT}; }}
QLabel#StatIcon {{ border-radius: 18px; }}
QLabel#StatIcon[tone="help"] {{ background-color: {T.MIST}; }}
QLabel#StatIcon[tone="appointment"] {{ background-color: {CORAL_DEEP}; }}
QLabel#StatIcon[tone="warning"] {{ background-color: {WARN_TINT}; }}
QLabel#StatIcon[tone="done"] {{ background-color: {T.SPROUT}; }}
QFrame#OverviewTodoRow {{
    background: transparent; border: none; border-bottom: 1px solid {T.LINE};
}}
QLabel#OverviewTodoDesc {{ font-size: 13px; color: {T.INK_SOFT}; }}
QLabel#OverviewActivityText {{ font-size: 13px; color: {T.INK}; }}
QLabel#OverviewActivityTime {{ font-size: 12px; color: {T.INK_SOFT}; }}

/* ================= 教师日历网格 ================= */
QPushButton#CalCell {{
    background-color: {T.CARD};
    color: {T.INK_SOFT};
    border: 1px solid {T.LINE};
    border-radius: 8px;
    padding: 4px 6px;
    min-height: 38px;
    font-size: {T.FONT_SMALL}px;
}}
QPushButton#CalCell[state="appt"] {{
    background-color: {T.MIST};
    color: {T.PRIMARY_INK};
    border: 1px solid {T.MIST};
    font-weight: 600;
}}
QPushButton#CalCell[state="block"] {{
    background-color: {WARN_TINT};
    color: {WARN};
    border: 1px solid {WARN};
}}
QPushButton#CalCell[state="free"]:hover {{ border-color: {T.MIST}; }}
"""
