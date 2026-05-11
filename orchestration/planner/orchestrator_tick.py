"""Orchestrator polling tick — the deterministic glue between agents.

Runs as an asyncio task started in the FastAPI lifespan. Three jobs:

  1. **Auto-respawn the planner** after each new `CollectionScan`.
     Detects new scans by tracking the latest CollectionScan row id
     observed; when a new one appears and no `agent_type='planner'`
     row is currently active, spawn the planner phase tile. (The
     data collector keeps running in parallel — concurrent slugs are
     fine.)

  2. **Re-dispatch deferred steering.** When an active agent defers a
     row out of scope and names a `target_agent_type`, this tick
     spawns that target with a focused-task seed prompt the moment
     the active agent finishes. Uses
     `list_orphaned_deferred_steering()`.

  3. **STOP-row fast path.** A steering row with `is_stop=true` kills
     every active phase agent (except a designated `target_agent_type`
     if named) and lets staff resolve from a clean state. Uses
     `list_pending_stops()`.

The tick is intentionally polling (~3 s cadence) rather than event-
driven: SQLite is the source of truth and a poll is cheap, simple, and
easy to reason about across the multi-process layout (UI, slack
adapter, agent subprocesses).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from orchestration.agent import phase_runner
from orchestration.agents import list_active
from orchestration.plan_store.client import (
    get_plan,
    list_orphaned_deferred_steering,
    list_pending_stops,
    list_unacked_steering,
    record_orchestrator_ack,
)

logger = logging.getLogger(__name__)


_TICK_SECONDS = 3.0

# Collection-phase watchdog thresholds. The planner is normally respawned
# on every new CollectionScan row; if the data collector stops producing
# scans (e.g. the plan was zeroed out) the system goes deaf. These cover
# the three plausible deaf states.
_HEARTBEAT_MINUTES = 5.0           # planner finished and hasn't run since
_STALE_STEERING_MINUTES = 3.0      # operator steering unacked >3 min
_IDLE_SCAN_MINUTES = 5.0           # no new CollectionScan in >5 min
_MIN_HEARTBEAT_GAP_MINUTES = 5.0   # re-arm guard (3-sec tick would spam)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_running(agent_type: str) -> bool:
    """True if an AgentRun of this type has completed_at IS NULL."""
    return bool(list_active(agent_type=agent_type))


def _latest_collection_scan_id(experiment_id: str) -> Optional[str]:
    """Return the most recent CollectionScan id for *this* experiment
    (by timestamp DESC). None if none exist."""
    from sqlmodel import select
    from orchestration.plan_store.models import CollectionScan
    from orchestration.plan_store.session import get_session

    with get_session() as session:
        row = session.exec(
            select(CollectionScan)
            .where(CollectionScan.experiment_id == experiment_id)
            .order_by(CollectionScan.timestamp.desc())  # type: ignore[union-attr]
            .limit(1)
        ).first()
        return row.id if row else None


def _focused_steering_seed(row: dict) -> str:
    """Seed prompt delivered to the agent over stdin when the orchestrator
    respawns it for a single deferred steering message.

    Also recorded as `task_text` on the AgentRun row for audit."""
    return (
        f"[orchestrator focused-task respawn]\n"
        f"steering_id={row.get('id')}  author={row.get('author')}  "
        f"is_stop={row.get('is_stop')}\n"
        f"text: {row.get('text')}\n"
        f"You are spawned for this single steering item. Carry it out, "
        f"`steering complete <id> --result '...'` (or defer again if it's "
        f"genuinely out of scope), then exit."
    )


# ---------------------------------------------------------------------------
# Tick steps
# ---------------------------------------------------------------------------

class TickState:
    """Per-process tick state. The asyncio task closes over one of these."""

    def __init__(self) -> None:
        # The id of the latest CollectionScan we've already triggered a
        # planner respawn for. None on first tick — we don't want to
        # respawn the planner on startup just because old scans exist.
        self.last_seen_scan_id: Optional[str] = None
        self._initialized: bool = False
        self.planner_was_running: bool = False
        # Watchdog tracking — wall-clock timestamps from time.time().
        self.last_planner_finish_time: Optional[float] = None
        self.last_scan_time: Optional[float] = None
        self.last_heartbeat_spawn_time: Optional[float] = None


async def _step_planner_respawn(state: TickState, experiment_id: str) -> None:
    """If there's a new CollectionScan since last tick, spawn the planner."""
    try:
        latest = await asyncio.to_thread(_latest_collection_scan_id, experiment_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("orchestrator_tick: latest scan lookup failed: %s", e)
        return

    if not state._initialized:
        state.last_seen_scan_id = latest
        state._initialized = True
        return

    if latest is None or latest == state.last_seen_scan_id:
        return

    # New scan(s) since last tick.
    state.last_seen_scan_id = latest
    state.last_scan_time = time.time()

    if _is_running("planner"):
        # Already running — let it finish; the next scan will trigger another
        # respawn after this one exits.
        logger.info("orchestrator_tick: new scan %s, planner already running", latest)
        return

    try:
        info = await asyncio.to_thread(
            phase_runner.start, "planner",
            seed_text=f"between-scan replan after CollectionScan {latest}",
            spawned_by="orchestrator:scan-completed",
        )
        logger.info("orchestrator_tick: spawned planner (run_id=%s) for scan %s",
                    info.get("run_id"), latest)
    except ValueError as e:
        # "already running" race or missing script — tolerate.
        logger.info("orchestrator_tick: planner spawn skipped: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestrator_tick: planner spawn failed: %s", e)


async def _step_dispatch_deferred_steering(experiment_id: str) -> None:
    """For each orphaned deferred row with a named target_agent_type,
    spawn that agent with a focused-task seed (only if not already running).
    """
    try:
        rows = await asyncio.to_thread(list_orphaned_deferred_steering, experiment_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("orchestrator_tick: deferred lookup failed: %s", e)
        return

    for row in rows:
        target = row.get("target_agent_type")
        if not target:
            # No target named — leave it for staff to handle manually.
            continue
        if target not in phase_runner.PHASE_SCRIPTS:
            logger.warning(
                "orchestrator_tick: deferred row %s has unknown target %r",
                row.get("id"), target,
            )
            continue
        if _is_running(target):
            continue
        try:
            info = await asyncio.to_thread(
                phase_runner.start, target,
                seed_text=_focused_steering_seed(row),
                spawned_by=f"orchestrator:steering:{row.get('id')}",
            )
            # Stamp orchestrator_ack on the row so it doesn't fire repeatedly.
            await asyncio.to_thread(
                record_orchestrator_ack,
                row.get("id"),
                comment=f"redispatched to {target} (run_id={info.get('run_id')})",
                active_agent_run_id=info.get("run_id"),
            )
            logger.info(
                "orchestrator_tick: redispatched steering %s to %s (run_id=%s)",
                row.get("id"), target, info.get("run_id"),
            )
        except ValueError as e:
            logger.info("orchestrator_tick: redispatch skipped (%s): %s",
                        target, e)
        except Exception as e:  # noqa: BLE001
            logger.exception("orchestrator_tick: redispatch failed: %s", e)


async def _step_stop_rows(experiment_id: str) -> None:
    """STOP fast path — kill any running phase agent that ISN'T the
    target_agent_type, then spawn the target."""
    try:
        rows = await asyncio.to_thread(list_pending_stops, experiment_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("orchestrator_tick: STOP lookup failed: %s", e)
        return

    for row in rows:
        if row.get("orchestrator_ack_at"):
            continue  # already handled
        target = row.get("target_agent_type")
        # Kill every running phase agent except the named target.
        for slug in list(phase_runner.PHASE_SCRIPTS.keys()):
            if slug == target:
                continue
            if not phase_runner.is_running(slug):
                continue
            try:
                await asyncio.to_thread(
                    phase_runner.kill, slug, reason=f"STOP steering {row.get('id')}",
                )
            except ValueError:
                pass
            except Exception as e:  # noqa: BLE001
                logger.warning("orchestrator_tick: kill(%s) failed: %s", slug, e)

        if target and target in phase_runner.PHASE_SCRIPTS and not _is_running(target):
            try:
                info = await asyncio.to_thread(
                    phase_runner.start, target,
                    seed_text=_focused_steering_seed(row),
                    spawned_by=f"orchestrator:stop:{row.get('id')}",
                )
                await asyncio.to_thread(
                    record_orchestrator_ack,
                    row.get("id"),
                    comment=f"STOP — handed to {target} (run_id={info.get('run_id')})",
                    active_agent_run_id=info.get("run_id"),
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("orchestrator_tick: STOP target spawn failed: %s", e)
        else:
            # No target — just stamp the ack so we don't loop.
            try:
                await asyncio.to_thread(
                    record_orchestrator_ack,
                    row.get("id"),
                    comment="STOP — agents killed; no target named, awaiting staff",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("orchestrator_tick: STOP ack failed: %s", e)


def _generate_statistics_trend() -> None:
    """Read the active sample's convergence_stats from the plan and render
    a statistics trend PNG to data/tool_plots/."""
    from pathlib import Path
    from orchestration.config import PROJECT_ROOT
    from orchestration.plan_store.client import get_plan as _get_plan
    from orchestration.plan_store.session import get_active_experiment

    exp = get_active_experiment()
    if not exp:
        return
    plan_row = _get_plan(exp.id)
    if not plan_row:
        return
    body = plan_row.get("plan") or {}
    queue = body.get("sample_queue") or []

    active = None
    for s in queue:
        if s.get("status") == "in_progress":
            active = s
            break
    if active is None or not active.get("convergence_stats"):
        return

    stats = active["convergence_stats"]
    sample_name = active.get("sample_name", active.get("sample_id", ""))

    try:
        import matplotlib
        matplotlib.use("Agg")
        from beamline_tools.spec_data.plotting import plot_statistics_trend, fig_to_base64
        import base64
        from datetime import datetime

        fig, summary = plot_statistics_trend(stats, sample_name)
        if fig is None:
            logger.info("orchestrator_tick: statistics trend skipped: %s", summary)
            return

        out_dir = PROJECT_ROOT / "data" / "tool_plots"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
        sid = active.get("sample_id", "unknown")
        fname = f"statistics_trend_{sid}_{ts}.png"
        b64 = fig_to_base64(fig)
        (out_dir / fname).write_bytes(base64.b64decode(b64))
        import matplotlib.pyplot as plt
        plt.close(fig)
        logger.info("orchestrator_tick: statistics trend plot saved: %s", fname)
    except Exception as e:  # noqa: BLE001
        logger.warning("orchestrator_tick: statistics trend plot failed: %s", e)


def _oldest_unacked_steering_age_s(experiment_id: str) -> Optional[float]:
    """Wall-clock age of the oldest unacked steering row in seconds.
    None if the queue is empty or timestamps are missing."""
    rows = list_unacked_steering(experiment_id)
    if not rows:
        return None
    oldest_ts = None
    for row in rows:
        ts = row.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if oldest_ts is None or dt < oldest_ts:
            oldest_ts = dt
    if oldest_ts is None:
        return None
    return max(0.0, (datetime.now() - oldest_ts).total_seconds())


async def _step_collection_heartbeat(state: TickState, experiment_id: str) -> None:
    """Watchdog respawn during the `collection` phase.

    `_step_planner_respawn` is the only automatic spawn trigger and it
    fires on new CollectionScan rows. If the data collector stops
    producing scans (e.g. the plan zeroed out all reps) the system
    goes deaf — no planner respawns, no steering processing. This
    step covers that hole by spawning the planner when any of three
    quiescent-state thresholds tripped.
    """
    try:
        plan = await asyncio.to_thread(get_plan, experiment_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("orchestrator_tick: heartbeat plan lookup failed: %s", e)
        return
    if not plan or plan.get("phase") != "collection":
        return
    if _is_running("planner"):
        return

    now = time.time()
    if (
        state.last_heartbeat_spawn_time is not None
        and (now - state.last_heartbeat_spawn_time) < _MIN_HEARTBEAT_GAP_MINUTES * 60
    ):
        return

    reason: Optional[str] = None
    if (
        state.last_planner_finish_time is not None
        and (now - state.last_planner_finish_time) > _HEARTBEAT_MINUTES * 60
    ):
        idle_min = (now - state.last_planner_finish_time) / 60
        reason = f"planner idle {idle_min:.1f} min"
    else:
        try:
            steering_age = await asyncio.to_thread(
                _oldest_unacked_steering_age_s, experiment_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("orchestrator_tick: heartbeat steering lookup failed: %s", e)
            steering_age = None
        if steering_age is not None and steering_age > _STALE_STEERING_MINUTES * 60:
            reason = f"steering unacked {steering_age / 60:.1f} min"
        elif (
            state.last_scan_time is not None
            and (now - state.last_scan_time) > _IDLE_SCAN_MINUTES * 60
        ):
            idle_min = (now - state.last_scan_time) / 60
            reason = f"no new scans in {idle_min:.1f} min"

    if reason is None:
        return

    seed = (
        f"[orchestrator heartbeat] {reason}. "
        f"Run the mandatory status assessment; if zero actionable samples "
        f"remain, reopen the queue and distribute extra reps proportionally "
        f"per the convergence-fallback procedure."
    )
    try:
        info = await asyncio.to_thread(
            phase_runner.start, "planner",
            seed_text=seed,
            spawned_by="orchestrator:heartbeat",
        )
        state.last_heartbeat_spawn_time = now
        logger.info(
            "orchestrator_tick: heartbeat spawned planner (run_id=%s) — %s",
            info.get("run_id"), reason,
        )
    except ValueError as e:
        logger.info("orchestrator_tick: heartbeat spawn skipped: %s", e)
        state.last_heartbeat_spawn_time = now
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestrator_tick: heartbeat spawn failed: %s", e)


async def _step_statistics_trend(state: TickState) -> None:
    """After the planner finishes a run, generate a statistics trend plot
    and stamp the watchdog's `last_planner_finish_time`."""
    planner_running = _is_running("planner")
    if state.planner_was_running and not planner_running:
        state.last_planner_finish_time = time.time()
        try:
            await asyncio.to_thread(_generate_statistics_trend)
        except Exception as e:  # noqa: BLE001
            logger.warning("orchestrator_tick: statistics trend step failed: %s", e)
    state.planner_was_running = planner_running


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_forever() -> None:
    """Polling loop. Started by orchestration.api.lifespan."""
    from orchestration.plan_store.session import get_active_experiment

    state = TickState()
    logger.info("orchestrator_tick: started (cadence=%.1fs)", _TICK_SECONDS)
    try:
        while True:
            try:
                exp = await asyncio.to_thread(get_active_experiment)
                if exp is None:
                    await asyncio.sleep(_TICK_SECONDS)
                    continue
                experiment_id: str = exp.id

                await _step_stop_rows(experiment_id)
                await _step_dispatch_deferred_steering(experiment_id)
                await _step_planner_respawn(state, experiment_id)
                await _step_collection_heartbeat(state, experiment_id)
                await _step_statistics_trend(state)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("orchestrator_tick step raised: %s", e)
            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("orchestrator_tick: cancelled")
        raise
