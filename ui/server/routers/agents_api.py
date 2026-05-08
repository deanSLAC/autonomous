"""Agent registry / lifecycle API.

Exposes the AgentRun registry to the dashboard:

    POST /api/agents/{run_id}/kill   — terminate one run
    POST /api/agents/active/kill     — kill the active control agent
    GET  /api/agents/active          — fetch the active control agent row
    GET  /api/agents                 — list recent runs (limit 50)

The dashboard Stop button still posts to /api/orchestrator/stop — that
handler is wired to call into `agents.kill` itself so older UI builds
keep working.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from orchestration.agents import find_active_control, get_run, kill
from orchestration.agents.runs import list_recent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(limit: int = 50):
    """Most-recent agent runs (defaults to 50)."""
    return {"runs": list_recent(limit=limit)}


@router.get("/active")
def get_active():
    """Return the active control agent row, or {} if none is running."""
    row = find_active_control()
    return row or {}


@router.post("/active/kill")
def kill_active():
    """Kill the active control agent. Returns no_active=True if there isn't one."""
    row = find_active_control()
    if row is None:
        return {"ok": True, "no_active": True}
    ok = kill(row["id"], reason="api request")
    return {"ok": ok, "run_id": row["id"]}


@router.post("/{run_id}/kill")
def kill_run(run_id: str):
    """Kill a specific agent run."""
    row = get_run(run_id)
    if row is None:
        raise HTTPException(404, f"agent run {run_id} not found")
    ok = kill(run_id, reason="api request")
    return {"ok": ok, "run_id": run_id}
