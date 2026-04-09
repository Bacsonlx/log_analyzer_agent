import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from server import (
    _TEMPLATE_PHASES,
    _create_asr_subfile,
    _ensure_recordings_format,
    _extract_pipeline_result,
    _extract_template_data,
    _merge_asr_into_recordings,
    _normalize_template_id,
    _parse_asr_records,
)


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
    assert Path(result).name.startswith("aiBuds_ASR_")
    assert result.endswith(".log")

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


def test_parse_asr_records_interleaved_requests(tmp_path):
    """Duration line from req002 should not contaminate req001's duration_ms."""
    log = """\
2024-01-01 10:00:00.000 [AIBuds_ASR] Received - Start - req_a
2024-01-01 10:00:01.000 [AIBuds_ASR] Received - Start - req_b
2024-01-01 10:00:05.000 [AIBuds_ASR] ASRTask ended, end time: 5000, Request ID: req_a, Error: None
2024-01-01 10:00:05.500 [AIBuds_ASR] Received cloud End duration：5000
2024-01-01 10:00:08.000 [AIBuds_ASR] ASRTask ended, end time: 8000, Request ID: req_b, Error: None
2024-01-01 10:00:08.500 [AIBuds_ASR] Received cloud End duration：8000
"""
    f = tmp_path / "interleaved.log"
    f.write_text(log, encoding="utf-8")
    records = _parse_asr_records(str(f))
    assert len(records) == 2
    req_a = next(r for r in records if r["request_id"] == "req_a")
    req_b = next(r for r in records if r["request_id"] == "req_b")
    assert req_a["duration_ms"] == 5000
    assert req_b["duration_ms"] == 8000


def test_normalize_template_id_maps_deprecated_translation():
    assert _normalize_template_id("translation") == "audio-recognition"
    assert _normalize_template_id("recording") == "audio-recognition"
    assert _normalize_template_id("audio-recognition") == "audio-recognition"
    assert _normalize_template_id("auto") == "auto"


def test_template_phases_has_single_recognition_entry():
    assert "translation" not in _TEMPLATE_PHASES
    assert "recording" not in _TEMPLATE_PHASES
    ar = _TEMPLATE_PHASES["audio-recognition"]
    assert ar["label"] == "实时链路"
    assert ar["phases"][0]["name"] == "选择设备"
    assert ar["phases"][-1]["name"] == "识别结束"
    assert isinstance(ar["phases"][0]["modules"], list)
    assert len(ar["phases"][0]["modules"]) > 0


def test_merge_asr_into_recordings_by_record_id():
    td = {
        "template": "audio-recognition",
        "recordings": [
            {"record_id": "rec_A", "status": "success", "phases": []},
            {"record_id": "rec_B", "status": "failed", "phases": []},
        ],
    }
    asr = [
        {"request_id": "rec_A_0", "record_id": "rec_A", "status": "success", "final_text": "hello"},
        {"request_id": "rec_A_1", "record_id": "rec_A", "status": "success", "final_text": "world"},
        {"request_id": "rec_B_0", "record_id": "rec_B", "status": "error", "final_text": ""},
    ]
    _merge_asr_into_recordings(td, asr)
    assert len(td["recordings"][0]["asr_records"]) == 2
    assert len(td["recordings"][1]["asr_records"]) == 1
    assert td["recordings"][0]["asr_records"][0]["final_text"] == "hello"
    assert td["recordings"][1]["asr_records"][0]["status"] == "error"


def test_merge_asr_unmatched_goes_to_last_recording():
    td = {
        "recordings": [
            {"record_id": "rec_A", "phases": []},
        ],
    }
    asr = [
        {"request_id": "rec_X_0", "record_id": "rec_X", "status": "success", "final_text": "orphan"},
    ]
    _merge_asr_into_recordings(td, asr)
    assert len(td["recordings"][0]["asr_records"]) == 1
    assert td["recordings"][0]["asr_records"][0]["final_text"] == "orphan"


def test_merge_asr_noop_when_no_recordings():
    td = {"template": "recording", "phases": []}
    _merge_asr_into_recordings(td, [{"record_id": "x"}])
    assert "recordings" not in td


def test_ensure_recordings_format_wraps_flat_phases():
    td = {
        "template": "audio-recognition",
        "phases": [{"name": "选择设备", "status": "success"}],
        "asr_records": [{"request_id": "r1"}],
    }
    _ensure_recordings_format(td)
    assert "recordings" in td
    assert len(td["recordings"]) == 1
    assert td["recordings"][0]["record_id"] == "legacy"
    assert td["recordings"][0]["phases"][0]["name"] == "选择设备"
    assert len(td["recordings"][0]["asr_records"]) == 1
    assert "phases" not in td
    assert "asr_records" not in td


def test_ensure_recordings_format_noop_when_already_has_recordings():
    td = {
        "recordings": [{"record_id": "rec_A", "phases": []}],
    }
    _ensure_recordings_format(td)
    assert len(td["recordings"]) == 1
    assert td["recordings"][0]["record_id"] == "rec_A"


def test_ensure_recordings_format_noop_for_none():
    _ensure_recordings_format(None)


def test_extract_template_data_accepts_nested_recordings():
    """Per-recording JSON 含多层 phases 时，旧正则会在第一个「}」截断；须整段解析。"""
    inner = r""""recordings": [
    {
      "record_id": "rec_one",
      "status": "success",
      "phases": [
        {"name": "选择设备", "status": "skipped", "time": null, "detail": ""},
        {"name": "点击开始", "status": "success", "time": "10:00:01.000", "detail": "[AIBuds_Token] scene: create - new token success"}
      ]
    }
  ]"""
    body = f"""前言

```json
{{
  "template": "audio-recognition",
{inner}
}}
```

## 后续 Markdown
"""
    data, clean = _extract_template_data(body)
    assert data is not None
    assert data["template"] == "audio-recognition"
    assert len(data["recordings"]) == 1
    assert data["recordings"][0]["record_id"] == "rec_one"
    assert len(data["recordings"][0]["phases"]) == 2
    assert data["recordings"][0]["phases"][1]["name"] == "点击开始"
    assert "```json" not in clean
    assert "前言" in clean
    assert "后续 Markdown" in clean


def test_extract_template_data_flat_phases_still_works():
    body = """x

```json
{
  "template": "recording",
  "phases": [
    {"name": "录音入口", "status": "success", "time": null, "detail": "ok"}
  ]
}
```

tail"""
    data, clean = _extract_template_data(body)
    assert data["template"] == "recording"
    assert len(data["phases"]) == 1
    assert "x" in clean and "tail" in clean


def test_extract_template_data_skips_block_without_phases_or_recordings():
    body = """```json
{"template": "audio-recognition", "foo": []}
```

```json
{"template": "audio-recognition", "recordings": []}
```
end"""
    data, clean = _extract_template_data(body)
    assert data is not None
    assert data["recordings"] == []
    assert "end" in clean


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
