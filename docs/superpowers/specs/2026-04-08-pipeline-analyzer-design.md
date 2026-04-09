# Pipeline Analyzer：脚本预处理实时链路日志

> 日期: 2026-04-08  
> 状态: 待实现  
> 范围: 先做实时链路 (`audio-recognition`)，架构预留扩展

## 背景与目标

当前 AI 诊断实时链路时，需要自行从原始日志中通过 Grep 查找 `scene: create` / `scene: update` 等关键节点，存在三个问题：

1. **Token 消耗高** — AI 需要读大量原始日志行并逐一分类
2. **速度慢** — 多次工具调用（extract + diagnose + N×Grep）增加延迟
3. **准确性不稳定** — AI 可能漏掉关键节点（如 Token/Session 的 `scene:` 日志）

知识库已沉淀了各模块的 success/failure pattern，`_parse_asr_records` 也证明了脚本化解析的可行性。本方案将这一模式扩展到完整的实时链路诊断。

### 优化目标

- 减少 AI token 消耗（预估 input -30~50%, output -40%）
- 加快诊断速度（去掉额外 Grep，总耗时预估 -50%）
- 提高准确性（脚本确保不漏关键节点，标记置信度供 AI 最终判定）

## 数据流

### 当前

```
extract_aibuds_logs → 全量日志文件
                   ↓
diagnose_scenario → 100 行过滤日志 + check_order + common_causes (纯文本)
                   ↓
AI Grep/分析 → 多次工具调用 → 输出 recordings[] JSON + Markdown
```

### 优化后

```
extract_aibuds_logs → 全量日志文件
                   ↓
diagnose_scenario → 100 行过滤日志 + check_order + common_causes
                  + recordings[] 结构化分析 (JSON)
                   ↓
AI 审阅/修正/补充 → 直接输出 recordings[] JSON + Markdown（零额外 Grep）
```

## 架构

### 新增模块

`tools/log-analyzer/pipeline_analyzer.py`，包含：

- **`split_recordings()`** — 从全量日志中按录音段边界切分
- **`analyze_phases()`** — 对每段日志逐 phase 匹配 success/failure pattern
- **`analyze_pipeline()`** — 入口函数，串联分割 + 阶段分析

配置从 knowledge JSON 读取（`recording_boundaries` + `phase_mapping`），不硬编码。

### 集成点

`diagnose_scenario` 在现有返回末尾追加 `--- 结构化分析 (JSON) ---` 段。不改函数签名、不改返回类型（仍是 `str`），对无配置的场景完全无影响。

## 录音段分割（RecordingSplitter）

### 边界标志

| 边界 | Tag | Pattern |
|------|-----|---------|
| 开始 | `AIBuds_Record` | `Start recording, Device ID: .*` |
| 结束（正常） | `AIBuds_Record` | `Recording stopped successfully, Device ID: .*` |
| 结束（暂停） | `AIBuds_Record` | `Recording paused successfully, Device ID: .*` |
| 结束（异常） | `AIBuds_Record` | `scene: audio_record - stop when begin, error code: .*` |

### record_id 提取

从段内 `[AIBuds_AIChannel]` 的 `scene: request - started at .* requestId: (\S+)` 提取 requestId，去尾部 `_N` 得到 `record_id`。

### 分割逻辑

1. 找到所有 `Start recording` 行，标记段开始
2. 找到对应的 stop/pause/error 行，标记段结束
3. 最后一段无结束标志 → `end_reason: "interrupted"`
4. 第一段开始前的日志归入第一段；两段之间的间隙日志归入下一段（通常是语言选择等准备动作）；最后一段结束后的日志归入最后一段
5. 若日志中无任何 `Start recording` → 整个日志作为 1 段 fallback

### 配置格式

场景 JSON 新增 `recording_boundaries` 字段：

```json
{
  "recording_boundaries": {
    "start_tag": "AIBuds_Record",
    "start_pattern": "Start recording, Device ID:",
    "end_patterns": [
      {"tag": "AIBuds_Record", "pattern": "Recording stopped successfully", "reason": "stopped"},
      {"tag": "AIBuds_Record", "pattern": "Recording paused successfully", "reason": "paused"},
      {"tag": "AIBuds_Record", "pattern": "scene: audio_record - stop when begin", "reason": "error"}
    ],
    "record_id_extraction": {
      "tag": "AIBuds_AIChannel",
      "pattern": "scene: request - started at .* requestId: (\\S+)",
      "transform": "strip_trailing_sequence"
    }
  }
}
```

### 单段输出

```json
{
  "record_id": "ej_PHONE00UrkYs7_1775540437",
  "start_time": "10:23:01.123",
  "end_time": "10:25:30.456",
  "end_reason": "stopped",
  "lines": [...]
}
```

## 阶段状态引擎（PhaseEngine）

### 产品阶段 ↔ 技术阶段映射

| 产品阶段（前端展示） | 技术阶段（knowledge phases） | 主要匹配 Tag |
|---|---|---|
| 选择设备 | *(无直接对应)* | Record, AudioInput |
| 选择语言 | *(无直接对应)* | ASR, Translate |
| 点击开始 | Token 获取与更新 + Session 池与复用 + WebSocket 连接 | Token, Session, AIChannel |
| 开始识别 | 音频采集与发送 + 转写与 NLG | AIChannel, Recognition, ASR |
| 识别结束 | 请求收尾 | AIChannel, ASR, Record |

### 配置格式

场景 JSON 新增 `phase_mapping` 字段：

```json
{
  "phase_mapping": [
    {
      "product_phase": "选择设备",
      "tags": ["AIBuds_Record", "AIBuds_AudioInput"],
      "success_pattern": "Start recording, Device ID:",
      "failure_pattern": "Device does not exist|does not support"
    },
    {
      "product_phase": "选择语言",
      "tags": ["AIBuds_ASR", "AIBuds_Translate"],
      "success_pattern": "Token create asr config model:",
      "failure_pattern": "source language is empty|target language is empty"
    },
    {
      "product_phase": "点击开始",
      "knowledge_phases": ["Token 获取与更新", "Session 池与复用", "WebSocket 连接与保活"],
      "tags": ["AIBuds_Token", "AIBuds_Session", "AIBuds_AIChannel"],
      "success_pattern": "new token success|reuse same token|create - success sessionId|stream - connected|ws - connected",
      "failure_pattern": "new token failure|endpoint.update error|pool - creation failed|pool - full|create - failed|stream - not connected"
    },
    {
      "product_phase": "开始识别",
      "knowledge_phases": ["音频采集与发送", "转写与 NLG 结果"],
      "tags": ["AIBuds_AIChannel", "AIBuds_Recognition", "AIBuds_ASR"],
      "success_pattern": "pick_data - begin|send_data - begin|transcribe - text packet|nlg - append chunk",
      "failure_pattern": "ASR_START send failed|parse protobuf failed|invalid NLG|send failed"
    },
    {
      "product_phase": "识别结束",
      "knowledge_phases": ["请求收尾"],
      "tags": ["AIBuds_AIChannel", "AIBuds_ASR", "AIBuds_Record"],
      "success_pattern": "request - finished|ASRTask ended.*Error: None|Recording stopped successfully",
      "failure_pattern": "timer - timeout|server error|ASRTask ended.*Error: (?!None)"
    }
  ]
}
```

### 匹配算法

对每段录音的每个产品阶段：

1. 过滤该段 `lines[]` 中 tag 属于本阶段 `tags` 的行
2. 用 `failure_pattern` 正则扫描，收集失败证据
3. 用 `success_pattern` 正则扫描，收集成功证据
4. 判定规则：
   - 有 failure 匹配 → `status: "failed"`, `confidence: "high"`
   - 仅有 success 匹配 → `status: "success"`, `confidence: "high"`
   - 有相关 tag 行但无 pattern 命中 → `status: "success"`, `confidence: "low"`
   - 无任何相关 tag 行 → `status: "skipped"`, `confidence: "high"`
5. `detail`：拼接最多 3 条关键证据行（时间戳 + 原文前 80 字符）
6. `time`：取该阶段第一条匹配行的时间戳

### recording 级别 status

由最差阶段决定：任一 `failed` → `failed`；全部 `success`/`skipped` 但最后一段无结束 → `interrupted`；否则 `success`。

### 单段输出

```json
{
  "record_id": "ej_PHONE00UrkYs7_1775540437",
  "status": "failed",
  "phases": [
    {
      "name": "点击开始",
      "status": "failed",
      "confidence": "high",
      "time": "10:23:02.500",
      "detail": "[10:23:02.500] scene: create - new token failure",
      "evidence": [
        {"time": "10:23:02.500", "tag": "AIBuds_Token", "msg": "scene: create - new token failure", "match": "failure"}
      ]
    }
  ]
}
```

## `diagnose_scenario` 集成

在 `tools/log-analyzer/server.py` 的 `diagnose_scenario` 现有输出末尾追加：

```python
if best.get("recording_boundaries") and best.get("phase_mapping"):
    from pipeline_analyzer import analyze_pipeline
    pipeline_result = analyze_pipeline(file_path, best)
    if pipeline_result:
        out.append("")
        out.append("--- 结构化分析 (JSON) ---")
        out.append(json.dumps(pipeline_result, ensure_ascii=False, indent=2))
```

`pipeline_result` 包含 `recordings[]` 和 `summary`（统计信息）。

## `web-diagnostic/server.py` 适配

### 解析 pipeline_result

在工具结果回调中，从 `diagnose_scenario` 返回的文本中提取 `--- 结构化分析 (JSON) ---` 后的 JSON 块，保存为 `server_pipeline_data`。

### Fallback 策略

当 AI 最终输出 `template_data` 时：

- AI 输出了 `recordings` → 以 AI 版本为准（AI 可能修正了 confidence: low 的阶段）
- AI 未输出 `recordings` → 回退使用 `server_pipeline_data` 作为 fallback
- 两种情况下 `_parse_asr_records` + `_merge_asr_into_recordings` 逻辑不变

### 提示词适配

`_build_template_prompt` 增加说明：

```
[重要] diagnose_scenario 的返回中已包含「结构化分析 (JSON)」段，
其中的 recordings[] 是脚本根据日志 pattern 自动生成的阶段判定。

你的任务：
1. 审阅每个 recording 的 phases，尤其是 confidence: "low" 的阶段
2. 如需修正，直接在你输出的 JSON 中覆盖对应阶段的 status/detail
3. confidence: "high" 的阶段可直接采纳，无需重复验证
4. 输出完整的 recordings[] JSON 代码块（格式不变）
5. 继续输出 Markdown 诊断报告

你**不需要**使用 Grep 或其他工具搜索日志，所有关键证据已在 evidence 中提供。
```

## 测试策略

### 单元测试 (`tools/log-analyzer/tests/test_pipeline_analyzer.py`)

1. **RecordingSplitter**
   - 单段录音：1 组 start/stop → 1 recording
   - 多段录音：3 组交错 → 3 recordings，record_id 正确
   - 中断录音：有 start 无 stop → `end_reason: "interrupted"`
   - 空日志 / 无 Record 标志 → fallback 为 1 段

2. **PhaseEngine**
   - 全部 success → 5 阶段 `success/high`
   - 单阶段 failed → 对应阶段 `failed/high`
   - 无匹配行 → `skipped/high`
   - 低置信度 → `success/low`
   - evidence 最多 3 条

### 集成测试 (`web-diagnostic/tests/`)

- `diagnose_scenario` 返回含 `结构化分析 (JSON)` 且可解析
- `web-diagnostic/server.py` 能提取 pipeline_result 并作为 fallback

## 改动文件清单

| 文件 | 改动 |
|------|------|
| `tools/log-analyzer/pipeline_analyzer.py` | **新增** |
| `tools/log-analyzer/knowledge/aivoice-streaming-channel.json` | **修改** — 新增 `recording_boundaries` + `phase_mapping` |
| `tools/log-analyzer/server.py` | **修改** — `diagnose_scenario` 末尾调用 `analyze_pipeline` |
| `web-diagnostic/server.py` | **修改** — 解析 pipeline_result fallback + 提示词适配 |
| `tools/log-analyzer/tests/test_pipeline_analyzer.py` | **新增** |
| `web-diagnostic/tests/test_asr_parsing.py` | **修改** — 增加集成测试 |

### 不改动

- `web-diagnostic/frontend/` — `recordings[]` schema 不变
- `web-diagnostic/claude_runner.py` — 不改 allowed_tools / system prompt
- 其他 knowledge JSON — 暂不添加 `recording_boundaries`/`phase_mapping`
