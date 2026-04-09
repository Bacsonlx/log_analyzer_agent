"""Pipeline log analysis: split log files into per-recording segments and classify product phases."""

from __future__ import annotations

import re
from pathlib import Path

from log_parser import _parse_line

_TIME_SHORT_PATTERN = re.compile(r"\d{2}:\d{2}:\d{2}\.\d+")
_TRAILING_SEQ_PATTERN = re.compile(r"_\d+$")


def _parse_all_lines(file_path: str) -> list[dict]:
    """Read file and parse each line with log_parser._parse_line; return parsed entries only."""
    entries: list[dict] = []
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            entry = _parse_line(line)
            if entry is not None:
                entries.append(entry)
    return entries


def _extract_time_short(time_str: str) -> str | None:
    """Extract HH:MM:SS.mmm (or .mmm variant) from a full timestamp string."""
    if not time_str:
        return None
    m = _TIME_SHORT_PATTERN.search(time_str.strip())
    return m.group(0) if m else None


def _strip_trailing_sequence(request_id: str) -> str:
    """Remove trailing _N (digits) from requestId, e.g. ej_req001_0 -> ej_req001."""
    if not request_id:
        return request_id
    return _TRAILING_SEQ_PATTERN.sub("", request_id)


def _extract_record_id(lines: list[dict], cfg: dict) -> str | None:
    """Find requestId in lines using record_id_extraction config (tag, pattern regex, transform)."""
    if not cfg:
        return None
    tag = cfg.get("tag") or ""
    pattern = cfg.get("pattern") or ""
    transform = cfg.get("transform") or ""
    try:
        rx = re.compile(pattern)
    except re.error:
        return None
    for entry in lines:
        if entry.get("tag") != tag:
            continue
        msg = entry.get("msg") or ""
        m = rx.search(msg)
        if not m:
            continue
        raw = m.group(1).strip()
        if transform == "strip_trailing_sequence":
            return _strip_trailing_sequence(raw)
        return raw
    return None


def _split_by_field_grouping(file_path: str, boundaries: dict) -> list[dict]:
    """Split log into groups keyed by a regex-extracted field value, filtered by allowed tags.

    Supports alias_field_pattern: lines without the primary field (e.g. fileId) but
    with an alias field (e.g. recordId) are linked to the primary group via a mapping
    built from lines that contain both fields.
    """
    entries = _parse_all_lines(file_path)
    if not entries:
        return []

    tags = boundaries.get("tags") or []
    field_pattern_str = boundaries.get("field_pattern") or ""
    try:
        field_rx = re.compile(field_pattern_str)
    except re.error:
        return []

    alias_cfg = boundaries.get("alias_field_pattern")
    alias_rx = None
    if alias_cfg:
        try:
            alias_rx = re.compile(alias_cfg)
        except re.error:
            pass

    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    alias_to_primary: dict[str, str] = {}
    deferred: list[dict] = []

    for entry in entries:
        tag = entry.get("tag") or ""
        tag_lower = tag.lower()
        if not any((t or "").lower() in tag_lower for t in tags):
            continue
        msg = entry.get("msg") or ""
        m = field_rx.search(msg)
        if m:
            field_value = m.group(1)
            if field_value not in groups:
                groups[field_value] = []
                order.append(field_value)
            groups[field_value].append(entry)
            if alias_rx:
                am = alias_rx.search(msg)
                if am:
                    alias_to_primary[am.group(1)] = field_value
        elif alias_rx:
            am = alias_rx.search(msg)
            if am:
                deferred.append((am.group(1), entry))

    for alias_val, entry in deferred:
        primary = alias_to_primary.get(alias_val)
        if primary and primary in groups:
            groups[primary].append(entry)

    for fv in order:
        groups[fv].sort(key=lambda e: e.get("time", ""))

    if not groups:
        return []

    name_cfg = boundaries.get("record_name_extraction")
    name_rx = None
    if name_cfg and name_cfg.get("pattern"):
        try:
            name_rx = re.compile(name_cfg["pattern"])
        except re.error:
            pass

    results: list[dict] = []
    for fv in order:
        lines = groups[fv]
        record_name = None
        if name_rx:
            for entry in lines:
                m = name_rx.search(entry.get("msg") or "")
                if m:
                    record_name = m.group(1).strip()
                    break
        results.append(
            {
                "record_id": record_name or fv,
                "start_time": _extract_time_short(lines[0].get("time", "")),
                "end_time": _extract_time_short(lines[-1].get("time", "")),
                "end_reason": None,
                "lines": lines,
            }
        )
    return results


def split_recordings(file_path: str, boundaries: dict) -> list[dict]:
    """
    Split a log file into recording segments using recording_boundaries config.

    Returns list of dicts: record_id, start_time, end_time, end_reason, lines.
    """
    path = Path(file_path)
    if not path.is_file():
        return []

    raw = path.read_text(encoding="utf-8", errors="ignore")
    if raw.strip() == "":
        return []

    if boundaries.get("mode") == "group_by_field":
        return _split_by_field_grouping(file_path, boundaries)

    entries = _parse_all_lines(file_path)
    if not entries:
        return []

    start_tag = boundaries.get("start_tag") or ""
    start_pattern = boundaries.get("start_pattern") or ""
    end_patterns = boundaries.get("end_patterns") or []
    record_id_cfg = boundaries.get("record_id_extraction") or {}

    def is_start(entry: dict) -> bool:
        return entry.get("tag") == start_tag and start_pattern in (entry.get("msg") or "")

    def match_end(entry: dict) -> str | None:
        msg = entry.get("msg") or ""
        et = entry.get("tag") or ""
        for ep in end_patterns:
            if et == ep.get("tag") and (ep.get("pattern") or "") in msg:
                return ep.get("reason") or "stopped"
        return None

    start_indices = [i for i, e in enumerate(entries) if is_start(e)]

    if not start_indices:
        seg_lines = entries
        return [
            {
                "record_id": _extract_record_id(seg_lines, record_id_cfg),
                "start_time": _extract_time_short(seg_lines[0].get("time", "")),
                "end_time": _extract_time_short(seg_lines[-1].get("time", "")),
                "end_reason": None,
                "lines": seg_lines,
            }
        ]

    segment_specs: list[dict] = []
    for k, si in enumerate(start_indices):
        next_si = start_indices[k + 1] if k + 1 < len(start_indices) else None
        limit = next_si if next_si is not None else len(entries)
        end_idx: int | None = None
        end_reason: str | None = None
        for j in range(si + 1, limit):
            end_reason = match_end(entries[j])
            if end_reason is not None:
                end_idx = j
                break
        if end_idx is not None:
            segment_specs.append(
                {
                    "end_idx": end_idx,
                    "end_reason": end_reason,
                    "interrupted": False,
                }
            )
        else:
            if next_si is not None:
                seg_end = next_si - 1
            else:
                seg_end = len(entries) - 1
            segment_specs.append(
                {
                    "end_idx": seg_end,
                    "end_reason": "interrupted",
                    "interrupted": True,
                }
            )

    results: list[dict] = []
    line_start = 0
    for spec in segment_specs:
        end_idx = spec["end_idx"]
        seg_lines = entries[line_start : end_idx + 1]
        line_start = end_idx + 1

        start_entry = None
        for e in seg_lines:
            if is_start(e):
                start_entry = e
                break
        if start_entry is None:
            start_entry = seg_lines[0]

        start_time = _extract_time_short(start_entry.get("time", ""))

        if spec["interrupted"]:
            end_time = None
            end_reason = "interrupted"
        else:
            end_entry = entries[spec["end_idx"]]
            end_time = _extract_time_short(end_entry.get("time", ""))
            end_reason = spec["end_reason"]

        results.append(
            {
                "record_id": _extract_record_id(seg_lines, record_id_cfg),
                "start_time": start_time,
                "end_time": end_time,
                "end_reason": end_reason,
                "lines": seg_lines,
            }
        )

    return results


_STATUS_CODE_PATTERN = re.compile(
    r'(transcribeStatus|summaryStatus|translateStatus|(?:Transcription|Summarize|Translation)\s+status)\s*[:：]\s*(\d+)'
)


def _enrich_status_codes(msg: str, status_codes: dict | None) -> str:
    """Append human-readable labels to status code values found in msg."""
    if not status_codes or not msg:
        return msg

    def _replacer(m: re.Match) -> str:
        field_name = m.group(1)
        code_value = m.group(2)
        original = m.group(0)

        mapping = None

        if field_name in status_codes:
            mapping = (status_codes[field_name] or {}).get("mapping")
        else:
            field_lower = field_name.lower().replace(" ", "")
            for key, cfg in status_codes.items():
                key_lower = key.lower().replace("_", "")
                if key_lower in field_lower or field_lower in key_lower:
                    mapping = (cfg or {}).get("mapping")
                    break

        if mapping is None:
            cloud_cfg = status_codes.get("cloud_status")
            if cloud_cfg:
                mapping = cloud_cfg.get("mapping")

        if mapping and code_value in mapping:
            return f"{original} → ({mapping[code_value]})"

        return original

    return _STATUS_CODE_PATTERN.sub(_replacer, msg)


def _phase_evidence_item(entry: dict, match_kind: str, status_codes: dict | None = None) -> dict:
    """Build one evidence dict: short time, tag, msg truncated to 120 chars, match kind."""
    raw_time = entry.get("time") or ""
    short = _extract_time_short(raw_time)
    msg = entry.get("msg") or ""
    msg = _enrich_status_codes(msg, status_codes)
    if len(msg) > 120:
        msg = msg[:120]
    return {
        "time": short,
        "tag": entry.get("tag") or "",
        "msg": msg,
        "match": match_kind,
    }


def _phase_detail_from_evidence(evidence: list[dict]) -> str:
    """Join evidence as `[time] msg` with '; ', max 200 characters."""
    parts: list[str] = []
    for ev in evidence:
        t = ev.get("time") or ""
        m = ev.get("msg") or ""
        if t:
            parts.append(f"[{t}] {m}")
        else:
            parts.append(f"[] {m}")
    s = "; ".join(parts)
    if len(s) > 200:
        s = s[:200]
    return s


def _compile_phase_pattern(pat: str) -> re.Pattern[str] | None:
    if not pat:
        return None
    try:
        return re.compile(pat)
    except re.error:
        return None


def analyze_phases(recording: dict, phase_mapping: list[dict], status_codes: dict | None = None) -> dict:
    """
    Classify each product phase from recording lines using tag filters and success/failure regexes.

    Returns record_id, overall status (failed / interrupted / success), and per-phase results.
    """
    lines = recording.get("lines") or []
    record_id = recording.get("record_id")
    end_reason = recording.get("end_reason")

    phases_out: list[dict] = []
    any_failed = False

    for phase_cfg in phase_mapping:
        name = phase_cfg.get("product_phase") or phase_cfg.get("name") or ""
        tags = phase_cfg.get("tags") or []
        succ_pat = phase_cfg.get("success_pattern") or ""
        fail_pat = phase_cfg.get("failure_pattern") or ""

        def tag_matches(entry: dict) -> bool:
            t = entry.get("tag") or ""
            tl = t.lower()
            return any((tg or "").lower() in tl for tg in tags)

        filtered = [e for e in lines if tag_matches(e)]

        succ_rx = _compile_phase_pattern(succ_pat)
        fail_rx = _compile_phase_pattern(fail_pat)

        failure_hits: list[dict] = []
        success_hits: list[dict] = []
        for e in filtered:
            msg = e.get("msg") or ""
            if fail_rx and fail_rx.search(msg):
                failure_hits.append(e)
            elif succ_rx and succ_rx.search(msg):
                success_hits.append(e)

        if failure_hits:
            status = "failed"
            confidence = "high"
            picked = failure_hits[:3]
            evidence = [_phase_evidence_item(e, "failure", status_codes) for e in picked]
        elif success_hits:
            status = "success"
            confidence = "high"
            picked = success_hits[:3]
            evidence = [_phase_evidence_item(e, "success", status_codes) for e in picked]
        elif filtered:
            status = "success"
            confidence = "low"
            picked = filtered[:3]
            evidence = [_phase_evidence_item(e, "none", status_codes) for e in picked]
        else:
            status = "skipped"
            confidence = "high"
            evidence = []

        detail = _phase_detail_from_evidence(evidence)
        ev_time = evidence[0]["time"] if evidence else None

        phases_out.append(
            {
                "name": name,
                "status": status,
                "confidence": confidence,
                "time": ev_time,
                "detail": detail,
                "evidence": evidence,
            }
        )
        if status == "failed":
            any_failed = True

    if any_failed:
        overall = "failed"
    elif end_reason == "interrupted":
        overall = "interrupted"
    else:
        overall = "success"

    return {
        "record_id": record_id,
        "status": overall,
        "phases": phases_out,
    }


def analyze_pipeline(file_path: str, scenario: dict) -> dict | None:
    """Entry point: split recordings and analyze phases.

    Returns None if scenario lacks recording_boundaries or phase_mapping.
    """
    boundaries = scenario.get("recording_boundaries")
    phase_mapping = scenario.get("phase_mapping")
    status_codes = scenario.get("status_codes")
    if boundaries is None or phase_mapping is None:
        return None

    recordings_raw = split_recordings(file_path, boundaries)
    if not recordings_raw:
        return {
            "recordings": [],
            "summary": {
                "total": 0,
                "success": 0,
                "failed": 0,
                "interrupted": 0,
                "low_confidence_phases": 0,
            },
        }

    analyzed: list[dict] = []
    success_n = 0
    failed_n = 0
    interrupted_n = 0
    low_confidence_phases = 0

    for rec in recordings_raw:
        out = analyze_phases(rec, phase_mapping, status_codes)
        if all(p.get("status") == "skipped" for p in out.get("phases", [])):
            continue
        analyzed.append(out)
        overall = out.get("status") or ""
        if overall == "success":
            success_n += 1
        elif overall == "failed":
            failed_n += 1
        elif overall == "interrupted":
            interrupted_n += 1
        for ph in out.get("phases") or []:
            if ph.get("confidence") == "low":
                low_confidence_phases += 1

    total = len(analyzed)
    return {
        "recordings": analyzed,
        "summary": {
            "total": total,
            "success": success_n,
            "failed": failed_n,
            "interrupted": interrupted_n,
            "low_confidence_phases": low_confidence_phases,
        },
    }
