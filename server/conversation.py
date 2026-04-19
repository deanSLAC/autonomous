"""Conversation service — thin wrapper around an opencode session.

opencode runs the full tool-calling loop; this class just holds the
session handle and tracks buffered staff messages. Tool execution,
model choice, and message routing are all handled by the opencode
server (see scripts/start_opencode.sh, opencode.json).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from opencode_client import OpenCodeClient

logger = logging.getLogger(__name__)


@dataclass
class ConversationResult:
    """Result of a single agent interaction."""
    text: str
    images: list[str] = field(default_factory=list)


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
            return ConversationResult(text=f"Error: {e}")
        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        return ConversationResult(text=out.text, images=out.images)

    def handle_staff_llm(self, staff_text: str, staff_name: str = "Staff") -> ConversationResult:
        prompt = f"[Staff member {staff_name}]: {staff_text}"
        self.messages.append({"role": "user", "content": prompt})
        try:
            out = self.client.send(prompt)
        except Exception as e:
            logger.error("opencode staff-LLM send failed: %s", e, exc_info=True)
            return ConversationResult(text=f"Error: {e}")
        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        return ConversationResult(text=out.text, images=out.images)

    def reset(self) -> None:
        self.messages.clear()
        self._staff_buffer.clear()
        self.client.reset_session()

    def get_history(self) -> list[dict]:
        return list(self.messages)
