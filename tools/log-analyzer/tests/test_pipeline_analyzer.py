"""Tests for pipeline_analyzer.split_recordings and analyze_phases."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline_analyzer import (  # noqa: E402
    _enrich_status_codes,
    analyze_phases,
    analyze_pipeline,
    split_recordings,
)


def _load_streaming_channel_boundaries():
    root = Path(__file__).resolve().parent.parent
    cfg_path = root / "knowledge" / "aivoice-streaming-channel.json"
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["recording_boundaries"]


def _load_phase_mapping():
    root = Path(__file__).resolve().parent.parent
    cfg_path = root / "knowledge" / "aivoice-streaming-channel.json"
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["phase_mapping"]


def _phase_by_name(result: dict, name: str) -> dict:
    for p in result["phases"]:
        if p["name"] == name:
            return p
    raise KeyError(name)


def _one_recording_log(request_suffix="ej_req001_0"):
    return "\n".join(
        [
            "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
            "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
            f"2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: {request_suffix}",
            "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
            "",
        ]
    )


def test_split_single_recording_stopped(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    p = tmp_path / "one.log"
    p.write_text(_one_recording_log(), encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 1
    r = recs[0]
    assert r["record_id"] == "ej_req001"
    assert r["end_reason"] == "stopped"
    assert r["start_time"] == "10:00:01.000"
    assert r["end_time"] == "10:00:10.000"
    assert len(r["lines"]) == 4


def test_split_multi_three_stopped_stopped_paused(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:02 requestId: r1_0",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
        "2024-01-01 10:00:06.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:07.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:07 requestId: r2_1",
        "2024-01-01 10:00:08.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
        "2024-01-01 10:00:09.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:10 requestId: r3_2",
        "2024-01-01 10:00:11.000 [Info] <AIBuds_Record> Recording paused successfully, Device ID: dev001",
    ]
    p = tmp_path / "multi.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 3
    assert recs[0]["record_id"] == "r1"
    assert recs[0]["end_reason"] == "stopped"
    assert recs[1]["record_id"] == "r2"
    assert recs[1]["end_reason"] == "stopped"
    assert recs[2]["record_id"] == "r3"
    assert recs[2]["end_reason"] == "paused"


def test_split_interrupted_no_stop(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    lines = [
        "2024-01-01 09:59:00.000 [Info] <AIBuds_Token> warmup",
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: only_9",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
    ]
    p = tmp_path / "interrupted.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 1
    r = recs[0]
    assert r["end_reason"] == "interrupted"
    assert r["end_time"] is None
    assert r["record_id"] == "only"
    assert r["start_time"] == "10:00:01.000"


def test_split_no_start_boundary_fallback_one_segment(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    lines = [
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: fb_0",
        "2024-01-01 10:00:04.000 [Info] <AIBuds_Token> other",
    ]
    p = tmp_path / "no_start.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 1
    assert len(recs[0]["lines"]) == 3
    assert recs[0]["record_id"] == "fb"


def test_split_empty_file(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    p = tmp_path / "empty.log"
    p.write_text("", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert recs == []


def test_analyze_phases_all_success_high(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    phase_mapping = _load_phase_mapping()
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:01.100 [Info] <AIBuds_ASR> Token create asr config model: m1",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
        "2024-01-01 10:00:02.500 [Info] <AIBuds_Session> create - success sessionId sid1",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: stream - connected",
        "2024-01-01 10:00:03.100 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: allok_0",
        "2024-01-01 10:00:04.000 [Info] <AIBuds_AIChannel> pick_data - begin",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_Recognition> transcribe - text packet",
        "2024-01-01 10:00:06.000 [Info] <AIBuds_AIChannel> request - finished",
        "2024-01-01 10:00:06.500 [Info] <AIBuds_ASR> ASRTask ended (Error: None)",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "all_success.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 1
    result = analyze_phases(recs[0], phase_mapping)
    assert result["record_id"] == "allok"
    assert result["status"] == "success"
    for ph in result["phases"]:
        assert ph["status"] == "success"
        assert ph["confidence"] == "high"


def test_analyze_phases_token_failure_click_start(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    phase_mapping = _load_phase_mapping()
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:01.050 [Info] <AIBuds_ASR> Token create asr config model: m1",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token failure",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: badtok_0",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "token_fail.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    result = analyze_phases(recs[0], phase_mapping)
    assert result["status"] == "failed"
    click = _phase_by_name(result, "点击开始")
    assert click["status"] == "failed"
    assert click["confidence"] == "high"
    assert "new token failure" in click["detail"]


def test_analyze_phases_start_recognition_skipped_no_channel_lines(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    phase_mapping = _load_phase_mapping()
    # No AIBuds_AIChannel / AIBuds_Recognition / AIBuds_ASR lines so 开始识别 has no tagged lines.
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "no_channel.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    assert len(recs) == 1
    result = analyze_phases(recs[0], phase_mapping)
    start_rec = _phase_by_name(result, "开始识别")
    assert start_rec["status"] == "skipped"
    assert start_rec["confidence"] == "high"


def test_analyze_phases_click_start_low_confidence_token_only_noise(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    phase_mapping = _load_phase_mapping()
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:01.050 [Info] <AIBuds_ASR> Token create asr config model: m1",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> warmup unrelated message",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: lowcf_0",
        "2024-01-01 10:00:04.000 [Info] <AIBuds_Session> pool - idle wait",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "low_conf.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    result = analyze_phases(recs[0], phase_mapping)
    click = _phase_by_name(result, "点击开始")
    assert click["status"] == "success"
    assert click["confidence"] == "low"


def test_analyze_phases_evidence_max_three(tmp_path):
    boundaries = _load_streaming_channel_boundaries()
    phase_mapping = _load_phase_mapping()
    header = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:01.050 [Info] <AIBuds_ASR> Token create asr config model: m1",
    ]
    token_lines = [
        f"2024-01-01 10:00:{i:02d}.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: t{i}"
        for i in range(2, 12)
    ]
    tail = [
        "2024-01-01 10:00:20.000 [Info] <AIBuds_Session> create - success sessionId sid1",
        "2024-01-01 10:00:21.000 [Info] <AIBuds_AIChannel> scene: stream - connected",
        "2024-01-01 10:00:22.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:22 requestId: ev3_0",
        "2024-01-01 10:00:23.000 [Info] <AIBuds_AIChannel> pick_data - begin",
        "2024-01-01 10:00:24.000 [Info] <AIBuds_Recognition> transcribe - text packet",
        "2024-01-01 10:00:25.000 [Info] <AIBuds_AIChannel> request - finished",
        "2024-01-01 10:00:26.000 [Info] <AIBuds_ASR> ASRTask ended (Error: None)",
        "2024-01-01 10:00:30.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "ten_tokens.log"
    p.write_text("\n".join(header + token_lines + tail) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), boundaries)
    result = analyze_phases(recs[0], phase_mapping)
    click = _phase_by_name(result, "点击开始")
    assert len(click["evidence"]) <= 3


def _scenario_from_knowledge():
    return {
        "recording_boundaries": _load_streaming_channel_boundaries(),
        "phase_mapping": _load_phase_mapping(),
    }


def _multi_recording_log_lines():
    return [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:02 requestId: r1_0",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
        "2024-01-01 10:00:06.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:07.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:07 requestId: r2_1",
        "2024-01-01 10:00:08.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
        "2024-01-01 10:00:09.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:10 requestId: r3_2",
        "2024-01-01 10:00:11.000 [Info] <AIBuds_Record> Recording paused successfully, Device ID: dev001",
    ]


def test_analyze_pipeline_end_to_end_all_success(tmp_path):
    scenario = _scenario_from_knowledge()
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording, Device ID: dev001",
        "2024-01-01 10:00:01.100 [Info] <AIBuds_ASR> Token create asr config model: m1",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Token> scene: create - new token success tokenId: tok1",
        "2024-01-01 10:00:02.500 [Info] <AIBuds_Session> create - success sessionId sid1",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_AIChannel> scene: stream - connected",
        "2024-01-01 10:00:03.100 [Info] <AIBuds_AIChannel> scene: request - started at 10:00:03 requestId: allok_0",
        "2024-01-01 10:00:04.000 [Info] <AIBuds_AIChannel> pick_data - begin",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_Recognition> transcribe - text packet",
        "2024-01-01 10:00:06.000 [Info] <AIBuds_AIChannel> request - finished",
        "2024-01-01 10:00:06.500 [Info] <AIBuds_ASR> ASRTask ended (Error: None)",
        "2024-01-01 10:00:10.000 [Info] <AIBuds_Record> Recording stopped successfully, Device ID: dev001",
    ]
    p = tmp_path / "all_success.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = analyze_pipeline(str(p), scenario)
    assert out is not None
    assert len(out["recordings"]) == 1
    assert len(out["recordings"][0]["phases"]) == 5
    assert out["summary"]["total"] == 1
    assert out["summary"]["success"] == 1
    assert out["recordings"][0]["status"] == "success"


def test_analyze_pipeline_missing_boundaries_returns_none(tmp_path):
    p = tmp_path / "any.log"
    p.write_text("x\n", encoding="utf-8")
    assert analyze_pipeline(str(p), {"phases": []}) is None


def test_analyze_pipeline_multi_recordings_summary_total(tmp_path):
    scenario = _scenario_from_knowledge()
    p = tmp_path / "multi.log"
    p.write_text("\n".join(_multi_recording_log_lines()) + "\n", encoding="utf-8")

    out = analyze_pipeline(str(p), scenario)
    assert out is not None
    assert out["summary"]["total"] == 3


# ---------------------------------------------------------------------------
# Field grouping split mode tests
# ---------------------------------------------------------------------------

FIELD_GROUPING_BOUNDARIES = {
    "mode": "group_by_field",
    "field_pattern": r"fileId: (\d+)",
    "field_name": "fileId",
    "tags": ["AIBuds_Upload", "AIBuds_Transcribe", "AIBuds_MQTT", "AIBuds_DB", "AIBuds_FileUpdate"],
}


def test_split_field_grouping_multi_files(tmp_path):
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Upload> Start transcription task  fileId: 111",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_MQTT> Received status update  fileId: 222",
        "2024-01-01 10:00:03.000 [Info] <AIBuds_Upload> Upload progress  fileId: 111",
        "2024-01-01 10:00:04.000 [Info] <AIBuds_Transcribe> Transcription started  fileId: 333",
        "2024-01-01 10:00:05.000 [Info] <AIBuds_DB> DB update  fileId: 222",
        "2024-01-01 10:00:06.000 [Info] <AIBuds_FileUpdate> File updated  fileId: 333",
    ]
    p = tmp_path / "multi_field.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), FIELD_GROUPING_BOUNDARIES)
    assert len(recs) == 3
    assert recs[0]["record_id"] == "111"
    assert len(recs[0]["lines"]) == 2
    assert recs[1]["record_id"] == "222"
    assert len(recs[1]["lines"]) == 2
    assert recs[2]["record_id"] == "333"
    assert len(recs[2]["lines"]) == 2


def test_split_field_grouping_empty_no_field(tmp_path):
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Upload> Start transcription task no id here",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_MQTT> Received status update",
    ]
    p = tmp_path / "no_field.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), FIELD_GROUPING_BOUNDARIES)
    assert len(recs) == 0


def test_split_field_grouping_ignores_unrelated_tags(tmp_path):
    lines = [
        "2024-01-01 10:00:01.000 [Info] <AIBuds_Record> Start recording  fileId: 111",
        "2024-01-01 10:00:02.000 [Info] <AIBuds_Record> Stop recording  fileId: 222",
    ]
    p = tmp_path / "unrelated.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs = split_recordings(str(p), FIELD_GROUPING_BOUNDARIES)
    assert len(recs) == 0


# ---------------------------------------------------------------------------
# Status code enrichment tests
# ---------------------------------------------------------------------------

STATUS_CODES_CFG = {
    "transcribeStatus": {
        "source": "local_db",
        "mapping": {"0": "未知", "1": "转写中", "2": "转写成功", "3": "转写失败"},
    },
    "summaryStatus": {
        "source": "local_db",
        "mapping": {"0": "老数据", "1": "未知", "2": "总结中", "3": "总结成功", "4": "总结失败"},
    },
    "cloud_status": {
        "source": "mqtt",
        "mapping": {"0": "未知", "1": "初始状态", "2": "进行中", "9": "成功", "100": "失败"},
    },
}


def test_enrich_transcribe_status_failed():
    msg = "DB update transcribeStatus: 3 done"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "转写失败" in result


def test_enrich_summary_status_failed():
    msg = "DB update summaryStatus: 4 done"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "总结失败" in result


def test_enrich_cloud_transcription_status():
    msg = "MQTT response Transcription status ： 100 received"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert "失败" in result


def test_enrich_no_status_code_unchanged():
    msg = "Normal log without status codes"
    result = _enrich_status_codes(msg, STATUS_CODES_CFG)
    assert result == msg


def test_enrich_no_config_unchanged():
    msg = "DB update transcribeStatus: 3 done"
    result = _enrich_status_codes(msg, None)
    assert result == msg
