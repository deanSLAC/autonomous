"""Orchestrator control + intervention resolution API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from orchestration.config import AGENT_BACKEND, llm_enabled
from orchestration.plan_store.client import get_intervention, reset_run_state
from orchestration.plan_store.session import get_experiment
from orchestration.agent.opencode_client import OpenCodeClient
from orchestration.planner import planner
from orchestration.planner.loop import get_orchestrator
from orchestration.planner.staff_guidance import coordinator
from beamline_tools.spec_control import spec_cmd

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


@router.post("/start")
async def start(payload: dict):
    experiment_id = payload.get("experiment_id") or ""
    if not experiment_id:
        return JSONResponse({"success": False, "error": "experiment_id required"}, status_code=400)
    exp = get_experiment(experiment_id)
    if exp is None:
        return JSONResponse({"success": False, "error": "experiment not found"}, status_code=404)

    # Build plan
    beamtime_hours = float(payload.get("beamtime_hours", 48))
    try:
        planner.build_initial_plan(experiment_id, beamtime_hours=beamtime_hours)
    except Exception as e:
        return JSONResponse({"success": False, "error": f"plan build failed: {e}"}, status_code=500)

    orch = get_orchestrator()
    if orch is None:
        return JSONResponse(
            {
                "success": False,
                "error": (
                    "Orchestrator not initialized — the local opencode agent "
                    "server is not reachable. Launch it with "
                    "scripts/start_opencode.sh (or scripts/start.sh) and retry."
                ),
            },
            status_code=503,
        )
    orch.start(experiment_id)
    return {"success": True, "experiment_id": experiment_id, "phase": spec_cmd.get_phase()}


@router.post("/pause")
def pause():
    orch = get_orchestrator()
    if orch is None:
        raise HTTPException(503, "orchestrator not initialized")
    orch.pause()
    return {"ok": True}


@router.post("/resume")
def resume():
    orch = get_orchestrator()
    if orch is None:
        raise HTTPException(503, "orchestrator not initialized")
    orch.resume()
    return {"ok": True}


@router.post("/stop")
def stop():
    """Stop the orchestrator AND kill the active control agent (if any).

    Two-stage stop: the orchestrator state machine pauses its loop, and
    the agents-registry kill terminates the live Claude subprocess. We
    do both because the orchestrator's own `stop()` only manages the
    planner/loop side — the spawned control agent runs independently
    and would otherwise keep going.
    """
    from orchestration.agents import find_active_control, kill as kill_agent

    orch = get_orchestrator()
    if orch is None:
        raise HTTPException(503, "orchestrator not initialized")
    orch.stop()

    killed_run_id = None
    active = find_active_control()
    if active is not None:
        if kill_agent(active["id"], reason="ui:stop-button"):
            killed_run_id = active["id"]

    return {"ok": True, "killed_agent_run_id": killed_run_id}


@router.post("/reset")
def reset(payload: dict | None = None):
    """Hard reset: stop the run, invalidate action_log rows, resolve
    pending interventions, put phase back to setup. Keeps experiment
    config + sample queue. Operator can then toggle phase enables
    before clicking Start again.
    """
    experiment_id = (payload or {}).get("experiment_id") or spec_cmd.get_experiment_id()
    if not experiment_id:
        raise HTTPException(400, "experiment_id required (or start an experiment first)")
    orch = get_orchestrator()
    if orch is not None and orch.state.running:
        orch.stop()
    summary = reset_run_state(experiment_id)
    spec_cmd.set_phase("setup", experiment_id=experiment_id)
    if orch is not None:
        # Clear transient in-memory state so the next Start is clean.
        orch.state.turn_count = 0
        orch.checker = type(orch.checker)()  # fresh PreconditionChecker
    return {"ok": True, "experiment_id": experiment_id, **summary}


@router.post("/abort_spec")
def abort_spec():
    """Issue a ctrl-C to SPEC — equivalent to the agent's
    `abort_current_scan` tool. Does not touch orchestrator state."""
    try:
        res = spec_cmd.call("abort", [], justification="ui:stop-spec-button")
    except Exception as e:
        raise HTTPException(500, f"abort failed: {e}")
    return {"ok": True, "result": res}


@router.get("/status")
def status():
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
