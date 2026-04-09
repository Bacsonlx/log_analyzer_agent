# Transcription Template Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the offline-transcription template to support multi-recording (by fileId), 6 phases (transcribe + summary split), status code auto-translation, and pipeline_analyzer pre-processing.

**Architecture:** Extend `pipeline_analyzer.py` with a `group_by_field` splitting mode, add status code enrichment to evidence, update `aivoice-transcription.json` with `recording_boundaries` + `phase_mapping` + `status_codes`, and adapt `web-diagnostic/server.py` template + fallback logic.

**Tech Stack:** Python 3.10+, existing `pipeline_analyzer.py` framework, `log_parser._parse_line()`.

**Spec:** `docs/superpowers/specs/2026-04-09-transcription-template-upgrade-design.md`

---

### Task 1: Knowledge JSON — Full Update

**Files:**
- Modify: `tools/log-analyzer/knowledge/aivoice-transcription.json`

- [ ] **Step 1: Rewrite aivoice-transcription.json**

Replace the entire contents of `tools/log-analyzer/knowledge/aivoice-transcription.json` with:

```json
{
  "_meta": {
    "updated": "2026-04-09",
    "description": "AIVoice 转写/总结诊断知识库，覆盖 extAttribute 状态追踪、MQTT 回传、结果获取"
  },
  "id": "aivoice-transcription",
  "name": "AIVoice 转写与总结问题",
  "module_refs": ["AIBuds_DB", "AIBuds_FileUpdate", "AIBuds_Upload", "AIBuds_Transcribe", "AIBuds_MQTT", "AIBuds_CloudSync"],
  "keywords": [
    "transcribe", "转写", "转录", "transcription",
    "summary", "总结",
    "status", "extAttribute",
    "transcribeStatus", "summaryStatus", "translateStatus",
    "fileId", "MQTT", "trans_mqtt", "summary_mqtt"
  ],
  "primary_tags": [
    "AIBuds_Upload",
    "AIBuds_Transcribe",
    "AIBuds_MQTT",
    "AIBuds_DB"
  ],
  "secondary_tags": [
    "AIBuds_FileUpdate",
    "AIBuds_CloudSync"
  ],
  "noise_tags": [],
  "check_order": [
    "1. 检查 AIBuds_DB 的 transcribeStatus（本地DB：0=未知, 1=转写中, 2=转写成功, 3=转写失败）",
    "2. 检查 AIBuds_DB 的 summaryStatus（本地DB：0=老数据, 1=未知, 2=总结中, 3=总结成功, 4=总结失败）",
    "2b. 检查 AIBuds_DB 的 translateStatus（本地DB：0=老数据, 1=未知, 2=翻译中, 3=翻译成功, 4=翻译失败）",
    "3. 云端 MQTT 状态码统一为：0=未知, 1=初始, 2=进行中, 9=成功, 100=失败",
    "4. 检查 AIBuds_FileUpdate 是否触发转写/总结",
    "5. 检查 audioUploadStatus 是否为 2（上传完成才能触发云端转写）",
    "6. 检查 recordSource（0 本地 / 1 云端）确认数据来源",
    "7. ASR/NLG 记录由云端流式通道产生并存储，客户端无需上报 ASR 文本至云端 transcript 存储"
  ],
  "common_causes": [
    {
      "pattern": "transcribeStatus=3",
      "cause": "转录失败，检查音频文件是否上传成功、服务端转录服务状态"
    },
    {
      "pattern": "summaryStatus=3|summaryStatus=4",
      "cause": "总结失败，检查转录是否完成、AI 总结服务状态"
    },
    {
      "pattern": "transcribeStatus=1.*长时间未变",
      "cause": "转录状态卡在「转录中」，可能服务端任务超时或消息推送丢失"
    },
    {
      "pattern": "audioUploadStatus=0|audioUploadStatus=3",
      "cause": "音频未上传或上传失败，无法触发云端转写"
    },
    {
      "pattern": "Transcription task failed to start",
      "cause": "转写任务启动失败，检查网络或参数"
    },
    {
      "pattern": "Summary request failed",
      "cause": "总结请求失败，检查转写是否完成或网络问题"
    }
  ],
  "normal_behaviors": [
    {
      "pattern": "File record updated successfully",
      "description": "DB 文件记录更新成功，属于正常状态变更",
      "how_to_identify": "每次 updateFile 后出现"
    },
    {
      "pattern": "transcription record is too short and is treated as a successful summary",
      "description": "云端返回 TranscribeTooShort 错误码时，客户端约定视为总结成功，回调给小程序展示对应错误码",
      "how_to_identify": "AIBuds_Upload 日志中出现此行，后续 summaryStatus 更新为成功"
    },
    {
      "pattern": "ASR/NLG records are cloud-generated",
      "description": "实时 ASR 和 NLG 的识别记录由云端流式通道产生并存储，客户端无需将 ASR 全量文本上报至云端 transcript 存储。转写/总结服务直接读取云端已有的流式识别结果",
      "how_to_identify": "系统架构约定，非日志可判断"
    }
  ],
  "phases": [
    {
      "name": "触发转写",
      "tags": ["AIBuds_Upload", "AIBuds_Transcribe"],
      "success_pattern": "Transcription task started successfully|Start transcription task",
      "failure_pattern": "Transcription task failed to start|Invalid transcription parameter"
    },
    {
      "name": "转写完成",
      "tags": ["AIBuds_MQTT", "AIBuds_DB"],
      "success_pattern": "scene: trans_mqtt - Transcription successful|transcribeStatus=2",
      "failure_pattern": "transcribeStatus=3|scene: trans_mqtt - Transcription failed"
    },
    {
      "name": "总结完成",
      "tags": ["AIBuds_Upload", "AIBuds_MQTT", "AIBuds_DB"],
      "success_pattern": "Summary request succeeded|summaryStatus=2|scene: summary_mqtt.*succeeded|transcription record is too short and is treated as a successful summary",
      "failure_pattern": "summaryStatus=3|summaryStatus=4|Summary request failed|Summary failed"
    }
  ],
  "recording_boundaries": {
    "mode": "group_by_field",
    "field_pattern": "fileId: (\\d+)",
    "field_name": "fileId",
    "tags": ["AIBuds_Upload", "AIBuds_Transcribe", "AIBuds_MQTT", "AIBuds_DB", "AIBuds_FileUpdate"]
  },
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
      "failure_pattern": "scene: trans_mqtt - Transcription failed|scene: trans_mqtt.*Database synchronization failed"
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
      "success_pattern": "scene: summary_mqtt.*Summarize status.*Database synchronization succeeded",
      "failure_pattern": "scene: summary_mqtt.*Database synchronization failed"
    },
    {
      "product_phase": "总结结果写入",
      "tags": ["AIBuds_Upload", "AIBuds_DB"],
      "success_pattern": "Cloud summary result retrieved successfully|Update summary status to success|transcription record is too short and is treated as a successful summary",
      "failure_pattern": "Summary result is empty|Failed to retrieve cloud summary results|Update summary status failed"
    }
  ],
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
  },
  "known_issues": []
}
```

- [ ] **Step 2: Validate JSON**

```bash
cd tools/log-analyzer && python3 -c "import json; json.load(open('knowledge/aivoice-transcription.json')); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/log-analyzer/knowledge/aivoice-transcription.json
git commit -m "feat: upgrade aivoice-transcription knowledge with 6 phases, status codes, and field grouping"
```

---

### Task 2: Pipeline Analyzer — `_split_by_field_grouping` + Tests

**Files:**
- Modify: `tools/log-analyzer/pipeline_analyzer.py`
- Modify: `tools/log-analyzer/tests/test_pipeline_analyzer.py`

- [ ] **Step 1: Add field grouping tests**

Append to `tools/log-analyzer/tests/test_pipeline_analyzer.py`:

```python
# ── Field grouping tests ─────────────────────────────────────────────

FIELD_GROUPING_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Upload> Start transcription task  fileId: 111
2024-01-01 10:00:02.000 [Info] <AIBuds_Upload> Transcription task started successfully  fileId: 111
2024-01-01 10:00:03.000 [Debug] <AIBuds_MQTT> scene: trans_mqtt - Transcription successful, synchronized with the mini-program.  recordId: rec111
2024-01-01 10:00:04.000 [Info] <AIBuds_Upload> Start transcription task  fileId: 222
2024-01-01 10:00:05.000 [Info] <AIBuds_Upload> Transcription task started successfully  fileId: 222
2024-01-01 10:00:06.000 [Info] <AIBuds_Upload> Cloud transcription result obtained successfully  fileId: 111, textLength: 500
2024-01-01 10:00:07.000 [Error] <AIBuds_Upload> Transcription task failed to start  fileId: 333, error: network
2024-01-01 10:00:08.000 [Info] <AIBuds_Record> some unrelated log without fileId
"""

FIELD_GROUPING_BOUNDARIES = {
    "mode": "group_by_field",
    "field_pattern": "fileId: (\\d+)",
    "field_name": "fileId",
    "tags": ["AIBuds_Upload", "AIBuds_Transcribe", "AIBuds_MQTT", "AIBuds_DB", "AIBuds_FileUpdate"]
}


def test_split_by_field_grouping_multi_files(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "field.log"
    f.write_text(FIELD_GROUPING_LOG, encoding="utf-8")
    recs = split_recordings(str(f), FIELD_GROUPING_BOUNDARIES)
    ids = [r["record_id"] for r in recs]
    assert "111" in ids
    assert "222" in ids
    assert "333" in ids
    assert len(recs) == 3
    rec_111 = next(r for r in recs if r["record_id"] == "111")
    assert len(rec_111["lines"]) == 3


def test_split_by_field_grouping_empty(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "empty_field.log"
    f.write_text("2024-01-01 10:00:01.000 [Info] <AIBuds_Record> no fileId here\n", encoding="utf-8")
    recs = split_recordings(str(f), FIELD_GROUPING_BOUNDARIES)
    assert len(recs) == 0


def test_split_by_field_grouping_ignores_unrelated_tags(tmp_path):
    from pipeline_analyzer import split_recordings

    log = "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> some log fileId: 999\n"
    f = tmp_path / "unrelated.log"
    f.write_text(log, encoding="utf-8")
    recs = split_recordings(str(f), FIELD_GROUPING_BOUNDARIES)
    assert len(recs) == 0
```

- [ ] **Step 2: Add `_split_by_field_grouping()` to `pipeline_analyzer.py`**

In `pipeline_analyzer.py`, add this function before `split_recordings()`:

```python
def _split_by_field_grouping(file_path: str, boundaries: dict) -> list[dict]:
    """Split log by grouping lines that share the same field value (e.g. fileId)."""
    entries = _parse_all_lines(file_path)
    if not entries:
        return []

    field_pattern = boundaries.get("field_pattern", "")
    tags_cfg = boundaries.get("tags", [])
    tags_lower = {t.lower() for t in tags_cfg}

    if not field_pattern:
        return []

    field_re = re.compile(field_pattern)
    groups: dict[str, list[dict]] = {}
    order: list[str] = []

    for entry in entries:
        tag = (entry.get("tag") or "").lower()
        if not any(t in tag for t in tags_lower):
            continue
        msg = entry.get("msg") or ""
        m = field_re.search(msg)
        if not m:
            continue
        fid = m.group(1)
        if fid not in groups:
            groups[fid] = []
            order.append(fid)
        groups[fid].append(entry)

    results: list[dict] = []
    for fid in order:
        lines = groups[fid]
        results.append({
            "record_id": fid,
            "start_time": _extract_time_short(lines[0].get("time", "")),
            "end_time": _extract_time_short(lines[-1].get("time", "")),
            "end_reason": None,
            "lines": lines,
        })
    return results
```

Then modify `split_recordings()` to dispatch by mode. At the very beginning of the function, after the empty-file check, add:

```python
    mode = boundaries.get("mode", "event_boundary")
    if mode == "group_by_field":
        return _split_by_field_grouping(file_path, boundaries)
```

- [ ] **Step 3: Run all tests**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v
```
Expected: all tests PASS (13 existing + 3 new = 16)

- [ ] **Step 4: Commit**

```bash
git add tools/log-analyzer/pipeline_analyzer.py tools/log-analyzer/tests/test_pipeline_analyzer.py
git commit -m "feat: add group_by_field splitting mode for fileId-based recording segmentation"
```

---

### Task 3: Status Code Enrichment + Tests

**Files:**
- Modify: `tools/log-analyzer/pipeline_analyzer.py`
- Modify: `tools/log-analyzer/tests/test_pipeline_analyzer.py`

- [ ] **Step 1: Add status code enrichment tests**

Append to `tools/log-analyzer/tests/test_pipeline_analyzer.py`:

```python
# ── Status code enrichment tests ─────────────────────────────────────

from pipeline_analyzer import _enrich_status_codes

STATUS_CODES_CFG = {
    "transcribeStatus": {
        "source": "local_db",
        "mapping": {"0": "未知", "1": "转写中", "2": "转写成功", "3": "转写失败"}
    },
    "summaryStatus": {
        "source": "local_db",
        "mapping": {"0": "老数据", "1": "未知", "2": "总结中", "3": "总结成功", "4": "总结失败"}
    },
    "cloud_status": {
        "source": "mqtt",
        "mapping": {"0": "未知", "1": "初始状态", "2": "进行中", "9": "成功", "100": "失败"}
    }
}


def test_enrich_transcribe_status():
    msg = "transcribeStatus: 3 fileId: 111"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "转写失败" in result
    assert "transcribeStatus: 3" in result


def test_enrich_summary_status():
    msg = "summaryStatus: 4 fileId: 222"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "总结失败" in result


def test_enrich_cloud_status():
    msg = "Transcription status ： 100 recordId: rec111"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "失败" in result


def test_enrich_no_match():
    msg = "no status code here"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert result == msg


def test_enrich_no_config():
    msg = "transcribeStatus: 3"
    result = _enrich_status_codes(msg, None)
    assert result == msg
```

- [ ] **Step 2: Implement `_enrich_status_codes()`**

Add to `pipeline_analyzer.py` before `_phase_evidence_item()`:

```python
_STATUS_CODE_PATTERN = re.compile(
    r'(transcribeStatus|summaryStatus|translateStatus|(?:Transcription|Summarize|Translation)\s+status)\s*[:：]\s*(\d+)'
)


def _enrich_status_codes(msg: str, status_codes: dict | None) -> str:
    """Append human-readable labels to status code values found in msg."""
    if not status_codes or not msg:
        return msg

    all_mappings: dict[str, dict[str, str]] = {}
    for key, cfg in status_codes.items():
        mapping = cfg.get("mapping", {})
        all_mappings[key.lower()] = mapping

    def _replace(m: re.Match) -> str:
        field = m.group(1).strip().lower()
        value = m.group(2)
        for key, mapping in all_mappings.items():
            if key in field or field in key:
                label = mapping.get(value)
                if label:
                    return f"{m.group(0)} → ({label})"
                break
        if "status" in field:
            for mapping in all_mappings.values():
                label = mapping.get(value)
                if label:
                    return f"{m.group(0)} → ({label})"
                    break
        return m.group(0)

    return _STATUS_CODE_PATTERN.sub(_replace, msg)
```

- [ ] **Step 3: Wire enrichment into `_phase_evidence_item()`**

Modify `_phase_evidence_item()` to accept an optional `status_codes` parameter:

```python
def _phase_evidence_item(entry: dict, match_kind: str, status_codes: dict | None = None) -> dict:
    """Build one evidence dict: short time, tag, msg truncated to 120 chars, match kind."""
    raw_time = entry.get("time") or ""
    short = _extract_time_short(raw_time)
    msg = entry.get("msg") or ""
    if status_codes:
        msg = _enrich_status_codes(msg, status_codes)
    if len(msg) > 120:
        msg = msg[:120]
    return {
        "time": short,
        "tag": entry.get("tag") or "",
        "msg": msg,
        "match": match_kind,
    }
```

Then update `analyze_phases()` signature to accept `status_codes`:

```python
def analyze_phases(recording: dict, phase_mapping: list[dict], status_codes: dict | None = None) -> dict:
```

And pass `status_codes` to every `_phase_evidence_item()` call inside `analyze_phases()`.

Finally update `analyze_pipeline()` to pass `status_codes`:

```python
status_codes = scenario.get("status_codes")
# ...
out = analyze_phases(rec, phase_mapping, status_codes=status_codes)
```

- [ ] **Step 4: Run all tests**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v
```
Expected: all tests PASS (16 + 5 = 21)

- [ ] **Step 5: Commit**

```bash
git add tools/log-analyzer/pipeline_analyzer.py tools/log-analyzer/tests/test_pipeline_analyzer.py
git commit -m "feat: add status code enrichment to pipeline evidence items"
```

---

### Task 4: `web-diagnostic/server.py` — Template + Fallback + Prompt

**Files:**
- Modify: `web-diagnostic/server.py`

- [ ] **Step 1: Update `_TEMPLATE_PHASES` for `offline-transcription`**

Replace the `offline-transcription` entry (around line 435-438):

```python
    "offline-transcription": {
        "label": "离线转写/总结",
        "phases": ["进入详情页", "开始转写/总结", "收到转写MQ", "获取转写结果"],
    },
```

With:

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

- [ ] **Step 2: Expand pipeline_data capture beyond audio-recognition**

Find (around line 353):
```python
                        if task.template == "audio-recognition" and server_pipeline_data is None:
```
Replace with:
```python
                        if server_pipeline_data is None:
```

- [ ] **Step 3: Add `recordings_by_field` prompt branch**

In `_build_template_prompt()`, find the check `if meta.get("asr_records"):` (around line 498). Before this line, add a new branch for `recordings_by_field`:

```python
        if meta.get("recordings_by_field"):
            phases_str = ",\n".join(_phase_json_line(p, indent=8) for p in meta["phases"])
            recording_example = f"""    {{
      "record_id": "<fileId>",
      "status": "<success|failed|interrupted>",
      "phases": [
{phases_str}
      ]
    }}"""

            phase_modules_hint = ""
            if any(isinstance(p, dict) and p.get("modules") for p in meta["phases"]):
                lines = []
                for p in meta["phases"]:
                    if isinstance(p, dict) and p.get("modules"):
                        tags = ", ".join(f"[AIBuds_{{m}}]" for m in p["modules"])
                        lines.append(f"  - {{p['name']}}: {{tags}}")
                phase_modules_hint = "\\n各阶段应重点关注的日志模块：\\n" + "\\n".join(lines)

            recording_status_hint = (
                "\\nrecording 级别 status 取值: "
                "success=全部阶段完成无失败; "
                "failed=某步失败; "
                "interrupted=流程未完成"
            )

            status_codes_hint = """
状态码参考：
- transcribeStatus（本地DB）：0=未知, 1=转写中, 2=转写成功, 3=转写失败
- summaryStatus（本地DB）：0=老数据, 1=未知, 2=总结中, 3=总结成功, 4=总结失败
- translateStatus（本地DB）：0=老数据, 1=未知, 2=翻译中, 3=翻译成功, 4=翻译失败
- 云端 MQTT 状态码：0=未知, 1=初始, 2=进行中, 9=成功, 100=失败
注意：云端返回 TranscribeTooShort 错误码时，客户端约定视为总结成功。"""

            return f\"\"\"

---
[诊断报告格式要求] 本次诊断场景为「{meta["label"]}」。
日志中可能包含多个 fileId 对应的独立转写/总结流程。请按 fileId 分别诊断每个文件的 6 个阶段。

请在输出 Markdown 报告正文之前，先输出以下格式的 JSON 代码块：
```json
{{
  "template": "{template}",
  "recordings": [
{recording_example}
  ]
}}
```
{_PHASE_STATUS_HINT}{recording_status_hint}{phase_modules_hint}{status_codes_hint}

诊断报告中出现 transcribeStatus、summaryStatus 等状态码时，请标注其真实含义。

[重要] diagnose_scenario 的返回中可能已包含「结构化分析 (JSON)」段，
其中的 recordings[] 是脚本根据日志 pattern 自动生成的阶段判定（含 confidence 和 evidence）。
若存在该段：
1. 审阅每个 recording 的 phases，尤其是 confidence: "low" 的阶段需要你用日志上下文做最终判定
2. confidence: "high" 的阶段可直接采纳，将 evidence 中的关键信息写入 detail
3. 如需修正，直接在你输出的 JSON 中覆盖对应阶段的 status/detail
4. 你**不需要**使用 Grep 或其他工具搜索日志，所有关键证据已在 evidence 中提供{_full_extract_hint}
输出 JSON 代码块后，换行继续输出正常的 Markdown 诊断报告。\"\"\"
```

Note: The actual code should use proper f-string syntax. Read the existing `asr_records` branch as reference for exact formatting.

- [ ] **Step 4: Run web-diagnostic tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add web-diagnostic/server.py
git commit -m "feat: upgrade offline-transcription template with 6 phases, recordings_by_field, and status code hints"
```

---

### Task 5: Frontend Template Update

**Files:**
- Modify: `web-diagnostic/frontend/src/templates/index.js`

- [ ] **Step 1: Update phases**

Replace:
```javascript
  'offline-transcription': {
    label: '离线转写/总结',
    phases: ['进入详情页', '开始转写/总结', '收到转写MQ', '获取转写结果'],
  },
```

With:
```javascript
  'offline-transcription': {
    label: '离线转写/总结',
    phases: ['触发转写', '收到转写MQ', '转写结果写入', '触发总结', '收到总结MQ', '总结结果写入'],
  },
```

- [ ] **Step 2: Commit**

```bash
git add web-diagnostic/frontend/src/templates/index.js
git commit -m "feat: update offline-transcription frontend phases to 6 stages"
```

---

### Task 6: Integration Tests

**Files:**
- Modify: `web-diagnostic/tests/test_asr_parsing.py`

- [ ] **Step 1: Add offline-transcription template tests**

Append to `web-diagnostic/tests/test_asr_parsing.py`:

```python
def test_template_phases_offline_transcription_has_6_phases():
    ot = _TEMPLATE_PHASES["offline-transcription"]
    assert ot["label"] == "离线转写/总结"
    assert len(ot["phases"]) == 6
    assert ot["phases"][0]["name"] == "触发转写"
    assert ot["phases"][-1]["name"] == "总结结果写入"
    assert ot.get("recordings_by_field") is True


def test_extract_template_data_recordings_for_transcription():
    body = """前言

```json
{
  "template": "offline-transcription",
  "recordings": [
    {
      "record_id": "111",
      "status": "success",
      "phases": [
        {"name": "触发转写", "status": "success", "time": "10:00:01", "detail": "ok"}
      ]
    }
  ]
}
```

tail"""
    data, clean = _extract_template_data(body)
    assert data is not None
    assert data["template"] == "offline-transcription"
    assert len(data["recordings"]) == 1
    assert data["recordings"][0]["record_id"] == "111"
```

- [ ] **Step 2: Run all tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 3: Run log-analyzer tests too**

```bash
cd tools/log-analyzer && python -m pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add web-diagnostic/tests/test_asr_parsing.py
git commit -m "test: add offline-transcription template and integration tests"
```
