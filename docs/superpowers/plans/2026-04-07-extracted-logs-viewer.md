# Extracted Logs Viewer + ASR Server-Side Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add extracted log file viewer/downloader to all result templates, and replace AI-generated `asr_records` with server-side Python parsing from a dedicated ASR sub-file.

**Architecture:** Intercept `tool_result` events during AI streaming to capture `extract_aibuds_logs` output file paths; for ASR templates, auto-generate a filtered sub-file and parse structured records via regex; expose a `/api/extracted-file` endpoint for content fetch and download; frontend renders a lazy-loaded `<details>` viewer for each file in both timeline and markdown render modes.

**Tech Stack:** Python (FastAPI, asyncio, regex, pathlib), Vanilla JS (ES modules, fetch API, CustomEvent), HTML `<details>/<summary>` with toggle events, Tailwind CSS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `web-diagnostic/server.py` | Modify | `_EXTRACT_FILE_RE`, `_create_asr_subfile()`, `_parse_asr_records()`, path capture in `_run_task`, `/api/extracted-file` endpoint, `extracted_files` in history + WS result, remove ASR from prompt |
| `web-diagnostic/tests/test_asr_parsing.py` | Create | Unit tests for `_create_asr_subfile()` and `_parse_asr_records()` |
| `web-diagnostic/tests/test_extracted_file_api.py` | Create | Integration tests for `/api/extracted-file` endpoint |
| `web-diagnostic/frontend/src/main.js` | Modify | Store `extracted_files` in resultMeta (live result + history load) |
| `web-diagnostic/frontend/src/components/report.js` | Modify | `_buildExtractedFilesHtml()`, `_bindLogViewers()`, call in both render modes |

---

### Task 1: ASR Sub-file Creation Helper

**Files:**
- Modify: `web-diagnostic/server.py` (add after `_extract_template_data`)
- Create: `web-diagnostic/tests/test_asr_parsing.py`

- [ ] **Step 1: Write the failing test**

```python
# web-diagnostic/tests/test_asr_parsing.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import pytest
from server import _create_asr_subfile


def _write_temp_log(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        suffix=".log", delete=False, mode="w", encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


MIXED_LOG = """\
2024-01-01 10:00:00.001 [AIBuds_ASR] Received - Start - req_001
2024-01-01 10:00:01.000 [AIBuds_CONN] some other log line
2024-01-01 10:00:02.000 [AIBuds_ASR] asr - Update - req_001 - 今天天气
2024-01-01 10:00:05.000 [AIBuds_ASR] ASRTask ended, Request ID: req_001, Error: None
"""


def test_create_asr_subfile_filters_only_asr_lines(tmp_path):
    src = tmp_path / "aiBuds_20260407_120000.log"
    src.write_text(MIXED_LOG, encoding="utf-8")

    result = _create_asr_subfile(str(src))
    assert result is not None

    asr_lines = Path(result).read_text(encoding="utf-8").splitlines()
    assert len(asr_lines) == 3
    assert all("[AIBuds_ASR]" in line for line in asr_lines)


def test_create_asr_subfile_returns_none_for_missing_file():
    result = _create_asr_subfile("/nonexistent/path.log")
    assert result is None


def test_create_asr_subfile_returns_none_for_empty_asr_content(tmp_path):
    src = tmp_path / "aiBuds_no_asr.log"
    src.write_text("no asr lines here\nonly other logs\n", encoding="utf-8")

    result = _create_asr_subfile(str(src))
    assert result is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd web-diagnostic && python -m pytest tests/test_asr_parsing.py -v 2>&1 | head -30
```
Expected: `ImportError` or `AttributeError: module 'server' has no attribute '_create_asr_subfile'`

- [ ] **Step 3: Add `_create_asr_subfile` to server.py**

Add after `_extract_template_data` function (around line 493 in server.py):

```python
def _create_asr_subfile(full_log_path: str) -> str | None:
    """从全量 AIBuds 日志中过滤 [AIBuds_ASR] 行，保存为子文件。无 ASR 行时返回 None。"""
    src = Path(full_log_path)
    if not src.is_file():
        return None
    lines = [
        l for l in src.read_text(encoding="utf-8", errors="replace").splitlines()
        if "[AIBuds_ASR]" in l
    ]
    if not lines:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = src.parent / f"aiBuds_ASR_{ts}.log"
    dest.write_text("\n".join(lines), encoding="utf-8")
    return str(dest)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd web-diagnostic && python -m pytest tests/test_asr_parsing.py::test_create_asr_subfile_filters_only_asr_lines tests/test_asr_parsing.py::test_create_asr_subfile_returns_none_for_missing_file tests/test_asr_parsing.py::test_create_asr_subfile_returns_none_for_empty_asr_content -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd web-diagnostic && git add server.py tests/test_asr_parsing.py
git commit -m "feat: add _create_asr_subfile helper for ASR secondary extraction"
```

---

### Task 2: ASR Records Parser

**Files:**
- Modify: `web-diagnostic/server.py` (add after `_create_asr_subfile`)
- Modify: `web-diagnostic/tests/test_asr_parsing.py` (add new tests)

- [ ] **Step 1: Write the failing tests**

Append to `web-diagnostic/tests/test_asr_parsing.py`:

```python
from server import _parse_asr_records

ASR_LOG = """\
2024-01-01 10:23:01.123 [AIBuds_ASR] Received - Start - ej_req001
2024-01-01 10:23:05.000 [AIBuds_ASR] asr - Update - ej_req001 - 今天天气
2024-01-01 10:23:08.000 [AIBuds_ASR] asr - Update - ej_req001 - 今天天气怎么样
2024-01-01 10:23:08.500 [AIBuds_ASR] asr - Update - ej_req001 - 今天天气怎么样
2024-01-01 10:23:10.000 [AIBuds_ASR] Start sending to the mini-program, requestId: ej_req001 asr: 今天天气怎么样？, translate: Today weather
2024-01-01 10:23:23.260 [AIBuds_ASR] ASRTask ended, end time: 23260, Request ID: ej_req001, Error: None
2024-01-01 10:23:23.300 [AIBuds_ASR] Received cloud End duration：20449
"""

ASR_LOG_EMPTY = """\
2024-01-01 10:25:00.000 [AIBuds_ASR] Received - Start - ej_req002
2024-01-01 10:25:05.000 [AIBuds_ASR] asr & translate All data is empty, requestId: ej_req002
2024-01-01 10:25:05.100 [AIBuds_ASR] ASRTask ended, end time: 25100, Request ID: ej_req002, Error: None
"""

ASR_LOG_ERROR = """\
2024-01-01 10:30:00.000 [AIBuds_ASR] Received - Start - ej_req003
2024-01-01 10:30:10.000 [AIBuds_ASR] ASRTask ended, end time: 30100, Request ID: ej_req003, Error: TIMEOUT
"""


def test_parse_asr_records_success(tmp_path):
    f = tmp_path / "asr.log"
    f.write_text(ASR_LOG, encoding="utf-8")
    records = _parse_asr_records(str(f))
    assert len(records) == 1
    r = records[0]
    assert r["request_id"] == "ej_req001"
    assert r["status"] == "success"
    assert r["final_text"] == "今天天气怎么样？"
    assert r["translation"] == "Today weather"
    assert r["duration_ms"] == 20449
    assert r["error"] is None
    # adjacent duplicate update should be deduped
    assert len(r["updates"]) == 2
    assert r["updates"][0]["text"] == "今天天气"
    assert r["updates"][1]["text"] == "今天天气怎么样"


def test_parse_asr_records_empty_status(tmp_path):
    f = tmp_path / "asr_empty.log"
    f.write_text(ASR_LOG_EMPTY, encoding="utf-8")
    records = _parse_asr_records(str(f))
    assert len(records) == 1
    assert records[0]["status"] == "empty"
    assert records[0]["final_text"] == ""


def test_parse_asr_records_error_status(tmp_path):
    f = tmp_path / "asr_error.log"
    f.write_text(ASR_LOG_ERROR, encoding="utf-8")
    records = _parse_asr_records(str(f))
    assert len(records) == 1
    assert records[0]["status"] == "error"
    assert records[0]["error"] == "TIMEOUT"


def test_parse_asr_records_empty_file(tmp_path):
    f = tmp_path / "empty.log"
    f.write_text("", encoding="utf-8")
    assert _parse_asr_records(str(f)) == []


def test_parse_asr_records_missing_file():
    assert _parse_asr_records("/nonexistent.log") == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd web-diagnostic && python -m pytest tests/test_asr_parsing.py -k "parse_asr" -v 2>&1 | head -20
```
Expected: `AttributeError: module 'server' has no attribute '_parse_asr_records'`

- [ ] **Step 3: Add `_parse_asr_records` to server.py**

Add after `_create_asr_subfile`:

```python
_ASR_TIMESTAMP_RE = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d+)')
_ASR_START_RE = re.compile(r'Received - Start - (\S+)')
_ASR_UPDATE_RE = re.compile(r'asr - Update - (\S+) - (.+)')
_ASR_SEND_RE = re.compile(r'Start sending to the mini-program.*?requestId:\s*(\S+)\s+asr:\s*(.*?),\s*translate:\s*(.*?)(?:\s*$|\s+\w+:)')
_ASR_ENDED_RE = re.compile(r'ASRTask ended.*?Request ID:\s*(\S+),\s*Error:\s*(.+)')
_ASR_DURATION_RE = re.compile(r'Received cloud End duration[：:]\s*(\d+)')
_ASR_EMPTY_RE = re.compile(r'asr & translate All data is empty.*?requestId:\s*(\S+)')


def _parse_asr_records(asr_log_path: str) -> list[dict]:
    """解析 ASR 子文件，按 requestId 分组生成结构化记录。"""
    path = Path(asr_log_path)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []

    # ordered dict: requestId → record
    records: dict[str, dict] = {}
    order: list[str] = []

    def get_or_create(rid: str) -> dict:
        if rid not in records:
            records[rid] = {
                "request_id": rid,
                "start_time": None,
                "end_time": None,
                "duration_ms": None,
                "final_text": "",
                "translation": "",
                "status": "success",
                "error": None,
                "updates": [],
                "_last_update_text": "",
                "_has_empty": False,
            }
            order.append(rid)
        return records[rid]

    last_rid: str | None = None

    for line in text.splitlines():
        ts_m = _ASR_TIMESTAMP_RE.search(line)
        ts = ts_m.group(1) if ts_m else ""

        if m := _ASR_START_RE.search(line):
            rid = m.group(1).rstrip(",")
            r = get_or_create(rid)
            r["start_time"] = ts
            last_rid = rid

        elif m := _ASR_UPDATE_RE.search(line):
            rid = m.group(1).rstrip(",")
            txt = m.group(2).strip()
            r = get_or_create(rid)
            if txt != r["_last_update_text"]:
                r["updates"].append({"time": ts, "text": txt})
                r["_last_update_text"] = txt
            last_rid = rid

        elif m := _ASR_SEND_RE.search(line):
            rid = m.group(1).rstrip(",")
            r = get_or_create(rid)
            r["final_text"] = m.group(2).strip().rstrip("？?。，,")
            # restore final punctuation if present
            raw_asr = m.group(2).strip()
            r["final_text"] = raw_asr
            r["translation"] = m.group(3).strip()
            last_rid = rid

        elif m := _ASR_ENDED_RE.search(line):
            rid = m.group(1).rstrip(",")
            err_raw = m.group(2).strip()
            r = get_or_create(rid)
            r["end_time"] = ts
            if err_raw and err_raw.lower() != "none":
                r["error"] = err_raw
                r["status"] = "error"
            last_rid = rid

        elif m := _ASR_DURATION_RE.search(line):
            # associate with most recent record
            target_rid = last_rid
            if target_rid and target_rid in records:
                records[target_rid]["duration_ms"] = int(m.group(1))

        elif m := _ASR_EMPTY_RE.search(line):
            rid = m.group(1).rstrip(",")
            r = get_or_create(rid)
            r["_has_empty"] = True
            last_rid = rid

    # finalize
    result = []
    for rid in order:
        r = records[rid]
        if r["_has_empty"] and r["status"] == "success":
            r["status"] = "empty"
        # clean internal tracking fields
        del r["_last_update_text"]
        del r["_has_empty"]
        result.append(r)

    return result[:20]  # cap at 20 records
```

- [ ] **Step 4: Run all asr parsing tests**

```bash
cd web-diagnostic && python -m pytest tests/test_asr_parsing.py -v
```
Expected: all 8 tests pass

- [ ] **Step 5: Commit**

```bash
cd web-diagnostic && git add server.py tests/test_asr_parsing.py
git commit -m "feat: add _parse_asr_records for server-side ASR structured extraction"
```

---

### Task 3: Capture Extracted File Paths in `_run_task` + ASR Secondary Extraction

**Files:**
- Modify: `web-diagnostic/server.py` (`_run_task`, `_save_history`, `_format_ws_message`, `_load_history_detail`)

- [ ] **Step 1: Add `_EXTRACT_FILE_RE` regex constant**

Add after the `_TEMPLATE_DATA_RE` definition (around line 479):

```python
_EXTRACT_FILE_RE = re.compile(r'输出文件[：:]\s*([^\s(]+\.log)', re.MULTILINE)
```

- [ ] **Step 2: Modify `_run_task` to collect extracted file paths**

In `_run_task`, add `extracted_files: list[dict] = []` to the variable declarations block (alongside `template_data: dict | None = None`):

```python
    extracted_files: list[dict] = []
```

Still inside the `async for event in runner.run(...)` loop, after the existing `event_count += 1` line, add interception for `tool_result` events to capture file paths. Insert before the `if event.is_result:` block:

```python
            # 捕获 extract_aibuds_logs 输出的文件路径
            if event.role == "user" and event.tool_result:
                fm = _EXTRACT_FILE_RE.search(event.tool_result)
                if fm:
                    raw_path = fm.group(1).strip()
                    abs_path = Path(raw_path)
                    if not abs_path.is_absolute():
                        abs_path = _REPO / raw_path
                    if abs_path.is_file():
                        try:
                            rel = abs_path.relative_to(_REPO)
                        except ValueError:
                            rel = abs_path
                        extracted_files.append({
                            "path": str(rel),
                            "name": "全量提取",
                            "type": "full",
                            "size_kb": round(abs_path.stat().st_size / 1024, 1),
                        })
                        # ASR 模版：生成 ASR 子文件并解析 asr_records
                        if task.template in ("audio-recognition", "translation"):
                            asr_path = _create_asr_subfile(str(abs_path))
                            if asr_path:
                                asr_abs = Path(asr_path)
                                try:
                                    asr_rel = asr_abs.relative_to(_REPO)
                                except ValueError:
                                    asr_rel = asr_abs
                                extracted_files.append({
                                    "path": str(asr_rel),
                                    "name": "ASR提取",
                                    "type": "asr",
                                    "size_kb": round(asr_abs.stat().st_size / 1024, 1),
                                })
                                _asr_records_pending = _parse_asr_records(asr_path)
                                # 存入 template_data（稍后在 is_result 时合并）
                                if _asr_records_pending:
                                    if template_data is None:
                                        template_data = {}
                                    template_data.setdefault("asr_records", _asr_records_pending)
```

Then in the `if event.is_result:` block, **after** `template_data, result_text = _extract_template_data(result_text)`, merge any pending asr_records collected above:

```python
                # 合并服务端解析的 asr_records（优先于 AI 输出的字段）
                if extracted_files and template_data:
                    asr_from_server = [
                        ef for ef in extracted_files if ef["type"] == "asr"
                    ]
                    if asr_from_server and "asr_records" not in template_data:
                        pass  # already set above via setdefault
```

> Note: The `setdefault` call above ensures server-side records are only written if AI didn't output them; but since we're removing ASR from the prompt in Task 4, the AI won't output `asr_records` at all.

- [ ] **Step 3: Pass `extracted_files` through `_format_ws_message` and `_save_history`**

Update `_format_ws_message` signature and result message:

```python
def _format_ws_message(event: StreamEvent, template_data: dict | None = None, extracted_files: list | None = None) -> dict | None:
```

In the `if event.is_result:` branch of `_format_ws_message`, add:

```python
        if extracted_files:
            msg["extracted_files"] = extracted_files
```

Update the call site in `_run_task`:

```python
            msg = _format_ws_message(event, template_data if event.is_result else None, extracted_files if event.is_result else None)
```

Update `_save_history` signature:

```python
def _save_history(task: QueuedTask, result: str, duration_ms: int, cost_usd: float, tool_count: int, status: str, template_data: dict | None = None, extracted_files: list | None = None) -> str | None:
```

In `_save_history`, after `if template_data: record["template_data"] = template_data`, add:

```python
        if extracted_files:
            record["extracted_files"] = extracted_files
```

Update the call site in `_run_task`:

```python
        hist_file = _save_history(task, result_text, result_duration, result_cost, tool_count, "done", template_data, extracted_files)
```

Update `_load_history_detail` to expose `extracted_files`:

```python
        data.setdefault("extracted_files", [])
```

- [ ] **Step 4: Manually verify**

```bash
cd web-diagnostic && python -c "
from server import _EXTRACT_FILE_RE
test = 'tools/log-analyzer/data/aiBuds__20260407.log (196.8KB)\n输出文件: tools/log-analyzer/data/aiBuds__20260407.log (196.8KB)'
m = _EXTRACT_FILE_RE.search(test)
print('Match:', m.group(1) if m else 'NONE')
"
```
Expected: `Match: tools/log-analyzer/data/aiBuds__20260407.log`

- [ ] **Step 5: Commit**

```bash
cd web-diagnostic && git add server.py
git commit -m "feat: capture extracted file paths in _run_task and trigger ASR secondary extraction"
```

---

### Task 4: New `/api/extracted-file` Endpoint

**Files:**
- Modify: `web-diagnostic/server.py` (add new route)
- Create: `web-diagnostic/tests/test_extracted_file_api.py`

- [ ] **Step 1: Write failing tests**

```python
# web-diagnostic/tests/test_extracted_file_api.py
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["WEB_DIAGNOSTIC_SKIP_CLAUDE"] = "1"

import pytest
from fastapi.testclient import TestClient
from server import app, UPLOAD_DIR


@pytest.fixture
def sample_log_file(tmp_path, monkeypatch):
    """Create a sample log file in the allowed directory."""
    # Write directly into UPLOAD_DIR which is tools/log-analyzer/data/
    log_file = UPLOAD_DIR / "test_sample_20260407.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    yield log_file
    log_file.unlink(missing_ok=True)


def test_extracted_file_returns_content(sample_log_file):
    client = TestClient(app)
    # path relative to WORKSPACE
    from server import _REPO
    rel = sample_log_file.relative_to(_REPO)
    resp = client.get(f"/api/extracted-file?path={rel}")
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "line1" in data["content"]
    assert "size_kb" in data


def test_extracted_file_download_mode(sample_log_file):
    client = TestClient(app)
    from server import _REPO
    rel = sample_log_file.relative_to(_REPO)
    resp = client.get(f"/api/extracted-file?path={rel}&dl=1")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_extracted_file_rejects_path_traversal():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=../../etc/passwd")
    assert resp.status_code == 400


def test_extracted_file_rejects_outside_allowed_dir():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=web-diagnostic/server.py")
    assert resp.status_code == 400


def test_extracted_file_not_found():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=tools/log-analyzer/data/nonexistent.log")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd web-diagnostic && python -m pytest tests/test_extracted_file_api.py -v 2>&1 | head -20
```
Expected: 404 or errors because endpoint doesn't exist yet

- [ ] **Step 3: Add `/api/extracted-file` endpoint to server.py**

Add before the `/health` route (or near the bottom of route definitions, before static mount):

```python
_ALLOWED_EXTRACTED_PREFIX = str(_REPO / "tools" / "log-analyzer" / "data")


@app.get("/api/extracted-file")
async def get_extracted_file(path: str, dl: int = 0):
    """Return content of an extracted log file, or trigger download."""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse

    # Security: reject path traversal
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    abs_path = (_REPO / path).resolve()

    # Security: whitelist — must be inside tools/log-analyzer/data/
    if not str(abs_path).startswith(_ALLOWED_EXTRACTED_PREFIX):
        raise HTTPException(status_code=400, detail="Path not allowed")

    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if dl:
        return FileResponse(
            str(abs_path),
            media_type="text/plain",
            filename=abs_path.name,
            headers={"Content-Disposition": f'attachment; filename="{abs_path.name}"'},
        )

    content = abs_path.read_text(encoding="utf-8", errors="replace")
    size_kb = round(abs_path.stat().st_size / 1024, 1)
    return JSONResponse({"content": content, "size_kb": size_kb})
```

- [ ] **Step 4: Run all tests**

```bash
cd web-diagnostic && python -m pytest tests/test_extracted_file_api.py tests/test_health.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd web-diagnostic && git add server.py tests/test_extracted_file_api.py
git commit -m "feat: add /api/extracted-file endpoint with path whitelist security"
```

---

### Task 5: Remove ASR Records from AI Prompt

**Files:**
- Modify: `web-diagnostic/server.py` (`_build_template_prompt`)

- [ ] **Step 1: Remove `asr_records` field and `_ASR_RECORDS_HINT` from the prompt**

In `_build_template_prompt`, the current code conditionally appends `asr_field` and `asr_hint` for ASR templates. Since `asr_records` is now parsed server-side, remove it from the prompt entirely.

Find in `_build_template_prompt` for the explicit template branch (around line 431-447):

```python
        needs_asr = meta.get("asr_records", False)
        asr_field = f",\n{_asr_records_example}" if needs_asr else ""
        asr_hint = _ASR_RECORDS_HINT if needs_asr else ""
```

Replace with:

```python
        asr_field = ""
        asr_hint = ""
```

Also find the auto-mode section that builds `asr_auto_hint` (around line 455-456):

```python
    asr_template_ids = [tid for tid, m in _TEMPLATE_PHASES.items() if m.get("asr_records")]
    asr_auto_hint = f"\n若匹配场景为 {'/'.join(asr_template_ids)} 之一，还需在 JSON 中额外填入 \"asr_records\" 数组。{_ASR_RECORDS_HINT}" if asr_template_ids else ""
```

Replace with:

```python
    asr_auto_hint = ""
```

- [ ] **Step 2: Verify prompt no longer contains asr_records**

```bash
cd web-diagnostic && python -c "
from server import _build_template_prompt
p = _build_template_prompt('audio-recognition')
assert 'asr_records' not in p, 'FAIL: asr_records still in prompt'
print('OK: asr_records removed from prompt')
p2 = _build_template_prompt('auto')
assert 'asr_records' not in p2, 'FAIL: asr_records still in auto prompt'
print('OK: asr_records removed from auto prompt')
"
```
Expected: two `OK:` lines

- [ ] **Step 3: Commit**

```bash
cd web-diagnostic && git add server.py
git commit -m "feat: remove asr_records from AI prompt, now parsed server-side"
```

---

### Task 6: Frontend — Store `extracted_files` in `resultMeta`

**Files:**
- Modify: `web-diagnostic/frontend/src/main.js`

- [ ] **Step 1: Update live result handler**

In `main.js`, find the `ws.onMessage('result', ...)` handler (around line 319). Find:

```javascript
  store.set('resultMeta', {
    status: 'success',
    duration_ms: msg.duration_ms || 0,
    cost_usd: msg.cost_usd || 0,
    template_data: msg.template_data || null,
  });
```

Replace with:

```javascript
  store.set('resultMeta', {
    status: 'success',
    duration_ms: msg.duration_ms || 0,
    cost_usd: msg.cost_usd || 0,
    template_data: msg.template_data || null,
    extracted_files: msg.extracted_files || [],
  });
```

- [ ] **Step 2: Update history load path**

In `main.js`, find the `reportFile` loading block at the bottom (around line 397). Find:

```javascript
      store.set('resultMeta', {
        duration_ms: data.duration_ms || 0,
        cost_usd: data.cost_usd || 0,
        tool_count: data.tool_count || 0,
        score: data.score,
        has_failure: data.has_failure,
        template_data: data.template_data || null,
      });
```

Replace with:

```javascript
      store.set('resultMeta', {
        duration_ms: data.duration_ms || 0,
        cost_usd: data.cost_usd || 0,
        tool_count: data.tool_count || 0,
        score: data.score,
        has_failure: data.has_failure,
        template_data: data.template_data || null,
        extracted_files: data.extracted_files || [],
      });
```

- [ ] **Step 3: Verify by inspecting the edit**

```bash
grep -n "extracted_files" web-diagnostic/frontend/src/main.js
```
Expected: two lines, one in the result handler and one in the history load

- [ ] **Step 4: Commit**

```bash
git add web-diagnostic/frontend/src/main.js
git commit -m "feat: store extracted_files in resultMeta for live result and history load"
```

---

### Task 7: Frontend — Extracted Files Viewer in `report.js`

**Files:**
- Modify: `web-diagnostic/frontend/src/components/report.js`

- [ ] **Step 1: Add `_buildExtractedFilesHtml(files)` method**

In `report.js`, add the new method before `_bannerStyle()`:

```javascript
  _buildExtractedFilesHtml(files) {
    if (!Array.isArray(files) || !files.length) return '';

    const typeBadge = (type) => {
      if (type === 'asr') {
        return `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border border-neon-purple/40 bg-neon-purple/10 text-neon-purple">ASR</span>`;
      }
      return `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary">FULL</span>`;
    };

    const items = files.map((f, i) => {
      const name = esc(f.name || f.path.split('/').pop());
      const size = f.size_kb ? `${f.size_kb} KB` : '';
      const badge = typeBadge(f.type || 'full');
      const encodedPath = encodeURIComponent(f.path);
      return `
<details class="rounded border border-primary/10 bg-bg-dark/60" data-log-viewer="${i}" data-log-path="${esc(f.path)}">
  <summary class="flex flex-wrap items-center gap-2 px-3 py-2 cursor-pointer list-none select-none hover:bg-primary/5 rounded transition-colors">
    <span class="material-symbols-outlined text-sm text-slate-500">description</span>
    <span class="text-xs text-slate-300 font-mono">${name}</span>
    ${size ? `<span class="text-[10px] text-slate-500">${esc(size)}</span>` : ''}
    ${badge}
    <a href="/api/extracted-file?path=${encodedPath}&dl=1"
       class="ml-auto text-[10px] font-bold text-primary hover:text-primary/70 flex items-center gap-1 shrink-0"
       onclick="event.stopPropagation()"
       download>
      <span class="material-symbols-outlined text-sm">download</span>
      下载
    </a>
  </summary>
  <div class="px-3 pb-3 pt-1 border-t border-primary/10">
    <pre class="text-[11px] font-mono text-slate-400 overflow-x-auto whitespace-pre-wrap max-h-96 overflow-y-auto" data-log-content>加载中…</pre>
  </div>
</details>`;
    }).join('');

    return `
<div class="rounded-lg border border-primary/15 bg-surface/40 p-4">
  <p class="text-[10px] uppercase tracking-widest text-primary/50 font-bold mb-3 flex items-center gap-1.5">
    <span class="material-symbols-outlined text-sm">folder_open</span>
    提取日志（${files.length} 个文件）
  </p>
  <div class="space-y-2">${items}</div>
</div>`;
  }
```

- [ ] **Step 2: Add `_bindLogViewers()` method for lazy-load**

Add after `_buildExtractedFilesHtml`:

```javascript
  _bindLogViewers() {
    const viewers = this.el.querySelectorAll('[data-log-viewer]');
    viewers.forEach((details) => {
      const path = details.getAttribute('data-log-path');
      const pre = details.querySelector('[data-log-content]');
      if (!pre || !path) return;
      let loaded = false;
      details.addEventListener('toggle', async () => {
        if (!details.open || loaded) return;
        loaded = true;
        try {
          const resp = await fetch(`/api/extracted-file?path=${encodeURIComponent(path)}`);
          if (!resp.ok) {
            pre.textContent = `加载失败 (HTTP ${resp.status})`;
            return;
          }
          const data = await resp.json();
          pre.textContent = data.content || '（文件为空）';
        } catch (e) {
          pre.textContent = `加载失败: ${e.message}`;
        }
      });
    });
  }
```

- [ ] **Step 3: Insert extracted files section into `_renderTimeline()`**

In `_renderTimeline()`, find the existing `asrHtml` variable and where it's used. Locate the section that builds the `asrHtml` conditional block (around line 125). Add extracted files HTML just before the action buttons section.

Find in `_renderTimeline()`:

```javascript
    const asrRecords = Array.isArray(td.asr_records) ? td.asr_records : [];
    const asrHtml = asrRecords.length ? this._buildAsrRecordsHtml(asrRecords) : '';
```

Add after:

```javascript
    const extractedFiles = Array.isArray(this._meta.extracted_files) ? this._meta.extracted_files : [];
    const extractedFilesHtml = this._buildExtractedFilesHtml(extractedFiles);
```

Then in the returned HTML template, find the `<div class="flex flex-wrap gap-2 justify-center` (action buttons), and insert `${extractedFilesHtml}` just before it:

```javascript
  ${extractedFilesHtml}

  <div class="flex flex-wrap gap-2 justify-center sm:justify-start pb-2">
```

- [ ] **Step 4: Insert extracted files section into `_renderMarkdown()`**

In `_renderMarkdown()`, find the article element containing `data-report-body` and the action buttons `<div class="flex flex-wrap gap-2`. Before the action buttons div, add:

```javascript
    const extractedFiles = Array.isArray(this._meta.extracted_files) ? this._meta.extracted_files : [];
    const extractedFilesHtml = this._buildExtractedFilesHtml(extractedFiles);
```

And insert `${extractedFilesHtml}` just before the action buttons div in the returned template.

- [ ] **Step 5: Call `_bindLogViewers()` from `onMount()`**

In `onMount()`:

```javascript
  onMount() {
    if (this._renderMode === 'timeline') {
      this._mountTimeline();
    } else {
      this._hydrateBody();
    }
    this._bindSharedActions();
    this._bindLogViewers();  // ADD THIS LINE
  }
```

- [ ] **Step 6: Verify `esc` is imported and used correctly**

```bash
grep -n "^import\|^  esc\|_buildExtracted" web-diagnostic/frontend/src/components/report.js | head -10
```
Confirm `esc` is imported from `../utils/helpers.js` (it already is per current code).

- [ ] **Step 7: Commit**

```bash
git add web-diagnostic/frontend/src/components/report.js
git commit -m "feat: add extracted log file viewer with lazy-load and download in report component"
```

---

### Task 8: Run Full Test Suite + Manual Smoke Test

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

```bash
cd web-diagnostic && python -m pytest tests/ -v
```
Expected: all tests pass (test_health, test_asr_parsing, test_extracted_file_api)

- [ ] **Step 2: Start dev server and verify**

```bash
cd web-diagnostic/frontend && npm run dev &
cd web-diagnostic && python server.py
```

- [ ] **Step 3: Manual verification checklist**

1. Submit audio-recognition diagnosis → result page shows "提取日志（2个文件）" section (全量 + ASR)
2. Expand a file → content lazy-loads (spinner → text)
3. Click "下载" → browser triggers file download
4. Non-ASR scenario (e.g., cloud-upload) → only 全量 file shown, no ASR file
5. Open a historical record with `extracted_files` → viewer/download works
6. AI output contains no `asr_records` field in JSON block (verify in browser terminal log)
7. ASR records section still populates correctly (server-side parsed)

- [ ] **Step 4: Final commit if any tweaks made**

```bash
git add -p  # review and stage only intentional changes
git commit -m "fix: post-integration tweaks for extracted logs viewer"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ `_create_asr_subfile()` — Task 1
- ✅ `_parse_asr_records()` — Task 2
- ✅ Path capture in `_run_task` — Task 3
- ✅ `/api/extracted-file` endpoint with security whitelist — Task 4
- ✅ Remove ASR from AI prompt — Task 5
- ✅ `main.js` `extracted_files` storage — Task 6
- ✅ `report.js` viewer + lazy-load in both render modes — Task 7
- ✅ History JSON `extracted_files` field + `_load_history_detail` — Task 3 (server.py)

**Type consistency:**
- `extracted_files` is always `list[dict]` on backend, `Array` on frontend
- `_create_asr_subfile` returns `str | None` — used correctly in Task 3
- `_parse_asr_records` returns `list[dict]` — used correctly in Task 3

**Security:**
- Path traversal protection: rejects `..` and absolute paths
- Whitelist: only `tools/log-analyzer/data/` prefix allowed
