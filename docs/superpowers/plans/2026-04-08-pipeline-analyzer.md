# Pipeline Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a script-based pipeline analyzer that pre-processes realtime pipeline logs into structured `recordings[]` with per-phase status/evidence, so the AI only needs to review and summarize rather than grep raw logs.

**Architecture:** New `pipeline_analyzer.py` module under `tools/log-analyzer/` with two core components: `split_recordings()` (boundary-based log segmentation) and `analyze_phases()` (pattern-matching phase engine). Integrated into existing `diagnose_scenario()` as an appended JSON section. `web-diagnostic/server.py` extracts the pre-processed result and uses it as fallback when AI doesn't output its own `recordings[]`.

**Tech Stack:** Python 3.10+, regex pattern matching, existing `log_parser._parse_line()` for log parsing.

**Spec:** `docs/superpowers/specs/2026-04-08-pipeline-analyzer-design.md`

---

### Task 1: Knowledge JSON — Add `recording_boundaries` and `phase_mapping`

**Files:**
- Modify: `tools/log-analyzer/knowledge/aivoice-streaming-channel.json`

- [ ] **Step 1: Add `recording_boundaries` field**

Open `tools/log-analyzer/knowledge/aivoice-streaming-channel.json` and add after the `"phases"` array (before `"known_issues"`):

```json
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
},
```

- [ ] **Step 2: Add `phase_mapping` field**

Add after `recording_boundaries`:

```json
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
],
```

- [ ] **Step 3: Validate JSON**

Run:
```bash
python3 -c "import json; json.load(open('tools/log-analyzer/knowledge/aivoice-streaming-channel.json'))"
```
Expected: no output (valid JSON)

- [ ] **Step 4: Commit**

```bash
git add tools/log-analyzer/knowledge/aivoice-streaming-channel.json
git commit -m "feat: add recording_boundaries and phase_mapping to streaming-channel knowledge"
```

---

### Task 2: RecordingSplitter — Tests

**Files:**
- Create: `tools/log-analyzer/tests/test_pipeline_analyzer.py`

- [ ] **Step 1: Create test directory and file with splitter tests**

```bash
mkdir -p tools/log-analyzer/tests
```

Create `tools/log-analyzer/tests/test_pipeline_analyzer.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "aivoice-streaming-channel.json"

def _load_scenario():
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


# ── RecordingSplitter tests ──────────────────────────────────────────

SINGLE_RECORDING_LOG = """\
2024-01-01 10:00:00.000 [Info] <AIBuds_ASR> Token create asr config model: phone
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1
2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: ej_req001_0
2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
"""

MULTI_RECORDING_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:02 requestId: ej_recA_0
2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
2024-01-01 10:01:00.000 [Info] <AIBuds_ASR> Token create asr config model: phone
2024-01-01 10:01:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:01:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:01:02 requestId: ej_recB_0
2024-01-01 10:01:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
2024-01-01 10:02:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:02:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:02:02 requestId: ej_recC_0
2024-01-01 10:02:10.000 [Info] <AIBuds_Record> Recording paused successfully, Device ID: dev001
"""

INTERRUPTED_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:02 requestId: ej_int_0
2024-01-01 10:00:05.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1
"""

NO_RECORD_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1
2024-01-01 10:00:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:02 requestId: ej_fb_0
"""


def test_split_single_recording(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "single.log"
    f.write_text(SINGLE_RECORDING_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 1
    assert recs[0]["record_id"] == "ej_req001"
    assert recs[0]["end_reason"] == "stopped"
    assert recs[0]["start_time"] is not None
    assert recs[0]["end_time"] is not None
    assert len(recs[0]["lines"]) >= 4


def test_split_multi_recordings(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "multi.log"
    f.write_text(MULTI_RECORDING_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 3
    assert recs[0]["record_id"] == "ej_recA"
    assert recs[0]["end_reason"] == "stopped"
    assert recs[1]["record_id"] == "ej_recB"
    assert recs[1]["end_reason"] == "stopped"
    assert recs[2]["record_id"] == "ej_recC"
    assert recs[2]["end_reason"] == "paused"


def test_split_interrupted_recording(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "interrupted.log"
    f.write_text(INTERRUPTED_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 1
    assert recs[0]["end_reason"] == "interrupted"
    assert recs[0]["end_time"] is None


def test_split_no_record_boundary_fallback(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "no_record.log"
    f.write_text(NO_RECORD_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 1
    assert recs[0]["record_id"] == "ej_fb"
    assert recs[0]["end_reason"] == "interrupted"


def test_split_empty_file(tmp_path):
    from pipeline_analyzer import split_recordings

    f = tmp_path / "empty.log"
    f.write_text("", encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v -k "split" 2>&1 | head -30
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline_analyzer'`

- [ ] **Step 3: Commit test file**

```bash
git add tools/log-analyzer/tests/test_pipeline_analyzer.py
git commit -m "test: add RecordingSplitter tests (red)"
```

---

### Task 3: RecordingSplitter — Implementation

**Files:**
- Create: `tools/log-analyzer/pipeline_analyzer.py`

- [ ] **Step 1: Implement `split_recordings()`**

Create `tools/log-analyzer/pipeline_analyzer.py`:

```python
"""Pipeline Analyzer: recording splitter + phase engine for structured log diagnosis.

Reads scenario config (recording_boundaries, phase_mapping) from knowledge JSON
and produces structured recordings[] with per-phase status and evidence.
"""

import re
from log_parser import _parse_line


def _extract_time_short(time_str: str) -> str | None:
    """Extract HH:MM:SS.mmm from a full timestamp string."""
    m = re.search(r'(\d{2}:\d{2}:\d{2}\.\d+)', time_str)
    return m.group(1) if m else None


def _strip_trailing_sequence(request_id: str) -> str:
    """Remove trailing _N from requestId to get record_id."""
    return re.sub(r'_\d+$', '', request_id)


def _parse_all_lines(file_path: str) -> list[dict]:
    """Parse all log lines from file, attaching original line number."""
    entries = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for lineno, line in enumerate(f, 1):
            entry = _parse_line(line)
            if entry is not None:
                entry["_lineno"] = lineno
                entries.append(entry)
    return entries


def _extract_record_id(lines: list[dict], cfg: dict) -> str:
    """Extract record_id from lines using record_id_extraction config."""
    tag = cfg.get("tag", "")
    pattern = cfg.get("pattern", "")
    transform = cfg.get("transform", "")
    if not pattern:
        return "unknown"
    regex = re.compile(pattern)
    for entry in lines:
        if tag and tag.lower() not in entry["tag"].lower():
            continue
        m = regex.search(entry["msg"])
        if m:
            rid = m.group(1)
            if transform == "strip_trailing_sequence":
                rid = _strip_trailing_sequence(rid)
            return rid
    return "unknown"


def split_recordings(file_path: str, boundaries: dict) -> list[dict]:
    """Split log file into recording segments based on boundary config.

    Returns list of dicts with record_id, start_time, end_time, end_reason, lines.
    """
    all_lines = _parse_all_lines(file_path)
    if not all_lines:
        return []

    start_tag = boundaries.get("start_tag", "").lower()
    start_pattern = boundaries.get("start_pattern", "")
    end_patterns = boundaries.get("end_patterns", [])
    rid_cfg = boundaries.get("record_id_extraction", {})

    start_re = re.compile(start_pattern) if start_pattern else None
    end_res = []
    for ep in end_patterns:
        end_res.append({
            "tag": ep.get("tag", "").lower(),
            "regex": re.compile(ep["pattern"]),
            "reason": ep.get("reason", "stopped"),
        })

    segments: list[dict] = []
    current_start_idx: int | None = None

    for i, entry in enumerate(all_lines):
        tag_lower = entry["tag"].lower()
        if start_re and start_tag in tag_lower and start_re.search(entry["msg"]):
            if current_start_idx is not None:
                segments.append({
                    "start_idx": current_start_idx,
                    "end_idx": i - 1,
                    "end_reason": "interrupted",
                    "end_time": None,
                })
            current_start_idx = i
            continue

        if current_start_idx is not None:
            for ep in end_res:
                if ep["tag"] in tag_lower and ep["regex"].search(entry["msg"]):
                    segments.append({
                        "start_idx": current_start_idx,
                        "end_idx": i,
                        "end_reason": ep["reason"],
                        "end_time": _extract_time_short(entry["time"]),
                    })
                    current_start_idx = None
                    break

    if current_start_idx is not None:
        segments.append({
            "start_idx": current_start_idx,
            "end_idx": len(all_lines) - 1,
            "end_reason": "interrupted",
            "end_time": None,
        })

    if not segments:
        if not all_lines:
            return []
        segments = [{
            "start_idx": 0,
            "end_idx": len(all_lines) - 1,
            "end_reason": "interrupted",
            "end_time": None,
        }]

    recordings = []
    for si, seg in enumerate(segments):
        if si == 0:
            line_start = 0
        else:
            line_start = segments[si - 1]["end_idx"] + 1
        line_end = seg["end_idx"]
        if si == len(segments) - 1:
            line_end = len(all_lines) - 1

        seg_lines = all_lines[line_start : line_end + 1]
        start_time = _extract_time_short(all_lines[seg["start_idx"]]["time"]) if seg["start_idx"] < len(all_lines) else None
        record_id = _extract_record_id(seg_lines, rid_cfg)

        recordings.append({
            "record_id": record_id,
            "start_time": start_time,
            "end_time": seg["end_time"],
            "end_reason": seg["end_reason"],
            "lines": seg_lines,
        })

    return recordings
```

- [ ] **Step 2: Run splitter tests**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v -k "split"
```
Expected: all 5 `test_split_*` tests PASS

- [ ] **Step 3: Commit**

```bash
git add tools/log-analyzer/pipeline_analyzer.py
git commit -m "feat: implement RecordingSplitter with config-driven boundaries"
```

---

### Task 4: PhaseEngine — Tests

**Files:**
- Modify: `tools/log-analyzer/tests/test_pipeline_analyzer.py`

- [ ] **Step 1: Add PhaseEngine tests**

Append to `tools/log-analyzer/tests/test_pipeline_analyzer.py`:

```python
# ── PhaseEngine tests ────────────────────────────────────────────────

ALL_SUCCESS_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_ASR> Token create asr config model: phone
2024-01-01 10:00:03.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1
2024-01-01 10:00:04.000 [Info] <AIBuds_Session> scene: create - success sessionId: ses1 tokenId: tok1
2024-01-01 10:00:05.000 [Info] <AIBuds_AIChannel> scene: stream - connected ws1
2024-01-01 10:00:06.000 [Info] <AIBuds_AIChannel> scene: pick_data - begin at 10:00:06 intervalMs: 0
2024-01-01 10:00:07.000 [Info] <AIBuds_AIChannel> scene: send_data - begin at 10:00:07 intervalMs: 100
2024-01-01 10:00:08.000 [Info] <AIBuds_Recognition> scene: transcribe - text packet: hello
2024-01-01 10:00:09.000 [Info] <AIBuds_AIChannel> scene: request - finished at 10:00:09 intervalMs: 6000
2024-01-01 10:00:10.000 [Info] <AIBuds_ASR> ASRTask ended, end time: 10000, Request ID: ej_req001_0, Error: None
2024-01-01 10:00:11.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
"""

TOKEN_FAILURE_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_ASR> Token create asr config model: phone
2024-01-01 10:00:03.000 [Error] <AIBuds_Token> scene: create - new token failure
2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
"""

NO_MATCH_LOG = """\
2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001
2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: update - queued token update key: k1 params: p1
2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001
"""


def test_phase_all_success(tmp_path):
    from pipeline_analyzer import split_recordings, analyze_phases

    f = tmp_path / "success.log"
    f.write_text(ALL_SUCCESS_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    assert len(recs) == 1
    result = analyze_phases(recs[0], scenario["phase_mapping"])
    assert result["status"] == "success"
    for p in result["phases"]:
        assert p["status"] == "success"
        assert p["confidence"] == "high"
    assert len(result["phases"]) == 5


def test_phase_token_failure(tmp_path):
    from pipeline_analyzer import split_recordings, analyze_phases

    f = tmp_path / "fail.log"
    f.write_text(TOKEN_FAILURE_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    result = analyze_phases(recs[0], scenario["phase_mapping"])
    assert result["status"] == "failed"
    click_start = next(p for p in result["phases"] if p["name"] == "点击开始")
    assert click_start["status"] == "failed"
    assert click_start["confidence"] == "high"
    assert "new token failure" in click_start["detail"]


def test_phase_skipped_when_no_tag_lines(tmp_path):
    from pipeline_analyzer import split_recordings, analyze_phases

    f = tmp_path / "skip.log"
    f.write_text(TOKEN_FAILURE_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    result = analyze_phases(recs[0], scenario["phase_mapping"])
    recognition = next(p for p in result["phases"] if p["name"] == "开始识别")
    assert recognition["status"] == "skipped"
    assert recognition["confidence"] == "high"


def test_phase_low_confidence(tmp_path):
    from pipeline_analyzer import split_recordings, analyze_phases

    f = tmp_path / "low_conf.log"
    f.write_text(NO_MATCH_LOG, encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    result = analyze_phases(recs[0], scenario["phase_mapping"])
    click_start = next(p for p in result["phases"] if p["name"] == "点击开始")
    assert click_start["status"] == "success"
    assert click_start["confidence"] == "low"


def test_phase_evidence_max_3(tmp_path):
    from pipeline_analyzer import split_recordings, analyze_phases

    lines = ["2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001"]
    for i in range(10):
        lines.append(f"2024-01-01 10:00:0{i+2}.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok{i}")
    lines.append("2024-01-01 10:00:20.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001")

    f = tmp_path / "many_evidence.log"
    f.write_text("\n".join(lines), encoding="utf-8")
    scenario = _load_scenario()
    recs = split_recordings(str(f), scenario["recording_boundaries"])
    result = analyze_phases(recs[0], scenario["phase_mapping"])
    click_start = next(p for p in result["phases"] if p["name"] == "点击开始")
    assert len(click_start["evidence"]) <= 3
```

- [ ] **Step 2: Run to verify failures**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v -k "phase" 2>&1 | head -20
```
Expected: FAIL — `ImportError: cannot import name 'analyze_phases'`

- [ ] **Step 3: Commit**

```bash
git add tools/log-analyzer/tests/test_pipeline_analyzer.py
git commit -m "test: add PhaseEngine tests (red)"
```

---

### Task 5: PhaseEngine — Implementation

**Files:**
- Modify: `tools/log-analyzer/pipeline_analyzer.py`

- [ ] **Step 1: Add `analyze_phases()` to `pipeline_analyzer.py`**

Append to `tools/log-analyzer/pipeline_analyzer.py`:

```python
_MAX_EVIDENCE = 3


def analyze_phases(recording: dict, phase_mapping: list[dict]) -> dict:
    """Analyze a single recording segment against phase_mapping config.

    Returns dict with record_id, status, phases[].
    Each phase has name, status, confidence, time, detail, evidence[].
    """
    lines = recording.get("lines", [])
    phases_result = []

    for pm in phase_mapping:
        phase_tags = {t.lower() for t in pm.get("tags", [])}
        success_re = re.compile(pm["success_pattern"]) if pm.get("success_pattern") else None
        failure_re = re.compile(pm["failure_pattern"]) if pm.get("failure_pattern") else None

        tag_lines = [e for e in lines if any(t in e["tag"].lower() for t in phase_tags)]

        success_evidence = []
        failure_evidence = []

        for entry in tag_lines:
            if failure_re and failure_re.search(entry["msg"]):
                failure_evidence.append({
                    "time": _extract_time_short(entry["time"]) or entry["time"],
                    "tag": entry["tag"],
                    "msg": entry["msg"][:120],
                    "match": "failure",
                })
            elif success_re and success_re.search(entry["msg"]):
                success_evidence.append({
                    "time": _extract_time_short(entry["time"]) or entry["time"],
                    "tag": entry["tag"],
                    "msg": entry["msg"][:120],
                    "match": "success",
                })

        if failure_evidence:
            status = "failed"
            confidence = "high"
            evidence = failure_evidence[:_MAX_EVIDENCE]
        elif success_evidence:
            status = "success"
            confidence = "high"
            evidence = success_evidence[:_MAX_EVIDENCE]
        elif tag_lines:
            status = "success"
            confidence = "low"
            evidence = [{
                "time": _extract_time_short(tag_lines[0]["time"]) or tag_lines[0]["time"],
                "tag": tag_lines[0]["tag"],
                "msg": tag_lines[0]["msg"][:120],
                "match": "none",
            }]
        else:
            status = "skipped"
            confidence = "high"
            evidence = []

        first_time = evidence[0]["time"] if evidence else None
        detail_parts = [f"[{e['time']}] {e['msg']}" for e in evidence[:3]]
        detail = "; ".join(detail_parts) if detail_parts else ""
        if len(detail) > 200:
            detail = detail[:197] + "..."

        phases_result.append({
            "name": pm["product_phase"],
            "status": status,
            "confidence": confidence,
            "time": first_time,
            "detail": detail,
            "evidence": evidence,
        })

    has_failed = any(p["status"] == "failed" for p in phases_result)
    rec_status = "failed" if has_failed else ("interrupted" if recording.get("end_reason") == "interrupted" else "success")

    return {
        "record_id": recording.get("record_id", "unknown"),
        "status": rec_status,
        "phases": phases_result,
    }
```

- [ ] **Step 2: Run all PhaseEngine tests**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v -k "phase"
```
Expected: all 5 `test_phase_*` PASS

- [ ] **Step 3: Commit**

```bash
git add tools/log-analyzer/pipeline_analyzer.py
git commit -m "feat: implement PhaseEngine with config-driven pattern matching"
```

---

### Task 6: `analyze_pipeline()` — Entry Point + Tests

**Files:**
- Modify: `tools/log-analyzer/pipeline_analyzer.py`
- Modify: `tools/log-analyzer/tests/test_pipeline_analyzer.py`

- [ ] **Step 1: Add `analyze_pipeline` test**

Append to `tools/log-analyzer/tests/test_pipeline_analyzer.py`:

```python
# ── analyze_pipeline (entry point) tests ─────────────────────────────

def test_analyze_pipeline_end_to_end(tmp_path):
    from pipeline_analyzer import analyze_pipeline

    f = tmp_path / "e2e.log"
    f.write_text(ALL_SUCCESS_LOG, encoding="utf-8")
    scenario = _load_scenario()
    result = analyze_pipeline(str(f), scenario)
    assert "recordings" in result
    assert "summary" in result
    assert result["summary"]["total"] == 1
    assert result["summary"]["success"] == 1
    assert len(result["recordings"]) == 1
    assert len(result["recordings"][0]["phases"]) == 5


def test_analyze_pipeline_no_boundaries_returns_none():
    from pipeline_analyzer import analyze_pipeline
    result = analyze_pipeline("/dev/null", {"phases": []})
    assert result is None


def test_analyze_pipeline_multi_recordings(tmp_path):
    from pipeline_analyzer import analyze_pipeline

    f = tmp_path / "multi.log"
    f.write_text(MULTI_RECORDING_LOG, encoding="utf-8")
    scenario = _load_scenario()
    result = analyze_pipeline(str(f), scenario)
    assert result["summary"]["total"] == 3
    assert len(result["recordings"]) == 3
```

- [ ] **Step 2: Implement `analyze_pipeline()`**

Append to `tools/log-analyzer/pipeline_analyzer.py`:

```python
def analyze_pipeline(file_path: str, scenario: dict) -> dict | None:
    """Entry point: split recordings and analyze phases.

    Returns None if scenario lacks recording_boundaries or phase_mapping.
    """
    boundaries = scenario.get("recording_boundaries")
    phase_mapping = scenario.get("phase_mapping")
    if not boundaries or not phase_mapping:
        return None

    recordings = split_recordings(file_path, boundaries)
    if not recordings:
        return {
            "recordings": [],
            "summary": {"total": 0, "success": 0, "failed": 0, "interrupted": 0, "low_confidence_phases": 0},
        }

    results = []
    low_confidence = 0
    status_counts = {"success": 0, "failed": 0, "interrupted": 0}

    for rec in recordings:
        analyzed = analyze_phases(rec, phase_mapping)
        for p in analyzed.get("phases", []):
            if p.get("confidence") == "low":
                low_confidence += 1
            p.pop("evidence", None)  # evidence only in detailed output
        results.append(analyzed)
        s = analyzed.get("status", "success")
        if s in status_counts:
            status_counts[s] += 1

    return {
        "recordings": results,
        "summary": {
            "total": len(results),
            **status_counts,
            "low_confidence_phases": low_confidence,
        },
    }
```

Wait — we need evidence in the detailed output for AI review. Let me reconsider: keep evidence in `analyze_pipeline` output, only strip it when appending to `diagnose_scenario` if it's too large. Actually the spec says the AI needs evidence, so keep it.

Replace the `analyze_pipeline` implementation — remove the `p.pop("evidence", None)` line:

```python
def analyze_pipeline(file_path: str, scenario: dict) -> dict | None:
    """Entry point: split recordings and analyze phases.

    Returns None if scenario lacks recording_boundaries or phase_mapping.
    """
    boundaries = scenario.get("recording_boundaries")
    phase_mapping = scenario.get("phase_mapping")
    if not boundaries or not phase_mapping:
        return None

    recordings = split_recordings(file_path, boundaries)
    if not recordings:
        return {
            "recordings": [],
            "summary": {"total": 0, "success": 0, "failed": 0, "interrupted": 0, "low_confidence_phases": 0},
        }

    results = []
    low_confidence = 0
    status_counts = {"success": 0, "failed": 0, "interrupted": 0}

    for rec in recordings:
        analyzed = analyze_phases(rec, phase_mapping)
        for p in analyzed.get("phases", []):
            if p.get("confidence") == "low":
                low_confidence += 1
        results.append(analyzed)
        s = analyzed.get("status", "success")
        if s in status_counts:
            status_counts[s] += 1

    return {
        "recordings": results,
        "summary": {
            "total": len(results),
            **status_counts,
            "low_confidence_phases": low_confidence,
        },
    }
```

- [ ] **Step 3: Run all tests**

```bash
cd tools/log-analyzer && python -m pytest tests/test_pipeline_analyzer.py -v
```
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tools/log-analyzer/pipeline_analyzer.py tools/log-analyzer/tests/test_pipeline_analyzer.py
git commit -m "feat: add analyze_pipeline entry point with summary stats"
```

---

### Task 7: Integrate into `diagnose_scenario`

**Files:**
- Modify: `tools/log-analyzer/server.py:922-928`

- [ ] **Step 1: Add pipeline_analyzer import and call**

In `tools/log-analyzer/server.py`, find this block (around line 922-928):

```python
    report = "\n".join(out)
    report_path = _save_report(report, scenario)
    out.append("")
    out.append(f"报告已保存: {report_path}")

    return "\n".join(out)
```

Replace with:

```python
    if best.get("recording_boundaries") and best.get("phase_mapping"):
        try:
            from pipeline_analyzer import analyze_pipeline
            pipeline_result = analyze_pipeline(file_path, best)
            if pipeline_result and pipeline_result.get("recordings"):
                import json as _json
                out.append("")
                out.append("--- 结构化分析 (JSON) ---")
                out.append(_json.dumps(pipeline_result, ensure_ascii=False, indent=2))
        except Exception as e:
            out.append(f"\n--- 结构化分析失败: {e} ---")

    report = "\n".join(out)
    report_path = _save_report(report, scenario)
    out.append("")
    out.append(f"报告已保存: {report_path}")

    return "\n".join(out)
```

- [ ] **Step 2: Verify no syntax errors**

```bash
cd tools/log-analyzer && python -c "import server; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/log-analyzer/server.py
git commit -m "feat: integrate pipeline_analyzer into diagnose_scenario output"
```

---

### Task 8: `web-diagnostic/server.py` — Parse pipeline_result + Fallback

**Files:**
- Modify: `web-diagnostic/server.py`

- [ ] **Step 1: Add pipeline_result extraction regex and parser**

In `web-diagnostic/server.py`, after the existing `_EXTRACT_FILE_RE` definition (around line 638), add:

```python
_PIPELINE_RESULT_RE = re.compile(
    r'--- 结构化分析 \(JSON\) ---\s*(\{.+)',
    re.DOTALL,
)


def _extract_pipeline_result(tool_result: str) -> dict | None:
    """Extract pipeline analyzer JSON from diagnose_scenario output."""
    m = _PIPELINE_RESULT_RE.search(tool_result)
    if not m:
        return None
    blob = m.group(1)
    brace_start = blob.find("{")
    if brace_start < 0:
        return None
    extracted = _extract_balanced_json_object(blob, brace_start)
    if not extracted:
        return None
    try:
        data = json.loads(extracted)
        if isinstance(data.get("recordings"), list):
            return data
    except json.JSONDecodeError:
        pass
    return None
```

- [ ] **Step 2: Capture pipeline_result from tool_result events**

In the `_run_task` function, find the block that handles `event.role == "user" and event.tool_result` (around line 326). After the existing `if task.template == "audio-recognition":` ASR parsing block, add:

```python
                        if task.template == "audio-recognition" and not server_pipeline_data:
                            _pipeline = _extract_pipeline_result(event.tool_result)
                            if _pipeline:
                                server_pipeline_data = _pipeline
```

Also add `server_pipeline_data: dict | None = None` in the variable declarations at the top of `_run_task` (near `server_asr_records`).

- [ ] **Step 3: Add fallback logic in the `event.is_result` block**

In the `if event.is_result:` block, after `_merge_asr_into_recordings(template_data, server_asr_records)`, add:

```python
                if not template_data and server_pipeline_data:
                    template_data = {
                        "template": task.template or "audio-recognition",
                        "recordings": server_pipeline_data.get("recordings", []),
                    }
                    _merge_asr_into_recordings(template_data, server_asr_records)
```

- [ ] **Step 4: Run existing tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add web-diagnostic/server.py
git commit -m "feat: extract pipeline_result from diagnose_scenario and use as fallback"
```

---

### Task 9: Prompt Adaptation

**Files:**
- Modify: `web-diagnostic/server.py`

- [ ] **Step 1: Update `_build_template_prompt` for asr_records templates**

In `web-diagnostic/server.py`, find the `_full_extract_hint` string in `_build_template_prompt` (around line 530). After the closing `"""` of the returned prompt string for the `asr_records` branch, locate the line that says:

```python
输出 JSON 代码块后，换行继续输出正常的 Markdown 诊断报告。"""
```

Insert before the closing `"""` (inside the f-string):

```

[重要] diagnose_scenario 的返回中可能已包含「结构化分析 (JSON)」段，
其中的 recordings[] 是脚本根据日志 pattern 自动生成的阶段判定（含 confidence 和 evidence）。
若存在该段：
1. 审阅每个 recording 的 phases，尤其是 confidence: "low" 的阶段需要你用日志上下文做最终判定
2. confidence: "high" 的阶段可直接采纳，将 evidence 中的关键信息写入 detail
3. 如需修正，直接在你输出的 JSON 中覆盖对应阶段的 status/detail
4. 你**不需要**使用 Grep 或其他工具搜索日志，所有关键证据已在 evidence 中提供
```

- [ ] **Step 2: Run tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add web-diagnostic/server.py
git commit -m "feat: adapt template prompt to leverage pipeline_result"
```

---

### Task 10: Integration Test

**Files:**
- Modify: `web-diagnostic/tests/test_asr_parsing.py`

- [ ] **Step 1: Add pipeline_result extraction test**

Append to `web-diagnostic/tests/test_asr_parsing.py`:

```python
from server import _extract_pipeline_result


def test_extract_pipeline_result_from_diagnose_output():
    tool_output = """============================================================
场景化诊断: AIVoice 流式通道
============================================================
--- 排查路径 ---
  1. Token
--- 相关日志（共 5 条）---
  [10:00:01] [Info ] [AIBuds_Token] scene: create - new token success

--- 结构化分析 (JSON) ---
{
  "recordings": [
    {
      "record_id": "ej_test",
      "status": "success",
      "phases": [
        {"name": "选择设备", "status": "success", "confidence": "high", "time": "10:00:01", "detail": "ok", "evidence": []}
      ]
    }
  ],
  "summary": {"total": 1, "success": 1, "failed": 0, "interrupted": 0, "low_confidence_phases": 0}
}

报告已保存: /tmp/report.txt"""
    result = _extract_pipeline_result(tool_output)
    assert result is not None
    assert len(result["recordings"]) == 1
    assert result["recordings"][0]["record_id"] == "ej_test"
    assert result["summary"]["total"] == 1


def test_extract_pipeline_result_returns_none_without_section():
    result = _extract_pipeline_result("no pipeline data here")
    assert result is None
```

- [ ] **Step 2: Run all tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 3: Run log-analyzer tests too**

```bash
cd tools/log-analyzer && python -m pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add web-diagnostic/tests/test_asr_parsing.py
git commit -m "test: add integration tests for pipeline_result extraction"
```
