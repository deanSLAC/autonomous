"""Autonomy CAT-8 orchestration tools — overlay on top of upstream's tools_core.

The ~101 upstream tool handlers (CAT-0..CAT-7, CAT-9, CAT-10) live in
`beamtimehero_cli.tool_catalog.tools_core`. This module only defines
the 22 CAT-8 orchestration tools that are autonomy-specific (plan
edits, intervention requests, sample/holder budgets, etc.) and merges
them into a single `DISPATCH` dict that the executor consumes.

Every SPEC-mutating tool here delegates to `audited_call()`, which
looks up phase + experiment from `orchestration.runtime_state`
(mirrored to upstream's `beamtimehero_cli.runtime_state`) and writes
to `action_log` before dispatch. The `justification` argument is
required on every write tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from beamline_tools.audited_call import audited_call
# Phase 2+: the CLI's DISPATCH is keyed by ``(tree, ..., name)``. The
# autonomy executor and tests use name-keyed lookups, so flatten here.
from beamtimehero_cli.tool_catalog.tools_core import DISPATCH as _UPSTREAM_DISPATCH_TREE
from orchestration import runtime_state

_UPSTREAM_DISPATCH: dict[str, callable] = {
    key[-1]: handler
    for key, handler in _UPSTREAM_DISPATCH_TREE.items()
    if key[0] != "s3df"
}
# s3df duplicates six spec-file leaf names (list_scans, read_scan, ...).
# On the beamline the spec-file handlers must win the name-keyed flatten;
# s3df-only leaves (psql etc.) still register.
for _key, _handler in _UPSTREAM_DISPATCH_TREE.items():
    if _key[0] == "s3df":
        _UPSTREAM_DISPATCH.setdefault(_key[-1], _handler)
del _key, _handler

# CAT-8 tools need the orchestration package. Import lazily so this
# module still imports when `orchestration/` is absent (e.g. when
# `beamline_tools` is vendored into a future project without it).
try:
    from orchestration.plan_store.client import (
        get_plan,
        list_guidance,
        list_open_interventions,
    )
    from orchestration.plan_store.timeutils import parse_iso_to_local_naive
    from orchestration.planner import planner
    from orchestration.planner.staff_guidance import coordinator
    _ORCHESTRATION_AVAILABLE = True
except Exception:  # pragma: no cover — ImportError when vendored without orchestration, ValidationError when .env missing
    get_plan = list_guidance = list_open_interventions = None  # type: ignore
    parse_iso_to_local_naive = None  # type: ignore
    planner = coordinator = None  # type: ignore
    _ORCHESTRATION_AVAILABLE = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Injection point for the intervention notifier (Slack/UI fanout).
# Set by app.py at startup so this module has no direct Slack dependency.
# ---------------------------------------------------------------------------

_intervention_notifier = None


def set_intervention_notifier(fn) -> None:
    global _intervention_notifier
    _intervention_notifier = fn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_json(result: dict | list | str) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)


def _require_xid() -> str | None:
    return runtime_state.get_experiment_id() or None


def _log_plan_edit_from_agent(experiment_id: str, action: str, *,
                              target_id: str | None = None,
                              payload: dict | None = None,
                              reason: str | None = None) -> None:
    from orchestration.plan_store.client import log_plan_edit
    try:
        log_plan_edit(
            experiment_id, author="agent", action=action,
            target_id=target_id, payload=payload or {}, reason=reason,
        )
    except Exception as e:
        logger.warning("plan-edit audit log failed: %s", e)


def _resolve_active_sample_id(experiment_id: str) -> Optional[str]:
    """Detect the currently-active sample from plan_json.

    Order of resolution:
      1. plan_json.active_sample_id (explicit flag set by Planner).
      2. The lowest-queue-order entry in plan_json.sample_queue whose
         status is not 'done' / 'skipped'.

    Returns None if neither path resolves a sample id.
    """
    plan = get_plan(experiment_id) or {}
    body = plan.get("plan", {}) or {}
    explicit = body.get("active_sample_id")
    if explicit:
        return str(explicit)
    queue = body.get("sample_queue", []) or []
    for entry in queue:
        status = (entry.get("status") or "queued").lower()
        if status in ("done", "skipped"):
            continue
        sid = entry.get("sample_id")
        if sid:
            return str(sid)
    return None


# ===========================================================================
# CAT-8 · Orchestration (no SPEC)
# ===========================================================================

def _record_measured_beam_size(result: dict) -> None:
    """Best-effort write-through of measured beam FWHM (mm → µm) to plan_store."""
    parsed = result.get("result") or {}
    h_mm = parsed.get("h_mm")
    v_mm = parsed.get("v_mm")
    if h_mm is None and v_mm is None:
        return
    try:
        xid = runtime_state.get_experiment_id()
        if not xid:
            return
        from orchestration.plan_store.session import record_measured_beam_size
        record_measured_beam_size(
            xid,
            h_mm * 1000.0 if h_mm is not None else None,
            v_mm * 1000.0 if v_mm is not None else None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("measure_beam_size write-through failed: %s", e)


def t_measure_beam_size(args: dict) -> tuple[str, list[str]]:
    j = (args.get("justification") or "").strip()
    mode_x = "1" if bool(args.get("small_x", False)) else "0"
    mode_z = "1" if bool(args.get("small_z", False)) else "0"
    res = audited_call("measure_beam_size", [mode_x, mode_z], justification=j)
    if isinstance(res, dict) and res.get("ok"):
        _record_measured_beam_size(res)
    return _as_json(res), []


def t_request_human_intervention(args: dict) -> tuple[str, list[str]]:
    kind = args["kind"]
    detail = args["detail"]
    experiment_id = runtime_state.get_experiment_id()

    notify = _intervention_notifier or (lambda i, d: asyncio.sleep(0))

    async def _go():
        return await coordinator.request_intervention(
            experiment_id=experiment_id,
            kind=kind,
            detail=detail,
            notify=notify,
        )

    # The agent's own tool: blocks until staff resolves the request.
    # No timeout — see config.py / orchestrator/staff_guidance.py.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        result = asyncio.run_coroutine_threadsafe(_go(), loop).result()
    else:
        result = asyncio.run(_go())
    return _as_json(result), []


def t_post_status_update(args: dict) -> tuple[str, list[str]]:
    from orchestration.planner.loop import get_orchestrator
    orch = get_orchestrator()
    text = args.get("text", "").strip()
    if not text:
        return "error: text required", []
    if orch is not None:
        orch._safe_invoke(orch.slack_status_post, text)
        orch._safe_emit({"type": "status_update", "text": text})
        return json.dumps({"posted": True}), []
    try:
        import os
        from ui.adapters.slack_notify import SlackNotifier
        from orchestration.config import SLACK_CHAT_CHANNEL_ID
        channel = SLACK_CHAT_CHANNEL_ID
        notifier = SlackNotifier(enabled=True, channel=channel)
        if notifier.enabled:
            notifier.post_message(text)
            return json.dumps({"posted": True, "via": "direct_slack"}), []
        return json.dumps({"posted": False, "error": "Slack not configured"}), []
    except Exception as e:
        return json.dumps({"posted": False, "error": str(e)}), []


def t_log_status_assessment(args: dict) -> tuple[str, list[str]]:
    import datetime as _dt
    import re as _re
    from orchestration.agent.phase_runner import _logs_dir

    text = args.get("text", "")
    if isinstance(text, str):
        text = text.strip()
    if not text:
        return json.dumps({"logged": False, "error": "text required"}), []

    experiment_id = runtime_state.get_experiment_id() or "unknown"
    spawn: Optional[int] = None
    m = _re.search(r"\[STATUS ASSESSMENT\s*[—-]\s*spawn\s+(\d+)\]", text)
    if m:
        spawn = int(m.group(1))

    record = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "experiment_id": experiment_id,
        "spawn": spawn,
        "text": text,
    }
    path = _logs_dir() / f"status_assessments_{experiment_id}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return json.dumps({"logged": True, "path": str(path), "spawn": spawn}), []


def t_update_plan(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []
    new_plan = args.get("plan")
    if not isinstance(new_plan, dict):
        return json.dumps({"ok": False, "error": "plan must be a JSON object"}), []
    try:
        planner.replace_plan(experiment_id, new_plan)
    except planner.PlanValidationError as e:
        return json.dumps({"ok": False, "error": str(e)}), []
    # Best-effort plan summary: writes data/plan_summaries/<id>.json
    # and posts to Slack. Any failure here must not block the agent's
    # update — the call already succeeded above.
    try:
        from orchestration.planner import plan_summary as _plan_summary
        _plan_summary.generate_and_post(experiment_id)
    except Exception as e:
        logger.warning("plan_summary.generate_and_post failed: %s", e)
    return json.dumps({"ok": True}), []


def t_record_sample_progress(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []
    planner.record_sample_progress(
        experiment_id,
        args["sample_id"],
        status=args.get("status"),
        snr_estimate=args.get("snr_estimate"),
        efficiency_verdict=args.get("efficiency_verdict"),
        reps_completed=args.get("reps_completed"),
        note=args.get("note"),
    )
    return json.dumps({"ok": True}), []


def t_record_convergence_stats(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []
    stats = args.get("stats")
    if not isinstance(stats, dict):
        return json.dumps({"ok": False, "error": "stats must be a JSON object"}), []
    planner.record_convergence_stats(
        experiment_id, args["sample_id"], stats,
    )
    return json.dumps({"ok": True}), []


def t_get_plan(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"error": "no active experiment"}), []
    plan = get_plan(experiment_id)
    return _as_json(plan or {}), []


def t_get_experiment_config(args: dict) -> tuple[str, list[str]]:
    """Return the canonical experiment configuration straight from the DB.

    Distinct from `get_plan`: this surfaces the operator-entered setup
    (mono crystal, beam, sample env, elements, holders, samples) — the
    same data the /config form writes when the user hits Save.
    """
    from sqlmodel import select
    from orchestration.plan_store.models import (
        Experiment, ExperimentElement, SampleHolder, SamplePosition,
    )
    from orchestration.plan_store.session import get_session

    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"error": "no active experiment"}), []

    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            return json.dumps({"error": f"experiment {experiment_id} not found"}), []

        elements = list(session.exec(
            select(ExperimentElement)
            .where(ExperimentElement.experiment_id == experiment_id)
            .order_by(ExperimentElement.priority)
        ))
        holders = list(session.exec(
            select(SampleHolder)
            .where(SampleHolder.experiment_id == experiment_id)
            .order_by(SampleHolder.queue_order, SampleHolder.created_at)
        ))
        holder_payloads = []
        for h in holders:
            samples = list(session.exec(
                select(SamplePosition)
                .where(SamplePosition.sample_holder_id == h.id)
                .order_by(SamplePosition.sample_number)
            ))
            holder_payloads.append({
                "id": h.id,
                "name": h.name,
                "holder_type": h.holder_type,
                "status": h.status,
                "n_samples": h.n_samples,
                "queue_order": h.queue_order,
                "beamtime_hours": h.beamtime_hours,
                "stop_time": h.stop_time.isoformat() if h.stop_time else None,
                "samples": [
                    {
                        "id": s.id,
                        "sample_number": s.sample_number,
                        "name": s.sample_name,
                        "element": s.element_symbol,
                        "enabled": s.enabled,
                        "sx_lo": s.sx_lo, "sx_hi": s.sx_hi, "sx_del": s.sx_del,
                        "sy_lo": s.sy_lo, "sy_hi": s.sy_hi, "sy_del": s.sy_del,
                        "sz_lo": s.sz_lo, "sz_hi": s.sz_hi, "sz_del": s.sz_del,
                        "emiss_energy_eV": s.emiss_energy_eV,
                        "total_spots": s.total_spots,
                        "do_xas": s.do_xas,
                        "xas_reps": s.xas_reps,
                        "xas_time": s.xas_time,
                        # xas_filter is the *measured* value (0 pre-survey);
                        # xas_filter_suggested is the operator's starting
                        # guess. The Sample Surveyor agent should read the
                        # suggested value as its first attempt and write the
                        # damage-assessment-derived result back to xas_filter.
                        "xas_filter": s.xas_filter,
                        "xas_filter_suggested": s.xas_filter_suggested,
                        "xas_emiss_override": s.xas_emiss_override,
                        "do_rixs": s.do_rixs,
                        "rixs_time": s.rixs_time,
                        "rixs_start": s.rixs_start,
                        "rixs_end": s.rixs_end,
                        "rixs_step": s.rixs_step,
                        "rixs_filter": s.rixs_filter,
                        "i0_gain": s.i0_gain,
                        "i0_offset": s.i0_offset,
                        "i1_gain": s.i1_gain,
                        "min_scans": s.min_scans,
                    }
                    for s in samples
                ],
            })

        payload = {
            "experiment": {
                "id": exp.id,
                "name": exp.name,
                "experimenter": exp.experimenter,
                "beamline": exp.beamline,
                "mono_crystal": exp.mono_crystal,
                "beam_size_h": exp.beam_size_h,
                "beam_size_v": exp.beam_size_v,
                "mirrors_out": exp.mirrors_out,
                "sample_env": exp.sample_env,
                "status": exp.status,
                "data_path": exp.data_path,
                "calibration_foil_element": getattr(exp, "calibration_foil_element", None),
                "calibration_foil_detector": getattr(exp, "calibration_foil_detector", None) or "I2",
                "created_at": exp.created_at.isoformat() if exp.created_at else None,
            },
            "elements": [
                {
                    "symbol": e.element_symbol,
                    "edge": e.edge,
                    "measurement_mode": e.measurement_mode,
                    "emission_line": e.emission_line,
                    "incident_energy_eV": e.incident_energy_eV,
                    "emission_energy_eV": e.emission_energy_eV,
                    "crystal_type": e.crystal_type,
                    "crystal_hkl": e.crystal_hkl,
                    "row_radius": e.row_radius,
                    "n_crystals": e.n_crystals,
                    "vortex_counter": e.vortex_counter or "vortDT",
                    "priority": e.priority,
                }
                for e in elements
            ],
            "sample_holders": holder_payloads,
        }
    return _as_json(payload), []


def t_get_remaining_beamtime(args: dict) -> tuple[str, list[str]]:
    """Hours from now until Experiment.end_time. Returns
    `{remaining_hours, end_time}` — or `{remaining_hours: null,
    end_time: null}` if the operator hasn't set an end time yet."""
    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"error": "no active experiment"}), []
    snap = planner.snapshot(experiment_id)
    if snap.end_time is None:
        return _as_json({
            "remaining_hours": None,
            "end_time": None,
            "note": "end_time not set — call set_experiment_end_time first",
        }), []
    return _as_json({
        "remaining_hours": snap.beamtime_remaining_hours,
        "end_time": snap.end_time.isoformat(),
    }), []


def t_set_experiment_end_time(args: dict) -> tuple[str, list[str]]:
    """Set the absolute end-of-beamtime timestamp on the active experiment.

    Accepts `end_time` as ISO-8601 (e.g. "2026-05-10T18:00:00") OR
    `hours_from_now` as a float (e.g. 36.0). Exactly one is required.
    """
    from datetime import datetime as _dt, timedelta as _td
    from orchestration.plan_store.session import set_experiment_end_time

    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    iso = (args.get("end_time") or "").strip() or None
    hours_from_now = args.get("hours_from_now")
    if (iso is None) == (hours_from_now is None):
        return json.dumps({
            "ok": False,
            "error": "provide exactly one of end_time (ISO-8601) or hours_from_now (number)",
        }), []

    if iso is not None:
        try:
            new_end = parse_iso_to_local_naive(iso)
        except ValueError as e:
            return json.dumps({
                "ok": False,
                "error": f"end_time must be ISO-8601: {e}",
            }), []
    else:
        try:
            hrs = float(hours_from_now)
        except (TypeError, ValueError):
            return json.dumps({
                "ok": False, "error": "hours_from_now must be a number",
            }), []
        new_end = _dt.now() + _td(hours=hrs)

    row = set_experiment_end_time(xid, new_end)
    if row is None:
        return json.dumps({"ok": False, "error": f"experiment {xid} not found"}), []
    _log_plan_edit_from_agent(
        xid, "set_end_time",
        payload={"end_time": new_end.isoformat()},
        reason=args.get("reason"),
    )
    return json.dumps({
        "ok": True,
        "end_time": new_end.isoformat(),
        "remaining_hours": max(0.0, (new_end - _dt.now()).total_seconds() / 3600),
    }), []


def t_get_staff_guidance(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    rows = list_guidance(experiment_id, limit=int(args.get("limit", 20)))
    return _as_json(rows), []


def t_list_open_interventions(args: dict) -> tuple[str, list[str]]:
    experiment_id = runtime_state.get_experiment_id()
    return _as_json(list_open_interventions(experiment_id)), []


def t_set_sample_time_budget(args: dict) -> tuple[str, list[str]]:
    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []
    sample_id = args.get("sample_id")
    if not sample_id:
        return json.dumps({"ok": False, "error": "sample_id required"}), []
    count_time_s = args.get("count_time_s")
    reps = args.get("reps")
    reps_per_spot = args.get("reps_per_spot")
    n_spots = args.get("n_spots")
    if (
        count_time_s is None and reps is None
        and reps_per_spot is None and n_spots is None
    ):
        return json.dumps({
            "ok": False,
            "error": "at least one of count_time_s/reps/reps_per_spot/n_spots required",
        }), []
    ok = planner.set_sample_time_budget(
        xid, sample_id,
        count_time_s=count_time_s, reps=reps,
        reps_per_spot=reps_per_spot, n_spots=n_spots,
        mode=args.get("mode"),
    )
    if not ok:
        return json.dumps({"ok": False, "error": f"sample {sample_id} not in plan"}), []
    _log_plan_edit_from_agent(
        xid, "set_sample_time_budget",
        target_id=sample_id,
        payload={
            "count_time_s": count_time_s, "reps": reps,
            "reps_per_spot": reps_per_spot, "n_spots": n_spots,
            "mode": args.get("mode"),
        },
        reason=args.get("reason"),
    )
    return json.dumps({"ok": True}), []


def t_set_holder_time_budget(args: dict) -> tuple[str, list[str]]:
    from datetime import datetime as _dt, timedelta as _td
    from orchestration.plan_store.session import update_sample_holder as _ush

    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    count_time_s = args.get("count_time_s")
    reps = args.get("reps")
    stop_time_iso = (args.get("stop_time") or "").strip() or None
    hours_remaining = args.get("hours_remaining")

    # At least one of count_time_s/reps or stop_time/hours_remaining must be given.
    has_plan_fields = count_time_s is not None or reps is not None
    has_stop_fields = stop_time_iso is not None or hours_remaining is not None

    if not has_plan_fields and not has_stop_fields:
        return json.dumps({
            "ok": False,
            "error": "provide count_time_s/reps and/or stop_time/hours_remaining",
        }), []

    # Handle stop_time / hours_remaining → persist on the SampleHolder row.
    new_stop: _dt | None = None
    holder_id = args.get("holder_id")
    if has_stop_fields:
        if stop_time_iso is not None and hours_remaining is not None:
            return json.dumps({
                "ok": False,
                "error": "provide stop_time OR hours_remaining, not both",
            }), []
        if stop_time_iso is not None:
            try:
                new_stop = parse_iso_to_local_naive(stop_time_iso)
            except ValueError as e:
                return json.dumps({
                    "ok": False,
                    "error": f"stop_time must be ISO-8601: {e}",
                }), []
        else:
            try:
                hrs = float(hours_remaining)
            except (TypeError, ValueError):
                return json.dumps({
                    "ok": False, "error": "hours_remaining must be a number",
                }), []
            new_stop = _dt.now() + _td(hours=hrs)

        if holder_id:
            _ush(holder_id, stop_time=new_stop)
        else:
            # Apply to all holders in the experiment.
            from orchestration.plan_store.session import list_sample_holders as _lsh
            for h in _lsh(xid):
                _ush(h.id, stop_time=new_stop)

    # Handle plan-level count_time_s / reps (existing behavior).
    summary: dict = {}
    if has_plan_fields:
        summary = planner.set_holder_time_budget(
            xid, holder_id,
            count_time_s=count_time_s, reps=reps, mode=args.get("mode"),
            apply_to_existing=bool(args.get("apply_to_existing", True)),
        )
    else:
        summary = {"holder_id": holder_id}

    if new_stop is not None:
        summary["stop_time"] = new_stop.isoformat()

    _log_plan_edit_from_agent(
        xid, "set_holder_time_budget",
        target_id=holder_id,
        payload=summary,
        reason=args.get("reason"),
    )
    return _as_json(summary), []


def t_get_holder_time_budget(args: dict) -> tuple[str, list[str]]:
    """Return the time budget for a holder: beamtime_hours, stop_time,
    and computed hours_remaining."""
    from datetime import datetime as _dt
    from orchestration.plan_store.session import list_sample_holders as _lsh

    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    holder_id = (args.get("holder_id") or "").strip() or None
    holders = _lsh(xid)
    if holder_id:
        holders = [h for h in holders if h.id == holder_id]
        if not holders:
            return json.dumps({
                "ok": False,
                "error": f"holder {holder_id!r} not found for this experiment",
            }), []

    results = []
    now = _dt.now()
    for h in holders:
        hours_remaining: float | None = None
        if h.stop_time is not None:
            hours_remaining = max(0.0, (h.stop_time - now).total_seconds() / 3600)
        results.append({
            "holder_id": h.id,
            "holder_name": h.name,
            "beamtime_hours": h.beamtime_hours,
            "stop_time": h.stop_time.isoformat() if h.stop_time else None,
            "hours_remaining": hours_remaining,
        })

    from orchestration.planner.planner import compute_holder_pacing
    pacing = {}
    try:
        pacing = compute_holder_pacing(xid)
    except Exception:
        pass

    return _as_json({"ok": True, "holders": results, "pacing": pacing}), []


def t_get_scans_since_last_plan_update(args: dict) -> tuple[str, list[str]]:
    from datetime import datetime as _dt

    from orchestration.plan_store import session as _ps
    from orchestration.plan_store.client import get_plan as _gep
    from orchestration.plan_store.models import SamplePosition

    experiment_id = (args.get("experiment_id") or runtime_state.get_experiment_id() or "").strip()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    wrapper = _gep(experiment_id) or {}
    updated_at_iso = wrapper.get("updated_at")
    updated_at: _dt
    if updated_at_iso:
        try:
            updated_at = _dt.fromisoformat(str(updated_at_iso))
        except ValueError:
            updated_at = _dt.fromtimestamp(0)
    else:
        updated_at = _dt.fromtimestamp(0)

    rows = _ps.get_collection_scans_since(experiment_id, updated_at)
    # Resolve sample names in one pass.
    sample_ids = sorted({r.sample_id for r in rows})
    name_by_id: dict[str, str] = {}
    if sample_ids:
        from sqlmodel import select as _select
        with _ps.get_session() as session:
            for sid in sample_ids:
                sp = session.get(SamplePosition, sid)
                if sp is not None:
                    name_by_id[sid] = sp.sample_name

    payload = {
        "ok": True,
        "experiment_id": experiment_id,
        "plan_updated_at": updated_at.isoformat(),
        "count": len(rows),
        "scans": [
            {
                "scan_number": r.scan_number,
                "sample_id": r.sample_id,
                "sample_name": name_by_id.get(r.sample_id),
                "technique": r.technique,
                "filter_setting": r.filter_setting,
                "count_time": r.count_time,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "spec_datafile": r.spec_datafile,
            }
            for r in rows
        ],
    }
    return _as_json(payload), []


def t_get_scans_for_active_sample(args: dict) -> tuple[str, list[str]]:
    from orchestration.plan_store import session as _ps
    from orchestration.plan_store.models import SamplePosition

    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    sample_id = (args.get("sample_id") or "").strip() or _resolve_active_sample_id(experiment_id)
    if not sample_id:
        return json.dumps({
            "ok": False,
            "error": "no active sample (sample_queue empty or all done)",
        }), []

    sample_name: Optional[str] = None
    with _ps.get_session() as session:
        sp = session.get(SamplePosition, sample_id)
        if sp is not None:
            sample_name = sp.sample_name

    rows = _ps.get_collection_scans_for_sample(sample_id)
    payload = {
        "ok": True,
        "sample_id": sample_id,
        "sample_name": sample_name,
        "count": len(rows),
        "scans": [
            {
                "scan_number": r.scan_number,
                "technique": r.technique,
                "filter_setting": r.filter_setting,
                "count_time": r.count_time,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "spec_datafile": r.spec_datafile,
            }
            for r in rows
        ],
    }
    return _as_json(payload), []


def t_upload_sample_alignment_results(args: dict) -> tuple[str, list[str]]:
    """Store per-sample alignment results (boundaries, emiss, filter, cps)."""
    from orchestration.plan_store import session as _ps

    j = (args.get("justification") or "").strip()
    if not j:
        return json.dumps({"ok": False, "error": "justification required"}), []
    raw = args.get("results")
    if not isinstance(raw, list) or not raw:
        return json.dumps({"ok": False, "error": "results must be a non-empty list"}), []

    _required = {"sample_id", "sx_lo", "sx_hi", "sy_lo", "sy_hi", "sz_lo", "sz_hi"}
    cleaned: list[dict] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            return json.dumps({"ok": False, "error": f"results[{i}] must be an object"}), []
        missing = _required - set(entry.keys())
        if missing:
            return json.dumps({
                "ok": False,
                "error": f"results[{i}] missing required keys: {sorted(missing)}",
            }), []
        try:
            cleaned.append({
                "sample_id": str(entry["sample_id"]),
                "sx_lo": float(entry["sx_lo"]),
                "sx_hi": float(entry["sx_hi"]),
                "sy_lo": float(entry["sy_lo"]),
                "sy_hi": float(entry["sy_hi"]),
                "sz_lo": float(entry["sz_lo"]),
                "sz_hi": float(entry["sz_hi"]),
                "emiss_energy_eV": float(entry["emiss_energy_eV"]) if entry.get("emiss_energy_eV") is not None else None,
                "suggested_filter": int(entry["suggested_filter"]) if entry.get("suggested_filter") is not None else None,
                "counts_per_sec": float(entry["counts_per_sec"]) if entry.get("counts_per_sec") is not None else None,
            })
        except (TypeError, ValueError) as e:
            return json.dumps({"ok": False, "error": f"results[{i}] type error: {e}"}), []

    updated = _ps.submit_sample_alignment_results(cleaned)
    return json.dumps({"ok": True, "updated": updated, "count": len(updated)}), []


def t_upload_sample_survey_results(args: dict) -> tuple[str, list[str]]:
    from orchestration.plan_store import session as _ps

    j = (args.get("justification") or "").strip()
    if not j:
        return json.dumps({"ok": False, "error": "justification required"}), []
    raw = args.get("results")
    if not isinstance(raw, list) or not raw:
        return json.dumps({"ok": False, "error": "results must be a non-empty list"}), []

    cleaned: list[dict] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            return json.dumps({"ok": False, "error": f"results[{i}] must be an object"}), []
        sid = entry.get("sample_id")
        if not isinstance(sid, str) or not sid:
            return json.dumps({"ok": False, "error": f"results[{i}].sample_id required"}), []
        try:
            fc = int(entry["filter_count"])
            cps = float(entry["counts_per_sec"])
        except (KeyError, TypeError, ValueError):
            return json.dumps({
                "ok": False,
                "error": f"results[{i}] needs integer filter_count and numeric counts_per_sec",
            }), []
        if fc < 0 or cps < 0:
            return json.dumps({"ok": False, "error": f"results[{i}] values must be >= 0"}), []
        cleaned.append({
            "sample_id": sid,
            "filter_count": fc,
            "counts_per_sec": cps,
            "survey_energy_ev": entry.get("survey_energy_ev"),
            "notes": entry.get("notes"),
        })

    updated = _ps.submit_survey_results(cleaned)
    return json.dumps({"ok": True, "updated": updated, "count": len(updated)}), []


def t_get_comprehensive_collection_plan(args: dict) -> tuple[str, list[str]]:
    from sqlmodel import select as _select

    from orchestration.plan_store import session as _ps
    from orchestration.plan_store.client import get_plan as _gep
    from orchestration.plan_store.models import SampleHolder, SamplePosition

    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    holder_id = (args.get("sample_holder_id") or "").strip() or None

    # Resolve target holder.
    with _ps.get_session() as session:
        if holder_id:
            holder = session.get(SampleHolder, holder_id)
            if holder is None or holder.experiment_id != experiment_id:
                return json.dumps({
                    "ok": False,
                    "error": f"sample_holder {holder_id!r} not found for this experiment",
                }), []
        else:
            holders_stmt = (
                _select(SampleHolder)
                .where(SampleHolder.experiment_id == experiment_id)
                .order_by(SampleHolder.queue_order, SampleHolder.created_at)  # type: ignore[arg-type]
            )
            holders = list(session.exec(holders_stmt).all())
            holder = next((h for h in holders if (h.status or "").lower() != "done"), None)
            if holder is None and holders:
                holder = holders[0]
            if holder is None:
                return json.dumps({
                    "ok": False,
                    "error": "no sample holder configured for this experiment",
                }), []

        samples_stmt = (
            _select(SamplePosition)
            .where(SamplePosition.sample_holder_id == holder.id)
            .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
        )
        samples = list(session.exec(samples_stmt).all())

    # Fold in plan_json overrides keyed by sample_id.
    wrapper = _gep(experiment_id) or {}
    body = wrapper.get("plan") or {}
    queue = body.get("sample_queue") or []
    plan_by_sid: dict[str, dict] = {q.get("sample_id"): q for q in queue if q.get("sample_id")}

    # Pull completed scans for this holder so we can return per-sample
    # and per-spot remaining-rep counts. The data collector reads this
    # plan between scans; "remaining" is what makes a mid-stream plan
    # edit translate cleanly into "do the next K scans" without
    # restarting completed work.
    from orchestration.plan_store.models import CollectionScan
    sample_ids = [s.id for s in samples if s.enabled]
    completed_total: dict[str, int] = {sid: 0 for sid in sample_ids}
    completed_by_spot: dict[str, dict[int, int]] = {sid: {} for sid in sample_ids}
    if sample_ids:
        with _ps.get_session() as session:
            scan_rows = list(session.exec(
                _select(CollectionScan)
                .where(CollectionScan.experiment_id == experiment_id)
                .where(CollectionScan.sample_id.in_(sample_ids))  # type: ignore[union-attr]
            ).all())
        for sc in scan_rows:
            completed_total[sc.sample_id] = completed_total.get(sc.sample_id, 0) + 1
            if sc.spot_index is not None:
                d = completed_by_spot.setdefault(sc.sample_id, {})
                d[sc.spot_index] = d.get(sc.spot_index, 0) + 1

    rows: list[dict] = []
    for s in samples:
        if not s.enabled:
            continue
        plan_entry = plan_by_sid.get(s.id, {}) or {}

        # Pull the xas mode if present — that's where reps_per_spot,
        # n_spots, count_time live.
        xas_mode: dict = {}
        for m in plan_entry.get("modes") or []:
            if (m.get("mode") or "").lower() == "xas":
                xas_mode = m
                break

        # planned_scans_total: prefer plan_json overrides, fall back to xas_reps.
        n_reps = plan_entry.get("planned_scans_total")
        if n_reps is None and xas_mode.get("reps") is not None:
            n_reps = xas_mode["reps"]
        if n_reps is None:
            n_reps = s.xas_reps
        try:
            n_reps = int(n_reps)
        except (TypeError, ValueError):
            n_reps = int(s.xas_reps)

        count_time = s.xas_time
        if xas_mode.get("count_time_s") is not None:
            count_time = float(xas_mode["count_time_s"])

        # Per-spot rep distribution. Three flavors, in priority order:
        #  1. xas_mode["reps_per_spot"] is a list[int] — explicit per-spot reps.
        #  2. xas_mode["n_spots"] + xas_mode["reps_per_spot"] (int) — even split.
        #  3. fall back to total_spots from SamplePosition; reps spread evenly.
        n_spots = int(xas_mode.get("n_spots") or s.total_spots or 1)
        rps = xas_mode.get("reps_per_spot")
        if isinstance(rps, list) and rps:
            reps_per_spot = [int(x) for x in rps]
            n_spots = len(reps_per_spot)
            n_reps = sum(reps_per_spot)
        elif isinstance(rps, (int, float)):
            per = int(rps)
            reps_per_spot = [per] * n_spots
            n_reps = per * n_spots
        else:
            # Default: spread n_reps across n_spots as evenly as we can.
            base, extra = divmod(n_reps, max(1, n_spots))
            reps_per_spot = [base + (1 if i < extra else 0) for i in range(n_spots)]

        # Compute completed/remaining (sample-level + per-spot).
        sample_completed = int(completed_total.get(s.id, 0))
        per_spot_done = completed_by_spot.get(s.id, {}) or {}
        spots_payload = []
        for i, planned in enumerate(reps_per_spot):
            done_i = int(per_spot_done.get(i, 0))
            spots_payload.append({
                "spot_index": i,
                "n_reps_planned": int(planned),
                "n_reps_completed": done_i,
                "n_reps_remaining": max(0, int(planned) - done_i),
            })
        n_remaining = max(0, int(n_reps) - sample_completed)

        cps = s.survey_counts_per_sec
        planned_time_s = float(n_reps) * float(count_time)

        # Compute per-spot motor positions from sample boundaries.
        sx_ctr = (s.sx_lo + s.sx_hi) / 2.0
        sy_ctr = (s.sy_lo + s.sy_hi) / 2.0
        sz_ctr = (s.sz_lo + s.sz_hi) / 2.0
        sz_span = s.sz_hi - s.sz_lo
        for spot in spots_payload:
            idx = spot["spot_index"]
            if n_spots <= 1:
                spot["sx"] = sx_ctr
                spot["sy"] = sy_ctr
                spot["sz"] = sz_ctr
            else:
                spot["sx"] = sx_ctr
                spot["sy"] = sy_ctr
                spot["sz"] = s.sz_lo + sz_span * (idx + 0.5) / n_spots

        rows.append({
            "sample_id": s.id,
            "sample_name": s.sample_name,
            "element_symbol": s.element_symbol,
            "status": (plan_entry.get("status") or "queued"),
            "sx_lo": s.sx_lo, "sx_hi": s.sx_hi,
            "sy_lo": s.sy_lo, "sy_hi": s.sy_hi,
            "sz_lo": s.sz_lo, "sz_hi": s.sz_hi,
            "emiss_energy_eV": s.emiss_energy_eV,
            "total_spots": int(n_spots),
            # filter_count is the value Data Collection should actually use:
            # the surveyor's measurement when present, falling back to the
            # operator's suggested starting filter pre-survey.
            "filter_count": int(s.xas_filter or s.xas_filter_suggested),
            "count_time": float(count_time),
            "n_reps": int(n_reps),
            "n_reps_completed": sample_completed,
            "n_reps_remaining": n_remaining,
            "spots": spots_payload,
            "counts_per_sec": cps,
            "planned_time_s": planned_time_s,
            "planned_scans_total": int(n_reps),
            "min_scans": s.min_scans,
        })

    payload = {
        "ok": True,
        "sample_holder_id": holder.id,
        "sample_holder_name": holder.name,
        "samples": rows,
    }
    return _as_json(payload), []


def t_record_completed_scan(args: dict) -> tuple[str, list[str]]:
    """Insert a CollectionScan row after a successful run_xas (or sibling).

    Resolves any unspecified args from the active context:
      * sample_id  → `_resolve_active_sample_id` (plan_json.active_sample_id
        or the lowest-queue-order non-done/skipped sample).
      * scan_number → SPEC `p SCAN_N` via `audited_call("scan_n", ...)`.
      * spec_datafile → SPEC `p DATAFILE` via
        `audited_call("p_datafile", ...)`.

    The row is what makes the scan visible to plan_summary's recent_plots
    lookup and the Planner's convergence analysis. justification is
    required (mirrors every other write tool's audit gate).
    """
    from orchestration.plan_store.session import (
        create_collection_scan,
        get_session,
    )
    from orchestration.plan_store.models import SamplePosition

    j = (args.get("justification") or "").strip()
    if not j:
        return json.dumps({"ok": False, "error": "justification required"}), []

    experiment_id = runtime_state.get_experiment_id()
    if not experiment_id:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    sample_id = (args.get("sample_id") or "").strip() or None
    if not sample_id:
        sample_id = _resolve_active_sample_id(experiment_id)
    if not sample_id:
        return json.dumps({
            "ok": False,
            "error": "no active sample (sample_queue empty or all done)",
        }), []

    scan_number = args.get("scan_number")
    if scan_number is None:
        res = audited_call("scan_n", [], justification="")
        if isinstance(res, dict) and res.get("ok") and isinstance(res.get("result"), dict):
            sn_val = res["result"].get("value")
            if sn_val is not None:
                try:
                    scan_number = int(sn_val)
                except (TypeError, ValueError):
                    scan_number = None
    if scan_number is None:
        return json.dumps({
            "ok": False,
            "error": "could not resolve scan_number (provide explicitly or ensure SPEC is reachable)",
        }), []
    try:
        scan_number = int(scan_number)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "scan_number must be an integer"}), []

    spec_datafile = (args.get("spec_datafile") or "").strip() or None
    if not spec_datafile:
        res = audited_call("p_datafile", [], justification="")
        if isinstance(res, dict) and res.get("ok") and isinstance(res.get("result"), dict):
            df = res["result"].get("datafile") or res["result"].get("raw")
            if df:
                spec_datafile = str(df).strip()
    if not spec_datafile:
        spec_datafile = ""

    technique = str(args.get("technique") or "xas").lower()
    if technique not in ("xas", "herfd", "rixs", "vtc"):
        return json.dumps({
            "ok": False,
            "error": f"technique must be one of xas/herfd/rixs/vtc (got {technique!r})",
        }), []

    filter_setting = args.get("filter_setting")
    if filter_setting is None:
        filter_setting = 0
    try:
        filter_setting = int(filter_setting)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "filter_setting must be an integer"}), []

    count_time = args.get("count_time")
    if count_time is None:
        count_time = 1.0
    try:
        count_time = float(count_time)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "count_time must be a number"}), []

    spot_index = args.get("spot_index")
    if spot_index is not None:
        try:
            spot_index = int(spot_index)
            if spot_index < 0:
                return json.dumps({
                    "ok": False, "error": "spot_index must be ≥ 0",
                }), []
        except (TypeError, ValueError):
            return json.dumps({
                "ok": False, "error": "spot_index must be an integer",
            }), []

    # Look up the sample name for the response payload.
    sample_name: Optional[str] = None
    with get_session() as session:
        sp = session.get(SamplePosition, sample_id)
        if sp is None:
            return json.dumps({
                "ok": False,
                "error": f"sample_id {sample_id!r} not found",
            }), []
        sample_name = sp.sample_name

    scan = create_collection_scan(
        experiment_id=experiment_id,
        sample_id=sample_id,
        technique=technique,
        scan_number=scan_number,
        spec_datafile=spec_datafile,
        filter_setting=filter_setting,
        count_time=count_time,
        spot_index=spot_index,
    )
    return json.dumps({
        "ok": True,
        "scan_id": scan.id,
        "sample_id": sample_id,
        "sample_name": sample_name,
        "scan_number": scan_number,
        "technique": technique,
        "spot_index": spot_index,
    }), []


def t_record_alignment_flux(args: dict) -> tuple[str, list[str]]:
    """Store the bl-aligner's max I0/I1 flux + gain record on the experiment."""
    from orchestration.plan_store import session as _ps

    j = (args.get("justification") or "").strip()
    if not j:
        return json.dumps({"ok": False, "error": "justification required"}), []
    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []

    fields: dict = {}
    try:
        for key in ("i0_max_cps", "i1_max_cps"):
            if args.get(key) is not None:
                fields[key] = float(args[key])
        for key in ("i0_gain", "i1_gain"):
            if args.get(key) is not None:
                fields[key] = str(args[key]).strip()
    except (TypeError, ValueError) as e:
        return json.dumps({"ok": False, "error": f"bad value: {e}"}), []
    if not fields:
        return json.dumps({
            "ok": False,
            "error": "provide at least one of i0_max_cps/i0_gain/i1_max_cps/i1_gain",
        }), []
    for cps_key in ("i0_max_cps", "i1_max_cps"):
        if cps_key in fields and fields[cps_key] < 0:
            return json.dumps({"ok": False, "error": f"{cps_key} must be >= 0"}), []

    exp = _ps.record_alignment_flux(xid, **fields)
    if exp is None:
        return json.dumps({"ok": False, "error": "experiment not found"}), []
    return json.dumps({
        "ok": True,
        "experiment_id": xid,
        "recorded": fields,
    }), []


def t_regenerate_plan(args: dict) -> tuple[str, list[str]]:
    xid = _require_xid()
    if not xid:
        return json.dumps({"ok": False, "error": "no active experiment"}), []
    new_plan = planner.rebuild_plan_preserving_progress(
        xid, beamtime_hours=args.get("beamtime_hours"),
    )
    n = len(new_plan.get("sample_queue", []))
    _log_plan_edit_from_agent(
        xid, "regenerate",
        payload={"sample_count": n},
        reason=args.get("reason"),
    )
    return json.dumps({"ok": True, "sample_count": n}), []


# ---------------------------------------------------------------------------
# Dispatch table — merge upstream (CAT-0..CAT-7, CAT-9, CAT-10) with
# autonomy (CAT-8).
# ---------------------------------------------------------------------------

_AUTONOMY_DISPATCH: dict[str, callable] = {
    "measure_beam_size": t_measure_beam_size,
    "request_human_intervention": t_request_human_intervention,
    "post_status_update": t_post_status_update,
    "log_status_assessment": t_log_status_assessment,
    "update_plan": t_update_plan,
    "record_sample_progress": t_record_sample_progress,
    "record_convergence_stats": t_record_convergence_stats,
    "get_plan": t_get_plan,
    "get_experiment_config": t_get_experiment_config,
    "get_remaining_beamtime": t_get_remaining_beamtime,
    "set_experiment_end_time": t_set_experiment_end_time,
    "get_staff_guidance": t_get_staff_guidance,
    "list_open_interventions": t_list_open_interventions,
    "set_sample_time_budget": t_set_sample_time_budget,
    "set_holder_time_budget": t_set_holder_time_budget,
    "get_holder_time_budget": t_get_holder_time_budget,
    "get_scans_since_last_plan_update": t_get_scans_since_last_plan_update,
    "get_scans_for_active_sample": t_get_scans_for_active_sample,
    "upload_sample_alignment_results": t_upload_sample_alignment_results,
    "upload_sample_survey_results": t_upload_sample_survey_results,
    "get_comprehensive_collection_plan": t_get_comprehensive_collection_plan,
    "record_completed_scan": t_record_completed_scan,
    "record_alignment_flux": t_record_alignment_flux,
    "regenerate_plan": t_regenerate_plan,
}

# Autonomy overrides take precedence; upstream supplies the other ~101 handlers.
DISPATCH: dict[str, callable] = {**_UPSTREAM_DISPATCH, **_AUTONOMY_DISPATCH}
