# Autonomous Beamline Agent — SSRL BL15-2

An LLM-driven multi-agent system that runs the BL15-2 X-ray beamline
end-to-end: beamline alignment → spectrometer crystal alignment → sample
holder alignment → data collection → real-time analysis → experiment
steering — with every SPEC action logged to sqlite and a web dashboard +
Slack bridge that keep users and staff informed.

**LLM backend:** Claude Code (`claude -p`), spawned as a subprocess per
agent task / chat turn, bound to the SLAC AI Gateway (configurable via
`LLM_GATEWAY`). Agents discover and invoke the ~100 beamline tools through
the `scripts/beamtimehero` argparse CLI (`--help` at any depth) — one
execution path, one audit log. The earlier opencode backend was removed in
June 2026; its full implementation is preserved on the
`archive/opencode-support` branch (tag `pre-opencode-removal`).

## What the agent does

1. **Setup.** User submits the experiment config form at `/config`. Planner builds a per-sample plan + budget.
2. **Beamline alignment.** Phase agent aligns upstream optics (M1/M2/mono) and measures beam size.
3. **Spectrometer alignment.** Per-crystal peaking + mono elastic scan.
4. **Sample alignment.** Wide Sz survey → per-sample fine centering + Sx/Sy boundaries.
5. **Collection.** Spot-by-spot HERFD/XAS loop under agent control, one scan at a time.
6. **Real-time analysis.** After each scan: efficiency / convergence analysis against the planner's thresholds (SNR target, min-reps) to decide more reps / skip / next sample / revise plan.
7. **Budget.** Agents see remaining beamtime + sample queue state every turn and trim accordingly.
8. **Pause-for-human.** `request_human_intervention(kind, detail)` blocks until staff resolves (Slack `!resume <id>` / `!deny <id>`, or the dashboard buttons).
9. **Slack.** Status updates, phase reports, steering channel (staff guidance), and a chat channel (threads + DMs route to a chat agent).

## Key invariants

- **Nothing reaches SPEC without a justification.** spec-write leaves require a non-empty `--justification` and every action is written to `action_log` *before* dispatch. Even if SPEC hangs, the record exists.
- **No free-form SPEC strings.** Agents choose from the whitelisted command catalog and per-role allowlisted motors (`beamline_tools/agent_roles.py`). Everything else is refused in Python before anything touches SPEC.
- **Plan state lives in sqlite** (`ExperimentPlan.plan_json`), schema-validated on every write (`orchestration/planner/plan_schema.py`) — including writes from the LLM via the `update_plan` tool.
- **Safety switches** (`beamline_tools/safety_switches.json`) gate every spec call, re-read per call — flip from the dashboard without restarting anything.

## Directory layout

```
autonomous/
├── main.py                    entry point — .env, simulation bootstrap, FastAPI
├── ui/
│   ├── server/app.py          app factory: pages, WS broadcast, chat endpoint, /health
│   ├── server/schemas.py      pydantic request models for the HTTP boundary
│   ├── server/routers/        dashboard, plan, config, phase_runner, orchestrator,
│   │                          sample_holders, safety_switches, spec_log, viewer, …
│   ├── adapters/slack_bridge.py  Slack Socket Mode bridge (steering / chat / DMs)
│   └── static/                plain HTML/CSS/JS pages (no build step):
│                              dashboard/ config/ viewer/ sample_holders/ tools/ shared/
├── orchestration/
│   ├── config.py              pydantic-settings Settings (.env is the source of truth)
│   ├── api.py                 facade the UI layer calls; event emitter wiring
│   ├── messages.py            typed cross-layer contracts (Slack inbound, chat WS events)
│   ├── planner/               plan lifecycle: planner.py, plan_schema.py, plan_summary,
│   │                          staff_guidance, orchestrator_tick
│   ├── agents/                agent spawn/drain lifecycle
│   ├── agent/                 claude_code_client.py, conversation.py, phase_runner
│   ├── chat/                  ChatRouter — dashboard + Slack chat → chat-claude.sh spawns
│   └── plan_store/            SQLModel schema (models.py) + sqlite session + CRUD
├── beamline_tools/            autonomy overlay on the shared CLI package:
│                              CAT-8 tools, agent roles, audited_call, steering CLI
├── simulation/                SPEC mock bootstrap (SPEC_MOCK=1 is the default)
├── scripts/
│   ├── beamtimehero           the CLI agents call (upstream parser + autonomy branches)
│   ├── start.sh / stop.sh     launch / kill FastAPI on :5005
│   └── *-claude.sh            per-role agent launchers (planner, collector, chat, …)
├── .claude/                   agent definitions, skills, prompts/base-layer.md
├── context/                   reference docs served via `beamtimehero ref <name>`
├── config/defaults.yaml       motor limits, gains, common elements
├── data/                      runtime sqlite DB, tool plots, phase reports
└── tests/                     pytest suite
```

The generic tool surface (CAT-0..7,9), SPEC file reading, log parsing, and
analysis live in the shared editable dependency
[`../beamtimehero_cli`](../beamtimehero_cli) (`pip install -e`).

## URLs (default port 5005)

| Path | What |
|------|------|
| `/` `/dashboard` | Live autonomy dashboard: phase tiles, agent output, plan, action tape, interventions, guidance, chat |
| `/config` | Experiment configuration form |
| `/phase?phase=<slug>` | Phase detail page |
| `/sample_holders` | Holder + sample editor with per-sample plan status |
| `/viewer` | SPEC data viewer |
| `/tools` | Tool catalog browser |
| `/health` | Liveness + agent/orchestrator/simulation status |
| `/api/chat` | POST — chat with the agent (reply arrives via `/ws` as `chat_reply`) |
| `/api/plan/*` | Steerable plan: add/remove/skip/reorder/update samples, end time, thresholds — every edit attributed + logged |
| `/ws` | WebSocket: chat replies/errors, steering + orchestrator events, interventions |

## Setup

```bash
# 1. Install Claude Code (the `claude` binary must be on PATH)

# 2. Copy env template
cp .env.example .env          # fill in LLM_GATEWAY creds, Slack tokens, etc.

# 3. Launch — creates venv, installs deps, inits DB, starts FastAPI on :5005
./scripts/start.sh
```

## Running without SPEC (dev / demo)

`SPEC_MOCK=1` (the default) routes all SPEC traffic to the in-process
simulator and seeds mock scan files + logs, so the full stack — phase
agents, plan machine, action_log, interventions, dashboard — runs on a dev
machine. Set `SPEC_MOCK=0` on the real beamline host.

## Tests

```bash
venv/bin/python -m pytest tests/ -q
```

## Slack behavior

- **Status updates + phase reports** posted to the chat channel from the orchestrator.
- **Steering channel**: every staff post becomes a steering row; the orchestrator routes it to a control agent and replies in-thread. A bare `stop` message is the STOP fast-path.
- **Chat channel + DMs**: each thread is a persistent chat session (`claude --resume` continuity); dashboard chat sessions are mirrored into Slack so staff can see and join them.
- **Interventions**: `!resume <id>` / `!deny <id>`, or resolve from the dashboard.

## Ports

Default is **5005**. The user-level rule forbids 5000 (macOS AirPlay
Receiver). Override via `PORT`.
