"""AI Debug Pipeline — MCP 日志分析服务器

为 Cursor AI 提供日志分析工具链，实现 搜索→下载→分析→代码关联 的全链路追踪。

工具列表:
  工单集成:
  - fetch_ticket: 从 Socrates 工单平台提取诊断信息并自动搜索日志

  搜索与下载:
  - search_logs: 通过 ticketId / uid 搜索日志
  - download_log: 下载日志文件到本地

  分析:
  - build_tag_index / refresh_tag_index: 构建/刷新 TAG 索引
  - log_summary: 日志统计摘要
  - filter_logs: 按条件过滤日志
  - error_context: 提取 Error 前后上下文
  - tag_lookup: 查找 TAG 对应的代码位置
  - search_related_tags: 搜索相关 TAG

  AIVoice:
  - extract_aibuds_logs: 从原始日志提取 AIBuds 日志
  - refresh_aibuds_catalog: 扫描 iOS AIBuds ObjC 日志，刷新模块目录
  - refresh_aibuds_knowledge: 扫描 + 生成模块知识 + 校验，一键完成

  BLE 协议:
  - ble_command_lookup: 按指令码/关键词查询 BLE 协议定义
  - ble_protocol_overview: 查询帧格式/分包/加密等基础协议知识
"""

import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR_FOR_PATH = Path(__file__).parent
if str(SCRIPT_DIR_FOR_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR_FOR_PATH))

from fastmcp import FastMCP

from tag_scanner import scan_tags, save_index, load_index, lookup_tag, search_related_tags as _search_related
from log_parser import log_summary as _log_summary, filter_logs as _filter_logs, error_context as _error_context
from log_downloader import (
    search_by_ticket, search_by_uid, search_by_account,
    download_files, format_search_results,
    list_files, format_file_list, detect_account_type,
    select_feedback_entries, UserSelectionRequired,
)
try:
    from aibuds_extractor import extract_to_file as _extract_aibuds
except ImportError:
    _extract_aibuds = None
from aibuds_scanner import parse_mdc_tags, build_macro_to_tag, build_tag_descriptions, scan_objc_logs, generate_module_knowledge, generate_catalog_json, merge_module_knowledge, run_full_pipeline, _tag_to_filename
from ticket_fetcher import (
    parse_ticket_id, fetch_ticket_detail,
    extract_plain_text, extract_diagnosis_params,
    format_ticket_summary,
)

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
INDEX_PATH = DATA_DIR / "tag-index.json"
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", str(SCRIPT_DIR.parent.parent))

mcp = FastMCP("DeviceCore Log Analyzer")

_tag_index: dict | None = None
_tag_index_mtime: float = 0.0


def _get_index() -> dict:
    """Load TAG index with automatic staleness detection.

    Reloads from disk if the index file was updated externally (e.g. by
    build_tag_index or CLI). Rebuilds from scratch if the index is empty
    or missing.
    """
    global _tag_index, _tag_index_mtime

    if INDEX_PATH.exists():
        current_mtime = INDEX_PATH.stat().st_mtime
        if _tag_index is not None and current_mtime > _tag_index_mtime:
            _tag_index = load_index(str(INDEX_PATH))
            _tag_index_mtime = current_mtime

    if _tag_index is None:
        _tag_index = load_index(str(INDEX_PATH))
        if _tag_index is not None and INDEX_PATH.exists():
            _tag_index_mtime = INDEX_PATH.stat().st_mtime

    if _tag_index is None or _tag_index.get("meta", {}).get("total_tags", 0) == 0:
        _tag_index = scan_tags(PROJECT_ROOT)
        save_index(_tag_index, str(INDEX_PATH))
        _tag_index_mtime = INDEX_PATH.stat().st_mtime

    return _tag_index


@mcp.tool
def build_tag_index() -> str:
    """扫描 SDK 代码库中所有 L.i/d/w/e 日志调用，构建 TAG→模块→文件 的映射索引。
    首次使用或代码变更后调用。"""
    global _tag_index
    _tag_index = scan_tags(PROJECT_ROOT)
    save_index(_tag_index, str(INDEX_PATH))
    meta = _tag_index["meta"]
    return (
        f"TAG 索引构建完成\n"
        f"扫描文件: {meta['scanned_files']}\n"
        f"唯一 TAG: {meta['total_tags']}\n"
        f"总匹配数: {meta['total_matches']}\n"
        f"耗时: {meta['elapsed_seconds']}s\n"
        f"索引保存至: {INDEX_PATH}"
    )


@mcp.tool
def refresh_tag_index() -> str:
    """重新扫描代码库，刷新 TAG 索引。在代码变更后调用以更新索引。"""
    return build_tag_index()


AIBUDS_MDC_PATH = os.environ.get(
    "AIBUDS_MDC_PATH",
    str(Path(PROJECT_ROOT).parent / ".cursor" / "rules" / "aibuds.mdc"),
)
AIBUDS_SCAN_DIRS_ENV = os.environ.get("AIBUDS_SCAN_DIRS", "")


def _resolve_aibuds_scan_dirs(scan_dirs_csv: str = "") -> list[str]:
    """解析 AIBuds 扫描目录，优先使用参数，其次环境变量，最后默认路径。"""
    if scan_dirs_csv:
        return [d.strip() for d in scan_dirs_csv.split(",") if d.strip()]
    if AIBUDS_SCAN_DIRS_ENV:
        return [d.strip() for d in AIBUDS_SCAN_DIRS_ENV.split(",") if d.strip()]
    modules_root = Path(PROJECT_ROOT).parent / "Modules"
    return [
        str(modules_root / "ThingAudioRecordModule" / "ThingAudioRecordModule" / "Classes"),
        str(modules_root / "ThingAutomaticSpeechRecognitionModule" / "ThingAutomaticSpeechRecognitionModule" / "Classes"),
    ]


@mcp.tool
def refresh_aibuds_catalog(scan_dirs: str = "") -> str:
    """扫描 iOS AIBuds ObjC 日志调用，刷新模块目录 (data/aibuds-module-catalog.json)。

    Args:
        scan_dirs: 逗号分隔的扫描目录列表，留空使用默认路径
    """
    dirs = _resolve_aibuds_scan_dirs(scan_dirs)
    mdc = AIBUDS_MDC_PATH
    if not os.path.exists(mdc):
        return f"aibuds.mdc 不存在: {mdc}"

    tags = parse_mdc_tags(mdc)
    macro_map = build_macro_to_tag(tags)
    catalog = scan_objc_logs(dirs, macro_map)

    catalog_path = str(SCRIPT_DIR / "data" / "aibuds-module-catalog.json")
    os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    meta = catalog["_meta"]
    return (
        f"AIBuds 模块目录刷新完成\n"
        f"扫描文件: {meta['scanned_files']}\n"
        f"模块数: {meta['total_modules_found']}\n"
        f"日志调用: {meta['total_log_calls']}\n"
        f"耗时: {meta['elapsed_seconds']}s\n"
        f"目录保存至: {catalog_path}"
    )


@mcp.tool
def refresh_aibuds_knowledge(scan_dirs: str = "") -> str:
    """一键刷新 AIBuds 知识资产：扫描 ObjC 日志 → 生成模块知识 → 更新模块总览。

    Args:
        scan_dirs: 逗号分隔的扫描目录列表，留空使用默认路径
    """
    dirs = _resolve_aibuds_scan_dirs(scan_dirs)
    mdc = AIBUDS_MDC_PATH
    if not os.path.exists(mdc):
        return f"aibuds.mdc 不存在: {mdc}"

    catalog = run_full_pipeline(mdc, dirs)
    meta = catalog["_meta"]

    modules_dir = str(SCRIPT_DIR / "knowledge" / "modules")
    module_files = [f for f in os.listdir(modules_dir) if f.startswith("aibuds-") and f.endswith(".json")]

    return (
        f"AIBuds 知识资产刷新完成\n"
        f"扫描文件: {meta['scanned_files']}\n"
        f"模块数: {meta['total_modules_found']}\n"
        f"日志调用: {meta['total_log_calls']}\n"
        f"生成模块知识文件: {len(module_files)} 个\n"
        f"耗时: {meta['elapsed_seconds']}s\n"
        f"模块目录: {SCRIPT_DIR / 'data' / 'aibuds-module-catalog.json'}\n"
        f"知识文件: {modules_dir}/"
    )


@mcp.tool
def log_summary(file_path: str) -> str:
    """解析日志文件，输出统计摘要。
    包含：时间范围、总行数、级别分布、TAG 频率 Top 30、Error/Warning 日志列表。

    Args:
        file_path: 日志文件的绝对路径或相对路径
    """
    return _log_summary(file_path)


@mcp.tool
def filter_logs(
    file_path: str,
    tags: str = "",
    level: str = "",
    after: str = "",
    before: str = "",
    limit: int = 200
) -> str:
    """按条件过滤日志。TAG 支持模糊匹配（不区分大小写）。

    Args:
        file_path: 日志文件路径
        tags: TAG 关键词，逗号分隔（如 "ble,connect"），模糊匹配
        level: 日志级别过滤，逗号分隔（如 "Error,Warn"）
        after: 起始时间（如 "2026-03-09 15:00:00"）
        before: 截止时间
        limit: 最大返回条数，默认 200
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    level_list = [l.strip() for l in level.split(",") if l.strip()] or None
    return _filter_logs(
        file_path,
        tags=tag_list,
        level=level_list,
        after=after or None,
        before=before or None,
        limit=limit
    )


@mcp.tool
def error_context(file_path: str, seconds: int = 5, limit: int = 20) -> str:
    """提取每条 Error 日志前后 N 秒的上下文日志，还原错误现场。

    Args:
        file_path: 日志文件路径
        seconds: 前后时间窗口（秒），默认 5
        limit: 最多分析的 Error 数量，默认 20
    """
    return _error_context(file_path, seconds=seconds, limit=limit)


@mcp.tool
def tag_lookup(keyword: str) -> str:
    """在 TAG 索引中查找匹配的 TAG，返回其所属模块、文件路径、类名、行号。

    Args:
        keyword: TAG 名称或关键词（模糊匹配，不区分大小写）
    """
    index = _get_index()
    results = lookup_tag(index, keyword)
    if not results:
        return f"未找到匹配 '{keyword}' 的 TAG。可尝试 search_related_tags 用更宽泛的关键词搜索。"

    lines = [f"=== TAG 查找结果（关键词: {keyword}，匹配 {len(results)} 个）==="]
    for r in results[:20]:
        lines.append(f"\nTAG: {r['tag']}")
        lines.append(f"  模块: {r['module']}/{r['submodule']}")
        for f in r["files"][:5]:
            lines.append(f"  文件: {f['path']}")
            lines.append(f"  类名: {f['class']}")
            lines.append(f"  级别: {', '.join(f['levels'])}")
            lines.append(f"  行号: {f['lines'][:10]}")
    return "\n".join(lines)


@mcp.tool
def search_related_tags(keyword: str) -> str:
    """根据关键词搜索所有相关 TAG 及其模块归属。用于快速了解某个领域涉及哪些日志 TAG。

    Args:
        keyword: 搜索关键词（如 "ble"、"mqtt"、"connect"），模糊匹配
    """
    index = _get_index()
    results = _search_related(index, keyword)
    if not results:
        return f"未找到与 '{keyword}' 相关的 TAG。"

    lines = [f"=== 相关 TAG（关键词: {keyword}，找到 {len(results)} 个）==="]
    lines.append(f"{'TAG':<40s} {'模块':<20s} {'文件数':>5s} {'级别'}")
    lines.append("-" * 80)
    for r in results:
        module_str = f"{r['module']}/{r['submodule']}"
        levels_str = ",".join(r["levels"])
        lines.append(f"{r['tag']:<40s} {module_str:<20s} {r['file_count']:>5d} {levels_str}")
    return "\n".join(lines)


@mcp.tool
def error_code_lookup(keyword: str) -> str:
    """查询配网错误码的含义和解决方案。

    在错误码知识库中搜索匹配的错误码，返回失败原因和建议解决方案。
    支持模糊搜索，可输入错误码数字、关键词或错误描述。
    自动展示关联错误码链路（如 207 → 205228 → 205800）。

    Args:
        keyword: 错误码或关键词（如 "101"、"connect"、"密码"、"超时"）
    """
    ec_files = [
        KNOWLEDGE_DIR / "error-codes.json",
        KNOWLEDGE_DIR / "aivoice-error-codes.json",
    ]
    loaded_any = False

    all_errors: dict[str, dict] = {}
    for ec_path in ec_files:
        if not ec_path.exists():
            continue
        loaded_any = True
        with open(ec_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        source = data.get("name", ec_path.stem)
        for cat_id, cat_info in data.get("categories", {}).items():
            cat_name = cat_info.get("name", cat_id)
            for err in cat_info.get("errors", []):
                code = str(err.get("code", ""))
                all_errors[code] = {**err, "_category": f"{source} / {cat_name}"}

    if not loaded_any:
        return "错误码知识库不存在，请先创建 knowledge/error-codes.json"

    keyword_lower = keyword.lower()
    results = []
    matched_codes: set[str] = set()

    for code, err in all_errors.items():
        full_code = err.get("full_code", "")
        reason = err.get("reason", "")
        solution = err.get("solution", "")
        searchable = f"{code} {full_code} {reason} {solution}".lower()
        if keyword_lower in searchable:
            results.append({
                "category": err["_category"],
                "code": code,
                "reason": reason,
                "solution": solution,
                "related_codes": err.get("related_codes", []),
            })
            matched_codes.add(code)

    if not results:
        return f"未找到匹配 '{keyword}' 的错误码。"

    related_codes_to_show: list[str] = []
    for r in results:
        for rc in r.get("related_codes", []):
            if rc not in matched_codes and rc not in related_codes_to_show:
                related_codes_to_show.append(rc)

    lines = [f"=== 错误码查询（关键词: {keyword}，匹配 {len(results)} 个）==="]
    for r in results[:20]:
        lines.append("")
        lines.append(f"[{r['category']}] 错误码: {r['code']}")
        if r["reason"]:
            lines.append(f"  原因: {r['reason']}")
        if r["solution"]:
            lines.append(f"  方案: {r['solution']}")
        if r["related_codes"]:
            lines.append(f"  关联错误码: {', '.join(r['related_codes'])}")
    if len(results) > 20:
        lines.append(f"\n... 还有 {len(results) - 20} 个结果")

    if related_codes_to_show:
        lines.append("")
        lines.append("--- 关联错误码详情 ---")
        for rc in related_codes_to_show:
            err = all_errors.get(rc)
            if err:
                lines.append(f"  [{err['_category']}] 错误码: {rc}")
                if err.get("reason"):
                    lines.append(f"    原因: {err['reason']}")
                if err.get("solution"):
                    lines.append(f"    方案: {err['solution']}")

    return "\n".join(lines)


@mcp.tool
def fetch_ticket(ticket_url_or_id: str) -> str:
    """从 Socrates 工单平台提取诊断信息，并自动搜索关联的 App 日志。

    输入工单 URL 或工单 ID，自动提取问题描述、用户账号、服务区域、设备 PID 等信息，
    然后用提取到的账号自动搜索日志。返回工单摘要 + 日志搜索结果。

    Args:
        ticket_url_or_id: 工单 URL 或 ID
            (如 "https://socrates.tuya-inc.com:7799/my/detail?id=48712" 或 "48712")
    """
    try:
        problem_id = parse_ticket_id(ticket_url_or_id)
    except ValueError as e:
        return f"解析工单 ID 失败: {e}"

    try:
        detail = fetch_ticket_detail(problem_id)
    except Exception as e:
        return f"获取工单失败: {e}"

    content_json = detail.get("problemContent", "")
    plain_text = extract_plain_text(content_json)
    params = extract_diagnosis_params(plain_text)

    summary = format_ticket_summary(detail, plain_text, params)

    lines = [summary]

    account = params.get("account")
    region = params.get("region")

    if account:
        lines.append("")
        lines.append("=" * 60)
        lines.append("自动搜索日志")
        lines.append("=" * 60)
        try:
            search_region = region or "auto"
            acct_type = detect_account_type(account)

            if acct_type in ("email", "mobile", "account"):
                acct_region = "cn" if search_region == "auto" else search_region
                resp, used_region = search_by_account(account, region=acct_region)
            elif acct_type == "uid":
                explicit_region = None if search_region == "auto" else search_region
                resp, used_region = search_by_uid(account, region=explicit_region)
            else:
                ticket_region = "cn" if search_region == "auto" else search_region
                resp, used_region = search_by_ticket(account, region=ticket_region)

            lines.append(format_search_results(resp, used_region))
        except Exception as e:
            lines.append(f"日志搜索失败: {e}")
            lines.append("可手动调用 search_logs 尝试其他搜索条件。")
    else:
        lines.append("")
        lines.append("未从工单中提取到用户账号，无法自动搜索日志。")
        lines.append("请手动调用 search_logs 并提供 UID 或账号进行搜索。")

    lines.append("")
    lines.append("--- 建议下一步 ---")
    title = detail.get("title", "")
    if account:
        lines.append(
            f'1. 从上方日志搜索结果中选择记录，调用 download_log(feedback_id="<ID>") 下载日志'
        )
    lines.append(
        f'2. 下载后调用 quick_diagnosis(file_path="<路径>", problem="{title}") 一键诊断'
    )
    if params.get("pid"):
        lines.append(f'   问题关联设备 PID: {params["pid"]}')

    return "\n".join(lines)


@mcp.tool
def search_logs(
    query: str,
    query_type: str = "auto",
    region: str = "auto",
    app_index: int = 0,
) -> str:
    """在 App 日志平台搜索用户反馈日志。

    支持通过工单 ID、用户 UID、手机号、邮箱搜索。
    搜索结果包含反馈记录 ID，可传给 download_log 下载日志文件。

    Args:
        query: 搜索关键词（工单ID / UID / 手机号如86-xxx / 邮箱）
        query_type: 搜索类型 — auto / ticket / uid / account，默认 auto 自动识别
        region: 区域码 — auto / cn / eu / us / ue / in / we，默认 auto
        app_index: 邮箱/手机号多应用时指定应用序号(1起)，0 表示自动（单应用）或需用户选择
    """
    try:
        if query_type == "auto":
            query_type = detect_account_type(query)

        idx = app_index if app_index > 0 else None

        if query_type in ("email", "mobile", "account"):
            acct_region = "cn" if region == "auto" else region
            resp, used_region = search_by_account(
                query, region=acct_region, app_index=idx,
            )
        elif query_type == "uid":
            explicit_region = None if region == "auto" else region
            resp, used_region = search_by_uid(query, region=explicit_region)
        else:
            ticket_region = "cn" if region == "auto" else region
            resp, used_region = search_by_ticket(query, region=ticket_region)

        return format_search_results(resp, used_region)
    except UserSelectionRequired as e:
        return str(e)
    except Exception as e:
        return f"搜索失败: {e}"


def _classify_log_file(file_path: str) -> tuple[str, bool]:
    """Classify a log file by name pattern. Returns (label, is_recommended).

    Only .xlog files with 'main' in the name are the primary business logs to analyze.
    Example: p9rvnxmk3g3sq7qhcwm7_7.2.9_Android_main_20260311_144834_0-1773211717.xlog
    """
    name = os.path.basename(file_path).lower()
    if name.endswith(".xlog") and "_main_" in name:
        return "业务日志 / L 日志（主日志）", True
    if name.endswith(".xlog"):
        return "业务日志 / L 日志（非主日志）", False
    if "logcat" in name:
        return "系统日志（Android logcat）", False
    if "crash" in name or "tombstone" in name:
        return "崩溃日志", False
    if "anr" in name:
        return "ANR 日志", False
    return "其他日志", False


@mcp.tool
def download_log(
    feedback_id: str,
    region: str = "cn",
    file_filter: str = "xlog",
    timestamp_dir: bool = False,
) -> str:
    """下载指定反馈记录的日志文件到本地。

    默认仅下载 .xlog 业务日志文件（L 日志），忽略其他类型。
    下载完成后返回文件路径，可直接传给 log_summary / filter_logs 等工具分析。

    Args:
        feedback_id: 反馈记录 ID（从 search_logs 结果中获取）
        region: 区域码 — cn / eu / us / ue / in / we
        file_filter: 文件过滤 — "xlog"(仅业务日志，默认) / "all"(全部文件)
        timestamp_dir: 是否在 data 目录下新建时间戳子目录存放日志
    """
    try:
        save_dir = str(DATA_DIR)
        time_basename = None
        if timestamp_dir:
            time_basename = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_dir = str(DATA_DIR / time_basename)

        downloaded = download_files(
            feedback_id, region,
            save_dir=save_dir,
            file_filter=file_filter,
            time_basename=time_basename,
        )

        if not downloaded:
            return "下载完成但未找到日志文件。"

        lines = [f"日志下载成功，共 {len(downloaded)} 个文件："]
        recommended_file = None
        for fp in downloaded:
            size_mb = round(os.path.getsize(fp) / 1024 / 1024, 1)
            label, is_recommended = _classify_log_file(fp)
            rec_mark = " ★ 推荐优先分析" if is_recommended else ""
            lines.append(f"  {fp} ({size_mb}MB) — {label}{rec_mark}")
            if is_recommended and recommended_file is None:
                recommended_file = fp

        target = recommended_file or downloaded[0]
        lines.append("")
        lines.append("建议下一步操作：")
        lines.append(
            f'  log_summary(file_path="{target}")  → 日志摘要'
        )
        lines.append(
            f'  filter_logs(file_path="{target}", '
            f'level="Error,Warn")  → 过滤错误'
        )

        return "\n".join(lines)
    except Exception as e:
        return f"下载失败: {e}"


@mcp.tool
def extract_aibuds_logs(
    file_path: str,
    module: str = "",
    start_time: str = "",
    end_time: str = "",
) -> str:
    """从原始日志中提取 AIBuds 相关日志（[AIBuds_*] 标签行）。

    用于 AIVoice 日志分析前的预处理步骤，过滤出 AIBuds 业务日志。
    提取结果保存到 data/ 目录，返回文件路径可直接传给分析工具。

    Args:
        file_path: 原始日志文件路径
        module: 指定提取的模块，为 `AIBuds_` 后的名称，如 Record、ASR、Transfer、Token、Session、AIChannel、Recognition；为空则提取全部 AIBuds 日志
        start_time: 起始时间过滤（如 "2026-03-09 15:00:00"）
        end_time: 截止时间过滤
    """
    if _extract_aibuds is None:
        return "Error: aibuds_extractor 模块未安装，无法提取 AIBuds 日志。"

    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    try:
        output_dir = str(DATA_DIR)
        output_file, count = _extract_aibuds(
            file_path,
            output_dir=output_dir,
            module=module,
            start_time=start_time,
            end_time=end_time,
        )

        if count == 0:
            return (
                f"未从 {os.path.basename(file_path)} 中提取到 AIBuds 日志。\n"
                "请确认该文件包含 [AIBuds_*] 格式的日志行。"
            )

        size_kb = round(os.path.getsize(output_file) / 1024, 1)
        lines = [
            f"AIBuds 日志提取完成：",
            f"  源文件: {file_path}",
            f"  提取条数: {count}",
            f"  输出文件: {output_file} ({size_kb}KB)",
        ]
        if module:
            lines.append(f"  过滤模块: {module}")

        lines.append("")
        lines.append("建议下一步操作：")
        lines.append(
            f'  diagnose_scenario(file_path="{output_file}", '
            f'scenario="<问题描述>")  → 场景化诊断'
        )
        lines.append(
            f'  quick_diagnosis(file_path="{output_file}")  → 一键诊断'
        )

        return "\n".join(lines)
    except Exception as e:
        return f"AIBuds 日志提取失败: {e}"


KNOWLEDGE_DIR = SCRIPT_DIR / "knowledge"


def _save_report(content: str, problem: str = "") -> str:
    """Save diagnosis report as markdown. Returns the file path."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_problem = re.sub(r'[^\w\u4e00-\u9fff]', '_', problem.strip())[:30]
    if safe_problem:
        filename = f"{safe_problem}_{timestamp}.md"
    else:
        filename = f"diagnosis_{timestamp}.md"

    report_dir = DATA_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / filename
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return str(report_path)


_global_config: dict | None = None


def _load_global_config() -> dict:
    """Load the _global.json config (cached)."""
    global _global_config
    if _global_config is not None:
        return _global_config
    gpath = KNOWLEDGE_DIR / "_global.json"
    if gpath.exists():
        try:
            with open(gpath, 'r', encoding='utf-8') as f:
                _global_config = json.load(f)
        except (json.JSONDecodeError, OSError):
            _global_config = {}
    else:
        _global_config = {}
    return _global_config


def _load_global_noise() -> set[str]:
    """Return the set of globally blacklisted TAG substrings (lowered)."""
    cfg = _load_global_config()
    return {t.lower() for t in cfg.get("noise_tags", [])}


_knowledge_cache: list[dict] | None = None
_knowledge_name_index: dict[str, dict] | None = None
_knowledge_id_index: dict[str, dict] | None = None

_DEPRECATED_SCENARIO_IDS = {"aivoice-recording"}
_SCENARIO_ALIAS_TO_ID = {
    "录音问题": "aivoice-streaming-channel",
    "aivoice 录音问题": "aivoice-streaming-channel",
    "aivoice recording": "aivoice-streaming-channel",
    "aivoice-recording": "aivoice-streaming-channel",
}


def _load_all_knowledge() -> list[dict]:
    """Load all scenario knowledge files (cached)."""
    global _knowledge_cache, _knowledge_name_index, _knowledge_id_index
    if _knowledge_cache is not None:
        return _knowledge_cache
    results = []
    name_idx: dict[str, dict] = {}
    id_idx: dict[str, dict] = {}
    if not KNOWLEDGE_DIR.exists():
        _knowledge_cache = results
        _knowledge_name_index = name_idx
        _knowledge_id_index = id_idx
        return results
    for fp in KNOWLEDGE_DIR.glob("*.json"):
        if fp.name.startswith("_") or fp.name == "error-codes.json":
            continue
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
                results.append(data)
                name = data.get("name", "")
                if name:
                    name_idx[name.lower()] = data
                sid = data.get("id", "")
                if sid:
                    id_idx[sid.lower()] = data
        except (json.JSONDecodeError, OSError):
            continue
    _knowledge_cache = results
    _knowledge_name_index = name_idx
    _knowledge_id_index = id_idx
    return results


def _find_scenario(scenario: str) -> dict | None:
    """直接按名称查找场景，O(1) 命中则跳过全量模糊匹配。"""
    global _knowledge_name_index, _knowledge_id_index
    if _knowledge_name_index is None:
        _load_all_knowledge()
    key = scenario.lower().strip()
    alias_id = _SCENARIO_ALIAS_TO_ID.get(key)
    if alias_id and _knowledge_id_index:
        hit = _knowledge_id_index.get(alias_id.lower())
        if hit:
            return hit
    if _knowledge_name_index:
        hit = _knowledge_name_index.get(key)
        if hit:
            return hit
    return None


def _match_scenario(problem: str, knowledge: list[dict]) -> list[dict]:
    """Match problem description to knowledge scenarios by keyword overlap."""
    problem_lower = problem.lower()
    scored = []
    for k in knowledge:
        if k.get("id") in _DEPRECATED_SCENARIO_IDS:
            continue
        score = sum(1 for kw in k.get("keywords", []) if kw in problem_lower)
        if score > 0:
            scored.append((score, k))
    scored.sort(key=lambda x: -x[0])
    return [k for _, k in scored]


@mcp.tool
def diagnose_scenario(
    file_path: str,
    scenario: str,
    limit: int = 100,
) -> str:
    """场景化诊断：根据问题场景自动加载领域知识，按相关 TAG 过滤日志。

    输入问题描述或场景名称，自动从知识库匹配场景、过滤相关日志、提供排查路径指引。
    支持精确名称匹配（O(1)）和模糊关键词匹配。

    Args:
        file_path: 日志文件路径
        scenario: 场景名称或问题描述（如 "蓝牙连接失败"、"配网超时"、"设备离线"）
        limit: 最大返回日志条数，默认 100
    """
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    best = _find_scenario(scenario)
    if not best:
        knowledge = _load_all_knowledge()
        matched = _match_scenario(scenario, knowledge)
        if not matched:
            return (
                f"未找到与 '{scenario}' 匹配的诊断场景。\n"
                f"可用场景: {', '.join(k['name'] for k in knowledge)}\n"
                f"建议使用 quick_diagnosis 进行通用诊断。"
            )
        best = matched[0]

    all_tags = best.get("primary_tags", []) + best.get("secondary_tags", [])
    tags_lower = [t.lower() for t in all_tags]

    global_noise = _load_global_noise()
    scene_noise = {t.lower() for t in best.get("noise_tags", [])}
    all_noise = global_noise | scene_noise
    noise_set = frozenset(all_noise)
    tags_set = frozenset(tags_lower)
    error_filter = best.get("error_filter", "scene_only")
    collect_all_errors = error_filter == "all_errors"

    from log_parser import _parse_line

    results: list[dict] = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if len(results) >= limit:
                break
            entry = _parse_line(line)
            if entry is None:
                continue
            tag_lower = entry["tag"].lower()
            if any(n in tag_lower for n in noise_set):
                continue
            if any(t in tag_lower for t in tags_set):
                results.append(entry)
            elif collect_all_errors and entry["level"].lower() == "error":
                results.append(entry)

    out: list[str] = []
    out.append("=" * 60)
    out.append(f"场景化诊断: {best['name']}")
    out.append("=" * 60)

    normal_behaviors = best.get("normal_behaviors", [])
    if normal_behaviors:
        out.append("")
        out.append("--- ⚠ 正常行为提醒（不要误判为错误）---")
        for nb in normal_behaviors:
            out.append(f"  场景: {nb['pattern']}")
            out.append(f"  说明: {nb['description']}")
            out.append(f"  识别: {nb['how_to_identify']}")
            out.append("")

    known_issues = best.get("known_issues", [])
    matched_issues = []
    if known_issues and results:
        result_text = " ".join(
            f"{e['tag']} {e['msg']}" for e in results
            if e["level"].lower() == "error"
        ).lower()
        for issue in known_issues:
            issue_codes = [str(c) for c in issue.get("error_codes", [])]
            issue_msgs = [m.lower() for m in issue.get("error_messages", [])]
            if any(code in result_text for code in issue_codes) or \
               any(msg in result_text for msg in issue_msgs):
                matched_issues.append(issue)

    if matched_issues:
        out.append("")
        out.append("--- !! 匹配到已知问题 ---")
        for issue in matched_issues:
            out.append(f"  [{issue['title']}]")
            out.append(f"  错误码: {issue.get('error_codes', [])}")
            out.append(f"  根因: {issue['root_cause']}")
            out.append(f"  关键日志链路:")
            for step in issue.get("key_log_sequence", []):
                out.append(f"    - {step}")
            out.append(f"  诊断方法: {issue.get('diagnosis_method', '')}")
            out.append(f"  解决方案:")
            for s in issue.get("solution", []):
                out.append(f"    {s}")
            out.append("")

    out.append("--- 排查路径 ---")
    for step in best.get("check_order", []):
        out.append(f"  {step}")

    out.append("")
    out.append("--- 常见根因 ---")
    for cause in best.get("common_causes", []):
        out.append(f"  模式: {cause['pattern']}")
        out.append(f"  原因: {cause['cause']}")
        out.append("")

    out.append(f"--- 相关日志（共 {len(results)} 条）---")
    for entry in results:
        level_marker = " !!!" if entry["level"].lower() == "error" else ""
        out.append(
            f"  [{entry['time']}] [{entry['level']:5s}] "
            f"[{entry['tag']}] {entry['msg'][:200]}{level_marker}"
        )

    primary_tags = best.get("primary_tags")
    if primary_tags:
        try:
            index = _get_index()
        except Exception:
            index = None
        if index:
            out.append("")
            out.append("--- 关键 TAG 代码位置 ---")
            for tag_name in primary_tags[:8]:
                tag_results = lookup_tag(index, tag_name)
                for r in tag_results:
                    if r["tag"].lower() == tag_name.lower() and r["files"]:
                        f0 = r["files"][0]
                        out.append(
                            f"  {tag_name} -> {f0['path']}:{f0['lines'][0] if f0['lines'] else '?'}"
                        )
                        break

    retry_patterns = best.get("retry_patterns", [])
    if retry_patterns and results:
        retry_events = _track_retries(results, retry_patterns)
        if retry_events:
            out.append("")
            out.append("--- 重试追踪 ---")
            for rev in retry_events:
                out.append(f"  [{rev['trigger_time']}] 触发重试: {rev['trigger_msg'][:120]}")
                if rev["outcome"]:
                    oc = rev["outcome"]
                    out.append(f"    -> 结果: {oc['status']} [{oc['time']}] {oc['msg'][:150]}")
                else:
                    out.append(f"    -> 结果: 未检测到（可能超出时间窗口）")

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


def _parse_time_for_timeline(time_str: str):
    """Parse time string for timeline comparison."""
    from datetime import datetime
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return None


def _track_retries(entries: list[dict], retry_patterns: list[dict]) -> list[dict]:
    """Detect retry triggers and track their outcomes within a time window."""
    from datetime import timedelta
    results = []
    for rp in retry_patterns:
        trigger_re = re.compile(rp.get("trigger", "$."), re.IGNORECASE)
        outcome_tags = [t.lower() for t in rp.get("outcome_tags", [])]
        window_sec = rp.get("outcome_window_seconds", 30)
        success_re = re.compile(rp.get("success_pattern", "$."), re.IGNORECASE) if rp.get("success_pattern") else None
        failure_re = re.compile(rp.get("failure_pattern", "$."), re.IGNORECASE) if rp.get("failure_pattern") else None

        for i, entry in enumerate(entries):
            if not trigger_re.search(entry["msg"]):
                continue
            trigger_time = _parse_time_for_timeline(entry["time"])
            outcome = None

            for j in range(i + 1, len(entries)):
                candidate = entries[j]
                cand_time = _parse_time_for_timeline(candidate["time"])
                if trigger_time and cand_time:
                    if (cand_time - trigger_time) > timedelta(seconds=window_sec):
                        break

                tag_lower = candidate["tag"].lower()
                if not any(t in tag_lower for t in outcome_tags):
                    continue

                combined = f"{candidate['tag']} {candidate['msg']}"
                if failure_re and failure_re.search(combined):
                    outcome = {"status": "失败", "time": candidate["time"], "msg": candidate["msg"]}
                    break
                if success_re and success_re.search(combined):
                    outcome = {"status": "成功", "time": candidate["time"], "msg": candidate["msg"]}
                    break

            results.append({
                "trigger_time": entry["time"],
                "trigger_msg": entry["msg"],
                "outcome": outcome,
            })
    return results


@mcp.tool
def scenario_timeline(
    file_path: str,
    scenario: str,
) -> str:
    """场景时间线：按阶段聚合日志，每阶段标注成功/失败，失败阶段自动展开详细日志。

    需要场景知识库中定义了 phases 配置才能使用。适用于还原配网、OTA 等多阶段流程的完整时间线。

    Args:
        file_path: 日志文件路径
        scenario: 问题场景描述（如 "BLE 配网"、"OTA 升级"）
    """
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    knowledge = _load_all_knowledge()
    matched = _match_scenario(scenario, knowledge)

    if not matched:
        return (
            f"未找到与 '{scenario}' 匹配的场景。\n"
            f"可用场景: {', '.join(k['name'] for k in knowledge)}"
        )

    best = matched[0]
    phases = best.get("phases", [])
    if not phases:
        return (
            f"场景 '{best['name']}' 未配置 phases 时间线定义，"
            f"请使用 diagnose_scenario 进行诊断。"
        )

    global_noise = _load_global_noise()
    scene_noise = {t.lower() for t in best.get("noise_tags", [])}
    all_noise = global_noise | scene_noise

    all_phase_tags = set()
    for phase in phases:
        for tag in phase.get("tags", []):
            all_phase_tags.add(tag.lower())

    from log_parser import _parse_line

    relevant_entries: list[dict] = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            entry = _parse_line(line)
            if entry is None:
                continue
            tag_lower = entry["tag"].lower()
            if any(n in tag_lower for n in all_noise):
                continue
            if any(t in tag_lower for t in all_phase_tags) or entry["level"].lower() == "error":
                relevant_entries.append(entry)

    phase_results = []
    for phase in phases:
        phase_tags_lower = [t.lower() for t in phase.get("tags", [])]
        success_re = re.compile(phase.get("success_pattern", "$."), re.IGNORECASE) if phase.get("success_pattern") else None
        failure_re = re.compile(phase.get("failure_pattern", "$."), re.IGNORECASE) if phase.get("failure_pattern") else None

        phase_entries = []
        status = "unknown"
        first_time = None
        last_time = None

        for entry in relevant_entries:
            tag_lower = entry["tag"].lower()
            if not any(t in tag_lower for t in phase_tags_lower):
                continue
            phase_entries.append(entry)
            t = _parse_time_for_timeline(entry["time"])
            if t:
                if first_time is None or t < first_time:
                    first_time = t
                if last_time is None or t > last_time:
                    last_time = t

            combined = f"{entry['tag']} {entry['msg']}"
            if failure_re and failure_re.search(combined):
                status = "failed"
            elif success_re and success_re.search(combined) and status != "failed":
                status = "success"

        duration = ""
        if first_time and last_time:
            delta = (last_time - first_time).total_seconds()
            duration = f" ({delta:.1f}s)"

        phase_results.append({
            "name": phase["name"],
            "status": status,
            "entries": phase_entries,
            "first_time": first_time,
            "duration": duration,
        })

    retry_patterns = best.get("retry_patterns", [])
    retry_events = _track_retries(relevant_entries, retry_patterns)

    out: list[str] = []
    out.append("=" * 60)
    out.append(f"场景时间线: {best['name']}")
    out.append("=" * 60)
    out.append("")

    for pr in phase_results:
        if pr["status"] == "success":
            mark = "[OK]"
        elif pr["status"] == "failed":
            mark = "[FAIL]"
        else:
            mark = "[--]"

        time_str = pr["first_time"].strftime("%H:%M:%S") if pr["first_time"] else "??:??:??"
        out.append(f"  [{time_str}] {pr['name']:16s} {mark}{pr['duration']}")

        if pr["status"] == "failed":
            for entry in pr["entries"]:
                level_mark = " !!!" if entry["level"].lower() == "error" else ""
                out.append(
                    f"    [{entry['time']}] [{entry['level']:5s}] "
                    f"[{entry['tag']}] {entry['msg'][:180]}{level_mark}"
                )

    if retry_events:
        out.append("")
        out.append("--- 重试追踪 ---")
        for rev in retry_events:
            out.append(f"  [{rev['trigger_time']}] 触发重试: {rev['trigger_msg'][:120]}")
            if rev["outcome"]:
                oc = rev["outcome"]
                out.append(f"    -> 结果: {oc['status']} [{oc['time']}] {oc['msg'][:150]}")
            else:
                out.append(f"    -> 结果: 未检测到（可能超出时间窗口）")

    report = "\n".join(out)
    report_path = _save_report(report, f"timeline_{scenario}")
    out.append("")
    out.append(f"报告已保存: {report_path}")

    return "\n".join(out)


def _cluster_errors(
    all_entries: list[dict], error_indices: list[int]
) -> list[dict]:
    """Cluster errors by TAG+message-prefix. Returns deduplicated groups.

    Each group: {tag, msg_prefix, count, first_idx, last_idx, representative_idx}
    """
    from collections import OrderedDict

    groups: OrderedDict[str, dict] = OrderedDict()
    for idx in error_indices:
        err = all_entries[idx]
        msg_prefix = err["msg"][:80].strip()
        key = f"{err['tag']}||{msg_prefix}"
        if key not in groups:
            groups[key] = {
                "tag": err["tag"],
                "msg_prefix": msg_prefix,
                "count": 0,
                "first_idx": idx,
                "last_idx": idx,
                "representative_idx": idx,
            }
        g = groups[key]
        g["count"] += 1
        g["last_idx"] = idx
    return list(groups.values())


@mcp.tool
def quick_diagnosis(file_path: str, problem: str = "", max_errors: int = 8) -> str:
    """一键诊断：日志摘要 + 知识库匹配 + Error 聚类去重 + 代表性 Error 上下文 + TAG 代码关联。

    自动从知识库匹配场景，将已知问题、排查路径、常见根因注入报告。
    Error 按 TAG+消息前缀聚类去重，先输出聚类摘要表，再对每组代表性 Error 展开上下文。

    Args:
        file_path: 日志文件路径
        problem: 用户描述的问题（可选，如 "蓝牙连接失败"），用于关联知识库
        max_errors: 最多展开上下文的 Error 组数，默认 8
    """
    if not os.path.exists(file_path):
        return f"Error: 文件不存在: {file_path}"

    index = _get_index()
    from log_parser import _parse_line, _parse_time
    from datetime import timedelta
    from collections import Counter

    total_lines = 0
    parsed_lines = 0
    level_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    first_time = None
    last_time = None
    all_entries: list[dict] = []
    error_indices: list[int] = []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            total_lines += 1
            entry = _parse_line(line)
            if entry is None:
                continue
            parsed_lines += 1
            entry["_dt"] = _parse_time(entry["time"])

            level_counter[entry["level"]] += 1
            tag_counter[entry["tag"]] += 1

            t = entry["_dt"]
            if t:
                if first_time is None or t < first_time:
                    first_time = t
                if last_time is None or t > last_time:
                    last_time = t

            all_entries.append(entry)
            if entry["level"].lower() == "error":
                error_indices.append(len(all_entries) - 1)

    file_size_mb = round(os.path.getsize(file_path) / 1024 / 1024, 1)
    time_range = ""
    if first_time and last_time:
        time_range = (
            f"{first_time.strftime('%Y-%m-%d %H:%M:%S')} ~ "
            f"{last_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    out: list[str] = []
    out.append("=" * 60)
    out.append("一键诊断报告")
    out.append("=" * 60)

    out.append("")
    out.append(f"文件: {os.path.basename(file_path)} ({file_size_mb}MB)")
    out.append(f"时间: {time_range}")
    out.append(f"总行: {total_lines:,} | 有效: {parsed_lines:,}")

    error_count = level_counter.get("Error", 0)
    warn_count = level_counter.get("Warn", 0) + level_counter.get("Warning", 0)
    out.append(f"Error: {error_count} | Warn: {warn_count}")
    if problem:
        out.append(f"问题描述: {problem}")

    out.append("")
    out.append("--- TAG 频率 Top 15 ---")
    for i, (tag, count) in enumerate(tag_counter.most_common(15), 1):
        out.append(f"  {i:>2}. {tag:<40s} {count:>6,}")

    # ---- Knowledge Base Matching ----
    knowledge = _load_all_knowledge()
    kb_matched_scenarios: list[dict] = []

    if problem:
        kb_matched_scenarios = _match_scenario(problem, knowledge)

    if not kb_matched_scenarios and error_indices:
        error_text = " ".join(
            f"{all_entries[i]['tag']} {all_entries[i]['msg']}" for i in error_indices
        ).lower()
        tag_text = " ".join(tag_counter.keys()).lower()
        combined_text = f"{error_text} {tag_text}"
        for k in knowledge:
            score = sum(1 for kw in k.get("keywords", []) if kw in combined_text)
            tag_overlap = sum(
                1 for t in k.get("primary_tags", [])
                if t.lower() in tag_text
            )
            total = score + tag_overlap * 2
            if total > 0:
                kb_matched_scenarios.append(k)
                kb_matched_scenarios.sort(
                    key=lambda x: sum(1 for kw in x.get("keywords", []) if kw in combined_text)
                    + sum(2 for t in x.get("primary_tags", []) if t.lower() in tag_text),
                    reverse=True,
                )

    if kb_matched_scenarios:
        best_kb = kb_matched_scenarios[0]
        out.append("")
        out.append(f"--- 知识库匹配: {best_kb['name']} ---")

        known_issues = best_kb.get("known_issues", [])
        matched_issues = []
        if known_issues and error_indices:
            error_full_text = " ".join(
                f"{all_entries[i]['tag']} {all_entries[i]['msg']}" for i in error_indices
            ).lower()
            for issue in known_issues:
                codes = [str(c) for c in issue.get("error_codes", [])]
                msgs = [m.lower() for m in issue.get("error_messages", [])]
                if any(c in error_full_text for c in codes) or \
                   any(m in error_full_text for m in msgs):
                    matched_issues.append(issue)

        if matched_issues:
            out.append("")
            out.append("  !! 命中已知问题:")
            for issue in matched_issues:
                out.append(f"  [{issue['title']}]")
                out.append(f"    错误码: {issue.get('error_codes', [])}")
                out.append(f"    根因: {issue['root_cause']}")
                out.append(f"    关键日志链路:")
                for step in issue.get("key_log_sequence", []):
                    out.append(f"      - {step}")
                out.append(f"    诊断方法: {issue.get('diagnosis_method', '')}")
                out.append(f"    解决方案:")
                for s in issue.get("solution", []):
                    out.append(f"      {s}")
                out.append("")

        normal_behaviors = best_kb.get("normal_behaviors", [])
        if normal_behaviors:
            out.append("  正常行为提醒（不要误判为错误）:")
            for nb in normal_behaviors:
                out.append(f"    - {nb['pattern']}: {nb['description']}")
            out.append("")

        common_causes = best_kb.get("common_causes", [])
        if common_causes:
            out.append("  常见根因模式:")
            for cc in common_causes:
                out.append(f"    - {cc['pattern']} → {cc['cause']}")
            out.append("")

        check_order = best_kb.get("check_order", [])
        if check_order:
            out.append("  推荐排查路径:")
            for step in check_order:
                out.append(f"    {step}")
            out.append("")

    if error_indices:
        error_groups = _cluster_errors(all_entries, error_indices)

        out.append("")
        out.append(f"--- Error 聚类摘要（{len(error_indices)} 条 → {len(error_groups)} 组）---")
        out.append(f"  {'#':>3s}  {'次数':>4s}  {'TAG':<35s} {'消息摘要'}")
        out.append("  " + "-" * 90)
        for i, g in enumerate(error_groups, 1):
            out.append(
                f"  {i:>3d}  {g['count']:>4d}  "
                f"{g['tag']:<35s} {g['msg_prefix'][:50]}"
            )

        seen_tags: set[str] = set()
        delta = timedelta(seconds=3)

        out.append("")
        out.append(f"--- Error 详情（展开前 {min(max_errors, len(error_groups))} 组代表性 Error）---")

        for g in error_groups[:max_errors]:
            err_idx = g["representative_idx"]
            err = all_entries[err_idx]
            err_dt = err.get("_dt")
            if not err_dt:
                continue

            seen_tags.add(err["tag"])
            repeat_note = f"  (共 {g['count']} 次)" if g["count"] > 1 else ""

            out.append("")
            out.append(f"[ERROR] [{err['time']}] [{err['tag']}]{repeat_note}")
            out.append(f"  {err['msg'][:300]}")
            if g["count"] > 1:
                last_err = all_entries[g["last_idx"]]
                out.append(f"  末次出现: [{last_err['time']}]")

            start_idx = max(0, err_idx - 200)
            end_idx = min(len(all_entries), err_idx + 200)
            ctx_lines: list[str] = []
            for j in range(start_idx, end_idx):
                e = all_entries[j]
                e_dt = e.get("_dt")
                if not e_dt:
                    continue
                if e_dt < err_dt - delta or e_dt > err_dt + delta:
                    continue
                marker = ">>>" if j == err_idx else "   "
                ctx_lines.append(
                    f"  {marker} [{e['time']}] [{e['level']:5s}] "
                    f"[{e['tag']}] {e['msg'][:150]}"
                )

            if ctx_lines:
                out.append("  上下文 (前后3秒):")
                out.extend(ctx_lines)

        out.append("")
        out.append("--- TAG 代码关联 ---")
        for tag_name in sorted(seen_tags):
            results = lookup_tag(index, tag_name)
            if results:
                for r in results[:3]:
                    if r["tag"].lower() == tag_name.lower():
                        for finfo in r["files"][:2]:
                            out.append(
                                f"  {tag_name} -> "
                                f"{finfo.get('module', r['module'])}/"
                                f"{finfo.get('submodule', r['submodule'])} "
                                f"| {finfo['path']}:{finfo['lines'][0] if finfo['lines'] else '?'} "
                                f"({finfo['class']})"
                            )
                        break
                else:
                    out.append(
                        f"  {tag_name} -> {results[0]['module']}/"
                        f"{results[0]['submodule']} (模糊匹配)"
                    )
            else:
                out.append(f"  {tag_name} -> 未找到代码关联")

    elif warn_count > 0:
        out.append("")
        out.append("无 Error 日志，以下为 Warning 摘要（前 10 条）:")
        w_count = 0
        for entry in all_entries:
            if entry["level"].lower() in ("warn", "warning") and w_count < 10:
                out.append(
                    f"  [{entry['time']}] [{entry['tag']}] {entry['msg'][:200]}"
                )
                w_count += 1
    else:
        out.append("")
        out.append("未发现 Error 或 Warning 日志。")

    ble_tags_in_log = any(
        "thingble_" in t or "ble" in t.lower()
        for t in list(tag_counter.keys())[:30]
    )
    if ble_tags_in_log:
        out.append("")
        out.append("--- BLE 协议辅助 ---")
        out.append("检测到 BLE 通信日志，如需查询协议指令含义：")
        out.append('  ble_command_lookup(query="0x0000")   → 查询具体指令的字段格式')
        out.append('  ble_command_lookup(query="配对")     → 按关键词搜索相关指令')
        out.append('  ble_protocol_overview(topic="frame") → 帧格式/分包/加密基础知识')

    out.append("")
    out.append("=" * 60)
    out.append("本报告已包含以下信息（无需重复查询）：")
    included = ["Error 聚类摘要 + 上下文日志", "TAG → 源码文件:行号 映射"]
    if kb_matched_scenarios:
        included.insert(0, f"知识库匹配: {kb_matched_scenarios[0]['name']} (含已知问题/根因/解决方案/排查路径)")
        included.append("错误码含义（已在知识库中）")
    if ble_tags_in_log:
        included.append("BLE协议查询(ble_command_lookup)")
    out.append("  " + " | ".join(included))
    if kb_matched_scenarios:
        out.append("结论明确时可直接输出诊断报告，无需额外工具调用。")
        out.append("如需源码验证，请直接使用上方 TAG 代码关联 中的文件路径和行号。")
    out.append("=" * 60)

    report = "\n".join(out)
    report_path = _save_report(report, problem or os.path.basename(file_path))
    out.append("")
    out.append(f"报告已保存: {report_path}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# BLE Protocol Knowledge — 按需加载协议规范
# ---------------------------------------------------------------------------

PROTOCOL_DIR = KNOWLEDGE_DIR / "ble-protocol"
_proto_index: dict | None = None
_proto_lines: list[str] | None = None
_proto_section_map: dict[str, tuple[int, int]] | None = None


def _load_proto_index() -> dict:
    global _proto_index
    if _proto_index is not None:
        return _proto_index
    idx_path = PROTOCOL_DIR / "command-index.json"
    if not idx_path.exists():
        _proto_index = {}
        return _proto_index
    with open(idx_path, "r", encoding="utf-8") as f:
        _proto_index = json.load(f)
    return _proto_index


def _build_section_map() -> tuple[list[str], dict[str, tuple[int, int]]]:
    """Build a line-number map of {#cmd-0xNNNN} anchors for fast section extraction."""
    global _proto_lines, _proto_section_map
    if _proto_lines is not None and _proto_section_map is not None:
        return _proto_lines, _proto_section_map

    spec_path = PROTOCOL_DIR / "protocol-spec.md"
    if not spec_path.exists():
        _proto_lines = []
        _proto_section_map = {}
        return _proto_lines, _proto_section_map

    _proto_lines = spec_path.read_text(encoding="utf-8").splitlines()

    anchor_re = re.compile(r"\{#(cmd-0x[0-9A-Fa-f]{4})\}")
    heading_re = re.compile(r"^#{2,4}\s")
    anchors: list[tuple[int, str]] = []
    heading_lines: list[int] = []

    for i, line in enumerate(_proto_lines):
        m = anchor_re.search(line)
        if m:
            anchors.append((i, m.group(1)))
        if heading_re.match(line):
            heading_lines.append(i)

    _proto_section_map = {}
    for idx, (line_no, section_id) in enumerate(anchors):
        end_line = len(_proto_lines)
        for hl in heading_lines:
            if hl > line_no:
                end_line = hl
                break
        _proto_section_map[section_id] = (line_no, end_line)

    return _proto_lines, _proto_section_map


def _extract_section(section_id: str) -> str | None:
    lines, smap = _build_section_map()
    if section_id not in smap:
        return None
    start, end = smap[section_id]
    return "\n".join(lines[start:end]).strip()


def _extract_topic_section(topic: str) -> str | None:
    """Extract a non-command section by heading text match.

    For parent topics (e.g. "配对绑定流程"), includes all child sections.
    """
    lines, _ = _build_section_map()
    if not lines:
        return None

    topic_map = {
        "frame": "帧格式定义",
        "subpacket": "分包数据协议",
        "encryption": "设备通信流程",
        "broadcast": "蓝牙广播格式",
        "pairing": "设备通信流程",
        "interface": "蓝牙接口定义",
        "key": "设备通信流程",
    }
    target = topic_map.get(topic, topic)

    heading_re = re.compile(r"^(#{2,6})\s")
    start = None
    start_level = 0
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            if start is not None and len(m.group(1)) <= start_level:
                section = "\n".join(lines[start:i]).strip()
                if len(section) > 50:
                    return section
            if target in line and start is None:
                start = i
                start_level = len(m.group(1))

    if start is not None:
        end = min(start + 500, len(lines))
        return "\n".join(lines[start:end]).strip()
    return None


@mcp.tool
def ble_command_lookup(query: str) -> str:
    """查询 BLE 协议指令定义：字段格式、标志位含义、请求/响应规范。

    支持按指令码（"0x0001"）、名称关键词（"配对"、"OTA"、"dp下发"）搜索。
    返回该指令的完整协议描述，包含请求帧/响应帧字段定义。

    Args:
        query: 指令码（如 "0x0001"、"0001"）或关键词（如 "配对"、"OTA升级"、"设备信息"）
    """
    index = _load_proto_index()
    commands = index.get("commands", {})
    if not commands:
        return "BLE 协议知识库未初始化。请先运行 convert_protocol.py 生成协议文件。"

    normalized = query.strip().lower()
    if normalized.startswith("0x"):
        hex_part = normalized[2:]
        normalized = f"0x{hex_part.zfill(4)}"
    elif re.match(r"^[0-9a-f]{1,4}$", normalized):
        normalized = f"0x{normalized.zfill(4)}"

    matched: list[tuple[str, dict]] = []

    if normalized.startswith("0x"):
        code_upper = normalized.upper().replace("0X", "0x")
        if code_upper in commands:
            matched.append((code_upper, commands[code_upper]))
    else:
        for code, info in commands.items():
            name = info.get("name", "")
            category = info.get("category", "")
            code_ref = info.get("code_ref", "")
            searchable = f"{name} {category} {code_ref} {code}".lower()
            if normalized in searchable:
                matched.append((code, info))

    if not matched:
        return f"未找到匹配 '{query}' 的 BLE 协议指令。可用指令共 {len(commands)} 个。"

    if len(matched) > 5:
        out = [f"匹配 '{query}' 的指令共 {len(matched)} 个（仅显示摘要，请用具体指令码查询详情）："]
        out.append(f"{'指令码':<10s} {'方向':<8s} {'分类':<12s} {'名称'}")
        out.append("-" * 60)
        for code, info in matched[:15]:
            out.append(
                f"{code:<10s} {info.get('direction', ''):8s} "
                f"{info.get('category', ''):12s} {info['name']}"
            )
        if len(matched) > 15:
            out.append(f"... 还有 {len(matched) - 15} 个")
        return "\n".join(out)

    out: list[str] = []
    for code, info in matched:
        out.append(f"=== {code} {info['name']} ===")
        out.append(f"方向: {info.get('direction', '未知')}")
        out.append(f"分类: {info.get('category', '')}")
        if info.get("code_ref"):
            out.append(f"代码常量: {info['code_ref']}")

        section = _extract_section(info["section_id"])
        if section:
            out.append("")
            out.append(section)
        out.append("")

    return "\n".join(out)


@mcp.tool
def ble_protocol_overview(topic: str = "frame") -> str:
    """查询 BLE 协议基础知识：帧格式、分包规则、加密方式、广播格式等。

    用于了解 BLE 通信的基础协议结构，不涉及具体功能码指令。

    Args:
        topic: 查询主题 — "frame"(帧格式) / "subpacket"(分包协议) /
               "encryption"(加密方式) / "broadcast"(广播格式) /
               "pairing"(配对流程) / "key"(密钥生成) / "interface"(蓝牙接口)
    """
    content = _extract_topic_section(topic)
    if content:
        return content
    available = "frame, subpacket, encryption, broadcast, pairing, key, interface"
    return f"未找到主题 '{topic}'。可选: {available}"


if __name__ == "__main__":
    mcp.run()
