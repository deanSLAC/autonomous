"""Process-wide orchestration state used by tools.

The autonomous outer-loop ("Orchestrator drives the whole run") was retired
when the dashboard switched to per-phase tile launchers — every phase now
spawns its own Claude-CLI subprocess and there is no master cadence to run
turns from. The Orchestrator *singleton* still exists, however, because
a couple of tools reach back into it from a subprocess context:

  * `post_status_update` calls `orch.slack_status_post(text)`
  * the chat router resolves the active experiment via
    `orch.state.experiment_id`

So we keep a pared-down container with `state` (current experiment,
last-summary cache for the dashboard pill) and the Slack status
callback. start/pause/resume/stop/_run_forever are gone, and the
precondition gating layer that used to live here is gone too.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from orchestration import runtime_state
from orchestration.agent.conversation import ConversationService
from orchestration.planner import planner

logger = logging.getLogger(__name__)


EventEmitter = Callable[[dict], Any]  # can be sync or async — we handle both


@dataclass
class OrchestratorState:
    experiment_id: Optional[str] = None
    turn_count: int = 0
    last_summary: str = ""
    last_images: list[str] = field(default_factory=list)
    # Compatibility shims for callers (autonomy.js, dashboards) that
    # still read these fields. With the per-phase model there is no
    # master loop, so they're always False.
    running: bool = False
    paused: bool = False
    last_turn_at: float = 0.0


class Orchestrator:
    """Lightweight state holder + Slack status post bridge.

    Constructed at FastAPI startup (see orchestration.api.lifespan). Tools
    pick it up via `get_orchestrator()`.
    """

    def __init__(
        self,
        conversation: Optional[ConversationService] = None,
        *,
        emit: Optional[EventEmitter] = None,
        slack_status_post: Optional[Callable[[str], Any]] = None,
        slack_post_steering_reply: Optional[Callable[[str, str, str], Any]] = None,
    ):
        self.conversation = conversation
        self.emit = emit or (lambda evt: None)
        self.slack_status_post = slack_status_post or (lambda text: None)
        self.slack_post_steering_reply = (
            slack_post_steering_reply or (lambda c, t, s: None)
        )
        self.state = OrchestratorState()

    def snapshot(self) -> dict:
        snap = None
        if self.state.experiment_id:
            try:
                snap = planner.snapshot(self.state.experiment_id).__dict__
            except Exception:
                snap = None
        try:
            from orchestration.observability import mlflow_logging
            obs_status = mlflow_logging.status()
        except Exception:
            obs_status = "disabled"
        return {
            "running": self.state.running,
            "paused": self.state.paused,
            "experiment_id": self.state.experiment_id,
            "turn_count": self.state.turn_count,
            "last_turn_at": self.state.last_turn_at,
            "phase": runtime_state.get_phase(),
            "last_summary": self.state.last_summary,
            "plan_snapshot": snap,
            "obs_status": obs_status,
        }

    # -- Helpers -------------------------------------------------------

    def _safe_emit(self, event: dict) -> None:
        try:
            res = self.emit(event)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception as e:
            logger.warning("emit failed: %s", e)

    def _safe_invoke(self, fn, *a, **kw) -> None:
        try:
            res = fn(*a, **kw)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception as e:
            logger.warning("invoke failed: %s", e)


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

_singleton: Optional[Orchestrator] = None


def set_orchestrator(orch: Orchestrator) -> None:
    global _singleton
    _singleton = orch


def get_orchestrator() -> Optional[Orchestrator]:
    return _singleton
