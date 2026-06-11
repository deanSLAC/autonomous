"""Plan-steering API.

Implements the "steerable experiment plan" from slide 09 of the design
deck: users can add, remove, reorder, and skip samples, adjust scan
counts, extend the beamtime budget, and tune quality thresholds. Every
edit is attributed to its author and persisted in the PlanEdit audit
log, so staff and remote users share a single history of changes.

Request bodies are validated by the pydantic models in
ui/server/schemas.py — a misspelled key or wrong type is a field-named
422 instead of a silently-ignored key.
"""

from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, HTTPException

from orchestration.plan_store.client import (
    list_plan_edits,
    get_plan,
    log_plan_edit,
)
from orchestration import runtime_state
from orchestration.plan_store.session import get_experiment
from orchestration.planner import planner
from ui.server.schemas import (
    AddSampleIn,
    HolderTimeBudgetIn,
    PlanEditIn,
    RegenerateIn,
    ReorderIn,
    SampleRefIn,
    SampleTimeBudgetIn,
    SetEndTimeIn,
    UpdateSampleIn,
    UpdateThresholdsIn,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["plan"])


def _require_experiment(experiment_id: str | None) -> str:
    xid = experiment_id or runtime_state.get_experiment_id()
    if not xid:
        raise HTTPException(400, "experiment_id required (or start an experiment first)")
    if get_experiment(xid) is None:
        raise HTTPException(404, f"experiment {xid} not found")
    return xid


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("/{experiment_id}")
def read_plan(experiment_id: str):
    plan = get_plan(experiment_id)
    if plan is None:
        raise HTTPException(404, "plan not found — start the autonomous run first")
    return {
        "plan": plan,
        "edits": list_plan_edits(experiment_id, limit=50),
    }


@router.get("/{experiment_id}/edits")
def get_edits(experiment_id: str, limit: int = 100):
    return {"edits": list_plan_edits(experiment_id, limit=limit)}


# ---------------------------------------------------------------------------
# Sample queue edits
# ---------------------------------------------------------------------------

@router.post("/add_sample")
async def add_sample(body: AddSampleIn):
    xid = _require_experiment(body.experiment_id)
    sample_id = body.sample_id or f"user-{uuid.uuid4().hex[:10]}"
    entry = planner.add_sample_to_plan(
        xid,
        sample_id=sample_id,
        sample_name=body.sample_name,
        element_symbol=body.element_symbol,
        holder_id=body.holder_id,
        modes=body.modes,
        position=body.position,
    )
    log_plan_edit(
        xid, author=body.author, action="add_sample",
        target_id=sample_id,
        payload={"sample": entry, "position": body.position},
        reason=body.reason,
    )
    return {"ok": True, "sample": entry}


@router.post("/remove_sample")
async def remove_sample(body: SampleRefIn):
    xid = _require_experiment(body.experiment_id)
    ok = planner.remove_sample_from_plan(xid, body.sample_id)
    if not ok:
        raise HTTPException(404, f"sample {body.sample_id} not in plan")
    log_plan_edit(
        xid, author=body.author, action="remove_sample", target_id=body.sample_id,
        payload={}, reason=body.reason,
    )
    return {"ok": True}


@router.post("/skip_sample")
async def skip_sample(body: SampleRefIn):
    xid = _require_experiment(body.experiment_id)
    ok = planner.skip_sample(xid, body.sample_id, note=body.note)
    if not ok:
        raise HTTPException(404, f"sample {body.sample_id} not in plan")
    log_plan_edit(
        xid, author=body.author, action="skip", target_id=body.sample_id,
        payload={"note": body.note}, reason=body.reason,
    )
    return {"ok": True}


@router.post("/reorder")
async def reorder(body: ReorderIn):
    xid = _require_experiment(body.experiment_id)
    planner.reorder_plan(xid, body.order)
    log_plan_edit(
        xid, author=body.author, action="reorder", payload={"order": body.order},
        reason=body.reason,
    )
    return {"ok": True}


@router.post("/update_sample")
async def update_sample(body: UpdateSampleIn):
    xid = _require_experiment(body.experiment_id)
    ok = planner.update_sample_params(
        xid, body.sample_id,
        modes=body.modes,
        status=body.status,
        snr_target=body.snr_target,
        note=body.note,
    )
    if not ok:
        raise HTTPException(404, f"sample {body.sample_id} not in plan")
    log_plan_edit(
        xid, author=body.author, action="update_params", target_id=body.sample_id,
        payload={"modes": body.modes, "status": body.status,
                 "snr_target": body.snr_target, "note": body.note},
        reason=body.reason,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Budget + thresholds
# ---------------------------------------------------------------------------

@router.post("/set_end_time")
async def set_end_time(body: SetEndTimeIn):
    """Set the absolute end-of-beamtime timestamp (replaces the old
    extend_budget / set_budget endpoints)."""
    from datetime import datetime as _dt, timedelta as _td
    from orchestration.plan_store.session import set_experiment_end_time
    from orchestration.plan_store.timeutils import parse_iso_to_local_naive

    xid = _require_experiment(body.experiment_id)
    if body.end_time is not None:
        try:
            new_end = parse_iso_to_local_naive(body.end_time)
        except ValueError as e:
            raise HTTPException(400, f"end_time must be ISO-8601: {e}")
    else:
        new_end = _dt.now() + _td(hours=body.hours_from_now)

    row = set_experiment_end_time(xid, new_end)
    if row is None:
        raise HTTPException(404, f"experiment {xid} not found")

    log_plan_edit(
        xid, author=body.author, action="set_end_time",
        payload={"end_time": new_end.isoformat()},
        reason=body.reason,
    )
    return {
        "ok": True,
        "end_time": new_end.isoformat(),
        "remaining_hours": max(0.0, (new_end - _dt.now()).total_seconds() / 3600),
    }


@router.post("/update_thresholds")
async def update_thresholds(body: UpdateThresholdsIn):
    xid = _require_experiment(body.experiment_id)
    thresholds = planner.update_thresholds(
        xid,
        snr_target=body.snr_target,
        min_reps_per_sample=body.min_reps_per_sample,
        max_drift_ev=body.max_drift_ev,
    )
    log_plan_edit(
        xid, author=body.author, action="update_thresholds",
        payload={"thresholds": thresholds},
        reason=body.reason,
    )
    return {"ok": True, "thresholds": thresholds}


# ---------------------------------------------------------------------------
# Per-holder and per-sample time budgets
# ---------------------------------------------------------------------------

@router.post("/set_sample_time_budget")
async def set_sample_time_budget(body: SampleTimeBudgetIn):
    xid = _require_experiment(body.experiment_id)
    ok = planner.set_sample_time_budget(
        xid,
        body.sample_id,
        count_time_s=body.count_time_s,
        reps=body.reps,
        mode=body.mode,
    )
    if not ok:
        raise HTTPException(404, f"sample {body.sample_id} not in plan")
    log_plan_edit(
        xid, author=body.author, action="set_sample_time_budget",
        target_id=body.sample_id,
        payload={"count_time_s": body.count_time_s, "reps": body.reps,
                 "mode": body.mode},
        reason=body.reason,
    )
    return {"ok": True}


@router.post("/set_holder_time_budget")
async def set_holder_time_budget(body: HolderTimeBudgetIn):
    xid = _require_experiment(body.experiment_id)
    summary = planner.set_holder_time_budget(
        xid,
        body.holder_id,
        count_time_s=body.count_time_s,
        reps=body.reps,
        mode=body.mode,
        apply_to_existing=body.apply_to_existing,
    )
    log_plan_edit(
        xid, author=body.author, action="set_holder_time_budget",
        target_id=body.holder_id,
        payload=summary,
        reason=body.reason,
    )
    return {"ok": True, "summary": summary}


@router.post("/regenerate")
async def regenerate(body: RegenerateIn):
    xid = _require_experiment(body.experiment_id)
    new_plan = planner.rebuild_plan_preserving_progress(
        xid,
        beamtime_hours=body.beamtime_hours,
    )
    log_plan_edit(
        xid, author=body.author, action="regenerate",
        payload={"sample_count": len(new_plan.get("sample_queue", []))},
        reason=body.reason,
    )
    return {"ok": True, "sample_count": len(new_plan.get("sample_queue", []))}
