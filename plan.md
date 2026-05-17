# Autonomous Beamline Agent — Implementation Plan

## Goal

A single application in this repo that runs BL15-2 (SSRL) fully autonomously:

1. **Beamline alignment** via `align_the_beamline` macro (CAT-0).
2. **XES spectrometer crystal alignment** via `run_spec_align` (CAT-0).
3. **Sample holder alignment** via `auto_sample_align` (CAT-0).
4. **Data collection** via `run_collection` + element-specific `_xas` / `_cee` macros.
5. **Real-time analysis + steering**: evaluate SNR, convergence, efficiency after each scan; revise plan.
6. **Beamtime budget + sample throughput**: make and adapt an experiment plan.
7. **Human-in-the-loop**: pause for crystal install, sample mount, gap ownership; resume via Slack.
8. **Staff guidance**: live Slack input steers the agent mid-run.
9. **Auditability**: every SPEC action is written to sqlite `action_log` *with a required justification before dispatch*.
10. **Web UI**: themed SSRL dashboard showing phase progress, current action, plan, budget, quality metrics. Always-on, non-blocking chat pane.
11. **Slack**: periodic progress posts + pause-for-human alerts + staff-guidance intake.

## Source projects being merged

- **`../beamtimehero/`** — LLM agent scaffold. Keeps: `server/` (FastAPI + conversation loop + Slack bridge), `beamline_lib/` (SPEC screen client, scan reader, analysis), `static/` (chat UI), `context/` (system prompt + reference docs). Model: Claude via Stanford AI API Gateway.
- **`../beamline/`** — Phase model + DB. Keeps: `db/models.py` + `db/client.py` (SQLModel schema: Experiment, ExperimentElement, SampleHolder, SamplePosition, PhaseRun, ScanRecord, CollectionScan, LLMLog, MotorPosition, Image), `analysis/` (decisions, fitter, scan_strategies), `llm/advisor.py` (phase assessments), `slack/notify.py`, `reports.py`, `spec_reader.py`, `config_generator.py`, `dashboard/` (themed SSRL UI), `web/` (experiment config form).
- **`../design_handoff_autonomous_beamline_agent/needed-tools-for-autonomy.md`** — Authoritative spec for new `spec_cmd` CLI + CAT-0..CAT-8 tools + action_log schema + `transition_phase` orchestration.

## Architecture

Single FastAPI server + in-process background scheduler. Exposes three "audiences":

1. **Web UI (user-facing)** — themed SSRL dashboard + experiment config form + chat pane. Always-on chat shown during any phase; never blocks the agent loop.
2. **Agent tool API** — `POST /spec_cmd`, `GET /spec_cmd/status`, `GET /spec_cmd/wait`, plus CAT-0..CAT-8 endpoints. Used by the agent tool loop.
3. **Slack** — Socket Mode bot listening to `#beamtimehero` (LLM mirror + staff guidance) and `#users` (user relay). Reuses beamtimehero's 3-channel pattern.

```
autonomous/
├── server/
│   ├── app.py                    # FastAPI hub (from beamtimehero, extended)
│   ├── config.py                 # env + paths
│   ├── api_client.py             # Stanford AI client (Claude)
│   ├── conversation.py           # LLM tool-loop (from beamtimehero)
│   ├── slack_bridge.py           # Slack Socket Mode (from beamtimehero)
│   ├── tools/                    # agent tool layer
│   │   ├── definitions.py        # OpenAI-style tool schemas
│   │   ├── executor.py           # dispatch
│   │   ├── cli.py                # CLI/progressive discovery mode
│   │   └── autonomy_tools.py     # NEW — CAT-0..CAT-8 tool wrappers
│   ├── orchestrator/             # NEW — autonomous loop + planner
│   │   ├── loop.py               # agent loop (plan→act→observe→replan)
│   │   ├── planner.py            # beamtime budget + sample plan
│   │   ├── phase.py              # transition_phase + allowlists
│   │   └── staff_guidance.py     # Slack-driven steering queue
│   ├── spec/                     # NEW — spec_cmd endpoint + screen client
│   │   ├── spec_cmd.py           # whitelist dispatch + phase gate
│   │   ├── screen_client.py      # screen inject + prompt-detect poll
│   │   └── phases.py             # phase constants + agent-role allowlists
│   ├── action_log/               # NEW — sqlite action logging
│   │   ├── db.py                 # sqlite schema + writer
│   │   └── models.py             # pydantic shapes
│   ├── ui/                       # UI routers
│   │   ├── config_api.py         # experiment config form (from beamline/web)
│   │   └── dashboard_api.py      # phase dashboard (from beamline/db/server)
│   └── analysis/                 # from beamline/analysis (fitter, decisions, strategies)
├── beamline_lib/                 # from beamtimehero (scan reader, logs, plots)
├── static/                       # themed UI (merged from both projects)
│   ├── index.html                # landing: config form
│   ├── dashboard.html            # phase dashboard
│   ├── chat.html                 # chat-only pane (used in split view)
│   ├── css/                      # SSRL design tokens + beamtimehero styles
│   └── js/                       # form.js, dashboard.js, chat.js
├── context/                      # agent system prompt + BL15-2 references
├── config/
│   └── defaults.yaml             # from beamline/config/defaults.yaml
├── data/                         # runtime DB + logs
│   └── autonomous.db             # sqlite — experiments + phase runs + action_log + query_log + phase_transition_log
├── scripts/
│   ├── start.sh                  # launch venv + server
│   └── smoke_test.py             # end-to-end mock driver
├── requirements.txt
├── README.md
└── plan.md                       # (this file)
```

## Phase model

Fixed sequence. Agent advances via `transition_phase(target, justification)`. Backward transitions require Slack approval.

```
setup → beamline_alignment → [xes_alignment] → sample_alignment → collection → complete
```

Motor allowlist gate per phase (full table in spec). Enforced in `spec/phases.py`, consulted by `spec_cmd` before dispatch.

## Agent tool surface

Implement all tools from `needed-tools-for-autonomy.md` as Python functions registered in `server/tools/autonomy_tools.py` and exposed through the same dispatch layer as existing read-only tools. Tools are grouped:

- **CAT-0 procedural (primary)**: `align_beamline`, `align_xes_spectrometer`, `run_sample_alignment`, `run_collection`, `select_element`, `peak_mono_pitch`, `calibrate_mono`.
- **`spec_cmd` read-only**: `wa`, `p_motor`, `get_S`, `ct`, `fon`, `pwd`, `scan_n`, `beam_status`, `p_global`.
- **`spec_cmd` action**: `umv`, `umvr`, `mv`, `ascan`, `dscan`, `cen`, `peak`, `shutter`, `mv_energy`, `xas`, `emiss_scan`, `safely_remove_filters`, `set_i0_gain`, `set_i1_gain`, `set_i2_gain`, `set_vortex_roi`, `newfile`, `abort`, `gaprequest`, `run_shortcut`.
- **Scan execution wrappers**: `run_motor_scan`, `run_motor_scan_relative`, `run_xas`, `run_emiss_scan`.
- **Alignment fallbacks (CAT-4)**: `run_align_shortcut`, `post_scan_move`, `optimize_motor_on_signal`, `zero_pinhole`, `find_pinhole`, `center_on_pinhole`, `center_on_sample`.
- **Sample management (CAT-5)**: `move_to_sample`, `store_sample_position`, `scan_sz_for_samples`.
- **Beam monitoring (CAT-6)**: `get_beam_status`, `get_counts`, `get_counter`, `wait_for_stable_beam`, `request_gap_ownership`.
- **Run state (CAT-7)**: `get_scan_number`, `get_current_datafile`.
- **Orchestration (CAT-8)**: `transition_phase`, `post_status_update`, `request_human_intervention`, `update_plan`, `get_plan`, `get_remaining_beamtime`, `get_staff_guidance`.

Keep the existing beamtimehero read-only tools (analysis, plotting, logs, files) exposed unchanged — they remain the "eyes".

## Action logging (non-negotiable)

`action_log` sqlite table per the spec. Writer sits in front of the screen client — *cannot* dispatch a SPEC command without first writing a record with `justification`. Read-only `spec_cmd` tier writes to `query_log` (same shape, no justification). Dashboard shows the last N actions with colorized status badges.

## Planner + steering loop

`server/orchestrator/loop.py` runs the outer agent loop:

1. Load experiment config → build initial plan (ordered samples × scan modes × reps).
2. Track budget: elapsed time, remaining hours, phase progress, per-sample quality scores (from `analyze_efficiency`).
3. On each observation (scan complete, LLM response), reassess: repeat sample? skip? advance phase? stop?
4. Absorb staff guidance from a Slack-fed queue (`staff_guidance.py`) on every iteration — guidance becomes a system message for the next LLM turn and is displayed in the UI.
5. Stream structured status events to the dashboard via the existing WebSocket broadcaster.

The planner is *advisory* — it composes the context; the LLM still chooses the next tool call. This keeps the agent flexible (can deviate when data surprises it) while anchoring it to the budget.

## Pause-for-human

Three categories of human interaction:

1. **Planned interventions** (crystal install, sample mount, foil insert): modeled as a `request_human_intervention(kind, detail)` tool. It posts a Slack message with a resume button (`"✅ Done — resume"`) and blocks the agent on `asyncio.Event`. UI shows a matching banner with a "Mark complete" button.
2. **Gap ownership**: `request_gap_ownership()` uses the blocking SPEC `gaprequest` with timeout; on timeout it escalates via Slack.
3. **Backward phase transitions**: `transition_phase` backward triggers Slack approve/deny with default-deny timeout (60 s for one step back, 30 s for more).

All three flow through `staff_guidance.py` so reads are consistent.

## Slack

Reuse beamtimehero's SlackBridge verbatim, add two new message types posted by the orchestrator:

- **`post_status_update(phase, summary)`** — periodic (configurable, default every 15 min) high-level progress ping to `#beamtimehero`.
- **`request_human_intervention(kind, detail)`** — blocks until staff reply `resume` or press the UI button.

Staff guidance intake uses the existing `on_llm_thread_reply` → buffered into the conversation on the next turn; unchanged behavior, we just add a header tag "[STEERING]" so the UI can highlight it.

## UI

Single themed SSRL dashboard with three integrated panels:

- **Left: phase tiles** (4 phases, status badges, metrics) — from `beamline/dashboard/`.
- **Right: chat pane + staff guidance feed** — from `beamtimehero/static/`.
- **Footer: action log tape** — last 10 `action_log` entries with justification tooltip. NEW.

Dedicated pages:

- **`/` — experiment config form** (two-tab form from beamline/web).
- **`/dashboard` — live phase dashboard** (new merged page).
- **`/history` — scrollable action-log + query-log viewer** (NEW, simple).

Polling every 5 s + WebSocket push on state-change events (phase transition, action started, action completed, pause triggered).

## Port strategy

Single FastAPI on port **8080** (user disallowed 5000). Serves the UI, agent API, and dashboard API from one process. No Flask — port the form's handlers into FastAPI routes to simplify deployment.

## Testing strategy (outside production)

- Unit-test the spec_cmd whitelist + phase allowlist + action_log writer.
- Unit-test the planner's budget math.
- Mock the screen client so end-to-end tests drive the phase state machine without SPEC. The mock returns canned `SPEC>` prompts + synthetic scan numbers.
- Smoke test (`scripts/smoke_test.py`) runs through setup → beamline_alignment → sample_alignment → collection → complete using the mock, confirming: action_log entries written, phase transitions gated correctly, pause-for-human blocks and resumes, Slack messages dispatched to a stub, WebSocket events broadcast.
- Document what can't be tested without a live SPEC: real alignment convergence, real scan data quality, real beam-status EPICS.

## Execution order

1. Fork beamtimehero → `./autonomous/`. Keep agent loop, Slack, tool framework, SPEC client.
2. Port beamline DB + analysis + llm advisor + reports + spec_reader + config_generator.
3. Port beamline UI (dashboard + form) into FastAPI routes under `/ui/*`.
4. Add `action_log` + `query_log` + `phase_transition_log` sqlite tables and a writer.
5. Implement `spec_cmd` dispatch layer with whitelist + phase allowlist.
6. Implement CAT-0..CAT-8 tool wrappers. Register with tool definitions.
7. Implement orchestrator loop + planner + staff guidance + pause-for-human.
8. Merge the two UIs; add the action-log tape + plan panel.
9. Smoke-test end-to-end with the screen mock.
10. README + start script + sample `.env`.

When done, the user can `cd autonomous && ./scripts/start.sh`, open `http://localhost:8080`, fill the experiment form, click "Start autonomous run", and watch the agent execute the four phases with Slack + UI updates.
