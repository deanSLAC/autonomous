"""Per-phase agent runner + spectrometer-aligned flag API.

Replaces the master Start/Pause/Resume/Stop autonomy bar. Every phase
tile owns its own subprocess; the user clicks Run on the tile, the
backend spawns the corresponding scripts/<phase>-claude.sh, and the
tile flips to running.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from orchestration.agent import phase_runner
from orchestration.plan_store.session import (
    get_experiment,
    set_spectrometer_aligned,
)
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/phase", tags=["phase"])


_TAIL_MAX_BYTES = 64 * 1024  # cap each poll's payload


def _tail_file(path: str | None, offset: int) -> dict:
    """Read at most _TAIL_MAX_BYTES from `path` starting at `offset`.

    Returns {path, offset, content, eof} where the new offset is the
    file's end-of-file position after the read. If `offset` is past
    EOF (file rotated/truncated), reset to 0 and re-read from start.
    """
    if not path or not os.path.exists(path):
        return {"path": path, "offset": 0, "content": "", "eof": 0}
    size = os.path.getsize(path)
    if offset > size:
        offset = 0
    end = min(size, offset + _TAIL_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(end - offset)
    return {
        "path": path,
        "offset": end,
        "content": chunk.decode("utf-8", errors="replace"),
        "eof": size,
    }


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


@router.post("/kill_all")
async def kill_all_phases():
    """SIGTERM every running phase agent. Used by the autonomy bar's
    Stop agents button."""
    killed = phase_runner.kill_all()
    return {"ok": True, "killed": killed, "count": len(killed)}


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


@router.get("/log_tail")
async def log_tail(slug: str | None = None, offset: int = 0):
    """Tail the most recent phase agent log.

    If `slug` is given, tails that phase's most recent log. Otherwise
    auto-picks the most recently active slug (running > finished).
    Returns {slug, path, offset, content, eof} so the frontend can
    advance its local offset and detect log rotation.
    """
    target = slug or phase_runner.latest_active_slug()
    if target is None:
        return {"slug": None, "path": None, "offset": 0, "content": "", "eof": 0}
    path = phase_runner.get_log_path(target)
    out = _tail_file(path, offset)
    out["slug"] = target
    return out


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
