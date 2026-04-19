"""SQLModel table definitions for BL15-2 beamline automation database.

Tracks experiments, alignment phases, scan results, sample positions,
data collection, and LLM advisory conversations.
"""

from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
import uuid


def generate_id() -> str:
    """Generate a short unique ID (12-char hex)."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

class Experiment(SQLModel, table=True):
    """Top-level experiment record.  One per beamtime session."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    name: str = Field(index=True)
    beamline: str = Field(default="BL15-2")
    experimenter: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    mono_crystal: str = Field(default="A")  # A (Si111) or B (Si311)
    beam_size_h: str = Field(default="big")      # horizontal: "big" or "focused"
    beam_size_v: str = Field(default="big")      # vertical: "big" or "focused"
    mirrors_out: bool = Field(default=False)      # mirrors removed (energy above cutoff)
    sample_env: Optional[str] = None  # cryostat, ambient, operando
    status: str = Field(default="created", index=True)  # created/aligning/collecting/done
    config_yaml: Optional[str] = None  # Full YAML text of experiment config
    data_path: Optional[str] = None  # e.g. /data/fifteen/{name}


# ---------------------------------------------------------------------------
# Experiment Element
# ---------------------------------------------------------------------------

class ExperimentElement(SQLModel, table=True):
    """Element + edge + analyzer configuration for an experiment."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    element_symbol: str  # e.g. "Zn", "As"
    edge: str  # K, L1, L2, L3
    incident_energy_eV: float
    emission_energy_eV: float
    crystal_type: int  # 0 = Si, 1 = Ge
    crystal_hkl: str  # e.g. "6 4 2"
    row_radius: int
    n_crystals: int  # 1-7
    vortex_channel: int  # 1 or 3
    priority: int = 0


# ---------------------------------------------------------------------------
# Sample Holder
# ---------------------------------------------------------------------------

class SampleHolder(SQLModel, table=True):
    """Groups samples into a named holder for a given experiment."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    name: str  # user-chosen, e.g. "sample_holder_1"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: str = Field(default="configured")  # configured/aligning/ready/collecting/done
    n_samples: int = 0
    holder_type: str = "flat"  # cryostat, flat, electrode


# ---------------------------------------------------------------------------
# Phase Run
# ---------------------------------------------------------------------------

class PhaseRun(SQLModel, table=True):
    """One execution of a major phase (alignment, collection, etc.)."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    phase: str = Field(index=True)  # bl_align, xes_align, sample_align, collection
    element_id: Optional[str] = Field(default=None, foreign_key="experimentelement.id")
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = Field(default="running")  # running/completed/failed/aborted
    spec_datafile: Optional[str] = None
    first_scan: Optional[int] = None
    last_scan: Optional[int] = None
    summary_image_path: Optional[str] = None
    anomaly_flags: Optional[str] = None  # JSON
    notes: Optional[str] = None  # LLM assessment


# ---------------------------------------------------------------------------
# Scan Record
# ---------------------------------------------------------------------------

class ScanRecord(SQLModel, table=True):
    """Individual scan within a phase run, with decision trail."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    phase_run_id: str = Field(foreign_key="phaserun.id", index=True)
    scan_number: int
    motor_name: str
    scan_type: str  # dscan, ascan, cscan
    command: str  # Full SPEC command
    result_position: Optional[float] = None
    peak_intensity: Optional[float] = None
    fwhm: Optional[float] = None
    centroid: Optional[float] = None
    anomaly: bool = False
    anomaly_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    # Fit output
    fit_result: Optional[str] = None  # JSON: full fitter output
    # Decision tracking
    decision_action: Optional[str] = None  # move, cen, rescan, etc.
    decision_command: Optional[str] = None  # Exact SPEC command returned
    decision_confidence: Optional[float] = None
    llm_consulted: bool = False
    llm_log_id: Optional[str] = None  # FK to LLMLog (soft reference)
    iteration: int = 1


# ---------------------------------------------------------------------------
# Sample Position
# ---------------------------------------------------------------------------

class SamplePosition(SQLModel, table=True):
    """Per-sample position and boundary data within a holder."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    sample_holder_id: str = Field(foreign_key="sampleholder.id", index=True)
    sample_number: int
    sample_name: str
    element_symbol: str
    # Stage boundaries
    sx_lo: float = 0.0
    sx_hi: float = 0.0
    sy_lo: float = 0.0
    sy_hi: float = 0.0
    sz_lo: float = 0.0
    sz_hi: float = 0.0
    # Step sizes
    sx_del: float = 0.0
    sy_del: float = 0.0
    sz_del: float = 0.0
    # Emission
    emiss_energy_eV: Optional[float] = None
    total_spots: int = 1
    enabled: bool = True
    # XAS parameters
    do_xas: bool = True
    xas_reps: int = 10
    xas_time: float = 0.5
    xas_filter: int = 0
    xas_emiss_override: Optional[float] = None  # Override element emission
    # RIXS parameters
    do_rixs: bool = False
    rixs_time: float = 1.0
    rixs_start: Optional[float] = None  # Emission start (eV)
    rixs_end: Optional[float] = None    # Emission end (eV)
    rixs_step: float = -0.2             # Negative (scanning downward)
    rixs_filter: int = 0


# ---------------------------------------------------------------------------
# Collection Scan
# ---------------------------------------------------------------------------

class CollectionScan(SQLModel, table=True):
    """One data-collection scan (XAS, HERFD, RIXS, VTC)."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    sample_id: str = Field(foreign_key="sampleposition.id", index=True)
    technique: str  # xas, herfd, rixs, vtc
    scan_number: int
    spec_datafile: str
    filter_setting: int = 0
    count_time: float = 1.0
    timestamp: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# LLM Log
# ---------------------------------------------------------------------------

class LLMLog(SQLModel, table=True):
    """Record of every LLM call: prompt, response, cost, timing."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    phase: str  # bl_align, xes_align, sample_align, collection
    phase_run_id: Optional[str] = None
    prompt_summary: str  # First 500 chars of prompt
    full_prompt: str
    response: str
    model: str = "claude-4-5-sonnet"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    image_path: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Motor Position
# ---------------------------------------------------------------------------

class MotorPosition(SQLModel, table=True):
    """Snapshot of a motor position for a specific scan."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    scan_filename: str
    scan_number: int
    motor_name: str
    position: float


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

class Image(SQLModel, table=True):
    """Image file metadata (report PNGs, sample photos, etc.)."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    image_type: str  # sample_holder, report, scan_plot, etc.
    file_path: str
    file_size: int
    sha256_hash: str


# ---------------------------------------------------------------------------
# Action Log (autonomy spec — every SPEC action is recorded BEFORE dispatch)
# ---------------------------------------------------------------------------

class ActionLog(SQLModel, table=True):
    """Durable record of every spec_cmd action call.

    Writer invariant: the row is INSERT'd before the command is injected to
    the SPEC screen session. Even if SPEC hangs, the row still exists.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    phase_run_id: Optional[str] = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    phase: str = Field(index=True)
    command: str = Field(index=True)
    args_json: str = "[]"
    spec_string_sent: str = ""
    justification: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_json: Optional[str] = None
    screen_output: Optional[str] = None
    scan_number: Optional[int] = None
    success: Optional[int] = None  # 1 ok, 0 err, None in progress
    error_message: Optional[str] = None
    agent: str = Field(default="llm")  # "llm" | "operator" | "system"


class QueryLog(SQLModel, table=True):
    """Non-mutating spec_cmd read calls — separate log so action_log stays clean."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    phase: str = Field(default="unknown")
    command: str = Field(index=True)
    args_json: str = "[]"
    result_json: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# Phase transition log (CAT-8)
# ---------------------------------------------------------------------------

class PhaseTransitionLog(SQLModel, table=True):
    """Compact high-level narrative of the run's phase progression."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    previous_phase: str
    new_phase: str
    justification: str
    allowed: bool
    preconditions_json: Optional[str] = None
    human_approved: Optional[bool] = None  # None unless Slack gated it
    reason: Optional[str] = None  # when allowed=False


# ---------------------------------------------------------------------------
# Experiment plan + steering
# ---------------------------------------------------------------------------

class ExperimentPlan(SQLModel, table=True):
    """Live plan maintained by the orchestrator / planner.

    One row per experiment. Updated continuously as the agent makes
    progress and absorbs staff guidance.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    beamtime_total_hours: float = 0.0
    beamtime_elapsed_hours: float = 0.0
    phase: str = Field(default="setup")
    plan_json: str = "{}"  # serialized plan (sample queue, goals, thresholds)
    notes: Optional[str] = None


class StaffGuidance(SQLModel, table=True):
    """A single piece of guidance from staff / user, consumed by the agent loop."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    source: str  # "slack" | "web" | "operator-cli"
    author: str
    text: str
    consumed: bool = Field(default=False, index=True)
    consumed_at: Optional[datetime] = None


class PlanEdit(SQLModel, table=True):
    """Audit log of every edit made to the live experiment plan.

    Every add / remove / reorder / skip / parameter change / budget bump
    writes one row. Used for the plan-history view described in the
    slides ("Every edit is attributed").
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    author: str  # "web-user" | "slack:<name>" | "agent" | "operator"
    action: str = Field(index=True)  # add_sample | remove_sample | reorder | skip | update_params | extend_budget | reprioritize
    target_id: Optional[str] = None  # sample_id, etc.
    payload_json: str = "{}"
    reason: Optional[str] = None


class InterventionRequest(SQLModel, table=True):
    """An agent-triggered pause waiting for a human to unblock it."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    resolved_at: Optional[datetime] = None
    kind: str = Field(index=True)  # "crystal_install" | "sample_mount" | "foil_insert" | "backward_transition" | "gap_ownership" | "custom"
    detail: str
    status: str = Field(default="waiting", index=True)  # waiting | resolved | denied | timed_out
    resolver: Optional[str] = None
    resolver_note: Optional[str] = None
    slack_channel: Optional[str] = None
    slack_ts: Optional[str] = None
