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

from orchestration.config import AGENT_BACKEND, llm_enabled
from orchestration.plan_store.client import get_intervention
from orchestration.agent.opencode_client import OpenCodeClient
from orchestration.planner.loop import get_orchestrator
from orchestration.planner.staff_guidance import coordinator
from beamline_tools.audited_call import audited_call
from orchestration import runtime_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


def _agent_reachable() -> bool:
    """Live probe of the opencode backend — used by the dashboard
    pill so a mid-run crash shows up without a page reload.

    Only meaningful when AGENT_BACKEND=opencode (long-lived loopback
    server). With AGENT_BACKEND=claude_code each turn spawns a
    `claude -p` subprocess, so there's nothing to ping — treat as
    always reachable.
    """
    if not llm_enabled():
        return False
    if AGENT_BACKEND != "opencode":
        return True
    try:
        return OpenCodeClient().health_check()
    except Exception:
        return False


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
            "agent_backend": AGENT_BACKEND,
        }
    return {
        "initialized": True,
        "agent_reachable": reachable,
        "agent_backend": AGENT_BACKEND,
        **orch.snapshot(),
    }


@router.post("/guidance")
async def submit_guidance(payload: dict):
    """Users / staff submit steering text via web UI — joins the staff-guidance queue."""
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    author = (payload.get("author") or "web-user").strip()
    experiment_id = payload.get("experiment_id") or runtime_state.get_experiment_id()
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
