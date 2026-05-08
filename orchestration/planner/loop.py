"""The autonomous agent outer loop — orchestrator state machine.

After the LLM-decoupling refactor, this loop no longer drives the agent
itself. Instead it polls the steering queue (`staffguidance` table) and
the active-agent registry (`agentrun` table), spawning control agents
via `orchestration.agents.spawn()` to handle messages and posting their
results back to Slack when they complete.

State-machine summary (one tick at `ORCHESTRATOR_TICK_S`):

  1. STOP fast-path. Any `staffguidance` row with `is_stop=True` and
     `completed_at IS NULL` triggers `kill()` of the active control agent
     and a synchronous `spec_cmd.call("abort", ...)`. No spawn, no LLM.

  2. Pickup new steering. Rows with `orchestrator_ack_at IS NULL` are
     dispatched: spawn a control agent if none is active, else defer
     (the active agent polls `beamtimehero steering pending` itself).

  3. Re-pickup deferred rows. Rows whose linked agent has finished but
     the row still has `completed_at IS NULL` are dispatched again.

  4. Slack-reply for completed rows. Rows with `completed_at IS NOT NULL`,
     `slack_thread_ts`, and `slack_replied_at IS NULL` get their `result`
     posted as a thread reply, then `slack_replied_at` is stamped.

  5. Reap dead control agents. Any `agentrun` row marked active whose
     PID isn't alive anymore is marked killed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from beamline_tools.spec_control import phase_allowlist, spec_cmd
from orchestration.agents import (
    complete_run,
    find_active_control,
    list_active,
    spawn,
    kill,
)
from orchestration.config import ORCHESTRATOR_TICK_S, PROJECT_ROOT
from orchestration.plan_store.client import (
    complete_steering,
    list_completed_unposted_steering,
    list_new_steering_for_orchestrator,
    list_orphaned_deferred_steering,
    list_pending_stops,
    mark_steering_replied,
    record_orchestrator_ack,
)
from orchestration.planner import planner
from orchestration.planner.phase import PreconditionChecker

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
    last_turn_at: float = 0.0     # last time the loop did meaningful work
    turn_count: int = 0


def _pid_alive(pid: int | None) -> bool:
    """Cheap mid-run liveness check. signal 0 = exists check.

    Startup-orphan reaping uses /proc parsing in `agents.spawn`; here we
    only need to know whether a PID is currently alive.
    """
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another uid — treat as alive.
        return True


class Orchestrator:
    """Polls the steering queue, dispatches control agents, posts replies.

    The constructor no longer takes a ConversationService. The LLM is
    invoked inside each spawned control-agent subprocess via
    `scripts/control-claude.sh`; this loop only does SQL queries +
    occasional spawn/kill/Slack-post.
    """

    def __init__(
        self,
        *,
        emit: Optional[EventEmitter] = None,
        slack_status_post: Optional[Callable[[str], Any]] = None,
        slack_post_steering_reply: Optional[Callable[[str, str, str], Any]] = None,
    ):
        self.emit = emit or (lambda evt: None)
        self.slack_status_post = slack_status_post or (lambda text: None)
        self.slack_post_steering_reply = (
            slack_post_steering_reply or (lambda c, t, s: None)
        )
        self.state = OrchestratorState()
        self.checker = PreconditionChecker()
        self._stop = asyncio.Event()
        self._paused_event = asyncio.Event()
        self._paused_event.set()  # not paused by default

    # -- State control -------------------------------------------------

    def start(self, experiment_id: str) -> None:
        """Seed plan-derived preconditions, set running, kick the loop task."""
        self.state.experiment_id = experiment_id
        self.state.running = True
        self.state.paused = False
        self._paused_event.set()
        self._stop = asyncio.Event()
        self.checker.record("experiment_id", experiment_id)
        # Seed plan-derived preconditions so phase-transition tools have a
        # populated checker even though the orchestrator itself doesn't drive
        # phase moves anymore.
        plan = planner.snapshot(experiment_id)
        self.checker.record("n_samples_configured", plan.samples_total)
        self.checker.record("beam_good", True)  # checker refines on its own
        spec_cmd.set_phase(
            plan.phase or phase_allowlist.PHASE_SETUP,
            experiment_id=experiment_id,
        )
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
        """One pass through the steering state machine. No LLM, no awaits on long calls."""
        exp_id = self.state.experiment_id

        phase = spec_cmd.get_phase()
        if phase == phase_allowlist.PHASE_COMPLETE:
            logger.info("phase=complete — stopping orchestrator")
            self.stop()
            return

        # 1. STOP fast-path (no LLM, no spawn)
        stop_rows = list_pending_stops()
        if stop_rows:
            self._handle_stops(stop_rows)
            self.state.last_turn_at = time.time()
            self.state.turn_count += 1
            return

        # 2. Pickup new steering (FIFO)
        new_rows = list_new_steering_for_orchestrator(exp_id)
        for row in new_rows:
            self._dispatch_new_steering(row)

        # 3. Re-pickup orphaned deferred rows (agent finished without acting)
        for row in list_orphaned_deferred_steering():
            # Only re-dispatch rows that match our experiment scope (or no
            # experiment scope at all). We don't filter at SQL because an
            # exp-less row can still be relevant in a single-experiment
            # session; but if exp_id is set, skip rows from other experiments.
            if exp_id and row.get("experiment_id") and row["experiment_id"] != exp_id:
                continue
            self._dispatch_new_steering(row, reason="re-tasked after deferral")

        # 4. Post completed rows back to Slack
        for row in list_completed_unposted_steering():
            self._post_steering_completion(row)

        # 5. Reap dead control agents (PID gone, completed_at still NULL)
        for run in list_active(agent_type="control"):
            pid = run.get("pid")
            if not _pid_alive(pid):
                complete_run(
                    run["id"],
                    killed=True,
                    kill_reason="process disappeared",
                )
                self._safe_emit({"type": "agent_reaped", "run_id": run["id"]})

        if new_rows or stop_rows:
            self.state.last_turn_at = time.time()
        self.state.turn_count += 1

    # -- State-machine handlers ---------------------------------------

    def _handle_stops(self, stop_rows: list[dict]) -> None:
        """STOP fast-path: kill active control agent, abort scan, complete rows.

        Slack reply for the STOP rows is posted on the next tick via the
        normal completion path (step 4 in `_one_turn`).
        """
        active = find_active_control()
        if active:
            try:
                kill(active["id"], reason="STOP from steering")
            except Exception as e:
                logger.error("STOP: kill(%s) raised: %s", active["id"], e)

        # Synchronous spec_cmd dispatch — fast even on real spec; on
        # SPEC_MOCK=1 it's a no-op-ish stub. The spec_cmd-level command
        # name is "abort" (autonomy_tools wraps it as "abort_current_scan").
        try:
            spec_cmd.call(
                "abort", [],
                justification="STOP from steering",
                agent="orchestrator",
            )
        except Exception as e:
            logger.error("STOP: spec_cmd.call('abort') raised: %s", e)

        ids: list[str] = []
        for row in stop_rows:
            try:
                complete_steering(
                    row["id"],
                    result=(
                        "STOP executed: control agent killed and "
                        "abort_current_scan invoked."
                    ),
                )
                ids.append(row["id"])
            except Exception as e:
                logger.error("STOP: complete_steering(%s) raised: %s", row["id"], e)

        self._safe_emit({"type": "stop_executed", "ids": ids})

    def _dispatch_new_steering(
        self,
        row: dict,
        reason: str = "tasking response agent",
    ) -> None:
        """Spawn a control agent for this row, or defer if one is already active."""
        active = find_active_control()
        if active:
            comment = (
                f"deferred — active agent in flight (run {active['id']})"
            )
            try:
                record_orchestrator_ack(
                    row["id"],
                    comment=comment,
                    active_agent_run_id=active["id"],
                )
            except Exception as e:
                logger.error(
                    "defer record_orchestrator_ack(%s) raised: %s",
                    row["id"], e,
                )
            self._safe_emit({
                "type": "steering_deferred",
                "steering_id": row["id"],
                "active_agent_run_id": active["id"],
            })
            return

        # No active control agent → spawn fresh.
        seed = self._build_steering_prompt(row)
        try:
            run_id = spawn(
                agent_type="control",
                task_text=f"steering: {(row.get('text') or '')[:80]}",
                spawned_by=f"steering:{row['id']}",
                script_path=PROJECT_ROOT / "scripts" / "control-claude.sh",
                seed_prompt=seed,
                experiment_id=row.get("experiment_id"),
                claude_session_id=None,  # fresh session per control run
            )
        except Exception as e:
            logger.error("spawn for steering %s raised: %s", row["id"], e)
            self._safe_emit({
                "type": "steering_spawn_failed",
                "steering_id": row["id"],
                "error": str(e),
            })
            return

        try:
            record_orchestrator_ack(
                row["id"],
                comment=reason,
                active_agent_run_id=run_id,
            )
        except Exception as e:
            logger.error(
                "spawn record_orchestrator_ack(%s) raised: %s",
                row["id"], e,
            )

        self._safe_emit({
            "type": "steering_dispatched",
            "steering_id": row["id"],
            "agent_run_id": run_id,
            "reason": reason,
        })

    def _build_steering_prompt(self, row: dict) -> str:
        """Seed prompt handed to the spawned control-claude session."""
        author = row.get("author") or "unknown"
        source = row.get("source") or "unknown"
        slack_channel = row.get("slack_channel") or ""
        slack_thread_ts = row.get("slack_thread_ts") or ""
        text = row.get("text") or ""
        slack_line = (
            f"{slack_channel}/{slack_thread_ts}"
            if slack_channel or slack_thread_ts else "(none)"
        )
        return (
            f"[STEERING TASK — id={row['id']}]\n"
            f"Author: {author} via {source}\n"
            f"Slack thread: {slack_line}\n\n"
            f"{text}\n\n"
            "Acknowledge this task by running:\n"
            f"  beamtimehero steering ack {row['id']}\n"
            "Then either:\n"
            f"  beamtimehero steering complete {row['id']} --result \"<your reply>\"\n"
            "or:\n"
            f"  beamtimehero steering defer {row['id']} --reason \"<reason>\"\n\n"
            "Between major operations, also poll for any other pending "
            "steering messages with `beamtimehero steering pending` and "
            "process them."
        )

    def _post_steering_completion(self, row: dict) -> None:
        """Post the completed row's `result` back to Slack and mark replied."""
        channel = row.get("slack_channel")
        thread_ts = row.get("slack_thread_ts")
        result = row.get("result") or "(no result)"
        if channel and thread_ts:
            try:
                self.slack_post_steering_reply(channel, thread_ts, result)
            except Exception as e:
                logger.error(
                    "slack post_steering_reply failed for %s: %s",
                    row.get("id"), e,
                )
        try:
            mark_steering_replied(row["id"])
        except Exception as e:
            logger.error("mark_steering_replied(%s) raised: %s", row["id"], e)

    # -- Snapshot ------------------------------------------------------

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
        try:
            active = find_active_control()
        except Exception:
            active = None
        return {
            "running": self.state.running,
            "paused": self.state.paused,
            "experiment_id": self.state.experiment_id,
            "turn_count": self.state.turn_count,
            "last_turn_at": self.state.last_turn_at,
            "phase": spec_cmd.get_phase(),
            "active_control_agent": active,
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


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

_singleton: Optional[Orchestrator] = None


def set_orchestrator(orch: Orchestrator) -> None:
    global _singleton
    _singleton = orch


def get_orchestrator() -> Optional[Orchestrator]:
    return _singleton
