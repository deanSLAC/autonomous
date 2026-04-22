# HTTP endpoint catalog

Inventory of every HTTP route and WebSocket registered on the FastAPI
app, grouped by function. Paths are shown as served — `BASE_PATH` is
empty by default (see `server/config.py`), so the raw decorator paths
are what the browser/client hits.

The **Links to** field on page routes lists the other endpoints the
served HTML + its JS calls. For pure API endpoints it's `—` (they are
leaf calls). **Used by** on API endpoints lists the page(s) that hit
them, to make the cross-reference symmetric.

Routers are registered in [server/app.py:284-290](server/app.py#L284-L290):

| Prefix                   | Router file                      |
|--------------------------|----------------------------------|
| `/api`                   | `server/ui/config_api.py`        |
| `/api/dashboard`         | `server/ui/dashboard_api.py`     |
| `/api/orchestrator`      | `server/ui/orchestrator_api.py`  |
| `/api/plan`              | `server/ui/plan_api.py`          |
| `/api/insight`           | `server/ui/insight_api.py`       |
| `/api/sample_holders`    | `server/ui/sample_holders_api.py`|
| `/api/viewer`            | `server/ui/viewer_api.py`        |

Everything else (page routes, `/api/chat`, `/api/tools`, `/api/reset`,
`/ws`, `/health`) is defined directly in `server/app.py`.

---

## Page routes

### `GET /`

- **Handler:** `app._index_page` (serves `static/dashboard/index.html`)
- **What it does:** Same payload as `/dashboard` — the autonomous-run dashboard.
- **Links to:** `/api/dashboard/experiments`, `/api/dashboard/status`, `/api/orchestrator/status`, `/api/orchestrator/start`, `/api/orchestrator/pause`, `/api/orchestrator/resume`, `/api/orchestrator/stop`, `/api/orchestrator/reset`, `/api/orchestrator/guidance`, `/api/orchestrator/intervention/{id}/resolve`, `/api/plan/*`, `/api/chat`, `/api/tools`, `/ws`, `/health`.

### `GET /dashboard`

- **Handler:** `app.dashboard_page` (serves `static/dashboard/index.html`)
- **What it does:** Autonomous-run dashboard — top bar (Tools/Insight/config/theme), control strip (start/pause/resume/stop/reset), phase tiles, sample plan table, latest agent output, guidance + chat panels, plan-history feed, action log tape.
- **Links to:** Same as `/` above.

### `GET /phase`

- **Handler:** `app.phase_page` (serves `static/dashboard/phase.html`)
- **What it does:** Per-phase detail drill-down — lists the scan records and metadata for one phase run.
- **Links to:** `/api/dashboard/phase/{phase_run_id}`, `/api/dashboard/status`, `/api/dashboard/image`.

### `GET /config`

- **Handler:** `app.config_page` (serves `static/config/index.html`)
- **What it does:** Experiment configuration form — experimenter, mono crystal, beam, mirrors, sample environment, per-element settings.
- **Links to:** `/api/defaults`, `/api/submit_experiment`, `/api/submit_sample_holder`, `/api/experiment_summary/{id}`, `/api/load_experiment/{id}`, `/api/load_active`, `/api/element_info`, `/api/lookup_energy`, `/api/experiments`, `/api/orchestrator/start`, `/health`. *Also contains a legacy reference to `/api/submit_collection` in `form.js:938` which has no server handler — dead code.*

### `GET /sample_planning`

- **Handler:** `app.sample_planning_page` (serves `static/sample_planning/index.html`)
- **What it does:** Sample queue editor — per-sample reps/count-time, holder-level budgets, thresholds, phase toggles, sample add/remove/reorder/skip.
- **Links to:** `/api/plan/{experiment_id}`, `/api/plan/{experiment_id}/edits`, every `POST /api/plan/*`, `/api/dashboard/status`, `/api/orchestrator/status`.

### `GET /sample_holders`

- **Handler:** `app.sample_holders_page` (serves `static/sample_holders/index.html`)
- **What it does:** Multi-holder CRUD — create, edit, delete, reorder sample holders; open the SPEC viewer for a holder.
- **Links to:** `/api/experiment_summary/{id}`, `/api/sample_holders/list`, `/api/sample_holders/{id}`, `/api/sample_holders/create`, `/api/sample_holders/update`, `/api/sample_holders/delete`, `/api/sample_holders/reorder`, `/viewer`.

### `GET /viewer`

- **Handler:** `app.viewer_page` (serves `static/viewer/index.html`)
- **What it does:** SPEC file browser and scan plotter — pick a file, pick a scan, get data + plot.
- **Links to:** `/api/viewer/files`, `/api/viewer/scans`, `/api/viewer/scan_data`.

### `GET /tools`

- **Handler:** `app.tools_page` (serves `static/tools/index.html`)
- **What it does:** "What the agent can do" catalog — per-tool Python function, SPEC command string, data source, inputs/outputs, and tool dependencies.
- **Links to:** `/api/tools`.

### `GET /insight`

- **Handler:** `app.insight_page` (serves `static/insight/index.html`)
- **What it does:** Agent insight — turn tape, tool call/response panels, optional system-prompt viewer, simulation-mode pill.
- **Links to:** `/api/insight/turns`, `/api/insight/simulation`, `/api/insight/system_prompt`, `/api/dashboard/action_log`, `/ws`, `/health`.

### `GET /history`

- **Handler:** `app.history_page` (inline HTML — no static file)
- **What it does:** Reads-only audit view — last 200 action-log entries, one row per action with timestamp/phase/command/justification/outcome badge.
- **Links to:** `/api/dashboard/action_log`.

---

## Health

### `GET /health`

- **Handler:** `app.health`
- **What it does:** Returns phase, simulation flag, opencode reachability, orchestrator init state, and the active scan directory. Polled by every page for the status-dot indicator.
- **Used by:** `/`, `/dashboard`, `/config`, `/insight`.

---

## Configuration APIs (router prefix `/api`)

### `GET /api/defaults`

- **Handler:** `config_api.get_defaults`
- **What it does:** Returns the default experiment configuration values from `config/defaults.yaml` — populates the config form when the user clicks "New experiment".
- **Used by:** `/config`.

### `POST /api/submit_experiment`

- **Handler:** `config_api.submit_experiment`
- **What it does:** Creates or updates an experiment record (name, experimenter, mono crystal, beam size, mirrors, sample environment, element list) from the first step of the config form.
- **Used by:** `/config`.

### `POST /api/submit_sample_holder`

- **Handler:** `config_api.submit_sample_holder`
- **What it does:** Writes a single sample holder + its samples for the active experiment; if a plan already exists, regenerates it to absorb the new holder.
- **Used by:** `/config`.

### `GET /api/experiment_summary/{experiment_id}`

- **Handler:** `config_api.experiment_summary`
- **What it does:** Compact experiment payload (metadata + element list) for header strips and dropdown summaries.
- **Used by:** `/config`, `/sample_holders`.

### `GET /api/load_experiment/{experiment_id}`

- **Handler:** `config_api.load_experiment`
- **What it does:** Full experiment hydration — metadata, elements, and every holder with samples — used when editing an existing experiment.
- **Used by:** `/config`.

### `GET /api/load_active`

- **Handler:** `config_api.load_active`
- **What it does:** Convenience endpoint: loads the most-recently-created experiment's full config.
- **Used by:** `/config`.

### `POST /api/element_info`

- **Handler:** `config_api.element_info`
- **What it does:** Queries xraydb for an element's edges + emission lines, filtered to the BL15-2 accessible energy range. Powers the edge picker in the config form.
- **Used by:** `/config`.

### `POST /api/lookup_energy`

- **Handler:** `config_api.lookup_energy`
- **What it does:** Returns incident + emission energies for a chosen element/edge pair — used to auto-fill the element row when a user picks an edge.
- **Used by:** `/config`.

### `GET /api/experiments`

- **Handler:** `config_api.list_experiments`
- **What it does:** Recent-experiments list (id + name + status) for the top-bar experiment selector.
- **Used by:** `/config`.

---

## Dashboard APIs (router prefix `/api/dashboard`)

### `GET /api/dashboard/experiments`

- **Handler:** `dashboard_api.experiments`
- **What it does:** Recent experiments with name/experimenter/status/sample-environment; drives the dashboard top-bar dropdown.
- **Used by:** `/dashboard`.

### `GET /api/dashboard/status`

- **Handler:** `dashboard_api.status`
- **What it does:** One-shot status snapshot for a given `experiment_id` — plan, elements, holders, phase runs, scan records, action log head, intervention queue, guidance history. This is the dashboard's main polling endpoint.
- **Used by:** `/dashboard`, `/phase`, `/sample_planning`.

### `GET /api/dashboard/phase/{phase_run_id}`

- **Handler:** `dashboard_api.phase`
- **What it does:** Per-phase-run detail (scan records + metadata) used by the phase drill-down page.
- **Used by:** `/phase`.

### `GET /api/dashboard/image`

- **Handler:** `dashboard_api.image`
- **What it does:** Serves a PNG/JPEG summary image from a phase run by relative path (used for inline thumbnails of alignment plots).
- **Used by:** `/phase`.

### `GET /api/dashboard/action_log`

- **Handler:** `dashboard_api.action_log`
- **What it does:** Recent action-log + query-log entries, optionally filtered by experiment. Feeds the action tape on `/dashboard`, the full list on `/history`, and the tool-call tape on `/insight`.
- **Used by:** `/dashboard`, `/history`, `/insight`.

---

## Orchestrator control APIs (router prefix `/api/orchestrator`)

### `POST /api/orchestrator/start`

- **Handler:** `orchestrator_api.start`
- **What it does:** Builds the initial plan and starts the autonomous orchestrator loop (needs `experiment_id`, optional `beamtime_hours`).
- **Used by:** `/dashboard`, `/config`.

### `POST /api/orchestrator/pause`

- **Handler:** `orchestrator_api.pause`
- **What it does:** Pauses the orchestrator between turns without tearing down state.
- **Used by:** `/dashboard`.

### `POST /api/orchestrator/resume`

- **Handler:** `orchestrator_api.resume`
- **What it does:** Resumes the paused orchestrator.
- **Used by:** `/dashboard`.

### `POST /api/orchestrator/stop`

- **Handler:** `orchestrator_api.stop`
- **What it does:** Stops the orchestrator loop; config + plan are kept, action history is kept, Start resumes from the saved phase.
- **Used by:** `/dashboard`.

### `POST /api/orchestrator/reset`

- **Handler:** `orchestrator_api.reset`
- **What it does:** Hard reset — stops the run, invalidates action logs, resolves open interventions, resets the phase to `setup`. Experiment config and sample plan are preserved.
- **Used by:** `/dashboard`.

### `GET /api/orchestrator/status`

- **Handler:** `orchestrator_api.status`
- **What it does:** Orchestrator state snapshot (turn count, latest summary, current phase, budget used, agent-backend reachability).
- **Used by:** `/dashboard`, `/sample_planning`.

### `POST /api/orchestrator/guidance`

- **Handler:** `orchestrator_api.submit_guidance`
- **What it does:** Records a piece of steering text from staff/user (the "Experimenter Guidance" panel) into the guidance queue the agent reads next turn.
- **Used by:** `/dashboard`.

### `POST /api/orchestrator/intervention/{intervention_id}/resolve`

- **Handler:** `orchestrator_api.resolve_intervention`
- **What it does:** Marks a paused-for-human intervention as resolved or denied, with an optional note; unblocks the agent.
- **Used by:** `/dashboard`.

### `POST /api/orchestrator/phase`

- **Handler:** `orchestrator_api.force_phase`
- **What it does:** Operator override — writes a specific phase as the active one, bypassing the agent's transition gate. Used for recovery / manual reset mid-run.
- **Used by:** `/dashboard`.

---

## Chat & tool APIs

### `POST /api/chat`

- **Handler:** `app.chat`
- **What it does:** Accepts the user's free-form chat text, prepends planner + page context, forwards to the LLM, and returns the reply + any tool-generated images.
- **Used by:** `/dashboard`.

### `GET /api/tools`

- **Handler:** `app.get_tools`
- **What it does:** Full tool catalog — every LLM-callable tool with long description, Python function chain, SPEC command (when applicable), source, inputs, outputs, and `depends_on`. Powers the `/tools` page.
- **Used by:** `/tools`.

### `POST /api/reset`

- **Handler:** `app.reset`
- **What it does:** Resets the chat conversation service (fresh LLM session) and clears the Slack bridge thread. Distinct from `/api/orchestrator/reset` — this one is chat-only.
- **Used by:** `/dashboard` (currently unwired in the UI; reachable from the API directly).

---

## Insight APIs (router prefix `/api/insight`)

### `GET /api/insight/turns`

- **Handler:** `insight_api.turns`
- **What it does:** Last *N* LLM turns from the ring buffer (timestamp, text, tool calls, source). Feeds the turn tape on `/insight`.
- **Used by:** `/insight`.

### `GET /api/insight/simulation`

- **Handler:** `insight_api.simulation_status`
- **What it does:** Simulation-mode flag + mock screen positions (when simulating). Drives the `SIM` pill in the top bar.
- **Used by:** `/insight`, `/dashboard`.

### `GET /api/insight/system_prompt`

- **Handler:** `insight_api.system_prompt`
- **What it does:** Returns the agent's current system-prompt text + source file path. Shown in the optional verbose panel on `/insight`.
- **Used by:** `/insight`.

---

## Plan steering APIs (router prefix `/api/plan`)

Every `POST` here logs a `plan_edit` audit row with author + reason.

### `GET /api/plan/{experiment_id}`

- **Handler:** `plan_api.get_plan`
- **What it does:** Full experiment plan — sample queue, budget, thresholds, holder budgets — plus the most recent edits.
- **Used by:** `/sample_planning`.

### `GET /api/plan/{experiment_id}/edits`

- **Handler:** `plan_api.get_edits`
- **What it does:** Plan edit history (who changed what, when, why) with optional `limit`.
- **Used by:** `/sample_planning`, `/dashboard` (plan-history feed).

### `POST /api/plan/add_sample`

- **Handler:** `plan_api.add_sample`
- **What it does:** Inserts a new sample into the queue at an optional position.
- **Used by:** `/sample_planning`.

### `POST /api/plan/remove_sample`

- **Handler:** `plan_api.remove_sample`
- **What it does:** Removes a sample from the queue.
- **Used by:** `/sample_planning`.

### `POST /api/plan/skip_sample`

- **Handler:** `plan_api.skip_sample`
- **What it does:** Marks a sample as skipped with an optional note (kept in the plan for audit).
- **Used by:** `/sample_planning`.

### `POST /api/plan/reorder`

- **Handler:** `plan_api.reorder`
- **What it does:** Reorders the queue to the given list of `sample_id`s.
- **Used by:** `/sample_planning`.

### `POST /api/plan/update_sample`

- **Handler:** `plan_api.update_sample`
- **What it does:** Updates a sample's modes / status / SNR target / note.
- **Used by:** `/sample_planning`.

### `POST /api/plan/extend_budget`

- **Handler:** `plan_api.extend_budget`
- **What it does:** Adds (or subtracts, with a negative delta) hours to the total beamtime budget.
- **Used by:** `/sample_planning`.

### `POST /api/plan/set_budget`

- **Handler:** `plan_api.set_budget`
- **What it does:** Sets the total beamtime budget to an absolute value.
- **Used by:** `/sample_planning`.

### `POST /api/plan/update_thresholds`

- **Handler:** `plan_api.update_thresholds`
- **What it does:** Updates plan-level thresholds (SNR target, min reps per sample, max drift).
- **Used by:** `/sample_planning`.

### `POST /api/plan/set_sample_time_budget`

- **Handler:** `plan_api.set_sample_time_budget`
- **What it does:** Sets count_time and/or reps for a single sample, optionally scoped to one mode (`xas` or `emiss`).
- **Used by:** `/sample_planning`.

### `POST /api/plan/set_holder_time_budget`

- **Handler:** `plan_api.set_holder_time_budget`
- **What it does:** Sets the default count_time / reps for an entire holder; optionally propagates to existing samples.
- **Used by:** `/sample_planning`.

### `POST /api/plan/set_phase_enabled`

- **Handler:** `plan_api.set_phase_enabled`
- **What it does:** Enables or disables a phase in the plan; returns the list of phases skipped as a result.
- **Used by:** `/sample_planning`, `/dashboard` (per-phase toggles).

### `POST /api/plan/regenerate`

- **Handler:** `plan_api.regenerate`
- **What it does:** Rebuilds the plan from the current set of DB holders while preserving sample progress (status, reps_completed, notes) and user overrides.
- **Used by:** `/sample_planning`.

---

## Sample holders APIs (router prefix `/api/sample_holders`)

### `GET /api/sample_holders/list`

- **Handler:** `sample_holders_api.list_for_experiment`
- **What it does:** Every holder for a given experiment, with its samples and status.
- **Used by:** `/sample_holders`.

### `GET /api/sample_holders/{holder_id}`

- **Handler:** `sample_holders_api.get_holder`
- **What it does:** Full holder detail for editing (metadata + samples + per-sample measurement params).
- **Used by:** `/sample_holders`.

### `POST /api/sample_holders/create`

- **Handler:** `sample_holders_api.create`
- **What it does:** Creates a new holder + its samples; regenerates the plan if one exists.
- **Used by:** `/sample_holders`.

### `POST /api/sample_holders/update`

- **Handler:** `sample_holders_api.update`
- **What it does:** Updates a holder's metadata and/or sample list; regenerates the plan if one exists.
- **Used by:** `/sample_holders`.

### `POST /api/sample_holders/delete`

- **Handler:** `sample_holders_api.delete`
- **What it does:** Deletes a holder; regenerates the plan if one exists.
- **Used by:** `/sample_holders`.

### `POST /api/sample_holders/reorder`

- **Handler:** `sample_holders_api.reorder`
- **What it does:** Reorders the holders for an experiment; regenerates the plan if one exists.
- **Used by:** `/sample_holders`.

---

## Data viewer APIs (router prefix `/api/viewer`)

### `GET /api/viewer/files`

- **Handler:** `viewer_api.files`
- **What it does:** SPEC file enumeration across the experiment's scan directories, with optional filter by holder name / sample names. Returns per-file path, size, mtime, and holder-match hints.
- **Used by:** `/viewer`.

### `GET /api/viewer/scans`

- **Handler:** `viewer_api.scans`
- **What it does:** List of `#S` scan blocks in a given SPEC file.
- **Used by:** `/viewer`.

### `GET /api/viewer/scan_data`

- **Handler:** `viewer_api.scan_data`
- **What it does:** Full scan payload (columns, motor positions, parsed command) for plotting.
- **Used by:** `/viewer`.

---

## WebSocket

### `WS /ws`

- **Handler:** `app.websocket_endpoint`
- **What it does:** Long-lived bidirectional connection. Client sends `"ping"` → server replies `{"type":"pong"}`. Server broadcasts events to every connected client:
    - `{"type":"turn_complete", "turn":…}` — a new LLM turn landed
    - `{"type":"staff_message", "name":…, "text":…}` — staff message from Slack
    - `{"type":"staff_in_llm", "name":…, "text":…}` — staff reply routed into the LLM thread
    - `{"type":"assistant", "text":…, "images":…}` — LLM chat response
    - `{"type":"intervention_created", "id":…, "detail":…}` — human intervention required
    - `{"type":"status_update", "text":…}` — agent-posted progress message
- **Used by:** `/dashboard`, `/insight`.

---

## Static file mount

### `GET /static/*`

- **Handler:** FastAPI `StaticFiles`
- **What it does:** Serves CSS/JS/images from `static/` under `/static/`.
- **Used by:** Every page route.
