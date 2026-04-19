"""Experiment planner — builds & maintains the run plan.

Responsibilities:

  * Compose an ordered per-sample plan from the experiment config.
  * Track beamtime budget (elapsed / remaining).
  * Produce a short, agent-readable planner status block that the LLM
    receives as system context every turn — anchors the agent to the
    plan without removing its autonomy.
  * Accept revisions (plan dict replaced wholesale) from the agent tool
    `update_experiment_plan`.

Keeps no hidden state; the DB is the source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlmodel import select

from config import DEFAULT_BEAMTIME_HOURS
from db.autonomy_client import get_experiment_plan, upsert_experiment_plan
from db.client import get_session
from db.models import (
    CollectionScan,
    Experiment,
    ExperimentElement,
    PhaseRun,
    SampleHolder,
    SamplePosition,
)


# ---------------------------------------------------------------------------
# Plan representation
# ---------------------------------------------------------------------------

DEFAULT_SNR_TARGET = 8.0          # "efficiency_verdict >= marginal"
DEFAULT_MIN_REPS_PER_SAMPLE = 3   # don't declare a sample done below this


def build_initial_plan(experiment_id: str,
                       beamtime_hours: Optional[float] = None) -> dict:
    """Compose the first-pass plan from the experiment config."""
    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            raise ValueError(f"experiment {experiment_id} not found")
        elements = list(session.exec(
            select(ExperimentElement).where(ExperimentElement.experiment_id == experiment_id)
        ))
        holders = list(session.exec(
            select(SampleHolder).where(SampleHolder.experiment_id == experiment_id)
        ))
        samples = list(session.exec(
            select(SamplePosition).where(SamplePosition.experiment_id == experiment_id)
            .order_by(SamplePosition.sample_holder_id, SamplePosition.sample_number)
        ))

    queue: list[dict] = []
    for s in samples:
        if not s.enabled:
            continue
        modes = []
        if s.do_xas:
            modes.append({
                "mode": "xas",
                "reps": s.xas_reps,
                "count_time_s": s.xas_time,
                "filter_bitmask": s.xas_filter,
                "emiss_override_ev": s.xas_emiss_override,
            })
        if s.do_rixs:
            modes.append({
                "mode": "emiss",
                "emiss_start_ev": s.rixs_start,
                "emiss_end_ev": s.rixs_end,
                "emiss_step_ev": s.rixs_step,
                "count_time_s": s.rixs_time,
                "filter_bitmask": s.rixs_filter,
            })
        queue.append({
            "sample_id": s.id,
            "sample_name": s.sample_name,
            "element_symbol": s.element_symbol,
            "holder_id": s.sample_holder_id,
            "modes": modes,
            "status": "queued",
            "snr_estimate": None,
            "efficiency_verdict": None,
            "reps_completed": 0,
            "notes": [],
        })

    plan = {
        "experiment": {
            "id": exp.id,
            "name": exp.name,
            "experimenter": exp.experimenter,
            "mono_crystal": exp.mono_crystal,
            "beam_size_h": exp.beam_size_h,
            "beam_size_v": exp.beam_size_v,
            "sample_env": exp.sample_env,
        },
        "elements": [
            {
                "symbol": e.element_symbol,
                "edge": e.edge,
                "incident_energy_eV": e.incident_energy_eV,
                "emission_energy_eV": e.emission_energy_eV,
                "n_crystals": e.n_crystals,
                "vortex_channel": e.vortex_channel,
                "crystal_hkl": e.crystal_hkl,
                "row_radius": e.row_radius,
            }
            for e in elements
        ],
        "holders": [{"id": h.id, "name": h.name, "type": h.holder_type} for h in holders],
        "sample_queue": queue,
        "thresholds": {
            "snr_target": DEFAULT_SNR_TARGET,
            "min_reps_per_sample": DEFAULT_MIN_REPS_PER_SAMPLE,
        },
        "budget": {
            "beamtime_total_hours": beamtime_hours or DEFAULT_BEAMTIME_HOURS,
            "started_at": datetime.now().isoformat(),
        },
        "updated_at": datetime.now().isoformat(),
    }

    upsert_experiment_plan(
        experiment_id,
        beamtime_total_hours=plan["budget"]["beamtime_total_hours"],
        plan=plan,
        phase="setup",
    )
    return plan


# ---------------------------------------------------------------------------
# Live budget + progress math
# ---------------------------------------------------------------------------

@dataclass
class PlannerSnapshot:
    experiment_id: str
    phase: str
    beamtime_total_hours: float
    beamtime_elapsed_hours: float
    beamtime_remaining_hours: float
    samples_total: int
    samples_completed: int
    samples_in_progress: int
    samples_queued: int
    plan: dict = field(default_factory=dict)

    def to_system_context(self) -> str:
        return (
            "[PLANNER STATE]\n"
            f"  phase: {self.phase}\n"
            f"  beamtime: {self.beamtime_elapsed_hours:.2f}h elapsed / "
            f"{self.beamtime_total_hours:.2f}h total "
            f"({self.beamtime_remaining_hours:.2f}h remaining)\n"
            f"  samples: {self.samples_completed} done / {self.samples_in_progress} in progress / "
            f"{self.samples_queued} queued ({self.samples_total} total)\n"
            f"  thresholds: SNR target={self.plan.get('thresholds', {}).get('snr_target')}, "
            f"min reps/sample={self.plan.get('thresholds', {}).get('min_reps_per_sample')}\n"
            "  plan updates should go through the `update_experiment_plan` tool "
            "so the user can see the rationale."
        )


def snapshot(experiment_id: str) -> PlannerSnapshot:
    plan = get_experiment_plan(experiment_id) or {}
    plan_body = plan.get("plan", {}) or {}
    sample_queue = plan_body.get("sample_queue", []) or []

    total = len(sample_queue)
    done = sum(1 for s in sample_queue if s.get("status") == "done")
    in_progress = sum(1 for s in sample_queue if s.get("status") == "in_progress")
    queued = total - done - in_progress

    budget = plan_body.get("budget", {}) or {}
    total_hours = float(budget.get("beamtime_total_hours") or plan.get("beamtime_total_hours") or DEFAULT_BEAMTIME_HOURS)
    started_at = budget.get("started_at")

    elapsed = float(plan.get("beamtime_elapsed_hours") or 0.0)
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at)
            elapsed = max(elapsed, (datetime.now() - dt).total_seconds() / 3600)
        except ValueError:
            pass

    remaining = max(0.0, total_hours - elapsed)

    return PlannerSnapshot(
        experiment_id=experiment_id,
        phase=plan.get("phase", "setup"),
        beamtime_total_hours=total_hours,
        beamtime_elapsed_hours=elapsed,
        beamtime_remaining_hours=remaining,
        samples_total=total,
        samples_completed=done,
        samples_in_progress=in_progress,
        samples_queued=queued,
        plan=plan_body,
    )


def record_sample_progress(
    experiment_id: str,
    sample_id: str,
    *,
    status: str | None = None,
    snr_estimate: float | None = None,
    efficiency_verdict: str | None = None,
    reps_completed: int | None = None,
    note: str | None = None,
) -> dict:
    plan = get_experiment_plan(experiment_id) or {}
    body = plan.get("plan", {})
    for s in body.get("sample_queue", []):
        if s.get("sample_id") == sample_id:
            if status is not None:
                s["status"] = status
            if snr_estimate is not None:
                s["snr_estimate"] = snr_estimate
            if efficiency_verdict is not None:
                s["efficiency_verdict"] = efficiency_verdict
            if reps_completed is not None:
                s["reps_completed"] = reps_completed
            if note:
                s.setdefault("notes", []).append(
                    {"ts": datetime.now().isoformat(), "text": note}
                )
            break
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return body


def replace_plan(experiment_id: str, new_plan: dict) -> dict:
    new_plan["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=new_plan)
    return new_plan


def bump_elapsed(experiment_id: str, hours: float) -> None:
    plan = get_experiment_plan(experiment_id) or {}
    elapsed = float(plan.get("beamtime_elapsed_hours") or 0.0) + hours
    upsert_experiment_plan(experiment_id, beamtime_elapsed_hours=elapsed)


# ---------------------------------------------------------------------------
# Plan steering (edits applied in one place; every edit persisted to the
# plan blob + appended to the PlanEdit audit table by the API layer).
# ---------------------------------------------------------------------------

def _make_sample_entry(
    *,
    sample_id: str,
    sample_name: str,
    element_symbol: str,
    holder_id: str | None = None,
    modes: list | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "sample_name": sample_name,
        "element_symbol": element_symbol,
        "holder_id": holder_id,
        "modes": modes or [{"mode": "xas", "reps": 3, "count_time_s": 0.5}],
        "status": "queued",
        "snr_estimate": None,
        "efficiency_verdict": None,
        "reps_completed": 0,
        "notes": [],
    }


def _load_plan(experiment_id: str) -> tuple[dict, list[dict]]:
    wrapper = get_experiment_plan(experiment_id) or {}
    body = wrapper.get("plan") or {}
    queue = body.setdefault("sample_queue", [])
    return body, queue


def add_sample_to_plan(
    experiment_id: str,
    *,
    sample_id: str,
    sample_name: str,
    element_symbol: str,
    holder_id: str | None = None,
    modes: list | None = None,
    position: int | None = None,
) -> dict:
    body, queue = _load_plan(experiment_id)
    entry = _make_sample_entry(
        sample_id=sample_id, sample_name=sample_name,
        element_symbol=element_symbol, holder_id=holder_id, modes=modes,
    )
    if position is None or position >= len(queue):
        queue.append(entry)
    else:
        queue.insert(max(0, position), entry)
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return entry


def remove_sample_from_plan(experiment_id: str, sample_id: str) -> bool:
    body, queue = _load_plan(experiment_id)
    before = len(queue)
    body["sample_queue"] = [s for s in queue if s.get("sample_id") != sample_id]
    if len(body["sample_queue"]) == before:
        return False
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return True


def skip_sample(experiment_id: str, sample_id: str, *, note: str | None = None) -> bool:
    body, queue = _load_plan(experiment_id)
    found = False
    for s in queue:
        if s.get("sample_id") == sample_id:
            s["status"] = "skipped"
            if note:
                s.setdefault("notes", []).append(
                    {"ts": datetime.now().isoformat(), "text": note}
                )
            found = True
            break
    if not found:
        return False
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return True


def reorder_plan(experiment_id: str, new_order: list[str]) -> bool:
    """Reorder the queue by sample_id. IDs missing from new_order stay at the end
    in their existing relative order.
    """
    body, queue = _load_plan(experiment_id)
    index = {s.get("sample_id"): s for s in queue}
    reordered: list[dict] = []
    seen: set[str] = set()
    for sid in new_order:
        if sid in index and sid not in seen:
            reordered.append(index[sid])
            seen.add(sid)
    for s in queue:
        if s.get("sample_id") not in seen:
            reordered.append(s)
    body["sample_queue"] = reordered
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return True


def update_sample_params(
    experiment_id: str,
    sample_id: str,
    *,
    modes: list | None = None,
    status: str | None = None,
    snr_target: float | None = None,
    note: str | None = None,
) -> bool:
    body, queue = _load_plan(experiment_id)
    found = False
    for s in queue:
        if s.get("sample_id") != sample_id:
            continue
        if modes is not None:
            s["modes"] = modes
        if status is not None:
            s["status"] = status
        if snr_target is not None:
            s["snr_target"] = snr_target
        if note:
            s.setdefault("notes", []).append(
                {"ts": datetime.now().isoformat(), "text": note}
            )
        found = True
        break
    if not found:
        return False
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return True


def extend_budget(experiment_id: str, hours_delta: float) -> float:
    """Add (or subtract, if negative) hours to the beamtime budget."""
    wrapper = get_experiment_plan(experiment_id) or {}
    body = wrapper.get("plan") or {}
    total = float(wrapper.get("beamtime_total_hours") or 0.0) + hours_delta
    body.setdefault("budget", {})["beamtime_total_hours"] = total
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(
        experiment_id, plan=body, beamtime_total_hours=total,
    )
    return total


def update_thresholds(
    experiment_id: str,
    *,
    snr_target: float | None = None,
    min_reps_per_sample: int | None = None,
    max_drift_ev: float | None = None,
) -> dict:
    body, _ = _load_plan(experiment_id)
    thresholds = body.setdefault("thresholds", {})
    if snr_target is not None:
        thresholds["snr_target"] = snr_target
    if min_reps_per_sample is not None:
        thresholds["min_reps_per_sample"] = min_reps_per_sample
    if max_drift_ev is not None:
        thresholds["max_drift_ev"] = max_drift_ev
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return thresholds
