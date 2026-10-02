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
    "BG", "CARD", "INK", "INK_SOFT", "LINE", "MIST", "CORAL", "SPROUT",
    "PRIMARY_INK", "FOCUS_RING", "DANGER_SOFT",
    "BRAND", "BRAND_SELECTED", "SUCCESS", "PENDING", "WARNING", "AUX_GRAY",
    "RADIUS", "CARD_PADDING", "FONT_BODY", "FONT_TITLE", "FONT_SMALL",
    "LINE_HEIGHT", "MIN_TAP", "ANIM_MS", "PALETTE", "SIZES",
    "FONT_CANDIDATES", "FONT_SEARCH_DIRS",
    "contrast_ratio", "relative_luminance", "build_qss", "apply_theme",
    "install_fonts",
]

# --------------------------------------------------------------------------- 调色板
# 见山教师端 · 统一设计变量（低饱和蓝灰体系）

BG = "#F5F7FA"            # 主背景（极浅蓝灰）
CARD = "#FFFFFF"          # 卡片背景（纯白）
INK = "#243447"           # **正文文字**（深蓝灰）
INK_SOFT = "#64748B"      # 次要文字（中性灰）
LINE = "#E4E9F0"          # 分隔线 / 边框（极浅灰蓝）
MIST = "#EAF1F7"          # 选中背景（浅蓝）
CORAL = "#F7E4E1"         # 预警浅底（浅红）
SPROUT = "#DFEEE6"        # 成功浅底（浅绿）
PRIMARY_INK = "#4E7FAE"   # 品牌主色（低饱和蓝）
FOCUS_RING = "#7AA7CC"    # 焦点环（品牌蓝加深）
DANGER_SOFT = "#B85C55"   # 预警/错误（克制红）

#: 见山教师端语义色
BRAND = "#4E7FAE"          # 品牌主色
BRAND_SELECTED = "#EAF1F7" # 选中背景
SUCCESS = "#38765B"        # 成功状态
PENDING = "#A66A24"        # 待处理状态
WARNING = "#B85C55"        # 预警状态
AUX_GRAY = "#526174"       # 分割线与辅助色

#: 供别的模块（含教师端）枚举主题变量，避免各处硬编码色值
PALETTE: Dict[str, str] = {
    "BG": BG, "CARD": CARD, "INK": INK, "INK_SOFT": INK_SOFT, "LINE": LINE,
    "MIST": MIST, "CORAL": CORAL, "SPROUT": SPROUT, "PRIMARY_INK": PRIMARY_INK,
    "FOCUS_RING": FOCUS_RING, "DANGER_SOFT": DANGER_SOFT,
    "BRAND": BRAND, "BRAND_SELECTED": BRAND_SELECTED, "SUCCESS": SUCCESS,
    "PENDING": PENDING, "WARNING": WARNING, "AUX_GRAY": AUX_GRAY,
}

# --------------------------------------------------------------------------- 尺寸

RADIUS = 14          # 圆角 ≥ 12px（UI约定 §2 尺寸）
RADIUS_SMALL = 12
CARD_PADDING = 22    # 卡片内边距 ≥ 20px
FONT_BODY = 15       # 正文 15–16px
FONT_TITLE = 21
FONT_HEADING = 17
FONT_SMALL = 13
LINE_HEIGHT = 1.6
MIN_TAP = 34         # 可点区域最小高度（桌面 ≥ 32×32）
ANIM_MS = 180        # 唯一允许的动画（淡入/淡出）时长，≤ 240ms

SIZES: Dict[str, object] = {
    "RADIUS": RADIUS, "RADIUS_SMALL": RADIUS_SMALL, "CARD_PADDING": CARD_PADDING,
    "FONT_BODY": FONT_BODY, "FONT_TITLE": FONT_TITLE, "FONT_HEADING": FONT_HEADING,
    "FONT_SMALL": FONT_SMALL, "LINE_HEIGHT": LINE_HEIGHT, "MIN_TAP": MIN_TAP,
    "ANIM_MS": ANIM_MS,
}

#: 正则：QSS 里禁止出现动画/闪烁类属性（自检会断言）
FORBIDDEN_QSS_PATTERNS: Tuple[str, ...] = (
    "qlineargradient", "animation:", "qproperty-",
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
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
}}
QFrame#Divider {{ background-color: {LINE}; border: none; }}

/* ===== 按钮 ===== */
QPushButton {{
    font-size: {FONT_BODY}px;
    color: {INK};
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: {RADIUS_SMALL}px;
    padding: 9px 18px;
    min-height: {MIN_TAP}px;
}}
QPushButton:hover   {{ border-color: {MIST}; background-color: #F3F7F9; }}
QPushButton:pressed {{ background-color: #E8F0F4; }}
QPushButton:disabled {{ color: {INK_SOFT}; background-color: #F2EFE9; border-color: {LINE}; }}

QPushButton#PrimaryButton {{
    background-color: {MIST};
    color: {PRIMARY_INK};
    border: 1px solid {MIST};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover   {{ background-color: #9DBDD1; border-color: #9DBDD1; }}
QPushButton#PrimaryButton:pressed {{ background-color: #93B4C9; border-color: #93B4C9; }}
QPushButton#PrimaryButton:disabled {{ background-color: #DCE6EC; color: {INK_SOFT};
                                      border-color: #DCE6EC; }}

QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid {LINE};
    color: {INK};
}}
QPushButton#GhostButton:hover {{ border-color: {MIST}; }}

QPushButton#ChoiceButton {{
    text-align: left;
    padding: 14px 18px;
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

/* ===== 输入 ===== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {CARD};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: {RADIUS_SMALL}px;
    padding: 10px 12px;
    selection-background-color: {MIST};
    selection-color: {PRIMARY_INK};
}}
QLineEdit {{ min-height: {MIN_TAP}px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {FOCUS_RING};
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

/* ===== 列表 ===== */
QListWidget, QListView, QScrollArea {{
    background-color: {CARD};
    border: 1px solid {LINE};
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
QLabel#Hotline {{ font-size: {FONT_SMALL}px; color: {INK_SOFT}; }}
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
    "DejaVuSans.ttf",
)


def install_fonts(app=None, *, quiet: bool = True) -> list:
    """显式加载一个可用的中文字体（offscreen 下中文渲染的前提）。

    返回成功加载的字体文件路径列表；找不到任何候选字体时返回空列表
    （**不抛异常**：字体缺失不该让应用起不来，但自检会把空列表判为失败）。
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
            break
        if loaded:
            break
    if families and app is not None:
        font = QFont(families[0])
        font.setPointSize(FONT_BODY)
        app.setFont(font)
    if loaded and not quiet:
        print(f"已加载字体：{loaded[0]}（{families[:2]}）")
    return loaded


def apply_theme(app) -> str:
    """把主题应用到 `QApplication`（或任意 QWidget）；返回 QSS 字符串便于自检核对。"""
    qss = build_qss()
    app.setStyleSheet(qss)
    return qss
