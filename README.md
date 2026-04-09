# device-core-ai-toolkit

DeviceCore SDK 的 AI 开发工具配置，支持 Cursor 和 Claude Code 双工具。

**工程架构与运维指引**（架构图、MCP 清单、工作流、知识库维护）：见 [docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md)。

## 目录结构

```
cursor/                          # Cursor 配置（部署到 .cursor/）
├── rules/                       # MDC 规则（项目概览、模块边界、构建命令、日志诊断）
├── skills/                      # Agent Skills（分支管理、依赖切换、日志分析、发版、提交）
├── commands/                    # 自定义命令（PR、Review、上传、依赖切换、日志分析）
├── hooks/                       # 钩子脚本（API 边界检查）
└── mcp.json                     # MCP 服务配置

claude-code/                     # Claude Code 配置（部署到 .claude/）
├── CLAUDE.md                    # Claude Code 补充指令（基础信息引用根目录 AGENTS.md）
├── rules/                       # 规则（模块边界、构建命令补充、日志诊断）
├── commands/  → ../cursor/commands   # 共享命令（符号链接）
├── skills/    → ../cursor/skills     # 共享技能（符号链接）
└── settings.json                # MCP + Hooks 配置

tools/                           # 共享 MCP 工具
└── log-analyzer/                # 日志分析 MCP 服务
    ├── server.py                # MCP Server 主入口
    ├── tag_scanner.py           # TAG 索引扫描器
    ├── log_parser.py            # 日志解析引擎（通用）
    ├── log_downloader.py        # 日志搜索与下载
    ├── verify-knowledge.sh      # 知识库有效性验证脚本
    └── knowledge/               # 故障场景知识库（含 _meta 版本信息）
```

### 共享策略

| 内容 | 方式 | 说明 |
|------|------|------|
| commands | 符号链接 | 格式完全兼容，零重复 |
| skills | 符号链接 | SKILL.md 已添加双兼容 frontmatter |
| rules | 独立维护 | Cursor 用 `.mdc`，Claude Code 用 `.md`，格式不同 |
| tools | 共享 | 两边的 MCP 配置都引用同一个 tools/ |

### 上下文去重原则

- 根目录 `AGENTS.md` 是项目信息的**唯一信息源**（Cursor / Claude Code 共用）
- `.claude/CLAUDE.md` **只放 Claude Code 特有的补充内容**（MCP 工具、依赖路径等），不重复 AGENTS.md 已有的信息
- `rules/*.md` 只放 AGENTS.md 中**未覆盖的补充细节**
- 组件目录下 `CLAUDE.md` → `AGENTS.md` 符号链接，零维护成本

## 使用方式

在 DeviceCore 工作区根目录执行：

```bash
./ai-setup.sh                     # 自动检测工具并配置
./ai-setup.sh --tool cursor       # 仅配置 Cursor
./ai-setup.sh --tool claude-code  # 仅配置 Claude Code
./ai-setup.sh --tool both         # 同时配置两者
./ai-setup.sh --verify            # 自检：验证配置完整性
```

脚本会自动克隆本仓库到 `.ai-config/`，并创建 symlink：
- `.cursor` → `.ai-config/cursor`（Cursor）
- `.claude` → `.ai-config/claude-code`（Claude Code）
- `tools` → `.ai-config/tools`（共享）
- 各组件目录的 `CLAUDE.md` → `AGENTS.md`（Claude Code 自动加载）

其他操作：

```bash
./ai-setup.sh --reset  # 清除并重新拉取
./ai-setup.sh --unlink # 移除所有 symlink
```

## 自检

`--verify` 检查以下项目：

| 检查项 | 说明 |
|--------|------|
| 符号链接 | `.claude`、`.cursor`、`tools` 是否指向正确目标 |
| 组件文档 | 各组件目录的 `CLAUDE.md` → `AGENTS.md` symlink 是否完整 |
| Python 环境 | venv 是否创建、fastmcp 是否安装 |
| 系统依赖 | jq（Hook 依赖）、groovy（分支管理依赖） |
| Hook 脚本 | `check-api-boundary.sh` 是否可执行 |
| TAG 索引 | 索引是否已构建、TAG 数量 |
| 知识库 | TAG 引用是否有效、是否超期未更新 |

## MCP 工具

日志分析 MCP 服务提供以下能力：

| 工具 | 说明 |
|------|------|
| `quick_diagnosis` | 一键诊断：摘要 + Error 上下文 + TAG 代码关联 |
| `diagnose_scenario` | 按问题类型加载知识库诊断 |
| `search_logs` | 按 ticketId / uid / 账号搜索日志 |
| `log_summary` | 日志统计摘要 |
| `filter_logs` | 按 TAG / 级别 / 时间过滤 |
| `error_context` | 提取 Error 前后上下文 |
| `tag_lookup` | 从 TAG 查代码位置 |

## 知识库维护

知识库 JSON 文件包含 `_meta` 字段记录版本信息：

```json
{
  "_meta": {
    "updated": "2026-03-11",
    "sdk_version": "7.4.0"
  },
  ...
}
```

验证知识库有效性：

```bash
# 检查 TAG 引用是否仍存在于代码中
tools/log-analyzer/verify-knowledge.sh

# 自定义过期天数（默认 180）
tools/log-analyzer/verify-knowledge.sh --stale-days 90
```

## Python 依赖

```bash
pip3 install -r tools/log-analyzer/requirements.txt
```
