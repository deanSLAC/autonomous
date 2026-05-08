"""Per-phase agent runner + spectrometer-aligned flag API.

Replaces the master Start/Pause/Resume/Stop autonomy bar. Every phase
tile owns its own subprocess; the user clicks Run on the tile, the
backend spawns the corresponding scripts/<phase>-claude.sh, and the
tile flips to running.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from orchestration.agent import phase_runner
from orchestration.plan_store.session import (
    get_experiment,
    set_spectrometer_aligned,
)
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/phase", tags=["phase"])


@router.post("/run/{slug}")
async def run_phase(slug: str):
    try:
        info = phase_runner.start(slug)
    except ValueError as e:
        # 409 if already running; 400/404 for unknown slug or missing script.
        msg = str(e)
        code = 409 if "already running" in msg else 400
        raise HTTPException(code, msg)
    return {"ok": True, **info}


@router.post("/kill/{slug}")
async def kill_phase(slug: str):
    try:
        info = phase_runner.kill(slug)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, **info}


@router.get("/run_status")
async def run_status():
    return {"phases": phase_runner.status_all()}


@router.post("/spectrometer_aligned")
async def post_spectrometer_aligned(payload: dict):
    """Set/clear the operator-confirmed spectrometer-alignment flag."""
    experiment_id = (
        (payload or {}).get("experiment_id")
        or spec_cmd.get_experiment_id()
    )
    if not experiment_id:
        raise HTTPException(400, "experiment_id required")
    aligned = bool((payload or {}).get("aligned", True))
    exp = set_spectrometer_aligned(experiment_id, aligned)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return {"ok": True, "experiment_id": experiment_id, "aligned": exp.spectrometer_aligned}


@router.get("/spectrometer_aligned")
async def get_spectrometer_aligned(experiment_id: str):
    exp = get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return {
        "experiment_id": experiment_id,
        "aligned": bool(getattr(exp, "spectrometer_aligned", False)),
        "mono_crystal": exp.mono_crystal,
    }
