"""Plan-steering API.

Implements the "steerable experiment plan" from slide 09 of the design
deck: users can add, remove, reorder, and skip samples, adjust scan
counts, extend the beamtime budget, and tune quality thresholds. Every
edit is attributed to its author and persisted in the PlanEdit audit
log, so staff and remote users share a single history of changes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from orchestration.plan_store.client import (
    list_plan_edits,
    get_experiment_plan,
    log_plan_edit,
)
from orchestration.plan_store.session import get_experiment
from orchestration.planner import planner
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["plan"])


def _pick_author(body: dict) -> str:
    author = (body.get("author") or "").strip()
    return author or "web-user"


def _require_experiment(experiment_id: str | None) -> str:
    xid = experiment_id or spec_cmd.get_experiment_id()
    if not xid:
        raise HTTPException(400, "experiment_id required (or start an experiment first)")
    if get_experiment(xid) is None:
        raise HTTPException(404, f"experiment {xid} not found")
    return xid


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("/{experiment_id}")
def get_plan(experiment_id: str):
    plan = get_experiment_plan(experiment_id)
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
async def add_sample(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    author = _pick_author(body)
    sample_name = (body.get("sample_name") or "").strip()
    element = (body.get("element_symbol") or "").strip()
    holder_id = body.get("holder_id")
    modes = body.get("modes")
    position = body.get("position")
    if not sample_name or not element:
        raise HTTPException(400, "sample_name and element_symbol are required")

    sample_id = body.get("sample_id") or f"user-{uuid.uuid4().hex[:10]}"
    entry = planner.add_sample_to_plan(
        xid,
        sample_id=sample_id,
        sample_name=sample_name,
        element_symbol=element,
        holder_id=holder_id,
        modes=modes,
        position=position,
    )
    log_plan_edit(
        xid, author=author, action="add_sample",
        target_id=sample_id,
        payload={"sample": entry, "position": position},
        reason=body.get("reason"),
    )
    return {"ok": True, "sample": entry}


@router.post("/remove_sample")
async def remove_sample(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    sample_id = body.get("sample_id")
    if not sample_id:
        raise HTTPException(400, "sample_id required")
    ok = planner.remove_sample_from_plan(xid, sample_id)
    if not ok:
        raise HTTPException(404, f"sample {sample_id} not in plan")
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="remove_sample", target_id=sample_id,
        payload={}, reason=body.get("reason"),
    )
    return {"ok": True}


@router.post("/skip_sample")
async def skip_sample(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    sample_id = body.get("sample_id")
    if not sample_id:
        raise HTTPException(400, "sample_id required")
    note = body.get("note")
    ok = planner.skip_sample(xid, sample_id, note=note)
    if not ok:
        raise HTTPException(404, f"sample {sample_id} not in plan")
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="skip", target_id=sample_id,
        payload={"note": note}, reason=body.get("reason"),
    )
    return {"ok": True}


@router.post("/reorder")
async def reorder(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    order = body.get("order")
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise HTTPException(400, "order must be a list of sample_ids")
    planner.reorder_plan(xid, order)
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="reorder", payload={"order": order},
        reason=body.get("reason"),
    )
    return {"ok": True}


@router.post("/update_sample")
async def update_sample(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    sample_id = body.get("sample_id")
    if not sample_id:
        raise HTTPException(400, "sample_id required")
    ok = planner.update_sample_params(
        xid, sample_id,
        modes=body.get("modes"),
        status=body.get("status"),
        snr_target=body.get("snr_target"),
        note=body.get("note"),
    )
    if not ok:
        raise HTTPException(404, f"sample {sample_id} not in plan")
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="update_params", target_id=sample_id,
        payload={k: body.get(k) for k in ("modes", "status", "snr_target", "note")},
        reason=body.get("reason"),
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Budget + thresholds
# ---------------------------------------------------------------------------

@router.post("/extend_budget")
async def extend_budget(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    try:
        hours = float(body.get("hours", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "hours must be a number")
    new_total = planner.extend_budget(xid, hours)
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="extend_budget",
        payload={"hours_delta": hours, "new_total_hours": new_total},
        reason=body.get("reason"),
    )
    return {"ok": True, "new_total_hours": new_total}


@router.post("/update_thresholds")
async def update_thresholds(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    thresholds = planner.update_thresholds(
        xid,
        snr_target=body.get("snr_target"),
        min_reps_per_sample=body.get("min_reps_per_sample"),
        max_drift_ev=body.get("max_drift_ev"),
    )
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="update_thresholds",
        payload={"thresholds": thresholds},
        reason=body.get("reason"),
    )
    return {"ok": True, "thresholds": thresholds}


@router.post("/set_budget")
async def set_budget(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    try:
        hours = float(body.get("hours_total"))
    except (TypeError, ValueError):
        raise HTTPException(400, "hours_total must be a number")
    new_total = planner.set_budget(xid, hours)
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="set_budget",
        payload={"new_total_hours": new_total},
        reason=body.get("reason"),
    )
    return {"ok": True, "new_total_hours": new_total}


# ---------------------------------------------------------------------------
# Per-holder and per-sample time budgets
# ---------------------------------------------------------------------------

@router.post("/set_sample_time_budget")
async def set_sample_time_budget(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    sample_id = body.get("sample_id")
    if not sample_id:
        raise HTTPException(400, "sample_id required")
    count_time_s = body.get("count_time_s")
    reps = body.get("reps")
    if count_time_s is None and reps is None:
        raise HTTPException(400, "at least one of count_time_s or reps is required")
    ok = planner.set_sample_time_budget(
        xid,
        sample_id,
        count_time_s=count_time_s,
        reps=reps,
        mode=body.get("mode"),
    )
    if not ok:
        raise HTTPException(404, f"sample {sample_id} not in plan")
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="set_sample_time_budget",
        target_id=sample_id,
        payload={"count_time_s": count_time_s, "reps": reps, "mode": body.get("mode")},
        reason=body.get("reason"),
    )
    return {"ok": True}


@router.post("/set_holder_time_budget")
async def set_holder_time_budget(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    count_time_s = body.get("count_time_s")
    reps = body.get("reps")
    if count_time_s is None and reps is None:
        raise HTTPException(400, "at least one of count_time_s or reps is required")
    summary = planner.set_holder_time_budget(
        xid,
        body.get("holder_id"),
        count_time_s=count_time_s,
        reps=reps,
        mode=body.get("mode"),
        apply_to_existing=bool(body.get("apply_to_existing", True)),
    )
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="set_holder_time_budget",
        target_id=body.get("holder_id"),
        payload=summary,
        reason=body.get("reason"),
    )
    return {"ok": True, "summary": summary}


@router.post("/set_phase_enabled")
async def set_phase_enabled(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    phase = (body.get("phase") or "").strip()
    enabled = bool(body.get("enabled"))
    try:
        skipped = planner.set_phase_enabled(xid, phase, enabled)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_plan_edit(
        xid, author=_pick_author(body),
        action="set_phase_enabled",
        target_id=phase,
        payload={"enabled": enabled, "phases_skipped": skipped},
        reason=body.get("reason"),
    )
    return {"ok": True, "phases_skipped": skipped}


@router.post("/regenerate")
async def regenerate(body: dict):
    xid = _require_experiment(body.get("experiment_id"))
    new_plan = planner.rebuild_plan_preserving_progress(
        xid,
        beamtime_hours=body.get("beamtime_hours"),
    )
    author = _pick_author(body)
    log_plan_edit(
        xid, author=author, action="regenerate",
        payload={"sample_count": len(new_plan.get("sample_queue", []))},
        reason=body.get("reason"),
    )
    return {"ok": True, "sample_count": len(new_plan.get("sample_queue", []))}
