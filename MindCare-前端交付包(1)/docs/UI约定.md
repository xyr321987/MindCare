# UI 约定（PySide6 双端共享）

> ## ⚠️ 范围变更（2026-10-02）：**本轮只做学生端**
>
> | 项 | 状态 |
> |---|---|
> | 学生端 `mindcare/student-desktop/` | ✅ **本轮交付** |
> | 共享包 `mindcare/desktop_common/` | ✅ **本轮交付**（owner：学生端） |
> | 教师端 `teacher-desktop/` | ⏸ **暂停**，中途归档至 `_archive-teacher-desktop/`（未验收、无截图，**不要当成已完成**） |
>
> **本文档的教师端章节仍然有效**，作为将来复活教师端时的依据；但**本轮不验收**。
> 教师端相关接口（`/triage/*`）**服务端已实现且测试通过**，只是暂无界面消费。

> **本文件是 B 侧两个桌面应用的冻结约定。** 学生端与教师端各自独立开发，但必须共用同一套主题变量、HTTP 客户端与基础控件——否则会出现两套 QSS、两个 HTTP 层，后期无法合并。
> 状态：`冻结 v1.0`　依据：`mindcare新版/contracts/api-contract.md`（**v1.0，11 端点，唯一依据**）、`mindcare新版/docs/学生端接口协议说明.md`、`mindcare/copywriting.md`
>
> ⚠️ **2026-10-02 更新**：底座已切换为队友线 v1.0，我方 v1.1 契约与架构方案已归档至 `_archive-v1-track/`。
> **本文档下文若提到 v1.1 独有的能力**（撤回 `PATCH …/revoke`、校方反馈 `/feedback/*`、`material_related`/`material_detail`、第 5 个 `result_scene`），
> **在当前底座下均不存在**，学生端已相应降级——详见 [docs/转向决策记录-v2.md](转向决策记录-v2.md) §3。

---

## 0. 两个应用的形态

| | 学生端 | 教师端 |
|---|---|---|
| 目录 | `mindcare/student-desktop/` | `mindcare/teacher-desktop/` |
| 主窗口 | `QMainWindow` + **2 个 Tab**（问卷 / 树洞） | 登录窗 → 主窗（分诊台） |
| 入口 | `student-desktop/app/main.py` | `teacher-desktop/app/main.py` |
| 依赖 | `PySide6`、`httpx`（或 `requests`） | 同左 |

**启动方式（必须写进各自 README）**
```powershell
$py = 'python'
Set-Location '<仓库根目录>'
& $py -m student_desktop.app.main --server http://127.0.0.1:8080
& $py -m teacher_desktop.app.main --server http://127.0.0.1:8080
```
> 用 `-m` 模块方式启动，`sys.path` 自然包含 `mindcare/`，因此两个应用都能 `import server.*` 与 `import desktop_common.*`。

---

## 1. 共享包 `mindcare/desktop_common/`（**由一个应用先行落地，另一个只引用**）

```
desktop_common/
  __init__.py
  theme.py       # 调色板 + 尺寸常量 + build_qss()
  api.py         # ApiClient：信封解包、错误码、token
  widgets.py     # 基础控件（按钮/卡片/标签/输入区）
  models.py      # 与契约一致的轻量数据类（可选）
```

**改动规则**：`desktop_common/**` 的 owner 是**学生端 agent**（因为学生端先做完契约里更复杂的状态机）。教师端 agent **只读引用**，需要改动时在报告里提出，不要直接改。

---

## 2. 主题（`theme.py`）

**调色板**（治愈系；**禁止刺眼正红与警示闪烁**）

| 变量 | 值 | 用途 |
|---|---|---|
| `BG` | `#FAF7F2` | 窗口底色（米白） |
| `CARD` | `#FFFFFF` | 卡片面 |
| `INK` | `#3A3A38` | **正文文字**（不用主色写正文） |
| `INK_SOFT` | `#6E6A63` | 次要文字 |
| `LINE` | `#E6E0D6` | 分隔线 |
| `MIST` | `#A8C5D6` | 主色（雾蓝）：**选中态填充、进度条、主按钮底色** |
| `CORAL` | `#F2B8A0` | 辅助色（柔珊瑚）：P1 关注标记的**底色**，不是文字色 |
| `SPROUT` | `#B7D7B9` | 平静/正向 |
| `PRIMARY_INK` | `#2F4A57` | 雾蓝上的文字色（**白字压在雾蓝上对比度不足，用深墨蓝**） |

> ### 与队友规格的差异（2026-10-02 留档）
>
> 队友《开发任务计划》B1-6 给出的色板为：雾蓝 `#A8C5D6` / 珊瑚 `#F2B8A0` / 米白 `#FAF6F0` / 深灰 `#4A4A4A` / 嫩芽绿 `#B7D7B9`。
> 逐项比对结果：
>
> | 色 | 队友 B1-6 | 本实现 | 判定 |
> |---|---|---|---|
> | 雾蓝 `MIST` | `#A8C5D6` | `#A8C5D6` | ✅ 一致 |
> | 珊瑚 `CORAL` | `#F2B8A0` | `#F2B8A0` | ✅ 一致 |
> | 嫩芽绿 `SPROUT` | `#B7D7B9` | `#B7D7B9` | ✅ 一致 |
> | 米白 `BG` | `#FAF6F0` | `#FAF7F2` | ⚠️ 微差（肉眼不可辨） |
> | 深灰 `INK` | `#4A4A4A` | `#3A3A38` | ⚠️ 微差（本实现更深，对比度更高） |
>
> **处置：保留本实现的取值**，理由：① 三主色完全一致，设计语言未偏离；
> ② 本实现的取值已**实测对比度**并写进自检断言（`INK/BG=10.67`、`INK/CARD=11.40`，均远超 AA 的 4.5:1）；
> ③ 改动会令 9 张已验收截图失效，而收益肉眼不可辨。
> **接手者若要求严格对齐 B1-6**：改 `desktop_common/theme.py` 两个常量即可，但需重跑自检并重出截图。

**尺寸**：圆角 ≥ 12px、正文 15–16px、行高 1.6、大留白（卡片内边距 ≥ 20px）。

**硬要求**
1. **对比度**：正文 ≥ 4.5:1。**雾蓝 `#A8C5D6` 不得用于正文文字**（它当底、不当字）。
2. `build_qss()` 返回一份 QSS 字符串；**两个应用都调它**，不得各写一份样式表。
3. 禁止：弹跳、抖动、闪烁、循环动画；`QPropertyAnimation` 时长 ≤ 240ms。
4. 键盘可达：所有可点控件设置 `setFocusPolicy(Qt.StrongFocus)`，并有可见 focus 样式。

---

## 3. HTTP 契约客户端（`api.py`）

**必须封装，不得在页面里直接散写 `requests.get`。**

```python
class ApiClient:
    def __init__(self, base_url: str): ...        # base_url 形如 http://127.0.0.1:8080
    token: str | None

    def login_student(self, student_no: str) -> dict: ...      # POST /api/v1/auth/login {role:student,password:None}
    def login_teacher(self, teacher_no: str, password: str) -> dict: ...
    def health(self) -> dict: ...

    # 学生端
    def submit_questionnaire(self, body: dict) -> dict: ...
    def my_profile(self, date: str) -> dict: ...
    def my_dates(self) -> dict: ...
    def create_treehole(self, body: dict) -> dict: ...
    def my_treehole(self, date: str) -> dict: ...
    def tips(self, scene: str) -> dict: ...
    def submit_school_feedback(self, body: dict) -> dict: ...
    def my_school_feedback(self) -> dict: ...
    def revoke_consent(self, record_id: str) -> dict: ...      # PATCH

    # 教师端
    def triage_list(self, since: str | None = None) -> dict: ...
    def student_today(self, student_id: str) -> dict: ...
    def ack_ticket(self, ticket_id: str, action: str) -> dict: ...
```

**统一约定**
| 项 | 规则 |
|---|---|
| 信封 | 所有响应是 `{code, message, data}`；**`code != 0` 一律抛 `ApiError(code, message, path)`** |
| 错误码 → 文案 | 用 `copywriting.json` 的 `errors`（1001/1002/2001/2002/3001/4001 + network/timeout） |
| 幂等键 | `record_id` / `entry_id` / `feedback_id` **由客户端生成**（`rec_`/`tre_`/`fb_` + 随机串），超时重试一次 |
| 时间 | 契约是 ISO 8601；**日期参数一律用 `Asia/Shanghai` 的 `YYYY-MM-DD`** |
| 网络失败 | 抛 `ApiError`，UI 显示"网络"文案，**不得静默吞掉** |

**关键：不要阻塞 UI 线程。** 所有请求走 `QThread`/`QThreadPool` 或 `QTimer` + worker；主线程只更新界面。

---

## 4. 文案来源（**不得硬编码**）

两个应用都从 `mindcare/copywriting.json` 读文案（`/tips` 也用同一份）。
> ℹ️ **2026-10-02 路径修正**：运行时 JSON 原在 `mindcare/server/copywriting.json`，已移到
> **`mindcare/copywriting.json`**（与 `copywriting.md` 同级）。文案表是 **B 线资产**，
> 不该放在必须与上游逐字节一致的 `server/` 下——那会让"把后端恢复原样"这个正确动作
> 导致前端静默丢文案（实测丢了 58 条）。代码侧 `COPY_JSON_PATH` 已同步。
```python
COPY = json.loads((ROOT / 'copywriting.json').read_text(encoding='utf-8'))
COPY['errors']['1002']      # 例
COPY['hotlines']            # 危机热线
```
**要求**：任何面向用户的中文文案都必须来自该文件；**发现缺键就在报告里列出**，不要就地写死（也**不要改那个文件**——它由内容负责人维护）。

---

## 5. 页面与状态机

### 5.1 学生端 = 1 主窗 + 2 Tab

```
主窗口 (QMainWindow)
├── Tab1「问卷」= QStackedWidget（逐题切换，**纯本地，不走网络**）
│    Q1 心情(高兴/平淡/沮丧)
│      ├ 高兴 → 恭喜页 ────────────┐
│      ├ 平淡 → 原因选填页 ────────┤
│      └ 沮丧 → Q2 原因(学业/人际/家庭) → Q2.5 物质条件相关? → Q3 详细阐述
│                                 │
│      求助选择（请求心理老师帮助 / 不用帮助）
│            ↓ 一次性 POST /questionnaire/submissions
│      结果页（按 result_scene 渲染，**共 5 个值**）
└── Tab2「树洞」= 列表 + 编辑器
```
**`result_scene` → 页面（穷举 5 个，不得只处理 4 个）**
| 值 | 页面 |
|---|---|
| `happy_end` | 恭喜页 |
| `plain_tips` | 快乐小贴士 |
| `help_sent` | 感谢页（"老师会尽快看到"） |
| `self_care` | 自助建议（深呼吸 / 走一走 / **[写树洞]** → 切到 Tab2 打开编辑器） |
| `consent_revoked` | 撤回结束页 |

**必须实现的字段语义**
- `request_help` 与 `consent_share` **同值**（契约强制）
- Q2.5 `material_related='yes'` 时 `material_detail` **必填**；命中敏感词时接口返回 `2001`（整条不落库），UI 要显示"这段内容会由心理老师来看"
- 树洞 **L0 绝对私密**：界面上**不得**出现任何"分享/公开/让老师看"控件或文案
- 树洞 `visibility` 恒为 `private`

### 5.2 教师端 = 登录窗 → 主窗

```
登录窗 → 主窗（分诊台）
  ├ 顶部：最后同步时间 + 手动刷新 + 30s 倒计时
  ├ 左：分诊列表（priority 徽标 P1/P2/P3 + 姓名/班级 + flags chips + 最后活跃）
  │      chips：病史 / 近N次低落×2 / 求助待处理
  │      ※ 颜色用柔珊瑚/雾蓝/浅灰，**禁止刺眼正红**
  ├ 右：详情抽屉（当日 mood / 提交数 / 待处理求助 / shared_records 正文）
  │      has_shared_records=false 时显示治愈话术占位，**不得显示任何推断性文字**
  └ 操作：ack 对话框（accept / done）
```
**轮询**：进入页面先拉全量（不传 `since`），之后每 30s 传上次响应的 `generated_at`；连续失败 3 次间隔翻倍（30→60→120s）。
**预警口径必须可见**：界面上要写出"近 {window_n} 次记录中出现 {threshold_k} 次低落"，不能只给一个徽标（否则会从"排序参考"退化成"给学生贴标签"）。

---

## 6. 无障碍与合规（双端通用）

- **正文对比度 ≥ 4.5:1**；主色只做底/边/进度，不做正文字色
- 可点区域 ≥ 32×32（桌面）；Tab 键可遍历；焦点可见
- 页脚/关于页必须含：非诊断声明 + 危机热线（12356 / 010-82951332 / 120·110）
- **教师端"病史"chip 属敏感个人信息**：不得进入任何日志/导出/截图；**绝不展示既往病史的具体名称**
- 全流程**禁用诊断性措辞**（抑郁/焦虑/障碍/症状/重度/高危/预警/异常）

---

## 7. 验收方式（无显示器环境下的硬约束）

本机**没有图形界面**，因此：
1. **必须用 offscreen 平台跑通**：`QT_QPA_PLATFORM=offscreen`
2. 必须能**无头启动并构建完整控件树**（不抛异常），并提供一条自检脚本
3. 必须能**截图**（offscreen 下 `widget.grab().save(path)`）存到 `*/__screenshots__/`
4. **不得把"能 import"当作"能跑"**——要断言关键控件存在（用 `findChild` 按 `objectName` 查找）

自检脚本要求（各自应用提供）：
```powershell
$env:QT_QPA_PLATFORM='offscreen'
& $py -m student_desktop.app.selfcheck      # 构建全部页面 + 截图 + 断言关键控件
```

**禁止**：为了让自检通过而跳过页面构建；把网络请求放在主线程；写死一个假数据绕过接口。
