"""TAG 索引扫描器

扫描 SDK 代码库中所有日志调用，自动构建 TAG -> module -> file -> class -> line 的映射。

支持的日志调用模式：
  1. L.d("literal_tag", msg)         — 内联字符串 TAG
  2. L.d(TAG, msg)                   — TAG 常量引用
  3. L.d(LogTag.TAG_BLE_XXX, msg)    — LogTag 注册表常量引用

支持的 TAG 定义模式：
  Java:  private static final String TAG = "xxx";
  Java:  private static final String TAG = PREFIX + "suffix";
  Java:  private static final String TAG = LogTag.TAG_XXX;
  Java:  private static final String TAG = Xxx.class.getSimpleName();
  Kotlin: private val TAG = "xxx"
  Kotlin: const val TAG = "xxx"
"""

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

JAVA_TAG_DEF = re.compile(
    r'(?:private|public|protected)\s+'
    r'(?:static\s+)?(?:final\s+)?'
    r'String\s+(\w+)\s*=\s*(.+?)\s*;'
)

KT_TAG_DEF = re.compile(
    r'(?:private\s+)?(?:const\s+)?val\s+(\w+)\s*(?::\s*String)?\s*=\s*(.+)'
)

STRING_LITERAL = re.compile(r'^"([^"]*)"$')
STRING_CONCAT = re.compile(r'^(\w+)\s*\+\s*"([^"]*)"$')
CLASSNAME_PATTERN = re.compile(r'^(\w+)\.class\.getSimpleName\(\)$')
QUALIFIED_REF = re.compile(r'^(\w+)\.(\w+)$')

LOG_CALL = re.compile(
    r'L\.(i|d|w|e|v)\(\s*'
    r'(["\w][^,)]*?)'
    r'\s*[,)]'
)

JAVA_CLASS_PATTERN = re.compile(
    r'(?:public\s+|abstract\s+|final\s+)*'
    r'(?:class|interface|enum)\s+(\w+)'
)
KOTLIN_CLASS_PATTERN = re.compile(
    r'(?:class|object|interface|enum\s+class)\s+(\w+)'
)

COMPONENT_DIRS = {
    'api', 'baselib', 'bluetooth', 'cache', 'components',
    'device', 'device-core', 'hardware', 'matter', 'mqtt', 'network',
}

SCAN_EXTENSIONS = {'.java', '.kt'}

SKIP_DIRS = {
    'build', '.gradle', '.git', 'test', 'androidTest',
    'generated', 'kapt', 'TuyaSmart_AppShell', 'sdk-sample',
    'publicApk', '.idea', '.repo', 'tools',
}


def _should_skip(dir_name: str) -> bool:
    return dir_name in SKIP_DIRS or dir_name.startswith('.')


def _resolve_module(file_path: str, project_root: str) -> tuple[str, str]:
    rel = os.path.relpath(file_path, project_root)
    parts = Path(rel).parts
    if len(parts) >= 2 and parts[0] in COMPONENT_DIRS:
        module = parts[0]
        submodule = parts[1] if len(parts) > 2 else module
        return module, submodule
    return "other", Path(rel).parts[0] if parts else "unknown"


def _extract_class_name(file_path: str, content: str) -> str:
    pat = KOTLIN_CLASS_PATTERN if file_path.endswith('.kt') else JAVA_CLASS_PATTERN
    match = pat.search(content)
    return match.group(1) if match else Path(file_path).stem


def _scan_logtag_files(project_root: str) -> dict[str, str]:
    """Pre-scan all LogTag.java files, build constant_name -> resolved_value map."""
    registry: dict[str, str] = {}

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not _should_skip(d)]
        for fname in files:
            if fname == 'LogTag.java' or fname == 'LogTag.kt':
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except (OSError, IOError):
                    continue
                _parse_constant_file(content, registry)

    return registry


def _parse_constant_file(content: str, registry: dict[str, str]) -> None:
    """Parse a LogTag-style file: extract all constant definitions and resolve them."""
    raw: dict[str, str] = {}

    for line in content.split('\n'):
        line = line.strip()
        match = JAVA_TAG_DEF.search(line)
        if not match:
            match = KT_TAG_DEF.search(line)
        if not match:
            continue
        name, value_expr = match.group(1), match.group(2).strip().rstrip(';')
        raw[name] = value_expr

    for name, expr in raw.items():
        resolved = _resolve_expr(expr, raw, registry)
        if resolved:
            registry[name] = resolved


def _resolve_expr(
    expr: str,
    local_consts: dict[str, str],
    global_registry: dict[str, str],
) -> str | None:
    """Resolve a TAG value expression to a string."""
    expr = expr.strip()

    m = STRING_LITERAL.match(expr)
    if m:
        return m.group(1)

    m = STRING_CONCAT.match(expr)
    if m:
        prefix_name, suffix = m.group(1), m.group(2)
        prefix_val = (
            local_consts.get(prefix_name)
            or global_registry.get(prefix_name)
        )
        if prefix_val:
            prefix_resolved = _resolve_expr(prefix_val, local_consts, global_registry)
            if prefix_resolved:
                return prefix_resolved + suffix
        return None

    m = CLASSNAME_PATTERN.match(expr)
    if m:
        return m.group(1)

    m = QUALIFIED_REF.match(expr)
    if m:
        return global_registry.get(m.group(2))

    if re.match(r'^\w+$', expr):
        raw = local_consts.get(expr) or global_registry.get(expr)
        if raw and raw != expr:
            return _resolve_expr(raw, local_consts, global_registry)
        return global_registry.get(expr)

    return None


def _extract_file_tags(content: str, logtag_registry: dict[str, str]) -> dict[str, str]:
    """Extract TAG constant definitions from a single file.
    Returns variable_name -> resolved_tag_string."""
    raw: dict[str, str] = {}

    for line in content.split('\n'):
        line_stripped = line.strip()
        for pattern in (JAVA_TAG_DEF, KT_TAG_DEF):
            m = pattern.search(line_stripped)
            if m:
                name, value_expr = m.group(1), m.group(2).strip().rstrip(';')
                if name.startswith('TAG') or name == 'TAG':
                    raw[name] = value_expr
                break

    resolved: dict[str, str] = {}
    for name, expr in raw.items():
        val = _resolve_expr(expr, raw, logtag_registry)
        if val:
            resolved[name] = val

    return resolved


def scan_tags(project_root: str) -> dict:
    """Scan the project codebase and build the TAG index."""
    start_time = time.time()

    logtag_registry = _scan_logtag_files(project_root)

    tags: dict[str, dict] = defaultdict(lambda: {
        "module": "",
        "submodule": "",
        "files": [],
    })
    scanned_files = 0
    total_matches = 0

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not _should_skip(d)]

        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in SCAN_EXTENSIONS:
                continue

            file_path = os.path.join(root, fname)
            scanned_files += 1

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except (OSError, IOError):
                continue

            file_tags = _extract_file_tags(content, logtag_registry)

            tag_lines: dict[str, dict] = defaultdict(
                lambda: {"levels": set(), "lines": []}
            )
            has_match = False

            for line_num, line_content in enumerate(content.split('\n'), 1):
                for m in LOG_CALL.finditer(line_content):
                    level = m.group(1)
                    tag_expr = m.group(2).strip()

                    tag_name = None
                    str_m = STRING_LITERAL.match(tag_expr)
                    if str_m:
                        tag_name = str_m.group(1)
                    elif re.match(r'^\w+$', tag_expr):
                        tag_name = (
                            file_tags.get(tag_expr)
                            or logtag_registry.get(tag_expr)
                        )
                    else:
                        qm = QUALIFIED_REF.match(tag_expr)
                        if qm:
                            tag_name = logtag_registry.get(qm.group(2))

                    if not tag_name:
                        continue

                    tag_lines[tag_name]["levels"].add(level)
                    tag_lines[tag_name]["lines"].append(line_num)
                    total_matches += 1
                    has_match = True

            if not has_match:
                continue

            class_name = _extract_class_name(file_path, content)
            module, submodule = _resolve_module(file_path, project_root)
            rel_path = os.path.relpath(file_path, project_root)

            for tag_name, info in tag_lines.items():
                tag_entry = tags[tag_name]
                if not tag_entry["module"]:
                    tag_entry["module"] = module
                    tag_entry["submodule"] = submodule

                tag_entry["files"].append({
                    "path": rel_path,
                    "module": module,
                    "submodule": submodule,
                    "class": class_name,
                    "levels": sorted(info["levels"]),
                    "lines": info["lines"][:20],
                })

    elapsed = round(time.time() - start_time, 2)

    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_tags": len(tags),
            "total_matches": total_matches,
            "scanned_files": scanned_files,
            "elapsed_seconds": elapsed,
            "logtag_constants": len(logtag_registry),
        },
        "tags": dict(tags),
    }


def save_index(index: dict, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def load_index(index_path: str) -> dict | None:
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def lookup_tag(index: dict, keyword: str) -> list[dict]:
    """Fuzzy-match TAG names, return matching TAG entries."""
    keyword_lower = keyword.lower()
    results = []
    for tag_name, info in index.get("tags", {}).items():
        if keyword_lower in tag_name.lower():
            results.append({
                "tag": tag_name,
                "module": info["module"],
                "submodule": info["submodule"],
                "files": info["files"],
            })
    return results


def search_related_tags(index: dict, keyword: str) -> list[dict]:
    """Search related TAGs by keyword, return summary info."""
    keyword_lower = keyword.lower()
    results = []
    for tag_name, info in index.get("tags", {}).items():
        if keyword_lower in tag_name.lower():
            all_modules = set()
            for f in info["files"]:
                all_modules.add(f"{f.get('module', info['module'])}/{f.get('submodule', info['submodule'])}")

            results.append({
                "tag": tag_name,
                "module": info["module"],
                "submodule": info["submodule"],
                "file_count": len(info["files"]),
                "modules": sorted(all_modules),
                "levels": sorted(set(
                    level for f in info["files"] for level in f["levels"]
                )),
            })
    results.sort(key=lambda x: x["file_count"], reverse=True)
    return results[:50]


if __name__ == "__main__":
    import sys
    project_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    index = scan_tags(project_root)
    meta = index["meta"]
    print(f"Scanned {meta['scanned_files']} files in {meta['elapsed_seconds']}s")
    print(f"Found {meta['total_tags']} unique TAGs, {meta['total_matches']} total matches")
    print(f"LogTag constants resolved: {meta['logtag_constants']}")

    output = os.path.join(os.path.dirname(__file__), "data", "tag-index.json")
    save_index(index, output)
    print(f"Index saved to {output}")
