# AIBuds 知识库刷新与 Objective-C 日志扫描设计

**日期**：2026-04-03  
**状态**：待实施  
**范围**：`tuya-log-analysis` 日志排查系统 — AIBuds iOS 模块知识库体系

---

## 1. 背景与目标

### 1.1 现状

- `tuya-log-analysis` 的 `tag_scanner.py` 只支持 Java/Kotlin 的 `L.i/d/w/e` 日志调用，无法覆盖 iOS 端 AIBuds 日志。
- iOS 端两个核心模块 `ThingAudioRecordModule` 和 `ThingAutomaticSpeechRecognitionModule` 使用 `AIBudsLogDebug/Info/Error(ThingAIBudsLogModule*, @"...")` 范式，当前版本（v2.9.0）新增了大量日志 Tag 和日志语句。
- 现有 AIVoice 知识库（`knowledge/aivoice-*.json`）按场景组织，但模块级基础知识缺乏系统化沉淀，每次版本迭代需要大量人工搬运。

### 1.2 目标

1. **补齐 Objective-C 扫描能力**：自动扫描 iOS AIBuds 日志，产出结构化索引与模块目录。
2. **建立两层知识模型**：底层按 `AIBuds_*` 模块沉淀基础知识，上层按场景编排排查流程。
3. **支持可重复刷新**：每次版本迭代后可重新跑扫描 → 生成 → 校验流程，人工只做 review。

---

## 2. 目标架构

```
aibuds.mdc（白名单）
       ↓ 提取模块列表与宏名映射
ObjC 源码扫描（aibuds_scanner.py）
       ↓ 产出
data/aibuds-module-catalog.json（中间产物）
       ↓ 自动生成 + 人工 review
knowledge/modules/*.json（模块知识）
       ↑ 被引用
knowledge/aivoice-*.json（场景知识）
       ↑ 被调用
MCP: diagnose_scenario / quick_diagnosis
```

四层职责：

| 层 | 职责 | 更新方式 |
|----|------|----------|
| 扫描层 | 从源码提取日志调用结构 | 自动 |
| 模块知识层 | 按 AIBuds_* 模块沉淀信号与关联 | 自动生成 + 人工补充 |
| 场景知识层 | 按故障场景编排排查顺序 | 人工为主，引用模块知识 |
| 校验层 | 检查引用完整性与时效性 | 自动 |

---

## 3. 扫描器设计（aibuds_scanner.py）

### 3.1 扫描范围

| 仓库 | 扫描路径 | 文件类型 |
|------|----------|----------|
| ThingAudioRecordModule | `ThingAudioRecordModule/Classes/**` | `.m`, `.mm` |
| ThingAutomaticSpeechRecognitionModule | `ThingAutomaticSpeechRecognitionModule/Classes/**` | `.m`, `.mm` |

### 3.2 识别模式

目标日志调用格式：

```objc
AIBudsLogInfo(ThingAIBudsLogModuleRecord, @"Record started - deviceId: %@", deviceId);
AIBudsLogDebug(ThingAIBudsLogModuleASR, @"scene: transcribe - result: %@", text);
AIBudsLogError(ThingAIBudsLogModuleTranslate, @"Translate failed - error: %@", error);
```

提取字段：

- **日志级别**：`Debug / Info / Error`（从函数名 `AIBudsLogDebug/Info/Error` 得出）
- **模块宏名**：`ThingAIBudsLogModuleXxx`
- **日志模板**：`@"..."` 中的静态文本，保留 `%@`、`%ld` 等占位符
- **子场景**：从日志模板中提取 `scene: xxx` 前缀
- **源码位置**：文件名、类名（从 `@implementation` 提取）、行号

### 3.3 模块名解析

不硬编码映射表，而是从 `aibuds.mdc` 白名单动态推导：

1. 从 `aibuds.mdc` 的「核心模块标签」列表提取标签名，如 `AIBuds_Record`
2. 按命名规则推导宏名：`AIBuds_Record` → `ThingAIBudsLogModuleRecord`
3. 扫描时用宏名匹配，映射回真实标签

推导规则：`[AIBuds_Xxx]` → 去掉方括号和 `AIBuds_` 前缀 → 首字母大写保留 → 拼接 `ThingAIBudsLogModule` 前缀。

特殊情况（如 `AIBuds_AIChannel` → `ThingAIBudsLogModuleAIChannel`）在白名单侧已经隐含，无需额外处理。

### 3.4 日志模板归一化

- 去掉 `@"` 和 `"` 外壳
- 保留 `%@`、`%ld` 等格式占位符
- 识别并提取 `scene: xxx -` 前缀
- 同一模块下完全相同的模板去重
- 支持多行调用（`@"..."` 跨行拼接）

### 3.5 候选信号自动分类

基于关键词做保守分类，打标而不下结论：

| 候选类型 | 匹配关键词 |
|----------|-----------|
| `success_candidates` | `success`, `ready`, `connected`, `begin`, `started`, `resumed`, `completed` |
| `failure_candidates` | `fail`, `failed`, `error`, `exception`, `invalid`, `empty`, `timeout`, `abort` |
| `lifecycle_candidates` | `start`, `stop`, `end`, `create`, `destroy`, `dealloc`, `pause`, `resume`, `init` |
| `noise_candidates` | 纯参数打印、buffer/length 类、重复性极高的模板 |

---

## 4. 中间产物

### 4.1 data/aibuds-module-catalog.json

扫描器的直接输出，不进知识库目录：

```json
{
  "_meta": {
    "updated": "2026-04-03",
    "scanned_repos": [
      "ThingAudioRecordModule",
      "ThingAutomaticSpeechRecognitionModule"
    ],
    "total_modules_found": 28,
    "total_log_calls": 1200
  },
  "modules": {
    "AIBuds_Record": {
      "files": [
        {
          "path": "ThingAudioRecordManager.m",
          "class": "ThingAudioRecordManager",
          "log_count": 45
        }
      ],
      "log_count": 99,
      "by_level": { "info": 60, "debug": 25, "error": 14 },
      "scenes": ["start", "stop", "pause"],
      "templates": [
        {
          "level": "info",
          "scene": "start",
          "template": "Start recording - Device ID: %@",
          "file": "ThingAudioRecordManager.m",
          "line": 210,
          "candidate_type": "success_candidates"
        }
      ]
    }
  }
}
```

### 4.2 与现有 tag-index.json 的关系

- `tag-index.json` 继续承担通用 TAG → 文件/类/行号索引，服务 `tag_lookup / search_related_tags`
- `aibuds-module-catalog.json` 是 AIBuds 专用的模块维度视图，服务知识库生成
- 两者独立维护，互不影响

---

## 5. 模块知识文件结构

### 5.1 目录

```
knowledge/modules/
├── _catalog.json              ← 模块总览（自动生成）
├── aibuds-record.json
├── aibuds-db.json
├── aibuds-asr.json
├── aibuds-token.json
├── aibuds-session.json
├── aibuds-aichannel.json
├── aibuds-transfer.json
├── aibuds-translate.json
├── aibuds-mqtt.json
├── ...                        ← 只为有日志的模块生成
```

### 5.2 单个模块知识文件 Schema

```json
{
  "_meta": {
    "updated": "2026-04-03",
    "source_repos": ["ThingAudioRecordModule"],
    "auto_generated": true,
    "human_reviewed": false
  },
  "module": "AIBuds_Record",
  "description": "录音管理模块，负责录音的创建、暂停、恢复、停止等生命周期",
  "source_files": [
    "ThingAudioRecordManager.m",
    "ThingAudioRecordTransferTask.m"
  ],
  "related_modules": ["AIBuds_Transfer", "AIBuds_AudioInput", "AIBuds_Token"],
  "scenes": ["start", "stop", "pause", "resume"],
  "log_stats": {
    "total": 99,
    "by_level": { "info": 60, "debug": 25, "error": 14 }
  },
  "success_signals": [
    {
      "pattern": "Start recording.*Device ID",
      "level": "info",
      "description": "录音成功开始",
      "source": "auto"
    }
  ],
  "failure_signals": [
    {
      "pattern": "source language is empty",
      "level": "error",
      "description": "源语言未设置",
      "cause": "录音前未选择语言",
      "source": "auto"
    }
  ],
  "lifecycle_signals": [
    {
      "pattern": "Transcription task paused",
      "level": "info",
      "description": "转写任务暂停",
      "source": "auto"
    }
  ],
  "noise_patterns": ["buffer length"]
}
```

### 5.3 `source` 字段与增量更新

- `source: "auto"`：扫描器自动产出，每次刷新时允许覆盖
- `source: "human"`：人工补充，扫描器不触碰
- 新增模块：自动生成骨架文件（`human_reviewed: false`）
- 消失模块：不自动删除，标记 `"deprecated": true`

### 5.4 _catalog.json

模块总览，由扫描器自动生成：

```json
{
  "_meta": {
    "updated": "2026-04-03",
    "total_modules": 38,
    "modules_with_logs": 28,
    "total_log_calls": 1200
  },
  "modules": {
    "AIBuds_Record": {
      "file_count": 5,
      "log_count": 99,
      "levels": ["info", "debug", "error"],
      "scenes": ["start", "stop", "pause", "resume"],
      "knowledge_file": "modules/aibuds-record.json"
    }
  }
}
```

---

## 6. 场景知识文件更新

### 6.1 结构变化

现有场景文件（如 `aivoice-recording.json`）新增 `module_refs` 字段：

```json
{
  "id": "aivoice-recording",
  "name": "AIVoice 录音问题",
  "module_refs": ["AIBuds_Record", "AIBuds_Transfer", "AIBuds_AudioInput", "AIBuds_Token"],
  "primary_tags": ["AIBuds_Record", "AIBuds_Transfer", "AIBuds_AudioInput"],
  "secondary_tags": ["AIBuds_ASR", "AIBuds_DB"],
  "phases": [...],
  "check_order": [...],
  "common_causes": [...]
}
```

`module_refs` 告知排查工具：匹配此场景时需加载哪些模块知识文件。

### 6.2 向后兼容

- `module_refs` 为新增可选字段，不影响现有 `diagnose_scenario` 的匹配逻辑
- `primary_tags / secondary_tags / phases / common_causes` 结构不变
- `phases` 中的 `success_pattern / failure_pattern` 可继续独立维护，也可引用模块知识

### 6.3 本次需更新的场景文件

| 场景文件 | 更新内容 |
|----------|----------|
| `aivoice-recording.json` | 刷新 pattern、补充 module_refs |
| `aivoice-transcription.json` | 刷新 pattern、补充 module_refs |
| `aivoice-translation.json` | 刷新 pattern、补充 module_refs |
| `aivoice-streaming-channel.json` | 刷新 pattern、补充 module_refs |
| `aivoice-file-transfer.json` | 刷新 pattern、补充 module_refs |
| `aivoice-cloud-upload.json` | 刷新 pattern、补充 module_refs |

---

## 7. 校验与刷新机制

### 7.1 标准刷新流程

每次版本迭代后执行：

```
1. 运行 aibuds_scanner.py → 产出 data/aibuds-module-catalog.json
2. 对比上次 catalog → 发现新增/消失模块日志
3. 自动生成/更新 knowledge/modules/*.json（仅覆盖 source: auto）
4. 校验场景文件引用完整性
5. 人工 review 生成结果，补充 source: human 条目
```

### 7.2 校验规则（扩展 verify-knowledge.sh）

| 检查项 | 说明 |
|--------|------|
| 模块引用完整性 | 场景 `module_refs / primary_tags` 引用的模块在 `modules/` 下有对应知识文件 |
| 白名单一致性 | 模块知识的 `module` 字段在 `aibuds.mdc` 白名单内 |
| 源码存在性 | 模块知识的 `source_files` 仍存在于源码仓库 |
| 覆盖率提醒 | 扫描发现日志但无对应知识文件的模块列表 |
| 时效性 | `_meta.updated` 过期检查（沿用现有逻辑） |

### 7.3 MCP 工具入口

- `refresh_tag_index`：不变，仍负责通用索引
- `refresh_aibuds_catalog`（新增）：运行 Objective-C 扫描，产出 catalog
- `refresh_aibuds_knowledge`（新增）：扫描 + 生成模块知识 + 校验，一键完成

---

## 8. 交付清单

| 序号 | 交付物 | 类型 | 说明 |
|------|--------|------|------|
| 1 | `tools/log-analyzer/aibuds_scanner.py` | 新文件 | Objective-C AIBuds 日志扫描器 |
| 2 | `tools/log-analyzer/data/aibuds-module-catalog.json` | 自动生成 | 模块扫描中间产物 |
| 3 | `tools/log-analyzer/knowledge/modules/_catalog.json` | 自动生成 | 模块总览 |
| 4 | `tools/log-analyzer/knowledge/modules/aibuds-*.json` | 自动+人工 | 各模块知识文件 |
| 5 | `tools/log-analyzer/knowledge/aivoice-*.json` | 修改 | 场景文件增加 module_refs，刷新 pattern |
| 6 | `tools/log-analyzer/server.py` | 修改 | 注册新 MCP 工具 |
| 7 | `tools/log-analyzer/verify-knowledge.sh` | 修改 | 新增模块引用校验 |
| 8 | `docs/ENGINEERING_GUIDE.md` | 修改 | 补充两层知识维护流程 |

---

## 9. 不在本次范围

- 不改 `diagnose_scenario` 的匹配逻辑（场景文件结构向后兼容）
- 不做 Web 端知识库编辑 UI
- 不做 CI 自动触发扫描（留到下一期）
- 不覆盖 `TUniAudioDetectManager` 等其他仓库（本次只扫两个仓库）
- 不改 `tag-index.json` 的 schema
- 不做跨模块依赖图自动推导
