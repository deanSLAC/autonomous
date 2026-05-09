"""Agent registry / lifecycle API.

Exposes the AgentRun registry to the dashboard:

    POST /api/agents/{run_id}/kill   — terminate one run
    GET  /api/agents                 — list recent runs (limit 50)

Phase agents (beamline_alignment / sample_alignment / sample_survey /
collection / planner) are now spawned via
`/api/phase/run/{slug}` (see phase_runner_api), and they write to the
same `agentrun` table — so this router serves the registry directly
for both phase agents and chat agents.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from orchestration.agents import get_run, kill
from orchestration.agents.runs import list_recent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(limit: int = 50):
    """Most-recent agent runs (defaults to 50)."""
    return {"runs": list_recent(limit=limit)}


@router.post("/{run_id}/kill")
def kill_run(run_id: str):
    """Kill a specific agent run."""
    row = get_run(run_id)
    if row is None:
        raise HTTPException(404, f"agent run {run_id} not found")
    ok = kill(run_id, reason="api request")
    return {"ok": ok, "run_id": run_id}
