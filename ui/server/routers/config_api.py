"""Experiment configuration API (ported from beamline/web/app.py).

Exposes the same endpoints the existing form.js calls, but as FastAPI
routes so we can serve the form from the main process.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import select

from ui.config import CONFIG_DIR
from orchestration.config_generator import (
    generate_config,
    sanitize_spec_string,
    validate_experiment_data,
    validate_sample_holder_data,
)
from orchestration.plan_store.session import (
    create_experiment,
    create_experiment_element,
    create_sample_holder,
    create_sample_position,
    get_active_experiment,
    get_elements_for_experiment,
    get_experiment,
    get_sample_holder_by_name,
    get_samples_for_holder,
    get_session,
)
from orchestration.plan_store.models import Experiment, ExperimentElement, SampleHolder, SamplePosition

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["config"])


_DEFAULTS_PATH = CONFIG_DIR / "defaults.yaml"


def _load_defaults() -> dict:
    with open(_DEFAULTS_PATH) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _delete_experiment_elements(experiment_id: str) -> None:
    with get_session() as session:
        stmt = select(ExperimentElement).where(
            ExperimentElement.experiment_id == experiment_id
        )
        for e in session.exec(stmt).all():
            session.delete(e)
        session.commit()


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/defaults")
def get_defaults():
    return _load_defaults()


@router.post("/submit_experiment")
async def submit_experiment(data: dict):
    try:
        errors = validate_experiment_data(data)
        if errors:
            return JSONResponse({"success": False, "errors": errors}, status_code=400)

        exp_name = data["experiment_name"].strip()
        # Experimenter is optional now (per beamline change). The legacy
        # autonomous.db has a NOT NULL constraint on this column from the
        # original schema, and SQLite can't ALTER that without rebuilding
        # the table — so we store "" rather than NULL when none is given.
        experimenter = (data.get("experimenter") or "").strip()
        mono_crystal = data["mono_crystal"]
        beam_size_h = data.get("beam_size_h", "big")
        beam_size_v = data.get("beam_size_v", "big")
        mirrors_out = bool(data.get("mirrors_out", False))
        sample_env = data.get("sample_env", "ambient")
        data_dir = data.get("data_directory", "").strip()
        if not data_dir:
            data_dir = f"/data/fifteen/{sanitize_spec_string(exp_name)}"

        llm_enabled = data.get("llm_enabled", True)
        llm_decide_enabled = data.get("llm_decide_enabled", True)

        existing_id = data.get("experiment_id")
        if existing_id:
            exp = get_experiment(existing_id)
            if exp:
                _delete_experiment_elements(existing_id)
                with get_session() as session:
                    exp = session.get(Experiment, existing_id)
                    exp.name = exp_name
                    exp.experimenter = experimenter
                    exp.mono_crystal = mono_crystal
                    exp.beam_size_h = beam_size_h
                    exp.beam_size_v = beam_size_v
                    exp.mirrors_out = mirrors_out
                    exp.sample_env = sample_env
                    exp.data_path = data_dir
                    session.add(exp)
                    session.commit()
                    session.refresh(exp)
            else:
                existing_id = None

        if not existing_id:
            exp = create_experiment(
                name=exp_name,
                experimenter=experimenter,
                mono_crystal=mono_crystal,
                beam_size_h=beam_size_h,
                beam_size_v=beam_size_v,
                mirrors_out=mirrors_out,
                sample_env=sample_env,
                data_path=data_dir,
            )
        experiment_id = exp.id

        # The only experiment-level overrides we still store in
        # config_yaml are the LLM flags. Per-channel gains moved to
        # the per-sample row.
        config_extra = {
            "llm_enabled": llm_enabled,
            "llm_decide_enabled": llm_decide_enabled,
        }
        with get_session() as session:
            exp_db = session.get(Experiment, experiment_id)
            exp_db.config_yaml = yaml.dump(config_extra)
            session.add(exp_db)
            session.commit()

        elements_data = data.get("elements", [])
        for i, el in enumerate(elements_data):
            mode = (el.get("measurement_mode") or "XES").upper()
            crystal_hkl = (el.get("crystal_hkl") or "0 0 0").strip() or "0 0 0"
            create_experiment_element(
                experiment_id=experiment_id,
                element_symbol=el["symbol"].strip(),
                edge=el["edge"],
                measurement_mode=mode,
                emission_line=(el.get("emission_line") or None) if mode == "XES" else None,
                incident_energy_eV=float(el["incident_energy"]),
                emission_energy_eV=float(el.get("emission_energy") or 0),
                crystal_type=int(el.get("crystal_type", 0)),
                crystal_hkl=crystal_hkl,
                row_radius=int(el.get("row_radius", 1000) or 1000),
                n_crystals=int(el.get("n_crystals", 3) or 3),
                vortex_channel=int(el.get("vortex_channel", 1) or 1),
                priority=i,
            )

        elem_summary = ", ".join(f"{el['symbol']} {el['edge']}" for el in elements_data)
        return {
            "success": True,
            "experiment_id": experiment_id,
            "message": f"Experiment '{exp_name}' saved. Now configure sample holders.",
            "summary": {
                "experiment": exp_name,
                "elements": elem_summary,
                "mono_crystal": mono_crystal,
                "beam_size": f"H:{beam_size_h} V:{beam_size_v}",
            },
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"success": False, "errors": [f"Server error: {e}"]}, status_code=500)


@router.post("/submit_sample_holder")
async def submit_sample_holder(data: dict):
    try:
        experiment_id = data.get("experiment_id")
        if not experiment_id:
            return JSONResponse({"success": False, "errors": ["No experiment selected"]}, status_code=400)
        exp = get_experiment(experiment_id)
        if not exp:
            return JSONResponse({"success": False, "errors": ["Experiment not found"]}, status_code=404)

        elements = get_elements_for_experiment(experiment_id)
        element_names = {el.element_symbol for el in elements}
        errors = validate_sample_holder_data(data, element_names)
        if errors:
            return JSONResponse({"success": False, "errors": errors}, status_code=400)

        holder_name = data["sample_holder_name"].strip()
        sample_env = exp.sample_env or "ambient"
        samples_data = data.get("samples", [])
        holder_type = sample_env if sample_env in ("cryostat", "flat", "electrode") else "flat"
        element_emission = {el.element_symbol: el.emission_energy_eV for el in elements}

        existing_holder = get_sample_holder_by_name(experiment_id, holder_name)
        if existing_holder:
            with get_session() as session:
                stmt = select(SamplePosition).where(
                    SamplePosition.sample_holder_id == existing_holder.id
                )
                for sp in session.exec(stmt).all():
                    session.delete(sp)
                h = session.get(SampleHolder, existing_holder.id)
                h.updated_at = datetime.now()
                h.holder_type = holder_type
                h.n_samples = len(samples_data)
                session.add(h)
                session.commit()
                session.refresh(h)
            holder = h
        else:
            holder = create_sample_holder(
                experiment_id=experiment_id,
                name=holder_name,
                n_samples=len(samples_data),
                holder_type=holder_type,
            )

        for i, s in enumerate(samples_data, 1):
            elem_sym = s["element"].strip()
            emiss_eV = element_emission.get(elem_sym)
            create_sample_position(
                experiment_id=experiment_id,
                sample_holder_id=holder.id,
                sample_number=i,
                sample_name=s["name"].strip(),
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
                emiss_energy_eV=emiss_eV,
                total_spots=int(s.get("total_spots", 1)),
                enabled=s.get("enabled", True),
                do_xas=s.get("do_xas", True),
                xas_reps=int(s.get("xas_reps", 10)),
                xas_time=float(s.get("xas_time", 0.5)),
                xas_filter=int(s.get("xas_filter", 0)),
                xas_emiss_override=_float_or_none(s.get("xas_emiss_override")),
                do_rixs=s.get("do_rixs", False),
                rixs_time=float(s.get("rixs_time", 1.0)),
                rixs_start=_float_or_none(s.get("rixs_start")),
                rixs_end=_float_or_none(s.get("rixs_end")),
                rixs_step=float(s.get("rixs_step", -0.2)),
                rixs_filter=int(s.get("rixs_filter", 0)),
                i0_gain=(s.get("i0_gain") or None),
                i0_offset=(s.get("i0_offset") or None),
                i1_gain=(s.get("i1_gain") or None),
            )

        try:
            generate_config(experiment_id)
        except Exception as e:
            logger.warning("config_generator failed (non-fatal): %s", e)

        # If an experiment plan already exists, rebuild it so the agent
        # immediately sees the new/edited holder samples. Safe no-op if
        # no plan is present yet.
        try:
            from orchestration.planner import planner
            from orchestration.plan_store.client import get_experiment_plan as _get_plan
            if _get_plan(experiment_id):
                planner.rebuild_plan_preserving_progress(experiment_id)
        except Exception as e:
            logger.warning("plan rebuild on holder save skipped: %s", e)

        return {
            "success": True,
            "experiment_id": experiment_id,
            "holder_id": holder.id,
            "message": (
                f"Sample holder '{holder_name}' saved with {len(samples_data)} samples. "
                "Click 'Start autonomous run' to hand over to the agent."
            ),
            "summary": {"holder": holder_name, "n_samples": len(samples_data)},
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"success": False, "errors": [f"Server error: {e}"]}, status_code=500)


@router.get("/experiment_summary/{experiment_id}")
def experiment_summary(experiment_id: str):
    exp = get_experiment(experiment_id)
    if exp is None:
        return JSONResponse({"success": False, "error": "Experiment not found"}, status_code=404)
    elements = get_elements_for_experiment(experiment_id)
    return {
        "success": True,
        "experiment": {
            "id": exp.id, "name": exp.name, "experimenter": exp.experimenter,
            "mono_crystal": exp.mono_crystal, "beam_size_h": exp.beam_size_h,
            "beam_size_v": exp.beam_size_v, "mirrors_out": exp.mirrors_out,
            "sample_env": exp.sample_env or "ambient",
        },
        "elements": [
            {
                "symbol": el.element_symbol,
                "edge": el.edge,
                "measurement_mode": getattr(el, "measurement_mode", "XES") or "XES",
            }
            for el in elements
        ],
    }


@router.get("/load_experiment/{experiment_id}")
def load_experiment(experiment_id: str):
    exp = get_experiment(experiment_id)
    if exp is None:
        return JSONResponse({"success": False, "error": "Experiment not found"}, status_code=404)
    elements = get_elements_for_experiment(experiment_id)
    config_extra = {}
    if exp.config_yaml:
        try:
            config_extra = yaml.safe_load(exp.config_yaml) or {}
        except yaml.YAMLError:
            config_extra = {}
    # Holders + samples
    holders = []
    samples_flat: list[dict] = []
    with get_session() as session:
        for h in session.exec(
            select(SampleHolder).where(SampleHolder.experiment_id == experiment_id)
        ):
            samples = get_samples_for_holder(h.id)
            holder_samples = [
                {
                    "name": s.sample_name, "element": s.element_symbol,
                    "sample_number": s.sample_number,
                    "sx_lo": s.sx_lo, "sx_hi": s.sx_hi, "sx_del": s.sx_del,
                    "sy_lo": s.sy_lo, "sy_hi": s.sy_hi, "sy_del": s.sy_del,
                    "sz_lo": s.sz_lo, "sz_hi": s.sz_hi, "sz_del": s.sz_del,
                    "enabled": s.enabled,
                    "do_xas": s.do_xas, "xas_reps": s.xas_reps,
                    "xas_time": s.xas_time, "xas_filter": s.xas_filter,
                    "xas_emiss_override": s.xas_emiss_override,
                    "do_rixs": s.do_rixs, "rixs_time": s.rixs_time,
                    "rixs_start": s.rixs_start, "rixs_end": s.rixs_end,
                    "rixs_step": s.rixs_step, "rixs_filter": s.rixs_filter,
                    "i0_gain": getattr(s, "i0_gain", None) or "",
                    "i0_offset": getattr(s, "i0_offset", None) or "",
                    "i1_gain": getattr(s, "i1_gain", None) or "",
                    "sample_id": s.id,
                }
                for s in samples
            ]
            holders.append({
                "id": h.id, "name": h.name, "holder_type": h.holder_type,
                "samples": holder_samples,
            })
            samples_flat.extend(holder_samples)

    primary_holder = holders[0] if holders else None
    exp_payload = {
        "id": exp.id, "name": exp.name, "experimenter": exp.experimenter,
        "mono_crystal": exp.mono_crystal, "beam_size_h": exp.beam_size_h,
        "beam_size_v": exp.beam_size_v, "mirrors_out": exp.mirrors_out,
        "sample_env": exp.sample_env or "ambient",
        "data_path": exp.data_path, "status": exp.status,
        "sample_holder_name": primary_holder["name"] if primary_holder else "",
        **{k: v for k, v in config_extra.items()
           if k in ("llm_enabled", "llm_decide_enabled")},
    }
    return {
        "success": True,
        "experiment": exp_payload,
        "elements": [
            {
                "symbol": el.element_symbol, "edge": el.edge,
                "measurement_mode": getattr(el, "measurement_mode", "XES") or "XES",
                "emission_line": getattr(el, "emission_line", None) or "",
                "incident_energy": el.incident_energy_eV,
                "emission_energy": el.emission_energy_eV,
                "crystal_type": el.crystal_type, "crystal_hkl": el.crystal_hkl,
                "row_radius": el.row_radius, "n_crystals": el.n_crystals,
                "vortex_channel": el.vortex_channel,
            }
            for el in elements
        ],
        "holders": holders,
        # form.js looks for `samples` at the top level on initial load
        "samples": samples_flat,
    }


@router.get("/load_active")
def load_active():
    exp = get_active_experiment()
    if exp is None:
        return JSONResponse({"success": False, "error": "No active experiment"}, status_code=404)
    return load_experiment(exp.id)


@router.post("/element_info")
async def element_info(data: dict):
    """Edges + emission lines for an element, filtered by accessible energy.

    Powers the element-card edge dropdown and the per-edge emission-line
    dropdown. Lines are sorted by intensity (strongest first) within
    each edge; everything outside the beamline's accessible energy
    range (defaults.yaml accessible_energy_range_eV) is dropped.
    """
    symbol = (data.get("symbol") or "").strip()
    if not symbol:
        return JSONResponse({"success": False, "error": "symbol required"}, status_code=400)

    try:
        import xraydb  # type: ignore
    except ImportError:
        return JSONResponse({
            "success": False,
            "error": "xraydb not installed (pip install xraydb)",
        }, status_code=500)

    defaults = _load_defaults()
    erange = defaults.get("accessible_energy_range_eV", [4000, 25000])
    emin, emax = float(erange[0]), float(erange[1])

    edges: list[dict] = []
    for edge_name in ("K", "L1", "L2", "L3"):
        try:
            ed = xraydb.xray_edge(symbol, edge_name)
        except (ValueError, KeyError):
            ed = None
        if ed is not None and emin <= ed.energy <= emax:
            edges.append({"edge": edge_name, "energy": round(ed.energy, 1)})

    lines_by_edge: dict[str, list[dict]] = {}
    try:
        all_lines = xraydb.xray_lines(symbol)
    except (ValueError, KeyError):
        all_lines = {}
    for line_name, info in (all_lines or {}).items():
        if info is None or not (emin <= info.energy <= emax):
            continue
        edge_key = info.initial_level  # e.g. "K", "L3"
        lines_by_edge.setdefault(edge_key, []).append({
            "line": line_name,
            "energy": round(info.energy, 1),
            "intensity": round(info.intensity, 4),
        })
    for edge_key in lines_by_edge:
        lines_by_edge[edge_key].sort(key=lambda ln: -ln["intensity"])

    return {
        "success": True,
        "symbol": symbol,
        "energy_range": [emin, emax],
        "edges": edges,
        "lines_by_edge": lines_by_edge,
    }


@router.post("/lookup_energy")
async def lookup_energy(data: dict):
    symbol = (data.get("symbol") or "").strip()
    edge = (data.get("edge") or "").strip()
    if not symbol or not edge:
        return JSONResponse({"success": False, "error": "symbol and edge required"}, status_code=400)

    try:
        import xraydb  # type: ignore
    except ImportError:
        return JSONResponse({
            "success": False,
            "error": "xraydb not installed (pip install xraydb) — energies must be entered manually.",
        }, status_code=500)

    edge_data = xraydb.xray_edge(symbol, edge)
    if edge_data is None:
        return JSONResponse({"success": False, "error": f"No edge data for {symbol} {edge}"}, status_code=404)

    incident_energy = edge_data.energy
    emission_energy = None
    emission_line = None
    edge_to_lines = {
        "K": ["Ka1", "Ka2", "Kb1"],
        "L1": ["Lb3", "Lb4"],
        "L2": ["Lb1", "Lg1"],
        "L3": ["La1", "La2", "Lb2"],
    }
    for line_name in edge_to_lines.get(edge, []):
        try:
            edata = xraydb.xray_line(symbol, line_name)
            if edata is not None:
                emission_energy = edata.energy
                emission_line = line_name
                break
        except (ValueError, KeyError):
            continue
    return {
        "success": True,
        "edge_energy": round(incident_energy, 1),
        "incident_energy": round(incident_energy + 200, 1),
        "emission_energy": round(emission_energy, 1) if emission_energy else None,
        "emission_line": emission_line,
    }


@router.get("/experiments")
def list_experiments(limit: int = 20):
    """List recent experiments (for the dashboard experiment selector)."""
    with get_session() as session:
        stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit)
        return [
            {
                "id": e.id, "name": e.name, "experimenter": e.experimenter,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "sample_env": e.sample_env,
            }
            for e in session.exec(stmt)
        ]
