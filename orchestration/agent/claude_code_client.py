"""claude-CLI stream-json ingest helpers + binary health check.

The in-process per-turn client (ConversationService driving
`ClaudeCodeClient.send()`) was removed with the conversation layer:
chat goes through ChatRouter → `scripts/chat-claude.sh` spawns, phases
through the dashboard tiles → `orchestration/agent/phase_runner.py`.
Gateway env for those subprocesses is applied by
`scripts/_agent-common.sh` via `orchestration.agent.gateway_env`.

What remains here is the shared machinery both spawn paths rely on:

  * `_Accumulator` / `_ingest_event` — fold a `claude -p` stream-json
    JSONL transcript into final text + tool-call records (consumed by
    `orchestration.agents.spawn`'s drain thread; entry shape is
    `orchestration.messages.ToolCallRecord`).
  * `ClaudeCodeClient.health_check()` — "is the claude binary
    invokable", surfaced as `agent_reachable` on `/health`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

from orchestration.config import CLAUDE_MODEL, LLM_GATEWAY, gateway_config

logger = logging.getLogger(__name__)


CLAUDE_BIN = os.getenv("CLAUDE_BIN", shutil.which("claude") or "claude")


@dataclass
class _Accumulator:
    """Fold claude code's stream-json events into a usable transcript."""

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
# Health check
# ---------------------------------------------------------------------------

class ClaudeCodeClient:
    """Thin handle on the `claude` CLI: model identity + reachability."""

    def __init__(self) -> None:
        gw = gateway_config()
        self.model = CLAUDE_MODEL or gw["model_alias"] or LLM_GATEWAY

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
