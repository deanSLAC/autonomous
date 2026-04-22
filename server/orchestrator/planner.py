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
import logging
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
    experiment: dict = field(default_factory=dict)

    def to_system_context(self) -> str:
        exp = self.experiment or {}
        mono = exp.get("mono_crystal")
        mono_label = {"A": "A Si(111)", "B": "B Si(311)"}.get(mono, mono or "?")
        elements = exp.get("elements") or []
        if elements:
            el_line = ", ".join(
                f"{e.get('symbol')} {e.get('edge') or ''}".strip()
                + (f" ({e.get('mode')})" if e.get('mode') else "")
                for e in elements
            )
        else:
            el_line = "(none)"

        # Samples/holders are not preconditions for leaving `setup`.
        # They populate during `sample_alignment`. Make that explicit
        # so the agent does not stall waiting for a queue.
        phase_note = ""
        if self.phase == "setup":
            phase_note = (
                "  NOTE: setup → beamline_alignment only needs experiment_id + "
                "beam good. The sample queue is populated later (during "
                "sample_alignment); an empty queue here is expected.\n"
            )

        return (
            "[PLANNER STATE]\n"
            f"  phase: {self.phase}\n"
            f"  experiment: id={self.experiment_id} "
            f"name={exp.get('name') or '?'} experimenter={exp.get('experimenter') or '?'}\n"
            f"  config: mono={mono_label} sample_env={exp.get('sample_env') or 'ambient'} "
            f"elements=[{el_line}]\n"
            f"  beamtime: {self.beamtime_elapsed_hours:.2f}h elapsed / "
            f"{self.beamtime_total_hours:.2f}h total "
            f"({self.beamtime_remaining_hours:.2f}h remaining)\n"
            f"  samples: {self.samples_completed} done / {self.samples_in_progress} in progress / "
            f"{self.samples_queued} queued ({self.samples_total} total)\n"
            f"  thresholds: SNR target={self.plan.get('thresholds', {}).get('snr_target')}, "
            f"min reps/sample={self.plan.get('thresholds', {}).get('min_reps_per_sample')}\n"
            + phase_note
            + "  plan updates should go through the `update_experiment_plan` tool "
            "so the user can see the rationale."
        )


def snapshot(experiment_id: str) -> PlannerSnapshot:
    plan = get_experiment_plan(experiment_id) or {}
    plan_body = plan.get("plan", {}) or {}
    sample_queue = plan_body.get("sample_queue", []) or []

    # Pull experiment-record metadata so the planner-state prefix the
    # LLM sees every turn actually says "the experiment is configured"
    # — otherwise a fresh run with an empty sample_queue leads the
    # agent to conclude config is missing.
    exp_meta: dict = {}
    try:
        with get_session() as session:
            row = session.get(Experiment, experiment_id)
            if row is not None:
                elems = list(session.exec(
                    select(ExperimentElement).where(
                        ExperimentElement.experiment_id == experiment_id
                    )
                ))
                exp_meta = {
                    "name": row.name,
                    "experimenter": row.experimenter,
                    "mono_crystal": row.mono_crystal,
                    "sample_env": row.sample_env,
                    "beam_size_h": row.beam_size_h,
                    "beam_size_v": row.beam_size_v,
                    "mirrors_out": row.mirrors_out,
                    "status": row.status,
                    "elements": [
                        {
                            "symbol": e.element_symbol,
                            "edge": e.edge,
                            "mode": e.measurement_mode,
                        }
                        for e in elems
                    ],
                }
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning("planner.snapshot: could not read experiment meta: %s", e)

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
        experiment=exp_meta,
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


PHASES_SKIPPABLE = {
    "beamline_alignment",
    "xes_alignment",
    "sample_alignment",
    "collection",
}


def set_phase_enabled(experiment_id: str, phase: str, enabled: bool) -> list[str]:
    """Mark a phase as skipped or enabled. Stored in plan.phases_skipped.

    Disabled phases are auto-passed by the precondition gate — the
    agent can transition past them without running their macros.
    Used for manual override when the operator wants to skip
    bl_align, xes_align, or sample_align (e.g. alignment already
    known-good from a previous session).
    """
    if phase not in PHASES_SKIPPABLE:
        raise ValueError(f"phase {phase!r} is not skippable")
    wrapper = get_experiment_plan(experiment_id) or {}
    body = wrapper.get("plan", {}) or {}
    # Self-heal: an earlier bug (before 2026-04-21) stored the outer
    # wrapper where the body belonged; detect that shape and unwrap.
    while isinstance(body.get("plan"), dict) and (
        "experiment_id" in body or "id" in body
    ):
        body = body["plan"]
    skipped = set(body.get("phases_skipped") or [])
    if enabled:
        skipped.discard(phase)
    else:
        skipped.add(phase)
    body["phases_skipped"] = sorted(skipped)
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return body["phases_skipped"]


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


def set_budget(experiment_id: str, hours_total: float) -> float:
    """Set the beamtime budget to an absolute value (hours)."""
    wrapper = get_experiment_plan(experiment_id) or {}
    body = wrapper.get("plan") or {}
    total = max(0.0, float(hours_total))
    body.setdefault("budget", {})["beamtime_total_hours"] = total
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(
        experiment_id, plan=body, beamtime_total_hours=total,
    )
    return total


def _apply_mode_fields(mode_entry: dict, *, count_time_s, reps) -> None:
    if count_time_s is not None:
        mode_entry["count_time_s"] = float(count_time_s)
    if reps is not None and "reps" in mode_entry:
        mode_entry["reps"] = int(reps)


def set_sample_time_budget(
    experiment_id: str,
    sample_id: str,
    *,
    count_time_s: float | None = None,
    reps: int | None = None,
    mode: str | None = None,
) -> bool:
    """Update the time budget for a single sample.

    `mode` restricts the update to one of the sample's mode entries
    (e.g. 'xas' or 'emiss'). When None, every mode on the sample gets
    updated. Returns False if the sample is not in the queue.
    """
    body, queue = _load_plan(experiment_id)
    updated = False
    for s in queue:
        if s.get("sample_id") != sample_id:
            continue
        modes = s.get("modes") or []
        for m in modes:
            if mode and m.get("mode") != mode:
                continue
            _apply_mode_fields(m, count_time_s=count_time_s, reps=reps)
            updated = True
        if updated:
            s.setdefault("notes", []).append(
                {
                    "ts": datetime.now().isoformat(),
                    "text": f"time budget updated (count_time_s={count_time_s}, reps={reps}, mode={mode or 'all'})",
                }
            )
        break
    if not updated:
        return False
    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return True


def set_holder_time_budget(
    experiment_id: str,
    holder_id: str | None,
    *,
    count_time_s: float | None = None,
    reps: int | None = None,
    mode: str | None = None,
    apply_to_existing: bool = True,
) -> dict:
    """Set a default time budget for every sample in a holder.

    Stores the default under `plan.holder_budgets[holder_id]` so new
    samples inherit it, and (when `apply_to_existing` is True) walks
    the current queue and updates each matching sample's modes.

    `holder_id=None` acts as a global default (applies to all samples).
    Returns a summary dict so the caller can log it.
    """
    body, queue = _load_plan(experiment_id)
    holder_budgets = body.setdefault("holder_budgets", {})
    key = holder_id or "_default"
    entry = holder_budgets.setdefault(key, {})
    if count_time_s is not None:
        entry["count_time_s"] = float(count_time_s)
    if reps is not None:
        entry["reps"] = int(reps)
    if mode is not None:
        entry["mode"] = mode

    n_updated = 0
    if apply_to_existing:
        for s in queue:
            if holder_id and s.get("holder_id") != holder_id:
                continue
            for m in s.get("modes") or []:
                if mode and m.get("mode") != mode:
                    continue
                _apply_mode_fields(m, count_time_s=count_time_s, reps=reps)
                n_updated += 1
            s.setdefault("notes", []).append(
                {
                    "ts": datetime.now().isoformat(),
                    "text": f"holder budget applied (count_time_s={count_time_s}, reps={reps}, mode={mode or 'all'})",
                }
            )

    body["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(experiment_id, plan=body)
    return {
        "holder_id": holder_id,
        "count_time_s": count_time_s,
        "reps": reps,
        "mode": mode,
        "samples_updated": n_updated,
    }


def rebuild_plan_preserving_progress(
    experiment_id: str,
    beamtime_hours: float | None = None,
) -> dict:
    """Regenerate the plan from DB while preserving sample-level progress.

    Used when a new sample holder is added or edited after the plan was
    first built — we need the new samples to show up without wiping out
    `status`, `snr_estimate`, `reps_completed`, etc. that the agent has
    already recorded for samples still present in the DB.
    """
    previous = get_experiment_plan(experiment_id) or {}
    prev_body = previous.get("plan") or {}
    prev_queue = prev_body.get("sample_queue") or []
    progress: dict[str, dict] = {
        s.get("sample_id"): {
            "status": s.get("status"),
            "snr_estimate": s.get("snr_estimate"),
            "efficiency_verdict": s.get("efficiency_verdict"),
            "reps_completed": s.get("reps_completed"),
            "notes": s.get("notes", []),
            # Preserve per-sample time-budget overrides the user has
            # already applied. Mode overrides win over holder-default +
            # DB values on regeneration.
            "modes": s.get("modes"),
        }
        for s in prev_queue if s.get("sample_id")
    }

    # Carry across budget + thresholds + holder_budgets so regeneration
    # doesn't reset user-authored overrides.
    budget = prev_body.get("budget", {})
    thresholds = prev_body.get("thresholds", {})
    holder_budgets = prev_body.get("holder_budgets", {})

    total_hours = beamtime_hours
    if total_hours is None:
        total_hours = budget.get("beamtime_total_hours") or previous.get("beamtime_total_hours")

    new_plan = build_initial_plan(experiment_id, beamtime_hours=total_hours)

    # Re-apply preserved data (status, progress, notes)
    for s in new_plan.get("sample_queue", []):
        sid = s.get("sample_id")
        prior = progress.get(sid)
        if prior:
            for k in ("status", "snr_estimate", "efficiency_verdict", "reps_completed"):
                if prior.get(k) is not None:
                    s[k] = prior[k]
            if prior.get("notes"):
                s["notes"] = prior["notes"]
    if thresholds:
        new_plan["thresholds"] = {**new_plan.get("thresholds", {}), **thresholds}
    if holder_budgets:
        new_plan["holder_budgets"] = holder_budgets
        # Apply holder budgets to the freshly-built queue first, so the
        # per-sample overrides below can trump them on a sample-by-sample
        # basis.
        for s in new_plan.get("sample_queue", []):
            hid = s.get("holder_id")
            bud = holder_budgets.get(hid) or holder_budgets.get("_default") or {}
            for m in s.get("modes") or []:
                if bud.get("mode") and m.get("mode") != bud["mode"]:
                    continue
                _apply_mode_fields(
                    m,
                    count_time_s=bud.get("count_time_s"),
                    reps=bud.get("reps"),
                )
    # Re-apply per-sample mode overrides (user-authored count_time_s /
    # reps survive regeneration).
    for s in new_plan.get("sample_queue", []):
        prior_modes = (progress.get(s.get("sample_id")) or {}).get("modes") or []
        if not prior_modes:
            continue
        by_name = {m.get("mode"): m for m in prior_modes if isinstance(m, dict)}
        for m in s.get("modes") or []:
            prev = by_name.get(m.get("mode"))
            if not prev:
                continue
            if prev.get("count_time_s") is not None:
                m["count_time_s"] = prev["count_time_s"]
            if prev.get("reps") is not None:
                m["reps"] = prev["reps"]
    if budget:
        new_plan.setdefault("budget", {}).update(budget)
        if total_hours is not None:
            new_plan["budget"]["beamtime_total_hours"] = float(total_hours)

    new_plan["updated_at"] = datetime.now().isoformat()
    upsert_experiment_plan(
        experiment_id,
        plan=new_plan,
        beamtime_total_hours=new_plan.get("budget", {}).get("beamtime_total_hours"),
    )
    return new_plan


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
