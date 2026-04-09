# web-diagnostic

DeviceCore AI 日志诊断 Web 应用。用户上传设备日志（或指定 Ticket ID 自动拉取），Claude AI 通过 MCP 工具实时分析，结果以 Markdown 报告或时间轴形式展示。

Docker 部署指引见 [DOCKER.md](DOCKER.md)。

## 功能概览

- **日志自动拉取**：通过 SSO/OAuth 认证后，输入 Ticket ID 即可从 App Log Platform 自动下载日志
- **文件上传**：支持拖拽上传 `.log` / `.txt` / `.zip` / `.gz`（单文件最大 50 MB）
- **AI 实时诊断**：Claude Code CLI + log-analyzer MCP 工具，流式输出工具调用过程
- **场景化报告**：内置 AIVoice 场景模板（识别音频、录音、云端上传等），输出结构化时间轴报告
- **分析历史**：结果自动保存，支持回溯查看和下载
- **知识库积累**：可从诊断结果中提取规律写入知识库，供后续诊断参考

## 架构

```
web-diagnostic/
├── server.py              # FastAPI 后端（WebSocket + REST API）
├── claude_runner.py       # Claude CLI 封装（进程管理 + JSON 流解析）
├── start.sh               # 本地一键启动脚本
├── requirements.txt       # Python 依赖
├── Dockerfile             # 多阶段构建（Node 20 前端 + Python 3.12 运行时）
├── docker-compose.yml     # Docker Compose 配置
├── DOCKER.md              # Docker 部署指引
├── frontend/              # 前端（Vanilla JS + Tailwind CSS + Vite）
│   └── src/
│       ├── main.js        # 入口，WebSocket 事件路由，视图切换
│       ├── core/          # 基础设施（store、component、ws）
│       ├── views/         # 三个主视图（idle / analyzing / result）
│       ├── components/    # 可复用组件（terminal、report、history 等）
│       ├── utils/         # 工具函数（markdown 渲染、格式化）
│       └── templates/     # AIVoice 场景模板元数据
├── data/
│   └── history/           # 诊断历史（JSON，持久化到本地/volume）
└── tests/                 # Python 测试
```

## 快速启动（本地）

```bash
# 在仓库根目录或 web-diagnostic/ 目录下均可执行
cd web-diagnostic
./start.sh               # 默认端口 8080
./start.sh --port 9000   # 自定义端口
```

脚本会自动完成：
1. 检测并创建 Python venv（需 Python 3.10+）
2. 安装 Python 依赖
3. 构建前端（需 Node.js，若 `frontend/src` 有变更则自动重新构建）
4. 链接 `.mcp.json`（log-analyzer MCP 工具）
5. 启动 Uvicorn

浏览器访问 `http://localhost:8080`。

> **前提**：已安装并登录 Claude Code CLI（`claude`），且已配置 log-analyzer MCP 工具。

## 前端开发

```bash
cd frontend
npm install
npm run dev      # Vite dev server（代理到后端 8080）
npm run build    # 构建到 dist/
```

## 后端架构要点

### 任务队列

单 worker 顺序处理，多个用户提交的诊断任务依次执行，WebSocket 实时广播队列状态。

### WebSocket 协议

**Client → Server**（`/ws/chat`）：

| 字段 | 说明 |
|------|------|
| `action` | `analyze` / `stop` / `set_sso` / `knowledge` |
| `message` | 问题描述（analyze 时可选） |
| `file_path` | 已上传文件路径（可选） |
| `template` | 场景模板 ID，如 `audio-recognition`（可选） |
| `token` | SSO 用户 Token |

**Server → Client**（事件类型）：

| 类型 | 说明 |
|------|------|
| `hello` | 连接建立，携带 `web_session_id` |
| `queued` | 已入队，携带位置信息 |
| `task_started` | 任务开始执行 |
| `tool_use` | Claude 调用 MCP 工具 |
| `tool_result` | 工具返回结果 |
| `text` | Claude 输出的文本 |
| `result` | 最终报告（含 `template_data` 结构化数据） |
| `error` | 错误信息 |
| `stopped` | 任务被中止 |
| `queue_update` | 全局队列状态变更 |

### 场景模板（AIVoice）

内置四类场景，Claude 按照预定义 phase 输出结构化报告：

| 模板 ID | 场景 |
|---------|------|
| `audio-recognition` | 实时链路（语音识别/录音链路统一） |
| `cloud-upload` | 云端上传 |
| `offline-transcription` | 离线转写 |

AIBuds 日志中的 `[AIBuds_ASR]` 行会被自动提取、解析为 ASR 记录表格（包括 request_id、耗时、识别文本、中间更新次数）。

## REST API

| 路径 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（Docker HEALTHCHECK） |
| `/api/upload` | POST | 上传日志文件 |
| `/api/fetch-ticket` | GET | 拉取 Socrates Ticket 详情 |
| `/api/sso-verify` | POST | 验证 SSO Token |
| `/api/oauth/app-log/status` | GET | OAuth 配置状态 |
| `/api/oauth/app-log/start` | GET | 跳转 OAuth 授权 |
| `/api/oauth/app-log/callback` | GET | OAuth 回调 |
| `/api/history` | GET | 历史列表 |
| `/api/history/{filename}` | GET/DELETE | 历史详情 / 删除 |
| `/api/extracted-file` | GET | 下载提取出的日志文件 |
| `/api/queue` | GET | 当前队列状态 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WORKSPACE_ROOT` | 自动检测 | 仓库根路径，用于定位 MCP 工具和知识库 |
| `PROJECT_ROOT` | 同上 | MCP `run.sh` 使用 |
| `WEB_DIAGNOSTIC_SKIP_CLAUDE` | `0`（本地）/ `1`（Docker） | 跳过 Claude CLI 检测 |

## Python 依赖

```bash
pip install -r requirements.txt
```

主要依赖：`fastapi`、`uvicorn[standard]`、`websockets`、`requests`、`python-multipart`。
