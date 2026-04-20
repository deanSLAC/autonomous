"""Convenience client for programmatic access to the BL15-2 experiments database.

Provides a singleton engine, session helper, and CRUD functions for the
most common operations.  Designed for use by the FastAPI server, analysis
scripts, and interactive debugging.

Usage:
    from db.client import (
        create_experiment, get_experiment, get_active_experiment,
        create_phase_run, complete_phase_run, create_scan_record,
        create_sample_position, create_llm_log,
    )
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from db.models import (
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

# ---------------------------------------------------------------------------
# Engine / session management
# ---------------------------------------------------------------------------

_engine = None


def get_engine(db_path: str | None = None):
    """Return a singleton SQLAlchemy engine with WAL and busy_timeout set.

    Args:
        db_path: Override the default database location.  Only respected on
                 the first call (subsequent calls return the cached engine).
    """
    global _engine
    if _engine is not None:
        return _engine

    if db_path is None:
        db_path = os.environ.get(
            "BEAMLINE_DB_PATH",
            str(Path(__file__).resolve().parent / "experiments.db"),
        )

    db_url = f"sqlite:///{db_path}"
    _engine = create_engine(db_url, echo=False)

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    # Ensure all tables exist (safe to call repeatedly)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    SQLModel.metadata.create_all(_engine)

    return _engine


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
    config_yaml: Optional[str] = None,
    data_path: Optional[str] = None,
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
        config_yaml=config_yaml,
        data_path=data_path,
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
    vortex_channel: int = 1,
    priority: int = 0,
    measurement_mode: str = "XES",
    emission_line: Optional[str] = None,
) -> ExperimentElement:
    """Create and persist a new ExperimentElement."""
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
        vortex_channel=vortex_channel,
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
) -> SampleHolder:
    """Create and persist a new SampleHolder."""
    holder = SampleHolder(
        experiment_id=experiment_id,
        name=name,
        n_samples=n_samples,
        holder_type=holder_type,
    )
    with get_session() as session:
        session.add(holder)
        session.commit()
        session.refresh(holder)
    return holder


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
    xas_reps: int = 10,
    xas_time: float = 0.5,
    xas_filter: int = 0,
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
    )
    with get_session() as session:
        session.add(pos)
        session.commit()
        session.refresh(pos)
    return pos


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
    )
    with get_session() as session:
        session.add(scan)
        session.commit()
        session.refresh(scan)
    return scan


def get_collection_scans_for_sample(sample_id: str) -> list[CollectionScan]:
    """Return all collection scans for a sample."""
    with get_session() as session:
        stmt = (
            select(CollectionScan)
            .where(CollectionScan.sample_id == sample_id)
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
    model: str = "claude-4-5-sonnet",
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
