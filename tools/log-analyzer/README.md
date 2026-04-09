# DeviceCore Log Analyzer

IoT 设备日志分析工具，基于 MCP（Model Context Protocol）为 Cursor / Claude Code 提供日志诊断能力。

## 功能

### 日志搜索与下载

- **工单搜索**：通过 ticketId 搜索用户反馈日志
- **UID 搜索**：通过用户 UID 搜索日志（自动识别区域）
- **日志下载**：自动下载日志文件到本地，供后续分析

### 日志分析

- **TAG 索引**：自动扫描 SDK 代码中的日志调用（`L.i/d/w/e`），构建 TAG→模块→文件 的映射
- **日志摘要**：支持解析大日志文件，输出统计概览
- **智能过滤**：按 TAG（模糊匹配）、级别、时间范围过滤日志
- **错误上下文**：提取每条 Error 前后 N 秒的日志，还原事件现场
- **代码关联**：从日志 TAG 追溯到具体的源代码文件和行号

## 安装

```bash
cd tools/log-analyzer
pip install -r requirements.txt
```

需要 Python 3.10+。

可选依赖（自动读取 Chrome 登录态）：

```bash
pip install browsercookie
```

## 认证配置

日志搜索/下载功能需要内部平台的 SSO 登录态，支持两种方式：

1. **自动读取浏览器 Cookie**（推荐）：在 Chrome 中登录 `https://app-log-cn.tuya-inc.com:7799/`，工具自动读取 Cookie
2. **环境变量**：`export SSO_USER_TOKEN=<your_token>`

## 在 Cursor / Claude Code 中使用

工具通过 MCP 配置自动注册（Cursor: `.cursor/mcp.json`，Claude Code: `.claude/settings.json`）。

在 Agent 对话中：
- 输入 `/analyze-log` 触发完整分析流程
- 或直接描述问题：
  - "帮我查一下工单 3977372e 的日志"
  - "用户 ay12345 蓝牙连接失败，帮我看下日志"
  - "分析这个日志文件，设备离线了"（拖入文件）

AI 会自动调用以下 MCP 工具：

| 工具 | 作用 |
|------|------|
| **`quick_diagnosis`** | **一键诊断（首选）** — 摘要 + Error 上下文 + TAG 代码关联 |
| **`diagnose_scenario`** | **场景化诊断** — 按问题类型加载知识库、过滤日志 |
| `search_logs` | 通过 ticketId / uid / 手机号 / 邮箱搜索日志 |
| `download_log` | 下载日志文件到本地 |
| `build_tag_index` | 构建 TAG 索引（支持常量解析，覆盖 500+ TAG） |
| `log_summary` | 日志统计摘要 |
| `filter_logs` | 按条件过滤日志 |
| `error_context` | Error 前后上下文 |
| `tag_lookup` | TAG→代码位置查找 |
| `search_related_tags` | 搜索相关 TAG |

## 区域支持

| 区域码 | 说明 | UID 前缀 |
|--------|------|----------|
| cn | 中国 | ay |
| eu | 欧洲 | eu |
| us | 美国西 | az |
| ue | 美国东 | ue |
| in | 印度 | in |
| we | 西欧 | we |

UID 搜索时自动根据前缀推断区域，也可手动指定 `region` 参数。

## 独立使用

TAG 索引扫描器可独立运行：

```bash
python tag_scanner.py /path/to/TuyaDeviceCoreKit
```

MCP Server 也可独立启动：

```bash
python server.py
```

## 日志格式

支持三种格式的自动识别：

**JSON Lines**：
```json
{"type":"t","time":"2026-03-09 15:23:10.506","payload":{"level":"Info","tag":"Business_ThingNetworkMonitor","msg":"onCallStart: false 10 21"}}
```

**格式化 Logcat**：
```
2026-03-09 18:30:09.291 [Info] <Business_ThingNetworkMonitor> onCallStart: true 0 0
```

**Android Studio Logcat**：
```
03-05 13:07:34.003 16654 16654 D Thing   : GwTransferModel try to startService
```

## 故障知识库

`knowledge/` 目录包含按场景组织的诊断知识：

| 场景文件 | 覆盖问题 |
|----------|----------|
| `ble-connection.json` | BLE 连接/断连/配对 |
| `ble-provisioning.json` | BLE 配网/激活 |
| `mesh-network.json` | Mesh 组网/控制 |
| `mqtt-connection.json` | MQTT 连接/断连 |
| `device-offline.json` | 设备离线/在线 |
| `ota-upgrade.json` | OTA 固件升级 |
| `hardware-activate.json` | AP/EZ 配网激活 |

`diagnose_scenario` 工具会根据问题描述自动匹配场景。

## 知识库维护

知识库 JSON 文件包含 `_meta` 字段，记录更新日期和适用的 SDK 版本：

```json
{
  "_meta": {
    "updated": "2026-03-11",
    "sdk_version": "7.4.0"
  },
  "id": "ble-connection",
  ...
}
```

使用验证脚本检查知识库有效性：

```bash
# 检查所有知识库引用的 TAG 是否仍存在于代码中
./verify-knowledge.sh

# 自定义过期天数（默认 180 天）
./verify-knowledge.sh --stale-days 90

# 指定项目根目录
./verify-knowledge.sh /path/to/TuyaDeviceCoreKit
```

也可通过 `./ai-setup.sh --verify` 一键自检（包含知识库验证）。

## 文件结构

```
tools/log-analyzer/
├── server.py              # MCP Server 主入口
├── tag_scanner.py         # TAG 索引扫描器（支持常量解析）
├── log_parser.py          # 日志解析引擎
├── log_downloader.py      # 日志搜索与下载
├── verify-knowledge.sh    # 知识库有效性验证脚本
├── run.sh                 # MCP Server 启动脚本（自动创建 venv）
├── requirements.txt       # 依赖
├── knowledge/             # 故障诊断知识库（含 _meta 版本信息）
│   ├── ble-connection.json
│   ├── ble-provisioning.json
│   └── ...
├── data/
│   ├── tag-index.json     # TAG 索引（自动生成）
│   └── *.xlog             # 下载的日志文件（自动下载）
└── README.md              # 本文件
```
