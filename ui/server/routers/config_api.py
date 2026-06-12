"""Experiment configuration API (ported from beamline/web/app.py).

Exposes the same endpoints the existing form.js calls, but as FastAPI
routes so we can serve the form from the main process.
"""

from __future__ import annotations

import logging
import traceback

import yaml
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlmodel import select

from ui.config import CONFIG_DIR
from ui.server.schemas import (
    ExperimentIn,
    validation_error_strings,
)
from orchestration.config_generator import (
    generate_config,
    sanitize_spec_string,
)
from orchestration.plan_store.session import (
    create_experiment,
    create_experiment_element,
    get_active_experiment,
    get_elements_for_experiment,
    get_experiment,
    get_samples_for_holder,
    get_session,
)
from orchestration.plan_store.models import Experiment, ExperimentElement, SampleHolder

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/defaults")
def get_defaults():
    return _load_defaults()


@router.post("/submit_experiment")
async def submit_experiment(data: dict):
    try:
        try:
            req = ExperimentIn.model_validate(data)
        except ValidationError as e:
            return JSONResponse(
                {"success": False, "errors": validation_error_strings(e)},
                status_code=400,
            )

        exp_name = req.experiment_name
        # Experimenter is optional now (per beamline change). The legacy
        # autonomous.db has a NOT NULL constraint on this column from the
        # original schema, and SQLite can't ALTER that without rebuilding
        # the table — so we store "" rather than NULL when none is given.
        experimenter = req.experimenter
        mono_crystal = req.mono_crystal
        beam_size_h = req.beam_size_h
        beam_size_v = req.beam_size_v
        mirrors_out = req.mirrors_out
        sample_env = req.sample_env
        data_dir = req.data_directory
        if not data_dir:
            data_dir = f"/data/fifteen/{sanitize_spec_string(exp_name)}"

        # If the user left the foil element blank, default to the first
        # science-target element they configured. The user's rule: "by
        # default the foil will be the element we measure for the
        # experiment". Multiple elements: pick the first (priority 0 in
        # storage; the user's primary target).
        calibration_foil_element = (
            req.calibration_foil_element or req.elements[0].symbol or None
        )
        calibration_foil_detector = req.calibration_foil_detector
        end_time_dt = req.end_time

        existing_id = req.experiment_id
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
                    exp.calibration_foil_element = calibration_foil_element
                    exp.calibration_foil_detector = calibration_foil_detector
                    exp.end_time = end_time_dt
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
                calibration_foil_element=calibration_foil_element,
                calibration_foil_detector=calibration_foil_detector,
            )
        experiment_id = exp.id

        if end_time_dt and not existing_id:
            from orchestration.plan_store.session import set_experiment_end_time
            set_experiment_end_time(experiment_id, end_time_dt)

        for i, el in enumerate(req.elements):
            create_experiment_element(
                experiment_id=experiment_id,
                element_symbol=el.symbol,
                edge=el.edge,
                measurement_mode=el.measurement_mode,
                emission_line=el.emission_line if el.measurement_mode == "XES" else None,
                incident_energy_eV=el.incident_energy,
                emission_energy_eV=el.emission_energy,
                crystal_type=el.crystal_type,
                crystal_hkl=el.crystal_hkl or "0 0 0",
                row_radius=el.row_radius,
                n_crystals=el.n_crystals,
                vortex_counter=el.vortex_counter,
                priority=i,
            )

        elem_summary = ", ".join(f"{el.symbol} {el.edge}" for el in req.elements)
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
            "calibration_foil_element": getattr(exp, "calibration_foil_element", None) or "",
            "calibration_foil_detector": getattr(exp, "calibration_foil_detector", None) or "I2",
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
                    "min_scans": getattr(s, "min_scans", None),
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
        "calibration_foil_element": getattr(exp, "calibration_foil_element", None) or "",
        "calibration_foil_detector": getattr(exp, "calibration_foil_detector", None) or "I2",
        "end_time": exp.end_time.isoformat() if exp.end_time else None,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
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
                "vortex_counter": el.vortex_counter or "vortDT",
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


