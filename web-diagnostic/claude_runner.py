from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import sys
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

_CLAUDE_SEARCH_PATHS = [
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    Path.home() / ".local" / "bin" / "claude",
    Path.home() / ".npm-global" / "bin" / "claude",
]

_ANSI_RE = re.compile(
    r"(\x1b\[[0-9;?]*[a-zA-Z]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    r"|\r)"
)


def _find_claude_binary() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for p in _CLAUDE_SEARCH_PATHS:
        p = Path(p)
        if p.is_file() and p.stat().st_mode & 0o111:
            return str(p)
    raise FileNotFoundError(
        "claude CLI 未找到。请确认已安装并在 PATH 中，或位于 /opt/homebrew/bin/"
    )


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).strip()


@dataclass
class StreamEvent:
    """Parsed stream-json event from Claude Code CLI."""
    raw: dict
    event_type: str = ""
    role: str = ""
    text: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_use_id: str = ""
    tool_result: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_result: bool = False

    @classmethod
    def parse(cls, data: dict) -> "StreamEvent":
        evt = cls(raw=data)
        evt.event_type = data.get("type", "")

        if evt.event_type == "result":
            evt.is_result = True
            evt.session_id = data.get("session_id", "")
            evt.cost_usd = data.get("total_cost_usd", 0.0)
            evt.duration_ms = data.get("duration_ms", 0)
            evt.text = data.get("result", "")
            return evt

        msg = data.get("message", data)
        evt.role = msg.get("role", "") or data.get("role", "")
        evt.session_id = data.get("session_id", "")

        for block in msg.get("content", []):
            block_type = block.get("type", "")
            if block_type == "text":
                evt.text += block.get("text", "")
            elif block_type == "tool_use":
                evt.tool_name = block.get("name", "")
                evt.tool_input = block.get("input", {})
                evt.tool_use_id = block.get("id", "")
            elif block_type == "tool_result":
                evt.tool_use_id = block.get("tool_use_id", "")
                content = block.get("content", "")
                evt.tool_result = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

        return evt


class ClaudeRunner:
    """Wraps Claude Code CLI with `script -q /dev/null` for TTY allocation."""

    SYSTEM_PROMPT = (
        "你是 IoT SDK 日志诊断系统，同时支持 DeviceCore 和 AIVoice（AIBuds）两个团队的日志分析。\n"
        "收到请求后直接开始工作。禁止自我介绍、问候、列出能力清单、过程性描述。\n\n"
        "## 判断诊断类型\n"
        "根据用户描述判断是 **DeviceCore** 还是 **AIVoice** 场景：\n"
        "- **AIVoice**：涉及录音、转写、翻译、ASR、TTS、面对面翻译、电话翻译、文件传输(AP)、云同步上传、AIBuds 等关键词\n"
        "- **DeviceCore**：涉及 BLE 配网、MQTT、OTA、设备控制、离线、网络连接等关键词\n"
        "- 未明确时默认 DeviceCore 流程\n\n"
        "## 工作流程\n"
        "1. 如果已有日志文件路径 → 直接进入步骤 3\n"
        "2. 需要下载日志：search_logs → 检查结果\n"
        "   - 如果搜索到日志记录 → download_log 下载\n"
        "   - **如果搜索结果为 0 条 → 立即停止，输出错误报告（见下方「无日志处理」）**\n"
        "3. 分析入口：\n"
        "   - **AIVoice 场景**：先调用 extract_aibuds_logs 提取 AIBuds 日志 → 再调用 diagnose_scenario（scenario 传问题描述）\n"
        "   - **DeviceCore 场景**：调用 quick_diagnosis（传入 problem 参数）\n"
        "4. 看诊断结果：\n"
        "   - 如果输出了'知识库匹配'和'命中已知问题' → 结论已充分，直接基于结果写报告\n"
        "   - DeviceCore：如果没有知识库命中 → 可用 Read 读取源码文件路径做验证\n"
        "   - AIVoice：不需要读取源码，直接基于知识库分析\n"
        "5. 诊断工具只需调用一次，禁止重复调用\n\n"
        "## 无日志处理（严格执行）\n"
        "当 search_logs 返回 0 条结果时，禁止继续调用 download_log 或诊断工具。\n"
        "必须立即输出错误报告并结束：\n"
        "# 诊断失败 — 未找到日志\n"
        "说明搜索条件和失败原因，给出建议。\n"
        "[诊断可信度: 0/10]\n\n"
        "## 注意事项\n"
        "- 禁止用 Read 直接读取日志原始文件（文件过大会失败），日志内容已在诊断结果中\n"
        "- Read 只用于读取源码文件（.java/.kt），且必须带 offset/limit 参数定位到具体行\n\n"
        "## 报告格式\n"
        "最终用中文输出诊断报告。\n"
        "报告最末尾单独一行：[诊断可信度: X.X/10]\n"
        "评分：命中已知问题且日志充分 8-10，有日志但原因需推测 5-7，缺少关键日志 1-4。"
    )

    def __init__(self, workspace: str, allowed_tools: list[str] | None = None):
        self.workspace = workspace
        self.allowed_tools = allowed_tools or [
            "mcp__log-analyzer__search_logs",
            "mcp__log-analyzer__download_log",
            "mcp__log-analyzer__quick_diagnosis",
            "mcp__log-analyzer__diagnose_scenario",
            "mcp__log-analyzer__extract_aibuds_logs",
            "mcp__log-analyzer__error_code_lookup",
            "mcp__log-analyzer__tag_lookup",
            "Read", "Grep", "Glob",
        ]
        self.disallowed_tools = [
            "Bash", "Edit", "Write", "NotebookEdit",
            "WebFetch", "Task", "TaskOutput", "TaskStop",
            "mcp__log-analyzer__filter_logs",
            "mcp__log-analyzer__error_context",
            "mcp__log-analyzer__scenario_timeline",
            "mcp__log-analyzer__log_summary",
            "mcp__log-analyzer__build_tag_index",
            "mcp__log-analyzer__refresh_tag_index",
            "mcp__log-analyzer__search_related_tags",
        ]
        self._claude_bin = _find_claude_binary()
        self._active_procs: dict[str, asyncio.subprocess.Process] = {}
        logger.info("Claude CLI: %s", self._claude_bin)

    def _use_claude_bare(self) -> bool:
        """When True, pass --bare (skips auto-loaded MCP; pair with --mcp-config)."""
        v = os.environ.get("WEB_DIAGNOSTIC_CLAUDE_BARE", "").strip().lower()
        return v in ("1", "true", "yes", "on")

    def _explicit_mcp_config_args(self) -> list[str]:
        """
        Pass absolute --mcp-config so log-analyzer registers under headless -p:
        some CLI builds skip project / managed MCP without an explicit file.
        Set WEB_DIAGNOSTIC_SKIP_EXPLICIT_MCP_CONFIG=1 to disable (e.g. if duplicate).
        """
        skip = os.environ.get("WEB_DIAGNOSTIC_SKIP_EXPLICIT_MCP_CONFIG", "").strip().lower()
        if skip in ("1", "true", "yes", "on"):
            return []
        mcp_path = Path(self.workspace).resolve() / ".mcp.json"
        if not mcp_path.is_file():
            return []
        return ["--mcp-config", str(mcp_path)]

    def cancel(self, task_id: str):
        proc = self._active_procs.pop(task_id, None)
        if proc and proc.returncode is None:
            logger.info("Cancelling Claude process task=%s pid=%s", task_id, proc.pid)
            proc.terminate()

    def _build_shell_command(self, prompt_file: str, session_id: str | None = None) -> str:
        """Build shell command that reads prompt from a temp file."""
        args = [self._claude_bin]
        if self._use_claude_bare():
            args.append("--bare")
        args.extend(
            [
                "-p",
                f"$(cat {shlex.quote(prompt_file)})",
                "--verbose",
                "--output-format", "stream-json",
                "--system-prompt", self.SYSTEM_PROMPT,
            ]
        )
        for tool in self.allowed_tools:
            args.extend(["--allowedTools", tool])
        for tool in self.disallowed_tools:
            args.extend(["--disallowedTools", tool])
        args.extend(self._explicit_mcp_config_args())
        if session_id:
            args.extend(["--resume", session_id])

        parts = []
        for a in args:
            if a.startswith("$(cat "):
                parts.append(f'"{a}"')
            else:
                parts.append(shlex.quote(a))
        inner = " ".join(parts)

        env_setup = (
            'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi; '
        )
        wrapped = env_setup + inner
        q = shlex.quote(wrapped)
        # BSD/macOS: script [file [command ...]] — Linux util-linux 用 -c，否则报
        # "script: unexpected number of arguments".
        if sys.platform == "darwin":
            return f"script -q /dev/null bash -c {q}"
        return f"script -q -c {q} /dev/null"

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        task_id: str = "",
        extra_env: dict[str, str] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        prompt_fd, prompt_path = tempfile.mkstemp(suffix=".txt", prefix="claude_prompt_")
        try:
            os.write(prompt_fd, prompt.encode("utf-8"))
            os.close(prompt_fd)
        except Exception:
            os.close(prompt_fd)
            os.unlink(prompt_path)
            raise

        shell_cmd = self._build_shell_command(prompt_path, session_id)
        logger.info("Running task=%s prompt_len=%d cmd_len=%d", task_id, len(prompt), len(shell_cmd))

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        if extra_env:
            env.update(extra_env)

        try:
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                env=env,
                limit=20 * 1024 * 1024,
            )
            if task_id:
                self._active_procs[task_id] = proc
        except Exception as e:
            os.unlink(prompt_path)
            raise RuntimeError(f"启动 claude 进程失败: {e}")

        stderr_parts: list[bytes] = []

        async def _drain_stderr() -> None:
            while True:
                chunk = await proc.stderr.read(65536)
                if not chunk:
                    break
                stderr_parts.append(chunk)

        drain_task = asyncio.create_task(_drain_stderr())
        parsed_count = 0
        non_json_preview: list[str] = []
        try:
            async for raw_line in proc.stdout:
                text = raw_line.decode("utf-8", errors="replace")
                text = _strip_ansi(text)
                if not text:
                    continue
                try:
                    data = json.loads(text)
                    parsed_count += 1
                    yield StreamEvent.parse(data)
                except json.JSONDecodeError:
                    if len(non_json_preview) < 5:
                        non_json_preview.append(text[:400])
                    logger.debug("Non-JSON: %s", text[:150])

            rc = await proc.wait()
            try:
                await asyncio.wait_for(drain_task, timeout=60)
            except asyncio.TimeoutError:
                logger.warning("stderr drain timeout for task=%s", task_id)
                drain_task.cancel()
            err_raw = b"".join(stderr_parts).decode("utf-8", errors="replace")
            err_text = err_raw.strip()
            if rc is not None and rc != 0:
                if err_text:
                    logger.error("Claude exit %d: %s", rc, err_text[:500])
                    raise RuntimeError(f"Claude 异常退出 (code={rc}): {err_text[:300]}")
                raise RuntimeError(f"Claude 异常退出 (code={rc})，stderr 为空")
            if err_text:
                # 退出码 0 时常见：鉴权/网关提示只在 stderr，stdout 无 stream-json → Web 侧 0 events
                logger.warning("Claude stderr (exit=%s, task=%s): %s", rc, task_id, err_text[:2000])
            if parsed_count == 0:
                stderr_nbytes = sum(len(x) for x in stderr_parts)
                logger.warning(
                    "Claude 未解析到 stream-json 行（task=%s exit=%s stderr_bytes=%d stderr_preview=%s "
                    "non_json_stdout_lines=%s",
                    task_id,
                    rc,
                    stderr_nbytes,
                    repr(err_raw[:800]),
                    non_json_preview,
                )
        finally:
            self._active_procs.pop(task_id, None)
            if not drain_task.done():
                drain_task.cancel()
                try:
                    await drain_task
                except asyncio.CancelledError:
                    pass
            try:
                os.unlink(prompt_path)
            except OSError:
                pass
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()


def try_create_claude_runner(
    workspace: str, allowed_tools: list[str] | None = None
) -> ClaudeRunner | None:
    """
    Return ClaudeRunner if Claude CLI is available; otherwise None.
    Set WEB_DIAGNOSTIC_SKIP_CLAUDE=1 to disable without probing PATH.
    """
    flag = os.environ.get("WEB_DIAGNOSTIC_SKIP_CLAUDE", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        logger.warning("WEB_DIAGNOSTIC_SKIP_CLAUDE set; Claude runner disabled")
        return None
    try:
        return ClaudeRunner(workspace=workspace, allowed_tools=allowed_tools)
    except FileNotFoundError as e:
        logger.warning("Claude CLI not available: %s", e)
        return None
