# 识别模版：按段录音展开时间线

**日期**: 2026-04-08
**范围**: `web-diagnostic`（`server.py`、`report.js`、`templates/index.js`）

## 1. 背景与问题

当前 `audio-recognition` 模版将 5 个诊断阶段作为一条全局时间线展示，ASR 识别记录单独分区显示。但实际场景中，一个日志文件包含 3-5 段甚至更多独立录音，每段录音都有自己完整的「选择设备 → 选择语言 → 点击开始 → 开始识别 → 识别结束」流程。此外还需要处理异常情况：选择设备后未开始、中途杀死 APP 导致流程不完整等。

全局时间线无法表达这些 per-recording 的状态差异。

## 2. 目标

- 每段录音独立展示完整的 5 步时间线 + 该段的 ASR 识别记录。
- 正确标记异常录音（中断、失败）。
- 向后兼容老数据（flat `phases` + `asr_records`）。

## 3. 数据结构

### 3.1 AI 输出的 JSON（新格式）

```json
{
  "template": "audio-recognition",
  "recordings": [
    {
      "record_id": "ej_PHONE00UrkYs7_1775540437",
      "status": "success",
      "phases": [
        {"name": "选择设备", "status": "success", "time": "13:40:38.100", "detail": "[Record] 设备连接成功"},
        {"name": "选择语言", "status": "success", "time": "13:40:38.500", "detail": "[ASR] zh → en"},
        {"name": "点击开始", "status": "success", "time": "13:40:39.000", "detail": "[Session] 会话创建成功"},
        {"name": "开始识别", "status": "success", "time": "13:40:39.100", "detail": "[ASR] 识别中"},
        {"name": "识别结束", "status": "success", "time": "13:41:00.000", "detail": "[ASR] 正常结束，5句"}
      ]
    },
    {
      "record_id": "ej_PHONE00UrkYs7_1775540438",
      "status": "interrupted",
      "phases": [
        {"name": "选择设备", "status": "success", "time": "13:42:00.000", "detail": "[Record] 设备连接成功"},
        {"name": "选择语言", "status": "success", "time": "13:42:01.000", "detail": "[ASR] zh → ja"},
        {"name": "点击开始", "status": "failed", "time": "13:42:02.000", "detail": "[Session] 创建超时"},
        {"name": "开始识别", "status": "skipped", "time": null, "detail": "未到达此阶段"},
        {"name": "识别结束", "status": "skipped", "time": null, "detail": "未到达此阶段"}
      ]
    }
  ]
}
```

AI **不**输出 `asr_records`，服务端按 `record_id` 自动合并。

### 3.2 recording.status 取值

| 值 | 含义 |
|---|---|
| `success` | 5 步完整走完，无失败阶段 |
| `failed` | 某步失败但流程有结束标记 |
| `interrupted` | 中途中断（app 被杀、无结束日志） |

### 3.3 向后兼容

老数据（flat `phases` + `asr_records`，无 `recordings`）在读取时包装为单条 recording：

```python
if "phases" in data and "recordings" not in data:
    data["recordings"] = [{
        "record_id": "legacy",
        "status": "success",
        "phases": data["phases"],
        "asr_records": data.get("asr_records", []),
    }]
```

## 4. 服务端改动（`server.py`）

### 4.1 提示词（`_build_template_prompt`）

`audio-recognition` 模版的 JSON 示例改为 `recordings` 数组格式。提示词要求：
- 每段录音用日志中的 record_id 标识（从 requestId 去掉尾部 `_N` 序号）。
- 每段独立填写 5 个阶段的状态。
- 中途中断的录音，后续阶段标记为 `skipped`，recording status 为 `interrupted`。
- 不输出 `asr_records`。

全量提取指令（上一个 spec 引入的 `_full_extract_hint`）和阶段模块白名单保持不变。

### 4.2 `_TEMPLATE_DATA_RE` 适配

当前正则仅匹配含 `"phases"` 的 JSON 块。改为同时匹配 `"recordings"` 或 `"phases"`：

```python
_TEMPLATE_DATA_RE = re.compile(
    r'```json\s*(\{[^`]*?"template"\s*:[^`]*?(?:"recordings"|"phases")\s*:[^`]*?\})\s*```',
    re.DOTALL,
)
```

### 4.3 ASR 合并逻辑

在 `_extract_template_data` 后、发送结果前，执行 ASR 合并：

```python
def _merge_asr_into_recordings(template_data, server_asr_records):
    """将服务端解析的 asr_records 按 record_id 合并到 recordings。"""
    if not template_data or not server_asr_records:
        return
    recordings = template_data.get("recordings")
    if not recordings:
        return

    # 按 record_id 分桶
    asr_by_record = defaultdict(list)
    for r in server_asr_records:
        asr_by_record[r.get("record_id", "")].append(r)

    matched_ids = set()
    for rec in recordings:
        rid = rec.get("record_id", "")
        if rid in asr_by_record:
            rec["asr_records"] = asr_by_record[rid]
            matched_ids.add(rid)
        else:
            rec.setdefault("asr_records", [])

    # 未匹配的 ASR 记录归到最后一个 recording
    unmatched = []
    for rid, records in asr_by_record.items():
        if rid not in matched_ids:
            unmatched.extend(records)
    if unmatched and recordings:
        recordings[-1].setdefault("asr_records", []).extend(unmatched)
```

### 4.4 向后兼容（历史数据读取）

`_load_history_detail` 中，若 `template_data` 有 `phases` 无 `recordings`，包装为单条 recording。

## 5. 前端改动（`report.js`）

### 5.1 `_renderTimeline` 重构

从渲染单一时间线改为渲染 `recordings` 列表。每个 recording 是一个 `<details>` 卡片：

**卡片头**：
- 左侧：录音序号 `录音 #N` + record_id（截断显示）
- 右侧：状态徽章（成功/失败/中断）+ ASR 句数

**卡片体**：
- 该段的 5 步时间线（复用现有 `_buildTimelineHtml`）
- 该段的 ASR 识别记录（复用现有 `_buildAsrRecordsHtml`）

**展开策略**：
- 录音 ≤ 3 段：全部展开
- 录音 > 3 段：`failed`/`interrupted` 默认展开，`success` 默认折叠

### 5.2 状态汇总 banner

banner 区域增加录音概要：`3 段录音 · 2 成功 · 1 中断`

### 5.3 Fallback

若 `template_data` 中无 `recordings`（老数据或非 `audio-recognition` 模版），走现有的 flat timeline + separate ASR 渲染路径。

## 6. 不改动的部分

- `aibuds_extractor.py` / `aibuds_scanner.py`
- `_create_asr_subfile` / `_parse_asr_records` — 逻辑不变
- `templates/index.js` — 前端模版定义保持纯字符串 phases
- 其他模版（`recording`、`offline-transcription`、`cloud-upload`）— 保持 flat phases

## 7. 验收

- 使用示例日志（含多段录音）运行诊断，确认前端按段展示时间线 + ASR。
- 模拟异常录音（中途中断），确认显示 `interrupted` + 后续阶段 `skipped`。
- 打开一条老历史记录（flat phases），确认 fallback 正常显示。
- 全部测试通过。
