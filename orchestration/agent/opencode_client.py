"""HTTP client for the local opencode server.

opencode is run as a separate process (see scripts/start_opencode.sh).
Talking to it with this client replaces the old direct-HTTP-to-Stanford
code. opencode itself runs the tool-calling loop and reaches our
Python tool layer via the generated `.opencode/tools/*.ts` wrappers.

Reference: opencode REST surface
  POST /session                      create session
  POST /session/{id}/message         send user message (blocks, returns last assistant message)
  POST /session/{id}/abort           abort generation
  GET  /session/{id}/message         list all messages (user + assistant + tool)
  GET  /event                        SSE event stream
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

from orchestration.config import (
    CONTEXT_DIR,
    LLM_GATEWAY,
    OPENCODE_MESSAGE_TIMEOUT_S,
    OPENCODE_URL,
    gateway_config,
)

logger = logging.getLogger(__name__)


@dataclass
class OpenCodeResult:
    """Assistant reply from one opencode `send_message` call."""
    text: str
    images: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    session_id: Optional[str] = None
    thoughts: list[str] = field(default_factory=list)


def _url(path: str) -> str:
    return f"{OPENCODE_URL.rstrip('/')}{path}"


def _load_system_prompt() -> str:
    fp = CONTEXT_DIR / "system_prompt.txt"
    if fp.exists():
        return fp.read_text()
    return ""


_IMAGE_PATH_RE = re.compile(r'(?:plot_path|image_path|png_path)"\s*:\s*"([^"]+)"')


def _extract_image_paths(messages: list[dict]) -> list[str]:
    """Scan tool-result payloads for generated plot paths."""
    paths: list[str] = []
    for m in messages or []:
        if m.get("role") != "tool":
            # opencode may nest tool results under `parts`
            for part in m.get("parts", []) or []:
                content = part.get("content") or part.get("text") or ""
                if isinstance(content, str):
                    for mo in _IMAGE_PATH_RE.finditer(content):
                        paths.append(mo.group(1))
        else:
            content = m.get("content") or ""
            if isinstance(content, str):
                for mo in _IMAGE_PATH_RE.finditer(content):
                    paths.append(mo.group(1))
    return paths


def _stringify(val: Any) -> str:
    if isinstance(val, str):
        return val
    try:
        return json.dumps(val, default=str)
    except Exception:
        return str(val)


def _truncate(s: str, limit: int = 4000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} chars]"


def _extract_tool_calls(messages: list[dict]) -> list[dict]:
    """Pull (name, input, output, status, timing) tuples from a transcript.

    opencode's message format has shifted across versions; we accept any
    of the common shapes:
      - parts with type="tool" carrying name/input/output inline
      - parts with type="tool-call" + matching type="tool-result"
      - role="tool" messages carrying content blocks
    """
    calls: list[dict] = []
    by_id: dict[str, dict] = {}

    def _record(entry: dict) -> None:
        cid = entry.get("id")
        if cid and cid in by_id:
            existing = by_id[cid]
            for k, v in entry.items():
                if v is not None and not existing.get(k):
                    existing[k] = v
            return
        if cid:
            by_id[cid] = entry
        calls.append(entry)

    for m in messages or []:
        role = m.get("role")
        parts = m.get("parts") or []
        if not isinstance(parts, list):
            parts = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            t = part.get("type") or ""
            if t in ("tool", "tool-call", "tool_use", "function-call"):
                # opencode shape: {type:"tool", tool:"<name>", callID, state:{input,output,status,time}}
                state = part.get("state") if isinstance(part.get("state"), dict) else {}
                name = (part.get("tool") or part.get("toolName")
                        or part.get("name") or "?")
                input_ = (state.get("input") or part.get("input")
                          or part.get("arguments") or {})
                output = (state.get("output") or part.get("output")
                          or part.get("result") or "")
                status = state.get("status") or part.get("status")
                time_ = state.get("time") or {}
                _record({
                    "id": part.get("callID") or part.get("id")
                          or part.get("toolCallId") or part.get("call_id"),
                    "name": name,
                    "input": input_,
                    "output": _truncate(_stringify(output)),
                    "status": status,
                    "started_at": time_.get("start") or part.get("startedAt"),
                    "completed_at": time_.get("end") or part.get("completedAt"),
                    "role": role,
                })
            elif t in ("tool-result", "tool_result", "function-result"):
                _record({
                    "id": part.get("toolCallId") or part.get("id")
                          or part.get("callID") or part.get("call_id"),
                    "name": part.get("toolName") or part.get("name"),
                    "output": _truncate(_stringify(
                        part.get("output") or part.get("result") or
                        part.get("content") or "")),
                    "status": part.get("status") or "completed",
                })
        if role == "tool":
            content = m.get("content")
            if isinstance(content, str) and content:
                _record({
                    "id": m.get("id") or m.get("toolCallId"),
                    "name": m.get("name") or m.get("toolName") or "?",
                    "output": _truncate(content),
                    "status": "completed",
                })
    return calls


def _extract_assistant_thoughts(messages: list[dict]) -> list[str]:
    """Pull any 'reasoning' / 'thinking' parts from assistant messages."""
    out: list[str] = []
    for m in messages or []:
        if m.get("role") != "assistant":
            continue
        for part in m.get("parts") or []:
            if not isinstance(part, dict):
                continue
            t = part.get("type") or ""
            if t in ("reasoning", "thinking"):
                txt = part.get("text") or part.get("content")
                if isinstance(txt, str) and txt.strip():
                    out.append(txt)
    return out


class OpenCodeClient:
    """Thin HTTP client for a local opencode server."""

    def __init__(self, base_url: str | None = None, session_id: str | None = None):
        self.base_url = (base_url or OPENCODE_URL).rstrip("/")
        self.session_id: Optional[str] = session_id
        gw = gateway_config()
        self.model = gw["model_alias"] or LLM_GATEWAY
        self._system_prompt = _load_system_prompt()

    # ---- Connectivity -------------------------------------------------

    def health_check(self) -> bool:
        try:
            r = requests.get(_url("/session"), timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ---- Session management ------------------------------------------

    def ensure_session(self) -> str:
        if self.session_id:
            return self.session_id
        # opencode picks its default model + provider from opencode.json
        # (the project's `model` key). Specifying `model` here as a bare
        # string fails their schema; we just don't bother.
        r = requests.post(_url("/session"), json={"title": "autonomous-beamline"},
                          timeout=30)
        r.raise_for_status()
        data = r.json()
        sid = data.get("id") or data.get("sessionID")
        if not sid:
            raise RuntimeError(f"opencode: unexpected create-session body: {data!r}")
        self.session_id = sid

        # Seed the session with the system prompt as the first user-side
        # primer (opencode's session-create body doesn't accept a system
        # field directly).
        if self._system_prompt:
            try:
                self._post_message(
                    sid,
                    text=f"[SYSTEM PRIMER]\n{self._system_prompt}",
                )
            except requests.HTTPError as e:
                logger.warning("system primer post failed: %s", e)
        return sid

    def reset_session(self) -> str:
        self.session_id = None
        return self.ensure_session()

    def abort(self) -> None:
        if not self.session_id:
            return
        try:
            requests.post(_url(f"/session/{self.session_id}/abort"), timeout=10)
        except requests.RequestException as e:
            logger.warning("opencode abort failed: %s", e)

    # ---- Send + read --------------------------------------------------

    def _post_message(self, session_id: str, text: str, role: str = "user") -> dict:
        # opencode's message endpoint takes only `parts`. The session was
        # bound to a model when it was created; sending `model` again as a
        # bare string fails the schema (it expects {providerID, modelID}).
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if role and role != "user":
            body["role"] = role
        # No timeout — a 48-hour run_collection must not be killed by
        # an HTTP-level deadline. Health/session-create above keep their
        # short timeouts; this is the long-running tool-loop call.
        r = requests.post(
            _url(f"/session/{session_id}/message"),
            json=body,
            timeout=OPENCODE_MESSAGE_TIMEOUT_S,
        )
        # Non-2xx: surface the body so we can see *why* (model missing,
        # upstream gateway 5xx, auth, etc.) instead of a bare HTTPError.
        if not r.ok:
            snippet = (r.text or "")[:500].replace("\n", " ")
            raise RuntimeError(
                f"opencode POST /session/{session_id}/message "
                f"returned {r.status_code}: {snippet!r}"
            )
        # 200 with non-JSON body — seen when the upstream model provider
        # (Stanford AI Gateway) returns an empty/HTML error that opencode
        # forwards verbatim. Log enough to diagnose.
        try:
            return r.json()
        except ValueError as e:
            snippet = (r.text or "")[:500].replace("\n", " ")
            logger.error(
                "opencode returned 200 but body is not JSON (%d bytes): %r",
                len(r.text or ""), snippet,
            )
            raise RuntimeError(
                "opencode returned a non-JSON response to the message post. "
                "This usually means the upstream model gateway (Stanford AI) "
                "failed — check opencode's stdout for the real error. "
                f"Body snippet: {snippet!r}"
            ) from e

    def send(self, text: str) -> OpenCodeResult:
        """Send a user message, blocking until the assistant has replied.

        Returns the final assistant text plus any tool-generated image paths.
        """
        sid = self.ensure_session()
        last = self._post_message(sid, text=text, role="user")

        # After the message, fetch all messages so we can surface tool-call
        # traces and image paths to the dashboard.
        try:
            r = requests.get(
                _url(f"/session/{sid}/message"),
                timeout=30,
            )
            messages = r.json() if r.ok else []
        except requests.RequestException:
            messages = []

        assistant_text = self._extract_assistant_text(last)
        if not assistant_text and messages:
            # Walk from the end for the most recent assistant message.
            for m in reversed(messages):
                if m.get("role") == "assistant":
                    assistant_text = self._extract_assistant_text(m)
                    if assistant_text:
                        break

        return OpenCodeResult(
            text=assistant_text or "",
            images=_extract_image_paths(messages),
            tool_calls=_extract_tool_calls(messages),
            messages=messages,
            session_id=sid,
            thoughts=_extract_assistant_thoughts(messages),
        )

    @staticmethod
    def _extract_assistant_text(msg: dict) -> str:
        """Pull the user-facing text out of an opencode message body.

        opencode returns messages as either a plain string or a list of
        `parts` (text / tool / etc.). We handle both shapes.
        """
        if not isinstance(msg, dict):
            return ""
        # Plain string
        content = msg.get("content")
        if isinstance(content, str):
            return content
        # `parts` form
        parts = msg.get("parts") or (content if isinstance(content, list) else [])
        chunks: list[str] = []
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                chunks.append(part.get("text", ""))
            elif "text" in part and isinstance(part["text"], str):
                chunks.append(part["text"])
        return "\n".join(c for c in chunks if c).strip()
