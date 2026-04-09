"""日志解析引擎

解析日志文件，自动识别三种格式，提供统计、过滤、上下文提取能力。

格式 1 (JSON Lines):
  {"type":"t","time":"2026-03-09 15:23:10.506","payload":{"level":"Info","tag":"TAG","msg":"..."}}

格式 2 (格式化 Logcat):
  2026-03-09 18:30:09.291 [Info] <Business_ThingNetworkMonitor> onCallStart: true 0 0

格式 3 (Android Studio Logcat):
  03-05 13:07:34.003 16654 16654 D Thing   : GwTransferModel try to startService
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

LOGCAT_FORMATTED_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+'
    r'(?:[+-]\d{4}\s+)?'
    r'\[(\w+)\]\s+'
    r'<([^>]+)>\s+'
    r'(.*)$'
)

_AIBUDS_TAG_IN_MSG = re.compile(r'^\[([A-Za-z_]+)\]\s*(.*)', re.DOTALL)

LOGCAT_ANDROID_PATTERN = re.compile(
    r'^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+'
    r'\d+\s+\d+\s+'
    r'([VDIWEF])\s+'
    r'(\S+)\s*:\s+'
    r'(.*)$'
)

LEVEL_SHORT_MAP = {
    'V': 'Verbose', 'D': 'Debug', 'I': 'Info',
    'W': 'Warn', 'E': 'Error', 'F': 'Fatal',
}


def _parse_time(time_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(time_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _parse_line(line: str) -> dict | None:
    """自动识别三种日志格式：JSON、格式化 Logcat、Android Studio Logcat。"""
    line = line.strip()
    if not line:
        return None

    if line.startswith('{'):
        try:
            obj = json.loads(line)
            payload = obj.get("payload", {})
            return {
                "time": obj.get("time", ""),
                "level": payload.get("level", "Unknown"),
                "tag": payload.get("tag", ""),
                "msg": payload.get("msg", ""),
            }
        except (json.JSONDecodeError, AttributeError):
            pass

    match = LOGCAT_FORMATTED_PATTERN.match(line)
    if match:
        tag = match.group(3)
        msg = match.group(4)
        inner = _AIBUDS_TAG_IN_MSG.match(msg)
        if inner:
            tag = inner.group(1)
            msg = inner.group(2).strip()
        return {
            "time": match.group(1).strip(),
            "level": match.group(2),
            "tag": tag,
            "msg": msg,
        }

    match = LOGCAT_ANDROID_PATTERN.match(line)
    if match:
        return {
            "time": match.group(1).strip(),
            "level": LEVEL_SHORT_MAP.get(match.group(2), match.group(2)),
            "tag": match.group(3),
            "msg": match.group(4),
        }

    return None


def log_summary(file_path: str) -> str:
    """生成日志文件的统计摘要。"""
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    total_lines = 0
    parsed_lines = 0
    level_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    first_time = None
    last_time = None
    errors: list[dict] = []
    warnings: list[dict] = []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            total_lines += 1
            entry = _parse_line(line)
            if entry is None:
                continue
            parsed_lines += 1

            level = entry["level"]
            level_counter[level] += 1
            tag_counter[entry["tag"]] += 1

            t = _parse_time(entry["time"])
            if t:
                if first_time is None or t < first_time:
                    first_time = t
                if last_time is None or t > last_time:
                    last_time = t

            if level.lower() == "error" and len(errors) < 50:
                errors.append(entry)
            elif level.lower() in ("warn", "warning") and len(warnings) < 100:
                warnings.append(entry)

    file_size_mb = round(os.path.getsize(file_path) / 1024 / 1024, 1)
    time_range = ""
    if first_time and last_time:
        time_range = f"{first_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {last_time.strftime('%Y-%m-%d %H:%M:%S')}"

    lines = [
        f"=== 日志分析摘要 ===",
        f"文件: {os.path.basename(file_path)} ({file_size_mb}MB)",
        f"时间范围: {time_range}",
        f"总行数: {total_lines:,}",
        f"有效日志: {parsed_lines:,} (解析失败: {total_lines - parsed_lines:,})",
        "",
        "级别分布:",
    ]

    for level in ["Debug", "Info", "Warn", "Warning", "Error"]:
        count = level_counter.get(level, 0)
        if count > 0:
            pct = round(count / parsed_lines * 100, 1) if parsed_lines else 0
            lines.append(f"  {level:10s} {count:>8,} ({pct}%)")

    other_levels = {k: v for k, v in level_counter.items()
                    if k not in ["Debug", "Info", "Warn", "Warning", "Error"]}
    for level, count in sorted(other_levels.items(), key=lambda x: -x[1]):
        pct = round(count / parsed_lines * 100, 1) if parsed_lines else 0
        lines.append(f"  {level:10s} {count:>8,} ({pct}%)")

    lines.append("")
    lines.append("TAG 频率 Top 30:")
    for i, (tag, count) in enumerate(tag_counter.most_common(30), 1):
        lines.append(f"  {i:>2}. {tag:40s} {count:>8,}")

    if errors:
        lines.append("")
        lines.append(f"Error 日志（共 {level_counter.get('Error', 0)} 条，显示前 {len(errors)} 条）:")
        for e in errors:
            lines.append(f"  [{e['time']}] [{e['tag']}] {e['msg'][:200]}")

    if warnings:
        lines.append("")
        lines.append(f"Warning 日志（共 {level_counter.get('Warn', 0) + level_counter.get('Warning', 0)} 条，显示前 {len(warnings)} 条）:")
        for w in warnings:
            lines.append(f"  [{w['time']}] [{w['tag']}] {w['msg'][:200]}")

    return "\n".join(lines)


def filter_logs(
    file_path: str,
    tags: list[str] | None = None,
    level: list[str] | None = None,
    after: str | None = None,
    before: str | None = None,
    limit: int = 200
) -> str:
    """按条件过滤日志。TAG 支持模糊匹配（不区分大小写）。"""
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None
    tags_lower = [t.lower() for t in tags] if tags else None
    level_lower = [l.lower() for l in level] if level else None

    results = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if len(results) >= limit:
                break

            entry = _parse_line(line)
            if entry is None:
                continue

            if tags_lower:
                tag_lower = entry["tag"].lower()
                if not any(t in tag_lower for t in tags_lower):
                    continue

            if level_lower and entry["level"].lower() not in level_lower:
                continue

            if after_dt or before_dt:
                t = _parse_time(entry["time"])
                if t:
                    if after_dt and t < after_dt:
                        continue
                    if before_dt and t > before_dt:
                        continue

            results.append(entry)

    lines = [f"=== 过滤结果（共 {len(results)} 条，limit={limit}）==="]
    if tags:
        lines.append(f"TAG 过滤: {', '.join(tags)}")
    if level:
        lines.append(f"级别过滤: {', '.join(level)}")
    if after:
        lines.append(f"起始时间: {after}")
    if before:
        lines.append(f"截止时间: {before}")
    lines.append("")

    for entry in results:
        lines.append(f"[{entry['time']}] [{entry['level']:5s}] [{entry['tag']}] {entry['msg'][:300]}")

    return "\n".join(lines)


def error_context(file_path: str, seconds: int = 5, limit: int = 20) -> str:
    """提取每条 Error 日志前后 N 秒的上下文日志。
    使用索引窗口避免 O(n*m) 的全量扫描。"""
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    all_entries: list[dict] = []
    error_indices: list[int] = []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            entry = _parse_line(line)
            if entry is None:
                continue
            entry["_dt"] = _parse_time(entry["time"])
            all_entries.append(entry)
            if entry["level"].lower() == "error":
                error_indices.append(len(all_entries) - 1)

    if not error_indices:
        return "未找到 Error 级别的日志。"

    delta = timedelta(seconds=seconds)
    lines = [f"=== Error 上下文（前后 {seconds} 秒，共 {len(error_indices)} 个 Error，显示前 {min(limit, len(error_indices))} 个）==="]

    for err_idx in error_indices[:limit]:
        err = all_entries[err_idx]
        err_dt = err.get("_dt")
        if not err_dt:
            continue

        lines.append("")
        lines.append(f"{'='*60}")
        lines.append(f"ERROR: [{err['time']}] [{err['tag']}] {err['msg'][:300]}")
        lines.append(f"{'='*60}")
        lines.append("上下文日志:")

        start_idx = max(0, err_idx - 500)
        end_idx = min(len(all_entries), err_idx + 500)
        for i in range(start_idx, end_idx):
            entry = all_entries[i]
            entry_dt = entry.get("_dt")
            if not entry_dt:
                continue
            if entry_dt < err_dt - delta:
                continue
            if entry_dt > err_dt + delta:
                break
            marker = " >>>" if i == err_idx else "    "
            lines.append(f"{marker} [{entry['time']}] [{entry['level']:5s}] [{entry['tag']}] {entry['msg'][:200]}")

    return "\n".join(lines)
