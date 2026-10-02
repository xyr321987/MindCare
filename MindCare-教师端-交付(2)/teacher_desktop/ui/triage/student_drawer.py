# -*- coding: utf-8 -*-
"""学生抽屉：单个学生当日情况（迁移 教师端3.html 右侧抽屉）。

内容顺序与原型一致：
标题/日期 → 心情圆点行 → 预警卡（左珊瑚竖线）→ 求助工单操作 → 心里话（masked 占位）。

纪律：
- ticket_id 只认服务端给的值（契约缺口 G-1：没有 id 就显示占位，绝不伪造）；
- POST ack 非幂等：点击立刻禁用按钮，失败才由页面还原，绝不自动重发；
- masked 固定占位话术，不做任何推断文字。
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from desktop_common.widgets import (
    make_button, make_label, wrap_scroll,
)

from ...core import enums
from ...core.models import StudentToday, TriageItem

#: 心情值 → 圆点 objectName（颜色只在 QSS 里）
_MOOD_DOT_NAME = {
    "happy": "MoodDotHappy", "plain": "MoodDotPlain",
    "down": "MoodDotDown",
}


class StudentDrawer(QFrame):
    """右侧 380px 抽屉。ack 动作通过 ticket_action 信号交给页面走后台线程。"""

    ticket_action = Signal(str, str)   # ticket_id, action(accept/done)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Drawer")
        self.setFixedWidth(384)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._content = QWidget()
        self._content.setObjectName("DrawerContent")
        self._box = QVBoxLayout(self._content)
        self._box.setContentsMargins(20, 20, 20, 20)
        self._box.setSpacing(14)

        self._scroll = wrap_scroll(self._content, self)
        self._scroll.setObjectName("DrawerScroll")
        outer.addWidget(self._scroll)

        self.show_hint("在左边选一个学生，看看他今天怎么样")

    # ------------------------------------------------------------------ 状态切换
    def show_hint(self, text: str) -> None:
        self._rebuild()
        self._box.addStretch(1)
        hint = make_label(text, "DrawerHint")
        hint.setAlignment(Qt.AlignCenter)
        self._box.addWidget(hint)
        self._box.addStretch(2)

    def render(self, item: TriageItem) -> None:
        """按 item.today 渲染；today 还没拉到时显示加载文案。"""
        today = item.today
        if today is None:
            self.show_hint("正在拉取这位同学的当日情况…")
            return
        self._rebuild()

        # ---- 标题区
        self._add_label(f"{item.name} · {item.class_name}", "DrawerTitle")
        self._add_label(f"当日状态（{today.date}）", "DrawerHint")

        # ---- 心情行
        mood_hit = enums.MOOD.get(today.mood_latest or "")
        mood_text = mood_hit[0] if mood_hit else enums.MOOD_NONE_TEXT
        dot_name = _MOOD_DOT_NAME.get(today.mood_latest or "", "MoodDotNone")
        mood_row = QHBoxLayout()
        mood_row.setSpacing(8)
        dot = QLabel()
        dot.setObjectName(dot_name)
        mood_row.addWidget(dot)
        mood_row.addWidget(make_label(mood_text, "Body", word_wrap=False))
        mood_row.addStretch(1)
        mood_row.addWidget(make_label(f"今日填写 {today.submission_count_today} 次",
                                      "DrawerHint", word_wrap=False))
        self._box.addLayout(mood_row)

        # ---- 预警卡
        if today.alert:
            self._box.addWidget(self._build_alert_card(today))

        # ---- 求助工单
        if today.pending_help or today.tickets:
            self._add_label("求助工单", "SectionCaption")
            actionable = [t for t in today.tickets if t.status in ("pending", "accepted")]
            if actionable:
                for ticket in actionable:
                    action = "accept" if ticket.status == "pending" else "done"
                    label = "受理" if ticket.status == "pending" else "标记完成"
                    btn = make_button(label, object_name="AccentButton")
                    btn.clicked.connect(lambda _=False, tid=ticket.ticket_id,
                                        a=action, b=btn: self._on_ack(b, tid, a))
                    self._box.addWidget(btn)
            else:
                self._add_label("求助受理功能待服务端补齐工单号后开放", "DrawerHint")

        # ---- 心里话：masked 占位 / 授权分享的记录（含共享树洞，v1.1）
        if not today.has_shared_records:
            masked = make_label(enums.MASKED_TEXT, "MaskedText")
            masked.setAlignment(Qt.AlignCenter)
            self._box.addSpacing(6)
            self._box.addWidget(masked)
        else:
            if today.shared_records:
                self._add_label("愿意分享的心里话", "SectionCaption")
                for record in today.shared_records:
                    self._box.addWidget(self._build_record_card(record))
            if today.shared_treehole:
                self._add_label("愿意分享的树洞", "SectionCaption")
                for entry in today.shared_treehole:
                    self._box.addWidget(self._build_treehole_card(entry))

        self._box.addStretch(1)

    # ------------------------------------------------------------------ 卡片构造
    def _build_alert_card(self, today: StudentToday) -> QFrame:
        card = QFrame()
        card.setObjectName("AlertCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        lay.addWidget(make_label("可以多一点关注", "CardTitle"))
        rule_text = enums.ALERT_RULE.get(today.alert.rule, "近期需要多一点关注")
        lay.addWidget(make_label(rule_text, "Body"))
        lay.addWidget(make_label(
            f"近期低落 {today.alert.recent_down_count} / {today.alert.window_size} 次",
            "DrawerHint"))
        return card

    def _build_record_card(self, record) -> QFrame:
        card = QFrame()
        card.setObjectName("DrawerCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        mood_hit = enums.MOOD.get(record.mood or "")
        head = (f"{enums.short_time(record.ts)} · "
                f"{mood_hit[0] if mood_hit else '未填写'}")
        if record.cause_category:
            head += f" · 原因：{enums.CAUSE.get(record.cause_category, '未说明')}"
        lay.addWidget(make_label(head, "DrawerHint"))
        lay.addWidget(make_label(record.detail or "", "Body"))
        return card

    def _build_treehole_card(self, entry) -> QFrame:
        card = QFrame()
        card.setObjectName("DrawerCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        lay.addWidget(make_label(
            f"{enums.short_time(entry.get('ts', ''))} · 树洞", "DrawerHint"))
        lay.addWidget(make_label(entry.get("content") or "", "Body"))
        return card

    # ------------------------------------------------------------------ 内部工具
    def _on_ack(self, button: QPushButton, ticket_id: str, action: str) -> None:
        # 非幂等：立刻禁用，处理中不给第二次点击机会（失败由页面重渲染还原）
        button.setEnabled(False)
        button.setText("处理中…")
        self.ticket_action.emit(ticket_id, action)

    def _add_label(self, text: str, object_name: str) -> QLabel:
        label = make_label(text, object_name)
        self._box.addWidget(label)
        return label

    def _rebuild(self) -> None:
        while self._box.count():
            item = self._box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先 hide：deleteLater 依赖事件循环派发，避免旧控件短暂残画
                widget.hide()
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        # 清掉旧的 stretch 项后重新开始
        self._box.invalidate()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
