# 见山 · MindCare 校园心理关怀平台

一套面向校园心理关怀的三端应用：**学生端**（问卷 / 树洞 / 我的档案）、**教师端**（分诊台 / 预约 / 预警 / 回复库 / 导出）、**服务端**（HTTP API + SQLite 数据事实源）。整体视觉走「温柔、安静、治愈、自然」路线。

## 组成

| 目录 | 说明 | 技术栈 |
|---|---|---|
| `MindCare-服务端/` | HTTP API + SQLite 唯一数据事实源，学生端/教师端都通过它读写 | 纯 Python 标准库 |
| `MindCare-前端交付包(1)/` | 学生端桌面应用 + 双端共享包 + 文案表 | PySide6 |
| `MindCare-教师端-交付(2)/` | 教师端桌面应用 | PySide6 + openpyxl |

## 快速开始

> 完整的分步运行指南见 [运行说明](<运行说明.md>)。

环境：Python 3（本机实测 3.12）。学生端/教师端需 `pip install PySide6`（教师端另需 `openpyxl`），服务端无第三方依赖。

### 1. 启动服务端

```bash
cd MindCare-服务端
python -m server.httpd --port 8080 --data-dir ./data   # 落盘模式
# 内存态（重启即空）：python -m server.httpd --engine mock --port 8080
```

- 探活：`curl http://127.0.0.1:8080/api/v1/health`
- 预置教师账号：`tch_T001` / `mindcare123`

### 2. 启动学生端 / 教师端（需服务端已在运行）

```bash
# 学生端
cd "MindCare-前端交付包(1)"
python -m student_desktop.app.main --server http://127.0.0.1:8080

# 教师端
cd "MindCare-教师端-交付(2)"
python -m teacher_desktop.app.main --server http://127.0.0.1:8080
```

Windows 下也可双击各端目录内的 `start-server.cmd` / `start-student.cmd` / `start-teacher.cmd` 一键启动（自动找 `python` 并设好环境变量）。

## 自检

```bash
python -m server.selfcheck                                   # 服务端契约自检
python -m student_desktop.app.selfcheck --skip-network        # 学生端（离线）
python -m teacher_desktop.app.selfcheck                       # 教师端
```

## 目录结构

```
.
├── MindCare-服务端/
│   └── server/            # httpd 入口 / engine 引擎 / db / selfcheck
├── MindCare-前端交付包(1)/
│   ├── desktop_common/    # 双端共享包（主题 / HTTP / 会话）
│   ├── student-desktop/   # student_desktop 应用
│   └── copywriting.*      # 文案表
└── MindCare-教师端-交付(2)/
    ├── teacher_desktop/   # 页面层 / 适配层 / 数据网关
    └── requirements.txt
```

## 更多文档

- [运行说明](<运行说明.md>)
- [服务端 README](<MindCare-服务端/README.md>)
- [学生端（前端交付包）README](<MindCare-前端交付包(1)/README.md>)
- [教师端 README](<MindCare-教师端-交付(2)/README.md>)