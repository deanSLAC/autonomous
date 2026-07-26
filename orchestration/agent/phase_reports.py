"""Per-phase summary-image generator.

Orchestrator-side hook fired by phase_runner._watch_exit when a phase
agent finishes successfully. Routes by slug:

    beamline_alignment → reports.alignment_report
    xes_alignment      → reports.spectrometer_report
    sample_alignment   → reports.sample_report
    sample_survey      → reports.survey_report

Each route discovers its required inputs from the SPEC scan cache
(restricted to the phase run's [started_at, completed_at] window,
padded by _WINDOW_PAD_S to absorb clock skew between the SPEC host
and this machine) and the plan_store DB, calls the matching renderer
in orchestration.agent.reports, persists the PNG under
data/phase_reports/, and uploads it to Slack.

Failures are REPORTED, not swallowed. generate_and_post returns a
ReportOutcome carrying either a path or a specific reason, and the caller
stamps that reason onto the PhaseRun so the UI can say "report failed:
<why>". Previously every failure path returned a bare None, which the
phase page rendered identically to "this phase has no report" — so a
broken report was indistinguishable from an absent one, and four separate
render bugs went unnoticed for a month (see the 2026-05-11 and 2026-06-11
fix rounds). Rendering is still best-effort in the sense that it never
blocks the phase row update.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import NamedTuple, Optional

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

class ReportOutcome(NamedTuple):
    """Result of a summary-report attempt.

    Exactly one of `path` / `error` is set, except for the not-applicable case
    where both are None: this slug has no report and nothing went wrong. That
    distinction is the whole point — `error` is what lets the UI show "report
    failed: <why>" instead of silently hiding the container.
    """

    path: Optional[str] = None
    error: Optional[str] = None

    @property
    def failed(self) -> bool:
        return self.error is not None


# Slugs that produce a summary image, and the caption used for the Slack post.
_ROUTES = {
    "beamline_alignment": "Beamline alignment complete — summary report",
    "xes_alignment": "Spectrometer (XES) alignment complete — summary report",
    "sample_alignment": "Sample alignment complete — summary report",
    "sample_survey": "Sample survey complete — summary report",
}


def generate_and_post(slug: str, phase_run_id: str) -> ReportOutcome:
    """Render and post the summary image for a finished phase run.

    Returns ReportOutcome(path=...) on success, ReportOutcome(error=...) with a
    specific reason on failure, and ReportOutcome() when this slug simply has no
    report to make.
    """
    if slug not in _ROUTES:
        return ReportOutcome()

    def fail(msg: str) -> ReportOutcome:
        logger.warning("phase_reports: %s [%s]: %s", slug, phase_run_id, msg)
        return ReportOutcome(error=msg)

    try:
        run = get_phase_run(phase_run_id)
    except Exception as e:  # noqa: BLE001
        return fail(f"could not load phase run: {e}")
    if run is None:
        return fail("phase run row not found")
    if run.started_at is None:
        return fail("phase run has no started_at, so the scan window is unknown")

    pad = timedelta(seconds=_WINDOW_PAD_S)
    window = (
        run.started_at - pad,
        (run.completed_at or datetime.now()) + pad,
    )
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return fail(f"cannot create {REPORTS_DIR}: {e}")

    renderers = {
        "beamline_alignment": _render_alignment,
        "xes_alignment": _render_spectrometer,
        "sample_alignment": _render_sample_alignment,
        "sample_survey": _render_sample_survey,
    }
    try:
        path = renderers[slug](run.experiment_id, phase_run_id, window)
    except Exception as e:  # noqa: BLE001
        logger.exception("phase_reports: render raised for %s: %s", slug, e)
        return fail(f"renderer raised {type(e).__name__}: {e}")

    if not path:
        # The renderer declined — almost always "no matching scans in the phase
        # window". Say so, and say what the window was: that is the single most
        # useful fact when a report comes up empty.
        return fail("no usable scans found in the phase window "
                    f"{window[0]:%H:%M:%S}–{window[1]:%H:%M:%S} "
                    f"(±{int(_WINDOW_PAD_S)}s clock-skew pad)")
    if not os.path.exists(path):
        return fail(f"renderer returned {path} but no file is there")

    try:
        _post_to_slack(path, _ROUTES[slug])
    except Exception as e:  # noqa: BLE001
        # A failed Slack post is not a failed report — the image exists and the
        # UI will show it. Log and carry on.
        logger.warning("phase_reports: slack post failed for %s: %s", slug, e)

    logger.info("phase_reports: %s [%s] wrote %s", slug, phase_run_id, path)
    return ReportOutcome(path=path)


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


# ---------------------------------------------------------------------------
# Spectrometer (XES) alignment report
# ---------------------------------------------------------------------------

# c1y..c7y (pitch/Ath) and c1p..c7p (roll/Achi). Two digits because the XRS
# spectrometer numbers its 66 crystals c11..c58. Anchored and matched against
# the scanned motor only: ordinary files carry analyser *counters* named c5/c6/c7,
# and `crystal` is a real mono motor.
_CRYSTAL_SCAN_RE = re.compile(r"^c(\d{1,2})([yp])$", re.IGNORECASE)


def _pick_spectrometer_scans(window) -> tuple[Optional[str], list[int]]:
    """(spec_datafile, crystal scan numbers) for an xes_align run in this window.

    reports.spectrometer_report classifies the scans itself by motor name, so
    this only has to find them and agree on one data file.
    """
    scans = _scans_in_window(window)
    if not scans:
        return None, []

    matched = [s for s in scans if _CRYSTAL_SCAN_RE.match((_motor_of(s) or "").strip())]
    if not matched:
        seen = sorted({(_motor_of(s) or "?") for s in scans})
        logger.info("phase_reports: no c#y/c#p scans in window; motors seen: %s", seen)
        return None, []

    from collections import Counter
    files = Counter(s["file_path"] for s in matched if s.get("file_path"))
    if not files:
        return None, []
    spec_datafile = files.most_common(1)[0][0]
    numbers = [int(s["scan_number"]) for s in matched
               if s.get("file_path") == spec_datafile
               and s.get("scan_number") is not None]
    return spec_datafile, sorted(numbers)


def _spectrometer_elements(experiment_id: str) -> list[dict]:
    """Element rows for spectrometer_report's resolution table (best effort)."""
    out: list[dict] = []
    try:
        from sqlmodel import select
        from orchestration.plan_store.models import ExperimentElement
        with get_session() as session:
            rows = session.exec(
                select(ExperimentElement).where(
                    ExperimentElement.experiment_id == experiment_id)
            ).all()
            for r in rows:
                row = {"symbol": getattr(r, "symbol", None) or getattr(r, "element", "")}
                for src, dst in (("crystal_cut", "crystal_cut"),
                                 ("expected_fwhm", "expected_fwhm")):
                    val = getattr(r, src, None)
                    if val is not None:
                        row[dst] = val
                out.append(row)
    except Exception as e:  # noqa: BLE001
        logger.info("phase_reports: element lookup for resolution table failed: %s", e)
    return out


def _render_spectrometer(
    experiment_id: str,
    phase_run_id: str,
    window: tuple[datetime, datetime],
) -> Optional[str]:
    spec_datafile, scan_numbers = _pick_spectrometer_scans(window)
    if not spec_datafile or not scan_numbers:
        return None
    resolved = _resolve_spec_datafile(spec_datafile)
    if not resolved:
        logger.info("phase_reports: could not resolve spec file %s", spec_datafile)
        return None
    from orchestration.agent import reports
    return reports.spectrometer_report(
        spec_datafile=resolved,
        scan_numbers=scan_numbers,
        elements=_spectrometer_elements(experiment_id),
        output_dir=str(REPORTS_DIR),
    )


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
