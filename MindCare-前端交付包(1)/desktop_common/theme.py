"""共享主题：调色板常量 + 尺寸常量 + `build_qss()`。

依据 `docs/UI约定.md` §2（冻结 v1.0）：

* 调色板：米白底 / 白卡片 / 深灰正文 / 雾蓝主色 / 柔珊瑚辅助色 / 嫩芽绿
* 硬要求 ① 正文对比度 ≥ 4.5:1，**雾蓝 `#A8C5D6` 只做底、不做正文字色**
* 硬要求 ② `build_qss()` 返回一份 QSS 字符串，**两个应用都调它**，不得各写一份
* 硬要求 ③ 禁止弹跳/抖动/闪烁/循环动画；动画时长 ≤ 240ms（见 `ANIM_MS`）
* 硬要求 ④ 可点控件 `setFocusPolicy(Qt.StrongFocus)` + 可见 focus 样式

对比度实测（WCAG 2.1 相对亮度公式；**由自检脚本用 `contrast_ratio()` 现场复算**）::

    INK        #3A3A38 on BG      #FAF7F2 -> 10.67:1
    INK        #3A3A38 on CARD    #FFFFFF -> 11.40:1
    INK_SOFT   #6E6A63 on BG      #FAF7F2 ->  5.03:1
    INK_SOFT   #6E6A63 on CARD    #FFFFFF ->  5.38:1
    PRIMARY_INK #2F4A57 on MIST   #A8C5D6 ->  5.19:1
    INK        #3A3A38 on MIST    #A8C5D6 ->  6.31:1
    (#FFFFFF on MIST #A8C5D6 -> 1.81:1 —— 故白字**不得**压在雾蓝上)
"""
from __future__ import annotations

from typing import Dict, Tuple

__all__ = [
    "BG", "CARD", "FIELD", "INK", "INK_SOFT", "INK_FADE", "LINE", "MIST",
    "CORAL", "SPROUT", "PRIMARY_INK", "FOCUS_RING", "DANGER_SOFT",
    "DUSK_TOP", "DUSK_BOTTOM",
    "SLOT_BLOCKED_BG", "SLOT_BLOCKED_LINE", "SLOT_BLOCKED_INK",
    "SLOT_TAKEN_BG", "SLOT_TAKEN_LINE", "SLOT_MINE_BG", "SLOT_MINE_LINE",
    "SLOT_PAST_BG", "NAV_BG", "NAV_INACTIVE", "NAV_ACTIVE_BG", "NAV_ACTIVE_TEXT",
    "NAV_HOVER_BG",
    "MOOD_HAPPY_BG", "MOOD_HAPPY_LINE", "MOOD_PLAIN_BG", "MOOD_PLAIN_LINE",
    "MOOD_DOWN_BG", "MOOD_DOWN_LINE", "MOOD_TINT",
    "RADIUS", "RADIUS_SMALL", "CARD_PADDING", "FONT_BODY", "FONT_TITLE",
    "FONT_HEADING", "FONT_SMALL", "FONT_MUTE", "LINE_HEIGHT", "MIN_TAP",
    "ANIM_MS", "PALETTE", "SIZES",
    "FONT_CANDIDATES", "FONT_SEARCH_DIRS",
    "contrast_ratio", "relative_luminance", "build_qss", "apply_theme",
    "install_fonts",
]

# --------------------------------------------------------------------------- 调色板

BG = "#FAF7F2"            # 窗口底色（暖米白）
CARD = "#FFFDF9"          # 卡片面（暖白，**替代纯白 #FFFFFF**）
FIELD = "#F3EDE2"         # 输入/可编辑区底色（暖沙：用背景色差区分体系，替代硬边框）
INK = "#3A3A38"           # **正文文字**（不用主色写正文）
INK_SOFT = "#6E6A63"      # 次要文字
INK_FADE = "#9A948A"      # 底层信息（危机热线等）的弱化字色
LINE = "#EBE3D7"          # 分隔线（暖砂，进一步弱化“表格感”）
MIST = "#A8C5D6"          # 主色（雾蓝）：选中态填充、进度条、主按钮**底色**
CORAL = "#F2B8A0"         # 辅助色（柔珊瑚）：P1 关注标记的**底色**，不是文字色
SPROUT = "#B7D7B9"        # 平静 / 正向
PRIMARY_INK = "#2F4A57"   # 雾蓝上的文字色（白字压在雾蓝上对比度不足）
FOCUS_RING = "#7FA6BA"    # 焦点环（雾蓝加深，用于键盘可达样式）
DANGER_SOFT = "#C9836B"   # 柔化的提示色（**不是刺眼红**，只用于错误文本，仍是深色字）

#: 树洞「暮蓝」环境光渐变（自顶向下柔和暮色：传递夜间温暖的安全感）
DUSK_TOP = "#E3ECF1"
DUSK_BOTTOM = "#C2D4DF"

# --- 预约时间课表的格子配色（学生端 / 教师端共用；对比度由自检现场复算）--------
# ⚠️ 「不可预约」必须一眼看出来（需求指定**红框**），但仍受硬要求 ① 约束：
#    红只做**边框 + 底**，格子里的字一律深色，不得用刺眼的饱和红写字。
SLOT_BLOCKED_BG = "#F6E1DC"    # 不可预约：柔和珊瑚底
SLOT_BLOCKED_LINE = "#B03A24"  # 不可预约：**红框**
SLOT_BLOCKED_INK = "#7A2E1C"   # 框内深色字（on 底 7.48:1）
SLOT_TAKEN_BG = "#E7DCCB"      # 已有同学约了：暖砂底（字用 INK -> 8.35:1）
SLOT_TAKEN_LINE = "#D3C6B2"
SLOT_MINE_BG = "#DCEBE0"       # 我约的：嫩芽绿底（字用 INK -> 9.21:1）
SLOT_MINE_LINE = "#6E9A76"
SLOT_PAST_BG = "#F2EEE6"       # 已经过去（禁用态，与 `QPushButton:disabled` 同款）

# --- 学生端左侧导航（深色侧边栏，主题上独立于主调色板：内容区仍保持暖米色）--------
NAV_BG = "#1A1A1A"          # 侧边导航底色（深灰黑）
NAV_INACTIVE = "#A0A0A0"    # 未选中项文字/图标（浅灰）
NAV_ACTIVE_BG = "#3A3A3A"   # 选中项背景（中灰圆角）
NAV_ACTIVE_TEXT = "#FFFFFF" # 选中项文字（白）
NAV_HOVER_BG = "#2A2A2A"    # 悬停背景

# --- 情绪卡片（Q1）的色彩光晕 + 色温层 --------------------------------------
# 三种情绪各自有独立的「光晕」底色 / 边界色（不是正文文字色，对比度仍由自检复算）。
MOOD_HAPPY_BG = "#FBF0DC"    # 高兴：暖金光晕
MOOD_HAPPY_LINE = "#E4C98F"
MOOD_PLAIN_BG = "#EEF3F5"    # 平淡：雾蓝灰光晕
MOOD_PLAIN_LINE = "#CBD9E0"
MOOD_DOWN_BG = "#E7EEF2"     # 沮丧：冷调光晕
MOOD_DOWN_LINE = "#B9C9D4"
MOOD_TINT = "#3D5A6C"        # 色温层冷色（点「沮丧」时覆盖整屏的极浅冷调，靠 opacity 控制浓度）

#: 供别的模块（含教师端）枚举主题变量，避免各处硬编码色值
PALETTE: Dict[str, str] = {
    "BG": BG, "CARD": CARD, "FIELD": FIELD, "INK": INK, "INK_SOFT": INK_SOFT,
    "INK_FADE": INK_FADE, "LINE": LINE, "MIST": MIST, "CORAL": CORAL,
    "SPROUT": SPROUT, "PRIMARY_INK": PRIMARY_INK, "FOCUS_RING": FOCUS_RING,
    "DANGER_SOFT": DANGER_SOFT, "DUSK_TOP": DUSK_TOP, "DUSK_BOTTOM": DUSK_BOTTOM,
    "SLOT_BLOCKED_BG": SLOT_BLOCKED_BG, "SLOT_BLOCKED_LINE": SLOT_BLOCKED_LINE,
    "SLOT_BLOCKED_INK": SLOT_BLOCKED_INK, "SLOT_TAKEN_BG": SLOT_TAKEN_BG,
    "SLOT_TAKEN_LINE": SLOT_TAKEN_LINE, "SLOT_MINE_BG": SLOT_MINE_BG,
    "SLOT_MINE_LINE": SLOT_MINE_LINE, "SLOT_PAST_BG": SLOT_PAST_BG,
    "NAV_BG": NAV_BG, "NAV_INACTIVE": NAV_INACTIVE, "NAV_ACTIVE_BG": NAV_ACTIVE_BG,
    "NAV_ACTIVE_TEXT": NAV_ACTIVE_TEXT, "NAV_HOVER_BG": NAV_HOVER_BG,
    "MOOD_HAPPY_BG": MOOD_HAPPY_BG, "MOOD_HAPPY_LINE": MOOD_HAPPY_LINE,
    "MOOD_PLAIN_BG": MOOD_PLAIN_BG, "MOOD_PLAIN_LINE": MOOD_PLAIN_LINE,
    "MOOD_DOWN_BG": MOOD_DOWN_BG, "MOOD_DOWN_LINE": MOOD_DOWN_LINE,
    "MOOD_TINT": MOOD_TINT,
}

# --------------------------------------------------------------------------- 尺寸

RADIUS = 20          # 大圆角（方圆角），≥ 12px（UI约定 §2 尺寸）
RADIUS_SMALL = 16
CARD_PADDING = 26    # 卡片内边距 ≥ 20px（加大留白，提升呼吸感）
FONT_BODY = 15       # 正文 15–16px
FONT_TITLE = 21
FONT_HEADING = 17
FONT_SMALL = 14      # 提示语从 13 上调（缓解“字号偏小”）
FONT_MUTE = 12       # 危机热线等底层信息的弱化字号
LINE_HEIGHT = 1.8    # 行高 1.6 → 1.8（Qt QSS 无 line-height，由 spacing/padding 体现）
MIN_TAP = 34         # 可点区域最小高度（桌面 ≥ 32×32）
ANIM_MS = 180        # 唯一允许的动画（淡入/淡出）时长，≤ 240ms

SIZES: Dict[str, object] = {
    "RADIUS": RADIUS, "RADIUS_SMALL": RADIUS_SMALL, "CARD_PADDING": CARD_PADDING,
    "FONT_BODY": FONT_BODY, "FONT_TITLE": FONT_TITLE, "FONT_HEADING": FONT_HEADING,
    "FONT_SMALL": FONT_SMALL, "FONT_MUTE": FONT_MUTE, "LINE_HEIGHT": LINE_HEIGHT,
    "MIN_TAP": MIN_TAP, "ANIM_MS": ANIM_MS,
}

#: 正则：QSS 里禁止出现动画/闪烁类属性（自检会断言）。
#: 注：`qlineargradient` 已从禁项移除 —— 静态环境光渐变（树洞暮蓝）属有意设计，
#: 不是动画；仍禁止 `animation:` 与 `qproperty-`。
FORBIDDEN_QSS_PATTERNS: Tuple[str, ...] = (
    "animation:", "qproperty-",
)


# --------------------------------------------------------------------------- 对比度工具


def _srgb_channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 相对亮度。"""
    text = hex_color.lstrip("#")
    r, g, b = (int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """两色的对比度（≥ 4.5 表示满足正文可读性）。"""
    lum_a, lum_b = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return round((lighter + 0.05) / (darker + 0.05), 2)


# --------------------------------------------------------------------------- QSS


def build_qss() -> str:
    """返回全应用 QSS。**两个桌面应用都必须调用本函数**（UI约定 §2 硬要求 2）。

    约定：所有样式都通过 `objectName` 命中（见 `widgets.py` 的 `setObjectName`），
    页面里不写内联样式表，避免出现"两套 QSS"。
    """
    return f"""
/* ===== 基础 ===== */
QWidget {{
    background-color: {BG};
    color: {INK};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: {FONT_BODY}px;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}

QLabel {{ background: transparent; color: {INK}; }}
QLabel#Title      {{ font-size: {FONT_TITLE}px; font-weight: 600; color: {INK}; }}
QLabel#Heading    {{ font-size: {FONT_HEADING}px; font-weight: 600; color: {INK}; }}
QLabel#Body       {{ font-size: {FONT_BODY}px; color: {INK}; }}
QLabel#Hint       {{ font-size: {FONT_SMALL}px; color: {INK_SOFT}; }}
QLabel#Error      {{ font-size: {FONT_SMALL}px; color: {DANGER_SOFT}; }}
QLabel#Badge      {{ font-size: {FONT_SMALL}px; color: {PRIMARY_INK};
                     background-color: {MIST}; border-radius: {RADIUS_SMALL}px;
                     padding: 3px 10px; }}
QLabel#BadgeSoft  {{ font-size: {FONT_SMALL}px; color: {INK};
                     background-color: {CORAL}; border-radius: {RADIUS_SMALL}px;
                     padding: 3px 10px; }}
QLabel#BadgeCalm  {{ font-size: {FONT_SMALL}px; color: {INK};
                     background-color: {SPROUT}; border-radius: {RADIUS_SMALL}px;
                     padding: 3px 10px; }}
QLabel#CardTitle  {{ font-size: {FONT_HEADING}px; font-weight: 600; color: {INK}; }}

/* ===== 卡片 ===== */
QFrame#Card {{
    background-color: {CARD};
    border: none;
    border-radius: {RADIUS}px;
}}
QFrame#Divider {{ background-color: {LINE}; border: none; }}

/* ===== 环境光：树洞暮蓝渐变（夜间温暖的安全感）===== */
QWidget#TreeholeTab {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {DUSK_TOP}, stop:1 {DUSK_BOTTOM});
}}

/* ===== 按钮 ===== */
QPushButton {{
    font-size: {FONT_BODY}px;
    color: {INK};
    background-color: {FIELD};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 9px 18px;
    min-height: {MIN_TAP}px;
}}
QPushButton:hover   {{ background-color: #EDE4D6; }}
QPushButton:pressed {{ background-color: #E6DCC9; }}
QPushButton:disabled {{ color: {INK_FADE}; background-color: #F2EEE6; }}

QPushButton#PrimaryButton {{
    background-color: {MIST};
    color: {PRIMARY_INK};
    border: none;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover   {{ background-color: #9DBDD1; }}
QPushButton#PrimaryButton:pressed {{ background-color: #93B4C9; }}
QPushButton#PrimaryButton:disabled {{ background-color: #DCE6EC; color: {INK_FADE}; }}

QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid {LINE};
    color: {INK};
}}
QPushButton#GhostButton:hover {{ border-color: {MIST}; background-color: #F6F1E9; }}

QPushButton#ChoiceButton {{
    text-align: left;
    padding: 7px 16px;
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
}}
QPushButton#ChoiceButton:hover   {{ border-color: {MIST}; background-color: #F3F7F9; }}
QPushButton#ChoiceButton:checked {{
    border: 2px solid {MIST};
    background-color: #EAF2F6;
    color: {PRIMARY_INK};
    font-weight: 600;
}}

/* ===== 情绪卡片（Q1）：emoji + 文字 的竖向卡片 =====
   「色彩光晕」= 按 `mood` 动态属性命中的底色 + 边界色；落在 `:checked` 之前，
   选中态（`:checked`）仍后置、后写赢。呼吸动画由代码的 opacity 循环实现，不走 QSS。 */
QPushButton#MoodCard {{
    text-align: center;
    padding: 16px 12px;
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
}}
QPushButton#MoodCard[mood="happy"] {{ border: 1px solid {MOOD_HAPPY_LINE}; background-color: {MOOD_HAPPY_BG}; }}
QPushButton#MoodCard[mood="plain"] {{ border: 1px solid {MOOD_PLAIN_LINE}; background-color: {MOOD_PLAIN_BG}; }}
QPushButton#MoodCard[mood="down"]  {{ border: 1px solid {MOOD_DOWN_LINE}; background-color: {MOOD_DOWN_BG}; }}
QPushButton#MoodCard:hover {{ border-color: {MIST}; background-color: #F3F7F9; }}
QPushButton#MoodCard:checked {{
    border: 2px solid {MIST};
    background-color: #EAF2F6;
    color: {PRIMARY_INK};
    font-weight: 600;
}}

/* 色温层：点「沮丧」时覆盖整屏的极浅冷调（浓度由代码的 opacity 控制，非 QSS 动画） */
QWidget#MoodTint {{ background-color: {MOOD_TINT}; }}

/* Q3 空状态引导文案（隐约、输入即淡出） */
QLabel#DetailGuide {{ font-size: {FONT_SMALL}px; color: {INK_FADE}; background: transparent; }}

/* ===== 输入 ===== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {FIELD};
    color: {INK};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 12px 14px;
    selection-background-color: {MIST};
    selection-color: {PRIMARY_INK};
}}
QLineEdit {{ min-height: {MIN_TAP}px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {FOCUS_RING};
}}

/* 预约时间选择页的下拉（年月日时间段） */
QComboBox {{
    background-color: {FIELD};
    color: {INK};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 9px 12px;
    min-height: {MIN_TAP}px;
}}
QComboBox:focus {{ border: 2px solid {FOCUS_RING}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    color: {INK};
    selection-background-color: {MIST};
    selection-color: {PRIMARY_INK};
    border: 1px solid {LINE};
}}

/* ===== 焦点可见（键盘可达，UI约定 §2 硬要求 4）===== */
QPushButton:focus, QRadioButton:focus, QCheckBox:focus, QComboBox:focus {{
    border: 2px solid {FOCUS_RING};
}}
QTabBar::tab:focus {{ border: 2px solid {FOCUS_RING}; }}

/* ===== 单选 / 复选 ===== */
QRadioButton, QCheckBox {{ spacing: 8px; padding: 6px 2px; color: {INK}; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; }}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    background-color: {MIST}; border: 2px solid {PRIMARY_INK}; border-radius: 8px;
}}
QRadioButton::indicator:unchecked, QCheckBox::indicator:unchecked {{
    background-color: {CARD}; border: 1px solid {LINE}; border-radius: 8px;
}}

/* ===== Tab ===== */
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: {RADIUS}px; background: {CARD};
                    top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {INK_SOFT};
    padding: 10px 22px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: {RADIUS_SMALL}px;
    border-top-right-radius: {RADIUS_SMALL}px;
    min-height: {MIN_TAP}px;
}}
QTabBar::tab:selected {{
    background: {CARD};
    color: {PRIMARY_INK};
    border: 1px solid {LINE};
    border-bottom-color: {CARD};
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {INK}; }}

/* ===== 学生端左侧深色导航（SideNav：深色侧边栏 + 横排菜单）===== */
QWidget#SideNavBar {{
    background: {NAV_BG};
    min-width: 176px;
}}
QPushButton#NavItem {{
    background: transparent;
    color: {NAV_INACTIVE};
    padding: 12px 18px;
    border: none;
    border-radius: 9px;
    min-height: {MIN_TAP}px;
    font-weight: 500;
    text-align: left;
}}
QPushButton#NavItem:hover {{
    color: {NAV_ACTIVE_TEXT};
    background: {NAV_HOVER_BG};
}}
QPushButton#NavItem:checked {{
    background: {NAV_ACTIVE_BG};
    color: {NAV_ACTIVE_TEXT};
    font-weight: 600;
}}

/* ===== 列表 ===== */
QListWidget, QListView, QScrollArea {{
    background-color: {CARD};
    border: none;
    border-radius: {RADIUS}px;
    outline: none;
}}
QListWidget::item {{ padding: 12px 14px; border-bottom: 1px solid {LINE}; color: {INK}; }}
QListWidget::item:selected {{ background-color: #EAF2F6; color: {PRIMARY_INK}; }}
QListWidget::item:focus {{ border: 2px solid {FOCUS_RING}; }}

/* ===== 进度 ===== */
QProgressBar {{
    background-color: {LINE};
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    color: {INK};
}}
QProgressBar::chunk {{ background-color: {MIST}; border-radius: 6px; }}

/* ===== 滚动条（无动画、无闪烁）===== */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {MIST}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ===== 状态栏 / 提示条 ===== */
QStatusBar {{ background: {CARD}; color: {INK_SOFT}; border-top: 1px solid {LINE}; }}
QLabel#Toast {{
    background-color: {CARD};
    color: {INK};
    border: 1px solid {MIST};
    border-radius: {RADIUS_SMALL}px;
    padding: 10px 14px;
}}
QLabel#Hotline {{ font-size: {FONT_MUTE}px; color: {INK_FADE}; }}

/* ===== 预约时间课表（学生端 / 教师端**共用**同一份样式）=====
   格子状态靠动态属性 `slotState` 命中；红框 = 教师设的「不可预约」。
   ⚠️ 选中态 `[slotSelected="yes"]` 必须放在最后：QSS 同特异性时**后写的赢**。 */
QPushButton#SlotCell {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 12px;
    padding: 6px 2px;
    font-size: {FONT_SMALL}px;
    color: {INK};
}}
QPushButton#SlotCell:hover {{ border-color: {MIST}; background-color: #F3F7F9; }}
QPushButton#SlotCell[slotState="blocked"] {{
    background-color: {SLOT_BLOCKED_BG};
    border: 2px solid {SLOT_BLOCKED_LINE};
    color: {SLOT_BLOCKED_INK};
}}
QPushButton#SlotCell[slotState="taken"] {{
    background-color: {SLOT_TAKEN_BG};
    border: 1px solid {SLOT_TAKEN_LINE};
    color: {INK};
}}
QPushButton#SlotCell[slotState="mine"] {{
    background-color: {SLOT_MINE_BG};
    border: 2px solid {SLOT_MINE_LINE};
    color: {INK};
    font-weight: 600;
}}
QPushButton#SlotCell[slotState="past"] {{
    background-color: {SLOT_PAST_BG};
    border: 1px dashed {LINE};
    color: {INK_FADE};
}}
QPushButton#SlotCell[slotSelected="yes"] {{
    border: 3px solid {PRIMARY_INK};
    background-color: {MIST};
    color: {PRIMARY_INK};
    font-weight: 600;
}}

/* 月份导航栏（1~12 月） */
QPushButton#MonthButton {{
    padding: 8px 4px;
    background-color: {FIELD};
    color: {INK};
}}
QPushButton#MonthButton:hover {{ background-color: #EDE4D6; }}
QPushButton#MonthButton:checked {{
    background-color: {MIST};
    color: {PRIMARY_INK};
    font-weight: 600;
}}

/* 课表的行列头（星期 / 节次） */
QLabel#SlotHead {{ font-size: {FONT_SMALL}px; color: {INK_SOFT}; font-weight: 600; }}
QLabel#SlotPeriod {{ font-size: {FONT_SMALL}px; color: {INK_SOFT}; }}

/* 图例色块（与格子配色同源） */
QFrame#SwatchFree     {{ background-color: {CARD}; border: 1px solid {LINE};
                         border-radius: 5px; }}
QFrame#SwatchBlocked  {{ background-color: {SLOT_BLOCKED_BG};
                         border: 2px solid {SLOT_BLOCKED_LINE}; border-radius: 5px; }}
QFrame#SwatchTaken    {{ background-color: {SLOT_TAKEN_BG};
                         border: 1px solid {SLOT_TAKEN_LINE}; border-radius: 5px; }}
QFrame#SwatchMine     {{ background-color: {SLOT_MINE_BG};
                         border: 2px solid {SLOT_MINE_LINE}; border-radius: 5px; }}
"""


# --------------------------------------------------------------------------- 字体


#: QSS 里声明的字体族（按可用性回退）
FONT_CANDIDATES: Tuple[str, ...] = (
    "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI",
)

#: 无显示器/offscreen 环境下的字体文件搜索目录。
#: ⚠️ 为什么需要：PySide6 不再随包提供字体，offscreen 平台下 Qt 没有系统字体数据库，
#: 中文会渲染成空白/方框（截图会只有色块）。显式加载一个系统中文字体即可修复。
FONT_SEARCH_DIRS: Tuple[str, ...] = (
    r"C:\Windows\Fonts",
    "/usr/share/fonts",
    "/System/Library/Fonts",
)

#: 优先加载的字体文件（顺序即优先级）
_FONT_FILES: Tuple[str, ...] = (
    "msyh.ttc", "msyhbd.ttc", "Deng.ttf", "simhei.ttf", "simsun.ttc",
    "NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf", "PingFang.ttc",
    "DejaVuSans.ttf", "seguisym.ttf", "seguiemj.ttf",
)


def install_fonts(app=None, *, quiet: bool = True) -> list:
    """显式加载系统字体（offscreen 下的中文与 emoji 渲染前提）。

    返回成功加载的字体文件路径列表；找不到任何候选字体时返回空列表
    （**不抛异常**：字体缺失不该让应用起不来，但自检会把空列表判为失败）。

    主字体仍是候选里的第一个中文字体（`_FONT_FILES[0]`），其余（含 emoji
    字体 `seguisym/seguiemj`）一并注册进字体库，供 Qt 做逐字回退。
    """
    from pathlib import Path

    from PySide6.QtGui import QFont, QFontDatabase

    loaded: list = []
    families: list = []
    for directory in FONT_SEARCH_DIRS:
        base = Path(directory)
        if not base.is_dir():
            continue
        for name in _FONT_FILES:
            path = base / name
            if not path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                continue
            names = QFontDatabase.applicationFontFamilies(font_id)
            if not names:
                continue
            loaded.append(str(path))
            families.extend(names)
        if loaded:
            break
    if families and app is not None:
        font = QFont(families[0])
        font.setPointSize(FONT_BODY)
        app.setFont(font)
    if loaded and not quiet:
        short = [Path(p).name for p in loaded]
        print(f"已加载字体：{', '.join(short)}")
    return loaded


def apply_theme(app) -> str:
    """把主题应用到 `QApplication`（或任意 QWidget）；返回 QSS 字符串便于自检核对。"""
    qss = build_qss()
    app.setStyleSheet(qss)
    return qss
