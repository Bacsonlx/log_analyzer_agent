from __future__ import annotations

import json
import os
import re
import secrets
import uuid
import logging
import asyncio
import time
from collections import defaultdict
from urllib.parse import quote, urlencode
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager

from claude_runner import StreamEvent, try_create_claude_runner

sys_path_tool_dir = str(Path(__file__).resolve().parent.parent / "tools" / "log-analyzer")
import sys
if sys_path_tool_dir not in sys.path:
    sys.path.insert(0, sys_path_tool_dir)

import log_downloader  # noqa: E402
import requests  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 仓库根（含 web-diagnostic/、tools/、.mcp.json）；须与 Claude CLI cwd 一致以加载 MCP
_REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = os.environ.get("WORKSPACE_ROOT", str(_REPO_ROOT))
_REPO = Path(WORKSPACE)
UPLOAD_DIR = _REPO / "tools" / "log-analyzer" / "data"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_DIR = Path(__file__).resolve().parent / "data" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

KNOWLEDGE_DIR = _REPO / "tools" / "log-analyzer" / "knowledge"

ALLOWED_EXTENSIONS = {".log", ".xlog", ".gz", ".zip", ".txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024

# 多租户：按 WebSocket web_session_id 绑定 App 日志平台 SSO（内存）
AUTO_DOWNLOAD_SSO_MARKER = "请搜索并下载日志"
sso_token_by_web_session: dict[str, str] = {}
sso_verified_web_sessions: set[str] = set()

# OAuth → OAuth 返回后页面会重载，用一次性 bridge 把 Token 绑到新 web_session_id
OAUTH_STATE_TTL_SEC = 600
OAUTH_BRIDGE_TTL_SEC = 300
_oauth_state_store: dict[str, tuple[str, float]] = {}
_oauth_bridge_store: dict[str, tuple[str, float]] = {}

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(queue_worker())
    yield

app = FastAPI(title="AIVoice AI Diagnostic", lifespan=lifespan)


@app.middleware("http")
async def inject_request_sso_token(request: Request, call_next):
    """为 REST（如 fetch-ticket）注入当前浏览器会话的 SSO_USER_TOKEN ContextVar。"""
    sid = request.headers.get("x-web-diagnostic-session")
    if sid and sid in sso_token_by_web_session:
        tok = sso_token_by_web_session[sid]
        var = log_downloader.sso_request_token
        reset = var.set(tok)
        try:
            return await call_next(request)
        finally:
            var.reset(reset)
    return await call_next(request)

runner = try_create_claude_runner(WORKSPACE)
if runner is None:
    logger.warning("Claude runner unavailable; diagnose/chat actions will fail until Claude CLI is configured")

claude_sessions: dict[str, str] = {}


@app.get("/health")
async def health():
    """Liveness for Docker HEALTHCHECK and JumpServer MVP acceptance."""
    return {
        "status": "ok",
        "claude_enabled": runner is not None,
        "oauth_app_log_enabled": _oauth_app_log_configured(),
    }


# --------------- Global Task Queue ---------------

@dataclass
class QueuedTask:
    task_id: str
    web_session_id: str
    message: str
    ws: WebSocket
    template: str = "auto"
    cancelled: bool = False


task_queue: asyncio.Queue[QueuedTask] = asyncio.Queue()

pending_tasks: dict[str, QueuedTask] = {}

queue_order: list[str] = []

connected_clients: dict[str, WebSocket] = {}


def _public_base_url(request: Request) -> str:
    pub = (os.environ.get("APP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if pub:
        return pub
    return str(request.base_url).rstrip("/")


def _oauth_app_log_configured() -> bool:
    keys = (
        "APP_LOG_OAUTH_AUTHORIZE_URL",
        "APP_LOG_OAUTH_TOKEN_URL",
        "APP_LOG_OAUTH_CLIENT_ID",
        "APP_LOG_OAUTH_CLIENT_SECRET",
        "APP_LOG_OAUTH_REDIRECT_URI",
    )
    return all((os.environ.get(k) or "").strip() for k in keys)


def _oauth_prune_store(store: dict[str, tuple[str, float]], mono_now: float) -> None:
    for k in [x for x, (_, exp) in store.items() if exp < mono_now]:
        store.pop(k, None)


def _oauth_extract_token_from_json(data: dict, field_path: str) -> str | None:
    path = (field_path or "").strip()
    if path:
        cur: object = data
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        if isinstance(cur, str):
            s = cur.strip()
            return s if s else None
        return None
    for k in (
        "SSO_USER_TOKEN",
        "sso_user_token",
        "access_token",
        "accessToken",
        "id_token",
        "idToken",
    ):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _oauth_extract_token_from_json(nested, "")
    return None


def _oauth_exchange_code_sync(code: str) -> dict:
    token_url = os.environ["APP_LOG_OAUTH_TOKEN_URL"]
    redirect_uri = os.environ["APP_LOG_OAUTH_REDIRECT_URI"]
    client_id = os.environ["APP_LOG_OAUTH_CLIENT_ID"]
    client_secret = os.environ["APP_LOG_OAUTH_CLIENT_SECRET"]
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(token_url, data=payload, timeout=45)
    resp.raise_for_status()
    return resp.json()


async def broadcast_queue_status():
    """Notify all connected clients about current queue state."""
    status = []
    for tid in queue_order:
        t = pending_tasks.get(tid)
        if t:
            status.append({"task_id": t.task_id, "session_id": t.web_session_id, "message": t.message[:50]})

    msg = {"type": "queue_update", "queue": status}
    dead = []
    for sid, ws in connected_clients.items():
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(sid)
    for sid in dead:
        connected_clients.pop(sid, None)


async def queue_worker():
    """Single worker that processes tasks one at a time."""
    logger.info("Queue worker started")
    while True:
        task = await task_queue.get()
        tid = task.task_id

        if task.cancelled:
            pending_tasks.pop(tid, None)
            if tid in queue_order:
                queue_order.remove(tid)
            task_queue.task_done()
            await broadcast_queue_status()
            continue

        logger.info("Worker processing task=%s session=%s", tid, task.web_session_id)

        if tid in queue_order:
            queue_order.remove(tid)
        await broadcast_queue_status()

        try:
            await _run_task(task)
        except Exception as e:
            logger.exception("Worker task error: %s", e)
            try:
                await task.ws.send_json({"type": "error", "content": str(e)})
            except Exception:
                pass
        finally:
            pending_tasks.pop(tid, None)
            task_queue.task_done()
            await broadcast_queue_status()


def _extra_env_for_web_session(web_session_id: str) -> dict[str, str] | None:
    tok = sso_token_by_web_session.get(web_session_id)
    if not tok:
        return None
    return {"SSO_USER_TOKEN": tok}


async def _run_task(task: QueuedTask):
    """Execute a single analysis task and stream events to the client."""
    if AUTO_DOWNLOAD_SSO_MARKER in task.message:
        if task.web_session_id not in sso_verified_web_sessions:
            try:
                await task.ws.send_json({
                    "type": "need_sso",
                    "task_id": task.task_id,
                    "title": "需要日志平台登录态",
                    "hint": (
                        "自动下载前请在下方「日志平台登录态」粘贴 SSO/Cookie 并点「保存并验证」，"
                        "或（若已配置）使用「一键登录（OAuth）」。"
                    ),
                })
            except Exception:
                pass
            return

    try:
        await task.ws.send_json({"type": "task_started", "task_id": task.task_id})
    except Exception:
        return

    if runner is None:
        try:
            await task.ws.send_json({
                "type": "error",
                "content": "当前环境未启用 Claude CLI（例如容器内 WEB_DIAGNOSTIC_SKIP_CLAUDE=1），无法执行诊断。",
            })
        except Exception:
            pass
        return

    extra_env = _extra_env_for_web_session(task.web_session_id)

    c_session = claude_sessions.get(task.web_session_id)
    event_count = 0
    result_text = ""
    result_duration = 0
    result_cost = 0.0
    tool_count = 0
    template_data: dict | None = None
    extracted_files: list[dict] = []
    server_asr_records: list | None = None
    server_pipeline_data: dict | None = None

    # 构建带模版提示的完整消息
    full_message = task.message + _build_template_prompt(task.template)

    try:
        async for event in runner.run(
            full_message,
            session_id=c_session,
            task_id=task.task_id,
            extra_env=extra_env,
        ):
            if task.cancelled:
                runner.cancel(task.task_id)
                try:
                    await task.ws.send_json({"type": "stopped"})
                except Exception:
                    pass
                return

            event_count += 1
            if event.tool_name:
                tool_count += 1
            logger.info(
                "Event#%d task=%s: type=%s role=%s text=%s tool=%s",
                event_count, task.task_id, event.event_type, event.role,
                event.text[:80] if event.text else "", event.tool_name,
            )

            # 捕获 extract_aibuds_logs 输出的文件路径
            if event.role == "user" and event.tool_result:
                fm = _EXTRACT_FILE_RE.search(event.tool_result)
                if fm:
                    raw_path = fm.group(1).strip()
                    abs_path = Path(raw_path)
                    if not abs_path.is_absolute():
                        abs_path = _REPO / raw_path
                    abs_path = abs_path.resolve()
                    if abs_path.is_file():
                        try:
                            rel = abs_path.relative_to(_REPO)
                        except ValueError:
                            rel = abs_path
                        if not any(f["path"] == str(rel) for f in extracted_files):
                            extracted_files.append({
                                "path": str(rel),
                                "name": "全量提取",
                                "type": "full",
                                "size_kb": round(abs_path.stat().st_size / 1024, 1),
                            })
                        # 从全量日志中直接解析 ASR 记录（无需二次提取子文件）
                        if task.template == "audio-recognition":
                            _asr_records_from_server = _parse_asr_records(str(abs_path))
                            if _asr_records_from_server:
                                server_asr_records = _asr_records_from_server

                        if server_pipeline_data is None:
                            _pipeline = _extract_pipeline_result(event.tool_result)
                            if _pipeline:
                                server_pipeline_data = _pipeline

            if event.is_result:
                result_text = event.text
                result_duration = event.duration_ms
                result_cost = event.cost_usd
                # 提取 template_data，将 JSON 块从正文中分离
                template_data, result_text = _extract_template_data(result_text)
                if template_data and template_data.get("template") == "translation":
                    template_data["template"] = "audio-recognition"
                # 统一为 recordings 格式，合并服务端 ASR 数据
                _ensure_recordings_format(template_data)
                _merge_asr_into_recordings(template_data, server_asr_records)
                if not template_data and server_pipeline_data:
                    template_data = {
                        "template": task.template or "audio-recognition",
                        "recordings": server_pipeline_data.get("recordings", []),
                    }
                    _merge_asr_into_recordings(template_data, server_asr_records)
                event.text = result_text
                if event.session_id:
                    claude_sessions[task.web_session_id] = event.session_id

            elif event.is_result is False and event.session_id:
                pass

            if event.is_result and event.session_id:
                claude_sessions[task.web_session_id] = event.session_id

            msg = _format_ws_message(event, template_data if event.is_result else None, extracted_files if event.is_result else None)
            if msg:
                try:
                    await task.ws.send_json(msg)
                except Exception:
                    logger.warning("Failed to send to client, aborting task=%s", task.task_id)
                    runner.cancel(task.task_id)
                    return

        if event_count == 0:
            logger.warning(
                "Task=%s: Claude 未产生任何 stream-json 事件。请查看上一条 "
                "\"Claude stderr\" WARNING、鉴权(ANTHROPIC_*)、并在容器内试跑: "
                "claude -p \"ping\" --output-format stream-json --verbose",
                task.task_id,
            )
        hist_file = _save_history(task, result_text, result_duration, result_cost, tool_count, "done", template_data, extracted_files)
        if hist_file:
            try:
                await task.ws.send_json({"type": "history_file", "file": hist_file})
            except Exception:
                pass
        logger.info("Task=%s done, %d events", task.task_id, event_count)
    except asyncio.CancelledError:
        _save_history(task, "", 0, 0.0, event_count, "cancelled")
        runner.cancel(task.task_id)
        try:
            await task.ws.send_json({"type": "stopped"})
        except Exception:
            pass
    except Exception as e:
        logger.exception("Task=%s error: %s", task.task_id, e)
        try:
            await task.ws.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


_TEMPLATE_PHASES: dict[str, dict] = {
    "audio-recognition": {
        "label": "实时链路",
        "phases": [
            {"name": "选择设备", "modules": ["Record", "AudioInput", "BatteryMonitor", "MiniApp", "EventDispatch"]},
            {"name": "选择语言", "modules": ["ASR", "Translate", "Transfer", "FaceToFace", "SI", "Phone", "PhoneAndBuds", "PhoneAndEntryBuds"]},
            {"name": "点击开始", "modules": ["Record", "AudioInput", "VAD", "Session", "Token", "AIChannel", "Coder"]},
            {"name": "开始识别", "modules": ["ASR", "Recognition", "AIChannel", "VAD", "AudioInput", "Session", "Token", "Amplitude"]},
            {"name": "识别结束", "modules": ["ASR", "Recognition", "Transfer", "Translate", "MQTT", "TraceEvent", "Record"]},
        ],
        "asr_records": True,
    },
    "offline-transcription": {
        "label": "离线转写/总结",
        "phases": [
            {"name": "触发转写", "modules": ["Upload", "Transcribe", "DB"]},
            {"name": "收到转写MQ", "modules": ["MQTT"]},
            {"name": "转写结果写入", "modules": ["Upload", "DB"]},
            {"name": "触发总结", "modules": ["Upload"]},
            {"name": "收到总结MQ", "modules": ["MQTT"]},
            {"name": "总结结果写入", "modules": ["Upload", "DB"]},
        ],
        "recordings_by_field": True,
    },
    "cloud-upload": {
        "label": "云同步上传",
        "phases": ["发起上传", "获取加密密钥", "文件加密", "文件上传", "DB状态更新"],
    },
}


def _normalize_template_id(template: str) -> str:
    """将已废弃的模版 id 映射为当前 canonical id（兼容旧客户端与历史 JSON）。"""
    if template in ("translation", "recording"):
        return "audio-recognition"
    return template


_PHASE_STATUS_HINT = "status 取值: success=正常完成; failed=出现错误; warning=有警告但未中断; skipped=日志中未找到该阶段记录"

_ASR_RECORDS_HINT = """
另外，请从 [AIBuds_ASR] 日志中提取每一句话的 ASR 识别记录，填入 "asr_records" 数组（按时间排序，最多保留20条）。
每条记录对应一个唯一的 requestId，字段说明：
- request_id: 日志中的 requestId 字符串
- start_time: "Received - Start" 日志的时间戳（HH:MM:SS.mmm）
- end_time: "ASRTask ended" 日志的时间戳
- duration_ms: "Received cloud End duration" 的毫秒数（整数）
- final_text: "Start sending to the mini-program" 日志中最后出现的 asr 值
- translation: 同行 translate 值（无则空字符串）
- status: "All data is empty" 出现则填 "empty"；Error 非 None 则填 "error"；否则 "success"
- error: ASRTask ended 中 Error 字段值（None 时填 null）
- updates: Update 日志中文本变化的列表，格式 [{"time": "HH:MM:SS.mmm", "text": "识别文本"}]（相邻重复文本去重）
若日志中无 [AIBuds_ASR] 记录，asr_records 填空数组 []。"""


def _build_template_prompt(template: str) -> str:
    """构建模版提示词，追加到用户消息末尾告知AI按结构输出。"""

    def _phase_name(p) -> str:
        return p["name"] if isinstance(p, dict) else p

    def _phase_json_line(p, indent=4) -> str:
        name = _phase_name(p)
        pad = " " * indent
        return (
            f'{pad}{{"name": "{name}", "status": "<success|failed|warning|skipped>", '
            f'"time": "<HH:MM:SS.mmm 或 null>", '
            f'"detail": "<关键日志摘要，不超过100字符>"}}'
        )

    _full_extract_hint = (
        "\n\n[重要] 提取日志时请使用 extract_to_file 工具进行**全量提取**（不要指定 module 参数），"
        "确保包含所有 [AIBuds_*] 模块的完整日志。各阶段的诊断应基于全量 AIBuds 日志进行，"
        "不要仅看 [AIBuds_ASR]。每个阶段的 detail 中请注明参考了哪些模块的关键日志。"
    )

    if template != "auto" and template in _TEMPLATE_PHASES:
        meta = _TEMPLATE_PHASES[template]

        if meta.get("recordings_by_field"):
            phases_str = ",\n".join(_phase_json_line(p, indent=8) for p in meta["phases"])
            recording_example = f"""    {{
      "record_id": "<fileId>",
      "status": "<success|failed|interrupted>",
      "phases": [
{phases_str}
      ]
    }}"""

            phase_modules_hint = ""
            if any(isinstance(p, dict) and p.get("modules") for p in meta["phases"]):
                lines = []
                for p in meta["phases"]:
                    if isinstance(p, dict) and p.get("modules"):
                        tags = ", ".join(f"[AIBuds_{m}]" for m in p["modules"])
                        lines.append(f"  - {p['name']}: {tags}")
                phase_modules_hint = "\n各阶段应重点关注的日志模块：\n" + "\n".join(lines)

            recording_status_hint = (
                "\nrecording 级别 status 取值: "
                "success=全部阶段完成无失败; "
                "failed=某步失败; "
                "interrupted=流程未完成"
            )

            status_codes_hint = """
状态码参考：
- transcribeStatus（本地DB）：0=未知, 1=转写中, 2=转写成功, 3=转写失败
- summaryStatus（本地DB）：0=老数据, 1=未知, 2=总结中, 3=总结成功, 4=总结失败
- translateStatus（本地DB）：0=老数据, 1=未知, 2=翻译中, 3=翻译成功, 4=翻译失败
- 云端 MQTT 状态码：0=未知, 1=初始, 2=进行中, 9=成功, 100=失败
注意：云端返回 TranscribeTooShort 错误码时，客户端约定视为总结成功。"""

            return f"""

---
[诊断报告格式要求] 本次诊断场景为「{meta["label"]}」。
日志中可能包含多个 fileId 对应的独立转写/总结流程。请按 fileId 分别诊断每个文件的 6 个阶段。

请在输出 Markdown 报告正文之前，先输出以下格式的 JSON 代码块：
```json
{{
  "template": "{template}",
  "recordings": [
{recording_example}
  ]
}}
```
{_PHASE_STATUS_HINT}{recording_status_hint}{phase_modules_hint}{status_codes_hint}

诊断报告中出现 transcribeStatus、summaryStatus 等状态码时，请标注其真实含义。

[重要] diagnose_scenario 的返回中可能已包含「结构化分析 (JSON)」段，
其中的 recordings[] 是脚本根据日志 pattern 自动生成的阶段判定（含 confidence 和 evidence）。
若存在该段：
1. 审阅每个 recording 的 phases，尤其是 confidence: "low" 的阶段需要你用日志上下文做最终判定
2. confidence: "high" 的阶段可直接采纳，将 evidence 中的关键信息写入 detail
3. 如需修正，直接在你输出的 JSON 中覆盖对应阶段的 status/detail
4. 你**不需要**使用 Grep 或其他工具搜索日志，所有关键证据已在 evidence 中提供{_full_extract_hint}
输出 JSON 代码块后，换行继续输出正常的 Markdown 诊断报告。"""

        if meta.get("asr_records"):
            # per-recording 格式：recordings 数组
            phases_str = ",\n".join(_phase_json_line(p, indent=8) for p in meta["phases"])
            recording_example = f"""    {{
      "record_id": "<requestId 去掉尾部 _N 序号>",
      "status": "<success|failed|interrupted>",
      "phases": [
{phases_str}
      ]
    }}"""

            phase_modules_hint = ""
            if any(isinstance(p, dict) and p.get("modules") for p in meta["phases"]):
                lines = []
                for p in meta["phases"]:
                    if isinstance(p, dict) and p.get("modules"):
                        tags = ", ".join(f"[AIBuds_{m}]" for m in p["modules"])
                        lines.append(f"  - {p['name']}: {tags}")
                phase_modules_hint = "\n各阶段应重点关注的日志模块：\n" + "\n".join(lines)

            recording_status_hint = (
                "\nrecording 级别 status 取值: "
                "success=5步完整走完无失败; "
                "failed=某步失败但流程有结束; "
                "interrupted=中途中断（app被杀、无结束日志）"
            )

            return f"""

---
[诊断报告格式要求] 本次诊断场景为「{meta["label"]}」。
日志中可能包含多段独立的录音流程，每段录音都有自己完整的「选择设备→选择语言→点击开始→开始识别→识别结束」流程。
请识别出日志中所有录音段，为每段录音独立诊断 5 个阶段。对于中途中断的录音（如 app 被杀），后续阶段标记为 skipped。

请在输出 Markdown 报告正文之前，先输出以下格式的 JSON 代码块：
```json
{{
  "template": "{template}",
  "recordings": [
{recording_example}
  ]
}}
```
{_PHASE_STATUS_HINT}{recording_status_hint}{phase_modules_hint}

**不需要**输出 asr_records，服务端会自动从 ASR 日志中解析并合并。
record_id 从 requestId 中提取，去掉尾部 _N 序号（例如 ej_PHONE00UrkYs7_1775540437_0_0 的 record_id 为 ej_PHONE00UrkYs7_1775540437）。
在「点击开始」「开始识别」阶段的 detail 中，若全量日志里存在请务必摘抄 [AIBuds_Token] / [AIBuds_Session] / [AIBuds_AIChannel] 中含 `scene: create`、`scene: update`、`scene: remove` 或 `scene: session` 等关键行（附日志时间与一句原文，勿臆造）。

[重要] diagnose_scenario 的返回中可能已包含「结构化分析 (JSON)」段，
其中的 recordings[] 是脚本根据日志 pattern 自动生成的阶段判定（含 confidence 和 evidence）。
若存在该段：
1. 审阅每个 recording 的 phases，尤其是 confidence: "low" 的阶段需要你用日志上下文做最终判定
2. confidence: "high" 的阶段可直接采纳，将 evidence 中的关键信息写入 detail
3. 如需修正，直接在你输出的 JSON 中覆盖对应阶段的 status/detail
4. 你**不需要**使用 Grep 或其他工具搜索日志，所有关键证据已在 evidence 中提供{_full_extract_hint}
输出 JSON 代码块后，换行继续输出正常的 Markdown 诊断报告。"""

        # 非 asr_records 模版：保持 flat phases
        phases_str = ",\n".join(_phase_json_line(p) for p in meta["phases"])
        return f"""

---
[诊断报告格式要求] 本次诊断场景为「{meta["label"]}」，请在输出 Markdown 报告正文之前，先输出以下格式的 JSON 代码块：
```json
{{
  "template": "{template}",
  "phases": [
{phases_str}
  ]
}}
```
{_PHASE_STATUS_HINT}{_full_extract_hint}
输出 JSON 代码块后，换行继续输出正常的 Markdown 诊断报告。"""

    # auto 模式：列出所有可用场景让 AI 自选
    def _scene_phases_str(meta: dict) -> str:
        return ", ".join(_phase_name(p) for p in meta["phases"])

    scenes = "\n".join(
        f'- {tid}（{meta["label"]}）: {_scene_phases_str(meta)}'
        for tid, meta in _TEMPLATE_PHASES.items()
    )
    auto_phases_example = ",\n".join(_phase_json_line(p) for p in ["<阶段名1>", "<阶段名2>"])
    return f"""

---
[诊断报告格式要求] 如果本次诊断问题属于以下场景之一，请在 Markdown 报告正文之前先输出对应的 JSON 代码块：
{scenes}

格式：
```json
{{
  "template": "<场景ID>",
  "phases": [
{auto_phases_example}
  ]
}}
```
{_PHASE_STATUS_HINT}
若不匹配任何场景，则直接输出 Markdown 报告，不需要 JSON 代码块。"""


_EXTRACT_FILE_RE = re.compile(r'输出文件[：:]\s*([^\s(]+\.log)', re.MULTILINE)

_PIPELINE_RESULT_RE = re.compile(
    r'--- 结构化分析 \(JSON\) ---\s*(\{.+)',
    re.DOTALL,
)


def _extract_pipeline_result(tool_result: str) -> dict | None:
    """Extract pipeline analyzer JSON from diagnose_scenario output."""
    m = _PIPELINE_RESULT_RE.search(tool_result)
    if not m:
        return None
    blob = m.group(1)
    brace_start = blob.find("{")
    if brace_start < 0:
        return None
    extracted = _extract_balanced_json_object(blob, brace_start)
    if not extracted:
        return None
    try:
        data = json.loads(extracted)
        if isinstance(data.get("recordings"), list):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _extract_balanced_json_object(text: str, open_brace: int) -> str | None:
    """从 open_brace 指向的「{」起解析 JSON 对象，括号与字符串转义与 json 一致，避免被内层「}」截断。"""
    if open_brace < 0 or open_brace >= len(text) or text[open_brace] != "{":
        return None
    depth = 0
    i = open_brace
    in_str = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if in_str and c == "\\":
            escape = True
            i += 1
            continue
        if c == '"' and not escape:
            in_str = not in_str
            i += 1
            continue
        if not in_str:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[open_brace : i + 1]
        i += 1
    return None


def _extract_template_data(text: str) -> tuple[dict | None, str]:
    """从 AI 输出中提取含 template + recordings|phases 的 JSON 代码块，返回 (data, clean_text)。"""
    lower = text.lower()
    search_from = 0
    while True:
        fence = lower.find("```json", search_from)
        if fence < 0:
            return None, text
        brace = text.find("{", fence + 6)
        if brace < 0:
            search_from = fence + 6
            continue
        blob = _extract_balanced_json_object(text, brace)
        if not blob:
            search_from = fence + 6
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            search_from = fence + 6
            continue
        if not isinstance(data.get("template"), str):
            search_from = brace + 1
            continue
        phases_ok = isinstance(data.get("phases"), list)
        recordings_ok = isinstance(data.get("recordings"), list)
        if not phases_ok and not recordings_ok:
            search_from = fence + 6
            continue
        blob_end = brace + len(blob)
        end_fence = text.find("```", blob_end)
        if end_fence < 0:
            clean = (text[:fence] + text[blob_end:]).strip()
        else:
            clean = (text[:fence] + text[end_fence + 3 :]).strip()
        return data, clean


def _create_asr_subfile(full_log_path: str) -> str | None:
    """从全量 AIBuds 日志中过滤 [AIBuds_ASR] 行，保存为子文件。无 ASR 行时返回 None。"""
    src = Path(full_log_path)
    if not src.is_file():
        return None
    lines = [
        line for line in src.read_text(encoding="utf-8", errors="replace").splitlines()
        if "[AIBuds_ASR]" in line
    ]
    if not lines:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = src.parent / f"aiBuds_ASR_{ts}.log"
    dest.write_text("\n".join(lines), encoding="utf-8")
    return str(dest)


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
    last_ended_rid: str | None = None

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
            r["final_text"] = m.group(2).strip()
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
            last_ended_rid = rid

        elif m := _ASR_DURATION_RE.search(line):
            target = last_ended_rid or last_rid
            if target and target in records:
                records[target]["duration_ms"] = int(m.group(1))

        elif m := _ASR_EMPTY_RE.search(line):
            rid = m.group(1).rstrip(",")
            r = get_or_create(rid)
            r["_has_empty"] = True
            last_rid = rid

    result = []
    for rid in order:
        r = records[rid]
        if r["_has_empty"] and r["status"] == "success":
            r["status"] = "empty"
        del r["_last_update_text"]
        del r["_has_empty"]
        r["record_id"] = re.sub(r'_\d+$', '', rid)
        result.append(r)

    return result


def _merge_asr_into_recordings(template_data: dict | None, server_asr_records: list | None) -> None:
    """将服务端解析的 asr_records 按 record_id 合并到 recordings 数组。"""
    if not template_data or not server_asr_records:
        return
    recordings = template_data.get("recordings")
    if not recordings:
        return

    asr_by_record: dict[str, list] = defaultdict(list)
    for r in server_asr_records:
        asr_by_record[r.get("record_id", "")].append(r)

    matched_ids: set[str] = set()
    for rec in recordings:
        rid = rec.get("record_id", "")
        if rid in asr_by_record:
            rec["asr_records"] = asr_by_record[rid]
            matched_ids.add(rid)
        else:
            rec.setdefault("asr_records", [])

    unmatched = []
    for rid, recs in asr_by_record.items():
        if rid not in matched_ids:
            unmatched.extend(recs)
    if unmatched and recordings:
        recordings[-1].setdefault("asr_records", []).extend(unmatched)


def _ensure_recordings_format(template_data: dict | None) -> None:
    """向后兼容：将 flat phases + asr_records 包装为 recordings 格式。"""
    if not template_data:
        return
    if "recordings" in template_data:
        return
    if "phases" not in template_data:
        return
    template_data["recordings"] = [{
        "record_id": "legacy",
        "status": "success",
        "phases": template_data.pop("phases"),
        "asr_records": template_data.pop("asr_records", []),
    }]


def _format_ws_message(event: StreamEvent, template_data: dict | None = None, extracted_files: list | None = None) -> dict | None:
    if event.event_type == "system":
        return None

    if event.is_result:
        msg = {
            "type": "result",
            "session_id": event.session_id,
            "cost_usd": event.cost_usd,
            "duration_ms": event.duration_ms,
        }
        if event.text:
            msg["final_text"] = event.text
        if template_data:
            msg["template_data"] = template_data
        if extracted_files:
            msg["extracted_files"] = extracted_files
        return msg

    if event.role == "assistant":
        if event.tool_name:
            return {
                "type": "tool_use",
                "tool_name": event.tool_name,
                "tool_input": event.tool_input,
            }
        if event.text:
            return {
                "type": "text",
                "content": event.text,
            }

    if event.role == "user" and event.tool_result:
        return {
            "type": "tool_result",
            "tool_use_id": event.tool_use_id,
            "content": event.tool_result[:2000],
        }

    return None


# --------------- History ---------------

def _extract_description(message: str) -> str:
    """Extract a clean description from the task message."""
    for line in message.split("\n"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        return line[:60]
    return message[:60]


def _extract_report_title(result: str) -> str:
    """Extract the top-level heading from a Markdown report as the history title."""
    for line in result.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            title = re.sub(r'[^\w\u4e00-\u9fff\s—\-()（）]', '', title).strip()
            if title:
                return title[:60]
    return ""


def _save_history(task: QueuedTask, result: str, duration_ms: int, cost_usd: float, tool_count: int, status: str, template_data: dict | None = None, extracted_files: list | None = None) -> str | None:
    """Save task result to history directory. Returns filename on success."""
    try:
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        short_id = task.task_id.split("_")[-1] if "_" in task.task_id else task.task_id[:6]
        filename = f"{ts}_{short_id}.json"

        report_title = _extract_report_title(result)
        desc = _extract_description(task.message)
        display_name = f"{now.strftime('%m-%d %H:%M')} {report_title}" if report_title else f"{now.strftime('%m-%d %H:%M')} {desc}"

        record = {
            "id": task.task_id,
            "name": display_name,
            "message": task.message,
            "description": desc,
            "result": result,
            "status": status,
            "start_time": now.isoformat(),
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "tool_count": tool_count,
        }
        if template_data:
            record["template_data"] = template_data
        if extracted_files:
            record["extracted_files"] = extracted_files

        path = HISTORY_DIR / filename
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("History saved: %s", filename)
        return filename
    except Exception as e:
        logger.error("Failed to save history: %s", e)
        return None


_SCORE_RE = re.compile(r'\[诊断可信度:\s*([\d.]+)\s*/\s*10\s*\]')
_FAIL_KEYWORDS = re.compile(r'诊断失败|未找到日志|未找到.*记录', re.IGNORECASE)


def _extract_score(result: str) -> float | None:
    m = _SCORE_RE.search(result)
    return float(m.group(1)) if m else None


def _load_history(limit: int = 50) -> list[dict]:
    """Load history records, newest first."""
    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:limit]
    records = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result = data.get("result", "")
            score = _extract_score(result)
            has_failure = bool(_FAIL_KEYWORDS.search(result))

            td = data.get("template_data")
            template_id = None
            template_label = None
            phase_statuses = None
            if td and isinstance(td, dict):
                raw_tid = td.get("template")
                template_id = _normalize_template_id(raw_tid) if raw_tid else None
                if template_id:
                    template_label = _TEMPLATE_PHASES.get(template_id, {}).get("label")
                phases = td.get("phases", [])
                if phases and isinstance(phases, list):
                    phase_statuses = [
                        p.get("status", "skipped") for p in phases if isinstance(p, dict)
                    ]

            records.append({
                "id": data.get("id", ""),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "status": data.get("status", ""),
                "start_time": data.get("start_time", ""),
                "duration_ms": data.get("duration_ms", 0),
                "cost_usd": data.get("cost_usd", 0),
                "tool_count": data.get("tool_count", 0),
                "has_result": bool(result),
                "score": score,
                "has_failure": has_failure,
                "file": f.name,
                "template_id": template_id,
                "template_label": template_label,
                "phase_statuses": phase_statuses,
            })
        except Exception:
            continue
    return records


def _load_history_detail(filename: str) -> dict | None:
    """Load a single history record with full result."""
    path = HISTORY_DIR / filename
    if not path.is_file() or not path.suffix == ".json":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data.get("result", "")
        data["score"] = _extract_score(result)
        data["has_failure"] = bool(_FAIL_KEYWORDS.search(result))
        # template_data 已在保存时存入，直接透传（老记录无此字段则为 None）
        data.setdefault("template_data", None)
        data.setdefault("extracted_files", [])
        _ensure_recordings_format(data.get("template_data"))
        return data
    except Exception:
        return None


# --------------- Knowledge Base ---------------

def _parse_knowledge_json(content: str) -> Optional[dict]:
    """Try to extract a JSON object from Claude's knowledge output."""
    json_match = re.search(r'```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```', content)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        start = content.index('{')
        depth = 0
        for i in range(start, len(content)):
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(content[start:i + 1])
    except (ValueError, json.JSONDecodeError):
        pass
    return None


_ERROR_CODE_FILES = {"error-codes.json", "aivoice-error-codes.json"}


def _find_target_knowledge_file(entry: dict) -> Optional[Path]:
    """Match a knowledge entry to an existing JSON knowledge file by scenario/keywords."""
    if not KNOWLEDGE_DIR.is_dir():
        return None

    scenario_id = entry.get("scenario_id", "")

    for fp in KNOWLEDGE_DIR.glob("*.json"):
        if fp.name.startswith("_") or fp.name in _ERROR_CODE_FILES:
            continue
        if scenario_id and fp.stem == scenario_id:
            return fp

    entry_text = json.dumps(entry, ensure_ascii=False).lower()
    best_file = None
    best_score = 0
    for fp in KNOWLEDGE_DIR.glob("*.json"):
        if fp.name.startswith("_") or fp.name in _ERROR_CODE_FILES:
            continue
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                kb = json.load(f)
            keywords = kb.get("keywords", [])
            score = sum(1 for kw in keywords if kw.lower() in entry_text)
            if score > best_score:
                best_score = score
                best_file = fp
        except (json.JSONDecodeError, OSError):
            continue

    return best_file if best_score >= 2 else None


def _save_knowledge(content: str, description: str = "") -> Optional[str]:
    """Parse Claude's knowledge output and append to existing JSON knowledge file."""
    try:
        if not KNOWLEDGE_DIR.is_dir():
            logger.warning("Knowledge dir not found: %s", KNOWLEDGE_DIR)
            return None

        entry = _parse_knowledge_json(content)
        if not entry:
            logger.warning("Failed to parse JSON from knowledge content, saving as markdown fallback")
            now = datetime.now()
            slug = description[:30].strip().replace(" ", "-").replace("/", "-") if description else "auto"
            slug = "".join(c for c in slug if c.isalnum() or c in "-_")
            filename = f"kb_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.md"
            path = KNOWLEDGE_DIR / filename
            path.write_text(content, encoding="utf-8")
            logger.info("Knowledge saved as markdown fallback: %s", filename)
            return filename

        target_file = _find_target_knowledge_file(entry)
        if not target_file:
            logger.warning("No matching knowledge file found for entry, saving as standalone JSON")
            now = datetime.now()
            slug = description[:30].strip().replace(" ", "-").replace("/", "-") if description else "auto"
            slug = "".join(c for c in slug if c.isalnum() or c in "-_")
            filename = f"kb_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.json"
            path = KNOWLEDGE_DIR / filename
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Knowledge saved as standalone JSON: %s", filename)
            return filename

        with open(target_file, 'r', encoding='utf-8') as f:
            kb_data = json.load(f)

        if "known_issues" not in kb_data:
            kb_data["known_issues"] = []

        clean_entry = {k: v for k, v in entry.items() if k != "scenario_id"}
        if "title" not in clean_entry:
            clean_entry["title"] = description or "自动归纳条目"
        clean_entry["_added"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        kb_data["known_issues"].append(clean_entry)
        kb_data.setdefault("_meta", {})["updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(target_file, 'w', encoding='utf-8') as f:
            json.dump(kb_data, f, ensure_ascii=False, indent=2)

        logger.info("Knowledge appended to %s (now %d known_issues)",
                     target_file.name, len(kb_data["known_issues"]))
        return target_file.name

    except Exception as e:
        logger.error("Failed to save knowledge: %s", e)
        return None


async def _git_sync_knowledge(filename: str) -> bool:
    """Commit and push the updated knowledge file to git."""
    try:
        rel_path = f"tools/log-analyzer/knowledge/{filename}"
        cmd = (
            f"cd {_REPO} && "
            f"git add {rel_path} && "
            f"git commit -m 'knowledge: update {filename}' && "
            f"git push"
        )
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_REPO),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            logger.info("Knowledge git sync success: %s", filename)
            return True
        else:
            err = stderr.decode("utf-8", errors="replace").strip()
            logger.warning("Knowledge git sync failed (code=%d): %s", proc.returncode, err[:300])
            return False
    except asyncio.TimeoutError:
        logger.error("Knowledge git sync timeout")
        return False
    except Exception as e:
        logger.error("Knowledge git sync error: %s", e)
        return False


# --------------- Endpoints ---------------

def _extract_sso_token(raw: str) -> str | None:
    """尝试从 Cookie 字符串或裸 Token 中提取 SSO_USER_TOKEN。"""
    _extract = getattr(log_downloader, "extract_sso_user_token_from_cookie_blob", None)
    if _extract:
        return _extract(raw)
    import re
    m = re.search(r"SSO_USER_TOKEN=([^;\s]+)", raw)
    if m:
        return m.group(1)
    if ";" not in raw and "=" not in raw and len(raw) > 10:
        return raw
    return None


def _probe_sso(tok: str) -> tuple[bool, str]:
    """探测 SSO Token 是否有效。"""
    _probe = getattr(log_downloader, "probe_app_log_sso", None)
    if _probe:
        return _probe(tok)
    return True, "probe_app_log_sso not available, accepted without verification"


@app.post("/api/sso-verify")
async def sso_verify(payload: dict):
    """校验 App 日志平台 SSO_USER_TOKEN 并绑定到 web_session_id。"""
    try:
        wid = (payload.get("web_session_id") or "").strip()
        tok = (payload.get("token") or "").strip()
        cookie_blob = (payload.get("cookie") or "").strip()
        if cookie_blob:
            parsed = _extract_sso_token(cookie_blob)
            if not parsed:
                return {"ok": False, "error": "无法从 Cookie 中解析 SSO_USER_TOKEN"}
            tok = parsed
        elif tok and (";" in tok or "SSO_USER_TOKEN" in tok):
            parsed = _extract_sso_token(tok)
            if parsed:
                tok = parsed
        if not wid or not tok:
            return {"ok": False, "error": "缺少 web_session_id、token 或 cookie"}
        ok, msg = _probe_sso(tok)
        if ok:
            sso_token_by_web_session[wid] = tok
            sso_verified_web_sessions.add(wid)
            logger.info("SSO verified for web_session=%s", wid)
            return {"ok": True}
        logger.info("SSO verify failed for web_session=%s: %s", wid, msg[:200])
        return {"ok": False, "error": msg}
    except Exception as e:
        logger.exception("sso_verify error")
        return {"ok": False, "error": f"服务端异常: {str(e)[:200]}"}


@app.get("/api/oauth/app-log/status")
async def oauth_app_log_status():
    return {"enabled": _oauth_app_log_configured()}


@app.get("/api/oauth/app-log/start")
async def oauth_app_log_start(request: Request, web_session_id: str = ""):
    """浏览器跳转 IdP 授权页；state 绑定当前 WS 会话（须在授权开始前保持连接）。"""
    base = _public_base_url(request)
    if not _oauth_app_log_configured():
        return RedirectResponse(url=f"{base}/?oauth_error={quote('OAuth 未配置')}", status_code=302)
    wid = (web_session_id or "").strip()
    if wid not in connected_clients:
        return RedirectResponse(
            url=f"{base}/?oauth_error={quote('无效的 web_session_id，请在本页从「一键登录」重新进入')}",
            status_code=302,
        )
    now = time.monotonic()
    _oauth_prune_store(_oauth_state_store, now)
    state = secrets.token_urlsafe(32)
    _oauth_state_store[state] = (wid, now + OAUTH_STATE_TTL_SEC)
    auth_url = os.environ["APP_LOG_OAUTH_AUTHORIZE_URL"]
    client_id = os.environ["APP_LOG_OAUTH_CLIENT_ID"]
    redirect_uri = os.environ["APP_LOG_OAUTH_REDIRECT_URI"]
    scope = (os.environ.get("APP_LOG_OAUTH_SCOPE") or "").strip()
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scope:
        params["scope"] = scope
    extra = (os.environ.get("APP_LOG_OAUTH_EXTRA_PARAMS") or "").strip()
    if extra:
        try:
            for k, v in json.loads(extra).items():
                if isinstance(k, str) and isinstance(v, str):
                    params[k] = v
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("APP_LOG_OAUTH_EXTRA_PARAMS 不是合法 JSON 对象，已忽略")
    sep = "&" if "?" in auth_url else "?"
    url = f"{auth_url}{sep}{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@app.get("/api/oauth/app-log/callback")
async def oauth_app_log_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    base = _public_base_url(request)
    if error:
        msg = (error_description or error or "OAuth 错误")[:500]
        return RedirectResponse(url=f"{base}/?oauth_error={quote(msg)}", status_code=302)
    if not code or not state:
        return RedirectResponse(url=f"{base}/?oauth_error={quote('缺少 code 或 state')}", status_code=302)
    now = time.monotonic()
    _oauth_prune_store(_oauth_state_store, now)
    row = _oauth_state_store.pop(state, None)
    if not row or row[1] < now:
        return RedirectResponse(url=f"{base}/?oauth_error={quote('state 无效或已过期')}", status_code=302)
    token_json_field = (os.environ.get("APP_LOG_OAUTH_TOKEN_JSON_FIELD") or "").strip()
    try:
        data = await asyncio.to_thread(_oauth_exchange_code_sync, code)
    except Exception as e:
        logger.exception("OAuth token 交换失败: %s", e)
        return RedirectResponse(url=f"{base}/?oauth_error={quote(str(e)[:200])}", status_code=302)
    if not isinstance(data, dict):
        return RedirectResponse(url=f"{base}/?oauth_error={quote('Token 接口返回非 JSON 对象')}", status_code=302)
    sso_tok = _oauth_extract_token_from_json(data, token_json_field)
    if not sso_tok:
        return RedirectResponse(url=f"{base}/?oauth_error={quote('响应中未找到 SSO Token')}", status_code=302)
    bridge = secrets.token_urlsafe(24)
    _oauth_prune_store(_oauth_bridge_store, now)
    _oauth_bridge_store[bridge] = (sso_tok, now + OAUTH_BRIDGE_TTL_SEC)
    return RedirectResponse(url=f"{base}/?oauth_bridge={quote(bridge)}", status_code=302)


@app.post("/api/sso-bridge-claim")
async def sso_bridge_claim(payload: dict):
    """OAuth 重载页面后，用一次性 bridge 将 Token 绑定到新的 web_session_id。"""
    bridge = (payload.get("bridge_token") or payload.get("oauth_bridge") or "").strip()
    wid = (payload.get("web_session_id") or "").strip()
    if not bridge or not wid:
        return {"ok": False, "error": "缺少 bridge_token 或 web_session_id"}
    now = time.monotonic()
    _oauth_prune_store(_oauth_bridge_store, now)
    row = _oauth_bridge_store.pop(bridge, None)
    if not row or row[1] < now:
        return {"ok": False, "error": "领取链接无效或已过期，请重新一键登录"}
    sso_tok, _ = row
    ok, msg = log_downloader.probe_app_log_sso(sso_tok)
    if not ok:
        return {"ok": False, "error": msg}
    sso_token_by_web_session[wid] = sso_tok
    sso_verified_web_sessions.add(wid)
    logger.info("OAuth bridge claimed for web_session=%s", wid)
    return {"ok": True}


@app.get("/api/fetch-ticket")
async def fetch_ticket_api(ticket_id: str):
    """Fetch Socrates ticket info and extract diagnosis params.

    If an account is found but no UID, automatically looks up the UID
    via backendng API.
    """
    if not ticket_id or not ticket_id.strip():
        return {"error": "请输入工单 ID"}

    try:
        from ticket_fetcher import (
            parse_ticket_id,
            fetch_ticket_detail,
            extract_plain_text,
            extract_diagnosis_params,
        )

        pid = parse_ticket_id(ticket_id.strip())
        detail = fetch_ticket_detail(pid)

        content_json = detail.get("problemContent", "")
        plain_text = extract_plain_text(content_json)
        params = extract_diagnosis_params(plain_text)

        account = params.get("account")
        region = params.get("region")
        uid = params.get("uid")
        uid_source = None
        uid_lookup_msg = None

        if uid:
            uid_source = "ticket"
        elif account:
            try:
                looked_up_uid = _lookup_uid_by_account(account, region)
                if looked_up_uid:
                    uid = looked_up_uid
                    uid_source = "account_lookup"
                    logger.info("UID resolved from account %s: %s", account, uid)
                else:
                    uid_lookup_msg = f"通过账号 {account} 未查到 UID（可能是行业平台账号，不在消费者 backendng 中）"
                    logger.info("UID lookup returned empty for account %s", account)
            except Exception as e:
                uid_lookup_msg = f"UID 查询失败: {e}"
                logger.warning("UID lookup failed for account %s: %s", account, e)

        return {
            "success": True,
            "ticket_id": pid,
            "title": detail.get("title", ""),
            "customer": detail.get("customerName", ""),
            "biz_line": detail.get("bizLineName", ""),
            "state": detail.get("state"),
            "creator": detail.get("creatorPerson", {}).get("personName", ""),
            "solver": detail.get("solverStaffPerson", {}).get("personName", ""),
            "create_time": detail.get("createTime", ""),
            "problem_text": plain_text,
            "uid_lookup_msg": uid_lookup_msg,
            "params": {
                "account": account,
                "uid": uid,
                "uid_source": uid_source,
                "region": region,
                "pid": params.get("pid"),
                "device_id": params.get("device_id"),
                "app_version": params.get("app_version"),
                "sdk_version": params.get("sdk_version"),
                "client_id": params.get("client_id"),
                "platform": params.get("platform"),
            },
        }
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("fetch-ticket error: %s", e)
        return {"error": f"获取工单失败: {e}"}


def _lookup_uid_by_account(account: str, region: str | None = None) -> str | None:
    """Look up UID from account (email/phone) via backendng API."""
    from log_downloader import (
        detect_account_type,
        fetch_app_infos,
        uid_for_app,
    )

    acct_type = detect_account_type(account)
    if acct_type not in ("email", "mobile"):
        return None

    url_region, app_infos = fetch_app_infos(
        account, region or "cn", acct_type,
    )

    if not app_infos:
        return None

    try:
        uid, _ = uid_for_app(account, url_region, acct_type, app_infos[0])
        return uid or None
    except (ValueError, Exception):
        return None


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    original_name = (file.filename or "").strip()
    if not original_name:
        return {"error": "文件名不能为空"}

    # Strip any directory component from the filename (security + prevents write to missing subdir)
    original_name = Path(original_name).name
    if not original_name:
        return {"error": "无效的文件名"}

    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"error": f"不支持的文件类型: {ext}，允许: {', '.join(ALLOWED_EXTENSIONS)}"}

    try:
        content = await file.read()
    except Exception as e:
        logger.exception("Upload read error: %s", e)
        return {"error": f"读取文件失败: {e}"}

    if len(content) > MAX_FILE_SIZE:
        return {"error": f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制"}

    try:
        safe_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
        save_path = UPLOAD_DIR / safe_name
        save_path.write_bytes(content)
        rel_path = str(save_path.relative_to(Path(WORKSPACE)))
    except Exception as e:
        logger.exception("Upload save error: %s", e)
        return {"error": f"保存文件失败: {e}"}

    logger.info("File uploaded: %s -> %s", original_name, rel_path)
    return {"filename": original_name, "path": rel_path}


@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    web_session_id = str(uuid.uuid4())
    connected_clients[web_session_id] = ws
    logger.info("WebSocket connected: %s", web_session_id)

    try:
        await ws.send_json({"type": "hello", "web_session_id": web_session_id})
        await broadcast_queue_status()

        while True:
            data = await ws.receive_json()
            action = data.get("action", "analyze")

            if action == "set_sso":
                tok = (data.get("token") or "").strip()
                cookie_blob = (data.get("cookie") or "").strip()
                if cookie_blob:
                    parsed = log_downloader.extract_sso_user_token_from_cookie_blob(cookie_blob)
                    if not parsed:
                        await ws.send_json({"type": "error", "content": "无法从 Cookie 解析 SSO_USER_TOKEN"})
                        continue
                    tok = parsed
                elif tok and (";" in tok or "SSO_USER_TOKEN" in tok):
                    parsed = log_downloader.extract_sso_user_token_from_cookie_blob(tok)
                    if parsed:
                        tok = parsed
                if not tok:
                    await ws.send_json({"type": "error", "content": "SSO_USER_TOKEN 为空"})
                    continue
                ok, msg = log_downloader.probe_app_log_sso(tok)
                if ok:
                    sso_token_by_web_session[web_session_id] = tok
                    sso_verified_web_sessions.add(web_session_id)
                    await ws.send_json({"type": "sso_ok"})
                else:
                    await ws.send_json({"type": "error", "content": f"日志平台验证失败: {msg}"})
                continue

            if action == "stop":
                stop_id = data.get("task_id", "")
                if stop_id and stop_id in pending_tasks:
                    pending_tasks[stop_id].cancelled = True
                    if runner is not None:
                        runner.cancel(stop_id)
                    logger.info("Stop requested: task=%s by session=%s", stop_id, web_session_id)
                else:
                    for tid, t in list(pending_tasks.items()):
                        if t.web_session_id == web_session_id and not t.cancelled:
                            t.cancelled = True
                            if runner is not None:
                                runner.cancel(tid)
                            logger.info("Stop requested: task=%s by session=%s", tid, web_session_id)
                try:
                    await ws.send_json({"type": "stopped"})
                except Exception:
                    pass
                continue

            user_message = data.get("message", "")
            uploaded_file = data.get("file_path", "")
            template_raw = data.get("template", "auto")
            template = _normalize_template_id(
                str(template_raw) if template_raw is not None else "auto"
            )
            if not user_message:
                continue

            if action == "knowledge":
                if runner is None:
                    await ws.send_json({
                        "type": "error",
                        "content": "当前环境未启用 Claude，无法使用知识归纳。",
                    })
                    continue
                c_session = claude_sessions.get(web_session_id)
                if not c_session:
                    await ws.send_json({"type": "error", "content": "没有可用的对话上下文，请先完成一次诊断分析"})
                    continue
                logger.info("Knowledge request session=%s claude_session=%s", web_session_id, c_session)
                kb_task_id = f"kb_{uuid.uuid4().hex[:6]}"
                kb_extra = _extra_env_for_web_session(web_session_id)
                try:
                    result_text = ""
                    evt_count = 0
                    async for event in runner.run(
                        user_message,
                        session_id=c_session,
                        task_id=kb_task_id,
                        extra_env=kb_extra,
                    ):
                        evt_count += 1
                        logger.info(
                            "KB Event#%d task=%s: type=%s role=%s is_result=%s text_len=%d tool=%s",
                            evt_count, kb_task_id, event.event_type, event.role,
                            event.is_result, len(event.text), event.tool_name,
                        )
                        if event.is_result:
                            result_text = event.text
                            if event.session_id:
                                claude_sessions[web_session_id] = event.session_id
                        elif event.role == "assistant":
                            if event.tool_name:
                                try:
                                    await ws.send_json({"type": "knowledge_progress", "tool_name": event.tool_name})
                                except Exception:
                                    pass
                            elif event.text:
                                result_text += event.text
                                try:
                                    await ws.send_json({"type": "knowledge_progress", "content": event.text[:200]})
                                except Exception:
                                    pass
                    logger.info("KB task=%s done, %d events, result_len=%d", kb_task_id, evt_count, len(result_text))

                    git_synced = False
                    if result_text.strip():
                        desc = _extract_description(user_message)
                        kb_file = _save_knowledge(result_text, desc)
                        if kb_file:
                            try:
                                await ws.send_json({"type": "knowledge_progress", "content": "正在同步到 Git 仓库..."})
                            except Exception:
                                pass
                            git_synced = await _git_sync_knowledge(kb_file)

                    await ws.send_json({"type": "knowledge_result", "content": result_text, "git_synced": git_synced})
                except Exception as e:
                    logger.exception("Knowledge task error task=%s: %s", kb_task_id, e)
                    try:
                        await ws.send_json({"type": "error", "content": f"归纳失败: {e}"})
                    except Exception:
                        pass
                continue

            if uploaded_file:
                user_message = f"请分析日志文件 {uploaded_file}。\n{user_message}"

            task_id = f"{web_session_id}_{uuid.uuid4().hex[:6]}"
            task = QueuedTask(
                task_id=task_id,
                web_session_id=web_session_id,
                message=user_message,
                ws=ws,
                template=template,
            )
            pending_tasks[task_id] = task
            queue_order.append(task_id)
            await task_queue.put(task)

            position = len(queue_order)
            await ws.send_json({
                "type": "queued",
                "task_id": task_id,
                "position": position,
            })
            logger.info("Task queued: %s position=%d", task_id, position)
            await broadcast_queue_status()

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", web_session_id)
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        connected_clients.pop(web_session_id, None)
        sso_token_by_web_session.pop(web_session_id, None)
        sso_verified_web_sessions.discard(web_session_id)


@app.get("/api/queue")
async def get_queue():
    return {"queue": [
        {"task_id": tid, "session_id": pending_tasks[tid].web_session_id, "message": pending_tasks[tid].message[:80]}
        for tid in queue_order if tid in pending_tasks
    ]}


@app.get("/api/history")
async def get_history(limit: int = 50):
    return {"history": _load_history(limit)}


@app.get("/api/history/{filename}")
async def get_history_detail(filename: str):
    record = _load_history_detail(filename)
    if record is None:
        return {"error": "记录不存在"}
    return record


@app.delete("/api/history/{filename}")
async def delete_history(filename: str):
    path = HISTORY_DIR / filename
    if not path.is_file() or not path.suffix == ".json":
        return {"error": "记录不存在"}
    try:
        path.unlink()
        logger.info("History deleted: %s", filename)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


_ALLOWED_EXTRACTED_PREFIX = str((_REPO / "tools" / "log-analyzer" / "data").resolve())


@app.get("/api/extracted-file")
async def get_extracted_file(path: str, dl: int = 0):
    """Return content of an extracted log file, or trigger download."""
    # Security: reject path traversal and absolute paths
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




_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
_STATIC_LEGACY = Path(__file__).parent / "static"
# Vite emits hashed filenames under /assets; keep index.html uncached so new deploys are picked up.
_SPA_INDEX_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

app.mount("/static", StaticFiles(directory=str(_STATIC_LEGACY)), name="static")


@app.get("/")
async def index():
    if _FRONTEND_DIST.is_dir() and (_FRONTEND_DIST / "index.html").exists():
        return FileResponse(str(_FRONTEND_DIST / "index.html"), headers=_SPA_INDEX_HEADERS)
    return FileResponse(str(_STATIC_LEGACY / "index.html"), headers=_SPA_INDEX_HEADERS)
