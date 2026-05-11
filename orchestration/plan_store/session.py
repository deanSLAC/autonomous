"""CRUD helpers + engine/session for the orchestration plan_store DB.

Holds: experiments, phase runs, scan records, sample holders, LLM logs,
plan + staff guidance + interventions. Bound to
`ORCHESTRATION_DB_PATH` (see orchestration.config). Separate sqlite
file from the beamline_tools action_log DB.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from orchestration.plan_store.models import (
    CollectionScan,
    Experiment,
    ExperimentElement,
    Image,
    LLMLog,
    MotorPosition,
    PhaseRun,
    SampleHolder,
    SamplePosition,
    ScanRecord,
)

_SENTINEL = object()
_logger = logging.getLogger(__name__)

_RETRY_BACKOFF = (0.1, 0.2, 0.4)


def _commit_with_retry(
    session: Session, max_attempts: int = 3,
) -> None:
    """Retry session.commit() on transient SQLite BUSY errors."""
    for attempt in range(max_attempts):
        try:
            session.commit()
            return
        except OperationalError as e:
            if "database is locked" not in str(e) or attempt == max_attempts - 1:
                raise
            _logger.warning("SQLite BUSY on commit (attempt %d/%d), retrying",
                            attempt + 1, max_attempts)
            time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])


# ---------------------------------------------------------------------------
# Engine / session management
# ---------------------------------------------------------------------------

_engine = None


def _db_path() -> str:
    return os.environ.get(
        "ORCHESTRATION_DB_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "data" / "orchestration.db"),
    )


def get_engine(db_path: str | None = None):
    """Return a singleton SQLAlchemy engine with WAL + busy_timeout."""
    global _engine
    if _engine is not None:
        return _engine

    if db_path is None:
        db_path = _db_path()

    db_url = f"sqlite:///{db_path}"
    _engine = create_engine(db_url, echo=False)

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    SQLModel.metadata.create_all(_engine)
    _migrate_holder_pacing(_engine)
    _migrate_sample_position(_engine)
    _migrate_plan_version(_engine)

    return _engine


def _migrate_holder_pacing(engine):
    """Add started_at/completed_at columns to sampleholder if missing."""
    import sqlite3
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sampleholder)")
        columns = {row[1] for row in cursor.fetchall()}
        if "started_at" not in columns:
            cursor.execute("ALTER TABLE sampleholder ADD COLUMN started_at TEXT")
        if "completed_at" not in columns:
            cursor.execute("ALTER TABLE sampleholder ADD COLUMN completed_at TEXT")
        if "stop_time" not in columns:
            cursor.execute("ALTER TABLE sampleholder ADD COLUMN stop_time TEXT")
        cursor.execute("""
            UPDATE sampleholder SET started_at = created_at
            WHERE status = 'done' AND started_at IS NULL
        """)
        cursor.execute("""
            UPDATE sampleholder SET completed_at = updated_at
            WHERE status = 'done' AND completed_at IS NULL
        """)
        conn.commit()
    finally:
        conn.close()


def _migrate_sample_position(engine):
    """Add new columns to sampleposition if missing.

    SQLite doesn't auto-evolve schemas; new fields on SamplePosition need to
    be added here so pre-existing DBs don't 500 on column-not-found.
    """
    import sqlite3
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sampleposition)")
        columns = {row[1] for row in cursor.fetchall()}
        if "min_scans" not in columns:
            cursor.execute("ALTER TABLE sampleposition ADD COLUMN min_scans INTEGER")
        if "xas_filter_suggested" not in columns:
            cursor.execute(
                "ALTER TABLE sampleposition ADD COLUMN xas_filter_suggested INTEGER NOT NULL DEFAULT 0"
            )
            # Backfill from xas_filter so currently-aligned holders don't
            # appear to "lose" their value when the operator re-opens them.
            cursor.execute(
                "UPDATE sampleposition SET xas_filter_suggested = xas_filter "
                "WHERE xas_filter_suggested = 0 AND xas_filter > 0"
            )
        conn.commit()
    finally:
        conn.close()


def _migrate_plan_version(engine):
    """Add version column to experimentplan if missing."""
    import sqlite3
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(experimentplan)")
        cols = {row[1] for row in cursor.fetchall()}
        if "version" not in cols:
            cursor.execute(
                "ALTER TABLE experimentplan ADD COLUMN version INTEGER DEFAULT 0"
            )
            conn.commit()
    finally:
        conn.close()


def get_session() -> Session:
    """Return a new SQLModel Session bound to the singleton engine."""
    return Session(get_engine())


# ---------------------------------------------------------------------------
# Experiment CRUD
# ---------------------------------------------------------------------------

def create_experiment(
    name: str,
    experimenter: Optional[str] = None,
    mono_crystal: str = "A",
    beam_size_h: str = "big",
    beam_size_v: str = "big",
    mirrors_out: bool = False,
    sample_env: Optional[str] = None,
    data_path: Optional[str] = None,
    calibration_foil_element: Optional[str] = None,
    calibration_foil_detector: str = "I2",
) -> Experiment:
    """Create and persist a new Experiment."""
    exp = Experiment(
        name=name,
        experimenter=experimenter,
        mono_crystal=mono_crystal,
        beam_size_h=beam_size_h,
        beam_size_v=beam_size_v,
        mirrors_out=mirrors_out,
        sample_env=sample_env,
        data_path=data_path,
        calibration_foil_element=calibration_foil_element,
        calibration_foil_detector=calibration_foil_detector or "I2",
    )
    with get_session() as session:
        session.add(exp)
        session.commit()
        session.refresh(exp)
    return exp


def get_experiment(experiment_id: str) -> Optional[Experiment]:
    """Fetch an Experiment by ID, or None if not found."""
    with get_session() as session:
        return session.get(Experiment, experiment_id)


def get_active_experiment() -> Optional[Experiment]:
    """Return the most recently created Experiment that is not done."""
    with get_session() as session:
        stmt = (
            select(Experiment)
            .where(Experiment.status != "done")
            .order_by(Experiment.created_at.desc())  # type: ignore[union-attr]
        )
        return session.exec(stmt).first()


def update_experiment_status(experiment_id: str, status: str) -> Optional[Experiment]:
    """Update the status field of an Experiment."""
    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            return None
        exp.status = status
        session.add(exp)
        session.commit()
        session.refresh(exp)
    return exp


def record_measured_beam_size(
    experiment_id: str,
    h_fwhm_um: Optional[float],
    v_fwhm_um: Optional[float],
) -> Optional[Experiment]:
    """Store the latest measured beam-size FWHM (in µm) on the experiment row.

    Called from spec_cmd whenever `wbeamsize` returns parseable values.
    Either dimension can be None — caller decides whether the missing one
    should overwrite a previous value (it doesn't here).
    """
    if h_fwhm_um is None and v_fwhm_um is None:
        return None
    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            return None
        if h_fwhm_um is not None:
            exp.beam_h_fwhm_um = float(h_fwhm_um)
        if v_fwhm_um is not None:
            exp.beam_v_fwhm_um = float(v_fwhm_um)
        session.add(exp)
        session.commit()
        session.refresh(exp)
    return exp


def set_spectrometer_aligned(experiment_id: str, aligned: bool) -> Optional[Experiment]:
    """Mark the spectrometer as aligned (or clear the flag) for an experiment.

    The flag is set by the operator via the Spectrometer Alignment tile's
    Mark Complete button after they have manually aligned the crystals.
    Reset button on the same tile clears it. Used by the dashboard to gate
    Sample Alignment + Data Collection.
    """
    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            return None
        exp.spectrometer_aligned = bool(aligned)
        session.add(exp)
        session.commit()
        session.refresh(exp)
    return exp


# ---------------------------------------------------------------------------
# ExperimentElement
# ---------------------------------------------------------------------------

def create_experiment_element(
    experiment_id: str,
    element_symbol: str,
    edge: str,
    incident_energy_eV: float,
    emission_energy_eV: float,
    crystal_type: int,
    crystal_hkl: str,
    row_radius: int,
    n_crystals: int,
    vortex_counter: str = "vortDT",
    priority: int = 0,
    measurement_mode: str = "XES",
    emission_line: Optional[str] = None,
) -> ExperimentElement:
    """Create and persist a new ExperimentElement."""
    from orchestration.plan_store.models import vortex_channel_for_counter
    elem = ExperimentElement(
        experiment_id=experiment_id,
        element_symbol=element_symbol,
        edge=edge,
        measurement_mode=measurement_mode,
        emission_line=emission_line,
        incident_energy_eV=incident_energy_eV,
        emission_energy_eV=emission_energy_eV,
        crystal_type=crystal_type,
        crystal_hkl=crystal_hkl,
        row_radius=row_radius,
        n_crystals=n_crystals,
        vortex_counter=vortex_counter,
        vortex_channel=vortex_channel_for_counter(vortex_counter),
        priority=priority,
    )
    with get_session() as session:
        session.add(elem)
        session.commit()
        session.refresh(elem)
    return elem


def get_elements_for_experiment(experiment_id: str) -> list[ExperimentElement]:
    """Return all elements for an experiment, ordered by priority."""
    with get_session() as session:
        stmt = (
            select(ExperimentElement)
            .where(ExperimentElement.experiment_id == experiment_id)
            .order_by(ExperimentElement.priority)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# SampleHolder
# ---------------------------------------------------------------------------

def get_sample_holder_by_name(
    experiment_id: str,
    name: str,
) -> Optional[SampleHolder]:
    """Return the SampleHolder with the given name for an experiment, or None."""
    with get_session() as session:
        stmt = (
            select(SampleHolder)
            .where(SampleHolder.experiment_id == experiment_id)
            .where(SampleHolder.name == name)
        )
        return session.exec(stmt).first()


def create_sample_holder(
    experiment_id: str,
    name: str,
    n_samples: int,
    holder_type: str = "flat",
    beamtime_hours: float | None = None,
    stop_time: datetime | None = None,
) -> SampleHolder:
    """Create and persist a new SampleHolder.

    New holders are appended to the end of the queue — their
    `queue_order` is `max(existing) + 1`, so the first holder is
    always the active one on a fresh experiment.
    """
    with get_session() as session:
        existing = list(session.exec(
            select(SampleHolder).where(SampleHolder.experiment_id == experiment_id)
        ))
        max_order = max((h.queue_order for h in existing), default=-1)
        holder = SampleHolder(
            experiment_id=experiment_id,
            name=name,
            n_samples=n_samples,
            holder_type=holder_type,
            beamtime_hours=beamtime_hours,
            stop_time=stop_time,
            queue_order=max_order + 1,
        )
        session.add(holder)
        session.commit()
        session.refresh(holder)
    return holder


def list_sample_holders(experiment_id: str) -> list[SampleHolder]:
    """Return holders for this experiment ordered by queue_order (then created_at)."""
    with get_session() as session:
        stmt = (
            select(SampleHolder)
            .where(SampleHolder.experiment_id == experiment_id)
            .order_by(SampleHolder.queue_order, SampleHolder.created_at)  # type: ignore[arg-type]
        )
        return list(session.exec(stmt).all())


def update_sample_holder(
    holder_id: str,
    *,
    name: Optional[str] = None,
    holder_type: Optional[str] = None,
    status: Optional[str] = None,
    beamtime_hours: float | None = _SENTINEL,
    stop_time: datetime | None = _SENTINEL,
    notes: Optional[str] = None,
) -> Optional[SampleHolder]:
    with get_session() as session:
        h = session.get(SampleHolder, holder_id)
        if h is None:
            return None
        if name is not None:
            h.name = name
        if holder_type is not None:
            h.holder_type = holder_type
        if status is not None:
            if h.started_at is None and status != "configured":
                h.started_at = datetime.now()
            if status == "done" and h.completed_at is None:
                h.completed_at = datetime.now()
            h.status = status
        if beamtime_hours is not _SENTINEL:
            h.beamtime_hours = beamtime_hours
        if stop_time is not _SENTINEL:
            h.stop_time = stop_time
        if notes is not None:
            h.notes = notes
        h.updated_at = datetime.now()
        session.add(h)
        session.commit()
        session.refresh(h)
    return h


def delete_sample_holder(holder_id: str) -> bool:
    """Delete a holder and every sample position inside it."""
    with get_session() as session:
        h = session.get(SampleHolder, holder_id)
        if h is None:
            return False
        for sp in session.exec(
            select(SamplePosition).where(SamplePosition.sample_holder_id == holder_id)
        ).all():
            session.delete(sp)
        session.delete(h)
        session.commit()
    return True


def reorder_sample_holders(experiment_id: str, holder_ids_in_order: list[str]) -> None:
    """Rewrite queue_order for a specific sequence. Unlisted holders are pushed to the bottom."""
    with get_session() as session:
        existing = list(session.exec(
            select(SampleHolder).where(SampleHolder.experiment_id == experiment_id)
        ))
        by_id = {h.id: h for h in existing}
        seen: set[str] = set()
        order_i = 0
        for hid in holder_ids_in_order:
            h = by_id.get(hid)
            if h is None:
                continue
            h.queue_order = order_i
            order_i += 1
            seen.add(hid)
            session.add(h)
        # Anything not explicitly listed goes to the end, preserving relative order.
        leftovers = [h for h in existing if h.id not in seen]
        leftovers.sort(key=lambda h: (h.queue_order, h.created_at))
        for h in leftovers:
            h.queue_order = order_i
            order_i += 1
            session.add(h)
        session.commit()


# ---------------------------------------------------------------------------
# PhaseRun
# ---------------------------------------------------------------------------

def create_phase_run(
    experiment_id: str,
    phase: str,
    spec_datafile: Optional[str] = None,
    element_id: Optional[str] = None,
) -> PhaseRun:
    """Create a new PhaseRun (status=running)."""
    run = PhaseRun(
        experiment_id=experiment_id,
        phase=phase,
        spec_datafile=spec_datafile,
        element_id=element_id,
    )
    with get_session() as session:
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


def complete_phase_run(
    phase_run_id: str,
    status: str = "completed",
    last_scan: Optional[int] = None,
    summary_image_path: Optional[str] = None,
    anomaly_flags: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[PhaseRun]:
    """Mark a PhaseRun as completed (or failed/aborted)."""
    with get_session() as session:
        run = session.get(PhaseRun, phase_run_id)
        if run is None:
            return None
        run.status = status
        run.completed_at = datetime.now()
        if last_scan is not None:
            run.last_scan = last_scan
        if summary_image_path is not None:
            run.summary_image_path = summary_image_path
        if anomaly_flags is not None:
            run.anomaly_flags = anomaly_flags
        if notes is not None:
            run.notes = notes
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


def get_phase_run(phase_run_id: str) -> Optional[PhaseRun]:
    """Fetch a PhaseRun by ID."""
    with get_session() as session:
        return session.get(PhaseRun, phase_run_id)


def get_phase_runs_for_experiment(
    experiment_id: str,
    phase: Optional[str] = None,
) -> list[PhaseRun]:
    """Return phase runs for an experiment, optionally filtered by phase."""
    with get_session() as session:
        stmt = select(PhaseRun).where(PhaseRun.experiment_id == experiment_id)
        if phase is not None:
            stmt = stmt.where(PhaseRun.phase == phase)
        stmt = stmt.order_by(PhaseRun.started_at)  # type: ignore[union-attr]
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# ScanRecord
# ---------------------------------------------------------------------------

def create_scan_record(
    phase_run_id: str,
    scan_number: int,
    motor_name: str,
    scan_type: str,
    command: str,
    result_position: Optional[float] = None,
    peak_intensity: Optional[float] = None,
    fwhm: Optional[float] = None,
    centroid: Optional[float] = None,
    anomaly: bool = False,
    anomaly_reason: Optional[str] = None,
    fit_result: Optional[str] = None,
    decision_action: Optional[str] = None,
    decision_command: Optional[str] = None,
    decision_confidence: Optional[float] = None,
    llm_consulted: bool = False,
    llm_log_id: Optional[str] = None,
    iteration: int = 1,
) -> ScanRecord:
    """Create and persist a new ScanRecord."""
    record = ScanRecord(
        phase_run_id=phase_run_id,
        scan_number=scan_number,
        motor_name=motor_name,
        scan_type=scan_type,
        command=command,
        result_position=result_position,
        peak_intensity=peak_intensity,
        fwhm=fwhm,
        centroid=centroid,
        anomaly=anomaly,
        anomaly_reason=anomaly_reason,
        fit_result=fit_result,
        decision_action=decision_action,
        decision_command=decision_command,
        decision_confidence=decision_confidence,
        llm_consulted=llm_consulted,
        llm_log_id=llm_log_id,
        iteration=iteration,
    )
    with get_session() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


def get_scans_for_phase_run(phase_run_id: str) -> list[ScanRecord]:
    """Return all scans for a phase run, ordered by scan number."""
    with get_session() as session:
        stmt = (
            select(ScanRecord)
            .where(ScanRecord.phase_run_id == phase_run_id)
            .order_by(ScanRecord.scan_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


def get_llm_consulted_scans(phase_run_id: str) -> list[ScanRecord]:
    """Return scans where the LLM was consulted."""
    with get_session() as session:
        stmt = (
            select(ScanRecord)
            .where(ScanRecord.phase_run_id == phase_run_id)
            .where(ScanRecord.llm_consulted == True)  # noqa: E712
            .order_by(ScanRecord.scan_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# SamplePosition
# ---------------------------------------------------------------------------

def create_sample_position(
    experiment_id: str,
    sample_holder_id: str,
    sample_number: int,
    sample_name: str,
    element_symbol: str,
    sx_lo: float = 0.0,
    sx_hi: float = 0.0,
    sy_lo: float = 0.0,
    sy_hi: float = 0.0,
    sz_lo: float = 0.0,
    sz_hi: float = 0.0,
    sx_del: float = 0.0,
    sy_del: float = 0.0,
    sz_del: float = 0.0,
    emiss_energy_eV: Optional[float] = None,
    total_spots: int = 1,
    enabled: bool = True,
    do_xas: bool = True,
    xas_reps: int = 0,
    xas_time: float = 0.5,
    xas_filter: int = 0,
    xas_filter_suggested: int = 0,
    xas_emiss_override: Optional[float] = None,
    do_rixs: bool = False,
    rixs_time: float = 1.0,
    rixs_start: Optional[float] = None,
    rixs_end: Optional[float] = None,
    rixs_step: float = -0.2,
    rixs_filter: int = 0,
    i0_gain: Optional[str] = None,
    i0_offset: Optional[str] = None,
    i1_gain: Optional[str] = None,
    min_scans: Optional[int] = None,
) -> SamplePosition:
    """Create and persist a new SamplePosition."""
    pos = SamplePosition(
        experiment_id=experiment_id,
        sample_holder_id=sample_holder_id,
        sample_number=sample_number,
        sample_name=sample_name,
        element_symbol=element_symbol,
        sx_lo=sx_lo,
        sx_hi=sx_hi,
        sy_lo=sy_lo,
        sy_hi=sy_hi,
        sz_lo=sz_lo,
        sz_hi=sz_hi,
        sx_del=sx_del,
        sy_del=sy_del,
        sz_del=sz_del,
        emiss_energy_eV=emiss_energy_eV,
        total_spots=total_spots,
        enabled=enabled,
        do_xas=do_xas,
        xas_reps=xas_reps,
        xas_time=xas_time,
        xas_filter=xas_filter,
        xas_filter_suggested=xas_filter_suggested,
        xas_emiss_override=xas_emiss_override,
        do_rixs=do_rixs,
        rixs_time=rixs_time,
        rixs_start=rixs_start,
        rixs_end=rixs_end,
        rixs_step=rixs_step,
        rixs_filter=rixs_filter,
        i0_gain=i0_gain,
        i0_offset=i0_offset,
        i1_gain=i1_gain,
        min_scans=min_scans,
    )
    with get_session() as session:
        session.add(pos)
        session.commit()
        session.refresh(pos)
    return pos


def update_sample_position(sample_id: str, **fields) -> Optional[SamplePosition]:
    """Update only the fields passed; others are left alone.

    Used by the sample_holders UI upsert path so editing one field doesn't
    clobber agent-populated columns (alignment bounds, gains, survey data).
    """
    with get_session() as session:
        sp = session.get(SamplePosition, sample_id)
        if sp is None:
            return None
        for k, v in fields.items():
            if v is _SENTINEL:
                continue
            setattr(sp, k, v)
        session.add(sp)
        session.commit()
        session.refresh(sp)
    return sp


def delete_sample_position(sample_id: str) -> bool:
    """Delete a single SamplePosition by id. Returns True if a row was removed."""
    with get_session() as session:
        sp = session.get(SamplePosition, sample_id)
        if sp is None:
            return False
        session.delete(sp)
        session.commit()
    return True


def get_samples_for_holder(sample_holder_id: str) -> list[SamplePosition]:
    """Return all samples for a holder, ordered by sample number."""
    with get_session() as session:
        stmt = (
            select(SamplePosition)
            .where(SamplePosition.sample_holder_id == sample_holder_id)
            .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


def get_samples_for_experiment(experiment_id: str) -> list[SamplePosition]:
    """Return all samples across all holders for an experiment."""
    with get_session() as session:
        stmt = (
            select(SamplePosition)
            .where(SamplePosition.experiment_id == experiment_id)
            .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


def submit_sample_alignment_results(
    results: list[dict],
) -> list[str]:
    """Persist Sample-Alignment agent outputs to SamplePosition rows.

    Each entry in *results* must include ``sample_id``.  Accepted
    optional keys (all floats):

    * ``sx_lo``, ``sx_hi``, ``sy_lo``, ``sy_hi``, ``sz_lo``, ``sz_hi``
      — stage boundaries measured via d2scan / dscan.
    * ``emiss_energy_eV`` — measured optimal emission energy.
    * ``suggested_filter`` — starting filter count for this sample.
    * ``counts_per_sec`` — measured count rate at the alignment energy.

    Returns the list of sample_ids actually updated (unknown ids are
    skipped silently).
    """
    updated: list[str] = []
    if not results:
        return updated
    _float_keys = (
        "sx_lo", "sx_hi", "sy_lo", "sy_hi", "sz_lo", "sz_hi",
        "emiss_energy_eV",
    )
    with get_session() as session:
        for entry in results:
            sid = entry.get("sample_id")
            if not sid:
                continue
            sp = session.get(SamplePosition, sid)
            if sp is None:
                continue
            for key in _float_keys:
                val = entry.get(key)
                if val is not None:
                    setattr(sp, key, float(val))
            sf = entry.get("suggested_filter")
            if sf is not None:
                sp.xas_filter = int(sf)
            cps = entry.get("counts_per_sec")
            if cps is not None:
                sp.survey_counts_per_sec = float(cps)
            session.add(sp)
            updated.append(sid)
        session.commit()
    return updated


def submit_survey_results(
    results: list[dict],
) -> list[str]:
    """Persist Sample-Surveyor outputs to SamplePosition rows.

    Each entry in `results` must include `sample_id`, `filter_count`
    (written to `xas_filter`), and `counts_per_sec` (written to
    `survey_counts_per_sec`). Optional keys `survey_energy_ev` and
    `notes` are stored as-is. `survey_completed_at` is set to the time
    of this call. Returns the list of sample_ids actually updated
    (skipping unknown sample_ids).
    """
    updated: list[str] = []
    if not results:
        return updated
    with get_session() as session:
        for entry in results:
            sid = entry.get("sample_id")
            if not sid:
                continue
            sp = session.get(SamplePosition, sid)
            if sp is None:
                continue
            filter_count = entry.get("filter_count")
            cps = entry.get("counts_per_sec")
            if filter_count is not None:
                sp.xas_filter = int(filter_count)
            if cps is not None:
                sp.survey_counts_per_sec = float(cps)
            if entry.get("survey_energy_ev") is not None:
                sp.survey_energy_ev = float(entry["survey_energy_ev"])
            if entry.get("notes") is not None:
                sp.survey_notes = str(entry["notes"])
            sp.survey_completed_at = datetime.now()
            session.add(sp)
            updated.append(sid)
        session.commit()
    return updated


# ---------------------------------------------------------------------------
# CollectionScan
# ---------------------------------------------------------------------------

def create_collection_scan(
    experiment_id: str,
    sample_id: str,
    technique: str,
    scan_number: int,
    spec_datafile: str,
    filter_setting: int = 0,
    count_time: float = 1.0,
    spot_index: Optional[int] = None,
) -> CollectionScan:
    """Log a data-collection scan."""
    scan = CollectionScan(
        experiment_id=experiment_id,
        sample_id=sample_id,
        technique=technique,
        scan_number=scan_number,
        spec_datafile=spec_datafile,
        filter_setting=filter_setting,
        count_time=count_time,
        spot_index=spot_index,
    )
    with get_session() as session:
        session.add(scan)
        _commit_with_retry(session)
        session.refresh(scan)
    return scan


def set_experiment_end_time(
    experiment_id: str, end_time: datetime,
) -> Optional[Experiment]:
    """Set Experiment.end_time. Source of truth for remaining-beamtime math."""
    with get_session() as session:
        row = session.get(Experiment, experiment_id)
        if row is None:
            return None
        row.end_time = end_time
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def get_collection_scans_for_sample(sample_id: str) -> list[CollectionScan]:
    """Return all collection scans for a sample."""
    with get_session() as session:
        stmt = (
            select(CollectionScan)
            .where(CollectionScan.sample_id == sample_id)
            .order_by(CollectionScan.scan_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


def get_collection_scans_since(
    experiment_id: str,
    since: datetime,
) -> list[CollectionScan]:
    """Return CollectionScan rows for an experiment with `timestamp > since`.

    Used by `get_scans_since_last_plan_update` to feed the Planner the
    list of scans the Data Collection agent has accumulated since the
    plan was last revised.
    """
    with get_session() as session:
        stmt = (
            select(CollectionScan)
            .where(CollectionScan.experiment_id == experiment_id)
            .where(CollectionScan.timestamp > since)  # type: ignore[arg-type]
            .order_by(CollectionScan.scan_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


def get_collection_scans_for_experiment(experiment_id: str) -> list[CollectionScan]:
    """Return every collection scan for an experiment, ordered by scan number."""
    with get_session() as session:
        stmt = (
            select(CollectionScan)
            .where(CollectionScan.experiment_id == experiment_id)
            .order_by(CollectionScan.scan_number)  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# LLMLog
# ---------------------------------------------------------------------------

def create_llm_log(
    phase: str,
    prompt_summary: str,
    full_prompt: str,
    response: str,
    experiment_id: Optional[str] = None,
    phase_run_id: Optional[str] = None,
    model: str = "claude-opus-4-6",
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    image_path: Optional[str] = None,
) -> LLMLog:
    """Log an LLM call with full prompt/response and timing."""
    log = LLMLog(
        experiment_id=experiment_id,
        phase=phase,
        phase_run_id=phase_run_id,
        prompt_summary=prompt_summary[:500],
        full_prompt=full_prompt,
        response=response,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        image_path=image_path,
    )
    with get_session() as session:
        session.add(log)
        session.commit()
        session.refresh(log)
    return log


def get_llm_logs_for_experiment(experiment_id: str) -> list[LLMLog]:
    """Return all LLM logs for an experiment, newest first."""
    with get_session() as session:
        stmt = (
            select(LLMLog)
            .where(LLMLog.experiment_id == experiment_id)
            .order_by(LLMLog.timestamp.desc())  # type: ignore[union-attr]
        )
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# MotorPosition
# ---------------------------------------------------------------------------

def create_motor_position(
    experiment_id: str,
    scan_filename: str,
    scan_number: int,
    motor_name: str,
    position: float,
) -> MotorPosition:
    """Record a motor position snapshot."""
    mp = MotorPosition(
        experiment_id=experiment_id,
        scan_filename=scan_filename,
        scan_number=scan_number,
        motor_name=motor_name,
        position=position,
    )
    with get_session() as session:
        session.add(mp)
        session.commit()
        session.refresh(mp)
    return mp


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

def create_image(
    experiment_id: str,
    image_type: str,
    file_path: str,
    file_size: int,
    sha256_hash: str,
) -> Image:
    """Register an image file in the database."""
    img = Image(
        experiment_id=experiment_id,
        image_type=image_type,
        file_path=file_path,
        file_size=file_size,
        sha256_hash=sha256_hash,
    )
    with get_session() as session:
        session.add(img)
        session.commit()
        session.refresh(img)
    return img
