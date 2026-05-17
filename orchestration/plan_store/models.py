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
    experimenter: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    mono_crystal: str = Field(default="A")  # A (Si111) or B (Si311)
    beam_size_h: str = Field(default="big")      # horizontal: "big" or "focused"
    beam_size_v: str = Field(default="big")      # vertical: "big" or "focused"
    mirrors_out: bool = Field(default=False)      # mirrors removed (energy above cutoff)
    sample_env: Optional[str] = None  # cryostat, ambient, operando, liquid_jet
    status: str = Field(default="created", index=True)  # created/aligning/collecting/done
    data_path: Optional[str] = None  # e.g. /data/fifteen/{name}
    # Operator-confirmed flag: spectrometer was aligned for this experiment's
    # crystals. Gates Sample Alignment / Data Collection tiles in the
    # dashboard. Cleared by the Reset button on the Spectrometer tile.
    spectrometer_aligned: bool = Field(default=False)
    # Measured beam-size FWHM in micrometres. Populated by the wbeamsize
    # parser whenever a fresh measurement comes back; the dashboard's
    # Beam field switches from the configured big/focused mode pair to
    # these values once they're populated.
    beam_h_fwhm_um: Optional[float] = None
    beam_v_fwhm_um: Optional[float] = None
    # Energy-calibration foil. `calibration_foil_element` is the element
    # symbol of the reference foil (e.g. "Au", "Cu", "Fe") used during
    # the calibration step. `calibration_foil_detector` is which diode
    # the foil sits in front of — defaults to "I2" (the B-stage transmission
    # diode). I1 is also accepted; per the user, I1 is more reliable but
    # is easily blocked, so I2 is the safer default.
    calibration_foil_element: Optional[str] = None
    calibration_foil_detector: str = Field(default="I2")
    # End of beamtime as an absolute timestamp. The planner / agents read
    # this to compute remaining hours. NULL means "not set yet"; the
    # operator sets it once via `db set-experiment-end-time`.
    end_time: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Experiment Element
# ---------------------------------------------------------------------------

class ExperimentElement(SQLModel, table=True):
    """Element + edge + analyzer configuration for an experiment."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    element_symbol: str  # e.g. "Zn", "As"
    edge: str  # K, L1, L2, L3
    measurement_mode: str = Field(default="XES")  # "XES" or "TFY"
    emission_line: Optional[str] = None  # e.g. "Ka1" — None for TFY
    incident_energy_eV: float
    emission_energy_eV: float
    crystal_type: int  # 0 = Si, 1 = Ge
    crystal_hkl: str  # e.g. "6 4 2"
    row_radius: int
    n_crystals: int  # 1-7
    # Canonical counter mnemonic ("vortDT", "vortDT2", "vortDT3", "vortDT4").
    # The legacy `vortex_channel` int below is retained on the row for old
    # data only; new code derives it via vortex_channel_for_counter() when
    # the SPEC macro layer needs an int.
    vortex_counter: Optional[str] = None
    vortex_channel: int  # legacy (1, 3, 5, 7) — derived from vortex_counter
    priority: int = 0


# Mnemonic → SPEC vortex_roi channel int. Reserved-even-ROI convention:
# vortDT=ROI1, vortDT2=ROI3 (existing two-counter macro). vortDT3=ROI5,
# vortDT4=ROI7 follow the same pattern; select_element.mac will need a
# matching SPEC-side update before vortDT3/vortDT4 actually configure ROIs.
VORTEX_COUNTER_TO_CHANNEL: dict[str, int] = {
    "vortDT": 1, "vortDT2": 3, "vortDT3": 5, "vortDT4": 7,
}
VORTEX_COUNTERS: tuple[str, ...] = tuple(VORTEX_COUNTER_TO_CHANNEL.keys())


def vortex_channel_for_counter(counter: str) -> int:
    return VORTEX_COUNTER_TO_CHANNEL.get(counter, 1)


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
    # Ordered queue position within an experiment. The lowest-numbered
    # holder that isn't "done" is the active one; new holders go to the
    # bottom on creation (see create_sample_holder).
    queue_order: int = Field(default=0, index=True)
    beamtime_hours: Optional[float] = None
    # Absolute time by which collection on this holder should ideally
    # wrap up.  Planning aid only — we never auto-stop.
    stop_time: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None


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
    xas_reps: int = 0
    xas_time: float = 0.5
    # xas_filter is the *measured* filter the Sample Surveyor agent landed on
    # via damage assessment. The operator's starting guess lives in
    # xas_filter_suggested; the surveyor reads that and writes here.
    xas_filter: int = 0
    xas_filter_suggested: int = 0
    xas_emiss_override: Optional[float] = None  # Override element emission
    # RIXS parameters
    do_rixs: bool = False
    rixs_time: float = 1.0
    rixs_start: Optional[float] = None  # Emission start (eV)
    rixs_end: Optional[float] = None    # Emission end (eV)
    rixs_step: float = -0.2             # Negative (scanning downward)
    rixs_filter: int = 0
    # Per-sample gain overrides (None = use crystal default from defaults.yaml)
    i0_gain: Optional[str] = None
    i0_offset: Optional[str] = None
    i1_gain: Optional[str] = None
    # Sample-survey results — populated by the Sample Surveyor agent at the
    # end of its run via `upload_sample_survey_results`. The survey reads
    # xas_filter_suggested as its starting point, refines via damage
    # assessment, and writes the result into xas_filter for downstream Data
    # Collection use. `survey_energy_ev` and `survey_notes` are informational.
    # `survey_completed_at` flags the row as having been surveyed.
    survey_counts_per_sec: Optional[float] = None
    survey_energy_ev: Optional[float] = None
    survey_completed_at: Optional[datetime] = None
    survey_notes: Optional[str] = None
    # Operator-set minimum number of scans/reps that MUST be collected
    # for this sample before the planner can mark it done or move on.
    # None means no minimum — convergence alone decides.
    min_scans: Optional[int] = None


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
    # Spot index within the sample (0-based). The planner can prescribe
    # per-spot rep distributions (e.g. "8 reps across 4 spots, 2 each");
    # the data collector records which spot each scan was taken on so
    # the comprehensive collection plan can return per-spot remaining
    # rep counts. NULL means the scan wasn't tagged with a spot
    # (legacy rows or single-spot samples).
    spot_index: Optional[int] = None
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
    model: str = "claude-opus-4-6"
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
    version: int = Field(default=0)
    notes: Optional[str] = None


class StaffGuidance(SQLModel, table=True):
    """One steering message — staff guidance dispatched to control agents.

    The orchestrator state machine fills these fields as a steering message
    moves through its lifecycle:

      1. Slack/UI ingest writes (source, author, text, slack_channel, slack_thread_ts, is_stop)
      2. Orchestrator sees a new row, sets orchestrator_ack_at + ack_comment.
         Either it spawns a control agent (active_agent_run_id) or defers to the
         active agent already in flight.
      3. The active agent acks via `beamtimehero steering ack <id>` (active_agent_ack_at)
         and either responds (result + completed_at) or defers (ack_comment + completed_at NULL).
      4. Orchestrator notices completed_at, posts result back to slack_thread_ts.

    `consumed` / `consumed_at` are legacy: kept on the row for migration safety but
    no longer driven by the loop.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    source: str  # "slack-steering" | "slack-chat" | "slack-dm" | "web" | "operator-cli"
    author: str
    text: str
    consumed: bool = Field(default=False, index=True)  # legacy
    consumed_at: Optional[datetime] = None  # legacy
    # New steering state-machine columns.
    orchestrator_ack_at: Optional[datetime] = Field(default=None, index=True)
    ack_comment: Optional[str] = None
    active_agent_run_id: Optional[str] = Field(default=None, foreign_key="agentrun.id", index=True)
    active_agent_ack_at: Optional[datetime] = None
    completed_at: Optional[datetime] = Field(default=None, index=True)
    result: Optional[str] = None
    # Slack provenance (so the orchestrator can post a thread reply on completion).
    slack_channel: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    # STOP fast-path: kill agents and trigger abort_current_scan immediately.
    is_stop: bool = Field(default=False, index=True)
    # Set when the orchestrator has posted a completion reply back to Slack.
    # Used to dedupe Slack posts across ticks and across server restarts.
    slack_replied_at: Optional[datetime] = Field(default=None, index=True)
    # When an active agent defers a steering row out of scope, it names
    # the agent type that should pick it up (planner / sample-aligner /
    # beamline-aligner / sample-surveyor / collection). The orchestrator
    # tick re-dispatches deferred rows to this agent type with a
    # focused-task seed prompt.
    target_agent_type: Optional[str] = Field(default=None, index=True)


# ---------------------------------------------------------------------------
# Agent runs (control / chat / dm subprocess registry)
# ---------------------------------------------------------------------------

class AgentRun(SQLModel, table=True):
    """One spawned Claude agent subprocess.

    Used for every spawned Claude agent — phase-tile agents
    (`agent_type` matches the phase slug: beamline_alignment /
    sample_alignment / sample_survey / collection / planner) plus chat
    agents. `list_active(agent_type=<slug>)` is the gate the
    orchestrator tick uses to decide whether a phase agent is in
    flight.

    PID/PGID are stored so the FastAPI lifespan can sweep orphans on
    startup (`ps -p <pid>`) and clean-kill on shutdown via `killpg(pgid)`.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    agent_type: str = Field(index=True)  # phase slug | 'chat'
    task_text: str  # human-readable: why this agent was spawned
    spawned_by: str  # 'orchestrator' | 'ui:<button>' | 'slack-thread:<key>' | 'steering:<id>'
    pid: Optional[int] = None
    pgid: Optional[int] = None
    started_at: datetime = Field(default_factory=datetime.now, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    killed: bool = Field(default=False)
    kill_reason: Optional[str] = None
    result: Optional[str] = None
    claude_session_id: Optional[str] = None
    working_dir: Optional[str] = None
    script_path: Optional[str] = None  # which .sh launched this agent


# ---------------------------------------------------------------------------
# Chat sessions (per Slack thread / DM thread / UI session)
# ---------------------------------------------------------------------------

class ChatSession(SQLModel, table=True):
    """Per-thread persistent chat with a chat-class agent.

    `thread_key` namespaces every distinct conversation:
      * 'slack:<channel>:<root_ts>'  — Slack chat-channel thread
      * 'dm:<channel>:<root_ts>'     — Slack DM thread
      * 'ui:<ui_session_id>'         — UI chat-box session

    `claude_session_id` lets us `claude --resume <id>` so that a thread
    reactivated a week later picks up the same conversation. There is no
    timeout — sessions persist until archived (UI clear button).
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    thread_key: str = Field(index=True, unique=True)
    source: str = Field(index=True)  # 'slack_chat' | 'slack_dm' | 'ui'
    claude_session_id: Optional[str] = None
    working_dir: str  # data/chat_sessions/<safe_thread_key>/
    active_agent_run_id: Optional[str] = Field(default=None, foreign_key="agentrun.id")
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity_at: datetime = Field(default_factory=datetime.now, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    # Slack/UI provenance for replying back.
    slack_channel: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    ui_session_id: Optional[str] = None


class ChatMessage(SQLModel, table=True):
    """One message in a chat session — inbound from user or outbound from agent.

    Logged regardless of which surface (UI / Slack / DM) the message came
    from so the chat history is complete in one place.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    session_id: str = Field(foreign_key="chatsession.id", index=True)
    direction: str  # 'inbound' | 'outbound'
    source: str  # 'ui' | 'slack' | 'dm' | 'agent'
    author: str
    text: str
    slack_channel: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now, index=True)


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
    action: str = Field(index=True)  # add_sample | remove_sample | reorder | skip | update_params | set_end_time | reprioritize
    target_id: Optional[str] = None  # sample_id, etc.
    payload_json: str = "{}"
    reason: Optional[str] = None


class InterventionRequest(SQLModel, table=True):
    """An agent-triggered pause waiting for a human to unblock it."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, foreign_key="experiment.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    resolved_at: Optional[datetime] = None
    kind: str = Field(index=True)  # "crystal_install" | "sample_mount" | "foil_insert" | "gap_ownership" | "custom"
    detail: str
    status: str = Field(default="waiting", index=True)  # waiting | resolved | denied | timed_out
    resolver: Optional[str] = None
    resolver_note: Optional[str] = None
    slack_channel: Optional[str] = None
    slack_ts: Optional[str] = None
