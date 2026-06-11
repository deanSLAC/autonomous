"""Subprocess client for `claude -p` (Anthropic's claude code CLI).

`claude -p` is a one-shot per turn — there is no persistent server. Each
call subprocess-spawns claude code, feeds the user message via stdin
(`--input-format stream-json`), receives JSONL events on stdout
(`--output-format stream-json`), and exits. We persist `session_id`
across turns to keep the conversation continuous via `--resume`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from orchestration.messages import ToolCallRecord
from orchestration.config import (
    PROJECT_ROOT,
    LLM_GATEWAY,
    PROJECT_ROOT,
    gateway_config,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Assistant reply from one agent turn."""
    text: str
    images: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    session_id: Optional[str] = None
    thoughts: list[str] = field(default_factory=list)
    usage: Optional[dict] = None       # claude stream-json result.usage
    cost_usd: Optional[float] = None   # claude stream-json result.total_cost_usd


_IMAGE_PATH_RE = re.compile(r'(?:plot_path|image_path|png_path)"\s*:\s*"([^"]+)"')


def _extract_image_paths(texts: list[str]) -> list[str]:
    """Scan tool-result payload strings for generated plot paths."""
    paths: list[str] = []
    for t in texts or []:
        if isinstance(t, str):
            for mo in _IMAGE_PATH_RE.finditer(t):
                paths.append(mo.group(1))
    return paths


CLAUDE_BIN = os.getenv("CLAUDE_BIN", shutil.which("claude") or "claude")
# CLAUDE_MODEL, when set, overrides whatever model the active gateway
# would otherwise pin. Useful for one-off A/B testing of model versions.
_CLAUDE_MODEL_OVERRIDE = os.getenv("CLAUDE_MODEL")

# A claude -p turn that drives the full alignment + collection pipeline can
# legitimately run for hours. We do not impose a timeout — if the user wants
# to abort, they call `abort()` which signals the subprocess.
_NO_TIMEOUT = None


@dataclass
class _Accumulator:
    """Build an AgentResult while streaming claude code's stream-json."""

    session_id: Optional[str] = None
    final_text: str = ""
    assistant_chunks: list[str] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    tool_calls_by_id: dict[str, dict] = field(default_factory=dict)
    tool_calls_order: list[str] = field(default_factory=list)
    raw_events: list[dict] = field(default_factory=list)
    usage: Optional[dict] = None
    cost_usd: Optional[float] = None


def _truncate(s: str, limit: int = 4000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} chars]"


def _stringify(val: Any) -> str:
    if isinstance(val, str):
        return val
    try:
        return json.dumps(val, default=str)
    except Exception:  # noqa: BLE001
        return str(val)


def _content_blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, list):
        return [c for c in content if isinstance(c, dict)]
    return []


def _extract_text_from_content(content: list[dict]) -> str:
    chunks: list[str] = []
    for block in content:
        if block.get("type") == "text":
            t = block.get("text") or ""
            if t:
                chunks.append(t)
    return "\n".join(chunks).strip()


def _ingest_event(acc: _Accumulator, event: dict) -> None:
    """Update the accumulator with one stream-json event from claude -p."""
    acc.raw_events.append(event)
    et = event.get("type")
    sid = event.get("session_id")
    if sid and not acc.session_id:
        acc.session_id = sid

    if et == "assistant":
        msg = event.get("message") or {}
        for block in _content_blocks(msg):
            bt = block.get("type")
            if bt == "text":
                t = block.get("text") or ""
                if t:
                    acc.assistant_chunks.append(t)
            elif bt == "thinking":
                t = block.get("thinking") or block.get("text") or ""
                if isinstance(t, str) and t.strip():
                    acc.thoughts.append(t)
            elif bt == "tool_use":
                tid = block.get("id")
                if not tid:
                    continue
                name = block.get("name") or "?"
                inp = block.get("input") or {}
                entry = {
                    "id": tid,
                    "name": name,
                    "input": inp,
                    "output": "",
                    "status": "running",
                }
                if tid not in acc.tool_calls_by_id:
                    acc.tool_calls_order.append(tid)
                acc.tool_calls_by_id[tid] = entry
        return

    if et == "user":
        # Tool results are echoed back as user-role messages.
        msg = event.get("message") or {}
        for block in _content_blocks(msg):
            if block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            if not tid:
                continue
            content = block.get("content")
            if isinstance(content, list):
                # claude code wraps tool result in [{"type": "text", "text": "..."}]
                content = "\n".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            output_str = _stringify(content)
            entry = acc.tool_calls_by_id.get(tid) or {
                "id": tid, "name": "?", "input": {}, "output": "", "status": "completed",
            }
            entry["output"] = _truncate(output_str)
            entry["status"] = "error" if block.get("is_error") else "completed"
            if tid not in acc.tool_calls_order:
                acc.tool_calls_order.append(tid)
            acc.tool_calls_by_id[tid] = entry
        return

    if et == "result":
        # Final wrap-up. claude code provides the canonical final assistant
        # text under .result; fall back to accumulated assistant chunks.
        result_text = event.get("result")
        if isinstance(result_text, str) and result_text:
            acc.final_text = result_text
        usage = event.get("usage")
        if isinstance(usage, dict):
            acc.usage = usage
        cost = event.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            acc.cost_usd = float(cost)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ClaudeCodeClient:
    """Subprocess-based adapter for the `claude -p` headless CLI."""

    def __init__(self, session_id: str | None = None) -> None:
        gw = gateway_config()
        self.session_id: Optional[str] = session_id
        self.model = gw["model_alias"] or LLM_GATEWAY
        # CLAUDE_MODEL env overrides the gateway's --model alias if set.
        self._claude_model_alias: Optional[str] = (
            _CLAUDE_MODEL_OVERRIDE or gw["model_alias"]
        )
        self._gateway_url = gw["url"]
        self._gateway_key = gw["key"]
        self._gateway_env: dict = dict(gw.get("env") or {})
        self._gateway_name = LLM_GATEWAY
        self._initialized: bool = bool(session_id)
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()

    # ---- Connectivity -------------------------------------------------

    def health_check(self) -> bool:
        """True iff the `claude` binary is invokable. There is no server
        to ping — the subprocess model means every call is its own check."""
        if not CLAUDE_BIN:
            return False
        try:
            r = subprocess.run(
                [CLAUDE_BIN, "--version"],
                capture_output=True, timeout=10, check=False,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("claude --version failed: %s", e)
            return False

    # ---- Session management ------------------------------------------

    def ensure_session(self) -> str:
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
            self._initialized = False
        return self.session_id

    def reset_session(self) -> str:
        self.session_id = None
        self._initialized = False
        return self.ensure_session()

    def abort(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception as e:  # noqa: BLE001
            logger.warning("claude subprocess terminate failed: %s", e)

    # ---- Send + read --------------------------------------------------

    def _build_argv(self, sid: str) -> list[str]:
        base_layer = str(PROJECT_ROOT / ".claude" / "prompts" / "base-layer.md")
        args = [
            CLAUDE_BIN, "--agent", "chat", "-p",
            "--append-system-prompt-file", base_layer,
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--include-partial-messages",  # ensures we see thinking + tool blocks
            "--verbose",                   # required for stream-json
        ]
        if self._claude_model_alias:
            args.extend(["--model", self._claude_model_alias])
        if self._initialized:
            args.extend(["--resume", sid])
        else:
            args.extend(["--session-id", sid])
        return args

    def _stream_json_user_msg(self, text: str) -> str:
        """Wrap a user prompt in claude code's stream-json input shape."""
        return json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }) + "\n"

    def send(self, text: str) -> AgentResult:
        sid = self.ensure_session()
        argv = self._build_argv(sid)
        env = dict(os.environ)
        # Make sure the `beamtimehero` script is reachable. start.sh symlinks
        # it into venv/bin; for ad-hoc dev runs, prepend scripts/ to PATH.
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in env.get("PATH", ""):
            env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
        # Route claude code through the configured gateway. When LLM_GATEWAY
        # is "default" the url/key/env are all empty and we leave the parent
        # env in place — claude code uses whatever auth it has on disk.
        if self._gateway_url:
            env["ANTHROPIC_BASE_URL"] = self._gateway_url
        if self._gateway_key:
            env["ANTHROPIC_AUTH_TOKEN"] = self._gateway_key
        # Apply the gateway's env block (model defaults, beta-feature gates,
        # prompt-caching toggles). Mirrors what each gateway needs in the
        # user's ~/.claude/settings.json today.
        for k, v in self._gateway_env.items():
            env[k] = v

        logger.debug("claude argv: %s", " ".join(argv[:14]) + " …")
        with self._proc_lock:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
                env=env,
                text=True,
                bufsize=1,
            )

        proc = self._proc
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(self._stream_json_user_msg(text))
            proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError as e:
            logger.error("claude stdin write failed: %s", e)

        acc = _Accumulator()
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("non-JSON line from claude -p: %s", line[:200])
                continue
            try:
                _ingest_event(acc, event)
            except Exception as e:  # noqa: BLE001
                logger.warning("event ingest failed: %s", e)

        rc = proc.wait(timeout=_NO_TIMEOUT)
        stderr_tail = ""
        if proc.stderr is not None:
            try:
                stderr_tail = proc.stderr.read()
            except Exception:  # noqa: BLE001
                stderr_tail = ""
        with self._proc_lock:
            self._proc = None

        # Any session_id we observed is now the canonical one.
        if acc.session_id:
            self.session_id = acc.session_id
        # First successful call promotes us into "resume" mode.
        if rc == 0:
            self._initialized = True

        if rc != 0:
            err = (stderr_tail or "")[:600]
            logger.error("claude -p exited with rc=%d: %s", rc, err)

        # Finalize text: prefer the explicit result event, else accumulated chunks.
        final_text = acc.final_text or "\n".join(acc.assistant_chunks).strip()
        if not final_text and rc != 0:
            final_text = f"Error: claude -p exited with rc={rc}: {stderr_tail[:300]}"

        # Validate/normalize each record against the shared contract so
        # MLflow logs and viewers never see a drifted shape.
        tool_calls = [
            ToolCallRecord.model_validate(acc.tool_calls_by_id[tid]).model_dump()
            for tid in acc.tool_calls_order
        ]
        images = _extract_image_paths([tc.get("output") or "" for tc in tool_calls])

        return AgentResult(
            text=final_text,
            images=images,
            tool_calls=tool_calls,
            messages=acc.raw_events,
            session_id=self.session_id,
            thoughts=acc.thoughts,
            usage=acc.usage,
            cost_usd=acc.cost_usd,
        )
