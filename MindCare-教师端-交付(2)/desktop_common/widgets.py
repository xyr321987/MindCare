"""基础控件（`docs/UI约定.md` §1 的 `widgets.py`）。

设计纪律：

* **样式只来自 `theme.build_qss()`**，这里只负责 `setObjectName`；页面里不写内联样式表。
* **可点控件一律 `Qt.StrongFocus`**（`enforce_focus_policy()` 可对整个控件树兜底），
  且 `build_qss()` 里有可见 focus 样式（UI约定 §2 硬要求 4）。
* **无弹跳/抖动/闪烁/循环动画**：本模块唯一的动画是提示条的淡入淡出，
  时长 `theme.ANIM_MS = 180ms ≤ 240ms`。
* **面向用户的文字一律由调用方从文案表传入**（本模块不产生任何中文文案）。

`objectName` 约定（QSS 与自检都依赖它，**不要改**）::

    Card / Divider / Title / Heading / Body / Hint / Error
    Badge / BadgeSoft / BadgeCalm / CardTitle
    PrimaryButton / GhostButton / ChoiceButton
    Progress / Toast / Hotline
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import theme

__all__ = [
    "OBJECT_NAMES", "make_label", "make_title", "make_heading", "make_body",
    "make_hint", "make_error", "make_badge",
    "make_button", "make_primary_button", "make_ghost_button", "make_choice_button",
    "Card", "TextArea", "Progress", "ChoiceGroup", "ResultPage", "Toast",
    "divider", "hspacer", "vspacer", "hotline_label",
    "enforce_focus_policy", "clickable_widgets", "wrap_scroll",
]

#: QSS 依赖的 objectName 清单（自检会断言它们都真实存在）
OBJECT_NAMES: Tuple[str, ...] = (
    "Card", "Divider", "Title", "Heading", "Body", "Hint", "Error",
    "Badge", "BadgeSoft", "BadgeCalm", "CardTitle",
    "PrimaryButton", "GhostButton", "ChoiceButton", "Progress", "Toast", "Hotline",
)

#: 按钮角色 → objectName
BUTTON_ROLE_OBJECT = {
    "primary": "PrimaryButton",
    "ghost": "GhostButton",
    "choice": "ChoiceButton",
    "default": "",
}


# --------------------------------------------------------------------------- 标签


def make_label(text: str = "", object_name: str = "Body",
               *, word_wrap: bool = True, parent: Optional[QWidget] = None) -> QLabel:
    """统一标签工厂：文本由调用方从文案表取。

    wordWrap 的 QLabel **必须**保留 heightForWidth 标志（2026-10-03 修复）：
    直接 `setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)` 会用
    新构造的 policy 覆盖 `setWordWrap(True)` 内部设置的 hfw 标志；hfw 丢失后
    wordWrap 文本在布局中只按 sizeHint 快照分配高度（嵌套在卡片里时常退化为
    单行高度，长文被截断）。布局拿到 hfw 才会按实际宽度调
    `heightForWidth(width)` 精确计算换行高度。
    """
    label = QLabel(text, parent)
    label.setObjectName(object_name)
    label.setWordWrap(word_wrap)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    policy.setHeightForWidth(word_wrap)
    label.setSizePolicy(policy)
    return label


def make_title(text: str = "", **kw) -> QLabel:
    return make_label(text, "Title", **kw)


def make_heading(text: str = "", **kw) -> QLabel:
    return make_label(text, "Heading", **kw)


def make_body(text: str = "", **kw) -> QLabel:
    return make_label(text, "Body", **kw)


def make_hint(text: str = "", **kw) -> QLabel:
    return make_label(text, "Hint", **kw)


def make_error(text: str = "", **kw) -> QLabel:
    label = make_label(text, "Error", **kw)
    label.setVisible(bool(text))
    return label


def make_badge(text: str = "", tone: str = "mist",
               parent: Optional[QWidget] = None) -> QLabel:
    """小徽标。`tone`: `mist`（雾蓝底）/ `coral`（柔珊瑚底）/ `calm`（嫩芽绿底）。

    三种都是**底色**，文字统一深色 —— 主色不做正文字色（UI约定 §2 硬要求 1）。
    """
    name = {"mist": "Badge", "coral": "BadgeSoft", "calm": "BadgeCalm"}.get(tone, "Badge")
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(False)
    label.setAlignment(Qt.AlignCenter)
    label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return label


# --------------------------------------------------------------------------- 按钮


def make_button(text: str = "", role: str = "default", *,
                parent: Optional[QWidget] = None,
                object_name: Optional[str] = None,
                checkable: bool = False) -> QPushButton:
    """统一按钮工厂（**所有按钮都强制 `Qt.StrongFocus`**）。"""
    button = QPushButton(text, parent)
    button.setObjectName(object_name if object_name is not None
                         else BUTTON_ROLE_OBJECT.get(role, ""))
    button.setFocusPolicy(Qt.StrongFocus)
    button.setCursor(Qt.PointingHandCursor)
    button.setCheckable(checkable)
    button.setMinimumHeight(theme.MIN_TAP)
    return button


def make_primary_button(text: str = "", **kw) -> QPushButton:
    return make_button(text, "primary", **kw)


def make_ghost_button(text: str = "", **kw) -> QPushButton:
    return make_button(text, "ghost", **kw)


def make_choice_button(text: str = "", **kw) -> QPushButton:
    kw.setdefault("checkable", True)
    return make_button(text, "choice", **kw)


# --------------------------------------------------------------------------- 容器


class Card(QFrame):
    """卡片容器：圆角 ≥ 12px、内边距 ≥ 20px（UI约定 §2 尺寸）。"""

    def __init__(self, parent: Optional[QWidget] = None,
                 *, padding: int = theme.CARD_PADDING,
                 spacing: int = 12, title: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(spacing)
        self.title_label: Optional[QLabel] = None
        if title:
            self.title_label = make_label(title, "CardTitle")
            self._layout.addWidget(self.title_label)

    def body_layout(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


def divider(parent: Optional[QWidget] = None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    return line


def hspacer() -> QWidget:
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    return spacer


def vspacer() -> QWidget:
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
    return spacer


def hotline_label(text: str, parent: Optional[QWidget] = None) -> QLabel:
    """危机热线行（UI约定 §6：页脚必须含非诊断声明 + 热线）。"""
    label = QLabel(text, parent)
    label.setObjectName("Hotline")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class TextArea(QTextEdit):
    """多行输入（大输入框）。不显示字数上限、不做倒计时（文案表 §6 约束 5）。"""

    def __init__(self, parent: Optional[QWidget] = None, *,
                 placeholder: str = "", min_height: int = 160) -> None:
        super().__init__(parent)
        self.setObjectName("TextArea")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptRichText(False)
        self.setMinimumHeight(min_height)
        if placeholder:
            self.setPlaceholderText(placeholder)

    def text_value(self) -> str:
        return self.toPlainText().strip()

    def set_text_value(self, text: str) -> None:
        self.setPlainText(text or "")


class Progress(QProgressBar):
    """进度指示（确定值；**不做循环/弹跳动画** —— UI约定 §2 硬要求 3）。"""

    def __init__(self, parent: Optional[QWidget] = None,
                 *, minimum: int = 0, maximum: int = 100, value: int = 0) -> None:
        super().__init__(parent)
        self.setObjectName("Progress")
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setFocusPolicy(Qt.NoFocus)

    def set_progress(self, done: int, total: int) -> None:
        self.setRange(0, max(int(total), 1))
        self.setValue(max(0, min(int(done), int(total))))


class ChoiceGroup(QWidget):
    """单选组（可点控件全部 `Qt.StrongFocus`，Tab 可遍历，方向键可切换）。

    :param options: `[(value, label), ...]`
    """

    changed = Signal(str)

    def __init__(self, options: Sequence[Tuple[str, str]],
                 parent: Optional[QWidget] = None, *, vertical: bool = True) -> None:
        super().__init__(parent)
        self._buttons: List[QPushButton] = []
        self._values: List[str] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for index, (value, label) in enumerate(options):
            button = make_choice_button(label, parent=self)
            button.setObjectName("ChoiceButton")
            self._group.addButton(button, index)
            layout.addWidget(button)
            self._buttons.append(button)
            self._values.append(value)
            button.clicked.connect(lambda _checked=False, v=value: self.changed.emit(v))
        self.setFocusPolicy(Qt.StrongFocus)

    # -- 查询 / 设置 ---------------------------------------------------------

    def value(self) -> Optional[str]:
        checked = self._group.checkedId()
        if checked < 0 or checked >= len(self._values):
            return None
        return self._values[checked]

    def set_value(self, value: Optional[str]) -> None:
        if value is None:
            self.clear_selection()
            return
        if value in self._values:
            self._buttons[self._values.index(value)].setChecked(True)

    def clear_selection(self) -> None:
        self._group.setExclusive(False)
        for button in self._buttons:
            button.setChecked(False)
        self._group.setExclusive(True)

    def buttons(self) -> List[QPushButton]:
        return list(self._buttons)

    def labels(self) -> List[str]:
        return [button.text() for button in self._buttons]


class Toast(QLabel):
    """轻量提示条：淡入（180ms）→ 停留 → 淡出（180ms）。

    ⚠️ 唯一允许的动画形态：**一次性的淡入淡出**，无弹跳/抖动/闪烁/循环
    （UI约定 §2 硬要求 3）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVisible(False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(theme.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def show_message(self, text: str) -> None:
        self.setText(text)
        self.setVisible(True)
        self._anim.stop()
        self._anim.setStartValue(float(self._effect.opacity()))
        self._anim.setEndValue(1.0)
        self._anim.start()

    def clear_message(self) -> None:
        self._anim.stop()
        self._effect.setOpacity(0.0)
        self.setVisible(False)
        self.setText("")

    @property
    def animation_duration_ms(self) -> int:
        return int(self._anim.duration())


class ResultPage(QWidget):
    """结果页容器：`result_scene` 的 5 个页面都复用它渲染。

    统一结构 = 卡片（标题 + 正文 + 可选步骤/提示 + 动作区 + 页脚热线），
    保证 5 个结束页语气与留白一致（UI约定 §5.1 的 result_scene 穷举映射）。
    """

    def __init__(self, scene: str, parent: Optional[QWidget] = None, *,
                 hotline_text: str = "") -> None:
        super().__init__(parent)
        #: 该页对应的 `result_scene` 值（自检按此穷举 5 个页面）
        self.scene = scene
        self.setObjectName(f"ResultPage_{scene}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(vspacer())

        self.card = Card(title="")
        self.title_label = make_title("")
        self.body_label = make_body("")
        self.extra_label = make_hint("")
        self.extra_label.setVisible(False)
        self.card.add(self.title_label)
        self.card.add(self.body_label)
        self.card.add(self.extra_label)
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setContentsMargins(0, 4, 0, 0)
        self.steps_layout.setSpacing(6)
        self.card.add_layout(self.steps_layout)
        self.actions = QWidget()
        self.actions_layout = QHBoxLayout(self.actions)
        self.actions_layout.setContentsMargins(0, 8, 0, 0)
        self.actions_layout.setSpacing(12)
        self.card.add(self.actions)
        self.footer_label = make_hint("")
        self.card.add(self.footer_label)
        self.hotline = hotline_label(hotline_text)
        self.card.add(self.hotline)

        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.card, 3)
        holder.addStretch(1)
        outer.addLayout(holder)
        outer.addWidget(vspacer())

    # -- 渲染 ---------------------------------------------------------------

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_body(self, text: str) -> None:
        self.body_label.setText(text)

    def set_extra(self, text: str) -> None:
        self.extra_label.setText(text)
        self.extra_label.setVisible(bool(text))

    def set_steps(self, steps: Iterable[str]) -> None:
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for step in steps:
            self.steps_layout.addWidget(make_body(f"· {step}"))

    def set_footer(self, text: str) -> None:
        self.footer_label.setText(text)
        self.footer_label.setVisible(bool(text))

    def add_action(self, button: QPushButton) -> QPushButton:
        self.actions_layout.addWidget(button)
        return button

    def add_stretch(self) -> None:
        self.actions_layout.addStretch(1)


# --------------------------------------------------------------------------- 工具


def wrap_scroll(inner: QWidget, parent: Optional[QWidget] = None) -> QScrollArea:
    """把内容放进滚动区（窗口小时不裁剪内容）。"""
    area = QScrollArea(parent)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(inner)
    return area


def clickable_widgets(root: QWidget) -> List[QWidget]:
    """返回控件树里所有"可点"控件（自检用来断言 `Qt.StrongFocus`）。"""
    out: List[QWidget] = []
    for widget in [root] + root.findChildren(QWidget):
        if isinstance(widget, (QPushButton,)):
            out.append(widget)
    return out


def enforce_focus_policy(root: QWidget) -> int:
    """给所有可点控件补上 `Qt.StrongFocus`（幂等）；返回处理过的控件数。"""
    count = 0
    for widget in clickable_widgets(root):
        if widget.focusPolicy() != Qt.StrongFocus:
            widget.setFocusPolicy(Qt.StrongFocus)
            count += 1
    return count
