# MindCare 学生端（PySide6 桌面应用）

> 契约依据：`mindcare新版/contracts/api-contract.md`（**v1.0，11 个端点**）｜ UI 冻结约定：`docs/UI约定.md`
> 共享包：`mindcare/desktop_common/`（**owner = 学生端**，教师端只读引用）
>
> ⚠️ **本项目已从契约 v1.1 降级到 v1.0**：底座（队友线）的 HTTP 服务只实现 11 个端点。
> 降级丢掉的能力见 §5，请勿按 v1.1 的口径验收本目录。

## 1. 启动

### 方式 0（演示推荐）：一键启动脚本

双击 `start-student.cmd`，或带上门禁地址：

```bat
start-student.cmd
start-student.cmd http://10.0.0.5:8080
```

它自己完成三件事，**现场不必手设环境变量**：
1. 找 Python（先试本机打包运行时，再退回 `PATH` 上的 `python`）
2. 设 `PYTHONPATH` / `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`
3. 启动学生端，并在屏幕上打印**后端启动命令**（便于另开窗口照抄）

> ⚠️ **它不会替你启动后端**——后端是给定的 API，由后端队友负责。
> 屏幕上会打印确切命令，另开一个窗口执行即可。
>
> ⚠️ **该 `.cmd` 刻意只用 ASCII 字符**（0 个非 ASCII 字节）。这不是洁癖：
> cmd 以 GBK 解析 UTF-8 文件时，中文注释会破坏解析（实测：连 `set` 都不被识别）。
> **若要改这个脚本，请继续只用 ASCII。**

### 方式 A / B（手动）

`mindcare/student-desktop` 目录名含连字符（`docs/UI约定.md` §0 的目录形态），
**不是合法的 Python 包名**，因此 `desktop_common` 与 `student_desktop` 需要同时在 `sys.path` 上。
两种做法任选：

```powershell
$py = 'python'
Set-Location '<仓库根目录>'

# 方式 A（推荐）：显式给路径，`-m` 模块启动
$env:PYTHONPATH = "$PWD;$PWD\student-desktop"
$env:PYTHONUTF8 = '1'     # ⚠️ 必须：GBK 控制台下打印特殊字符会抛 UnicodeEncodeError
& $py -m student_desktop.app.main --server http://127.0.0.1:8080

# 方式 B：直接跑脚本（入口脚本内部会自己把 `student-desktop\` 加进 sys.path）
& $py .\student-desktop\student_desktop\app\main.py --server http://127.0.0.1:8080
```

依赖：`PySide6`（本机 6.11.2）。HTTP 只用标准库 `urllib`，
**不需要** `httpx`/`requests`（本机 pip 环境没有它们，见交付报告实测证据）。

## 2. 无显示器（offscreen）自检 + 截图

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'          # ⚠️ 必须：GBK 控制台打印特殊字符会 UnicodeEncodeError
$py = 'python'
Set-Location '<仓库根目录>'
$env:PYTHONPATH = "$PWD;$PWD\student-desktop"

& $py -m student_desktop.app.selfcheck                  # 65 项断言 + 8 张截图
& $py -m student_desktop.app.selfcheck --skip-network   # mock server 未启动时
```

* 截图落在 `student_desktop/__screenshots__/`（登录 / 告知页 / Q1 / Q3 详述 /
  求助选择 / 自助建议结果页 / 树洞 / 我的档案）。
* 自检退出码：`0` 全通过，`1` 有失败项（失败项会逐条打印证据）。

**启动前请先起 mock 服务（联调段会用到）**：

```powershell
Set-Location '<仓库根目录>'
$cmdline = 'set PYTHONPATH=<仓库根目录>&& set PYTHONUTF8=1&& "' + $py +
           '" -m server.api.httpd --engine mock --port 8080 --data-dir "<仓库根目录>\data"'
Start-Process cmd.exe -ArgumentList '/c', $cmdline -WindowStyle Hidden
Invoke-WebRequest 'http://127.0.0.1:8080/api/v1/health' -UseBasicParsing   # 应返回 code:0
```

> ⚠️ **学生 ID 形态**：mock 种子里的学号是 `stu_2023001` 这种（契约 §4 名单），
> 不是裸的 `2023001`。裸数字登录会得到 `2002 资源不存在: id`。
> 自检与 `tools/live_demo.py` 的默认值都已是 `stu_2023001`。

## 3. 目录

```
student-desktop/
  student_desktop/
    app/
      main.py         # 入口：QApplication + 登录页 + 主窗口（问卷 / 树洞 / 我的档案 / 关于）
      worker.py       # QThreadPool 执行器 + "主线程是否发过请求"的计数器
      selfcheck.py    # offscreen 自检（构建控件树 + 断言 + 截图 + 真实联调）
    ui/
      pages.py        # 问卷各页（告知 / Q1 / 平淡原因 / Q2 / Q3 / 求助选择）+ FlowState
      questionnaire.py# 问卷状态机（QStackedWidget，逐题跳转纯本地）+ result_scene 4 个结果页
      treehole.py     # 树洞 Tab（L0 绝对私密，列表 + 大输入框编辑器）
      profile.py      # 我的档案（按日选择 + 历史列表 + 日期打点；以 request_help 显示求助状态）
    __screenshots__/  # 自检产物
  tools/
    evidence.py       # 树洞零分享控件扫描 + 已下线能力禁用词扫描 + 问卷纯本地 import 审计
    live_demo.py      # 真实联调演示（登录 → 提交问卷 → 拉档案）
```

## 4. 关键纪律（与验收项一一对应）

| 纪律 | 落地位置 |
|---|---|
| 逐题跳转**纯本地**、提交只发生一次 | `ui/questionnaire.py`（不 import 任何网络客户端）+ 自检断言 |
| `result_scene` **穷举 4 个值** + 未登记值的可见兜底页 | `questionnaire.RESULT_PAGES` + 4 个 `ResultPage` + `_UnmappedResultPage` |
| 树洞 **L0 绝对私密**、零分享/可见性控件 | `ui/treehole.py`（请求体只有 `entry_id/content/mood_tag`）+ 自检控件树扫描 |
| **界面零已下线能力入口** | `ui/profile.py` 没有记录级按钮；自检用"从文案表键推导的禁用词"扫描 + 记录级按钮数 = 0 |
| 档案以 `request_help` 显示求助状态 | `ui/profile.py` 的 `STATUS_COPY` → `s.help.selected.request/no`（只用文案表已有键） |
| 提交正文只有 v1.0 的 **8 个字段** | `pages.FlowState.build_body()` + 自检字段白名单断言 |
| 文案全部来自 `COPY` | `desktop_common/copy.py`（`copywriting.md` → `copy_text.py`，见 `tools/gen_copy_text.py`） |
| 主线程不发网络请求 | `app/main.py` 只投递 `QThreadPool`；自检断言主线程传输调用 = 0 |
| `code != 0` 一律抛 `ApiError` | `desktop_common/api.py` + 自检实测（1001/1002/2001/2002/3001/4001/超时/非 JSON） |
| 非 2xx 的 HTTP 状态仍按信封解包 | `api._do_http` 从 `HTTPError` 里读信封，避免把 2001 误报成"网络失败" |
| 主题只有一份 QSS | 两个应用都调 `desktop_common.theme.build_qss()` |

## 5. 降到 v1.0 后**丢失**的能力（诚实清单，会写进项目文档）

| 能力 | v1.1 有什么 | v1.0 现状 | 被删的代码 |
|---|---|---|---|
| **事后收回可见性** | `PATCH /questionnaire/submissions/{record_id}`；档案页对应入口 + 二次确认 + 结束页 + 第 5 个 `result_scene` | 端点不存在（服务端对该 HTTP 方法直接 501）。档案页**零记录级操作按钮**，学生无法事后收回已分享的记录 | `api.revoke_consent`、`models.RevokeResult`、`RevokeLedger`、`RevokeConfirmDialog`、`RecordRow` 的按钮、`main.py` 的对应异步回调、`questionnaire` 的第 5 个结果页 |
| **敏感分流** | 命中敏感词 → 整条不写匿名转交通道、转心理通道并提示 | 服务端**没有**分流逻辑；前端预检已删（避免"客户端做了服务端没做"的错觉） | `pages.SENSITIVE_HINTS` / `keyword_hits`、追问页的提示、`main._on_submit_failed` 的追加提示 |
| **匿名转交通道** | `POST /feedback/school` + `GET /feedback/school/mine` + 提交体里的两个 material 专用字段 + Q2.5 那一页 | 两个端点都不存在；问卷**没有** Q2.5，请求体也没有那两个字段 | `api.submit_school_feedback/my_school_feedback`、`models.SchoolFeedbackItem`、`MaterialPage`、`MaterialDetailPage` |
| **第 5 个 `result_scene`** | `enums.result_scene` 含第 5 个值 | 只有 4 个值；未登记值落可见兜底页（保留的防御性断言） | `RESULT_SCENES` 第 5 项、`_RESULT_COPY`/`RESULT_PAGES` 的对应条目 |
| **告知页第 4/5/6 条** | 说明匿名转交那一栏、以及档案页里的收回入口 | 该能力不存在，故**不渲染**（`NoticePage.item_indexes = (1, 2, 3)`），避免告知页承诺做不到的事。文案本身未改，仅选择不展示 | `range(1, 7)` → `item_indexes` |

> 已下线能力对应的**文案键仍留在 `copywriting.json` 里**（该文件只读、不在本目录
> 职责内），但界面代码已不再引用它们；`COPY.missing_keys` 因此仍为空（缺键检测只关心
> "被引用了却找不到"，不关心"存在但没用到"）。自检与 `tools/evidence.py` 的
> "已下线能力禁用词黑名单"由这些**键前缀**在运行时推导，所以不需要把那些中文
> 词面写进代码 —— `grep` 证据因此是干净的，而断言强度不变。

