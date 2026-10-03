"""问卷流程的各个页面（`docs/UI约定.md` §5.1 / `docs/接口约定.md` §4.1）。

**逐题跳转纯本地，不走网络**：本模块不 import 任何网络客户端，
所有跳转由 `ui/questionnaire.py` 的 `QStackedWidget` 完成；
只有在最后一屏（求助选择）点确认时，才由主窗口发起**一次** `POST`。

文案纪律：本模块**不出现任何中文界面文案字面量**，一律 `COPY["<ID>"]`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_common import appointments as appt_store
from desktop_common import theme
from desktop_common import schedule as schedule_mod
from desktop_common import schedule_store
from desktop_common import sync as sync_mod
from desktop_common.copy import COPY
from desktop_common.remote_sync import RemoteSchedule
from desktop_common.schedule_grid import ScheduleBoard
from desktop_common.widgets import (
    Card,
    ChoiceGroup,
    MultiChoiceGroup,
    Progress,
    TextArea,
    divider,
    hotline_label,
    make_body,
    make_error,
    make_ghost_button,
    make_hint,
    make_primary_button,
    make_title,
    wrap_scroll,
)

__all__ = [
    "FlowState",
    "NoticePage", "MoodPage", "NotePage", "CausePage", "ExplorePage",
    "DetailPage", "HelpPage", "AppointmentPage",
]


@dataclass
class FlowState:
    """问卷本地状态（**纯内存，逐题跳转不产生网络请求**）。"""

    mood: Optional[str] = None
    plain_note: Optional[str] = None
    cause_category: Optional[str] = None
    detail: Optional[str] = None
    request_help: Optional[bool] = None
    record_id: str = ""
    result_scene: Optional[str] = None
    plain_branch_taken: Optional[str] = None   # 'skip' | 'note'
    #: 预约时间载荷（`AppointmentPage.confirmed` 透传）：year/month/day/time +
    #: share_questionnaire / share_treehole。`None` = 本次没有预约时间。
    appointment: Optional[dict] = None
    extra: Dict[str, object] = field(default_factory=dict)

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    # -- 提交体 -------------------------------------------------------------

    def build_body(self, record_id: str, consent_ts: Optional[str]) -> dict:
        """按 v1.0 校验矩阵构造 `POST /questionnaire/submissions` 的请求体。

        v1.0 只有 **8 个字段**：
        `record_id, mood, plain_note, cause_category, detail, request_help,
        consent_share, consent_ts`。

        `request_help` 与 `consent_share` **同值**（契约强制）；`consent_ts` 仅在
        `consent_share=true` 时给出（单独同意留痕）。

        矩阵四行（v1.0，仅 6 列）::

            happy            → plain_note/cause_category/detail 全 null，两个布尔 false
            plain 且未填原因  → 同上
            plain 且填了原因  → plain_note 非空 + cause/detail 必填 + 求助选择
            down             → cause/detail 必填（不限字数）+ 求助选择
        """
        mood = self.mood or ""
        help_ = bool(self.request_help)
        body: dict = {
            "record_id": record_id,
            "mood": mood,
            "plain_note": None,
            "cause_category": None,
            "detail": None,
            "request_help": help_,
            "consent_share": help_,
            "consent_ts": consent_ts if help_ else None,
        }
        if mood == "plain" and self.plain_note:
            body["plain_note"] = self.plain_note
            body["cause_category"] = self.cause_category
            body["detail"] = self.detail
        elif mood == "down":
            body["cause_category"] = self.cause_category
            body["detail"] = self.detail
        return body


# --------------------------------------------------------------------------- 基类


class _FlowPage(QWidget):
    """问卷页基类：统一留白、进度条与"上一步"按钮。"""

    #: 自检按 page_id 断言每个页面都真的进了控件树
    page_id = "page"
    title_key = ""
    subtitle_key = ""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"Page_{self.page_id}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        self.header = Card()
        self.progress = Progress()
        self.header.add(self.progress)
        self.title_label = make_title(COPY.get(self.title_key, ""))
        self.header.add(self.title_label)
        self.subtitle_label = make_hint(COPY.get(self.subtitle_key, ""))
        self.subtitle_label.setVisible(bool(self.subtitle_key))
        self.header.add(self.subtitle_label)
        outer.addWidget(self.header)

        self.body = Card()
        outer.addWidget(self.body, 1)

        self.footer = QWidget()
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setSpacing(12)
        self.error_label = make_error("")
        self.footer_layout.addWidget(self.error_label, 1)
        outer.addWidget(self.footer)

        self.back_button = make_ghost_button(COPY["c.action.back"])
        self.back_button.clicked.connect(self.back_requested.emit)
        self.footer_layout.addWidget(self.back_button)

    back_requested = Signal()
    next_requested = Signal()

    def set_progress(self, step: int, total: int) -> None:
        self.progress.set_progress(step, total)

    def set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def show_back(self, visible: bool = True) -> None:
        self.back_button.setVisible(visible)

    def enter(self) -> None:
        """进入本页时重置瞬时状态（子类可按需覆盖）。"""
        self.set_error("")


class _ChoicePage(_FlowPage):
    """单选页基类：选项来自文案表 ID 列表。"""

    options_spec: tuple[tuple[str, str], ...] = ()
    next_key = "c.action.next"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.group = self._build_group()
        self.body.add(self.group)
        self.extra_note = make_hint(self._extra_note())
        self.extra_note.setVisible(bool(self._extra_note()))
        self.body.add(self.extra_note)
        self.next_button = make_primary_button(COPY[self.next_key])
        self.next_button.clicked.connect(self._on_next)
        self.footer_layout.addWidget(self.next_button)

    def _build_group(self):
        """构造选项控件（子类可覆盖为卡片等形态）。"""
        return ChoiceGroup([(value, COPY[key]) for value, key in self.options_spec])

    def _extra_note(self) -> str:
        return ""

    def _on_next(self) -> None:
        if self.group.value() is None:
            self.set_error(COPY["c.error.2001"])
            return
        self.set_error("")
        self.next_requested.emit()

    def value(self) -> Optional[str]:
        return self.group.value()

    def reset(self) -> None:
        self.group.clear_selection()
        self.set_error("")


# --------------------------------------------------------------------------- 告知页


class NoticePage(_FlowPage):
    """首次进入问卷的告知页（PIPL 第 30 条；`copywriting.md` §4.5）。

    ⚠️ v1.0 降级：文案表里的 `s.notice.item4/5/6` 描述的是 v1.1 才有的两条能力
    （① 匿名转交学校相关部门那一栏；② 在「我的档案」里事后收回某条的可见性）。
    v1.0 服务端既没有那条匿名转交通道，也没有那个接口，因此这三条**不渲染** ——
    告知页不得承诺应用做不到的事（其余 3 条如实说明数据用途与树洞私密性，保持不变）。
    文案本身仍**只从文案表取**，此处不新增任何字面量。
    """

    page_id = "notice"
    title_key = "s.notice.title"
    subtitle_key = "s.notice.subtitle"
    #: 实际渲染的告知条目（见类 docstring 的 v1.0 降级说明）
    item_indexes = (1, 2, 3)
    #: 「想直接预约」：跳过问卷直接跳去独立预约 Tab
    appointment_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.show_back(False)
        for index in self.item_indexes:
            self.body.add(make_body("· " + COPY[f"s.notice.item{index}"]))
        self.body.add(divider())
        # 非诊断声明（`docs/UI约定.md` §6 硬要求；文案在 `copywriting.md` §4.8 单独登记）。
        # v1.0 的告知页只说"内容给谁看"，不说"这算什么"——学生可能把心情记录当成结论，
        # 因此在热线之前先讲清"不构成医学诊断"。
        self.body.add(make_hint(COPY["c.disclaimer.nondiagnostic"]))
        self.body.add(hotline_label(COPY.hotline_line()))
        self.agree_button = make_primary_button(COPY["s.notice.action.agree"])
        self.agree_button.clicked.connect(self.next_requested.emit)
        self.exit_button = make_ghost_button(COPY["s.notice.action.exit"])
        self.exit_button.clicked.connect(self.appointment_requested.emit)
        self.footer_layout.insertWidget(0, self.exit_button)
        self.footer_layout.addWidget(self.agree_button)


# --------------------------------------------------------------------------- Q1

#: 情绪卡片「轻微呼吸」动画参数。呼吸天然是慢的（秒级），因此这里刻意**长于**
#: 主题里的 `theme.ANIM_MS`（180ms，那是提示条淡入淡出用）；幅度很小（不透明度
#: 只在 1.0 ↔ 0.88 之间），用 `InOutSine` 缓动，视觉上是「光晕在轻轻起伏」。
_BREATH_CYCLE_MS = 5200
_BREATH_MIN_OPACITY = 0.88


def _attach_breathing(button: QPushButton) -> QPropertyAnimation:
    """给整张情绪卡挂一个极轻的 opacity「呼吸」循环（不是 QSS，不触发自检的禁动画断言）。"""
    effect = QGraphicsOpacityEffect(button)
    effect.setOpacity(1.0)
    button.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", button)
    anim.setDuration(_BREATH_CYCLE_MS)
    anim.setKeyValueAt(0.0, 1.0)
    anim.setKeyValueAt(0.5, _BREATH_MIN_OPACITY)
    anim.setKeyValueAt(1.0, 1.0)
    anim.setEasingCurve(QEasingCurve.InOutSine)
    anim.setLoopCount(-1)
    anim.start()
    return anim


class MoodCardGroup(QWidget):
    """Q1「情绪卡片」单选组：三张卡片竖着一列、水平居中。

    与 `ChoiceGroup` 同接口（`value` / `set_value` / `clear_selection`），
    但把选项渲染成「emoji + 文字」的竖向卡片。按钮 objectName 为
    `MoodCard`（QSS 见 `theme.build_qss()`），可点控件仍是 `Qt.StrongFocus`。
    """

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str, str, str]],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._buttons: list = []
        self._values: list = []
        self._breath_anims: list = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # 三张卡片竖着一列、水平居中：每张卡外侧各放一个 1:2:1 的伸缩，
        # 让卡片占约一半宽且左右留白居中，三张卡宽度一致。
        for index, (value, label, emoji, desc) in enumerate(options):
            button = self._make_card(emoji, label, desc, value)
            self._group.addButton(button, index)
            self._buttons.append(button)
            self._values.append(value)
            button.clicked.connect(lambda _checked=False, v=value: self.changed.emit(v))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch(1)
            row.addWidget(button, 2)
            row.addStretch(1)
            root.addLayout(row)

    def _make_card(self, emoji: str, label: str, desc: str, mood: str) -> QPushButton:
        button = QPushButton(parent=self)
        button.setObjectName("MoodCard")
        #: 动态属性 `mood`（QSS 用 `[mood="…"]` 命中各自的光晕底色/边界色）。
        button.setProperty("mood", mood)
        #: 用「emoji 换行 天气名 换行 描述」的原始文本，而不是在按钮里嵌 QLabel 子控件——
        #: QPushButton 的绘制会盖住子控件，导致 emoji/文字消失（见预览截图问题）。
        button.setText(f"{emoji}\n{label}\n{desc}")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.StrongFocus)
        self._breath_anims.append(_attach_breathing(button))
        return button

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

    def buttons(self) -> list:
        return list(self._buttons)


class MoodPage(_ChoicePage):
    """Q1 心情（高兴 / 平淡 / 沮丧）—— 渲染成情绪卡片。"""

    page_id = "q1"
    title_key = "s.q1.title"
    subtitle_key = "s.q1.subtitle"
    options_spec = (
        ("happy", "s.q1.option.happy"),
        ("plain", "s.q1.option.plain"),
        ("down", "s.q1.option.down"),
    )

    def _build_group(self):
        return MoodCardGroup([
            (value, COPY[key], COPY[f"{key}.emoji"], COPY[f"{key}.desc"])
            for value, key in self.options_spec
        ])

    def _extra_note(self) -> str:
        return COPY["s.q1.hint.optional"]

    # -- 色温层（点「沮丧」时整屏铺一层极浅冷调，共情低落）------------------

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tint = self._make_tint()
        self.group.changed.connect(self._apply_tint)

    def _make_tint(self) -> QWidget:
        tint = QWidget(self)
        tint.setObjectName("MoodTint")
        tint.setAttribute(Qt.WA_StyledBackground, True)
        tint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        tint.setGeometry(self.rect())
        tint.raise_()
        self._tint_effect = QGraphicsOpacityEffect(tint)
        self._tint_effect.setOpacity(0.0)
        tint.setGraphicsEffect(self._tint_effect)
        self._tint_anim = QPropertyAnimation(self._tint_effect, b"opacity", tint)
        self._tint_anim.setDuration(theme.ANIM_MS)
        self._tint_anim.setEasingCurve(QEasingCurve.OutCubic)
        return tint

    #: 冷调浓度（点「沮丧」时的目标；其余情绪回 0）。值很小，只让色温「微」变。
    _TINT_OPACITY = 0.07

    def _apply_tint(self, value: Optional[str]) -> None:
        target = self._TINT_OPACITY if value == "down" else 0.0
        self._tint_anim.stop()
        self._tint_anim.setStartValue(float(self._tint_effect.opacity()))
        self._tint_anim.setEndValue(target)
        self._tint_anim.start()

    def enter(self) -> None:
        super().enter()
        # 回到本页时按当前选中值重放色温（`changed` 只在点击时触发）。
        self._apply_tint(self.group.value())

    def reset(self) -> None:
        super().reset()
        self._apply_tint(None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_tint"):
            self._tint.setGeometry(self.rect())


# --------------------------------------------------------------------------- B 分支


class NotePage(_FlowPage):
    """平淡分支：原因选填页。填了 → 继续 Q2；跳过 → 快乐小贴士 + 结束。"""

    page_id = "plain_note"
    title_key = "s.branch.b.title"
    subtitle_key = "s.branch.b.question"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.body.add(make_hint(COPY["s.branch.b.optionalTag"]))
        self.area = TextArea(placeholder=COPY["s.branch.b.placeholder"], min_height=140)
        self.body.add(self.area)
        self.body.add(make_hint(COPY["s.branch.b.hint.skip"]))
        self.skip_button = make_ghost_button(COPY["s.branch.b.skip"])
        self.skip_button.clicked.connect(self.skip_requested.emit)
        self.submit_button = make_primary_button(COPY["s.branch.b.submit"])
        self.submit_button.clicked.connect(self._on_submit)
        self.footer_layout.addWidget(self.skip_button)
        self.footer_layout.addWidget(self.submit_button)

    skip_requested = Signal()
    note_submitted = Signal(str)

    def _on_submit(self) -> None:
        text = self.area.text_value()
        if not text:
            self.set_error(COPY["s.q3.error.empty"])
            return
        self.set_error("")
        self.note_submitted.emit(text)

    def reset(self) -> None:
        self.area.set_text_value("")
        self.set_error("")


# --------------------------------------------------------------------------- C 分支


class CausePage(_ChoicePage):
    """Q2 原因（学业 / 人际关系 / 家庭矛盾）—— **仅平淡分支**（沮丧走情绪探索页）。"""

    page_id = "q2"
    title_key = "s.q2.title"
    subtitle_key = "s.q2.subtitle"
    options_spec = (
        ("study", "s.q2.option.study"),
        ("relationship", "s.q2.option.relationship"),
        ("family", "s.q2.option.family"),
    )


class ExplorePage(_FlowPage):
    """情绪探索页（**仅沮丧分支**）：Q1 之后的多选页。

    7 个选项可多选（`MultiChoiceGroup`，非互斥），落库时映射到契约枚举
    `cause_category`（`study` / `relationship` / `family`）。确定性规则：
    多选只取优先级最高的一桶 —— `家庭` > `同学关系` > 其余（`学习` / `考试` /
    `睡眠` / `对未来的担心` / `其他` 归入 `study`）。更细的差异由 Q3 自由文本承载。
    """

    page_id = "explore"
    title_key = "s.explore.title"
    subtitle_key = "s.explore.subtitle"
    options_spec = (
        ("study", "s.explore.option.study"),
        ("exam", "s.explore.option.exam"),
        ("relationship", "s.explore.option.relationship"),
        ("family", "s.explore.option.family"),
        ("sleep", "s.explore.option.sleep"),
        ("future", "s.explore.option.future"),
        ("other", "s.explore.option.other"),
    )

    #: 选项 → `cause_category` 分桶（只有 `study`/`relationship`/`family` 三个值）
    _BUCKET = {
        "family": "family",
        "relationship": "relationship",
        "study": "study",
        "exam": "study",
        "sleep": "study",
        "future": "study",
        "other": "study",
    }
    #: 多选时的优先级（取第一个命中的桶）
    _PRIORITY = ("family", "relationship", "study")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.back_button.setText(COPY["s.explore.action.back"])
        self.body.add(make_hint(COPY["s.explore.hint"]))
        self.group = MultiChoiceGroup(
            [(value, COPY[key] + "\n" + COPY[f"{key}.desc"])
             for value, key in self.options_spec])
        self.body.add(self.group)
        self.body.add(make_hint(COPY["s.explore.hint.bottom"]))
        self.next_button = make_primary_button(COPY["s.explore.action.next"])
        self.next_button.clicked.connect(self._on_next)
        self.footer_layout.addWidget(self.next_button)

    def _on_next(self) -> None:
        if not self.group.has_selection():
            self.set_error(COPY["c.error.2001"])
            return
        self.set_error("")
        self.next_requested.emit()

    def selected(self) -> List[str]:
        return self.group.selected()

    def cause_category(self) -> str:
        """多选 → 单值 `cause_category`（优先级见 `_PRIORITY`）。"""
        buckets = {self._BUCKET[v] for v in self.group.selected()}
        for category in self._PRIORITY:
            if category in buckets:
                return category
        return "study"  # 防御兜底：selected 非空时必有桶，这里不会命中

    def reset(self) -> None:
        self.group.clear_selection()
        self.set_error("")


class DetailPage(_FlowPage):
    """Q3 详细阐述（必填，不限字数；不显示字数上限、不做倒计时）。

    空状态在大输入框上隐约浮着几句引导（``s.q3.guide.*``），学生一开始输入
    它们就像雾气一样淡出；清空后又淡回，缓解「不知道从何说起」的压力。
    """

    page_id = "q3"
    title_key = "s.q3.title"
    subtitle_key = "s.q3.subtitle"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.back_button.setText(COPY["s.q3.action.back"])
        # 空态只显示引导浮层（``s.q3.guide.*``），不再叠加原生占位符，避免两套
        # 文案重叠、让本就低落的学生更无从下笔。
        self.area = TextArea(min_height=200)

        # 输入区与引导文案叠在同一格：引导是透明鼠标的浮层，盖在输入区上方。
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.area, 0, 0)
        self._guide = self._build_guide()
        grid.addWidget(self._guide, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        self.body.add(holder)
        self.body.add(make_hint(COPY["s.q3.hint.bottom"]))

        self.submit_button = make_primary_button(COPY["s.q3.action.next"])
        self.submit_button.clicked.connect(self._on_submit)
        self.footer_layout.addWidget(self.submit_button)
        self.area.textChanged.connect(self._on_text_changed)

    def _build_guide(self) -> QWidget:
        guide = QWidget()
        guide.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        inner = QVBoxLayout(guide)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)
        for key in ("s.q3.guide.title", "s.q3.guide.1", "s.q3.guide.2",
                    "s.q3.guide.3", "s.q3.guide.4", "s.q3.guide.example"):
            label = QLabel(COPY[key])
            label.setObjectName("DetailGuide")
            label.setWordWrap(True)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            inner.addWidget(label)
        inner.addStretch(1)
        self._guide_effect = QGraphicsOpacityEffect(guide)
        self._guide_effect.setOpacity(1.0)
        guide.setGraphicsEffect(self._guide_effect)
        self._guide_anim = QPropertyAnimation(self._guide_effect, b"opacity", guide)
        self._guide_anim.setDuration(theme.ANIM_MS)
        self._guide_anim.setEasingCurve(QEasingCurve.OutCubic)
        return guide

    def _on_text_changed(self) -> None:
        target = 0.0 if self.area.text_value() else 1.0
        self._guide_anim.stop()
        self._guide_anim.setStartValue(float(self._guide_effect.opacity()))
        self._guide_anim.setEndValue(target)
        self._guide_anim.start()

    detail_submitted = Signal(str)

    def _on_submit(self) -> None:
        # 「具体内容」可选：空文本也放行，先让学生够得着「要不要让老师陪」这一步
        self.set_error("")
        self.detail_submitted.emit(self.area.text_value() or "")

    def reset(self) -> None:
        self.area.set_text_value("")
        self.set_error("")
        # 清空后引导文案淡回（若原本就是空，textChanged 不触发，这里兜底一遍）。
        self._on_text_changed()


class HelpPage(_FlowPage):
    """求助选择页：**只有一个开关**（`request_help`，`consent_share` 同值）。"""

    page_id = "help"
    title_key = "s.help.title"
    subtitle_key = "s.help.subtitle"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.back_button.setText(COPY["s.help.action.back"])
        self.body.add(
            make_hint(f"{COPY['s.help.option.request']}：" +
                      COPY["s.help.option.request.note"])
        )
        self.body.add(
            make_hint(f"{COPY['s.help.option.no']}：" + COPY["s.help.option.no.note"])
        )
        self.group = ChoiceGroup((
            ("request", COPY["s.help.option.request"]),
            ("no", COPY["s.help.option.no"]),
        ))
        self.body.add(self.group)
        self.selection_note = make_hint("")
        self.selection_note.setVisible(False)
        self.body.add(self.selection_note)
        self.body.add(make_hint(COPY["s.help.hint"]))
        self.group.changed.connect(self._on_changed)
        self.submit_button = make_primary_button(COPY["s.help.action.next"])
        self.submit_button.clicked.connect(self._on_submit)
        self.footer_layout.addWidget(self.submit_button)

    submit_requested = Signal(bool)

    def _on_changed(self, value: str) -> None:
        key = ("s.help.selected.request" if value == "request"
               else "s.help.selected.no")
        self.selection_note.setText(COPY[key])
        self.selection_note.setVisible(True)
        self.set_error("")

    def _on_submit(self) -> None:
        value = self.group.value()
        if value is None:
            self.set_error(COPY["s.help.hint"])
            return
        self.set_error("")
        self.submit_requested.emit(value == "request")

    def reset(self) -> None:
        self.group.clear_selection()
        self.selection_note.setVisible(False)
        self.set_error("")


class AppointmentPage(_FlowPage):
    """预约时间选择页（**课表形态**）：`request_help=true` 后进入。

    界面（需求原文）：以一年为基本空间，`1 ~ 12` 月排成导航栏；**星期几为横轴**、
    **第 1 ~ 第 8 节为纵轴**，每一节课一个小方块、可点击。选完后填预约人基本信息
    （班级 / 学号，来自登录 profile），并可**选择性**勾选一并给老师看的个人信息
    （测评内容 / 树洞）。

    只承载**本地选择**：`confirmed` 把载荷发给 `QuestionnaireTab`，由主窗口落
    本地预约库（`desktop_common.appointments`）后再走问卷提交。

    格子状态的判定（双端共用的口径见 `desktop_common/schedule_grid.py`）::

        past    日期已过        → 弱化、不可点
        blocked 教师设为不可预约 → **红框**、不可点（实时同步）
        mine    本人已预约      → 绿框、可点（可改选）
        taken   别的同学已预约  → 暖砂底、不可点
        free    其余            → 可点

    实时同步
    --------
    `StoreWatcher` 盯着预约库与不可预约库，教师端一改，本页**自动**重刷红框
    （不需要学生重启或手点刷新）。判定与渲染都在主线程，成本是两次 `stat`。

    文案纪律：本页不产生中文字面量，标签一律 `COPY["<ID>"]`，时间段是数字格式。
    """

    page_id = "appointment"
    title_key = "s.appointment.title"
    subtitle_key = "s.appointment.subtitle"

    #: 载荷 dict：year/month/day/period/weekday/time(+起止) + share_*
    confirmed = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None, *,
                 profile_provider: Optional[Callable[[], dict]] = None,
                 standalone: bool = False,
                 client: Any = None, runner: Any = None) -> None:
        super().__init__(parent)
        #: 取当前登录档案（`{id, name, class_name}`）的回调；主窗口在登录后注入
        self._profile_provider = profile_provider
        #: 独立预约标签页模式（True 时隐藏问卷进度条与「上一步」，只保留课表 + 确认）
        self._standalone = bool(standalone)
        #: 当前选中的格子 `(period, column)`；`None` = 还没选
        self._selected: Optional[Tuple[int, int]] = None
        #: HTTP 轮询同步器（`client`+`runner` 都给时启用；否则回退本地文件 StoreWatcher）。
        #: `None` = 本地模式。两者对外的 `start/stop/changed/change_count/force_refresh`
        #: 接口一致，本页只面向 `self._sync` 编程。
        self._remote: Optional[RemoteSchedule] = None
        #: 查询「可预约老师」用的 HTTP client/runner（本地模式为 None → 下拉只显示不指定）
        self._client = client
        self._runner = runner

        # ⚠️ 这一页的内容（预约人信息 + 8×7 课表 + 已选 + 分享勾选）比一屏高。
        #    全部塞进 `self.body` 时课表会被压扁（实测：整张网格被压到只剩年份下拉）。
        #    所以页面内容整体放进**滚动区**，`self.body` 只承载这一个滚动区。
        content = QWidget()
        content.setObjectName("AppointmentContent")
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(12)

        # --- 预约人基本信息（班级 / 学号）------------------------------------
        # 单行紧凑排布（课表才是这页的主角；基本信息只做"确认"，不做输入）
        inner.addWidget(make_body(COPY["s.appointment.profile.title"]))
        info = QHBoxLayout()
        info.setSpacing(8)
        self._info_values: Dict[str, QLabel] = {}
        for key, value_key in (
            ("s.appointment.profile.name", "name"),
            ("s.appointment.profile.class", "class_name"),
            ("s.appointment.profile.sid", "id"),
        ):
            info.addWidget(make_hint(COPY[key]))
            value = make_body("")
            value.setObjectName(f"AppointmentProfile{value_key.title()}")
            info.addWidget(value)
            info.addStretch(1)
            self._info_values[value_key] = value
        inner.addLayout(info)
        self.profile_note = make_hint(COPY["s.appointment.profile.none"])
        self.profile_note.setObjectName("AppointmentProfileNote")
        inner.addWidget(self.profile_note)

        inner.addWidget(divider())

        # --- 课表（与学生端/教师端同一份控件）---------------------------------
        self.board = ScheduleBoard()
        self.board.setObjectName("AppointmentBoard")
        self.board.setMinimumHeight(470)
        inner.addWidget(self.board)
        self.board.cell_activated.connect(self._on_cell)
        self.board.view_changed.connect(self._refresh)

        inner.addWidget(divider())
        self.selected_label = make_body(COPY["s.appointment.selected.none"])
        self.selected_label.setObjectName("AppointmentSelected")
        inner.addWidget(self.selected_label)
        inner.addWidget(make_hint(COPY["s.appointment.hint.grid"]))

        # --- 选择预约老师（可选，下拉框）------------------------------------
        inner.addWidget(make_body(COPY["s.appointment.teacher.title"]))
        self.teacher_combo = QComboBox()
        self.teacher_combo.setObjectName("AppointmentTeacherCombo")
        self.teacher_combo.setFocusPolicy(Qt.StrongFocus)
        self.teacher_combo.addItem(COPY["s.appointment.teacher.none"], None)
        inner.addWidget(self.teacher_combo)
        self.teacher_hint = make_hint("")
        self.teacher_hint.setObjectName("AppointmentTeacherHint")
        self.teacher_hint.setVisible(False)
        inner.addWidget(self.teacher_hint)

        # --- 选择咨询室（必选，自动选中第一间可用）----------------------------
        inner.addWidget(make_body(COPY["s.appointment.room.title"]))
        self.room_combo = QComboBox()
        self.room_combo.setObjectName("AppointmentRoomCombo")
        self.room_combo.setFocusPolicy(Qt.StrongFocus)
        self.room_combo.addItem(COPY["s.appointment.room.none"], None)
        inner.addWidget(self.room_combo)
        self.room_hint = make_hint("")
        self.room_hint.setObjectName("AppointmentRoomHint")
        self.room_hint.setVisible(False)
        inner.addWidget(self.room_hint)

        #: 独立标签页的「预约成功」提示（问卷流程里无此提示，提交后即跳走）
        self._success_label = make_hint("")
        self._success_label.setObjectName("AppointmentSuccess")
        self._success_label.setVisible(False)
        inner.addWidget(self._success_label)

        # --- 选择性分享 -------------------------------------------------------
        inner.addWidget(make_body(COPY["s.appointment.share.title"]))
        self.share_questionnaire = QCheckBox(COPY["s.appointment.share.questionnaire"])
        self.share_questionnaire.setObjectName("ShareQuestionnaireCheck")
        self.share_questionnaire.setFocusPolicy(Qt.StrongFocus)
        self.share_treehole = QCheckBox(COPY["s.appointment.share.treehole"])
        self.share_treehole.setObjectName("ShareTreeholeCheck")
        self.share_treehole.setFocusPolicy(Qt.StrongFocus)
        inner.addWidget(self.share_questionnaire)
        inner.addWidget(self.share_treehole)
        inner.addWidget(make_hint(COPY["s.appointment.share.hint"]))
        inner.addStretch(1)

        self.body.add(wrap_scroll(content), 1)

        self.confirm_button = make_primary_button(COPY["s.appointment.confirm"])
        self.confirm_button.setObjectName("AppointmentConfirmButton")
        self.confirm_button.clicked.connect(self._on_confirm)
        self.footer_layout.addWidget(self.confirm_button)

        # --- 实时同步（教师改不可预约 → 学生端立刻看到红框）-------------------
        # HTTP 模式（联调后端共享库）：由 `RemoteSchedule` 轮询 `GET /appointments/blocks`；
        # 本地模式（未提供 client/runner，演示/离线）：沿用文件签名 `StoreWatcher`。
        if client is not None and runner is not None:
            # 学生读不到他人预约（`GET /appointments` 对学生 1002），但能读**自己的**预约
            # （`GET /appointments/mine`）——教师代订后这一格也要同步刷成「已预约」。
            self._remote = RemoteSchedule(client, runner,
                                         fetch_appointments=False, fetch_mine=True)
            self._sync = self._remote
        else:
            self._sync = sync_mod.StoreWatcher(
                [appt_store.appointment_file(), schedule_store.block_file()])
        self._sync.changed.connect(self._refresh)

        today = date.today()
        self.board.set_week(today.year, today.month, today.day)
        self._refresh()

        # 独立标签页：不显示问卷进度条与「上一步」（此时它不是问卷流程的一环）
        if self._standalone:
            self.show_back(False)
            self.progress.setVisible(False)

    def notify_saved(self, text: str) -> None:
        """独立标签页「确认预约」成功后显示可读提示；空串则隐藏。"""
        self._success_label.setText(text)
        self._success_label.setVisible(bool(text))

    # -- 实时同步 -----------------------------------------------------------

    def start_sync(self) -> None:
        """开始后台同步（进入本页时调用；幂等）。"""
        self._sync.start()

    def stop_sync(self) -> None:
        self._sync.stop()

    @property
    def sync_count(self) -> int:
        """已经收到过多少次"数据变了"（自检用它断言真的同步过）。"""
        return self._sync.change_count

    def force_sync(self) -> None:
        """手工触发一次刷新（自检 / 排障用）。"""
        self._sync.force_refresh()

    def mark_mine(self, slot: str) -> None:
        """把「本人已预约」的格子记进内存快照（HTTP 模式学生读不到预约清单）。

        预约 POST 成功后由主窗口回调调用，让这一格立刻刷成「已预约」绿框；
        本地模式无需调用（落库后 `_refresh` 自然读得到）。
        """
        if self._remote is not None and slot:
            self._remote.add_mine(slot)

    # -- 数据 ---------------------------------------------------------------

    def profile(self) -> dict:
        """当前登录档案（`{id, name, class_name}`）；没登录时返回空 dict。"""
        if self._profile_provider is None:
            return {}
        try:
            data = self._profile_provider()
        except Exception:                            # pragma: no cover - 防御
            return {}
        return data if isinstance(data, dict) else {}

    def student_id(self) -> str:
        return str(self.profile().get("id") or "")

    def _slot_data(self) -> Tuple[set, set, set]:
        """一次读齐三路事实源：`(blocked, mine, taken)`。

        HTTP 模式：`blocked`/`mine` 来自 `RemoteSchedule`；学生端读不到他人预约
        （`GET /appointments` 对学生 1002），故 `taken` 恒为空（谁约了不暴露给学生）。
        本地模式：三路都来自本地 JSON Lines 文件。
        """
        if self._remote is not None:
            return self._remote.blocked_slots(), self._remote.mine_slots(), set()
        blocked = schedule_store.blocked_slots()
        mine = appt_store.appointment_slots(student_id=self.student_id()) \
            if self.student_id() else {}
        taken = appt_store.appointment_slots()
        return blocked, mine, taken

    def _cell_state(self, blocked: set, mine: set, taken: set,
                    period: int, day: Tuple[int, int, int]
                    ) -> Tuple[str, Optional[str], Optional[bool]]:
        """单个格子的状态（**唯一的判定点**，`_refresh` 与自动预选共用）。"""
        year, month, day_no = day
        today = date.today()
        slot = schedule_mod.slot_id(year, month, day_no, period)
        if (year, month, day_no) < (today.year, today.month, today.day) \
                or schedule_mod.is_past_slot(year, month, day_no, period, now=today):
            return "past", "", False
        if slot in blocked:
            return "blocked", None, False
        if slot in mine:
            return "mine", None, True
        if slot in taken:
            return "taken", None, False
        return "free", None, True

    def _refresh(self) -> None:
        """重读事实源并重刷 56 个格子（**唯一的刷新入口**）。"""
        blocked, mine, taken = self._slot_data()

        def state_of(period: int, _column: int,
                     day: Tuple[int, int, int]) -> Tuple[str, Optional[str], Optional[bool]]:
            return self._cell_state(blocked, mine, taken, period, day)

        self.board.apply_states(state_of)
        self._render_selected()

    # -- 选择 ---------------------------------------------------------------

    def _on_cell(self, period: int, column: int) -> None:
        self._selected = (int(period), int(column))
        self.set_error("")
        self.notify_saved("")
        self._render_selected()
        self._refresh_teachers()
        self._refresh_rooms()

    def _autoselect_first_free(self) -> None:
        """进入页面时自动选中第一个可约格子，顺带触发老师/咨询室下拉框拉取。

        否则两个下拉框要等学生手点时间格才出现，看起来像「没得选择」。整周都是
        过去/停诊/已约时什么都不做，占位项会引导学生换一周再选。
        """
        blocked, mine, taken = self._slot_data()
        for column in range(schedule_mod.WEEKDAY_COUNT):
            day = self.board.date_at(column)
            if day is None:
                continue
            for period in range(schedule_mod.PERIOD_INDEX_MIN,
                                schedule_mod.PERIOD_INDEX_MAX + 1):
                _state, _text, clickable = self._cell_state(
                    blocked, mine, taken, period, day)
                if clickable:
                    self._on_cell(period, column)
                    return

    def _refresh_teachers(self) -> None:
        """选中格子后拉取该时段「可预约老师」，填充下拉框（本地模式/未选则不拉）。"""
        if self._client is None or self._runner is None:
            return
        day = self.selected_date()
        period = self.selected_period()
        if day is None or period is None:
            return
        year, month, day_no = day
        self.teacher_combo.blockSignals(True)
        self.teacher_combo.clear()
        self.teacher_combo.addItem(COPY["s.appointment.teacher.none"], None)
        self.teacher_combo.blockSignals(False)
        self.teacher_hint.setText(COPY["s.appointment.teacher.loading"])
        self.teacher_hint.setVisible(True)
        self._runner.submit(
            self._client.available_teachers, year, month, day_no, period,
            done=self._on_teachers_loaded, failed=self._on_teachers_failed)

    def _on_teachers_loaded(self, data: Any) -> None:
        available = [(it.get("teacher_id"), it.get("name"))
                     for it in (data or {}).get("items", []) if it.get("available")]
        self.teacher_combo.blockSignals(True)
        self.teacher_combo.clear()
        self.teacher_combo.addItem(COPY["s.appointment.teacher.none"], None)
        for tid, name in available:
            self.teacher_combo.addItem(str(name), str(tid))
        self.teacher_combo.blockSignals(False)
        if not available:
            self.teacher_hint.setText(COPY["s.appointment.teacher.empty"])
            self.teacher_hint.setVisible(True)
        else:
            self.teacher_hint.setVisible(False)

    def _on_teachers_failed(self, _error: Any) -> None:
        # 查询失败不弹错：下拉保持「不指定老师」，学生仍可正常预约
        self.teacher_hint.setVisible(False)

    def _refresh_rooms(self) -> None:
        """选中格子后拉取该时段「可预约咨询室」，自动选中第一间可用（必选）。"""
        if self._client is None or self._runner is None:
            return
        day = self.selected_date()
        period = self.selected_period()
        if day is None or period is None:
            return
        year, month, day_no = day
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        self.room_combo.blockSignals(False)
        self.room_hint.setText(COPY["s.appointment.room.loading"])
        self.room_hint.setVisible(True)
        self._runner.submit(
            self._client.available_rooms, year, month, day_no, period,
            done=self._on_rooms_loaded, failed=self._on_rooms_failed)

    def _on_rooms_loaded(self, data: Any) -> None:
        available = [it for it in (data or {}).get("items", []) if it.get("available")]
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        for it in available:
            label = str(it.get("name") or it.get("room_id") or "")
            loc = it.get("location")
            if loc:
                label += f"（{loc}）"
            self.room_combo.addItem(label, str(it.get("room_id")))
        self.room_combo.blockSignals(False)
        if not available:
            self.room_hint.setText(COPY["s.appointment.room.empty"])
            self.room_hint.setVisible(True)
        else:
            self.room_hint.setVisible(False)
            self.room_combo.setCurrentIndex(0)   # 必选：自动选中第一间可用

    def _on_rooms_failed(self, _error: Any) -> None:
        # 查询失败不弹错：放回占位项并提示换时间，避免下拉框留白
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        self.room_combo.addItem(COPY["s.appointment.room.none"], None)
        self.room_combo.blockSignals(False)
        self.room_hint.setText(COPY["s.appointment.room.empty"])
        self.room_hint.setVisible(True)

    def _render_selected(self) -> None:
        """刷新"已选："那一行（选中格里那个格子的文字也随之更新）。"""
        if self._selected is None:
            self.selected_label.setText(COPY["s.appointment.selected.none"])
            self.board.clear_selection()
            return
        period, column = self._selected
        day = self.board.date_at(column)
        if day is None:
            self.selected_label.setText(COPY["s.appointment.selected.none"])
            return
        year, month, day_no = day
        weekday = schedule_mod.weekday_from_date(year, month, day_no)
        week_key = schedule_mod.WEEKDAY_KEYS[weekday - 1] if 1 <= weekday <= 7 else ""
        text = (COPY["s.appointment.selected"]
                .replace("{date}", schedule_mod.date_text(year, month, day_no))
                .replace("{weekday}", COPY[week_key] if week_key else "")
                .replace("{period}", str(period))
                .replace("{start}", schedule_mod.period_start(period))
                .replace("{end}", schedule_mod.period_end(period)))
        self.selected_label.setText(text)
        self.board.set_selected(period, column)

    def selected_date(self) -> Optional[Tuple[int, int, int]]:
        """当前选中格子的日期 `(y, m, d)`；没选返回 `None`。"""
        if self._selected is None:
            return None
        return self.board.date_at(self._selected[1])

    def selected_period(self) -> Optional[int]:
        return None if self._selected is None else self._selected[0]

    def payload(self) -> dict:
        """当前选择 → 预约载荷（供 `confirmed` 与自检读取）。

        没选时间时返回**空 dict** —— 调用方据此判断"本次没有预约时间"。
        """
        day = self.selected_date()
        period = self.selected_period()
        if day is None or period is None:
            return {}
        year, month, day_no = day
        return {
            "year": f"{year:04d}",
            "month": f"{month:02d}",
            "day": f"{day_no:02d}",
            "period": str(period),
            "weekday": str(schedule_mod.weekday_from_date(year, month, day_no)),
            "time": schedule_mod.period_start(period),
            "time_start": schedule_mod.period_start(period),
            "time_end": schedule_mod.period_end(period),
            "teacher_id": self.teacher_combo.currentData(),
            "room_id": self.room_combo.currentData(),
            "share_questionnaire": self.share_questionnaire.isChecked(),
            "share_treehole": self.share_treehole.isChecked(),
        }

    # -- 提交 ---------------------------------------------------------------

    def _on_confirm(self) -> None:
        """确认预约：先按**最新**的库状态过一遍闸，再发 `confirmed`。

        ⚠️ 为什么重新查库而不是只看界面状态：界面可能是 1.5s 前刷的，
        这期间老师刚把这一格设成不可预约。用**当前**事实再判一次，
        学生就不会"看着可约、点下去却失败"。
        """
        self.set_error("")
        day = self.selected_date()
        period = self.selected_period()
        if day is None or period is None:
            self.set_error(COPY["s.appointment.error.none"])
            return
        year, month, day_no = day
        if schedule_mod.is_past_slot(year, month, day_no, period):
            self.set_error(COPY["s.appointment.error.past"])
            return
        slot = schedule_mod.slot_id(year, month, day_no, period)
        if self._remote is not None:
            # HTTP 模式：用最新快照里的 blocks 过闸（学生读不到他人预约，无法判 taken）。
            if slot in self._remote.blocked_slots():
                self.set_error(COPY["s.appointment.error.blocked"])
                self._refresh()
                return
        else:
            if schedule_store.is_blocked(year, month, day_no, period):
                self.set_error(COPY["s.appointment.error.blocked"])
                self._refresh()
                return
            mine = appt_store.appointment_slots(student_id=self.student_id()) \
                if self.student_id() else {}
            if slot not in mine and slot in appt_store.appointment_slots():
                self.set_error(COPY["s.appointment.error.taken"])
                self._refresh()
                return
        # 必选咨询室（HTTP 模式）：没有可用咨询室时拦截，避免落成 room_id 为空
        if self._client is not None and self.room_combo.currentData() is None:
            self.set_error(COPY["s.appointment.room.empty"])
            return
        self.stop_sync()
        self.confirmed.emit(self.payload())

    # -- 生命周期 -----------------------------------------------------------

    def enter(self) -> None:
        """进入本页：清错误 → 带出预约人信息 → 刷库 → 开同步。"""
        self.set_error("")
        self.notify_saved("")
        profile = self.profile()
        for key, label in self._info_values.items():
            label.setText(str(profile.get(key) or ""))
        self.profile_note.setVisible(not any(
            str(profile.get(key) or "") for key in self._info_values))
        self._refresh()
        self.start_sync()
        # 进页就自动选中第一个可约格子，让老师/咨询室下拉框立即有内容可看
        if self._selected is None:
            self._autoselect_first_free()

    def reset(self) -> None:
        """清掉选择、取消分享勾选、停同步（问卷整体 reset 时调用）。"""
        self.stop_sync()
        if self._remote is not None:
            # 换人登录后，"本人已预约"的口径也要清掉，否则上一位学生的绿框残留。
            self._remote.clear_mine()
        self._selected = None
        self.share_questionnaire.setChecked(False)
        self.share_treehole.setChecked(False)
        self.teacher_combo.blockSignals(True)
        self.teacher_combo.clear()
        self.teacher_combo.addItem(COPY["s.appointment.teacher.none"], None)
        self.teacher_combo.blockSignals(False)
        self.teacher_hint.setVisible(False)
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        self.room_combo.addItem(COPY["s.appointment.room.none"], None)
        self.room_combo.blockSignals(False)
        self.room_hint.setVisible(False)
        self.selected_label.setText(COPY["s.appointment.selected.none"])
        self.board.clear_selection()
        today = date.today()
        self.board.set_week(today.year, today.month, today.day)
        self.set_error("")
        self.notify_saved("")
