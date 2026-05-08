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
from orchestration.agent.opencode_client import OpenCodeClient
from orchestration.planner.loop import get_orchestrator
from orchestration.planner.staff_guidance import coordinator
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


def _agent_reachable() -> bool:
    """Live probe of the agent backend — used by the dashboard pill so a
    mid-run crash shows up without a page reload."""
    if not llm_enabled():
        return False
    try:
        return OpenCodeClient().health_check()
    except Exception:
        return False


@router.get("/status")
def status():
    """Read-only snapshot for the dashboard.

    The Orchestrator class is still wired up at startup so tools that
    look up `get_orchestrator()` (e.g. transition_phase preconditions,
    post_status_update) keep working — but it no longer drives a
    multi-phase loop, so `running`/`paused` are advisory.
    """
    reachable = _agent_reachable()
    orch = get_orchestrator()
    if orch is None:
        return {"initialized": False, "agent_reachable": reachable}
    return {"initialized": True, "agent_reachable": reachable, **orch.snapshot()}


@router.post("/guidance")
async def submit_guidance(payload: dict):
    """Users / staff submit steering text via web UI — joins the staff-guidance queue."""
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    author = (payload.get("author") or "web-user").strip()
    experiment_id = payload.get("experiment_id") or spec_cmd.get_experiment_id()
    coordinator.record_guidance(
        experiment_id=experiment_id, source="web", author=author, text=text,
    )
    return {"ok": True}


@router.post("/intervention/{intervention_id}/resolve")
async def resolve_intervention(intervention_id: str, payload: dict):
    status = (payload.get("status") or "resolved").strip()
    if status not in ("resolved", "denied"):
        raise HTTPException(400, "status must be 'resolved' or 'denied'")
    row = get_intervention(intervention_id)
    if row is None:
        raise HTTPException(404, "intervention not found")
    resolver = (payload.get("resolver") or "web-user").strip()
    note = payload.get("note")
    await coordinator.resolve(intervention_id, status=status, resolver=resolver, note=note)
    return {"ok": True, "status": status}


@router.post("/phase")
async def force_phase(payload: dict):
    """Operator override — set the active phase directly (no agent loop involved)."""
    target = payload.get("phase")
    if not target:
        raise HTTPException(400, "phase required")
    experiment_id = payload.get("experiment_id") or spec_cmd.get_experiment_id()
    spec_cmd.set_phase(target, experiment_id=experiment_id)
    return {"ok": True, "phase": spec_cmd.get_phase()}
