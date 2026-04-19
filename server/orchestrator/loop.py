"""The autonomous agent outer loop.

Orchestrates the overall run: pulls the current plan + staff guidance,
asks the LLM (through ConversationService) to take the next step, and
broadcasts status events to the web UI and Slack.

The inner tool-calling loop lives in server/conversation.py (ported
verbatim from beamtimehero). This module owns the outer cadence: one
"turn" per orchestrator tick.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from config import ORCHESTRATOR_TICK_S, STATUS_POST_INTERVAL_S
from conversation import ConversationService
from db.autonomy_client import upsert_experiment_plan
from orchestrator import planner
from orchestrator.phase import PreconditionChecker
from orchestrator.staff_guidance import coordinator
from spec import phase_allowlist, spec_cmd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types for UI broadcast
# ---------------------------------------------------------------------------

EventEmitter = Callable[[dict], Any]  # can be sync or async — we handle both


@dataclass
class OrchestratorState:
    running: bool = False
    paused: bool = False
    experiment_id: Optional[str] = None
    last_status_post: float = 0.0
    last_turn_at: float = 0.0
    turn_count: int = 0
    last_summary: str = ""
    last_images: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        conversation: ConversationService,
        *,
        emit: Optional[EventEmitter] = None,
        slack_status_post: Optional[Callable[[str], Any]] = None,
    ):
        self.conversation = conversation
        self.emit = emit or (lambda evt: None)
        self.slack_status_post = slack_status_post or (lambda text: None)
        self.state = OrchestratorState()
        self.checker = PreconditionChecker()
        self._stop = asyncio.Event()
        self._paused_event = asyncio.Event()
        self._paused_event.set()  # not paused by default

    # -- State control -------------------------------------------------

    def start(self, experiment_id: str) -> None:
        self.state.experiment_id = experiment_id
        self.state.running = True
        self.state.paused = False
        self._paused_event.set()
        self._stop = asyncio.Event()
        self.checker.record("experiment_id", experiment_id)
        # Seed plan-derived preconditions
        plan = planner.snapshot(experiment_id)
        self.checker.record("n_samples_configured", plan.samples_total)
        self.checker.record("beam_good", True)  # assumed; checker will refine
        spec_cmd.set_phase(plan.phase or phase_allowlist.PHASE_SETUP,
                           experiment_id=experiment_id)
        asyncio.create_task(self._run_forever())
        self._safe_emit({"type": "orchestrator_started", "experiment_id": experiment_id})

    def pause(self) -> None:
        self.state.paused = True
        self._paused_event.clear()
        self._safe_emit({"type": "orchestrator_paused"})

    def resume(self) -> None:
        self.state.paused = False
        self._paused_event.set()
        self._safe_emit({"type": "orchestrator_resumed"})

    def stop(self) -> None:
        self.state.running = False
        self._stop.set()
        self._safe_emit({"type": "orchestrator_stopped"})

    # -- Main loop -----------------------------------------------------

    async def _run_forever(self) -> None:
        while self.state.running and not self._stop.is_set():
            try:
                await self._paused_event.wait()
                if not self.state.running:
                    break
                await self._one_turn()
            except Exception as e:
                logger.error("orchestrator turn failed: %s", e, exc_info=True)
                self._safe_emit({"type": "orchestrator_error", "error": str(e)})
            await asyncio.sleep(ORCHESTRATOR_TICK_S)

    async def _one_turn(self) -> None:
        exp_id = self.state.experiment_id
        if not exp_id:
            return

        phase = spec_cmd.get_phase()
        if phase == phase_allowlist.PHASE_COMPLETE:
            logger.info("phase=complete — stopping orchestrator")
            self.stop()
            return

        # Drain staff guidance -> turn context
        guidance = coordinator.drain_guidance(exp_id)
        plan_snap = planner.snapshot(exp_id)

        turn_prompt_parts = [plan_snap.to_system_context()]
        if guidance:
            steering = "\n".join(f"- [{g['author']}] {g['text']}" for g in guidance)
            turn_prompt_parts.append(f"[STEERING — new staff guidance]\n{steering}")
        turn_prompt_parts.append(
            "Continue the experiment. Decide the single next action; reason briefly "
            "about why; call exactly one tool. If the current phase is complete, "
            "call `transition_phase` with a justification. If you need a human, "
            "call `request_human_intervention`. If you need more time to think, "
            "do nothing and just respond with a short summary — the loop will tick again."
        )
        prompt = "\n\n".join(turn_prompt_parts)

        self._safe_emit({
            "type": "orchestrator_turn_start",
            "turn": self.state.turn_count + 1,
            "phase": phase,
            "plan_snapshot": plan_snap.__dict__,
        })

        result = await asyncio.to_thread(self.conversation.handle_message, prompt)
        self.state.turn_count += 1
        self.state.last_turn_at = time.time()
        self.state.last_summary = result.text[:2000]
        self.state.last_images = list(result.images)

        self._safe_emit({
            "type": "orchestrator_turn_complete",
            "turn": self.state.turn_count,
            "phase": spec_cmd.get_phase(),
            "text": result.text,
            "images": result.images,
        })

        # Periodic Slack status
        now = time.time()
        if now - self.state.last_status_post >= STATUS_POST_INTERVAL_S:
            try:
                summary = (
                    f"[Autonomy] phase={spec_cmd.get_phase()} "
                    f"turn={self.state.turn_count} "
                    f"samples_done={plan_snap.samples_completed}/{plan_snap.samples_total} "
                    f"remaining_h={plan_snap.beamtime_remaining_hours:.2f}\n"
                    f"Latest: {result.text[:400]}"
                )
                self._safe_invoke(self.slack_status_post, summary)
            except Exception as e:
                logger.error("slack status post failed: %s", e)
            self.state.last_status_post = now

    def snapshot(self) -> dict:
        snap = None
        if self.state.experiment_id:
            try:
                snap = planner.snapshot(self.state.experiment_id).__dict__
            except Exception:
                snap = None
        return {
            "running": self.state.running,
            "paused": self.state.paused,
            "experiment_id": self.state.experiment_id,
            "turn_count": self.state.turn_count,
            "last_turn_at": self.state.last_turn_at,
            "phase": spec_cmd.get_phase(),
            "last_summary": self.state.last_summary,
            "plan_snapshot": snap,
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
