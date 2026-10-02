# MindCare 教师端

Windows 桌面端（PySide6），供心理老师使用。

## 快速启动

```bash
cd teacher-desktop
python -m teacher_desktop.app.main --server http://127.0.0.1:8080
```

或双击 `start-teacher.cmd`。

## 功能

| 页面 | 说明 |
|------|------|
| 分诊台 | 学生名单 30 秒轮询，P1/P2/P3 优先级 |
| 今日预约 | 待预约求助 → 定时间 → 当日单线时间轴 |
| 预警记录 | 连续沮丧不求助预警（服务端真值，客户端只读+消除） |
| 回复库 | 老师自定义回复条目 CRUD |
| 数据导出 | 跨班汇总 → .xlsx（零正文红线） |

## 架构

```
ui/          ← 页面层，只依赖 adapters/base.py 的协议
core/
  adapters/  ← 适配层：Http*Adapter 统一走 DataGateway
  data_gateway.py  ← 统一数据网关（POST /db/read + POST /db/write）
  triage_client.py ← 既有 5 个冻结接口
  models.py  ← 数据类
app/         ← 入口/工厂/自检
desktop_common/  ← 与学生端共享的 HTTP/主题/会话
```

## 数据库对接

**当前数据接口为待填充状态**：`core/data_gateway.py` 的 `read()`/`write()`
是占位实现，数据库同学填充两个方法体即可接入（详见
[`docs/数据库接入指南.md`](docs/数据库接入指南.md)）。

## 自检

```bash
python -m teacher_desktop.app.selfcheck
```
