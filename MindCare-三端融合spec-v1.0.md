# MindCare 三端融合方案 spec v1.0

> 状态：**定案稿（31 项决策已锁定）**　日期：2026-10-02　｜　契约变更 = **v1.1 追加件**
> 覆盖：学生端桌面应用 + 教师端桌面应用 + 服务端(SQLite) 三端有机连接
> 依据：`MindCare-前端交付包(1)/`（学生端 + 冻结契约）、`MindCare-教师端-交付(2)/`（权威教师端）

---

## 0. 一句话结论

学生端与教师端是两台 PySide6 桌面应用，**都只通过 HTTP 与同一台服务端通信**；服务端用
**单个 SQLite 文件**作为唯一事实源，按 `student_id` 做"单库分区"实现"个人数据库"隔离；
教师端新增能力统一走 **`POST /db/read` + `POST /db/write`** 白名单分发器，学生端保留冻结
的 15 个 REST 端点。同步用 HTTP 轮询（预约 2s / 分诊 30s），不引 WebSocket。

---

## 1. 三端拓扑与运行形态

| 端 | 目录 | 通信 | 角色 |
|---|---|---|---|
| 学生端 | `student-desktop/student_desktop/` | HTTP → 服务端 REST（15 端点） | student |
| 教师端 | `teacher_desktop/`（交付2，权威） | HTTP → 冻结 REST + `/db/*` | teacher |
| 服务端 | （待建，不在交付包内） | 监听 `127.0.0.1:8080`，SQLite 落库 | 唯一事实源 |

- 部署：**单机演示**（三者同机 `127.0.0.1:8080`），但 `--server` 不写死，可切局域网。
- 传输：HTTP + JSON 信封 `{code,message,data}` + `Bearer token`；客户端同步 `urllib`，跑 `QThreadPool`。
- 实时：轮询（预约 2s、分诊 30s、健康检查 10s）。

---

## 2. 已定案决策清单（20 项）

| # | 决策 | 定案 |
|---|---|---|
| 1 | 数据库引擎 | SQLite（单文件，`--engine real`） |
| 2 | 部署拓扑 | 单机演示，`--server` 可切局域网 |
| 3 | 预约模型 | 两者融合，统一重设计 |
| 4 | 教师端接入 | 通用 `/db/read` + `/db/write` |
| 5 | 预约-工单关联 | 双路径弱关联（`ticket_id` 可空） |
| 6 | 老师回复回流 | 合并进 `tips` 查找，学生端零改动 |
| 7 | 预警落地 | 物化表 + 提交时同步扫描 |
| 8 | 交付节奏 | 先出完整设计再写码 |
| 9 | blocks 路由 | `/db` 加 `blocks.list` / `blocks.set` |
| 10 | 安全缺口 | 只打通，缺口留档（学生认证见 #12 注册制） |
| 11 | 完成联动 | `appointments.complete` 自动联动 `ticket→done` |
| 12 | 学生来源 | **注册制**（无预设种子）：班级/姓名/号次/密码 |
| 13 | 教师账号 | 预置 1 个（`tch_T001` + 固定演示口令） |
| 14 | 个人库形态 | 单库分区（非每学生一文件） |
| 15 | 授权范围 | 仅当天 |
| 16 | 预约推送 | 快速轮询 2s |
| 17 | 号次唯一性 | 全校唯一（登录凭据 = 号次 + 密码） |
| 18 | 教师口令 | 固定演示口令（见 §8） |
| 19 | 撤回授权 | v1 不做，留档（授权仅当天自动失效） |
| 20 | 交付形式 | 落成 spec 文档（本文件） |
| 21 | 分诊来源 | 全部注册学生（priority/flags 按近期活动实时算） |
| 22 | 详情刷新 | 详情抽屉打开即时拉 `student_today` |
| 23 | 契约版本 | 契约变更升 **v1.1 追加件**，走会签 |
| 24 | consent 机制 | 预约 share 标记为唯一可见性开关；问卷 `consent_share` 仅作 `request_help` 联动值 |
| 25 | 今天锚点 | 预约创建日（`created_ts` 日期），非约谈日 |
| 26 | 授权有效期 | 仅当天、过夜失效，无历史回看 |
| 27 | 病史来源 | 教师端标记（注册不自填） |
| 28 | 密码找回 | 教师端代重置 |
| 29 | 格子单一事实源 | 契约写死常量（8 节次/星期/日历锚点，§4.4） |
| 30 | slot 双预约 | 服务端拒绝同一 slot 第二个预约 |
| 31 | student_today | 返回 `tickets` 字段（消除缺口 G-1） |

---

## 3. 数据字典 v3（建表顺序即"创建函数"顺序）

单库 `MindCare.db`，按"根 → 分支 → 共享"三层。

```
【0 根表】students · credentials · teachers · teacher_credentials
【1 个人分支】questionnaire_submissions · treehole_entries   ← 时间线 append，无预设
【2 求助预约】tickets · appointments
【3 教师侧】warnings · replies · blocks · tips · sessions
```

### 3.1 根表（"个人数据库最开头"）

| 表 | 列 | 约束/说明 |
|---|---|---|
| `students` | `student_id` TEXT PK | `stu_<seat_no>`，内部 ID |
| | `seat_no` TEXT | 号次，**全校唯一**，登录凭据之一 |
| | `name` TEXT NOT NULL | 姓名 |
| | `class_name` TEXT NOT NULL | 班级 |
| | `has_mental_history` INTEGER | 病史标志（**教师端标记**，注册不自填，见决策 27） |
| | `created_ts` TEXT | ISO8601 |
| `credentials` | `student_id` TEXT PK → students | **密码独立存储** |
| | `password_hash` TEXT | 加盐哈希（stdlib `hashlib.scrypt`） |
| | `salt` TEXT | |
| `teachers` | `teacher_id` TEXT PK | `tch_T001` |
| | `name` TEXT | |
| `teacher_credentials` | `teacher_id` TEXT PK → teachers | |
| | `password_hash` / `salt` TEXT | 演示口令哈希 |

### 3.2 个人分支（时间线，一条条 append）

| 表 | 列 | 说明 |
|---|---|---|
| `questionnaire_submissions` | `record_id` TEXT PK(`rec_`), `student_id` FK, `ts`, `date`, `mood`, `plain_note`, `cause_category`, `detail`, `request_help`, `consent_share`, `consent_ts` | 分支1：问卷 |
| `treehole_entries` | `entry_id` TEXT PK(`tre_`), `student_id` FK, `ts`, `date`, `content`, `mood_tag` | 分支2：树洞，**L0 绝对私密** |

索引：`(student_id, date)` 各一。

### 3.3 求助 / 预约 / 共享

| 表 | 列 | 说明 |
|---|---|---|
| `tickets` | `ticket_id` PK(`tkt_`), `student_id` FK, `source_record_id` NULL, `status`(pending/accepted/done), `created_ts`, `updated_ts`, `note` | `request_help=true` 时服务端自动建 |
| `appointments` | `apt_id` PK(`apt_`), `student_id` FK, `ticket_id` NULL FK, `name`, `class_name`, `year/month/day/period/weekday/time_start/time_end/slot`, `date`(派生 YYYY-MM-DD), **`share_questionnaire`**, **`share_treehole`**, `status`(scheduled/done), `note`, `created_ts`, `updated_ts` | 融合表；`date` 用于"今天"过滤 |

### 3.4 教师侧

| 表 | 列 | 说明 |
|---|---|---|
| `blocks` | `blk_id` PK(`blk_`), `slot` UNIQUE, `active`, `reason`, `operator`, `created_ts` | 不可预约段 |
| `warnings` | `warning_id` PK(`warn_`), `student_id` FK, `rule`, `streak_count`, `latest_ts`, `status`(active/dismissed), `dismissed_at`, `dismiss_note`, `created_ts` | 物化 + 提交时扫描 |
| `replies` | `reply_id` PK(`rpl_`), `text`, `scenes`(JSON), `enabled`, `created_ts`, `updated_ts` | 老师自定义回复 |
| `tips` | `scene` PK, `text`, `treehole_entry` | 静态种子 |
| `sessions` | `token` PK, `role`, `subject_id`, `expires_at` | 12h |

**ID 前缀总表**：`stu_ / tch_ / rec_ / tre_ / tkt_ / apt_ / blk_ / warn_ / rpl_`。

---

## 4. 接口契约终稿（**v1.1 追加件**，对冻结 15 端点的 delta）

> 本节的契约变更作为 **v1.1 追加件** 走契约 §5 会签流程：新增 `POST /auth/register`、
> 学生登录改真密码、教师端 `/db/*`。冻结 v1.0 的 15 个端点本身不改；仅 `/triage/list`
> 的"名单来源"由预置 12 人改为注册全集（见 §8.7）。

### 4.1 变更与新增

| 项 | 内容 |
|---|---|
| ➕ `POST /auth/register`（公共） | `{class_name, name, seat_no, password}` → 建 students+credentials，**自动登录**返回 `{token, expires_in, profile}` |
| ✏️ `POST /auth/login`（学生） | `password` 由 `null` → **真密码**；`id` = 号次（全校唯一） |
| ✅ 学生端 15 REST | 不变（含预约 4 个）；`POST /appointments` 落库后触发教师端刷新 |
| ✏️ `/db/read` | RESOURCE 6 → **7**（加 `blocks.list`） |
| ✏️ `/db/write` | ACTION 6 → **9**（加 `blocks.set`、`students.set_history`、`students.reset_password`） |
| ✏️ `GET /triage/students/{id}/today` | 响应增加 `tickets[]` 字段（消除缺口 G-1，决策 31） |

注册重复号次 → `2001`，`message` 带字段名 `seat_no`（"号次已注册"）。

> **可执行契约（风险控制 R7/R10）**：§4.2/4.3 里每个 resource/action 的 `data` 形状与字段名
> **逐字对齐客户端适配器的解析**（适配器读 `data.items`）。写码先落**契约测试（先红后绿）**，
> 两端对着测，杜绝"字段名漂移 → 静默空数据"。

### 4.2 `/db/read`（教师，`{resource, params}`）

| resource | params | 返回 |
|---|---|---|
| `appointments.pending` | — | `items[]`：待预约工单 = `tickets WHERE status='pending' AND ticket_id NOT IN (SELECT ticket_id FROM appointments WHERE ticket_id IS NOT NULL)`，零正文 |
| `appointments.by_date` | `{date}` | `items[]`：当日预约，share=true 时才带正文 |
| `blocks.list` | `{}` | `items[]`：全部不可预约段 |
| `warnings.list` | — | `items[]`：active 前、dismissed 后 |
| `replies.list` | — | `items[]`：updated_at 倒序，含停用 |
| `export.classes` | — | `items[]`：班级列表 |
| `export.rows` | `{start, end, class_name?}` | `items[]`：**零正文**汇总行 |

### 4.3 `/db/write`（教师，`{action, payload}`）

| action | payload | 返回 |
|---|---|---|
| `appointments.schedule` | `{student_id, ticket_id?, year/month/day/period 或 scheduled_at, note?}` | appointment(scheduled) |
| `appointments.complete` | `{appointment_id}` | appointment(done)，**联动 ticket→done** |
| `blocks.set` | `{year, month, day, period, active, reason?}` | block |
| `warnings.dismiss` | `{warning_id, note?}` | warning(dismissed) |
| `replies.create` | `{text, scenes[]}` | reply |
| `replies.update` | `{reply_id, text?, scenes?, enabled?}` | reply |
| `replies.delete` | `{reply_id}` | `{reply_id}` |
| `students.set_history` | `{student_id, has_history}` | student 基本信息（含 has_mental_history） |
| `students.reset_password` | `{student_id, new_password}` | 重置成功回执 |

**安全纪律**：`/db/*` 是**闭集白名单分发器**（resource/action 各绑死处理函数，**绝不裸透传 SQL**）；教师角色专用，学生访问 → `1002`。

---

## 4.4 预约时间常量（**契约写死，两端一致**，决策 29）

解决 R8：格子/节次/星期/日历逻辑的"单一事实源"写进契约。服务端按此实现派生
`period/weekday/time_start/time_end/slot`；客户端 `schedule.py` 保留，但自检断言与此表一致。

| 节次 | 时间段 | 节次 | 时间段 |
|---|---|---|---|
| 1 | 08:00–08:45 | 5 | 13:30–14:15 |
| 2 | 08:50–09:35 | 6 | 14:20–15:05 |
| 3 | 09:55–10:40 | 7 | 15:11–16:00 |
| 4 | 10:45–11:30 | 8 | 16:05–16:50 |

- `weekday` 存 1~7（1=周一 … 7=周日），与 `datetime.weekday()` 的 0~6 相差 1。
- 日历锚点年份 = 2026（星期几按 2026 真实日历编排）。
- `slot_id` = `YYYY-MM-DD#P`（仅内存索引/界面定位，非主键）。

## 5. 可见性规则（"仅当天 + 颗粒授权"）

**"今天"的锚点 = 预约创建日**（`appointments.created_ts` 落在哪一天），**不是**预约约谈日
（约谈日可能在明天/后天；学生是"今天"求助并勾共享，开放的是今天的问卷/树洞）。这是
字段级模拟分析揪出的缺陷（矛盾 O）。

服务端在**所有教师读路径**统一套此过滤器：

```text
看学生 X 在日期 D（D = 预约创建日）的数据：
  appt = X 创建的、created_ts 落在 D 当天的预约
  appt.share_questionnaire=true → 返回 X 在 D 当天的 questionnaire 行
  appt.share_treehole=true      → 返回 X 在 D 当天的 treehole 行
  否则（无该日预约 / 两标记都 false）→ 只返回 students 基本信息（name/class_name/seat_no），正文一律 null
```

- 应用到：`GET /triage/students/{id}/today` 的 `shared_records`；`/db/read appointments.by_date` 的正文字段。
- **唯一开关**：教师可见性只看 `appointments` 的 share 标记；问卷表 `consent_share` 仅作 `request_help` 联动值，不单独控制可见性（决策 24）。
- **仅当天、过夜失效**：教师只能看到"当前日(Asia/Shanghai)"已授权的问卷/树洞；授权随当天结束失效，**无历史回看**（"当天"=预约创建日，且只在创建日当天可见）。
- 详情页刷新：教师打开学生抽屉时**即时拉一次** `student_today`（不靠 30s 轮询）。
- 树洞默认 L0 私密；只有 `share_treehole=true` 且该日才破例。

---

## 6. 权限矩阵

| 数据 | 学生 | 教师 | 规则 |
|---|---|---|---|
| 自己问卷/树洞 | ✅ | ❌（树洞无读路由） | L0 |
| 分诊聚合 | ❌ | ✅ | 列表零正文，`masked` 恒 true |
| 求助正文 | ✅ | ✅ 仅当天+consent | 见 §5 |
| 预约正文 | ✅ | ✅ 仅当天+share 标记 | 否则只有基本信息 |
| 导出汇总 | ❌ | ✅ 零正文 | 服务端硬校验 |
| 不可预约段 | ✅ 读 | ✅ 写（`/db blocks.set`） | 格子级非个人 |

---

## 7. 关键时序（数据流）

```
① 学生注册 POST /auth/register → students + credentials（空分区）
② 学生登录 POST /auth/login（号次+密码）→ token
③ 填问卷 POST /questionnaire/submissions → 时间线 append；request_help=true 时自动建 ticket(pending)
④ 写树洞 POST /treehole/entries → 时间线 append（L0）
⑤ 求助/预约：学生选格子 + 勾选共享(问卷/树洞) → POST /appointments → 落库
     → 教师端 2s 轮询 /db/read appointments.by_date 看到
⑥ 教师看详情 GET /triage/students/{id}/today → 按 §5 只回"当天+已授权"数据
⑦ 教师代订 /db/write appointments.schedule（仅当学生只求助没选格子）
⑧ 教师完成 /db/write appointments.complete → appointment(done) + ticket(done)
⑨ 预警：第 3 次 down+不求助 提交时 → warnings(active)；教师 dismiss → 留痕清零
⑩ 导出 /db/read export.rows → 零正文 xlsx
```

---

## 8. 服务端实现要点（写码阶段）

1. `db.py`：建 3.1~3.4 表 + 索引 + 迁移；`--engine real` 落 SQLite，`--engine mock` 内存。
2. `register()`：号次去重（全校唯一）→ 建 `students` + `credentials`（`hashlib.scrypt` 加盐）。
3. `/db` 分发器：白名单 `dict[resource|action] -> handler`，教师鉴权 + 参数校验。
4. 预警扫描：`POST /questionnaire/submissions` 后同步扫该生连续 down 计数（满 3 且 `request_help=false` → active；其他分支清零）。
5. `tips` 合并：按 `result_scene` 查 `replies(enabled)` 命中则覆盖默认 `tips.text`。
6. 预约推送：`POST /appointments` 成功后，教师端靠 2s 轮询感知（无需契约变更）。
7. 分诊列表来源 = `students` 注册全集（无种子，空列表合法）；priority/flags 按近期活动实时算。

**默认值（可调）**：教师演示口令 `mindcare123`；注册后自动登录；号次任意非空（去首尾空白、长度 ≤32、全校唯一）；学生密码 ≥4（生产需收紧，留档）；注册重复号次 → `2001` 带字段 `seat_no`；`student_id = "stu_" + seat_no`；consent 可见性唯一开关 = 预约 share 标记。

**运行纪律（二轮筛查风险控制）**：
- SQLite：**WAL + `busy_timeout` + 单写者连接**；写事务串行（同一时刻只一个写），避免 `database is locked`（R1）。
- `register()` 用**单事务**包裹 `students`+`credentials`，防孤儿账号（R2）。
- 服务端**强制 `zoneinfo("Asia/Shanghai")`**；`server_time` 是"今天"的唯一权威，客户端不自行判"今天"（R9）。
- 同 slot 第二个预约 → **拒绝**（`2001` 带字段 `slot`，R6/决策 30）。
- `/health` 返回 `engine_ready`（SQLite 就绪信号，R14）。
- token：随机 32 位、12h 过期、`1001` 清登录态（R15）。
- `export.rows` 的 `{start, end}` 为**含端点闭区间**，按问卷 `date` 过滤（R16）。
- `tips` 合并：仅 `enabled=true` 的回复参与；命中才覆盖默认，否则回退 `tips` 表（R18）。

---

## 9. 客户端改造清单

### 9.1 学生端（`MindCare-前端交付包(1)`）

1. 加注册页（班级/姓名/号次/密码）→ `POST /auth/register`。
2. 登录页加密码框；删除 `normalize_student_no()` 的"补 `stu_` 前缀"逻辑（改为原样发送号次）。
3. `desktop_common/api.py::login_student()` 签名改为发送真密码（**共享包改动，教师端同步受影响需回归**）。
4. 求助/预约页"共享问卷/共享树洞"勾选 = 颗粒授权 UI（已存在，微调文案）。
5. 删除/归档死抽象 `desktop_common/database.py`（学生端不调用它）。
6. `desktop_common/api.py` 改 `login_student()` 发真密码——**pkg1 与 pkg2 两份都要同步改**，改完跑两端自检防漂移（R3）。

### 9.2 教师端（`MindCare-教师端-交付(2)`）

1. `core/data_gateway.py` 的 `read()/write()` 填成 `_http_read()/_http_write()`。
2. 注册表加 `blocks.list` / `blocks.set`；新增 `HttpBlockAdapter`（或并入现有适配器）。
3. `core/models.py::StudentToday` 修正为用 `has_shared_records`（弃 `masked` 的旧语义），并删掉契约外的 `tickets` 字段（或改为兼容忽略）。
4. 归档 `前端交付包(1)/teacher-desktop/`（旧版，非权威）。
5. 详情抽屉打开时即时拉 `student_today`（解决"预约 2s / 分诊 30s"节奏差）。
6. 新增"学生管理"：病史标记 + 重置密码（走 `students.set_history` / `students.reset_password`）。

---

## 10. 端到端闭环用例 v2（写码阶段实跑，mock+SQLite 双引擎）

| # | 用例 | 断言 |
|---|---|---|
| 1 | 学生注册 → 登录 | students+credentials 建，token 可用 |
| 2 | 重复号次注册 | `2001` 带 `seat_no` |
| 3 | 填 happy → 提交 | submissions 落 1 行，无 ticket |
| 4 | down+求助+共享问卷(+预约) | ticket(pending) 建，教师端当天可见问卷、树洞不可见 |
| 5 | 只预约、都不共享 | 教师端只看到姓名/班级/号次 |
| 6 | 共享树洞 | 教师端当天可见树洞 |
| 7 | 学生只求助不选格子 → 教师代订 | schedule() 建 appointment |
| 8 | 教师 complete | appointment(done)+ticket(done) |
| 9 | 连续 3 次 down+不求助 | warnings active；dismiss 后留痕清零 |
| 10 | 教师设 blocks | 学生端 2s 内红框 |
| 11 | 教师建回复 | 学生同 scene 结果页文案被覆盖 |
| 12 | 跨班导出 | 零正文 |
| 13 | 学生 token 打 /db → 1002；教师打树洞 → 1002 | 权限负向 |
| 14 | 同 record_id 重发 | 不重复落库 |

---

## 11. 矛盾/缺口销号表（批判性回归）

| 编号 | 原矛盾 | 处置 |
|---|---|---|
| A | 两套网关词汇表 | 统一为 /db 注册表 + 学生保留 REST ✅ |
| B | 两套预约模型 | 融合 appointments 表 ✅ |
| C | 三套状态机 | tickets/appointments/warnings 三表各管一段 ✅ |
| D | 两个教师端 | 交付2 为权威，pkg1 旧教师端归档 ✅ |
| E | 预约双客户端通路 | 学生 REST / 教师 /db，服务端同 service ✅ |
| F | blocks 教师端丢失 | /db 加 blocks.list/set ✅ |
| G | 存储三说并存 | SQLite 落库，JSONL 仅导出/迁移 ✅ |
| H | 关键文档缺失 | 本 spec 补"教师端新增接口协议" ✅ |
| I | masked vs has_shared_records | 教师端模型改 has_shared_records ✅ |
| J | 教师端实体 ID 前缀 | warn_ / rpl_ 补上 ✅ |
| K | database.py 与 models.py 重复 | database.py 删除/归档 ✅ |
| L | 先预约后建 ticket 时序 | ticket_id 可空 + 双路径弱关联 ✅ |
| M | 预约两条路由 | 学生 POST /appointments；废弃 REST GET /appointments（教师列表） ✅ |
| N | consent 双机制 | 预约 share 标记为唯一开关（决策 24） ✅ |
| O | 今天锚点错误 | 改为预约创建日，非约谈日（决策 25，§5） ✅ |
| P | 病史无来源 | 教师端标记（决策 27） ✅ |

**安全缺口（留档，v1 不堵）**：token 明文落盘、幂等键不校验归属（**最建议下版补**）、数据明文、无撤回。
**注册制已自然解决**：学生零认证（现在有密码）。

---

## 12. 分阶段实施计划

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 定案（20 决策） | ✅ 完成 |
| 1 | 服务端 db.py：建表/迁移/注册/登录/凭证哈希 | 待写码 |
| 2 | 服务端接口：REST15 + /auth/register + /db 分发器(7+7) + §5 权限过滤 | 待写码 |
| 3 | 服务端业务：ticket 自动建/预警扫描/tips 合并/推送触发 | 待写码 |
| 4 | 学生端改造：注册页/密码登录/颗粒授权 UI | 待写码 |
| 5 | 教师端改造：data_gateway 填充/blocks 适配器/has_shared_records 修正 | 待写码 |
| 6 | 联调：§10 的 14 条闭环实跑（mock+SQLite 双引擎） | 待执行 |
| 7 | 批判性回归：§11 逐项销号 | 待执行 |

---

## 13. 信任边界（重要澄清）

"个人数据库仅个人可见"在**单库分区**下由**服务端应用层权限**实现，不是文件物理隔离——
即 SQLite 文件在服务端进程内可访问全部行，隐私依赖 §5/§6 的鉴权与过滤逻辑**正确实现**。
若未来要物理隔离，才升级为每学生独立库或 PostgreSQL 行级安全（不在 v1 范围）。
