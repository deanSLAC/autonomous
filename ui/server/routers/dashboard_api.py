"""Dashboard API (ported from beamline/db/server.py)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import select

from beamtimehero_cli.action_log.db import recent_actions, recent_queries
from orchestration.plan_store.client import (
    get_plan,
    list_open_interventions,
    list_guidance,
    list_phase_transitions,
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


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _holder_pacing(experiment_id: str) -> dict:
    try:
        from orchestration.planner.planner import compute_holder_pacing
        return compute_holder_pacing(experiment_id)
    except Exception:
        return {}



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

    # Live SPEC-derived scan_count fallback. ScanRecord rows aren't
    # currently produced by any agent path, so without this every tile
    # would show 0 scans even mid-run. We count scans whose date_time
    # falls within each phase_run's [started_at, completed_at] window
    # (or [started_at, now] if still running). When ScanRecord rows
    # later start being written, the agent-side count above (which is
    # authoritative — it knows iterations / LLM consults / anomalies)
    # takes precedence.
    needs_spec_count = [
        r for r in phase_runs
        if scan_aggs.get(r.id, {}).get("scan_count", 0) == 0 and r.started_at
    ]
    if needs_spec_count:
        try:
            from beamtimehero_cli.spec_data import local_data
            all_scans = local_data._all_scans_sorted()
        except Exception:
            all_scans = []
        for r in needs_spec_count:
            start = r.started_at
            end = r.completed_at or datetime.now()
            count = 0
            for s in all_scans:
                dt_str = s.get("date_time")
                if not dt_str:
                    continue
                try:
                    dt = datetime.fromisoformat(dt_str)
                except (TypeError, ValueError):
                    continue
                if start <= dt <= end:
                    count += 1
            scan_aggs[r.id]["scan_count"] = count

    plan = get_plan(experiment_id) or {}
    current_phase = plan.get("phase", "setup") if plan else "setup"
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
             "vortex_counter": e.vortex_counter or "vortDT"}
            for e in elements
        ],
        "holders": [
            {
                "id": h.id, "name": h.name, "type": h.holder_type,
                "n_samples": h.n_samples, "status": h.status,
                "beamtime_hours": h.beamtime_hours,
                "stop_time": h.stop_time.isoformat() if getattr(h, "stop_time", None) else None,
            }
            for h in holders
        ],
        "holder_pacing": _holder_pacing(experiment_id),
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
        "action_log": recent_actions(limit=200, experiment_id=experiment_id),
        "query_log": recent_queries(limit=30, experiment_id=experiment_id),
        "phase_transitions": list_phase_transitions(experiment_id),
        "interventions": list_open_interventions(experiment_id),
        "guidance": list_guidance(experiment_id, limit=20),
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

    scan_dicts = [
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
    ]

    # SPEC fallback: when no agent has written ScanRecord rows, surface the
    # raw scans from the SPEC cache that fell within this phase run's
    # window so the detail page has something to show. Per-scan
    # iteration / LLM / anomaly stay null since those are agent-side
    # concepts not present in the SPEC datafile.
    if not scan_dicts and run.started_at:
        try:
            from beamtimehero_cli.spec_data import local_data
            all_scans = local_data._all_scans_sorted()
        except Exception:
            all_scans = []
        start = run.started_at
        end = run.completed_at or datetime.now()
        for s in all_scans:
            dt_str = s.get("date_time")
            if not dt_str:
                continue
            try:
                dt = datetime.fromisoformat(dt_str)
            except (TypeError, ValueError):
                continue
            if not (start <= dt <= end):
                continue
            cmd = s.get("scan_command") or ""
            parts = cmd.split()
            scan_type = parts[0] if parts else None
            motor_name = parts[1] if len(parts) > 1 else None
            scan_dicts.append({
                "id": None, "scan_number": s.get("scan_number"),
                "motor_name": motor_name, "scan_type": scan_type,
                "command": cmd,
                "result_position": None, "peak_intensity": None,
                "fwhm": None, "centroid": None,
                "anomaly": False, "anomaly_reason": None,
                "timestamp": dt_str,
                "decision_action": None, "decision_command": None,
                "decision_confidence": None,
                "llm_consulted": False, "iteration": None,
                "spec_file": s.get("file_name"),
            })
        # SPEC results came in date-desc; flip to chronological for display.
        scan_dicts.sort(key=lambda d: d.get("scan_number") or 0)

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
        "scans": scan_dicts,
    }


@router.get("/image")
def image(path: str):
    # Only serve files from the runtime data tree (phase reports, tool
    # plots) — this endpoint must not be an arbitrary-file-read.
    from orchestration.config import DATA_DIR

    try:
        p = Path(path).resolve()
        allowed = p.is_relative_to(DATA_DIR.resolve())
    except (OSError, ValueError):
        allowed = False
    if not allowed:
        raise HTTPException(403, "path outside the data directory")
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "image not found")
    return FileResponse(str(p))


