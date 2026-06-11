"""Conversation service — thin wrapper around an agent session.

Claude Code runs the full tool-calling loop; this class just holds the
session handle and tracks buffered staff messages. Tool execution,
model choice, and message routing are all handled by Claude Code.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field

import mlflow

from orchestration.agent.claude_code_client import ClaudeCodeClient, OpenCodeResult
from orchestration.observability import mlflow_logging

logger = logging.getLogger(__name__)


_MLFLOW_EXPERIMENT = "autonomous/chat"


@dataclass
class ConversationResult:
    """Result of a single agent interaction."""
    text: str
    images: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    prompt: str = ""


def _log_run_success(
    run, *, client: ClaudeCodeClient, source: str, prompt: str,
    out: OpenCodeResult, latency_seconds: float,
    experiment_id: str | None, staff_name: str | None, turn: int | None,
) -> None:
    """Best-effort: write all per-turn artifacts to the active run.

    Wrapped in a single try/except — a flaky log call must not break the
    user's turn or skip remaining writes that might still succeed.
    """
    if run is None:
        return
    try:
        params = {
            "model": client.model,
            "source": source,
            "experiment_id": experiment_id,
            "staff_name": staff_name,
            "turn": turn,
            "opencode_session_id": out.session_id,
        }
        for k, v in params.items():
            if v is not None:
                mlflow.log_param(k, v)

        mlflow.log_metric("latency_seconds", latency_seconds)
        mlflow.log_metric("tool_call_count", len(out.tool_calls))
        mlflow.log_metric("image_count", len(out.images))
        mlflow.log_metric("error", 0)

        tool_counts: Counter[str] = Counter()
        for c in out.tool_calls:
            name = c.get("name") or "?"
            tool_counts[name] += 1
        for name, count in tool_counts.items():
            mlflow.set_tag(f"tool:{name}", count)

        mlflow.log_text(prompt, "prompt.txt")
        mlflow.log_text(out.text or "", "response.md")
        mlflow.log_dict({"calls": out.tool_calls}, "tool_calls.json")

        for img_path in out.images:
            try:
                mlflow.log_artifact(img_path, artifact_path="plots/")
            except Exception as e:
                logger.warning("mlflow log_artifact(%s) failed: %s", img_path, e)

        # TODO: token metrics (prompt/completion) are intentionally omitted —
        # opencode's REST surface does not expose them. Revisit if/when
        # opencode adds usage to its message responses.
    except Exception as e:
        mlflow_logging._mark_degraded(  # type: ignore[attr-defined]
            f"log_run_success: {e}",
            first=not mlflow_logging.MLFLOW_DEGRADED,
        )


def _log_run_failure(run, exc: BaseException) -> None:
    if run is None:
        return
    try:
        mlflow.log_metric("error", 1)
        mlflow.set_tag("error_type", type(exc).__name__)
        mlflow.log_text(str(exc), "error.txt")
    except Exception as e:
        mlflow_logging._mark_degraded(  # type: ignore[attr-defined]
            f"log_run_failure: {e}",
            first=not mlflow_logging.MLFLOW_DEGRADED,
        )


class ConversationService:
    """Owns one persistent agent session for an autonomous run."""

    def __init__(self, client: ClaudeCodeClient):
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

    def handle_message(
        self,
        user_text: str,
        *,
        source: str = "unknown",
        experiment_id: str | None = None,
        turn: int | None = None,
    ) -> ConversationResult:
        staff_context = self._flush_staff_context()
        combined = (
            f"{staff_context}\n\n[User/operator]: {user_text}"
            if staff_context else user_text
        )
        self.messages.append({"role": "user", "content": combined})

        with mlflow_logging.run(
            _MLFLOW_EXPERIMENT, source=source, experiment_id=experiment_id,
        ) as run:
            t0 = time.perf_counter()
            try:
                out = self.client.send(combined)
            except Exception as e:
                _log_run_failure(run, e)
                logger.error("agent send failed: %s", e, exc_info=True)
                return ConversationResult(text=f"Error: {e}", prompt=combined)
            latency = time.perf_counter() - t0
            _log_run_success(
                run, client=self.client, source=source, prompt=combined,
                out=out, latency_seconds=latency,
                experiment_id=experiment_id, staff_name=None, turn=turn,
            )

        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        return ConversationResult(
            text=out.text, images=out.images,
            tool_calls=out.tool_calls, thoughts=out.thoughts,
            prompt=combined,
        )

    def handle_staff_llm(
        self,
        staff_text: str,
        staff_name: str = "Staff",
        *,
        source: str = "unknown",
        experiment_id: str | None = None,
    ) -> ConversationResult:
        prompt = f"[Staff member {staff_name}]: {staff_text}"
        self.messages.append({"role": "user", "content": prompt})

        with mlflow_logging.run(
            _MLFLOW_EXPERIMENT, source=source, experiment_id=experiment_id,
            staff_name=staff_name,
        ) as run:
            t0 = time.perf_counter()
            try:
                out = self.client.send(prompt)
            except Exception as e:
                _log_run_failure(run, e)
                logger.error("agent staff-LLM send failed: %s", e, exc_info=True)
                return ConversationResult(text=f"Error: {e}", prompt=prompt)
            latency = time.perf_counter() - t0
            _log_run_success(
                run, client=self.client, source=source, prompt=prompt,
                out=out, latency_seconds=latency,
                experiment_id=experiment_id, staff_name=staff_name, turn=None,
            )

        stored = out.text
        if out.images:
            stored += f"\n\n[{len(out.images)} plot(s) generated]"
        self.messages.append({"role": "assistant", "content": stored})
        return ConversationResult(
            text=out.text, images=out.images,
            tool_calls=out.tool_calls, thoughts=out.thoughts,
            prompt=prompt,
        )

    def reset(self) -> None:
        self.messages.clear()
        self._staff_buffer.clear()
        self.client.reset_session()

    def get_history(self) -> list[dict]:
        return list(self.messages)
