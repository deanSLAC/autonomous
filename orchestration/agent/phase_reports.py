"""Per-phase summary-image generator.

Orchestrator-side hook fired by phase_runner._watch_exit when a phase
agent finishes successfully. Routes by slug:

    beamline_alignment → reports.alignment_report
    sample_survey      → reports.sample_report

Each route discovers its required inputs from the SPEC scan cache
(restricted to the phase run's [started_at, completed_at] window) and
the plan_store DB, calls the matching renderer in
orchestration.agent.reports, persists the PNG under
data/phase_reports/, and uploads it to Slack. Returns the saved path so
the caller can stamp it onto PhaseRun.summary_image_path. Every step is
best-effort — failures log and return None so the phase row update is
never blocked.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from orchestration.config import DATA_DIR
from orchestration.plan_store.session import get_phase_run, get_session
from orchestration.plan_store.models import SamplePosition


logger = logging.getLogger(__name__)


REPORTS_DIR = DATA_DIR / "phase_reports"


# Substring patterns (lower-case) that classify a SPEC motor name into one
# of the 8 grid slots in reports.alignment_report. Beam-size scans use Sz/Sx
# but those stages also drive the diagnostic pinhole alignment that
# immediately follows, so a motor-name match can't disambiguate them — beam
# size is intentionally omitted from this grid.
_ALIGNMENT_MOTOR_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("monvtra", ("monvtra",)),
    ("monhtra", ("monhtra",)),
    ("m1vert", ("m1vert",)),
    ("m2horz", ("m2horz",)),
    ("pitch", ("pitch",)),
    ("monvgap", ("monvgap",)),
    ("Bz", ("bz",)),
    ("Bx", ("bx",)),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_and_post(slug: str, phase_run_id: str) -> Optional[str]:
    """Render and post the summary image for a finished phase run.

    Returns the saved PNG path on success, or None if the slug is not
    handled, the inputs cannot be assembled, or rendering failed.
    """
    if slug not in ("beamline_alignment", "sample_survey"):
        return None
    try:
        run = get_phase_run(phase_run_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: get_phase_run failed for %s: %s", phase_run_id, e)
        return None
    if run is None or run.started_at is None:
        return None

    window = (run.started_at, run.completed_at or datetime.now())
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if slug == "beamline_alignment":
            path = _render_alignment(run.experiment_id, phase_run_id, window)
            caption = "Beamline alignment complete — summary report"
        else:
            path = _render_sample_survey(run.experiment_id, phase_run_id, window)
            caption = "Sample survey complete — summary report"
    except Exception as e:  # noqa: BLE001
        logger.exception("phase_reports: render failed for %s: %s", slug, e)
        return None

    if not path:
        return None

    try:
        _post_to_slack(path, caption)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: slack post failed: %s", e)

    return path


# ---------------------------------------------------------------------------
# Scan discovery (SPEC cache, restricted to phase window)
# ---------------------------------------------------------------------------

def _scans_in_window(window: tuple[datetime, datetime]) -> list[dict]:
    """Return SPEC scan dicts whose date_time falls inside the window."""
    try:
        from beamline_tools.spec_data import local_data
        scans = local_data._all_scans_sorted()
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: spec cache unavailable: %s", e)
        return []
    start, end = window
    out: list[dict] = []
    for s in scans:
        dt_str = s.get("date_time")
        if not dt_str:
            continue
        try:
            dt = datetime.fromisoformat(dt_str)
        except (TypeError, ValueError):
            continue
        if start <= dt <= end:
            s = dict(s)
            s["_dt"] = dt
            out.append(s)
    # Ascending by time so "last per motor" picks the converged scan.
    out.sort(key=lambda s: s["_dt"])
    return out


_MOTOR_RE = re.compile(r"^\s*(?:a|d|c|cd)scan\s+(\S+)", re.IGNORECASE)


def _motor_of(scan: dict) -> Optional[str]:
    cmd = scan.get("scan_command") or ""
    m = _MOTOR_RE.match(cmd)
    if not m:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# Alignment report
# ---------------------------------------------------------------------------

def _pick_alignment_scans(window) -> tuple[Optional[str], list[Optional[int]]]:
    """Return (spec_datafile, ordered list of 8 scan_numbers).

    Each slot is the latest scan whose motor matches that slot's patterns.
    Slots with no match are None — the renderer draws 'No data' there.
    The spec_datafile is taken from the chosen scans (one file expected per
    phase run; if multiple, the one with the most matches wins).
    """
    n_slots = len(_ALIGNMENT_MOTOR_PATTERNS)
    scans = _scans_in_window(window)
    if not scans:
        return None, [None] * n_slots

    picks: list[Optional[dict]] = [None] * n_slots
    for slot_idx, (_, patterns) in enumerate(_ALIGNMENT_MOTOR_PATTERNS):
        for s in scans:  # ascending → last wins by overwrite
            motor = (_motor_of(s) or "").lower()
            if not motor:
                continue
            if any(p in motor for p in patterns):
                picks[slot_idx] = s

    # Pick the spec_datafile that backs the most chosen scans.
    from collections import Counter
    files = Counter(s["file_path"] for s in picks if s and s.get("file_path"))
    spec_datafile = files.most_common(1)[0][0] if files else None

    scan_numbers: list[Optional[int]] = []
    for s in picks:
        if s and s.get("file_path") == spec_datafile:
            scan_numbers.append(int(s.get("scan_number")) if s.get("scan_number") is not None else None)
        else:
            scan_numbers.append(None)
    return spec_datafile, scan_numbers


def _render_alignment(
    experiment_id: str,
    phase_run_id: str,
    window: tuple[datetime, datetime],
) -> Optional[str]:
    spec_datafile, scan_numbers = _pick_alignment_scans(window)
    if not spec_datafile or not any(n is not None for n in scan_numbers):
        logger.info("phase_reports: no alignment scans in window for %s", phase_run_id)
        return None

    metadata = _alignment_metadata(experiment_id)
    # reports.alignment_report pads to length 9 internally but expects a flat
    # list of ints. Replace Nones with a sentinel scan number (-1) so the
    # renderer's per-cell try/except draws "No data" for missing slots.
    sn_arg = [n if n is not None else -1 for n in scan_numbers]
    out_path = str(REPORTS_DIR / f"alignment_{phase_run_id}.png")
    out_dir = str(REPORTS_DIR)

    from orchestration.agent import reports
    written = reports.alignment_report(
        spec_datafile=spec_datafile,
        scan_numbers=sn_arg,
        output_dir=out_dir,
        metadata=metadata,
    )
    # alignment_report writes its own timestamped filename; rename to the
    # phase_run-keyed name so summary_image_path is stable.
    try:
        if written and written != out_path:
            os.replace(written, out_path)
    except OSError as e:
        logger.warning("phase_reports: rename failed (%s → %s): %s", written, out_path, e)
        return written
    return out_path


def _alignment_metadata(experiment_id: str) -> dict:
    """Pull experiment-level annotations for the alignment_report footer."""
    md: dict = {}
    try:
        from orchestration.plan_store.models import Experiment
        with get_session() as session:
            exp = session.get(Experiment, experiment_id)
            if exp:
                md["experiment_name"] = exp.name
                if exp.mono_crystal:
                    md["crystal"] = exp.mono_crystal
                if getattr(exp, "beam_h_fwhm_um", None):
                    md["beam_h_fwhm"] = float(exp.beam_h_fwhm_um)
                if getattr(exp, "beam_v_fwhm_um", None):
                    md["beam_v_fwhm"] = float(exp.beam_v_fwhm_um)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: experiment lookup failed: %s", e)
    md["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return md


# ---------------------------------------------------------------------------
# Sample survey report
# ---------------------------------------------------------------------------

def _pick_survey_inputs(experiment_id: str, window) -> tuple[Optional[str], Optional[int], list[dict]]:
    """Return (spec_datafile, survey_scan_number, sample_positions[]).

    The 'wide Sz survey' is heuristically the Sz scan in the window with
    the largest motor range. Per-sample fine-alignment scans are not
    currently attributable to specific samples — sample_scans is left
    empty (the renderer handles this gracefully).
    """
    scans = _scans_in_window(window)
    sz_scans: list[tuple[float, dict]] = []
    for s in scans:
        motor = (_motor_of(s) or "").lower()
        if "sz" not in motor:
            continue
        cmd = (s.get("scan_command") or "").split()
        try:
            start = float(cmd[2])
            end = float(cmd[3])
            span = abs(end - start)
        except (IndexError, ValueError):
            span = 0.0
        sz_scans.append((span, s))

    if not sz_scans:
        survey = None
        spec_datafile = scans[-1]["file_path"] if scans else None
    else:
        sz_scans.sort(key=lambda t: t[0], reverse=True)
        survey = sz_scans[0][1]
        spec_datafile = survey.get("file_path")

    positions = _sample_positions_for_experiment(experiment_id)

    return spec_datafile, (int(survey["scan_number"]) if survey else None), positions


def _sample_positions_for_experiment(experiment_id: str) -> list[dict]:
    out: list[dict] = []
    try:
        from sqlmodel import select
        with get_session() as session:
            stmt = (
                select(SamplePosition)
                .where(SamplePosition.experiment_id == experiment_id)
                .where(SamplePosition.enabled == True)  # noqa: E712
                .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
            )
            for sp in session.exec(stmt).all():
                out.append({
                    "sample_number": sp.sample_number,
                    "sample_name": sp.sample_name,
                    "element_symbol": sp.element_symbol,
                    "sx_lo": sp.sx_lo, "sx_hi": sp.sx_hi,
                    "sy_lo": sp.sy_lo, "sy_hi": sp.sy_hi,
                    "sz_lo": sp.sz_lo, "sz_hi": sp.sz_hi,
                    "total_spots": sp.total_spots,
                    "emiss_energy_eV": sp.emiss_energy_eV,
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: sample positions lookup failed: %s", e)
    return out


def _render_sample_survey(
    experiment_id: str,
    phase_run_id: str,
    window: tuple[datetime, datetime],
) -> Optional[str]:
    spec_datafile, survey_scan, positions = _pick_survey_inputs(experiment_id, window)
    if not spec_datafile or survey_scan is None:
        logger.info(
            "phase_reports: no survey scan in window for %s (positions=%d)",
            phase_run_id, len(positions),
        )
        # No Sz scan to draw — skip rather than emit an empty PNG.
        return None

    out_path = str(REPORTS_DIR / f"sample_survey_{phase_run_id}.png")
    out_dir = str(REPORTS_DIR)

    from orchestration.agent import reports
    written = reports.sample_report(
        spec_datafile=spec_datafile,
        survey_scan=survey_scan,
        sample_scans={},  # per-sample fine-align attribution unavailable
        sample_positions=positions,
        output_dir=out_dir,
    )
    try:
        if written and written != out_path:
            os.replace(written, out_path)
    except OSError as e:
        logger.warning("phase_reports: rename failed (%s → %s): %s", written, out_path, e)
        return written
    return out_path


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _post_to_slack(image_path: str, caption: str) -> None:
    try:
        from ui.adapters.slack_notify import SlackNotifier
    except Exception as e:  # noqa: BLE001
        logger.info("phase_reports: slack notifier unavailable (%s) — skipping post", e)
        return
    channel = os.getenv("SLACK_CHAT_CHANNEL_ID") or os.getenv("SLACK_CHANNEL_ID")
    notifier = SlackNotifier(enabled=True, channel=channel)
    logger.info(
        "phase_reports: posting image to slack (enabled=%s) path=%s",
        notifier.enabled, image_path,
    )
    notifier.post_image(image_path, caption=caption)
