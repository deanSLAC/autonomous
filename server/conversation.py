"""Conversation service — thin wrapper around an opencode session.

opencode runs the full tool-calling loop; this class just holds the
session handle and tracks buffered staff messages. Tool execution,
model choice, and message routing are all handled by the opencode
server (see scripts/start_opencode.sh, opencode.json).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from opencode_client import OpenCodeClient

logger = logging.getLogger(__name__)


@dataclass
class ConversationResult:
    """Result of a single agent interaction."""
    text: str
    images: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    prompt: str = ""


# Optional sink for "turn complete" events — wired by app.py to broadcast
# a single tool-trace event to the WebSocket-attached Insight UI. Runs
# in whatever thread the conversation handler runs in; sinks must be
# thread-safe (the app uses asyncio.run_coroutine_threadsafe).
TurnSink = Optional[Callable[[dict], None]]
_sink: TurnSink = None
_sink_lock = threading.Lock()


def set_turn_sink(sink: TurnSink) -> None:
    global _sink
    with _sink_lock:
        _sink = sink


def _emit_turn(payload: dict) -> None:
    with _sink_lock:
        sink = _sink
    if sink is None:
        return
    try:
        sink(payload)
    except Exception as e:
        logger.warning("turn sink failed: %s", e)


class ConversationService:
    """Owns one persistent opencode session for an autonomous run."""

    def __init__(self, client: OpenCodeClient):
        self.client = client
        self._staff_buffer: list[str] = []
        self.messages: list[dict] = []  # mirror for legacy / UI callers

    # ---- Staff guidance buffering (mirrors old API) -------------------

    def buffer_staff_message(self, staff_text: str, staff_name: str = "Staff"):
        self._staff_buffer.append(f"[Staff member {staff_name}]: {staff_text}")

    def _flush_staff_context(self) -> str:
        if not self._staff_buffer:
            return ""
        ctx = "\n".join(self._staff_buffer)
        self._staff_buffer.clear()
        return ctx

    # ---- Core turns ----------------------------------------------------

    def handle_message(self, user_text: str) -> ConversationResult:
        staff_context = self._flush_staff_context()
        combined = (
            f"{staff_context}\n\n[User/operator]: {user_text}"
            if staff_context else user_text
        )
        self.messages.append({"role": "user", "content": combined})
        try:
            out = self.client.send(combined)
        except Exception as e:
            logger.error("opencode send failed: %s", e, exc_info=True)
            err = ConversationResult(text=f"Error: {e}", prompt=combined)
            _emit_turn({"type": "turn_complete", "source": "chat",
                        "prompt": combined, "text": err.text,
                        "tool_calls": [], "thoughts": [], "images": []})
            return err
        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        result = ConversationResult(
            text=out.text, images=out.images,
            tool_calls=out.tool_calls, thoughts=out.thoughts,
            prompt=combined,
        )
        _emit_turn({
            "type": "turn_complete", "source": "chat",
            "prompt": combined, "text": out.text,
            "tool_calls": out.tool_calls, "thoughts": out.thoughts,
            "images": out.images,
        })
        return result

    def handle_staff_llm(self, staff_text: str, staff_name: str = "Staff") -> ConversationResult:
        prompt = f"[Staff member {staff_name}]: {staff_text}"
        self.messages.append({"role": "user", "content": prompt})
        try:
            out = self.client.send(prompt)
        except Exception as e:
            logger.error("opencode staff-LLM send failed: %s", e, exc_info=True)
            err = ConversationResult(text=f"Error: {e}", prompt=prompt)
            _emit_turn({"type": "turn_complete", "source": "staff",
                        "prompt": prompt, "text": err.text,
                        "tool_calls": [], "thoughts": [], "images": []})
            return err
        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        result = ConversationResult(
            text=out.text, images=out.images,
            tool_calls=out.tool_calls, thoughts=out.thoughts,
            prompt=prompt,
        )
        _emit_turn({
            "type": "turn_complete", "source": "staff",
            "prompt": prompt, "text": out.text,
            "tool_calls": out.tool_calls, "thoughts": out.thoughts,
            "images": out.images,
        })
        return result

    def reset(self) -> None:
        self.messages.clear()
        self._staff_buffer.clear()
        self.client.reset_session()

    def get_history(self) -> list[dict]:
        return list(self.messages)
