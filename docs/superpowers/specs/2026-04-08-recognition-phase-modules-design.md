# 识别模版：全量日志提取 + 阶段模块白名单

**日期**: 2026-04-08
**范围**: `web-diagnostic/server.py`（`_TEMPLATE_PHASES`、`_build_template_prompt`）

## 1. 背景与问题

`audio-recognition` 模版当前存在三个问题：

1. **阶段诊断只看 ASR 日志**：提示词（`_ASR_RECORDS_HINT`）引导 AI 仅关注 `[AIBuds_ASR]`，但流程前几个阶段（选择设备、选择语言、点击开始）涉及 `Record`、`AudioInput`、`VAD`、`Session` 等多个模块。
2. **`asr_field` / `asr_hint` 始终为空**：`_build_template_prompt` 中 `asr_field = ""` / `asr_hint = ""` 从未被赋值，`_ASR_RECORDS_HINT` 和 `_asr_records_example` 定义了却未使用，AI 输出的 JSON 中不会包含 `asr_records`。
3. **全量提取被误用为 ASR 提取**：由于提示词只提 ASR，Claude 调用 `extract_to_file(module="ASR")` 而非全量提取，导致"全量提取"文件实际也只有 ASR 行。

## 2. 目标

- 每个阶段在提示词中列出应关注的模块白名单，引导 AI 从全量日志中按阶段分模块诊断。
- 修复 `_build_template_prompt`，当 `meta["asr_records"]` 为 `True` 时正确拼入 `_ASR_RECORDS_HINT` 和 `asr_records` 示例字段。
- 提示词中明确要求"全量提取所有 `[AIBuds_*]` 模块日志"，防止 Claude 只提取 ASR。

## 3. 阶段模块白名单

| 阶段 | 关注模块（`[AIBuds_*]` 后缀） |
|------|------|
| 选择设备 | Record, AudioInput, BatteryMonitor, MiniApp, EventDispatch |
| 选择语言 | ASR, Translate, Transfer, FaceToFace, SI, Phone, PhoneAndBuds, PhoneAndEntryBuds |
| 点击开始 | Record, AudioInput, VAD, Session, Token, AIChannel, Coder |
| 开始识别 | ASR, Recognition, AIChannel, VAD, AudioInput, Session, Token, Amplitude |
| 识别结束 | ASR, Recognition, Transfer, Translate, MQTT, TraceEvent, Record |

## 4. 行为说明

### 4.1 `_TEMPLATE_PHASES` 结构变更

`phases` 从纯字符串列表改为字典列表，每项包含 `name` 和 `modules`：

```python
"audio-recognition": {
    "label": "识别",
    "phases": [
        {"name": "选择设备", "modules": ["Record", "AudioInput", "BatteryMonitor", "MiniApp", "EventDispatch"]},
        {"name": "选择语言", "modules": ["ASR", "Translate", "Transfer", "FaceToFace", "SI", "Phone", "PhoneAndBuds", "PhoneAndEntryBuds"]},
        {"name": "点击开始", "modules": ["Record", "AudioInput", "VAD", "Session", "Token", "AIChannel", "Coder"]},
        {"name": "开始识别", "modules": ["ASR", "Recognition", "AIChannel", "VAD", "AudioInput", "Session", "Token", "Amplitude"]},
        {"name": "识别结束", "modules": ["ASR", "Recognition", "Transfer", "Translate", "MQTT", "TraceEvent", "Record"]},
    ],
    "asr_records": True,
}
```

其他模版（`offline-transcription`、`recording`、`cloud-upload`）的 `phases` 保持纯字符串列表不变，`_build_template_prompt` 兼容两种格式。

### 4.2 `_build_template_prompt` 修改

1. phase JSON 模板生成时：若 phase 是 dict（含 `modules`），在 `detail` 提示中注明"重点关注 `[AIBuds_X]` `[AIBuds_Y]` …"。
2. 当 `meta.get("asr_records")` 为 `True` 时，将 `_asr_records_example` 拼入 JSON 示例、`_ASR_RECORDS_HINT` 拼入尾部说明。
3. 在提示词头部添加全量提取指令："请使用 extract_to_file 工具提取日志时**不要指定 module 参数**，确保提取所有 `[AIBuds_*]` 模块的完整日志。"

### 4.3 前端

`templates/index.js` 中 `audio-recognition` 的 `phases` 保持纯字符串列表（前端只用 name 显示），不受服务端结构变更影响。

## 5. 不改动的部分

- `aibuds_extractor.py` — `extract_aibuds_logs()` 正确提取全量，无需改动。
- `aibuds_scanner.py` — ObjC 源码扫描器，不涉及。
- `report.js` — 前端展示逻辑不涉及。
- `_create_asr_subfile` / `_parse_asr_records` — ASR 子文件生成与解析逻辑正确。

## 6. 验收

- 使用示例日志运行 `aibuds_extractor.py` 全量提取，确认输出包含所有 26+ 个 AIBuds 模块。
- 检查 `_build_template_prompt("audio-recognition")` 输出的提示词包含：阶段模块白名单、`asr_records` JSON 示例、全量提取指令。
