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
from typing import Optional

from orchestration.agent import phase_runner
from orchestration.agents import list_active
from orchestration.plan_store.client import (
    list_orphaned_deferred_steering,
    list_pending_stops,
    record_orchestrator_ack,
)

logger = logging.getLogger(__name__)


_TICK_SECONDS = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_running(agent_type: str) -> bool:
    """True if an AgentRun of this type has completed_at IS NULL."""
    return bool(list_active(agent_type=agent_type))


def _latest_collection_scan_id() -> Optional[str]:
    """Return the most recent CollectionScan id (by timestamp DESC). None
    if none exist."""
    from sqlmodel import select
    from orchestration.plan_store.models import CollectionScan
    from orchestration.plan_store.session import get_session

    with get_session() as session:
        row = session.exec(
            select(CollectionScan)
            .order_by(CollectionScan.timestamp.desc())  # type: ignore[union-attr]
            .limit(1)
        ).first()
        return row.id if row else None


def _focused_steering_seed(row: dict) -> str:
    """Seed prompt body used when the orchestrator respawns an agent
    for the sole purpose of handling one deferred steering message.

    The launcher .sh ignores stdin, so this lands in `task_text` (a
    DB note for audit) rather than in the agent's actual prompt. The
    role-specific system prompt already tells the agent to drain
    pending steering at the top of every spawn — between agent-
    instructions §1 and `BEAMTIMEHERO_AGENT_RUN_ID` in env, the
    respawned agent will pick this row up automatically."""
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


async def _step_planner_respawn(state: TickState) -> None:
    """If there's a new CollectionScan since last tick, spawn the planner."""
    try:
        latest = await asyncio.to_thread(_latest_collection_scan_id)
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


async def _step_dispatch_deferred_steering() -> None:
    """For each orphaned deferred row with a named target_agent_type,
    spawn that agent with a focused-task seed (only if not already running).
    """
    try:
        rows = await asyncio.to_thread(list_orphaned_deferred_steering)
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


async def _step_stop_rows() -> None:
    """STOP fast path — kill any running phase agent that ISN'T the
    target_agent_type, then spawn the target."""
    try:
        rows = await asyncio.to_thread(list_pending_stops)
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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_forever() -> None:
    """Polling loop. Started by orchestration.api.lifespan."""
    state = TickState()
    logger.info("orchestrator_tick: started (cadence=%.1fs)", _TICK_SECONDS)
    try:
        while True:
            try:
                await _step_stop_rows()
                await _step_dispatch_deferred_steering()
                await _step_planner_respawn(state)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("orchestrator_tick step raised: %s", e)
            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("orchestrator_tick: cancelled")
        raise
