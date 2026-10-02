"""问卷状态机（`docs/UI约定.md` §5.1 / `docs/架构设计方案.md` §5.1）。

v1.0 流程（**没有 Q2.5 那一页**）::
    Q1 心情：高兴 / 平淡 / 沮丧
      ├ 高兴 → 恭喜页 ────────────────────────┐
      ├ 平淡 → 原因选填页 ────────────────────┤
      └ 沮丧 → Q2 原因 → Q3 详细阐述（必填）   │
                                             │
          求助选择（请求心理老师帮助 / 不用帮助）  ← happy 分支跳过此页
                    ↓ 一次性 POST /questionnaire/submissions
          结果页（按 result_scene 渲染，**共 4 个值，逐一穷举**）

* **逐题跳转纯本地，不走网络**（契约 §4.2）：本模块 `import` 列表里没有任何网络客户端。
* 提交**只发生一次**，由主窗口发起（`submit_requested` 信号 → `QThreadPool`）。
* `result_scene` 四个值都有实体页面：见 `RESULT_PAGES` 与 `show_result()`；
  未知值落到 `_unmapped` 页（可见的兜底页，而不是静默什么都不做）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from desktop_common.copy import COPY
from desktop_common.models import RESULT_SCENES
from desktop_common.widgets import (
    ResultPage,
    make_ghost_button,
    make_hint,
    make_primary_button,
    make_title,
)

from .pages import (
    AppointmentPage,
    CausePage,
    DetailPage,
    ExplorePage,
    FlowState,
    HelpPage,
    MoodPage,
    NotePage,
    NoticePage,
)

__all__ = ["QuestionnaireTab", "RESULT_PAGES", "PAGE_ORDER", "NOT_READY_KEY"]

#: `engine_ready=false`（数据库恢复中）时页面上的"稍后重试"文案用哪条键。
#:
#: ✅ 2026-10-02：原借用的 `c.error.network`=「网络好像有点慢，等会儿再试就好。」
#: 语义不准（这不是网络问题，是数据库在恢复）。现已在 `copywriting.md` §4.7
#: 正式收录专用键，改用之。与主窗口顶部提示条的分工：
#: 顶部条说「稍等一下再试」，提交拦截说「现在还不能提交」。
NOT_READY_KEY = "c.engine.notReady.action"

#: 结果页 → 文案 ID 组（v1.0 `result_scene` 4 个值全部在此登记）
_RESULT_COPY: Dict[str, Dict[str, str]] = {
    "happy_end": {
        "title": "s.end.happy.title",
        "body": "s.end.happy.body",
        "footer": "s.end.happy.footer",
        "primary": "s.end.happy.action.treehole",
        "ghost": "s.end.happy.action.close",
    },
    "plain_tips": {
        "title": "s.end.plain.title",
        "body": "s.end.plain.tips",
        "footer": "s.end.plain.footer",
        "primary": "s.end.plain.action.treehole",
        "ghost": "s.end.plain.action.close",
    },
    "help_sent": {
        "title": "s.end.help.title",
        "body": "s.end.help.body",
        "footer": "s.end.help.footer",
        "ghost": "s.end.help.action.close",
    },
    "self_care": {
        "title": "s.end.selfcare.title",
        "body": "s.end.selfcare.body",
        "footer": "s.end.selfcare.hotline.title",
        "primary": "s.end.selfcare.action.treehole",
        "ghost": "s.end.selfcare.action.close",
    },
}

#: `result_scene` → 栈内页面（自检断言：4 个值都能在控制器里查到页面）
RESULT_PAGES: Dict[str, str] = {
    "happy_end": "result_happy_end",
    "plain_tips": "result_plain_tips",
    "help_sent": "result_help_sent",
    "self_care": "result_self_care",
}

#: 栈内页面顺序（自检按此逐个构建）
PAGE_ORDER: tuple[str, ...] = (
    "notice", "q1", "plain_note", "q2", "explore", "q3", "help", "appointment",
    "result_happy_end", "result_plain_tips", "result_help_sent",
    "result_self_care", "result_unmapped",
)


class _UnmappedResultPage(QWidget):
    """**兜底页**：`result_scene` 出现未登记值时显示可见提示，绝不静默。

    这不是"未实现的分支"，而是防漂移的可观测兜底（例如契约将来新增第 6 个值）。
    它会被 `QuestionnaireTab.show_result()` 通过 `_add()` 注册进页面字典，因此
    `show_page("result_unmapped")` 能查到它（页面 ID 与本类 `page_id` 一致）。
    """

    page_id = "result_unmapped"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page_result_unmapped")
        self.setMinimumHeight(420)      # 让兜底页在 QStackedWidget 里占据可读高度
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(make_title(COPY["c.error.unknown"]))
        self.detail = make_hint("")
        layout.addWidget(self.detail)
        layout.addStretch(1)

    def set_scene(self, scene: str) -> None:
        self.detail.setText(scene)


class QuestionnaireTab(QWidget):
    """Tab1「问卷」：`QStackedWidget` 逐题切换（纯本地）。"""

    #: 最终提交请求（由主窗口接管 → QThreadPool → ApiClient）
    submit_requested = Signal(dict)
    #: 结果页的「写树洞」深链（切到 Tab2 并打开编辑器）
    treehole_deeplink = Signal()
    #: 结果页的「关闭/再见」（回到告知页并重置本地状态）
    restart_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *,
                 profile_provider: Optional[Callable[[], dict]] = None,
                 client: Any = None, runner: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("QuestionnaireTab")
        self.state = FlowState()
        self.stack = QStackedWidget(self)
        self.stack.setObjectName("QuestionnaireStack")
        #: 服务端 `engine_ready`（数据库就绪信号）。`False` 时**禁用所有提交按钮**
        #: 且**不发出** `submit_requested`，避免学生填完整份问卷才失败（协议 §5）。
        self.engine_ready = True
        #: 取当前登录档案的回调（预约页要显示"班级 / 学号"；由主窗口注入）
        self._profile_provider = profile_provider
        #: 预约页走 HTTP 共享库的 client/runner（透传给 `AppointmentPage`；None=本地模式）
        self._client = client
        self._runner = runner

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.pages: Dict[str, QWidget] = {}
        self._build_pages()
        self._wire()
        self.reset()

    # ---------------------------------------------------------------- 构建

    def set_profile_provider(self, provider: Optional[Callable[[], dict]]) -> None:
        """登录后由主窗口注入"取当前档案"的回调（预约人基本信息要用）。"""
        self._profile_provider = provider
        self.appointment._profile_provider = provider

    def _build_pages(self) -> None:
        self.notice = NoticePage()
        self.q1 = MoodPage()
        self.plain_note = NotePage()
        self.q2 = CausePage()
        self.explore = ExplorePage()
        self.q3 = DetailPage()
        self.help = HelpPage()
        self.appointment = AppointmentPage(
            profile_provider=self._profile_provider,
            client=self._client, runner=self._runner)
        for page in (self.notice, self.q1, self.plain_note, self.q2,
                     self.explore, self.q3, self.help, self.appointment):
            self._add(page)

        self.result_pages: Dict[str, ResultPage] = {}
        for scene, page_id in RESULT_PAGES.items():
            page = ResultPage(scene, hotline_text=COPY.hotline_line())
            page.setObjectName(page_id)
            self._render_result_scene(page, scene)
            self._add(page)
            self.result_pages[scene] = page

        self.unmapped = _UnmappedResultPage()
        self._add(self.unmapped)

    def _add(self, page: QWidget) -> None:
        page_id = getattr(page, "page_id", page.objectName())
        self.pages[page_id] = page
        self.stack.addWidget(page)

    def _render_result_scene(self, page: ResultPage, scene: str) -> None:
        keys = _RESULT_COPY[scene]
        page.set_title(COPY[keys["title"]])
        page.set_body(COPY[keys["body"]])
        page.set_footer(COPY[keys["footer"]])
        if scene == "self_care":
            page.set_steps((
                COPY["s.end.selfcare.suggest.breath"],
                COPY["s.end.selfcare.suggest.walk"],
                COPY["s.end.selfcare.suggest.treehole"],
                COPY["s.end.selfcare.suggest.friend"],
            ))
            page.set_extra(COPY["s.end.selfcare.tips"])
        primary_key = keys.get("primary")
        if primary_key:
            button = make_primary_button(COPY[primary_key])
            button.setObjectName("PrimaryButton")
            button.clicked.connect(self.treehole_deeplink.emit)
            page.add_action(button)
        ghost_key = keys.get("ghost")
        if ghost_key:
            button = make_ghost_button(COPY[ghost_key])
            button.setObjectName("GhostButton")
            button.clicked.connect(self.restart_requested.emit)
            page.add_action(button)
        page.add_stretch()

    def _wire(self) -> None:
        self.notice.next_requested.connect(lambda: self.show_page("q1"))
        self.q1.next_requested.connect(self._after_mood)
        self.plain_note.back_requested.connect(lambda: self.show_page("q1"))
        self.plain_note.skip_requested.connect(self._plain_skip)
        self.plain_note.note_submitted.connect(self._plain_note)
        self.q2.next_requested.connect(self._after_cause)
        self.q2.back_requested.connect(self._back_from_q2)
        self.explore.next_requested.connect(self._after_explore)
        self.explore.back_requested.connect(lambda: self.show_page("q1"))
        self.q3.back_requested.connect(self._back_from_q3)
        self.q3.detail_submitted.connect(self._detail_submitted)
        self.help.back_requested.connect(lambda: self.show_page("q3"))
        self.help.submit_requested.connect(self._final_submit)
        self.appointment.back_requested.connect(lambda: self.show_page("help"))
        self.appointment.confirmed.connect(self._on_appointment_confirmed)

    # ---------------------------------------------------------------- 导航

    def show_page(self, page_id: str) -> None:
        page = self.pages.get(page_id)
        if page is None:  # pragma: no cover - 防御：内部 ID 拼错
            raise KeyError(f"问卷里没有这个页面：{page_id}")
        self.stack.setCurrentWidget(page)
        enter = getattr(page, "enter", None)
        if callable(enter):
            enter()

    @property
    def current_page_id(self) -> str:
        current = self.stack.currentWidget()
        return getattr(current, "page_id", current.objectName())

    def set_error(self, text: str) -> None:
        """把错误显示在**当前页**（提交失败时状态不清空，学生不用重填）。"""
        current = self.stack.currentWidget()
        setter = getattr(current, "set_error", None)
        if callable(setter):
            setter(text)

    def clear_error(self) -> None:
        self.set_error("")

    # ---------------------------------------------------------------- 服务端就绪

    #: 所有"会造成提交"的按钮：三处显式提交 + 树洞深链**不算**（它不发问卷请求）
    @property
    def submit_buttons(self) -> List[Any]:
        """问卷里所有会触发提交的按钮（自检按此断言"全部被禁用"）。"""
        return [self.plain_note.submit_button, self.q3.submit_button,
                self.help.submit_button]

    def set_engine_ready(self, ready: bool) -> None:
        """`engine_ready=false`（数据库恢复中）→ 禁用全部提交按钮。

        协议 §5：此时"所有带鉴权请求应提示稍后重试"。禁用按钮只是第一道闸；
        **自动提交**分支（高兴 / 平淡且**不**填原因）不经过按钮，由 `_emit_submit()`
        的第二道闸负责，两道闸一起才覆盖全部提交路径。
        （2026-10-02：`平淡且填了原因` 已改为走 Q3 + 求助页，**不再**是自动提交分支。）
        """
        self.engine_ready = bool(ready)
        for button in self.submit_buttons:
            button.setEnabled(self.engine_ready)

    def not_ready_text(self) -> str:
        """"数据库恢复中，稍后再试"的页面文案（来自文案表，见 `NOT_READY_KEY`）。"""
        return COPY[NOT_READY_KEY]

    def submission_blocked(self) -> bool:
        """提交是否被"数据库未就绪"挡住（**唯一的判定点**）。

        允许调用的时机：`engine_ready` 已知为 `False`。`_emit_submit()` 与三处
        显式提交按钮都问这一个方法，避免"每个入口各写一份判断"那样漏掉一条路径。
        """
        return self.engine_ready is False

    # ---------------------------------------------------------------- 分支

    def _after_mood(self) -> None:
        mood = self.q1.value()
        self.state.mood = mood
        if mood == "happy":
            # 高兴分支：无需求助选择，直接提交（request_help / consent_share = false）
            if not self._allow_submit():
                return                      # 数据库恢复中：不落状态、不跳页、不发请求
            self.state.request_help = False
            self.state.plain_branch_taken = None
            self._emit_submit()
            return
        if mood == "plain":
            self.show_page("plain_note")
            return
        self.show_page("explore")

    def _plain_skip(self) -> None:
        """平淡且不填原因 → 直接提交（契约矩阵第 2 行），结果页为快乐小贴士。"""
        if not self._allow_submit():
            return
        self.state.plain_branch_taken = "skip"
        self.state.plain_note = None
        self.state.cause_category = None
        self.state.detail = None
        self.state.request_help = False
        self._emit_submit()

    def _plain_note(self, text: str) -> None:
        self.state.plain_branch_taken = "note"
        self.state.plain_note = text
        self.show_page("q2")

    def _after_cause(self) -> None:
        self.state.cause_category = self.q2.value()
        # ⚠️ 2026-10-02 修正（**曾被用户当场撞到**）：
        #   原实现把 plain 分支在这里直接 `_emit_submit()`，并注释"矩阵第 3 行不存在求助选择"。
        #   那是对矩阵的**误读**——第 3 行（plain 且填了原因）与第 4 行（down）要求完全相同：
        #       cause_category 必填 + **detail 必填** + **request_help 必选**
        #   而这条路径**从不收集 detail**（保持 None）→ 服务端必然回
        #       `HTTP 400 / code=2001 参数校验失败: detail`
        #   实测复现：连点几次后还会撞上 `4001` 限流，把学生彻底锁住一分钟。
        #   现在两条分支（平淡 / 沮丧）都要进 Q3（详述）与求助选择页。
        self.show_page("q3")

    def _after_explore(self) -> None:
        """情绪探索（仅沮丧分支）：多选 → 单值 `cause_category` → Q3 详述。"""
        self.state.cause_category = self.explore.cause_category()
        self.show_page("q3")

    def _allow_submit(self) -> bool:
        """提交前统一过闸：数据库未就绪 → 显示"稍后重试"并返回 `False`。

        覆盖**不经过按钮**的自动提交分支（高兴 / 平淡且**不**填原因）—— 按钮已被
        `set_engine_ready()` 禁用，但这两条路径根本不会点按钮。
        （2026-10-02：`平淡且填了原因` 改为走求助页，已由按钮闸覆盖。）
        """
        if not self.submission_blocked():
            return True
        text = self.not_ready_text()
        self.set_error(text)
        self.help.set_error(text)
        return False

    def _back_from_q2(self) -> None:
        """Q2 的"上一步"（仅平淡分支）：回到原因选填页。"""
        if self.state.mood == "plain":
            self.show_page("plain_note")
            return
        self.show_page("q1")

    def _back_from_q3(self) -> None:
        """Q3 的"上一步"：沮丧分支回到情绪探索，平淡分支回到 Q2。"""
        if self.state.mood == "down":
            self.show_page("explore")
            return
        self.show_page("q2")

    def _detail_submitted(self, text: str) -> None:
        self.state.detail = text
        self.show_page("help")

    def _final_submit(self, request_help: bool) -> None:
        # 契约强制：request_help 与 consent_share 同值
        self.state.request_help = bool(request_help)
        if request_help:
            # 「请求心理老师帮助」→ 先跳去选预约时间；确认后由
            # `_on_appointment_confirmed` 落状态并提交
            self.show_page("appointment")
            return
        self._emit_submit()

    def _on_appointment_confirmed(self, payload: dict) -> None:
        """预约时间选择完成：暂存载荷并走正常提交（由主窗口落本地预约库）。"""
        self.state.appointment = dict(payload or {})
        self._emit_submit()

    def _emit_submit(self) -> None:
        if self.submission_blocked():
            # 第二道闸（兜底）：任何走漏的提交路径到这里也不会发出请求。
            # 第一道闸在 `_allow_submit()` / `set_engine_ready()` 的按钮禁用。
            text = self.not_ready_text()
            self.set_error(text)
            self.help.set_error(text)
            return
        body = self.state.build_body(
            record_id=self.state.record_id,
            consent_ts=None,       # consent_ts 由主窗口在提交前按 ISO 时间戳填充
        )
        self.submit_requested.emit(body)

    # ---------------------------------------------------------------- 结果页

    def show_result(self, scene: str, *, tips_text: str = "") -> None:
        """按 `result_scene` 渲染结果页（**v1.0 的 4 个值穷举**，未登记则显示兜底页）。"""
        self.state.result_scene = scene
        page = self.result_pages.get(scene)
        if page is None:
            self.unmapped.set_scene(scene)
            self.show_page(self.unmapped.page_id)
            return
        if tips_text:
            page.set_body(tips_text)
        self.show_page(scene_to_page_id(scene))

    def reset(self) -> None:
        """回到告知页并清空本地状态（结果页"再见"、退出登录都走这里）。"""
        self.state.reset()
        for page in (self.q1, self.plain_note, self.q2, self.explore, self.q3,
                     self.help, self.appointment):
            reset = getattr(page, "reset", None)
            if callable(reset):
                reset()
        self.show_page("notice")

    def focus_first(self) -> None:
        """把焦点放到当前页第一个可点控件（键盘可达）。"""
        current = self.stack.currentWidget()
        for child in current.findChildren(QWidget):
            if child.focusPolicy() == Qt.StrongFocus and child.isVisible():
                child.setFocus()
                return


def scene_to_page_id(scene: str) -> str:
    """`result_scene` → 栈内页面 ID（未登记时返回兜底页）。"""
    return RESULT_PAGES.get(scene, "unmapped")


def all_result_scenes() -> List[str]:
    """契约 v1.0 `enums.result_scene` 的 4 个值（自检按此穷举）。"""
    return list(RESULT_SCENES)
