# -*- coding: utf-8 -*-
"""教师端自检（离线可跑，不依赖真实服务端）。

用法（在 teacher-desktop/ 目录）：

    python -m teacher_desktop.app.selfcheck

断言内容：
1. 全部模块可编译、可导入；
2. 网关注册表完整性（每个 resource/action 有中文注释）；
3. QSS 纪律检查（无内联 QSS、禁用属性、对比度）；
4. 导出列零正文字段断言；
5. 全控件树无内联 QSS、可点按钮均 StrongFocus。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from desktop_common import theme  # noqa: E402
from desktop_common.widgets import clickable_widgets  # noqa: E402

from ..core.data_gateway import ACTION_REGISTRY, RESOURCE_REGISTRY  # noqa: E402
from ..core.models import ExportRow  # noqa: E402
from ..ui.teacher_qss import build_teacher_qss  # noqa: E402
from .main import AppRoot  # noqa: E402
from .settings import Settings  # noqa: E402

FAILS: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  ✓ " if condition else "  ✗ ") + message)
    if not condition:
        FAILS.append(message)


def pump(app: QApplication, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


# ============================================================ 主流程
def run() -> int:
    print("【1】模块编译与导入")
    import importlib
    import pkgutil
    import teacher_desktop

    modules = []
    for info in pkgutil.walk_packages(teacher_desktop.__path__, "teacher_desktop."):
        modules.append(info.name)
    for name in modules:
        importlib.import_module(name)
    check(True, f"全部 {len(modules)} 个模块可导入")

    print("【2】网关注册表完整性")
    check(len(RESOURCE_REGISTRY) == 13, f"read 资源 13 项（实际 {len(RESOURCE_REGISTRY)}）")
    check(len(ACTION_REGISTRY) == 23, f"write 动作 23 项（实际 {len(ACTION_REGISTRY)}）")
    for key, desc in RESOURCE_REGISTRY.items():
        check(bool(desc.strip()), f"resource {key} 有中文注释")
    for key, desc in ACTION_REGISTRY.items():
        check(bool(desc.strip()), f"action {key} 有中文注释")

    print("【2.5】网关已对接（走 HTTP /db）")
    from ..core.data_gateway import DataGateway
    gateway = DataGateway("http://127.0.0.1:8080")
    try:
        gateway.read("not.registered")
        check(False, "未注册 resource 应抛 ValueError")
    except ValueError:
        check(True, "未注册 resource 拦截正常")
    try:
        gateway.write("not.registered", {})
        check(False, "未注册 action 应抛 ValueError")
    except ValueError:
        check(True, "未注册 action 拦截正常")

    print("【3】样式纪律")
    qss_extra = build_teacher_qss()
    for bad in theme.FORBIDDEN_QSS_PATTERNS:
        check(bad not in qss_extra, f"扩展 QSS 不含禁用属性 {bad}")

    from desktop_common.theme import contrast_ratio
    ink = theme.INK
    for name, bg in [("珊瑚 P1", "#F2B8A0"), ("深珊瑚 P2", "#E39B7F"),
                     ("灰 P3", "#C9C4BD"), ("预警紫底", "#EFEAF6"),
                     ("横幅米底", "#F3EAD9")]:
        check(contrast_ratio(ink, bg) >= 4.5, f"{name} 正文对比度 ≥ 4.5:1")

    print("【4】启动应用（offscreen）")
    app = QApplication(sys.argv)
    theme.install_fonts(app)
    app.setStyleSheet(theme.build_qss() + qss_extra)

    root = AppRoot(Settings())
    root.show()
    pump(app)

    print("【5】登录页渲染")
    login = root.currentWidget()
    check(login.__class__.__name__ == "LoginPage", "启动后进入登录页")
    check(hasattr(login, "work_edit") and hasattr(login, "pwd_edit"), "登录页控件完整")

    print("【5.5】登录页密码错误红字")
    from desktop_common.api import ApiError
    login._on_login_fail(ApiError(1001, "密码错误", "/auth/login", field="password"))
    pump(app)
    check(login.error_label.isVisible(), "密码错误提示可见")
    check(login.error_label.text() == "密码错误", "提示文案为「密码错误」")
    check(login.error_label.objectName() == "Error", "错误标签使用 Error 样式（红字）")

    print("【6】导出零正文字段")
    forbidden_cols = {"detail", "plain_note", "content", "body", "text", "treehole"}
    keys = {k for k, _ in ExportRow.COLUMNS}
    check(not (keys & forbidden_cols), f"导出列零正文字段（列：{sorted(keys)}）")

    print("【7】界面纪律")
    inline = [w for w in root.findChildren(QWidget) if w.styleSheet()]
    check(not inline, f"全控件树无内联 QSS（发现 {len(inline)} 处）")
    weak_focus = [w for w in clickable_widgets(root)
                  if w.focusPolicy() != Qt.StrongFocus]
    check(not weak_focus, f"可点按钮全部 StrongFocus（异常 {len(weak_focus)} 个）")

    print()
    if FAILS:
        print(f"自检未通过：{len(FAILS)} 项")
        for msg in FAILS:
            print(" - " + msg)
        return 1
    print("自检全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(run())
