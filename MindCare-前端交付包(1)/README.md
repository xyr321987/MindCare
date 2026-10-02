# MindCare · 前端交付包（学生端桌面应用）

> 打包时间：2026-10-02　｜　底座契约：**v1.0（11 个端点）**
> 本包**只含前端**（学生端桌面应用 + 双端共享包 + 文案表）。服务端**不在包内**——它是**给定的 API**，
> 由后端队友维护，我方只调用、未改动。

---

## 0. 一分钟跑起来

### 前置：先有一个 v1.0 服务端在跑

```powershell
# 在【服务端仓库】里另开一个窗口（本包不含服务端）
$py = 'C:\Users\cu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = '<服务端仓库路径>'
& $py -m server.api.httpd --engine mock --port 8080 --days 7 --data-dir "$PWD\data"
```

探活：浏览器或 `curl` 打开 `http://127.0.0.1:8080/api/v1/health`，应返回
`{"code":0,...,"data":{"status":"ok","version":"1.0.0","engine_ready":true}}`。

> ⚠️ **`--days` 必须给**。不给的话 mock 引擎不灌种子，登录能成功但档案/树洞全是空的
> （实测踩过：我第一次复现安全问题时因漏了这个参数，误以为"读不到树洞"）。

### 然后：启动学生端

**方式 A（推荐）**：双击

```
student-desktop\start-student.cmd
```

它自己会找 Python、设好环境变量、打印后端启动命令，然后开窗口。

**方式 B（手动）**

```powershell
$py = 'C:\Users\cu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Set-Location '<本包的父目录>\MindCare-前端交付包'      # 即本 README 所在目录

$env:PYTHONUTF8 = '1'                                  # ⚠️ 必须，见 §4
$env:PYTHONPATH = "$PWD;$PWD\student-desktop"          # ⚠️ 必须两段都加，见 §4
& $py -m student_desktop.app.main --server http://127.0.0.1:8080
```

**演示学号**：`stu_2023001` ~ `stu_2023012`（纯数字 `2023001` 也行，输入框会自动补 `stu_` 前缀）。
两名学生有病史标记：`stu_2023002` / `stu_2023007`。

---

## 1. 包内有什么

```
MindCare-前端交付包/
├── README.md                    ← 本文件
├── copywriting.md               ← 文案表（源，点分 ID，由内容负责人维护）
├── copywriting.json             ← 文案表（运行时，界面从这里读）
├── desktop_common/              ← 双端共享包（⚠️ 见 §3 owner 约定）
│   ├── theme.py                 ← 调色板 + build_qss()
│   ├── api.py                   ← ApiClient：信封解包 / 错误码 / 幂等重试 / 时间格式化
│   ├── widgets.py               ← 基础控件
│   ├── models.py                ← 数据类与 result_scene 枚举
│   ├── copy.py                  ← 文案表门面（COPY["s.q1.title"]）
│   ├── copy_text.py             ← ⚠️ 自动生成物，不要手改
│   └── session.py               ← 登录态持久化
├── student-desktop/
│   ├── start-student.cmd        ← 一键启动
│   ├── README.md                ← 学生端说明（含降级丢失能力清单）
│   ├── DELIVERY-报告-*.md        ← 交付报告（含已知缺陷与修复记录）
│   ├── student_desktop/
│   │   ├── app/main.py          ← 入口：主窗 + 2 层 Tab + 登录
│   │   ├── app/worker.py        ← QThreadPool 异步（主线程不发网络请求）
│   │   ├── app/selfcheck.py     ← 自检（107 项）
│   │   └── ui/{pages,questionnaire,profile,treehole}.py
│   ├── tools/{evidence,live_demo}.py
│   └── student_desktop/__screenshots__/   ← 10 张界面实拍 + 自检全文
├── tools/gen_copy_text.py       ← 从 copywriting.md/json 生成 copy_text.py
├── ui-preview/index.html        ← 界面预览画廊（图片已内嵌，单文件可拷走）
└── docs/
    ├── api-contract.md/.json    ← **给定的 API 契约**（只读参考，v1.0）
    ├── UI约定.md                 ← UI 冻结约定（主题 / ApiClient / 页面结构 / offscreen 验收）
    ├── 权限审计-v1.0.md           ← 独立渗透测试报告（**后端问题在这里**）
    ├── 审计独立复验记录.md         ← 主 agent 对审计结论的独立复现
    ├── 答辩与演示剧本.md           ← 9 步演示 + 20 个问答口径
    ├── 卖点可行性核对.md           ← 哪些话不能说（失实风险点名）
    └── 转向决策记录-v2.md         ← 为什么从 v1.1 降级到 v1.0
```

---

## 2. 跑自检（改完代码请跑一遍）

```powershell
$py = 'C:\Users\cu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Set-Location '<本包目录>'
$env:QT_QPA_PLATFORM = 'offscreen'          # 无头截图用；要看真窗口就不要设
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$PWD;$PWD\student-desktop"

# 需要后端在跑（会真的发请求）
& $py -m student_desktop.app.selfcheck --server http://127.0.0.1:8080     # 期望 107/107

# 不需要后端
& $py -m student_desktop.app.selfcheck --skip-network                     # 期望 87/87
```

自检会：构建完整控件树、断言 107 项、**重新生成 10 张截图**，并自动重写
`__screenshots__/manifest.txt` 与 `selfcheck_output.txt`（这两份是证据，**不要手工改**）。

> ⚠️ **`--server` 的坑（已修，但要知道）**：`check_ui` 曾把 base_url **硬编码**成 `127.0.0.1:8080`，
> 而联调段只换传输层不改 base_url → `--server` 不生效。后果是：**只要 8080 上碰巧有别的服务在跑，
> 自检就会"绿"**（打的是别人的服务）。现已修为 `check_ui(app, server=...)`。
> **跑自检前确认 8080 上跑的正是你要测的那个服务**。

---

## 3. 约定与纪律

| 项 | 约定 |
|---|---|
| **`desktop_common/` owner** | 学生端。教师端**只读引用**，需要改动请提出来——**不要各写一套 QSS 或一套 HTTP 客户端** |
| **文案** | 界面里**只写 ID**，不硬编码中文：`COPY["s.q1.title"]`。缺键请登记，不要就地写死 |
| **改文案** | 改 `copywriting.md`（点分 ID）→ 跑 `python tools/gen_copy_text.py` → `--check` 校对 |
| **主题** | 两个应用都调 `theme.build_qss()`；正文对比度 ≥ 4.5:1；主色雾蓝 `#A8C5D6` **只做底、不做字** |
| **网络** | 一律走 `QThreadPool`，**主线程不发请求**（自检会断言） |
| **幂等键** | `record_id`/`entry_id` 由客户端生成，超时重试**沿用同一个** |

---

## 4. 两个必踩的环境坑（都实测过）

**① `PYTHONPATH` 必须加两段。** `student-desktop` 目录名含连字符，**不是合法的 Python 包名**，
所以 `desktop_common` 与 `student_desktop` 要同时可导入：

```powershell
$env:PYTHONPATH = "$PWD;$PWD\student-desktop"
```

**② 控制台必须 UTF-8。** 自检会打印 `↔` 等字符，GBK 控制台下会抛
`UnicodeEncodeError: 'gbk' codec can't encode character '\u2194'`，**自检结果不可信**：

```powershell
$env:PYTHONUTF8 = '1'
```

> 另外：**`.cmd` 文件里不要写中文**。cmd 以 GBK 解析 UTF-8 文件时，中文注释会破坏解析
> （实测：一个中文 `rem` 就让后面的 `set` 都不被识别）。`start-student.cmd` 因此**刻意纯 ASCII**。

---

## 5. 已知差距（诚实清单，**别当已实现讲**）

| 差距 | 说明 |
|---|---|
| 🔴 **学生登录零认证** | 契约 `§2.1` 规定 `password: null` → **凭证就是学号**。实测零凭证可读到任意学生树洞私密正文。**属契约设计问题**；对**教师**的隔离是成立的（接口层无教师读树洞路由） |
| 🔴 **幂等键不校验归属** | 问卷 `record_id` / 树洞 `entry_id` 全局判重、不校验 owner → 存在性/情绪预言机、树洞回显他人 `ts`、**预占 id 可静默吞掉他人的求助**。**属后端实现问题**（`docs/权限审计-v1.0.md`） |
| **无撤回同意机制** | v1.0 无该端点 → 学生选择分享后无法反悔（PIPL 第 15 条） |
| **教师端不在本包** | 由其他队友负责；`/triage/*` 三个端点服务端已实现且有测试 |
| **数据未加密** | 明文 JSON Lines 落盘；token 表亦为明文 |
| **mock 引擎不落盘** | `--engine mock` 是内存态，**重启服务 = 演示数据归零**；要持久化用 `--engine real` |

> 📌 **答辩/汇报口径**：可以说「引擎四条验收全过、契约测试双目标全绿、**树洞对教师不存在任何读取路由**、
> 界面文案 100% 来自文案表、对比度实测达标」；
> **不可说**「认证安全」「数据已加密」「v1.0 已通过渗透测试」「撤回链路已实现」。

---

## 6. 依赖

- **Python** 3.12（本机实测 3.12.14）
- **PySide6**（本机实测 6.11.2）—— **唯一的第三方依赖**
- HTTP 只用标准库 `urllib`，**不需要** `httpx`/`requests`
- 无图形界面时（CI）设 `QT_QPA_PLATFORM=offscreen`

---

## 7. 最近一次验证结果（本包内容对应这次）

```
前端完整自检（--server 8090）      107 / 107   exit 0（连跑 2 次）
前端自检（--skip-network）          87 /  87   exit 0
后端引擎单测                        31 passed
后端契约测试                        63 passed (mock) + 63 passed (real)
服务端是否被前端改动                48/48 文件逐字节一致（未改动）
```

截图 10 张：`01_login` … `10_about`（均 1080×760，offscreen 实拍）。
