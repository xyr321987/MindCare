# -*- coding: utf-8 -*-
"""分诊台页面（迁移 教师端3.html 的主窗）。

保留的既有能力（一个不丢）：
- P1/P2/P3 优先级徽标 + chips（病史 / 近N次低落×N / 求助待处理）；
- 30s 增量轮询（since 游标用服务端 generated_at）；连续失败退避 30→60→120，成功恢复；
- 手动刷新全量、服务端排序不重排；断网横幅提示；
- 学生抽屉懒加载当日详情、masked 占位、工单 ack 状态机（pending→accepted→done）。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from desktop_common.api import ApiError
from desktop_common.widgets import (
    make_button, make_label, make_primary_button, wrap_scroll,
)

from ...app.settings import POLL_BACKOFF_STEPS, POLL_SECONDS
from ...core import enums
from ...core.models import TriageItem
from ...core.triage_client import TriageClient
from ..common.async_mixin import PageBase
from ..common.banner import Banner
from ..common.empty_state import EmptyState
from .student_drawer import StudentDrawer

#: 列宽（表头与行共用，保证对齐；改表格列只改这里）
COLUMNS = [(0, 132), (1, 86), (2, 98), (4, 92)]
COLUMN_HEADS = ["优先级", "姓名", "班级", "标记", "最后活跃"]


# ============================================================ 学生行
class StudentRow(QFrame):
    """列表中的一行：可点（自定义 QFrame，不用按钮以便嵌入多列布局）。"""

    picked = Signal(str)

    def __init__(self, item: TriageItem, server_date: str, parent=None) -> None:
        super().__init__(parent)
        self.student_id = item.student_id
        self.setObjectName("StudentRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(52)
        self.set_selected(False)

        grid = QGridLayout(self)
        grid.setContentsMargins(12, 6, 12, 6)
        grid.setVerticalSpacing(4)
        for col, width in COLUMNS:
            grid.setColumnMinimumWidth(col, width)
        grid.setColumnStretch(3, 1)

        # 优先级徽标
        p_text, _p_color = enums.PRIORITY.get(item.priority, enums.PRIORITY[3])
        badge = QLabel(p_text)
        badge.setObjectName(f"PrioBadge{item.priority if item.priority in (1, 2, 3) else 3}")
        badge.setAlignment(Qt.AlignCenter)
        grid.addWidget(badge, 0, 0)

        grid.addWidget(make_label(item.name, "Body", word_wrap=False), 0, 1)
        grid.addWidget(make_label(item.class_name or "—", "Body", word_wrap=False), 0, 2)

        # 标记 chips（顺序固定：病史 / 近窗低落 / 求助待处理）
        chips_box = QWidget()
        chips = QHBoxLayout(chips_box)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        for text, obj_name in self._chip_specs(item):
            chip = QLabel(text)
            chip.setObjectName(obj_name)
            if text == "病史" and item.flags.history_text:
                chip.setToolTip(str(item.flags.history_text))
            chips.addWidget(chip)
        if not item.flags or not self._chip_specs(item):
            chips.addWidget(make_label("—", "Body", word_wrap=False))
        chips.addStretch(1)
        grid.addWidget(chips_box, 0, 3)

        grid.addWidget(make_label(
            enums.relative_day_text(item.last_active_ts, server_date),
            "Body", word_wrap=False), 0, 4)

    @staticmethod
    def _chip_specs(item: TriageItem):
        specs = []
        if item.flags.has_history:
            specs.append(("病史", "ChipMist"))
        w = item.flags.window_size
        c = item.flags.recent_down_count
        # window_size 是实际窗口条数，不足 3 条如实显示，绝不写死 3
        if w > 0 and c > 0:
            specs.append((f"近{w}次低落×{c}", "ChipCoral"))
        if item.flags.pending_help:
            specs.append(("求助待处理", "ChipSprout"))
        return specs

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        # 动态属性变化后必须重新 polish，QSS 的 [selected=...] 才会生效
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.picked.emit(self.student_id)
        super().mousePressEvent(event)


# ============================================================ 分诊台页面
class TriagePage(PageBase):
    """分诊台。所有数据访问都在 worker 线程，主线程只渲染。"""

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.client: TriageClient = ctx.triage

        self._items: List[TriageItem] = []
        self._server_date = ""
        self._last_generated_at: Optional[str] = None
        self._selected_id: Optional[str] = None
        self._fail_count = 0
        self._synced = False
        self._seconds_left = POLL_SECONDS
        self._ago_seconds = 0

        self._build_ui()

        # 1s 心跳：驱动倒计时显示与轮询触发（轮询本身在 worker 线程）
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._update_sync_labels()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        # ---- 页头
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("分诊台", "PageTitle", word_wrap=False))
        titles.addWidget(make_label("按服务端规则排序，名单与标记每 30 秒增量同步",
                                    "PageSub", word_wrap=False))
        head.addLayout(titles)
        head.addStretch(1)
        source_text = f"数据源：{self.ctx.settings.server}"
        tag = make_label(source_text, "ModeTag", word_wrap=False)
        head.addWidget(tag, 0, Qt.AlignTop)
        self._root.addLayout(head)

        # ---- 同步状态行
        sync_row = QHBoxLayout()
        sync_row.setSpacing(16)
        self.sync_label = make_label("最后同步：尚未同步", "SyncHint", word_wrap=False)
        self.ago_label = make_label("尚未同步", "SyncHint", word_wrap=False)
        self.countdown_label = make_label("", "SyncHint", word_wrap=False)
        sync_row.addWidget(self.sync_label)
        sync_row.addWidget(self.ago_label)
        sync_row.addWidget(self.countdown_label)
        sync_row.addStretch(1)
        self.refresh_btn = make_primary_button("刷新")
        self.refresh_btn.clicked.connect(lambda: self._load_list(full=True, manual=True))
        sync_row.addWidget(self.refresh_btn)
        self._root.addLayout(sync_row)

        # ---- 断网横幅
        self.banner = Banner()
        self._root.addWidget(self.banner)

        # ---- 主体：名单 + 抽屉
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_list_panel(), 1)
        self.drawer = StudentDrawer()
        self.drawer.ticket_action.connect(self._on_ticket_action)
        body.addWidget(self.drawer)
        self._root.addLayout(body, 1)

    def _build_list_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 表头（与 StudentRow 列宽一致）
        head = QFrame()
        head.setMinimumHeight(44)
        grid = QGridLayout(head)
        grid.setContentsMargins(12, 0, 12, 0)
        for col, width in COLUMNS:
            grid.setColumnMinimumWidth(col, width)
        grid.setColumnStretch(3, 1)
        for col, text in enumerate(COLUMN_HEADS):
            grid.addWidget(make_label(text, "TableHead", word_wrap=False), 0, col)
        layout.addWidget(head)

        self.placeholder = EmptyState("正在拉取名单…")
        layout.addWidget(self.placeholder, 1)

        # 行容器
        self.rows_host = QWidget()
        self.rows_box = QVBoxLayout(self.rows_host)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        self.rows_box.addStretch(1)
        self.rows_scroll = wrap_scroll(self.rows_host)
        self.rows_scroll.setObjectName("PageScroll")
        self.rows_host.setObjectName("PageScrollContent")
        # 标记列（stretch）自适应宽度；窗口过窄时宁可略微裁切也不弹横向滚动条
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rows_scroll.setVisible(False)
        layout.addWidget(self.rows_scroll, 1)
        return panel

    # ------------------------------------------------------------------ 数据加载
    def refresh(self) -> None:
        """首次进入：全量拉名单。"""
        self._load_list(full=True)

    def _load_list(self, *, full: bool, manual: bool = False) -> None:
        if manual:
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText("刷新中…")

        since = None if full else self._last_generated_at

        def _job():
            return self.client.triage_list(since)

        self.call(_job,
                  on_ok=lambda data: self._on_list_ok(data, manual),
                  on_fail=lambda exc: self._on_list_fail(exc, manual))

    def _on_list_ok(self, data: dict, manual: bool) -> None:
        generated_at = data.get("generated_at") or ""
        if generated_at:
            self._server_date = generated_at[:10]
        incoming = TriageClient.parse_items(data)

        if not self._last_generated_at:
            # 首屏：整表替换
            self._items = incoming
        else:
            # 增量：就地替换/追加，绝不重排服务端顺序
            for new_item in incoming:
                idx = next((i for i, it in enumerate(self._items)
                            if it.student_id == new_item.student_id), -1)
                if idx >= 0:
                    new_item.today = self._items[idx].today   # 保留抽屉缓存
                    self._items[idx] = new_item
                else:
                    self._items.append(new_item)
        if generated_at:
            self._last_generated_at = generated_at

        self._fail_count = 0
        self.banner.clear()
        self._mark_synced()
        self._render_rows()
        if manual:
            self._restore_refresh_btn()

    def _on_list_fail(self, exc: Exception, manual: bool) -> None:
        if isinstance(exc, ApiError) and exc.code == 1001 and self.ctx.on_auth_fail:
            self.ctx.on_auth_fail("登录状态已过期，请重新登录")
            return
        self._fail_count += 1
        self.banner.set_message("暂时连不上服务端，名单可能不是最新（可继续查看已加载内容）")
        if manual:
            self._restore_refresh_btn()
        # 失败也重置倒计时，让退避间隔立即生效
        self._seconds_left = self._current_interval()

    def _restore_refresh_btn(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("刷新")

    # ------------------------------------------------------------------ 渲染
    def _render_rows(self) -> None:
        # 清旧行
        while self.rows_box.count() > 1:
            item = self.rows_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        has_rows = bool(self._items)
        self.placeholder.setVisible(not has_rows)
        self.rows_scroll.setVisible(has_rows)

        for item in self._items:
            row = StudentRow(item, self._server_date)
            row.set_selected(item.student_id == self._selected_id)
            row.picked.connect(self._select_student)
            self.rows_box.insertWidget(self.rows_box.count() - 1, row)

    def _select_student(self, student_id: str) -> None:
        self._selected_id = student_id
        # 更新选中底色（不整表重建，保留滚动位置）
        for i in range(self.rows_box.count()):
            w = self.rows_box.itemAt(i).widget()
            if isinstance(w, StudentRow):
                w.set_selected(w.student_id == student_id)

        item = self._find_item(student_id)
        if item is None:
            return
        if item.today is not None:
            self.drawer.render(item)
            return

        self.drawer.show_hint("加载中…")
        self.call(self.client.student_today, student_id,
                  on_ok=lambda data: self._on_today_ok(student_id, data),
                  on_fail=lambda exc: self._on_today_fail(student_id, exc))

    def _on_today_ok(self, student_id: str, data: dict) -> None:
        item = self._find_item(student_id)
        if item is None:
            return
        item.today = TriageClient.parse_today(data)
        if self._selected_id == student_id:
            self.drawer.render(item)

    def _on_today_fail(self, student_id: str, exc: Exception) -> None:
        if isinstance(exc, ApiError) and exc.code == 1001 and self.ctx.on_auth_fail:
            self.ctx.on_auth_fail("登录状态已过期，请重新登录")
            return
        if self._selected_id == student_id:
            self.drawer.show_hint(getattr(exc, "message", "暂时拿不到这位同学的当日情况"))

    # ------------------------------------------------------------------ 工单 ack
    def _on_ticket_action(self, ticket_id: str, action: str) -> None:
        def _ok(_data):
            # 刷新抽屉详情 + 全量同步名单（chips 的求助待处理要消掉）
            student_id = self._selected_id
            if student_id:
                item = self._find_item(student_id)
                if item is not None:
                    item.today = None
                self.call(self.client.student_today, student_id,
                          on_ok=lambda d: self._on_today_ok(student_id, d),
                          on_fail=lambda e: self.drawer.show_hint(
                              getattr(e, "message", "操作已提交，但详情刷新失败")))
            self._load_list(full=True)

        def _fail(exc):
            self.banner.set_message(getattr(exc, "message", "操作没成功，稍后再试一次"))
            # 用旧数据重渲染，把按钮还原给老师重试（绝不自动重发）
            item = self._find_item(self._selected_id or "")
            if item is not None:
                self.drawer.render(item)

        self.call(self.client.ack_ticket, ticket_id, action, None,
                  on_ok=_ok, on_fail=_fail)

    # ------------------------------------------------------------------ 轮询心跳
    def _tick(self) -> None:
        if not self._synced:
            return
        self._ago_seconds += 1
        self._seconds_left -= 1
        if self._seconds_left <= 0:
            self._load_list(full=False)
            # _on_list_ok 会按当前退避重置；失败路径同样重置
            self._seconds_left = self._current_interval()
        self._update_sync_labels()

    def _current_interval(self) -> int:
        """连续失败退避：>=3 次失败 60s，>=6 次 120s；成功后回到 30s。"""
        if self._fail_count >= 6:
            return POLL_BACKOFF_STEPS[2]
        if self._fail_count >= 3:
            return POLL_BACKOFF_STEPS[1]
        return POLL_SECONDS

    def _mark_synced(self) -> None:
        self._synced = True
        self._ago_seconds = 0
        self._seconds_left = self._current_interval()
        now_text = datetime.now().strftime("%H:%M:%S")
        self.sync_label.setText(f"最后同步：{now_text}")
        self._update_sync_labels()

    def _update_sync_labels(self) -> None:
        if self._synced:
            self.ago_label.setText(f"距离上次成功同步 {self._ago_seconds} 秒")
            self.countdown_label.setText(
                "马上刷新" if self._seconds_left <= 3
                else f"下次刷新 {self._seconds_left}s")
        else:
            self.ago_label.setText("尚未同步")
            self.countdown_label.setText("")

    # ------------------------------------------------------------------ 工具
    def _find_item(self, student_id: str) -> Optional[TriageItem]:
        return next((it for it in self._items if it.student_id == student_id), None)
