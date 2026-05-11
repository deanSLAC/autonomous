# Data Model & Cross-Phase Data Flow

How data moves through the autonomous beamline control system — from
experiment configuration through phase handoffs to collection convergence.

## Databases

Two SQLite files, both WAL mode + 5 s busy_timeout:

| File | Package | Tables | Scope |
|---|---|---|---|
| `data/orchestration.db` | `orchestration/plan_store` | 18 | Experiment config, plan, agents, steering, chat, audit |
| `data/beamline_tools.db` | `beamline_tools/action_log` | 3 | SPEC command log, query log, CLI invocation log |

Cross-DB references are soft (indexed strings, no FK constraint):
`ActionLog.experiment_id` and `ActionLog.phase_run_id` point into
`orchestration.db` by string ID.

## Table map

### orchestration.db

```
Experiment  ──1:N──  ExperimentElement
     │
     ├──1:N──  SampleHolder  ──1:N──  SamplePosition
     │
     ├──1:1──  ExperimentPlan   (plan_json blob + version)
     │
     ├──1:N──  PhaseRun  ──1:N──  ScanRecord
     │                              └── MotorPosition (per-scan snapshots)
     │
     ├──1:N──  CollectionScan   (one per XAS/HERFD/RIXS/VTC scan)
     │
     ├──1:N──  StaffGuidance    (steering lifecycle)
     │
     ├──1:N──  InterventionRequest
     │
     ├──1:N──  AgentRun         (every spawned Claude subprocess)
     │
     ├──1:N──  ChatSession  ──1:N──  ChatMessage
     │
     ├──1:N──  PhaseTransitionLog
     │
     ├──1:N──  PlanEdit         (audit trail of every plan mutation)
     │
     ├──1:N──  LLMLog           (prompt/response/cost per LLM call)
     │
     └──1:N──  Image            (report PNGs, sample photos)
```

### beamline_tools.db

```
ActionLog          (one row per spec_cmd write — INSERT before dispatch)
QueryLog           (non-mutating spec_cmd reads)
CliInvocationLog   (every `beamtimehero` invocation, regardless of tree)
```

## The plan_json blob

`ExperimentPlan.plan_json` is the central coordination structure. Every
agent reads it (via `beamtimehero db get-plan`); the planner and data
collector write it (via `beamtimehero db update-plan` and the planner's
mutation functions). It is versioned for optimistic locking.

### Top-level shape

```json
{
  "experiment": {
    "id": "...", "name": "...", "experimenter": "...",
    "mono_crystal": "A", "beam_size_h": "big", "beam_size_v": "big",
    "sample_env": "ambient",
    "calibration_foil_element": "Au", "calibration_foil_detector": "I2"
  },
  "elements": [
    {
      "symbol": "Zn", "edge": "K",
      "incident_energy_eV": 9659.0, "emission_energy_eV": 8637.0,
      "n_crystals": 5, "vortex_counter": "vortDT",
      "crystal_hkl": "6 4 2", "row_radius": 1000
    }
  ],
  "holders": [
    {"id": "...", "name": "sample_holder_1", "type": "flat",
     "beamtime_hours": 4.0}
  ],
  "sample_queue": [
    {
      "sample_id": "abc123",
      "sample_name": "sample_1",
      "element_symbol": "Zn",
      "holder_id": "def456",
      "modes": [
        {"mode": "xas", "reps": 8, "count_time_s": 0.5,
         "filter_bitmask": 2, "emiss_override_ev": null,
         "n_spots": 4, "reps_per_spot": [2, 2, 2, 2]}
      ],
      "status": "in_progress",
      "snr_estimate": 6.2,
      "efficiency_verdict": "marginal",
      "convergence_stats": { "...see below..." },
      "reps_completed": 5,
      "notes": [{"ts": "...", "text": "..."}]
    }
  ],
  "thresholds": {
    "snr_target": 8.0,
    "min_reps_per_sample": 3,
    "max_drift_ev": null
  },
  "holder_budgets": {
    "def456": {"count_time_s": 0.5, "reps": 6, "mode": "xas"},
    "_default": {"count_time_s": 0.5, "reps": 4}
  },
  "budget": {
    "beamtime_total_hours": 12.0,
    "started_at": "2026-05-11T08:00:00"
  },
  "updated_at": "2026-05-11T14:32:01"
}
```

### Sample status lifecycle

```
queued → in_progress → done
                     → skipped   (operator or planner decision)
                     → failed    (unrecoverable alignment/damage)
```

When all samples reach a terminal status (`done`/`skipped`/`failed`) with
beamtime remaining, the convergence fallback reopens every non-skipped,
non-failed sample with reps weighted by count rate x (1 + SNR slope),
floor of 2.

### convergence_stats (per sample)

Written by the planner after each between-scan assessment:

```json
{
  "reps_done": 5,
  "snr": 6.2,
  "snr_slope": 0.4,
  "chi_sq": 1.02,
  "edge_step": 0.85,
  "verdict": "needs_more",
  "assessed_at": "2026-05-11T14:30:00"
}
```

## Phase progression

```
setup → beamline_alignment → xes_alignment → sample_alignment → collection → complete
                                     │                                ↑
                                     └────────────────────────────────┘
                                   (xes_alignment is skippable if
                                    spectrometer was pre-aligned)
```

Each forward transition requires preconditions checked by
`PreconditionChecker`. Backward transitions require Slack approval
(default deny). The `collection → complete` transition is always blocked
— only the operator can stop the run.

### Phase ordering and agents

| Phase | Agent script | Agent type slug | Motor allowlist |
|---|---|---|---|
| setup | (no agent) | — | none |
| beamline_alignment | `bl-aligner-claude.sh` | `beamline_alignment` | energy, mono, crystal, gap, mirrors, slits, Bx/Bz, Sx-Sz, filter |
| xes_alignment | (part of bl-aligner flow) | — | emiss, Az, Dz, crystal axes, mono, energy |
| sample_alignment | `sample-aligner-claude.sh` | `sample_alignment` | Sx, Sy, Sz, Sr, energy, emiss, filter |
| sample_survey | `sample-surveyor-claude.sh` | `sample_survey` | (runs between alignment and collection) |
| collection | `data-collection-claude.sh` | `collection` | Sx, Sy, Sz, Sr, energy, emiss, filter |
| — | `planner-claude.sh` | `planner` | (no SPEC writes — read-only + plan mutations) |

## Data flow by phase

### 1. Setup (operator-driven, no agent)

**Input:** Operator configures via `/config` UI or Slack `setdir`.

**Written to DB:**
- `Experiment` row (beamline, mono crystal, beam size, sample env, calibration foil)
- `ExperimentElement` rows (element, edge, crystal config, vortex counter)
- `SampleHolder` rows (holder name, type, queue order)
- `SamplePosition` rows (sample name, element, stage boundaries, XAS/RIXS params, filter suggestions)

**Builds:** `ExperimentPlan` row via `build_initial_plan()` — populates
`plan_json` with the full sample queue derived from the above config.

**Handoff to beamline_alignment:** `ExperimentPlan.phase` set to
`beamline_alignment`. Preconditions: experiment loaded + beam present.

### 2. Beamline Alignment

**Reads:**
- `Experiment` (mono crystal, beam size, mirrors config)
- `ExperimentElement` (incident energy, calibration foil element/detector)

**SPEC commands (via `beamtimehero spec-write`):**
- Motor scans: `dscan`, `ascan` on mono pitch, slits, mirrors
- Procedures: `align_beamline`, `calibrate_mono`, `peak_mono_pitch`,
  `measure_beam_size`, `bigbeam`/`smallbeam`, `m2_stripe`

**Written to DB:**
- `PhaseRun` row (status, scan range, anomaly flags)
- `ScanRecord` rows (per alignment scan: motor, position, FWHM, centroid, decision)
- `MotorPosition` snapshots
- `ActionLog` rows (every SPEC command, with justification)
- `Experiment.beam_h_fwhm_um`, `beam_v_fwhm_um` (measured beam size)

**Precondition facts recorded:**
- `align_beamline_ok = True`
- `calibrate_mono_residual_ev = <float>`

**Handoff to sample_alignment:** Preconditions require `align_beamline_ok`
and mono calibration residual < 0.2 eV. These facts are re-derived from
`ActionLog` on every check (`seed_from_action_log`) because the checker
lives in the FastAPI parent process but tools run in agent subprocesses.

### 3. XES Alignment (optional, within beamline alignment flow)

**Reads:**
- `ExperimentElement` (emission energy, crystal HKL, row radius)
- Spectrometer hardware state via SPEC

**SPEC commands:**
- `align_xes_spectrometer`, `set_xes_en_offset`
- Motor scans on emiss, analyzer axes (Ax1-7), crystal y/pitch (c1-7y/p)

**Written to DB:**
- Same as beamline alignment (ScanRecord, ActionLog, etc.)
- `Experiment.spectrometer_aligned = True` (gates downstream tiles)

**Precondition facts:**
- `align_xes_ok = True`
- `xes_en_offset_set = True`

### 4. Sample Alignment

**Reads:**
- `SamplePosition` rows (stage boundaries sx/sy/sz lo/hi, step sizes)
- `ExperimentElement` (for `select_element` — sets energy + vortex ROI)
- `ExperimentPlan.plan_json` (sample queue ordering)

**SPEC commands:**
- `auto_sample_align` (the macro that drives Sx/Sy/Sz scans per sample)
- `select_element` (configures SPEC for the sample's element/edge)
- Motor scans: `dscan` on Sx, Sy, Sz to find sample edges + center

**Written to DB:**
- `ScanRecord` rows (alignment scans per sample)
- `SamplePosition` updates: refined boundaries and step sizes
- `ActionLog` rows
- Precondition fact: `n_samples_aligned` incremented per successful alignment

**Handoff to collection:** Precondition requires all configured samples
to have stored positions (`n_samples_aligned >= n_samples_configured`).

### 5. Sample Survey (between alignment and collection)

**Reads:**
- `SamplePosition` rows (all aligned samples in the active holder)
- `SamplePosition.xas_filter_suggested` (operator's starting filter guess)
- `ExperimentElement` (energy, emission for count rate measurement)

**SPEC commands:**
- `ct` (count) at each sample position to measure count rate
- Filter scans to assess radiation damage sensitivity

**Written to DB:**
- `SamplePosition.survey_counts_per_sec` — measured count rate
- `SamplePosition.survey_energy_ev` — energy at measurement
- `SamplePosition.xas_filter` — refined filter setting from damage assessment
- `SamplePosition.survey_completed_at` — timestamp
- `SamplePosition.survey_notes` — free-text notes
- `ActionLog` rows

**Data handoff:** The surveyor's outputs (`xas_filter`, `survey_counts_per_sec`)
are the primary inputs the data collector uses to set filter levels and
the planner uses to weight rep redistribution during convergence fallback.

### 6. Data Collection

**Reads (per scan cycle):**
- `ExperimentPlan.plan_json` — the entire plan, especially:
  - `sample_queue` ordering and per-sample status
  - `modes[].reps`, `modes[].count_time_s`, `modes[].filter_bitmask`
  - `modes[].reps_per_spot`, `modes[].n_spots` (spot-level distribution)
  - `thresholds.snr_target`, `thresholds.min_reps_per_sample`
- `SamplePosition` (stage boundaries for spot positioning)
- `CollectionScan` (prior scans — to count reps completed, avoid re-scanning)

**SPEC commands:**
- `select_element` (per-element setup)
- `run_xas` / `emiss_scan` (data collection macros)
- Motor moves: `umv Sx/Sy/Sz` (position to spot)

**Written to DB:**
- `CollectionScan` row per scan (technique, scan number, spec datafile,
  filter setting, count time, spot index)
- `ExperimentPlan.plan_json` updates via `record_sample_progress`:
  - `status` transitions (`queued` → `in_progress` → `done`)
  - `reps_completed` increment
  - `snr_estimate`, `efficiency_verdict`
  - `notes` append
- `ActionLog` rows

**Triggers planner:** Every new `CollectionScan` row triggers the
orchestrator tick to respawn the planner agent (if not already running).

### 7. Planner (runs between scans during collection)

**Reads:**
- `ExperimentPlan.plan_json` (full plan state)
- `CollectionScan` rows (to compute per-sample, per-spot rep counts)
- `SamplePosition` (survey data for count-rate-weighted redistribution)
- `Experiment.end_time` (budget computation)
- `SampleHolder` (pacing: completed vs. remaining holders)

**Written to DB:**
- `ExperimentPlan.plan_json` updates via planner mutation functions:
  - `record_convergence_stats` (SNR, chi-sq, edge step, verdict)
  - `set_sample_time_budget` (adjust reps, count time, spot distribution)
  - `replace_plan` (bulk rewrite — e.g. convergence fallback redistribution)
  - `update_thresholds` (SNR target, min reps)
  - `reorder_plan`, `skip_sample` (queue management)
- `PlanEdit` rows (audit trail for every mutation)

**No SPEC writes.** The planner is read-only with respect to the
beamline — it only mutates the plan. The data collector acts on the
updated plan in its next cycle.

## Agent ↔ system communication

Agents are `claude -p` subprocesses. They cannot import Python from the
parent process. All communication is through:

1. **`beamtimehero` CLI** — the agent's only tool. Five command trees:
   - `ref` — reference docs (read-only)
   - `tool` — plotting, analysis tools
   - `db` — plan CRUD, sample/holder queries, steering ack/complete
   - `spec-read` — non-mutating SPEC queries (motor positions, scan data)
   - `spec-write` — mutating SPEC commands (scans, moves, macros)

2. **stdin seed** — the orchestrator writes a stream-JSON user message to
   the agent's stdin at spawn time (kickoff prompt or focused-task seed
   for steering re-dispatch). The agent receives this as its first user
   turn.

3. **stdout JSONL** — the agent's stream-JSON output is logged to
   `logs/phase_<slug>_<ts>.log` (with per-field truncation for oversized
   base64 images).

4. **SQLite** — the shared state layer. The parent process and agent
   subprocesses both read/write the same SQLite files. This is why WAL
   mode + busy_timeout + optimistic locking matter.

## Steering flow

Staff guidance enters via Slack or the UI and follows a state machine:

```
Slack/UI ingest
  → StaffGuidance row (source, author, text, slack provenance)
  → orchestrator tick acks (orchestrator_ack_at, ack_comment)
  → dispatched to active agent (active_agent_run_id)
     OR deferred to target_agent_type for later respawn
  → agent acks (active_agent_ack_at)
  → agent completes (result, completed_at)
  → orchestrator posts reply to slack_thread_ts
```

STOP rows (`is_stop=true`) skip the normal pipeline: the orchestrator
kills all running agents (except a named target), then spawns the target
with the steering text.

## Intervention flow

Agents request human intervention for physical actions or backward
phase transitions:

```
Agent creates InterventionRequest
  → kind: crystal_install | sample_mount | foil_insert |
          backward_transition | gap_ownership | custom
  → status: waiting
  → posted to Slack
  → operator resolves: resolved | denied | timed_out
```

Backward phase transitions always create an intervention and block
until the operator responds (no timeout — the agent waits indefinitely).

## WebSocket broadcast

The FastAPI server pushes live updates to connected UI clients:

- Plan changes (sample status, convergence stats)
- Phase transitions
- Agent spawn/exit events
- Steering lifecycle updates
- New scan notifications

The UI polls `/api/dashboard/status` as a fallback; WebSocket is the
primary push channel for responsive updates.
