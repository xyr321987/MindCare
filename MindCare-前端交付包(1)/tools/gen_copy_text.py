"""从文案表**生成** `desktop_common/copy_text.py`（构建期工具，运行时不需要 md）。

## 为什么需要这个脚本

`docs/UI约定.md` §4 规定"任何面向用户的中文文案都必须来自 `copywriting.json`"，
而 `mindcare/copywriting.md` §0 规定"代码里只写 ID，不硬编码文案"。
但两份事实源**键名口径不同**：

* `mindcare/copywriting.md` 用**点分 ID**（`s.q1.title`、`s.revoke.confirm.irreversible` …），
  共 200+ 条，是内容负责人维护的**完整**文案表；
* `mindcare/copywriting.json` 只有 **13 个运行时键**
  （`plain` / `down` / `self_care` + `plain_tips` / `down_tips` / `self_care_page` /
  `happy_end` / `help_sent` / `revoke` / `disclosure` / `teacher_placeholder` /
  `priority_labels` / `errors` / `hotlines`），是 C 的 `/tips` 数据源。

**缺的不是"几个键"，而是 md 的全部 ID 在 JSON 里都没有**（实测缺口见交付报告）。
因此本脚本按 `docs/接口约定.md` §5 的**方案 2**（"B 编辑 .md，另写脚本转 JSON"）
把 md 的表格解析成一份 Python 常量，供界面按 ID 取用 —— 单一事实源仍是
`copywriting.md`，**没有一条中文是在 Python 里手写的**。

## 覆盖（override）

`mindcare/copywriting.md` 的链接行同步少数键时**用词与 JSON 不同**
（例：`plain` 在 md 里是直引号 `"应该开心"`，JSON 里是 `「应该开心」`）。
`/tips` 接口实际返回 JSON 的版本，界面必须显示**接口给的那份**，
故 `OVERRIDES` 把 JSON 的键覆盖到对应 ID（运行时读 JSON，不是把 JSON 抄进代码）。

用法::

    python tools/gen_copy_text.py            # 生成/刷新 desktop_common/copy_text.py
    python tools/gen_copy_text.py --check    # 只校对：ID 覆盖、override 目标是否存在
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# 工作根 = mindcare/（本文件在 mindcare/tools/ 下）
ROOT = Path(__file__).resolve().parent.parent
COPY_MD = ROOT / "copywriting.md"
COPY_JSON = ROOT / "copywriting.json"
OUT_PY = ROOT / "desktop_common" / "copy_text.py"

#: 表格行：`| s.q1.title | 你现在的心情怎么样？ |`
_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z][\w.]*)\s*\|\s*(.*?)\s*\|\s*$")

#: 只接受这几类 ID 前缀（文案表 §0 的场景映射）
_ID_PREFIXES = ("s.", "t.", "c.")

#: `_meta.word_ban` 里的禁用词 —— 生成的文案**一个都不许命中**
WORD_BAN = ("抑郁", "焦虑", "障碍", "症状", "重度", "高危", "预警", "异常", "患者", "受试者")

#: 文案表未列、但界面确实需要的少量 ID（**不是文案改写，是登记缺口**）。
#:
#: ✅ 2026-10-02：原先登记在这里的 6 条（`c.login.demoNote` / `c.login.studentNo` /
#: `c.login.action.submit` / `c.tab.questionnaire` / `c.tab.profile` / `c.tab.about`）
#: **已正式收录进 `copywriting.md` §4.6**，故从本表移除 —— 同一文案两处维护必然漂移。
#:
#: ⚠️ 以后若再出现"界面需要、文案表没有"的键，**先登记在这里**并在交付报告里列出，
#: 由内容负责人收录；**不要就地写死中文**。收录后请把对应条目从这里删掉。
EXTRA_TEXT: Dict[str, str] = {}

#: `ID -> JSON 键路径`：md 与 JSON 同一条文案时**以 JSON 为准**（运行时读 JSON）。
OVERRIDES: Dict[str, Tuple[str, ...]] = {
    "s.end.plain.tips": ("plain_tips", "text"),
    "s.end.selfcare.tips": ("down_tips", "text"),
    "s.end.selfcare.title": ("self_care_page", "title"),
    "s.end.selfcare.body": ("self_care_page", "body"),
    "s.end.selfcare.action.treehole": ("self_care_page", "treehole_action"),
    "s.end.selfcare.action.close": ("self_care_page", "close_action"),
    "s.end.selfcare.hotline.title": ("self_care_page", "hotline_title"),
    "s.end.selfcare.hotline.body": ("self_care_page", "hotline_line"),
    "s.end.happy.title": ("happy_end", "title"),
    "s.end.happy.body": ("happy_end", "body"),
    "s.end.help.title": ("help_sent", "title"),
    "s.end.help.body": ("help_sent", "body"),
    "s.revoke.badge.shared": ("revoke", "badge_shared"),
    "s.revoke.badge.revoked": ("revoke", "badge_revoked"),
    "s.revoke.entry.action": ("revoke", "entry_action"),
    "s.revoke.entry.action.revoked": ("revoke", "entry_action_revoked"),
    "s.revoke.entry.hint": ("revoke", "entry_hint"),
    "s.revoke.confirm.title": ("revoke", "confirm_title"),
    "s.revoke.confirm.body": ("revoke", "confirm_body"),
    "s.revoke.confirm.irreversible": ("revoke", "confirm_irreversible"),
    "s.revoke.confirm.keepNote": ("revoke", "confirm_keep_note"),
    "s.revoke.confirm.action.ok": ("revoke", "confirm_ok"),
    "s.revoke.confirm.action.cancel": ("revoke", "confirm_cancel"),
    "s.revoke.toast.done": ("revoke", "toast_done"),
    "s.revoke.toast.doneNote": ("revoke", "toast_done_note"),
    "s.revoke.toast.failed": ("revoke", "toast_failed"),
    "s.revoke.toast.alreadyRevoked": ("revoke", "toast_already_revoked"),
    "s.revoke.toast.notShared": ("revoke", "toast_not_shared"),
    "s.revoke.after.note": ("revoke", "after_note"),
    "s.revoke.after.relink": ("revoke", "after_relink"),
    "s.revoke.error.1002": ("revoke", "errors", "1002"),
    "s.revoke.error.2002": ("revoke", "errors", "2002"),
    "s.revoke.error.2001.notShared": ("revoke", "errors", "2001_not_shared"),
    "s.revoke.error.2001.restore": ("revoke", "errors", "2001_restore"),
    "s.revoke.error.network": ("revoke", "errors", "network"),
    "s.end.revoked.title": ("revoke", "end_page", "title"),
    "s.end.revoked.body": ("revoke", "end_page", "body"),
    "s.end.revoked.reassure": ("revoke", "end_page", "reassure"),
    "s.end.revoked.action.back": ("revoke", "end_page", "back_action"),
    "s.end.revoked.action.close": ("revoke", "end_page", "close_action"),
    "s.end.revoked.footer": ("revoke", "end_page", "footer"),
    "s.end.revoked.hotline": ("revoke", "end_page", "hotline"),
    "s.q25.disclosure.anonymous": ("disclosure", "q25_anonymous"),
    "s.q25.disclosure.materialOnly": ("disclosure", "q25_material_only"),
    "s.q25.sensitive.notice": ("disclosure", "q25_sensitive"),
    "c.error.1001": ("errors", "1001"),
    "c.error.1002": ("errors", "1002"),
    "c.error.2001": ("errors", "2001"),
    "c.error.2002": ("errors", "2002"),
    "c.error.3001": ("errors", "3001"),
    "c.error.4001": ("errors", "4001"),
    "c.error.network": ("errors", "network"),
}

#: `ID -> JSON 键路径`：md 表格里没有、只能来自 JSON 的条目
JSON_ONLY: Dict[str, Tuple[str, ...]] = {
    "c.hotline.national.name": ("hotlines", 0, "label"),
    "c.hotline.national.number": ("hotlines", 0, "number"),
    "c.hotline.beijing.name": ("hotlines", 1, "label"),
    "c.hotline.beijing.number": ("hotlines", 1, "number"),
    "c.hotline.emergency.name": ("hotlines", 2, "label"),
    "c.hotline.emergency.number": ("hotlines", 2, "number"),
    "c.hotline.line": ("self_care_page", "hotline_line"),
}


# --------------------------------------------------------------------------- 解析


def parse_markdown(path: Path = COPY_MD) -> Dict[str, str]:
    """解析 `copywriting.md` 全部两列表格，返回 `{ID: 文案}`。"""
    text = path.read_text(encoding="utf-8")
    out: Dict[str, str] = {}
    duplicates: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        match = _TABLE_ROW.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if not key.startswith(_ID_PREFIXES):
            continue
        if set(value) <= set("-: "):        # 表头分隔行
            continue
        if key in out and out[key] != value:
            duplicates.append(key)
        out.setdefault(key, value)
    if duplicates:
        print(f"[warn] 同一 ID 在 md 中出现多次且文案不同：{sorted(set(duplicates))}",
              file=sys.stderr)
    return out


def _walk_json(data: dict, path: Tuple) -> str:
    node = data
    for step in path:
        if isinstance(step, int):
            node = node[step]
        else:
            node = node[step]
    return str(node)


def build(verbose: bool = True) -> Dict[str, object]:
    """解析 md + JSON，返回生成所需的全部素材（供 `--check` 复用）。"""
    md = parse_markdown()
    data = json.loads(COPY_JSON.read_text(encoding="utf-8"))

    resolved: Dict[str, str] = dict(md)
    resolved.update(EXTRA_TEXT)

    missing_targets: List[str] = []
    for key, path in OVERRIDES.items():
        try:
            resolved[key] = _walk_json(data, path)
        except (KeyError, IndexError, TypeError) as exc:
            missing_targets.append(f"{key} -> {'.'.join(map(str, path))} ({exc})")
    for key, path in JSON_ONLY.items():
        try:
            resolved[key] = _walk_json(data, path)
        except (KeyError, IndexError, TypeError) as exc:
            missing_targets.append(f"{key} -> {'.'.join(map(str, path))} ({exc})")

    banned_hits = [(k, w) for k, v in resolved.items() for w in WORD_BAN if w in v]

    if verbose:
        print(f"md 解析到 ID          : {len(md)} 条")
        print(f"EXTRA_TEXT（登记缺口）: {len(EXTRA_TEXT)} 条")
        print(f"OVERRIDES（取 JSON）  : {len(OVERRIDES)} 条，失败 {len(missing_targets)} 条")
        print(f"JSON_ONLY             : {len(JSON_ONLY)} 条")
        print(f"合计可解析 ID         : {len(resolved)} 条")
        print(f"禁用词命中            : {len(banned_hits)} 条")
        for key, word in banned_hits:
            print(f"  ! {key} 命中 {word}")
        for item in missing_targets:
            print(f"  ! override 目标缺失：{item}")

    return {
        "resolved": resolved, "md": md, "banned_hits": banned_hits,
        "missing_targets": missing_targets, "json": data,
    }


# --------------------------------------------------------------------------- 生成


def render(resolved: Dict[str, str]) -> str:
    lines: List[str] = [
        '"""面向用户的文案（**自动生成，不要手改**）。',
        "",
        "生成命令： `python tools/gen_copy_text.py`",
        "唯一事实源： `mindcare/copywriting.md`（点分 ID）+ `mindcare/copywriting.json`",
        "（`OVERRIDES` / `JSON_ONLY` 的条目运行时读 JSON，见生成器头部说明）。",
        "",
        f"共 {len(resolved)} 条。",
        '"""',
        "from __future__ import annotations",
        "",
        "from typing import Dict",
        "",
        "#: `ID -> 文案`。界面代码只写 ID，不写中文。",
        "TEXT: Dict[str, str] = {",
    ]
    for key in sorted(resolved):
        value = resolved[key].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    "{key}": "{value}",')
    lines.extend(["}", "", '__all__ = ["TEXT"]', ""])
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/gen_copy_text.py",
                                     description="从 copywriting.md/json 生成 copy_text.py")
    parser.add_argument("--check", action="store_true",
                        help="只校对（不写文件）；有问题时返回码 1")
    args = parser.parse_args(argv)

    payload = build()
    resolved = payload["resolved"]
    assert isinstance(resolved, dict)
    banned_hits = payload["banned_hits"]
    missing_targets = payload["missing_targets"]

    if args.check:
        failed = bool(banned_hits) or bool(missing_targets)
        print("校对结果：", "失败" if failed else "通过")
        return 1 if failed else 0

    OUT_PY.write_text(render(resolved), encoding="utf-8")
    print(f"已写入 {OUT_PY}（{len(resolved)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
