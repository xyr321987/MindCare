# MindCare 服务端（SQLite）

三端融合方案 spec 的服务端实现（契约 v1.1 追加件）。纯 stdlib（`sqlite3` + `http.server`），
无第三方依赖。**唯一事实源**：学生端与教师端都只通过 HTTP 与本服务通信。

## 启动

```bash
cd MindCare-服务端
python -m server.httpd --port 8080 --data-dir ./data          # 落盘（默认）
python -m server.httpd --engine mock --port 8080              # 内存态（重启即空）
```

- 探活：`curl http://127.0.0.1:8080/api/v1/health`
- 预置教师：`tch_T001` / `mindcare123`（决策 13/18）
- 学生注册：`POST /api/v1/auth/register`（班级/姓名/号次/密码，号次全校唯一）

## 契约自检（先红后绿）

```bash
python -m server.selfcheck
```

覆盖：注册 / 登录 / 问卷 / 树洞 / 预约 / 工单 / 预警 / 回复 / 导出 / 越权 / 幂等 共 19 组断言。

## 端点（契约 §4）

- 冻结 REST 15 个 + `POST /auth/register`
- `POST /db/read`（7 资源）+ `POST /db/write`（9 动作）——教师专用白名单分发器，禁裸 SQL

## 运行纪律（spec §8）

- SQLite：WAL + busy_timeout + 单连接串行写（防 `database is locked`）
- 密码：`pbkdf2_hmac(sha256)` 加盐，`credentials` 独立表
- 时区：强制 `Asia/Shanghai`，`server_time` 是"今天"的唯一权威
- 可见性：§5（仅当天 + 颗粒授权，预约创建日为锚点）
