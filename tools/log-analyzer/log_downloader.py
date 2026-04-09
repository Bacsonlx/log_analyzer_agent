"""App 日志搜索与下载

从内部 App 日志平台搜索和下载用户反馈日志。
支持通过 ticketId、uid、用户账号（手机号/邮箱）搜索日志记录。
多应用账号支持交互选择或通过 app_index 指定。

认证方式（按优先级）：
1. 环境变量 SSO_USER_TOKEN
2. 从 Chrome 浏览器自动读取 Cookie（需安装 browsercookie）
"""

import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

FEEDBACK_TIME_CLUSTER_SEC = 300


class UserSelectionRequired(Exception):
    """非交互环境下需用户指定 app_index（多应用时）。"""

REGION_URL_MAP = {
    "cn": "cn",
    "eu": "eu",
    "us": "us",
    "ue": "ueaz",
    "in": "ind",
    "we": "weaz",
}

UID_PREFIX_TO_URL_REGION = {
    "ay": "cn",
    "eu": "eu",
    "az": "us",
    "ue": "ueaz",
    "in": "ind",
    "we": "weaz",
}

AREA_NAME_TO_URL_REGION = {
    "中国": "cn",
    "欧洲": "eu",
    "美国西": "us",
    "美国东": "ueaz",
    "印度": "ind",
    "西欧": "weaz",
}

_BASE_URL = (
    "https://app-log-{region}.tuya-inc.com:7799"
    "/client-log-backend/app-log/api/v1"
)

_BACKENDNG_URL = "https://backendng-{region}.tuya-inc.com:7799"

_EMAIL_RE = re.compile(r'^[\w.\-+]+@[\w.\-]+\.\w+$')
_PHONE_RE = re.compile(r'^\+?\d{1,4}[-\s]?\d{4,}$')

_session: requests.Session | None = None
_sso_token: str | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _get_sso_token() -> str:
    """获取 SSO Token。优先环境变量，其次 Chrome 浏览器 Cookie。"""
    global _sso_token
    if _sso_token:
        return _sso_token

    token = os.environ.get("SSO_USER_TOKEN", "")
    if token:
        _sso_token = token
        return token

    try:
        import browsercookie
        jar = browsercookie.chrome()
        for cookie in jar:
            if (cookie.name == "SSO_USER_TOKEN"
                    and cookie.domain.endswith(".tuya-inc.com")):
                _sso_token = cookie.value
                return _sso_token
    except Exception:
        pass

    raise RuntimeError(
        "未找到 SSO_USER_TOKEN。请执行以下操作之一：\n"
        "1. 在 Chrome 中打开 https://app-log-cn.tuya-inc.com:7799/ 并登录\n"
        "2. 设置环境变量：export SSO_USER_TOKEN=<your_token>\n"
        "   或在 .cursor/mcp.json 的 env 中添加 SSO_USER_TOKEN"
    )


def reset_token() -> None:
    """清除缓存的 Token，下次请求时重新获取。"""
    global _sso_token
    _sso_token = None


def _api_get(url: str) -> dict:
    """发起认证的 GET 请求。"""
    session = _get_session()
    headers = {
        "cookie": f"SSO_USER_TOKEN={_get_sso_token()}",
        "accept": "application/json",
    }
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    if resp.text.startswith("<!DOCTYPE"):
        reset_token()
        raise RuntimeError(
            "SSO Token 已过期，请在 Chrome 中重新登录：\n"
            "https://app-log-cn.tuya-inc.com:7799/"
        )

    return resp.json()


def _api_post(url: str, data: dict) -> dict:
    """发起认证的 POST 请求（用于 backendng API）。"""
    session = _get_session()
    headers = {
        "cookie": f"SSO_USER_TOKEN={_get_sso_token()}",
        "content-type": "application/json;charset=UTF-8",
    }
    resp = session.post(url, headers=headers, json=data, timeout=30)
    resp.raise_for_status()

    if resp.text.startswith("<!DOCTYPE"):
        reset_token()
        raise RuntimeError(
            "SSO Token 已过期，请在 Chrome 中重新登录：\n"
            "https://app-log-cn.tuya-inc.com:7799/"
        )

    return resp.json()


def _to_url_region(region: str) -> str:
    """将用户友好的区域码转换为 URL 区域码。"""
    return REGION_URL_MAP.get(region.lower(), region.lower())


def _infer_region_from_uid(uid: str) -> str:
    """根据 uid 前缀推断 URL 区域码。"""
    for prefix, url_region in UID_PREFIX_TO_URL_REGION.items():
        if uid.startswith(prefix):
            return url_region
    return "cn"


def _area_to_url_region(area: str) -> str:
    """将 backendng 返回的 userArea 区域名转换为 URL 区域码。"""
    for name, url_region in AREA_NAME_TO_URL_REGION.items():
        if area.startswith(name):
            return url_region
    return "cn"


def _normalize_upload_ts(raw) -> float:
    """uploadTime 可能是秒或毫秒，统一为秒（浮点）。"""
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v > 1e12:
        v = v / 1000.0
    return v


def parse_feedback_time(s: str) -> float:
    """将用户输入的时间解析为本地 Unix 时间戳（秒）。"""
    s = (s or "").strip()
    if not s:
        raise ValueError("feedback_time 不能为空")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    if s.isdigit():
        v = int(s)
        if v > 1e12:
            v = v / 1000.0
        return float(v)
    raise ValueError(
        f"无法解析 feedback_time: {s!r}，示例: 2026-03-13 15:45:42"
    )


def select_feedback_entries(
    uploads: list[dict],
    limit: int = 1,
    feedback_time_str: str | None = None,
) -> list[dict]:
    """决定要下载的反馈行。

    未指定 feedback_time 时按 limit 取前 N 条；
    指定 feedback_time 时找最接近的一条，并聚类 ±FEEDBACK_TIME_CLUSTER_SEC 秒内的记录。
    """
    if not uploads:
        return []
    lim = max(1, limit)

    if feedback_time_str:
        target = parse_feedback_time(feedback_time_str)
        pairs = [(u, _normalize_upload_ts(u.get("uploadTime"))) for u in uploads]
        valid = [(u, t) for u, t in pairs if t > 0]
        if not valid:
            raise ValueError("反馈列表中缺少有效的 uploadTime，无法按 feedback_time 匹配")
        _nearest_u, nearest_t = min(valid, key=lambda x: abs(x[1] - target))
        cluster = [
            u for u, t in valid if abs(t - nearest_t) <= FEEDBACK_TIME_CLUSTER_SEC
        ]
        seen: set = set()
        out: list[dict] = []
        for u in sorted(
            cluster,
            key=lambda x: _normalize_upload_ts(x.get("uploadTime")),
            reverse=True,
        ):
            fid = u.get("id")
            if fid is None or fid in seen:
                continue
            seen.add(fid)
            out.append(u)
        return out

    if lim == 1:
        return [uploads[0]]
    return uploads[:lim]


def _is_interactive() -> bool:
    """Whether stdin/stdout are TTY (safe to prompt)."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _print_table(title: str, headers: list[str], rows: list[list]) -> None:
    """Print a simple aligned table to stdout."""
    print(title, flush=True)
    cols = list(zip(*([headers] + rows))) if rows else [headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    sep = " | "
    head = sep.join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(head, flush=True)
    print(sep.join("-" * w for w in widths), flush=True)
    for row in rows:
        print(
            sep.join(str(row[i]).ljust(widths[i]) for i in range(len(headers))),
            flush=True,
        )


def _prompt_index(max_n: int, label: str = "选择序号") -> int:
    """1-based user choice; returns 0-based index."""
    while True:
        try:
            s = input(f"{label} (1-{max_n}): ").strip()
        except EOFError:
            raise UserSelectionRequired(
                "需要交互选择序号，但输入已结束。请使用 app_index 指定应用。"
            ) from None
        try:
            i = int(s)
        except ValueError:
            print("请输入有效数字。", file=sys.stderr)
            continue
        if 1 <= i <= max_n:
            return i - 1
        print(f"序号须在 1 到 {max_n} 之间。", file=sys.stderr)


def detect_account_type(account: str) -> str:
    """检测输入的账号类型。

    Returns:
        "email" / "mobile" / "uid" / "ticket"
    """
    account = account.strip()

    if _EMAIL_RE.match(account):
        return "email"

    cleaned = account.replace("-", "").replace("+", "").replace(" ", "")
    if _PHONE_RE.match(account) or (cleaned.isdigit() and len(cleaned) >= 8):
        return "mobile"

    if any(account.startswith(p) for p in UID_PREFIX_TO_URL_REGION):
        return "uid"

    return "ticket"


def search_by_ticket(ticket_id: str, region: str = "cn") -> tuple[dict, str]:
    """通过工单 ID 搜索日志。返回 (响应数据, 使用的URL区域码)。"""
    url_region = _to_url_region(region)
    url = (
        f"{_BASE_URL.format(region=url_region)}"
        f"/feedback/list"
        f"?ticketId={urllib.parse.quote(ticket_id)}"
        f"&pageSize=30&page=1"
    )
    return _api_get(url), url_region


def search_by_uid(
    uid: str,
    region: str | None = None,
    biz_type: int | None = None,
) -> tuple[dict, str]:
    """通过 UID 搜索日志。返回 (响应数据, 使用的URL区域码)。"""
    url_region = (
        _infer_region_from_uid(uid) if region is None
        else _to_url_region(region)
    )
    url = (
        f"{_BASE_URL.format(region=url_region)}"
        f"/feedback/list"
        f"?uid={urllib.parse.quote(uid)}"
        f"&pageSize=30&page=1"
    )
    if biz_type is not None:
        url += f"&bizType={urllib.parse.quote(str(biz_type))}"
    return _api_get(url), url_region


def fetch_app_infos(
    account: str,
    region: str,
    search_type: str,
) -> tuple[str, list[dict]]:
    """Query backendng for apps bound to email/mobile account.

    Returns (url_region, app_infos list).
    """
    url_region = _to_url_region(region)
    ng_url = (
        f"{_BACKENDNG_URL.format(region=url_region)}"
        f"/inner/backendng/user/type/bizName"
    )
    payload = {
        "userName": "",
        "bizType": "",
        "searchType": search_type,
        "searchValue": account,
        "groupId": "",
        "deviceState": True,
    }
    resp = _api_post(ng_url, payload)
    app_infos = resp.get("result", {}).get("appInfos", [])

    if not app_infos:
        user_area = resp.get("result", {}).get("userArea", [])
        if user_area:
            area = user_area[0].get("area", "")
            new_region = _area_to_url_region(area)
            if new_region != url_region:
                ng_url = (
                    f"{_BACKENDNG_URL.format(region=new_region)}"
                    f"/inner/backendng/user/type/bizName"
                )
                resp = _api_post(ng_url, payload)
                app_infos = resp.get("result", {}).get("appInfos", [])
                url_region = new_region

    return url_region, app_infos


def uid_for_app(
    account: str,
    url_region: str,
    search_type: str,
    app_info: dict,
) -> tuple[str, int]:
    """Resolve UID for one app (bizType). Returns (uid, biz_type)."""
    biz_type = app_info.get("bizType", 0)
    uid_url = (
        f"{_BACKENDNG_URL.format(region=url_region)}"
        f"/inner/backendng/device/getUserInfoV2"
    )
    uid_payload = {
        "bizType": biz_type,
        "searchType": search_type,
        "searchValue": account,
        "homeId": "",
        "offset": 0,
        "limit": 6,
        "includeUnbind": False,
    }
    uid_resp = _api_post(uid_url, uid_payload)
    uid = uid_resp.get("result", {}).get("uid", "")
    if not uid:
        raise ValueError("未找到账号在该应用下对应的 UID。")
    return uid, biz_type


def search_by_account(
    account: str,
    region: str = "cn",
    app_index: int | None = None,
) -> tuple[dict, str]:
    """通过用户账号（手机号/邮箱）搜索日志。

    支持多应用账号选择：单应用自动选择，多应用时通过 app_index(1-based)
    指定，或在交互终端中提示选择。

    Returns (响应数据, 使用的URL区域码)。
    """
    acct_type = detect_account_type(account)
    if acct_type not in ("email", "mobile"):
        raise ValueError(
            f"'{account}' 不是有效的手机号或邮箱。"
            f"如果是 UID 请使用 query_type='uid'，"
            f"如果是工单 ID 请使用 query_type='ticket'。"
        )

    url_region, app_infos = fetch_app_infos(account, region, acct_type)
    if not app_infos:
        raise ValueError(
            f"未找到账号 '{account}' 的应用信息。"
            f"请检查账号是否正确，或尝试指定 region 参数。"
        )

    if len(app_infos) == 1:
        chosen = app_infos[0]
    else:
        rows = [
            [
                idx + 1,
                x.get("appName", ""),
                x.get("appId", "-"),
                str(x.get("bizType", "")),
            ]
            for idx, x in enumerate(app_infos)
        ]
        _print_table(
            f"账号 {account} 归属多个应用，请选择应用序号：",
            ["No.", "App 名称", "AppId", "bizType"],
            rows,
        )
        if app_index is not None:
            if app_index < 1 or app_index > len(app_infos):
                raise ValueError(
                    f"app_index 须在 1-{len(app_infos)} 之间，当前为 {app_index}"
                )
            chosen = app_infos[app_index - 1]
        elif _is_interactive():
            chosen = app_infos[_prompt_index(len(app_infos), "应用")]
        else:
            raise UserSelectionRequired(
                "该账号绑定多个应用，请指定 app_index 参数选择应用 "
                f"(1..{len(app_infos)})。"
            )

    uid, biz_type = uid_for_app(account, url_region, acct_type, chosen)
    return search_by_uid(uid, region=url_region, biz_type=biz_type)


def get_log_detail(feedback_id: int | str, region: str = "cn") -> dict:
    """获取指定反馈记录的日志文件列表。"""
    url_region = _to_url_region(region)
    url = (
        f"{_BASE_URL.format(region=url_region)}"
        f"/feedback/get?id={feedback_id}"
    )
    return _api_get(url)


def list_files(
    feedback_id: int | str,
    region: str = "cn",
) -> tuple[list[dict], str]:
    """获取指定反馈记录的文件列表和平台信息。
    返回 (文件列表, platform)。"""
    detail = get_log_detail(feedback_id, region)
    data = detail.get("data", {})
    if not data:
        raise ValueError("未找到日志记录详情")

    logs = data.get("logs", [])
    platform = data.get("feedback", {}).get("platform", "iOS")
    return logs, platform


def format_file_list(logs: list[dict]) -> str:
    """格式化文件列表，标注业务日志文件。"""
    if not logs:
        return "该反馈记录中没有日志文件。"

    lines = [f"共 {len(logs)} 个文件：", ""]
    for idx, log_entry in enumerate(logs, 1):
        filename = log_entry.get("file", f"unknown_{idx}")
        is_biz = filename.endswith(".xlog")
        marker = " ← 业务日志" if is_biz else ""
        lines.append(f"  {idx}. {filename}{marker}")

    return "\n".join(lines)


def download_files(
    feedback_id: int | str,
    region: str = "cn",
    save_dir: str = ".",
    file_filter: str = "xlog",
    time_basename: str | None = None,
    time_index: list[int] | None = None,
) -> list[str]:
    """下载指定反馈记录的日志文件，返回已下载的文件路径列表。

    Args:
        file_filter: 文件过滤 — "xlog"(仅业务日志) / "all"(全部)，默认 "xlog"
        time_basename: 不为空时，文件命名为 <time_basename>.log / _2.log ...
        time_index: 可写的 [int]，用于多条反馈间连续编号避免覆盖
    """
    url_region = _to_url_region(region)
    detail = get_log_detail(feedback_id, region)

    data = detail.get("data", {})
    if not data:
        raise ValueError("未找到日志记录详情")

    logs = data.get("logs", [])
    platform = data.get("feedback", {}).get("platform", "iOS")

    if not logs:
        raise ValueError("该反馈记录中没有日志文件")

    if file_filter == "xlog":
        logs = [l for l in logs if (l.get("file", "")).endswith(".xlog")]
        if not logs:
            raise ValueError(
                "未找到 .xlog 业务日志文件。可设置 file_filter=\"all\" 下载全部文件。"
            )

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    downloaded: list[str] = []
    session = _get_session()

    for idx, log_entry in enumerate(logs):
        log_id = log_entry.get("id")
        if time_basename is not None:
            n = time_index[0] if time_index is not None else idx
            filename = (
                f"{time_basename}.log" if n == 0
                else f"{time_basename}_{n + 1}.log"
            )
            if time_index is not None:
                time_index[0] += 1
        else:
            filename = Path(log_entry.get("file", f"log_{log_id}.log")).name

        download_url = (
            f"{_BASE_URL.format(region=url_region)}"
            f"/log/download"
            f"?platform={urllib.parse.quote(platform)}"
            f"&id={log_id}&dtype=0"
        )

        headers = {"cookie": f"SSO_USER_TOKEN={_get_sso_token()}"}
        resp = session.get(
            download_url, headers=headers, timeout=120, stream=True
        )
        resp.raise_for_status()

        file_path = save_path / filename
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        downloaded.append(str(file_path))

    return downloaded


def format_search_results(resp: dict, used_region: str) -> str:
    """将搜索结果格式化为可读文本。"""
    data = resp.get("data") or {}
    result = resp.get("result") or {}
    total = data.get("total", 0) or result.get("total", 0)

    if total == 0:
        return (
            "未找到日志记录。\n"
            "可能原因：该用户/工单在当前区域无日志，或条件有误。\n"
            "可尝试切换 region 参数（cn/eu/us/ue/in/we）重新搜索。"
        )

    entries = (
        data.get("list")
        or result.get("list")
        or data.get("records")
        or data.get("feedbackList")
        or []
    )

    lines = [
        f"=== 找到 {total} 条日志记录（显示前 {len(entries)} 条）===",
        f"区域: {used_region}",
        "",
        f"{'No.':<5s} {'ID':<12s} {'App 名称':<20s} {'版本':<12s} "
        f"{'设备':<18s} {'系统':<15s} {'上传时间'}",
        "-" * 105,
    ]

    for idx, entry in enumerate(entries, 1):
        feedback_id = str(entry.get("id", ""))
        app_name = (entry.get("appName", "") or "")[:18]
        version = (entry.get("versionName", "") or "")[:10]
        device = (entry.get("device", "") or "")[:16]
        platform = entry.get("platform", "") or ""
        os_sys = entry.get("osSystem", "") or ""
        os_info = f"{platform} {os_sys}".strip()[:13]
        upload_ts = entry.get("uploadTime", 0)
        upload_time = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(
                _normalize_upload_ts(upload_ts)))
            if upload_ts else ""
        )

        lines.append(
            f"{idx:<5d} {feedback_id:<12s} {app_name:<20s} "
            f"{version:<12s} {device:<18s} {os_info:<15s} {upload_time}"
        )

    lines.append("")
    lines.append(
        f"下一步：调用 download_log(feedback_id=\"<ID>\", region=\"{used_region}\") "
        f"下载日志文件。"
    )

    return "\n".join(lines)
