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

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from orchestration.config_generator import validate_sample_holder_data
from orchestration.plan_store.session import (
    _SENTINEL,
    create_sample_holder,
    create_sample_position,
    delete_sample_holder,
    delete_sample_position,
    get_elements_for_experiment,
    get_experiment,
    get_samples_for_holder,
    get_session,
    list_sample_holders,
    reorder_sample_holders,
    update_sample_holder,
    update_sample_position,
)
from orchestration.plan_store.models import SampleHolder, SamplePosition
from orchestration.planner import planner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sample_holders", tags=["sample_holders"])


# ---------------------------------------------------------------------------
# Request models
#
# Pydantic enforces shape at the boundary so phantom fields (alignment bounds,
# gains, toggles, etc.) sent by an out-of-date client are silently dropped
# rather than reaching the upsert. The upsert then enforces a stricter
# whitelist on top — defense in depth so the form can never clobber data
# owned by alignment / survey / agent phases.
# ---------------------------------------------------------------------------

class SampleIn(BaseModel):
    id: str | None = None
    name: str
    element: str
    xas_time: float | None = None
    xas_filter_suggested: int | None = None
    min_scans: int | None = None


class HolderCreateIn(BaseModel):
    experiment_id: str
    name: str
    holder_type: str | None = None
    status: str | None = None
    notes: str | None = None
    beamtime_hours: float | None = None
    samples: list[SampleIn] = Field(default_factory=list)


class HolderUpdateIn(BaseModel):
    holder_id: str
    name: str | None = None
    holder_type: str | None = None
    status: str | None = None
    notes: str | None = None
    beamtime_hours: float | None = None
    stop_time: str | None = None
    samples: list[SampleIn] | None = None


def _holder_to_dict(h: SampleHolder, samples: list[SamplePosition] | None = None) -> dict:
    return {
        "id": h.id,
        "experiment_id": h.experiment_id,
        "name": h.name,
        "status": h.status,
        "holder_type": h.holder_type,
        "n_samples": h.n_samples,
        "queue_order": h.queue_order,
        "beamtime_hours": h.beamtime_hours,
        "stop_time": h.stop_time.isoformat() if getattr(h, "stop_time", None) else None,
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
                "xas_filter_suggested": s.xas_filter_suggested,
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
                "min_scans": getattr(s, "min_scans", None),
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


# Fields the /sample_holders form is allowed to write. Anything else on
# SamplePosition is owned by alignment / survey / agent phases and must NOT
# be touched by a form save, even if the request payload includes it.
_UI_WRITABLE = {
    "sample_name", "element_symbol", "sample_number",
    "xas_time", "xas_filter_suggested", "min_scans",
}


def _ui_fields(s: dict, sample_number: int) -> dict:
    """Project an incoming sample dict down to the UI-writable whitelist."""
    out = {
        "sample_name": (s.get("name") or "").strip(),
        "element_symbol": (s.get("element") or "").strip(),
        "sample_number": sample_number,
        "xas_time": float(s["xas_time"]) if s.get("xas_time") not in (None, "") else 0.5,
        "xas_filter_suggested": (
            int(s["xas_filter_suggested"])
            if s.get("xas_filter_suggested") not in (None, "")
            else 0
        ),
        "min_scans": (
            int(s["min_scans"]) if s.get("min_scans") not in (None, "") else None
        ),
    }
    assert set(out.keys()) <= _UI_WRITABLE, "leaked non-UI field into upsert"
    return out


def _upsert_samples(holder_id: str, experiment_id: str, samples: list[dict]) -> None:
    """Update existing rows in place, create new ones, delete removed ones.

    Sample IDs are stable across edits so `rebuild_plan_preserving_progress`
    reconnects all per-sample progress. UI-writable fields only — agent
    columns (alignment bounds, gains, survey data, xas_filter, toggles) are
    never touched on an update.
    """
    existing = {sp.id: sp for sp in get_samples_for_holder(holder_id)}
    elements = get_elements_for_experiment(experiment_id)
    element_emission = {e.element_symbol: e.emission_energy_eV for e in elements}
    incoming_ids: set[str] = set()

    for i, s in enumerate(samples, 1):
        ui = _ui_fields(s, i)
        sid = s.get("id")
        if sid and sid in existing:
            update_sample_position(sid, **ui)
            incoming_ids.add(sid)
        else:
            create_sample_position(
                experiment_id=experiment_id,
                sample_holder_id=holder_id,
                **ui,
                emiss_energy_eV=element_emission.get(ui["element_symbol"]),
            )

    for old_id in set(existing) - incoming_ids:
        delete_sample_position(old_id)


def _integrity_error_response(e: IntegrityError) -> JSONResponse:
    """Map SQL integrity violations to actionable messages for the UI."""
    msg = str(getattr(e, "orig", e)).lower()
    if "unique" in msg and "name" in msg:
        return JSONResponse(
            {"success": False, "errors": ["A holder with this name already exists for this experiment."]},
            status_code=400,
        )
    if "foreign key" in msg:
        return JSONResponse(
            {"success": False, "errors": ["Referenced experiment or holder no longer exists."]},
            status_code=400,
        )
    return JSONResponse({"success": False, "errors": [f"Database error: {e}"]}, status_code=400)


@router.post("/create")
async def create(body: HolderCreateIn):
    try:
        exp = get_experiment(body.experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")

        name = body.name.strip()
        if not name:
            raise HTTPException(400, "name required")

        samples = [s.model_dump() for s in body.samples]
        holder_type = (body.holder_type or (exp.sample_env or "flat")).strip()

        elements = get_elements_for_experiment(body.experiment_id)
        element_names = {el.element_symbol for el in elements}
        errors = validate_sample_holder_data(
            {"sample_holder_name": name, "samples": samples}, element_names,
        )
        if errors:
            return JSONResponse({"success": False, "errors": errors}, status_code=400)

        try:
            holder = create_sample_holder(
                experiment_id=body.experiment_id,
                name=name,
                n_samples=len(samples),
                holder_type=holder_type,
                beamtime_hours=body.beamtime_hours,
            )
            _upsert_samples(holder.id, body.experiment_id, samples)
        except IntegrityError as e:
            return _integrity_error_response(e)

        # Regenerate the plan if one exists so new holder samples show up.
        try:
            planner.rebuild_plan_preserving_progress(body.experiment_id)
        except Exception as e:
            logger.info("plan rebuild skipped: %s", e)

        return {
            "success": True,
            "holder": _holder_to_dict(holder, get_samples_for_holder(holder.id)),
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"success": False, "errors": [f"Server error: {e}"]}, status_code=500)


@router.post("/update")
async def update(body: HolderUpdateIn):
    try:
        with get_session() as session:
            h = session.get(SampleHolder, body.holder_id)
        if h is None:
            raise HTTPException(404, "sample holder not found")
        experiment_id = h.experiment_id

        samples = (
            [s.model_dump() for s in body.samples]
            if body.samples is not None
            else None
        )
        if samples is not None:
            elements = get_elements_for_experiment(experiment_id)
            element_names = {el.element_symbol for el in elements}
            errors = validate_sample_holder_data(
                {"sample_holder_name": h.name, "samples": samples}, element_names,
            )
            if errors:
                return JSONResponse({"success": False, "errors": errors}, status_code=400)

        # Distinguish "field omitted from request" (leave alone) from
        # "field sent as null" (explicitly clear). Pydantic exposes this via
        # model_fields_set; omitted fields default to None but aren't in the set.
        fields_set = body.model_fields_set

        # Parse stop_time from ISO-8601 string if present.
        if "stop_time" not in fields_set:
            parsed_stop_time = _SENTINEL
        elif body.stop_time in (None, "", "None"):
            parsed_stop_time = None
        else:
            try:
                parsed_stop_time = datetime.fromisoformat(str(body.stop_time))
            except ValueError:
                return JSONResponse(
                    {"success": False, "errors": [f"stop_time must be ISO-8601: {body.stop_time!r}"]},
                    status_code=400,
                )

        try:
            h = update_sample_holder(
                body.holder_id,
                name=body.name,
                holder_type=body.holder_type,
                status=body.status,
                beamtime_hours=(body.beamtime_hours if "beamtime_hours" in fields_set else _SENTINEL),
                stop_time=parsed_stop_time,
                notes=(body.notes if "notes" in fields_set else None),
            )

            if samples is not None:
                _upsert_samples(body.holder_id, experiment_id, samples)
                with get_session() as session:
                    hh = session.get(SampleHolder, body.holder_id)
                    hh.n_samples = len(samples)
                    hh.updated_at = datetime.now()
                    session.add(hh)
                    session.commit()
        except IntegrityError as e:
            return _integrity_error_response(e)

        try:
            planner.rebuild_plan_preserving_progress(experiment_id)
        except Exception as e:
            logger.info("plan rebuild skipped: %s", e)

        return {
            "success": True,
            "holder": _holder_to_dict(h, get_samples_for_holder(body.holder_id)),
        }
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
