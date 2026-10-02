# MindCare 接口契约（人读版）

- 版本：v1.0（M0 评审稿）
- 状态：待三方会签冻结
- 机读版：`api-contract.json`（两者冲突时，以会签后更高版本号者为准）

## 1. 全局约定

| 项 | 约定 |
|----|------|
| Base URL | `http://<服务端局域网IP>:8080/api/v1` |
| 编码 | UTF-8；`Content-Type: application/json` |
| 鉴权 | 除 `POST /auth/login`、`GET /health` 外，均需请求头 `Authorization: Bearer <token>` |
| 时间 | 时间戳 ISO 8601 带时区（如 `2026-10-01T22:31:05+08:00`）；日期 `YYYY-MM-DD`，时区 Asia/Shanghai |
| ID | `<前缀>_<随机串>`：`stu_ / tch_ / rec_ / tre_ / tkt_ / alt_` |
| 响应信封 | 成功 `{"code":0,"message":"ok","data":{...}}`；失败 `{"code":<非0>,"message":"<可读说明>","data":null}` |
| 幂等 | 写接口携带客户端生成的 `record_id`/`entry_id`；重复提交返回首次结果，不重复写库 |

### 错误码

| code | 含义 | 触发示例 |
|------|------|----------|
| 0 | 成功 | — |
| 1001 | 未登录或 token 过期 | 缺头 / token 失效 |
| 1002 | 无权限 | 学生访问 triage 接口；教师请求树洞 |
| 2001 | 参数校验失败 | mood=down 缺 detail；message 必须带字段名 |
| 2002 | 资源不存在 | student_id 不存在 |
| 3001 | 服务端内部错误 | 未捕获异常 |
| 4001 | 频率超限 | 同一 token 提交问卷 > 10 次/分钟 |

## 2. 接口明细

### 2.1 POST /auth/login（公共）

请求：

```json
{ "role": "student", "id": "2023001", "password": null }
```

- `role`: `student` | `teacher`
- `id`: 学号 / 工号（预置名单内）
- `password`: 教师必填（演示期预置口令）；学生为 null

响应 `data`：

```json
{
  "token": "9f2c...32位",
  "expires_in": 43200,
  "profile": { "id": "stu_2023001", "name": "林小满", "class_name": "高一(2)班", "role": "student" }
}
```

### 2.2 GET /health（公共）

响应 `data`：`{"status":"ok","version":"1.0.0","server_time":"2026-10-01T23:00:00+08:00","engine_ready":true}`

### 2.3 POST /questionnaire/submissions（学生）

一次性提交完整问卷结果（逐题跳转为前端本地状态机，不产生网络请求）。

请求：

```json
{
  "record_id": "rec_01J8ZEXAMPLE12",
  "mood": "down",
  "plain_note": null,
  "cause_category": "study",
  "detail": "最近三次月考排名连续下滑，晚自习完全无法集中……",
  "request_help": true,
  "consent_share": true,
  "consent_ts": "2026-10-01T22:31:05+08:00"
}
```

服务端强制校验规则（违反返回 2001）：

| mood | plain_note | cause_category | detail | request_help | consent_share |
|------|-----------|----------------|--------|--------------|---------------|
| happy | 必须 null | 必须 null | 必须 null | 必须 false | 必须 false |
| plain 且未填原因 | null | 必须 null | 必须 null | 必须 false | 必须 false |
| plain 且填了原因 | 非空 | 必填 | 必填 | 必选 | =request_help |
| down | 可为 null | 必填 | 必填（不限字数） | 必选 | =request_help |

- `cause_category`: `study` | `relationship` | `family`
- `request_help=true` 时 `consent_share` 必须为 true 且 `consent_ts` 必填（单独同意留痕）
- 副作用：`request_help=true` → 服务端自动创建 `ticket(status=pending)`

响应 `data`：

```json
{
  "record_id": "rec_01J8ZEXAMPLE12",
  "date": "2026-10-01",
  "result_scene": "help_sent",
  "tips": { "scene": "down", "text": "可以跟我做：深呼吸，走一走，或者去树洞写写心里话。", "treehole_entry": true }
}
```

- `result_scene`: `happy_end` | `plain_tips` | `help_sent` | `self_care`（前端据此渲染对应结束页）
- `tips` 仅 `plain_tips` / `self_care` 场景返回

### 2.4 GET /profile/me?date=YYYY-MM-DD（学生）

响应 `data`：

```json
{
  "date": "2026-10-01",
  "submissions": [ { "record_id": "rec_...", "ts": "...", "mood": "down", "cause_category": "study", "detail": "...", "request_help": true } ],
  "treehole": [ { "entry_id": "tre_...", "ts": "...", "content": "...", "mood_tag": null } ]
}
```

### 2.5 GET /profile/me/dates（学生）

响应 `data`：`{"dates":["2026-09-29","2026-09-30","2026-10-01"]}`（日历打点用）

### 2.6 POST /treehole/entries（学生）

请求：`{"entry_id":"tre_01J...","content":"今天……","mood_tag":null}`
响应 `data`：`{"entry_id":"tre_01J...","ts":"2026-10-01T22:40:11+08:00"}`

### 2.7 GET /treehole/entries?date=YYYY-MM-DD（学生）

响应 `data`：`{"date":"...","entries":[{"entry_id":"...","ts":"...","content":"...","mood_tag":null}]}`

### 2.8 GET /tips?scene=plain|down（学生，可选）

响应 `data`：`{"scene":"plain","text":"可以出去看看哦，运动或和朋友走走都可以有不一样的体验……"}`

### 2.9 GET /triage/list?since=（教师）

- `since` 可选，ISO 时间；增量语义：返回自该时间后有变化的学生条目（条目级全量）。

响应 `data`：

```json
{
  "generated_at": "2026-10-01T23:05:00+08:00",
  "params": { "window_n": 3, "threshold_k": 2, "p3_lookback_days": 7 },
  "items": [
    {
      "student_id": "stu_2023007",
      "name": "陈默",
      "class_name": "高一(2)班",
      "priority": 1,
      "flags": { "has_history": true, "recent_down_count": 2, "window_size": 3, "pending_help": false },
      "last_active_ts": "2026-10-01T21:12:44+08:00",
      "masked": true
    },
    {
      "student_id": "stu_2023001",
      "name": "林小满",
      "class_name": "高一(2)班",
      "priority": 2,
      "flags": { "has_history": false, "recent_down_count": 1, "window_size": 3, "pending_help": true },
      "last_active_ts": "2026-10-01T22:31:05+08:00",
      "masked": true
    }
  ]
}
```

**权限纪律**：本接口任何字段不得包含问卷正文/树洞内容；`masked` 恒为 true，提醒前端不得展示正文。

### 2.10 GET /triage/students/{student_id}/today（教师）

响应 `data`（该生当日未共享任何记录时）：

```json
{
  "student_id": "stu_2023007",
  "date": "2026-10-01",
  "mood_latest": "down",
  "submission_count_today": 1,
  "pending_help": false,
  "alert": { "level": 1, "rule": "history_plus_recent_down", "recent_down_count": 2, "window_size": 3 },
  "shared_records": [],
  "masked": true
}
```

该生有 `consent_share=true` 记录时，`shared_records` 按 ts 倒序返回正文，且 `masked=false`：

```json
{ "shared_records": [ { "record_id": "rec_...", "ts": "...", "mood": "down", "cause_category": "study", "detail": "……" } ], "masked": false }
```

### 2.11 POST /triage/tickets/{ticket_id}/ack（教师）

请求：`{"action":"accept","note":null}`（`action`: `accept` | `done`）
响应 `data`：`{"ticket_id":"tkt_...","status":"accepted","updated_at":"..."}`

## 3. 引擎内部接口（A→C，Python）

见 `docs/架构设计方案.md` §3.8，签名为契约一部分，冻结级别与 HTTP 接口相同。C 先行交付同签名的 `MockEngine`（内存实现）。

## 4. Mock 数据规格（C 交付）

- 学生 12 名（`stu_2023001`~`stu_2023012`）：2 名 `has_mental_history=true`；覆盖三个班级
- 教师 1 名：`tch_T001`，口令演示期预置
- 历史数据：过去 7 天，按脚本化分布生成（至少覆盖：P1 命中者 1 名、pending 求助 2 名、plain 未填原因 2 名、纯 happy 3 名、树洞 5 条）
- 种子脚本：`python -m mock.seed --data-dir ./data --days 7`

## 5. 契约变更流程

1. 提案方修改 `api-contract.json` + 本文件，版本号 +0.1，在 PR 描述写明影响面；
2. 三方会签后版本进位并打 tag；
3. 契约测试同步更新，先红后绿。
