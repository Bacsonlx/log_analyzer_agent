"""AIBuds Objective-C 日志扫描器

扫描 iOS AIBuds 模块源码中的 AIBudsLogDebug/Info/Error 调用，
构建模块维度的日志目录与知识库草稿。

数据流:
  aibuds.mdc → 提取白名单 → 推导宏名映射
  ObjC .m/.mm → 正则匹配 → 提取日志条目
  → data/aibuds-module-catalog.json
  → knowledge/modules/*.json（自动生成部分）
"""

import json
import os
import re
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
KNOWLEDGE_DIR = SCRIPT_DIR / "knowledge"
MODULES_DIR = KNOWLEDGE_DIR / "modules"
CATALOG_PATH = DATA_DIR / "aibuds-module-catalog.json"

SCAN_EXTENSIONS = {".m", ".mm"}
SKIP_DIRS = {"build", ".git", "Pods", "DerivedData", "test", "Tests", "Example"}

# ---------------------------------------------------------------------------
# 白名单解析
# ---------------------------------------------------------------------------

MDC_TAG_LINE = re.compile(
    r"^-\s+`\[AIBuds_(\w+)\]`\s*-\s*(.+)$"
)


def parse_mdc_tags(mdc_path: str) -> list[dict]:
    """从 aibuds.mdc 提取核心模块标签列表。

    Returns list of {"tag": "AIBuds_Record", "suffix": "Record",
                      "macro": "ThingAIBudsLogModuleRecord",
                      "description": "录音管理模块"}
    """
    tags = []
    with open(mdc_path, "r", encoding="utf-8") as f:
        for line in f:
            m = MDC_TAG_LINE.match(line.strip())
            if m:
                suffix = m.group(1)
                desc = m.group(2).strip()
                tags.append({
                    "tag": f"AIBuds_{suffix}",
                    "suffix": suffix,
                    "macro": f"ThingAIBudsLogModule{suffix}",
                    "description": desc,
                })
    return tags


def build_macro_to_tag(tags: list[dict]) -> dict[str, str]:
    """macro name -> AIBuds_* tag name"""
    return {t["macro"]: t["tag"] for t in tags}


def build_tag_descriptions(tags: list[dict]) -> dict[str, str]:
    """AIBuds_* -> description"""
    return {t["tag"]: t["description"] for t in tags}

# ---------------------------------------------------------------------------
# ObjC 源码扫描
# ---------------------------------------------------------------------------

AIBUDS_LOG_CALL = re.compile(
    r"AIBudsLog(Debug|Info|Error)\s*\(\s*"
    r"(ThingAIBudsLogModule\w+)\s*,"
    r"\s*@\"((?:[^\"\\]|\\.)*)\""
)

OBJC_IMPLEMENTATION = re.compile(r"@implementation\s+(\w+)")

SCENE_PREFIX = re.compile(r"^scene:\s*(\S+)\s*-\s*(.*)$")


def _should_skip(dir_name: str) -> bool:
    return dir_name in SKIP_DIRS or dir_name.startswith(".")


def _extract_class_name(content: str, filename: str) -> str:
    m = OBJC_IMPLEMENTATION.search(content)
    return m.group(1) if m else Path(filename).stem


def _classify_template(template: str, level: str) -> str:
    """对日志模板做保守候选分类。"""
    t_lower = template.lower()

    if level.lower() == "error":
        return "failure_candidates"

    failure_kw = {"fail", "failed", "error", "exception", "invalid",
                  "empty", "timeout", "abort", "missing", "mismatch"}
    for kw in failure_kw:
        if kw in t_lower:
            return "failure_candidates"

    success_kw = {"success", "ready", "connected", "completed",
                  "started", "resumed", "begin", "succeeded"}
    for kw in success_kw:
        if kw in t_lower:
            return "success_candidates"

    lifecycle_kw = {"start", "stop", "end", "create", "destroy",
                    "dealloc", "pause", "resume", "init", "release",
                    "remove", "close", "open"}
    for kw in lifecycle_kw:
        if kw in t_lower:
            return "lifecycle_candidates"

    return "noise_candidates"


def _extract_scene(template: str) -> str | None:
    m = SCENE_PREFIX.match(template.strip())
    return m.group(1) if m else None


def scan_objc_logs(
    scan_dirs: list[str],
    macro_to_tag: dict[str, str],
) -> dict:
    """扫描指定目录下 .m/.mm 文件中的 AIBudsLog* 调用。

    Returns raw catalog dict ready for JSON serialization.
    """
    start_time = time.time()

    modules: dict[str, dict] = defaultdict(lambda: {
        "files": defaultdict(lambda: {"class": "", "log_count": 0}),
        "log_count": 0,
        "by_level": defaultdict(int),
        "scenes": set(),
        "templates": [],
    })

    scanned_files = 0
    total_log_calls = 0
    repo_names = set()

    for scan_dir in scan_dirs:
        repo_name = Path(scan_dir).parts[-3] if len(Path(scan_dir).parts) >= 3 else Path(scan_dir).name
        repo_names.add(repo_name)

        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if not _should_skip(d)]

            for fname in files:
                ext = os.path.splitext(fname)[1]
                if ext not in SCAN_EXTENSIONS:
                    continue

                file_path = os.path.join(root, fname)
                scanned_files += 1

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except (OSError, IOError):
                    continue

                class_name = _extract_class_name(content, fname)
                rel_path = os.path.relpath(file_path, scan_dir)

                seen_templates: set[tuple] = set()

                for line_num, line_content in enumerate(content.split("\n"), 1):
                    if "AIBudsLog" not in line_content:
                        continue
                    if line_content.lstrip().startswith("//"):
                        continue

                    for m in AIBUDS_LOG_CALL.finditer(line_content):
                        level = m.group(1).lower()
                        macro_name = m.group(2)
                        template = m.group(3)

                        tag = macro_to_tag.get(macro_name)
                        if not tag:
                            continue

                        total_log_calls += 1
                        mod = modules[tag]
                        mod["log_count"] += 1
                        mod["by_level"][level] += 1

                        file_entry = mod["files"][rel_path]
                        file_entry["class"] = class_name
                        file_entry["log_count"] += 1

                        scene = _extract_scene(template)
                        if scene:
                            mod["scenes"].add(scene)

                        dedup_key = (tag, level, template)
                        if dedup_key not in seen_templates:
                            seen_templates.add(dedup_key)
                            candidate_type = _classify_template(template, level)
                            mod["templates"].append({
                                "level": level,
                                "scene": scene,
                                "template": template,
                                "file": fname,
                                "line": line_num,
                                "candidate_type": candidate_type,
                            })

    elapsed = round(time.time() - start_time, 2)

    result_modules = {}
    for tag, mod in sorted(modules.items()):
        file_list = []
        for path, info in sorted(mod["files"].items()):
            file_list.append({
                "path": path,
                "class": info["class"],
                "log_count": info["log_count"],
            })
        result_modules[tag] = {
            "files": file_list,
            "log_count": mod["log_count"],
            "by_level": dict(mod["by_level"]),
            "scenes": sorted(mod["scenes"]),
            "templates": mod["templates"],
        }

    return {
        "_meta": {
            "updated": date.today().isoformat(),
            "scanned_repos": sorted(repo_names),
            "scanned_files": scanned_files,
            "total_modules_found": len(result_modules),
            "total_log_calls": total_log_calls,
            "elapsed_seconds": elapsed,
        },
        "modules": result_modules,
    }


# ---------------------------------------------------------------------------
# 知识库生成
# ---------------------------------------------------------------------------

def generate_module_knowledge(
    catalog: dict,
    tag_descriptions: dict[str, str],
    all_tags: list[dict],
) -> dict[str, dict]:
    """从 catalog 生成 knowledge/modules/*.json 的内容。

    Returns tag -> knowledge dict
    """
    knowledge_files = {}

    for tag, mod in catalog["modules"].items():
        success = []
        failure = []
        lifecycle = []
        noise = []

        seen = set()
        for t in mod["templates"]:
            tmpl = t["template"]
            if tmpl in seen:
                continue
            seen.add(tmpl)

            entry = {
                "pattern": _template_to_pattern(tmpl),
                "level": t["level"],
                "description": "",
                "source": "auto",
            }
            if t["candidate_type"] == "success_candidates":
                success.append(entry)
            elif t["candidate_type"] == "failure_candidates":
                entry["cause"] = ""
                failure.append(entry)
            elif t["candidate_type"] == "lifecycle_candidates":
                lifecycle.append(entry)
            else:
                noise.append(tmpl)

        source_files = sorted(set(
            os.path.basename(f["path"]) for f in mod["files"]
        ))

        knowledge_files[tag] = {
            "_meta": {
                "updated": date.today().isoformat(),
                "source_repos": catalog["_meta"]["scanned_repos"],
                "auto_generated": True,
                "human_reviewed": False,
            },
            "module": tag,
            "description": tag_descriptions.get(tag, ""),
            "source_files": source_files,
            "related_modules": [],
            "scenes": mod["scenes"],
            "log_stats": {
                "total": mod["log_count"],
                "by_level": mod["by_level"],
            },
            "success_signals": success,
            "failure_signals": failure,
            "lifecycle_signals": lifecycle,
            "noise_patterns": _dedupe_noise(noise),
        }

    return knowledge_files


def _template_to_pattern(template: str) -> str:
    """将日志模板转为可用于日志匹配的简化 pattern。

    把 ObjC 格式占位符替换为 .* 通配。
    """
    p = template
    p = re.sub(r"%[@dDiuUxXoOfeEgGcCsSp]", ".*", p)
    p = re.sub(r"%l[dux]", ".*", p)
    p = re.sub(r"%lu", ".*", p)
    p = re.sub(r"%\.\d+f", ".*", p)
    p = re.sub(r"%\d*[dux]", ".*", p)
    p = re.sub(r"\\n", " ", p)
    p = p.strip()
    return p


def _dedupe_noise(patterns: list[str]) -> list[str]:
    seen = set()
    result = []
    for p in patterns:
        short = p[:60]
        if short not in seen:
            seen.add(short)
            result.append(short)
    return result[:20]


def generate_catalog_json(catalog: dict) -> dict:
    """生成 knowledge/modules/_catalog.json"""
    modules_summary = {}
    for tag, mod in catalog["modules"].items():
        modules_summary[tag] = {
            "file_count": len(mod["files"]),
            "log_count": mod["log_count"],
            "levels": sorted(mod["by_level"].keys()),
            "scenes": mod["scenes"],
            "knowledge_file": f"modules/aibuds-{_tag_to_filename(tag)}.json",
        }
    return {
        "_meta": {
            "updated": date.today().isoformat(),
            "total_modules": len(modules_summary),
            "total_log_calls": catalog["_meta"]["total_log_calls"],
        },
        "modules": modules_summary,
    }


def _tag_to_filename(tag: str) -> str:
    """AIBuds_Record -> record, AIBuds_AIChannel -> aichannel"""
    suffix = tag.replace("AIBuds_", "")
    return suffix.lower()


# ---------------------------------------------------------------------------
# 增量合并
# ---------------------------------------------------------------------------

def merge_module_knowledge(
    existing_path: str,
    new_data: dict,
) -> dict:
    """合并已有模块知识文件与新扫描结果。

    保留 source: human 条目，覆盖 source: auto 条目。
    """
    if not os.path.exists(existing_path):
        return new_data

    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError):
        return new_data

    for signal_key in ("success_signals", "failure_signals", "lifecycle_signals"):
        human_entries = [
            e for e in existing.get(signal_key, [])
            if e.get("source") == "human"
        ]
        auto_entries = new_data.get(signal_key, [])
        new_data[signal_key] = auto_entries + human_entries

    if existing.get("related_modules"):
        new_data["related_modules"] = existing["related_modules"]

    if existing.get("_meta", {}).get("human_reviewed"):
        new_data["_meta"]["human_reviewed"] = True

    return new_data


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_full_pipeline(
    mdc_path: str,
    scan_dirs: list[str],
    output_catalog: str | None = None,
    output_modules_dir: str | None = None,
) -> dict:
    """执行完整扫描 → 生成 → 写入流程。

    Returns catalog dict.
    """
    catalog_path = output_catalog or str(CATALOG_PATH)
    modules_dir = output_modules_dir or str(MODULES_DIR)

    tags = parse_mdc_tags(mdc_path)
    if not tags:
        raise ValueError(f"No tags found in {mdc_path}")

    macro_to_tag = build_macro_to_tag(tags)
    tag_descriptions = build_tag_descriptions(tags)

    catalog = scan_objc_logs(scan_dirs, macro_to_tag)

    os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    os.makedirs(modules_dir, exist_ok=True)

    knowledge_files = generate_module_knowledge(catalog, tag_descriptions, tags)
    for tag, data in knowledge_files.items():
        fname = f"aibuds-{_tag_to_filename(tag)}.json"
        fpath = os.path.join(modules_dir, fname)
        merged = merge_module_knowledge(fpath, data)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

    catalog_json = generate_catalog_json(catalog)
    catalog_json_path = os.path.join(modules_dir, "_catalog.json")
    with open(catalog_json_path, "w", encoding="utf-8") as f:
        json.dump(catalog_json, f, ensure_ascii=False, indent=2)

    return catalog


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python aibuds_scanner.py <aibuds.mdc> <scan_dir1> [scan_dir2 ...]")
        print("Example:")
        print("  python aibuds_scanner.py /path/to/aibuds.mdc /path/to/ThingAudioRecordModule/Classes /path/to/ASRModule/Classes")
        sys.exit(1)

    mdc = sys.argv[1]
    dirs = sys.argv[2:]

    catalog = run_full_pipeline(mdc, dirs)
    meta = catalog["_meta"]
    print(f"Scan complete:")
    print(f"  Scanned files: {meta['scanned_files']}")
    print(f"  Modules found: {meta['total_modules_found']}")
    print(f"  Log calls:     {meta['total_log_calls']}")
    print(f"  Elapsed:       {meta['elapsed_seconds']}s")
    print(f"  Catalog:       {CATALOG_PATH}")
    print(f"  Modules dir:   {MODULES_DIR}")
