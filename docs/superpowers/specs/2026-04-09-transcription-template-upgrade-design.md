# 离线转写/总结模板升级

> 日期: 2026-04-09
> 状态: 待实现
> 依赖: pipeline-analyzer（已实现）

## 背景与目标

当前 `offline-transcription` 模板存在以下问题：

1. **不支持多段录音** — 只有 4 个 flat phases，无法按 fileId 展示多条录音各自的转写/总结状态
2. **状态码不可读** — `transcribeStatus: 3`、MQTT `status: 100` 等数字无标注，AI 和用户都要查表
3. **特殊 Case 误判** — `TranscribeTooShort` 被客户端视为总结成功，但 AI 可能误判为错误
4. **知识缺失** — AI 曾错误地认为 ASR 文本需要客户端上报云端
5. **推理链路长** — AI 需要自己 Grep 找转写/总结各阶段的日志，token 消耗高

### 优化目标

- 按 fileId 支持多段录音的独立诊断
- 转写与总结拆开为 6 个阶段
- 状态码自动翻译（脚本 + 知识库双重保障）
- 正确处理 TranscribeTooShort 特殊 Case
- 复用 pipeline_analyzer 做脚本预处理，大幅减少 token

## 录音段切分：按 fileId 聚合

### 策略

离线转写场景没有 `Start recording` / `Recording stopped` 这样的事件边界。改用 **fileId 聚合**：

1. 扫描全量日志中 tag 属于配置 `tags` 列表的行（case-insensitive substring），正则提取 `fileId: (\d+)`
2. 按 fileId 分组，每组 = 一段录音的完整转写/总结流程
3. 组内按时间排序
4. `record_id` = fileId 字符串
5. 没有 fileId 的行归到 `_global` 兜底组

### pipeline_analyzer 扩展

在 `recording_boundaries` 配置中新增 `"mode": "group_by_field"` 分支：

```json
{
  "recording_boundaries": {
    "mode": "group_by_field",
    "field_pattern": "fileId: (\\d+)",
    "field_name": "fileId",
    "tags": ["AIBuds_Upload", "AIBuds_Transcribe", "AIBuds_MQTT", "AIBuds_DB", "AIBuds_FileUpdate"]
  }
}
```

`pipeline_analyzer.py` 增加 `_split_by_field_grouping()` 函数：
- `mode == "group_by_field"` → 走聚合逻辑
- 其他（现有实时链路）→ 走事件边界切段

### 单段输出

```json
{
  "record_id": "123456",
  "start_time": "10:23:01.123",
  "end_time": "10:25:30.456",
  "end_reason": null,
  "lines": [...]
}
```

## 6 阶段 Phase Mapping

| # | 产品阶段 | 主要 Tag | success_pattern | failure_pattern |
|---|---------|----------|-----------------|-----------------|
| 1 | 触发转写 | Upload, Transcribe | `Transcription task started successfully\|Start transcription task` | `Transcription task failed to start\|Invalid transcription parameter` |
| 2 | 收到转写MQ | MQTT | `scene: trans_mqtt - Transcription successful\|scene: trans_mqtt - Transcription status` | `scene: trans_mqtt - Transcription failed\|scene: trans_mqtt - .*Database synchronization failed` |
| 3 | 转写结果写入 | Upload, DB | `Cloud transcription result obtained successfully\|Cloud transcription data updated successfully` | `Failed to retrieve cloud transcription result\|Cloud transcription data update failed` |
| 4 | 触发总结 | Upload | `Start summarizing the task\|Summary request succeeded` | `Summary request failed\|Summary failed: file does not exist` |
| 5 | 收到总结MQ | MQTT | `scene: summary_mqtt - Summarize status.*Database synchronization succeeded` | `scene: summary_mqtt - .*Database synchronization failed` |
| 6 | 总结结果写入 | Upload, DB | `Cloud summary result retrieved successfully\|Update summary status to success\|transcription record is too short and is treated as a successful summary` | `Summary result is empty\|Failed to retrieve cloud summary results\|Update summary status failed` |

第 6 阶段 success_pattern 包含 `TranscribeTooShort` 特殊 Case，确保脚本正确识别为成功。

### 配置

```json
{
  "phase_mapping": [
    {
      "product_phase": "触发转写",
      "tags": ["AIBuds_Upload", "AIBuds_Transcribe"],
      "success_pattern": "Transcription task started successfully|Start transcription task",
      "failure_pattern": "Transcription task failed to start|Invalid transcription parameter"
    },
    {
      "product_phase": "收到转写MQ",
      "tags": ["AIBuds_MQTT"],
      "success_pattern": "scene: trans_mqtt - Transcription successful|scene: trans_mqtt - Transcription status",
      "failure_pattern": "scene: trans_mqtt - Transcription failed|scene: trans_mqtt - .*Database synchronization failed"
    },
    {
      "product_phase": "转写结果写入",
      "tags": ["AIBuds_Upload", "AIBuds_DB"],
      "success_pattern": "Cloud transcription result obtained successfully|Cloud transcription data updated successfully",
      "failure_pattern": "Failed to retrieve cloud transcription result|Cloud transcription data update failed"
    },
    {
      "product_phase": "触发总结",
      "tags": ["AIBuds_Upload"],
      "success_pattern": "Start summarizing the task|Summary request succeeded",
      "failure_pattern": "Summary request failed|Summary failed: file does not exist"
    },
    {
      "product_phase": "收到总结MQ",
      "tags": ["AIBuds_MQTT"],
      "success_pattern": "scene: summary_mqtt - Summarize status.*Database synchronization succeeded",
      "failure_pattern": "scene: summary_mqtt - .*Database synchronization failed"
    },
    {
      "product_phase": "总结结果写入",
      "tags": ["AIBuds_Upload", "AIBuds_DB"],
      "success_pattern": "Cloud summary result retrieved successfully|Update summary status to success|transcription record is too short and is treated as a successful summary",
      "failure_pattern": "Summary result is empty|Failed to retrieve cloud summary results|Update summary status failed"
    }
  ]
}
```

## 状态码翻译

### 双重保障

**脚本自动翻译**（pipeline_analyzer）：

在 `analyze_phases()` 生成 evidence 时，如果 scenario 配置了 `status_codes`，对 msg 中匹配 `(transcribeStatus|summaryStatus|translateStatus|status)\s*[:：]\s*(\d+)` 的数值从映射表追加中文标注。

例：`transcribeStatus: 3` → `transcribeStatus: 3 → (转写失败)`

**知识库映射表**（供 AI 参考）：

`aivoice-transcription.json` 新增 `status_codes` 字段：

```json
{
  "status_codes": {
    "transcribeStatus": {
      "source": "local_db",
      "mapping": {"0": "未知", "1": "转写中", "2": "转写成功", "3": "转写失败"}
    },
    "summaryStatus": {
      "source": "local_db",
      "mapping": {"0": "老数据", "1": "未知", "2": "总结中", "3": "总结成功", "4": "总结失败"}
    },
    "translateStatus": {
      "source": "local_db",
      "mapping": {"0": "老数据", "1": "未知", "2": "翻译中", "3": "翻译成功", "4": "翻译失败"}
    },
    "cloud_status": {
      "source": "mqtt",
      "mapping": {"0": "未知", "1": "初始状态", "2": "进行中", "9": "成功", "100": "失败"}
    }
  }
}
```

同时更新 `check_order` 中的状态码说明，包含完整含义。

### 实现位置

`pipeline_analyzer.py` 中在 evidence item 构建时增加 `_enrich_status_codes(msg, status_codes)` 函数，对 msg 做正则扫描和标注。通过 `analyze_phases()` 的 `scenario` 参数传入 `status_codes` 配置。

## 知识库更新

### normal_behaviors 新增

```json
{
  "pattern": "transcription record is too short and is treated as a successful summary",
  "description": "云端返回 TranscribeTooShort 错误码时，客户端约定视为总结成功，回调给小程序展示对应错误码",
  "how_to_identify": "AIBuds_Upload 日志中出现此行，后续 summaryStatus 更新为成功"
}
```

### 全局知识（_global.json 或 aivoice-transcription.json）

在 `common_causes` 或 `normal_behaviors` 中记录：

> ASR/NLG 的识别记录由云端流式通道实时产生并存储，客户端无需将 ASR 全量文本上报至云端 transcript 存储供总结服务读取。转写/总结服务直接读取云端已有的流式识别结果。

## web-diagnostic 适配

### `_TEMPLATE_PHASES` 更新

```python
"offline-transcription": {
    "label": "离线转写/总结",
    "phases": [
        {"name": "触发转写", "modules": ["Upload", "Transcribe", "DB"]},
        {"name": "收到转写MQ", "modules": ["MQTT"]},
        {"name": "转写结果写入", "modules": ["Upload", "DB"]},
        {"name": "触发总结", "modules": ["Upload"]},
        {"name": "收到总结MQ", "modules": ["MQTT"]},
        {"name": "总结结果写入", "modules": ["Upload", "DB"]},
    ],
    "recordings_by_field": True,
},
```

### fallback 范围扩展

`server_pipeline_data` 的捕获从 `task.template == "audio-recognition"` 扩展为所有模板：

```python
if server_pipeline_data is None:
    _pipeline = _extract_pipeline_result(event.tool_result)
    if _pipeline:
        server_pipeline_data = _pipeline
```

### 提示词

`_build_template_prompt` 中，当模板有 `recordings_by_field` 时：
- 输出 `recordings[]` 格式（每段 record_id = fileId）
- 加结构化分析提示（与实时链路相同）
- 加状态码参考表
- 不提 ASR record_id 去尾部 `_N` 逻辑

### 前端

`templates/index.js` 更新 `offline-transcription` 的 phases 为 6 阶段。`report.js` 无需改动（`recordings[]` schema 兼容）。

## 改动文件清单

| 文件 | 改动 |
|------|------|
| `tools/log-analyzer/knowledge/aivoice-transcription.json` | 加 `recording_boundaries` (group_by_field) + `phase_mapping` (6阶段) + `status_codes` + 更新 `check_order` + 加 `normal_behaviors` |
| `tools/log-analyzer/pipeline_analyzer.py` | 增加 `_split_by_field_grouping()` 分支 + `_enrich_status_codes()` |
| `web-diagnostic/server.py` | `_TEMPLATE_PHASES` 改 6 阶段 + `recordings_by_field` + 提示词 + fallback 扩展 |
| `web-diagnostic/frontend/src/templates/index.js` | phases 更新为 6 阶段 |
| `tools/log-analyzer/tests/test_pipeline_analyzer.py` | 增加 field grouping + 状态码翻译测试 |
| `web-diagnostic/tests/test_asr_parsing.py` | 增加 offline-transcription 模板测试 |

### 不改动

- `pipeline_analyzer.py` 的 `analyze_phases()` 核心逻辑 — status code enrichment 是附加层
- `web-diagnostic/frontend/src/components/report.js` — `recordings[]` schema 不变
- `web-diagnostic/claude_runner.py` — 不改
