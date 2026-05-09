"""Dashboard API (ported from beamline/db/server.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import select

from beamline_tools.action_log.db import recent_actions, recent_queries
from orchestration.plan_store.client import (
    get_experiment_plan,
    list_open_interventions,
    list_guidance,
    list_phase_transitions,
    list_plan_edits,
)
from orchestration.plan_store.session import get_session, get_experiment, get_phase_runs_for_experiment
from orchestration.plan_store.models import (
    Experiment,
    ExperimentElement,
    PhaseRun,
    ScanRecord,
    SampleHolder,
    SamplePosition,
)
from beamline_tools.spec_control import spec_cmd


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/experiments")
def experiments(limit: int = 20):
    with get_session() as session:
        stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit)
        return [
            {
                "id": e.id, "name": e.name, "experimenter": e.experimenter,
                "status": e.status, "sample_env": e.sample_env,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in session.exec(stmt)
        ]


@router.get("/status")
def status(experiment_id: str = Query(...)):
    exp = get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    phase_runs = get_phase_runs_for_experiment(experiment_id)
    with get_session() as session:
        elements = list(session.exec(
            select(ExperimentElement)
            .where(ExperimentElement.experiment_id == experiment_id)
            .order_by(ExperimentElement.priority)
        ))
        holders = list(session.exec(
            select(SampleHolder).where(SampleHolder.experiment_id == experiment_id)
        ))
        # Per-phase-run aggregates the dashboard tiles render
        # (scans, max iteration, LLM consults, anomalies). One query
        # over the experiment's runs and we fold in Python.
        run_ids = [r.id for r in phase_runs]
        scan_aggs: dict[str, dict] = {rid: {
            "scan_count": 0, "max_iteration": 0,
            "llm_count": 0, "anomaly_count": 0,
        } for rid in run_ids}
        if run_ids:
            scan_rows = session.exec(
                select(
                    ScanRecord.phase_run_id,
                    ScanRecord.iteration,
                    ScanRecord.llm_consulted,
                    ScanRecord.anomaly,
                ).where(ScanRecord.phase_run_id.in_(run_ids))  # type: ignore[union-attr]
            )
            for prid, iteration, llm_consulted, anomaly in scan_rows:
                a = scan_aggs[prid]
                a["scan_count"] += 1
                if iteration and iteration > a["max_iteration"]:
                    a["max_iteration"] = iteration
                if llm_consulted:
                    a["llm_count"] += 1
                if anomaly:
                    a["anomaly_count"] += 1

    plan = get_experiment_plan(experiment_id) or {}
    current_phase = spec_cmd.get_phase()
    return {
        "experiment": {
            "id": exp.id, "name": exp.name, "experimenter": exp.experimenter,
            "status": exp.status, "sample_env": exp.sample_env,
            "mono_crystal": exp.mono_crystal, "beam_size_h": exp.beam_size_h,
            "beam_size_v": exp.beam_size_v, "mirrors_out": exp.mirrors_out,
            "data_path": exp.data_path,
            "beam_h_fwhm_um": getattr(exp, "beam_h_fwhm_um", None),
            "beam_v_fwhm_um": getattr(exp, "beam_v_fwhm_um", None),
            "calibration_foil_element": getattr(exp, "calibration_foil_element", None),
            "calibration_foil_detector": getattr(exp, "calibration_foil_detector", None) or "I2",
        },
        "current_phase": current_phase,
        "plan": plan,
        "elements": [
            {"symbol": e.element_symbol, "edge": e.edge, "crystals": e.n_crystals,
             "vortex_channel": e.vortex_channel}
            for e in elements
        ],
        "holders": [{"id": h.id, "name": h.name, "type": h.holder_type, "n_samples": h.n_samples}
                    for h in holders],
        "phase_runs": [
            {
                "id": r.id, "phase": r.phase, "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "first_scan": r.first_scan, "last_scan": r.last_scan,
                "summary_image_path": r.summary_image_path,
                "anomaly_flags": json.loads(r.anomaly_flags) if r.anomaly_flags else None,
                "notes": r.notes,
                **scan_aggs.get(r.id, {
                    "scan_count": 0, "max_iteration": 0,
                    "llm_count": 0, "anomaly_count": 0,
                }),
            }
            for r in phase_runs
        ],
        "action_log": recent_actions(limit=30, experiment_id=experiment_id),
        "query_log": recent_queries(limit=30, experiment_id=experiment_id),
        "phase_transitions": list_phase_transitions(experiment_id),
        "interventions": list_open_interventions(experiment_id),
        "guidance": list_guidance(experiment_id, limit=20),
        "plan_edits": list_plan_edits(experiment_id, limit=30),
    }


@router.get("/phase/{phase_run_id}")
def phase(phase_run_id: str):
    with get_session() as session:
        run = session.get(PhaseRun, phase_run_id)
        if run is None:
            raise HTTPException(404, "Phase run not found")
        scans = list(session.exec(
            select(ScanRecord).where(ScanRecord.phase_run_id == phase_run_id)
            .order_by(ScanRecord.timestamp)
        ))

    return {
        "run": {
            "id": run.id, "experiment_id": run.experiment_id,
            "phase": run.phase, "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "spec_datafile": run.spec_datafile,
            "first_scan": run.first_scan, "last_scan": run.last_scan,
            "summary_image_path": run.summary_image_path,
            "anomaly_flags": json.loads(run.anomaly_flags) if run.anomaly_flags else None,
            "notes": run.notes,
        },
        "scans": [
            {
                "id": s.id, "scan_number": s.scan_number,
                "motor_name": s.motor_name, "scan_type": s.scan_type,
                "command": s.command,
                "result_position": s.result_position, "peak_intensity": s.peak_intensity,
                "fwhm": s.fwhm, "centroid": s.centroid,
                "anomaly": s.anomaly, "anomaly_reason": s.anomaly_reason,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "decision_action": s.decision_action,
                "decision_command": s.decision_command,
                "decision_confidence": s.decision_confidence,
                "llm_consulted": s.llm_consulted,
                "iteration": s.iteration,
            }
            for s in scans
        ],
    }


@router.get("/image")
def image(path: str):
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "image not found")
    return FileResponse(str(p))


@router.get("/action_log")
def action_log(limit: int = 100, experiment_id: Optional[str] = None):
    return {
        "actions": recent_actions(limit=limit, experiment_id=experiment_id),
        "queries": recent_queries(limit=limit, experiment_id=experiment_id),
    }
