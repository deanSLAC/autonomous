"""Per-phase summary-image generator.

Orchestrator-side hook fired by phase_runner._watch_exit when a phase
agent finishes successfully. Routes by slug:

    beamline_alignment → reports.alignment_report
    sample_alignment   → reports.sample_report
    sample_survey      → reports.survey_report

Each route discovers its required inputs from the SPEC scan cache
(restricted to the phase run's [started_at, completed_at] window,
padded by _WINDOW_PAD_S to absorb clock skew between the SPEC host
and this machine) and the plan_store DB, calls the matching renderer
in orchestration.agent.reports, persists the PNG under
data/phase_reports/, and uploads it to Slack. Returns the saved path so
the caller can stamp it onto PhaseRun.summary_image_path. Every step is
best-effort — failures log and return None so the phase row update is
never blocked.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from orchestration.config import DATA_DIR
from orchestration.plan_store.session import get_phase_run, get_session
from orchestration.plan_store.models import SamplePosition


logger = logging.getLogger(__name__)


REPORTS_DIR = DATA_DIR / "phase_reports"

# Seconds added on both ends of the phase window before matching SPEC
# scan timestamps. The #D lines come from the SPEC host's clock; the
# PhaseRun timestamps come from this machine's. A couple of minutes of
# skew between the two must not empty the window (the historical
# "report rendered with every cell blank" failure).
_WINDOW_PAD_S = 120.0


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
    if slug not in ("beamline_alignment", "sample_alignment", "sample_survey"):
        return None
    try:
        run = get_phase_run(phase_run_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: get_phase_run failed for %s: %s", phase_run_id, e)
        return None
    if run is None or run.started_at is None:
        return None

    pad = timedelta(seconds=_WINDOW_PAD_S)
    window = (
        run.started_at - pad,
        (run.completed_at or datetime.now()) + pad,
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if slug == "beamline_alignment":
            path = _render_alignment(run.experiment_id, phase_run_id, window)
            caption = "Beamline alignment complete — summary report"
        elif slug == "sample_alignment":
            path = _render_sample_alignment(run.experiment_id, phase_run_id, window)
            caption = "Sample alignment complete — summary report"
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
        from beamtimehero_cli.spec_data import local_data
        scans = local_data._all_scans_sorted()
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: spec cache unavailable: %s", e)
        return []
    start, end = window
    out: list[dict] = []
    for s in scans:
        dt_val = s.get("date_time")
        if dt_val is None:
            continue
        if isinstance(dt_val, datetime):
            dt = dt_val
        elif isinstance(dt_val, str):
            try:
                dt = datetime.fromisoformat(dt_val)
            except ValueError:
                continue
        else:
            continue
        if start <= dt <= end:
            s = dict(s)
            s["_dt"] = dt
            out.append(s)
    # Ascending by time so "last per motor" picks the converged scan.
    out.sort(key=lambda s: s["_dt"])
    logger.info(
        "phase_reports: %d/%d cached scans fall in window [%s .. %s]",
        len(out), len(scans), start, end,
    )
    if scans and not out:
        # The classic blank-report cause — say what would have helped.
        newest = max((s.get("date_time") for s in scans if s.get("date_time")), default=None)
        logger.warning(
            "phase_reports: scan cache is non-empty but nothing matched the "
            "window — check SPEC-host vs orchestrator clock skew "
            "(newest cached scan: %s)", newest,
        )
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

    unmatched = [
        label for (label, _), n in zip(_ALIGNMENT_MOTOR_PATTERNS, scan_numbers)
        if n is None
    ]
    if unmatched:
        seen_motors = sorted({(_motor_of(s) or "?") for s in scans})
        logger.info(
            "phase_reports: alignment grid slots without a matching scan: %s "
            "(motors seen in window: %s)", unmatched, seen_motors,
        )
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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(REPORTS_DIR / f"alignment_{phase_run_id}_{ts}.png")
    out_dir = str(REPORTS_DIR)

    from orchestration.agent import reports
    written = reports.alignment_report(
        spec_datafile=spec_datafile,
        scan_numbers=sn_arg,
        output_dir=out_dir,
        metadata=metadata,
    )
    # alignment_report writes its own timestamped filename; rename to the
    # phase_run-keyed name so summary_image_path is recorded once and stable.
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
                if getattr(exp, "i0_max_cps", None):
                    md["i0_max_cps"] = float(exp.i0_max_cps)
                if getattr(exp, "i0_gain", None):
                    md["i0_gain"] = str(exp.i0_gain)
                if getattr(exp, "i1_max_cps", None):
                    md["i1_max_cps"] = float(exp.i1_max_cps)
                if getattr(exp, "i1_gain", None):
                    md["i1_gain"] = str(exp.i1_gain)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: experiment lookup failed: %s", e)
    md["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return md


# ---------------------------------------------------------------------------
# Sample alignment report
# ---------------------------------------------------------------------------

_SAMPLE_MOTORS = ("sz", "sx", "sy")


def _scan_range(scan: dict) -> Optional[tuple[float, float]]:
    """Parse (lo, hi) out of an `a/dscan <motor> <lo> <hi> ...` command."""
    toks = (scan.get("scan_command") or "").split()
    try:
        lo, hi = float(toks[2]), float(toks[3])
    except (IndexError, ValueError):
        return None
    return (lo, hi) if lo <= hi else (hi, lo)


def _sample_positions_for_alignment(experiment_id: str) -> list[dict]:
    """Enabled SamplePosition rows as the dicts reports.sample_report wants."""
    from sqlmodel import select

    positions: list[dict] = []
    try:
        with get_session() as session:
            stmt = (
                select(SamplePosition)
                .where(SamplePosition.experiment_id == experiment_id)
                .where(SamplePosition.enabled == True)  # noqa: E712
                .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
            )
            for sp in session.exec(stmt).all():
                positions.append({
                    "sample_number": sp.sample_number,
                    "sample_name": sp.sample_name,
                    "element_symbol": sp.element_symbol,
                    "sx_lo": sp.sx_lo, "sx_hi": sp.sx_hi,
                    "sy_lo": sp.sy_lo, "sy_hi": sp.sy_hi,
                    "sz_lo": sp.sz_lo, "sz_hi": sp.sz_hi,
                    "total_spots": sp.total_spots,
                    "emiss_energy_eV": getattr(sp, "emiss_energy_eV", None),
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: sample position lookup failed: %s", e)
    return positions


def _pick_sample_alignment_inputs(
    experiment_id: str,
    window: tuple[datetime, datetime],
) -> tuple[Optional[str], Optional[int], dict[int, list[int]], list[dict]]:
    """Return (spec_datafile, survey_scan, sample_scans, sample_positions).

    The aligner's procedure is: one wide Sz survey, then per-sample fine
    scans (Sz, then Sx/Sy boundaries) sample by sample. Discovery mirrors
    that shape:

      * survey  = the widest Sz scan in the window;
      * blocks  = scans after the survey, attributed to the sample whose
        aligned [sz_lo, sz_hi] contains the block-opening Sz scan's
        center; Sx/Sy scans attach to the current block (the procedure
        is sequential per sample).
    """
    scans = _scans_in_window(window)
    motor_scans: list[tuple[dict, str]] = []
    for s in scans:
        motor = (_motor_of(s) or "").lower()
        if motor in _SAMPLE_MOTORS:
            motor_scans.append((s, motor))
    positions = _sample_positions_for_alignment(experiment_id)
    if not motor_scans:
        return None, None, {}, positions

    # Spec file: the one backing the most sample-stage scans.
    from collections import Counter
    files = Counter(
        s["file_path"] for s, _ in motor_scans if s.get("file_path")
    )
    spec_datafile = files.most_common(1)[0][0] if files else None
    motor_scans = [
        (s, m) for s, m in motor_scans if s.get("file_path") == spec_datafile
    ]

    # Stable procedure order: #D timestamps have 1 s resolution, so fast
    # consecutive scans tie on time — break ties by scan number.
    motor_scans.sort(
        key=lambda pair: (pair[0]["_dt"], pair[0].get("scan_number") or 0)
    )

    # Survey: widest Sz scan.
    survey = None
    survey_idx = -1
    survey_width = -1.0
    for idx, (s, m) in enumerate(motor_scans):
        if m != "sz":
            continue
        rng = _scan_range(s)
        width = (rng[1] - rng[0]) if rng else 0.0
        if width > survey_width:
            survey, survey_idx, survey_width = s, idx, width
    survey_scan = int(survey["scan_number"]) if survey else None

    # Sequential block attribution after the survey.
    sample_scans: dict[int, list[int]] = {}
    current: Optional[int] = None
    for s, m in motor_scans[survey_idx + 1:]:
        if m == "sz":
            rng = _scan_range(s)
            if rng:
                center = (rng[0] + rng[1]) / 2
                for sp in positions:
                    lo, hi = sp.get("sz_lo", 0.0), sp.get("sz_hi", 0.0)
                    if (lo or hi) and lo - 0.5 <= center <= hi + 0.5:
                        current = sp["sample_number"]
                        break
        if current is not None and s.get("scan_number") is not None:
            sample_scans.setdefault(current, []).append(int(s["scan_number"]))

    if not sample_scans:
        logger.info(
            "phase_reports: no per-sample fine scans attributed "
            "(%d stage scans in window, survey=%s, %d positions)",
            len(motor_scans), survey_scan, len(positions),
        )
    return spec_datafile, survey_scan, sample_scans, positions


def _render_sample_alignment(
    experiment_id: str,
    phase_run_id: str,
    window: tuple[datetime, datetime],
) -> Optional[str]:
    spec_datafile, survey_scan, sample_scans, positions = (
        _pick_sample_alignment_inputs(experiment_id, window)
    )
    if not spec_datafile or survey_scan is None:
        logger.info(
            "phase_reports: no sample-alignment scans in window for %s",
            phase_run_id,
        )
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(REPORTS_DIR / f"sample_alignment_{phase_run_id}_{ts}.png")
    out_dir = str(REPORTS_DIR)

    from orchestration.agent import reports
    written = reports.sample_report(
        spec_datafile=spec_datafile,
        survey_scan=survey_scan,
        sample_scans=sample_scans,
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
# Sample survey report
# ---------------------------------------------------------------------------

def _resolve_spec_datafile(name: Optional[str]) -> Optional[str]:
    """Map a CollectionScan.spec_datafile (basename) to the full path
    in the local SPEC scan cache. Returns the input as-is if it's
    already absolute, or None if no match.
    """
    if not name:
        return None
    if name.startswith("/"):
        return name
    try:
        from beamtimehero_cli.spec_data import local_data
        for s in local_data._all_scans_sorted():
            if s.get("file_name") == name and s.get("file_path"):
                return s.get("file_path")
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: spec datafile resolve failed: %s", e)
    return None


def _pick_survey_inputs(
    experiment_id: str,
    window: tuple[datetime, datetime],
) -> tuple[Optional[str], dict[str, list[int]], list[dict]]:
    """Return (spec_datafile, sample_scans, sample_positions).

    The surveyor runs `run_xas` per sample-spot and calls
    `record_completed_scan` after each one, which writes a CollectionScan
    row carrying (sample_id, scan_number, spec_datafile, timestamp). We
    group those by sample_id for the per-sample XAS overlays, and pull
    the matching SamplePosition rows (filtered to ones the surveyor
    actually finished) for the results table.
    """
    from collections import Counter, defaultdict
    from sqlmodel import select
    from orchestration.plan_store.models import CollectionScan

    start, end = window
    sample_scans: dict[str, list[int]] = defaultdict(list)
    files: Counter = Counter()
    positions: list[dict] = []

    try:
        with get_session() as session:
            scan_stmt = (
                select(CollectionScan)
                .where(CollectionScan.experiment_id == experiment_id)
                .where(CollectionScan.timestamp >= start)
                .where(CollectionScan.timestamp <= end)
                .order_by(CollectionScan.timestamp)  # type: ignore[union-attr]
            )
            for row in session.exec(scan_stmt).all():
                sample_scans[row.sample_id].append(int(row.scan_number))
                if row.spec_datafile:
                    files[row.spec_datafile] += 1

            pos_stmt = (
                select(SamplePosition)
                .where(SamplePosition.experiment_id == experiment_id)
                .where(SamplePosition.enabled == True)  # noqa: E712
                .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
            )
            for sp in session.exec(pos_stmt).all():
                # Only include samples the surveyor finished (or that
                # at least picked up scans in this window).
                if sp.survey_completed_at is None and sp.id not in sample_scans:
                    continue
                positions.append({
                    "sample_id": sp.id,
                    "sample_number": sp.sample_number,
                    "sample_name": sp.sample_name,
                    "element_symbol": sp.element_symbol,
                    "xas_filter": sp.xas_filter,
                    "survey_counts_per_sec": sp.survey_counts_per_sec,
                    "survey_energy_ev": sp.survey_energy_ev,
                    "survey_notes": sp.survey_notes,
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_reports: survey lookup failed: %s", e)

    raw_name = files.most_common(1)[0][0] if files else None
    spec_datafile = _resolve_spec_datafile(raw_name)
    return spec_datafile, dict(sample_scans), positions


def _render_sample_survey(
    experiment_id: str,
    phase_run_id: str,
    window: tuple[datetime, datetime],
) -> Optional[str]:
    spec_datafile, sample_scans, positions = _pick_survey_inputs(experiment_id, window)
    if not spec_datafile or not sample_scans:
        logger.info(
            "phase_reports: no survey scans in window for %s (positions=%d)",
            phase_run_id, len(positions),
        )
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(REPORTS_DIR / f"sample_survey_{phase_run_id}_{ts}.png")
    out_dir = str(REPORTS_DIR)

    from orchestration.agent import reports
    written = reports.survey_report(
        spec_datafile=spec_datafile,
        sample_scans=sample_scans,
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
    from orchestration.config import SLACK_CHAT_CHANNEL_ID
    channel = SLACK_CHAT_CHANNEL_ID
    notifier = SlackNotifier(enabled=True, channel=channel)
    logger.info(
        "phase_reports: posting image to slack (enabled=%s) path=%s",
        notifier.enabled, image_path,
    )
    notifier.post_image(image_path, caption=caption)
