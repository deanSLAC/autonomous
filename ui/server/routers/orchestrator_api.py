"""Orchestrator status + intervention resolution API.

The master Start/Pause/Resume/Stop/Reset endpoints have been retired —
each phase tile spawns its own Claude-CLI subprocess via
`/api/phase/run/{slug}` (see `phase_runner_api`). This router keeps the
read-only status snapshot (used by the dashboard's agent-online pill +
phase pill), staff guidance ingest, and the intervention-resolve hook
that Slack and the web UI both call into.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from orchestration.config import llm_enabled
from orchestration.plan_store.client import get_intervention
from orchestration.planner.loop import get_orchestrator
from orchestration.planner.staff_guidance import coordinator
from beamline_tools.audited_call import audited_call
from orchestration import runtime_state
from ui.server.schemas import GuidanceIn, ResetRunIn, ResolveInterventionIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


def _agent_reachable() -> bool:
    """Each turn spawns a `claude -p` subprocess — there is no long-lived
    server to ping, so reachability reduces to "is the LLM configured"."""
    return llm_enabled()


@router.get("/status")
def status():
    """Read-only snapshot for the dashboard.

    The Orchestrator class is still wired up at startup so tools that
    look up `get_orchestrator()` (e.g. post_status_update) keep working
    — but it no longer drives a multi-phase loop, so `running`/`paused`
    are advisory.
    """
    reachable = _agent_reachable()
    orch = get_orchestrator()
    if orch is None:
        return {
            "initialized": False,
            "agent_reachable": reachable,
        }
    return {
        "initialized": True,
        "agent_reachable": reachable,
        **orch.snapshot(),
    }


@router.post("/guidance")
async def submit_guidance(payload: GuidanceIn):
    """Users / staff submit steering text via web UI — joins the staff-guidance queue."""
    experiment_id = payload.experiment_id or runtime_state.get_experiment_id()
    coordinator.record_guidance(
        experiment_id=experiment_id, source="web", author=payload.author,
        text=payload.text,
    )
    return {"ok": True}


@router.post("/intervention/{intervention_id}/resolve")
async def resolve_intervention(intervention_id: str, payload: ResolveInterventionIn):
    row = get_intervention(intervention_id)
    if row is None:
        raise HTTPException(404, "intervention not found")
    await coordinator.resolve(
        intervention_id, status=payload.status, resolver=payload.resolver,
        note=payload.note,
    )
    return {"ok": True, "status": payload.status}


@router.post("/reset_run")
async def reset_run(payload: ResetRunIn):
    """Operator-triggered hard reset of the *run* (not the experiment).

    Kills running phase agents, records the phase transition back to
    `setup`, invalidates prior action-log rows, and resolves pending
    interventions with status='reset'. Experiment config, sample
    holders, and the sample queue are untouched.
    """
    if not payload.confirm:
        raise HTTPException(400, "confirm=true required (dashboard confirm dialog)")
    experiment_id = payload.experiment_id or runtime_state.get_experiment_id()
    if not experiment_id:
        raise HTTPException(404, "no active experiment")

    from orchestration.agent import phase_runner
    from orchestration.plan_store.client import reset_run_state

    killed = phase_runner.kill_all()
    try:
        # Before the DB phase is rewritten, so the transition row records
        # the actual previous phase.
        runtime_state.set_phase(
            "setup", experiment_id=experiment_id,
            justification="operator reset the run from the dashboard",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("reset_run: set_phase('setup') failed: %s", e)
    summary = reset_run_state(experiment_id)
    logger.info("reset_run: %s (killed %d agent(s))", summary, len(killed))
    return {"ok": True, "killed_agents": len(killed), **summary}


@router.post("/abort_spec")
def abort_spec():
    """Issue a ctrl-C to SPEC — equivalent to the agent's
    `abort_current_scan` tool. Useful regardless of which phase agent
    (if any) is currently running."""
    try:
        res = audited_call("abort", [], justification="ui:stop-spec-button")
    except Exception as e:
        raise HTTPException(500, f"abort failed: {e}")
    return {"ok": True, "result": res}
