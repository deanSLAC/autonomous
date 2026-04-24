"""Multi-holder CRUD + reorder API.

Adds a dedicated surface for listing, creating, editing, deleting, and
reordering sample holders for an experiment. The single-holder
`submit_sample_holder` endpoint in config_api still works, but this
router is what the /sample_holders page uses for its list view.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import select

from orchestration.config_generator import validate_sample_holder_data
from orchestration.plan_store.session import (
    create_sample_holder,
    create_sample_position,
    delete_sample_holder,
    get_elements_for_experiment,
    get_experiment,
    get_samples_for_holder,
    get_session,
    list_sample_holders,
    reorder_sample_holders,
    update_sample_holder,
)
from orchestration.plan_store.models import SampleHolder, SamplePosition
from orchestration.planner import planner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sample_holders", tags=["sample_holders"])


def _float_or_none(val: Any) -> float | None:
    try:
        if val in (None, "", "None"):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _float_or_zero(val: Any) -> float:
    v = _float_or_none(val)
    return 0.0 if v is None else v


def _holder_to_dict(h: SampleHolder, samples: list[SamplePosition] | None = None) -> dict:
    return {
        "id": h.id,
        "experiment_id": h.experiment_id,
        "name": h.name,
        "status": h.status,
        "holder_type": h.holder_type,
        "n_samples": h.n_samples,
        "queue_order": h.queue_order,
        "notes": h.notes,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
        "samples": [
            {
                "id": s.id,
                "sample_number": s.sample_number,
                "name": s.sample_name,
                "element": s.element_symbol,
                "enabled": s.enabled,
                "do_xas": s.do_xas,
                "xas_reps": s.xas_reps,
                "xas_time": s.xas_time,
                "xas_filter": s.xas_filter,
                "xas_emiss_override": s.xas_emiss_override,
                "do_rixs": s.do_rixs,
                "rixs_time": s.rixs_time,
                "rixs_start": s.rixs_start,
                "rixs_end": s.rixs_end,
                "rixs_step": s.rixs_step,
                "rixs_filter": s.rixs_filter,
                "sx_lo": s.sx_lo, "sx_hi": s.sx_hi, "sx_del": s.sx_del,
                "sy_lo": s.sy_lo, "sy_hi": s.sy_hi, "sy_del": s.sy_del,
                "sz_lo": s.sz_lo, "sz_hi": s.sz_hi, "sz_del": s.sz_del,
                "i0_gain": s.i0_gain or "",
                "i0_offset": s.i0_offset or "",
                "i1_gain": s.i1_gain or "",
            }
            for s in (samples or [])
        ],
    }


@router.get("/list")
def list_for_experiment(experiment_id: str):
    exp = get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    holders = list_sample_holders(experiment_id)
    return {
        "holders": [
            _holder_to_dict(h, get_samples_for_holder(h.id))
            for h in holders
        ],
    }


@router.get("/{holder_id}")
def get_holder(holder_id: str):
    with get_session() as session:
        h = session.get(SampleHolder, holder_id)
    if h is None:
        raise HTTPException(404, "sample holder not found")
    return _holder_to_dict(h, get_samples_for_holder(holder_id))


def _persist_samples(holder_id: str, experiment_id: str, samples: list[dict]) -> None:
    # Wipe-and-replace is simplest and matches existing submit_sample_holder.
    with get_session() as session:
        for sp in session.exec(
            select(SamplePosition).where(SamplePosition.sample_holder_id == holder_id)
        ).all():
            session.delete(sp)
        session.commit()

    elements = get_elements_for_experiment(experiment_id)
    element_emission = {e.element_symbol: e.emission_energy_eV for e in elements}
    for i, s in enumerate(samples, 1):
        elem_sym = (s.get("element") or "").strip()
        create_sample_position(
            experiment_id=experiment_id,
            sample_holder_id=holder_id,
            sample_number=i,
            sample_name=(s.get("name") or "").strip(),
            element_symbol=elem_sym,
            sx_lo=_float_or_zero(s.get("sx_lo")),
            sx_hi=_float_or_zero(s.get("sx_hi")),
            sy_lo=_float_or_zero(s.get("sy_lo")),
            sy_hi=_float_or_zero(s.get("sy_hi")),
            sz_lo=_float_or_zero(s.get("sz_lo")),
            sz_hi=_float_or_zero(s.get("sz_hi")),
            sx_del=_float_or_zero(s.get("sx_del")),
            sy_del=_float_or_zero(s.get("sy_del")),
            sz_del=_float_or_zero(s.get("sz_del")),
            emiss_energy_eV=element_emission.get(elem_sym),
            total_spots=int(s.get("total_spots", 1)),
            enabled=bool(s.get("enabled", True)),
            do_xas=bool(s.get("do_xas", True)),
            xas_reps=int(s.get("xas_reps", 10)),
            xas_time=float(s.get("xas_time", 0.5)),
            xas_filter=int(s.get("xas_filter", 0)),
            xas_emiss_override=_float_or_none(s.get("xas_emiss_override")),
            do_rixs=bool(s.get("do_rixs", False)),
            rixs_time=float(s.get("rixs_time", 1.0)),
            rixs_start=_float_or_none(s.get("rixs_start")),
            rixs_end=_float_or_none(s.get("rixs_end")),
            rixs_step=float(s.get("rixs_step", -0.2)),
            rixs_filter=int(s.get("rixs_filter", 0)),
            i0_gain=(s.get("i0_gain") or None),
            i0_offset=(s.get("i0_offset") or None),
            i1_gain=(s.get("i1_gain") or None),
        )


@router.post("/create")
async def create(body: dict):
    try:
        experiment_id = body.get("experiment_id")
        if not experiment_id:
            raise HTTPException(400, "experiment_id required")
        exp = get_experiment(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name required")
        samples = body.get("samples") or []
        holder_type = (body.get("holder_type") or (exp.sample_env or "flat")).strip()

        elements = get_elements_for_experiment(experiment_id)
        element_names = {el.element_symbol for el in elements}
        errors = validate_sample_holder_data(
            {"sample_holder_name": name, "samples": samples}, element_names,
        )
        if errors:
            return JSONResponse({"success": False, "errors": errors}, status_code=400)

        holder = create_sample_holder(
            experiment_id=experiment_id,
            name=name,
            n_samples=len(samples),
            holder_type=holder_type,
        )
        _persist_samples(holder.id, experiment_id, samples)

        # Regenerate the plan if one exists so new holder samples show up.
        try:
            planner.rebuild_plan_preserving_progress(experiment_id)
        except Exception as e:
            logger.info("plan rebuild skipped: %s", e)

        return {"success": True, "holder": _holder_to_dict(holder, get_samples_for_holder(holder.id))}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"success": False, "errors": [f"Server error: {e}"]}, status_code=500)


@router.post("/update")
async def update(body: dict):
    try:
        holder_id = body.get("holder_id")
        if not holder_id:
            raise HTTPException(400, "holder_id required")
        with get_session() as session:
            h = session.get(SampleHolder, holder_id)
        if h is None:
            raise HTTPException(404, "sample holder not found")
        experiment_id = h.experiment_id

        samples = body.get("samples")
        if samples is not None:
            elements = get_elements_for_experiment(experiment_id)
            element_names = {el.element_symbol for el in elements}
            errors = validate_sample_holder_data(
                {"sample_holder_name": h.name, "samples": samples}, element_names,
            )
            if errors:
                return JSONResponse({"success": False, "errors": errors}, status_code=400)

        h = update_sample_holder(
            holder_id,
            name=(body.get("name") or None),
            holder_type=(body.get("holder_type") or None),
            status=(body.get("status") or None),
            notes=(body.get("notes") if "notes" in body else None),
        )

        if samples is not None:
            _persist_samples(holder_id, experiment_id, samples)
            with get_session() as session:
                hh = session.get(SampleHolder, holder_id)
                hh.n_samples = len(samples)
                hh.updated_at = datetime.now()
                session.add(hh)
                session.commit()

        try:
            planner.rebuild_plan_preserving_progress(experiment_id)
        except Exception as e:
            logger.info("plan rebuild skipped: %s", e)

        return {"success": True, "holder": _holder_to_dict(h, get_samples_for_holder(holder_id))}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"success": False, "errors": [f"Server error: {e}"]}, status_code=500)


@router.post("/delete")
async def delete(body: dict):
    holder_id = body.get("holder_id")
    if not holder_id:
        raise HTTPException(400, "holder_id required")
    with get_session() as session:
        h = session.get(SampleHolder, holder_id)
    if h is None:
        raise HTTPException(404, "sample holder not found")
    experiment_id = h.experiment_id
    ok = delete_sample_holder(holder_id)
    if not ok:
        raise HTTPException(500, "delete failed")
    try:
        planner.rebuild_plan_preserving_progress(experiment_id)
    except Exception as e:
        logger.info("plan rebuild skipped: %s", e)
    return {"success": True}


@router.post("/reorder")
async def reorder(body: dict):
    experiment_id = body.get("experiment_id")
    order = body.get("order")
    if not experiment_id:
        raise HTTPException(400, "experiment_id required")
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise HTTPException(400, "order must be a list of holder_ids")
    reorder_sample_holders(experiment_id, order)
    try:
        planner.rebuild_plan_preserving_progress(experiment_id)
    except Exception as e:
        logger.info("plan rebuild skipped: %s", e)
    return {"success": True}
