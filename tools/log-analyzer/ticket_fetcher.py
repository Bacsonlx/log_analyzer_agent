"""Socrates 工单平台数据提取

从内网 Socrates 工单平台获取工单详情，解析富文本内容，
提取用于日志诊断的关键信息（账号、区域、设备 PID、App 版本等）。

认证方式：复用 log_downloader 的 SSO_USER_TOKEN。
"""

import json
import re
import urllib.parse

from log_downloader import _api_get, _get_sso_token, _get_session, reset_token

_SOCRATES_BASE = "https://socrates.tuya-inc.com:7799"
_PROBLEM_API = f"{_SOCRATES_BASE}/api/redline/socrates/api/problem/{{problem_id}}"

_EMAIL_RE = re.compile(r'[\w.\-+]+@[\w.\-]+\.\w{2,}')
_PHONE_RE = re.compile(r'(?<!\w)(?:\+?\d{1,4}[-\s])?\d{6,}(?!\w)')
_PID_RE = re.compile(r'(?:PID|pid)\s*[:：]\s*([a-z0-9]{10,})', re.IGNORECASE)
_DEVICE_ID_RE = re.compile(
    r'(?:设备\s*[Ii][Dd]|device\s*[Ii][Dd])\s*[:：]\s*([a-z0-9]{16,})',
    re.IGNORECASE,
)
_APP_VERSION_RE = re.compile(r'App\s*Version\s*[:：]\s*([\d.]+)', re.IGNORECASE)
_SDK_VERSION_RE = re.compile(r'SDK\s*Version\s*[:：]\s*([\d.]+)', re.IGNORECASE)
_CLIENT_ID_RE = re.compile(r'Client\s*ID\s*[:：]\s*([a-z0-9]+)', re.IGNORECASE)
_USER_ACCOUNT_RE = re.compile(r'User\s*Account\s*[:：]\s*(\S+)', re.IGNORECASE)

AREA_DESC_TO_REGION: dict[str, str] = {
    "中国": "cn",
    "国内": "cn",
    "欧洲": "eu",
    "美西": "us",
    "美国西": "us",
    "美东": "ue",
    "美国东": "ue",
    "印度": "in",
    "西欧": "we",
    "日本": "us",
}


def _socrates_api_get(url: str) -> dict:
    """Socrates 专用 GET 请求，与 log_downloader 共享 SSO 认证。"""
    session = _get_session()
    headers = {
        "cookie": f"SSO_USER_TOKEN={_get_sso_token()}",
        "accept": "application/json",
    }
    resp = session.get(url, headers=headers, timeout=30, verify=False)
    resp.raise_for_status()

    if resp.text.startswith("<!DOCTYPE"):
        reset_token()
        raise RuntimeError(
            "SSO Token 已过期，请在 Chrome 中重新登录：\n"
            "https://socrates.tuya-inc.com:7799/"
        )

    return resp.json()


def parse_ticket_id(ticket_url_or_id: str) -> str:
    """从工单 URL 或纯 ID 字符串中提取工单 ID。"""
    text = ticket_url_or_id.strip()

    if text.isdigit():
        return text

    parsed = urllib.parse.urlparse(text)
    qs = urllib.parse.parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]

    digits = re.search(r'\d+', text)
    if digits:
        return digits.group()

    raise ValueError(f"无法从 '{ticket_url_or_id}' 中提取工单 ID")


def fetch_ticket_detail(problem_id: str) -> dict:
    """调用 Socrates API 获取工单详情原始数据。"""
    url = _PROBLEM_API.format(problem_id=problem_id)
    resp = _socrates_api_get(url)

    if not resp.get("success"):
        raise RuntimeError(
            f"获取工单 #{problem_id} 失败: {resp.get('msg', '未知错误')}"
        )

    result = resp.get("result")
    if not result:
        raise RuntimeError(f"工单 #{problem_id} 不存在或无权限访问")

    return result


def extract_plain_text(content_json: str) -> str:
    """递归提取富文本 JSON 中的纯文本。

    Socrates 的 problemContent 使用 Slash 编辑器的 JSON 格式，
    结构为嵌套的 {type, children, text} 节点树。
    """
    if not content_json:
        return ""

    try:
        nodes = json.loads(content_json)
    except (json.JSONDecodeError, TypeError):
        return str(content_json)

    texts: list[str] = []

    def _walk(node):
        if isinstance(node, list):
            for child in node:
                _walk(child)
            return
        if not isinstance(node, dict):
            return

        text = node.get("text", "")
        if text and text.strip():
            texts.append(text.strip())

        children = node.get("children")
        if children:
            _walk(children)

    _walk(nodes)
    return "\n".join(texts)


def _infer_region_from_text(text: str) -> str | None:
    """从问题描述文本中推断服务区域。"""
    for keyword, region in AREA_DESC_TO_REGION.items():
        if keyword in text:
            return region
    return None


def extract_diagnosis_params(text: str) -> dict:
    """从工单纯文本中提取日志诊断所需的关键参数。

    Returns:
        dict with keys: account, region, pid, device_id,
                        app_version, sdk_version, client_id, platform
    """
    params: dict[str, str | None] = {
        "account": None,
        "region": None,
        "pid": None,
        "device_id": None,
        "app_version": None,
        "sdk_version": None,
        "client_id": None,
        "platform": None,
    }

    m = _USER_ACCOUNT_RE.search(text)
    if m:
        params["account"] = m.group(1)
    else:
        m = _EMAIL_RE.search(text)
        if m:
            params["account"] = m.group()

    m = _PID_RE.search(text)
    if m:
        params["pid"] = m.group(1)

    m = _DEVICE_ID_RE.search(text)
    if m:
        params["device_id"] = m.group(1)

    m = _APP_VERSION_RE.search(text)
    if m:
        params["app_version"] = m.group(1)

    m = _SDK_VERSION_RE.search(text)
    if m:
        params["sdk_version"] = m.group(1)

    m = _CLIENT_ID_RE.search(text)
    if m:
        params["client_id"] = m.group(1)

    params["region"] = _infer_region_from_text(text)

    text_lower = text.lower()
    if "android" in text_lower and "ios" not in text_lower:
        params["platform"] = "Android"
    elif "ios" in text_lower and "android" not in text_lower:
        params["platform"] = "iOS"

    return params


_TICKET_STATE_MAP = {
    0: "待处理",
    1: "处理中",
    2: "待确认",
    3: "已确认",
    4: "已驳回",
    5: "暂缓处理",
    6: "完结",
}


def format_ticket_summary(detail: dict, plain_text: str, params: dict) -> str:
    """将工单信息格式化为可读的诊断摘要。"""
    problem_id = detail.get("problemId", "?")
    title = detail.get("title", "")
    state = _TICKET_STATE_MAP.get(detail.get("state"), str(detail.get("state", "")))
    customer = detail.get("customerName", "")
    biz_line = detail.get("bizLineName", "")
    create_time = detail.get("createTime", "")
    creator = detail.get("creatorPerson", {}).get("personName", "")
    solver = detail.get("solverStaffPerson", {}).get("personName", "")

    lines = [
        "=" * 60,
        f"Socrates 工单 #{problem_id}",
        "=" * 60,
        "",
        f"标题: {title}",
        f"状态: {state}",
        f"客户: {customer}",
        f"业务线: {biz_line}",
        f"创建人: {creator}",
        f"经办人: {solver}",
        f"创建时间: {create_time}",
    ]

    lines.append("")
    lines.append("--- 提取的诊断参数 ---")

    param_labels = {
        "account": "用户账号",
        "region": "服务区域",
        "pid": "设备 PID",
        "device_id": "设备 ID",
        "app_version": "App 版本",
        "sdk_version": "SDK 版本",
        "client_id": "Client ID",
        "platform": "平台",
    }
    found_any = False
    for key, label in param_labels.items():
        val = params.get(key)
        if val:
            lines.append(f"  {label}: {val}")
            found_any = True
    if not found_any:
        lines.append("  （未提取到结构化参数）")

    lines.append("")
    lines.append("--- 问题描述 ---")
    for line in plain_text.splitlines():
        lines.append(f"  {line}")

    return "\n".join(lines)
