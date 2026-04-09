# Web Diagnostic 前端架构升级与 UI 精细化设计

**日期**：2026-04-03
**状态**：待实施
**范围**：`web-diagnostic` 前端工程化 + UI/UX 改进 + Docker 部署

---

## 1. 背景与目标

### 1.1 现状

- 前端为单个 `static/index.html`（1444 行），包含全部 HTML + CSS + JavaScript。
- 使用 Tailwind CDN、marked.js CDN、highlight.js CDN，无构建步骤。
- 暗色赛博朋克风格，功能完整（SSO、工单获取、自动/手动上传、实时终端、诊断报告、知识库归纳、历史记录）。
- Dockerfile 存在但依赖缺失的 `docker/` 子目录，本地无法构建。

### 1.2 目标

1. **工程架构升级**：Vite + ES Modules + Tailwind PostCSS，单文件拆分为组件化结构。
2. **UI/UX 精细化**：保留赛博朋克暗黑风格，改进布局、交互、响应式。
3. **Docker 部署**：多阶段构建，docker-compose 一键启动，消除对缺失文件的依赖。

### 1.3 约束

- 不引入 React/Vue/Svelte 等框架，保持纯 Vanilla JS。
- 后端 API 和 WebSocket 协议不变。
- 现有 `static/index.html` 保留为回退，不删除。

---

## 2. 工程架构

### 2.1 目录结构

```
web-diagnostic/
├── frontend/
│   ├── index.html               ← 入口（精简骨架）
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── src/
│   │   ├── main.js              ← 入口：初始化组件、连接 WebSocket
│   │   ├── style.css            ← Tailwind 指令 + 自定义样式
│   │   ├── core/
│   │   │   ├── component.js     ← 轻量组件基类
│   │   │   ├── store.js         ← 全局状态管理（发布-订阅）
│   │   │   └── ws.js            ← WebSocket 连接与消息路由
│   │   ├── views/
│   │   │   ├── idle.js          ← 首页视图
│   │   │   ├── analyzing.js     ← 分析中视图
│   │   │   └── result.js        ← 结果视图
│   │   ├── components/
│   │   │   ├── header.js        ← 顶部状态栏
│   │   │   ├── terminal.js      ← 实时终端日志
│   │   │   ├── file-upload.js   ← 拖拽上传
│   │   │   ├── sso-panel.js     ← SSO 登录态面板
│   │   │   ├── task-queue.js    ← 任务队列
│   │   │   ├── history-list.js  ← 历史记录
│   │   │   ├── progress-bar.js  ← 进度条
│   │   │   ├── steps-panel.js   ← 工具调用步骤
│   │   │   ├── report.js        ← Markdown 报告渲染
│   │   │   └── kb-modal.js      ← 知识库归纳抽屉
│   │   └── utils/
│   │       ├── markdown.js      ← marked + highlight.js 封装
│   │       └── helpers.js       ← esc、copyToClipboard 等
│   └── dist/                    ← Vite 构建产物（gitignore）
├── server.py                    ← 静态文件路径调整
├── Dockerfile                   ← 重写：多阶段构建
├── docker-compose.yml           ← 新增
├── static/index.html            ← 保留：回退方案
└── ...
```

### 2.2 组件基类（component.js）

约 50 行的轻量基类，提供：

- `render()` → 返回 HTML 字符串
- `mount()` → 渲染 + 调用 `onMount()` 绑定事件
- `update()` → 重新渲染 + 重新绑定
- `subscribe(key, callback)` → 订阅 store 变化，组件销毁时自动清理
- `destroy()` → 取消订阅 + 清空容器

不使用 Web Components / Shadow DOM，保持全局 Tailwind 样式。

### 2.3 状态管理（store.js）

极简发布-订阅模式：

- `get(key)` / `set(key, value)` 读写状态
- `on(key, callback)` 监听变化，返回取消函数
- `on('*', callback)` 监听所有变化

全局状态集中管理，替代现有的散布全局变量（`ws`、`uploadedFilePath`、`ssoVerified`、`taskQueue` 等）。

组件通过 `subscribe()` 监听关注的状态变化，自动调用 `update()` 重新渲染。

### 2.4 WebSocket 封装（ws.js）

- 连接管理：自动重连（指数退避）、状态广播到 store
- 消息路由：按 `msg.type` 分发到注册的 handler
- 发送封装：`send(payload)` 自动检查连接状态

### 2.5 构建与依赖

| 工具 | 用途 |
|------|------|
| Vite | 开发热更新 + 生产构建 |
| Tailwind CSS + PostCSS | 样式编译（告别 CDN） |
| marked | Markdown 渲染（npm 安装） |
| highlight.js | 代码高亮（npm 安装） |

开发时 Vite dev server（port 5173）代理 `/api/*` 和 `/ws/*` 到 FastAPI（port 8080）。

生产构建产物：`dist/index.html` + `dist/assets/*.js` + `dist/assets/*.css`。

---

## 3. UI/UX 改进

### 3.1 首页（Idle View）

布局从纵向堆叠改为双栏卡片式：

- 左侧（3/5 宽）：新建诊断区
  - SSO 面板默认折叠（已验证时显示一行绿色状态，点击展开）
  - 日志来源切换（自动下载 / 手动上传）
  - 用户信息面板（仅自动下载模式显示，可折叠）
  - 问题描述 + 场景选择 + 启动按钮
- 右侧（2/5 宽）：队列与历史区（SSO 验证前隐藏，保持现有门控逻辑）
  - 任务队列表格
  - 历史记录卡片列表（双行：标题 + 时间/状态，hover 预览摘要）

### 3.2 分析中（Analyzing View）

从左右两栏改为三栏：

- 左栏（w-56）：任务信息 + 进度条 + 已用时 + 终止按钮
- 中央（flex-1）：实时终端日志（主体视觉焦点，暗背景 + 扫描线）
- 右栏（w-56）：工具调用步骤时间线（从左侧移出，给终端更多空间）

### 3.3 结果页（Result View）

- 状态横幅 + 操作按钮做成 sticky，报告滚动时始终可见
- 报告内容区增加自动生成的目录导航（从 h2/h3 提取）
- 知识库归纳改为右侧抽屉式滑出

### 3.4 视觉精细化

| 项目 | 现有 | 改进 |
|------|------|------|
| 扫描线/网格 | `rgba(…, 0.03/0.04)` | 降低到 `0.015`，更微妙 |
| 面板边框 | `border-primary/20` | 统一 `/10`，交互态 `/30` |
| 卡片背景 | 纯色 `bg-surface` | 增加 `backdrop-blur-sm` |
| 发光效果 | 多处 `box-shadow` + `text-shadow` | 只在关键元素保留，减少视觉疲劳 |
| 脉冲动画 | 1.5s 快速闪烁 | 2.5s + `ease-in-out`，更柔和 |
| 视图切换 | `hidden` 硬切 | `opacity + translateY` 过渡动画（300ms） |

### 3.5 交互改进

- **文件上传**：拖拽时边框高亮 + 中心图标放大 + 背景脉冲
- **终端日志**：每条日志 hover 高亮，不同 tag 颜色前缀保持
- **SSO 面板**：验证通过后 300ms 动画折叠
- **响应式**：移动端（<768px）侧栏折叠，分析视图切为纵向

---

## 4. Docker 部署

### 4.1 多阶段 Dockerfile

```
Stage 1: frontend-build (node:20-alpine)
  - COPY frontend/ 并 npm ci && npm run build
  - 产出 frontend/dist/

Stage 2: runtime (python:3.12-slim-bookworm)
  - 安装 bash、curl、git
  - COPY frontend/dist/ 到静态目录
  - COPY server.py + tools/log-analyzer
  - pip install 后端依赖
  - 可选：ARG INSTALL_CLAUDE=1 安装 Claude CLI
```

### 4.2 设计要点

- 去除对 `docker/` 子目录的依赖（`minimal-claude-code`、`workspace.mcp.json`、`managed-mcp.json`、`claude-settings.tuya.example.json`）
- Claude 配置改为运行时环境变量和卷挂载
- MCP 配置通过 `start.sh` 自动生成或环境变量 `MCP_CONFIG_PATH` 指定
- 前端构建阶段不进入最终镜像

### 4.3 docker-compose.yml

```yaml
services:
  web-diagnostic:
    build:
      context: .
      dockerfile: web-diagnostic/Dockerfile
    ports:
      - "8080:8080"
    environment:
      - WEB_DIAGNOSTIC_SKIP_CLAUDE=1
    volumes:
      - ./tools/log-analyzer/knowledge:/workspace/tools/log-analyzer/knowledge
      - diagnostic-data:/workspace/web-diagnostic/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  diagnostic-data:
```

- knowledge 目录挂载：知识库更新后不用重建镜像
- data 持久卷：历史记录和上传日志持久化
- 默认跳过 Claude：纯前端 + API 模式

### 4.4 开发工作流

```bash
# 本地开发
cd web-diagnostic/frontend && npm run dev     # Vite dev server, port 5173
cd web-diagnostic && python server.py          # FastAPI, port 8080

# 生产构建
cd web-diagnostic/frontend && npm run build    # → dist/
docker compose up --build                      # 构建并启动
```

### 4.5 server.py 改动

- 生产模式：从 `frontend/dist/` serve 静态文件
- 开发模式（`DEV=1`）：Vite dev server 处理前端
- 兼容回退：`frontend/dist/` 不存在时回退到 `static/index.html`

---

## 5. 迁移策略

- **渐进式**：`static/index.html` 保留不删，`server.py` 优先 serve `frontend/dist/`
- **功能对齐**：新前端 1:1 覆盖现有全部功能后才算完成
- **零后端改动**：API 路由和 WebSocket 协议不变

---

## 6. 交付清单

| 序号 | 交付物 | 类型 | 说明 |
|------|--------|------|------|
| 1 | `frontend/` 目录 | 新增 | Vite 项目、所有组件 |
| 2 | `frontend/src/core/*.js` | 新增 | 组件基类 + 状态管理 + WebSocket |
| 3 | `frontend/src/views/*.js` | 新增 | 3 个视图组件 |
| 4 | `frontend/src/components/*.js` | 新增 | 10 个 UI 组件 |
| 5 | `frontend/src/utils/*.js` | 新增 | Markdown 渲染 + 工具函数 |
| 6 | `Dockerfile` | 重写 | 多阶段构建 |
| 7 | `docker-compose.yml` | 新增 | 一键部署 |
| 8 | `server.py` | 修改 | 静态文件路径调整 |

---

## 7. 不在本次范围

- 不重构后端 `server.py`（仅改静态文件路径）
- 不改 WebSocket 消息协议
- 不加新功能（先迁移 1:1 对齐，再增强）
- 不做 CI/CD
- 不做 HTTPS / nginx 反代
- 不删除 `static/index.html`
