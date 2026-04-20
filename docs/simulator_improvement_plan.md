# Simulator improvement plan

Status: **landed.** This file is kept as a post-mortem of the "Start did
nothing" bug and the fixes that went in with it. Follow-up simulator
work that was *not* done here lives in
[simulator_future_work.md](simulator_future_work.md).

## Why "Start" did nothing

1. `POST /api/orchestrator/start` returned **503 "orchestrator not
   initialized"** because the `Orchestrator` singleton is only created
   in [server/app.py](../server/app.py) *if* `ConversationService` was
   created, which itself only happened when the local opencode server
   (`127.0.0.1:4096`) passed a health check at startup. If opencode
   was not ready when FastAPI booted, the orchestrator stayed `None`
   forever and every Start click 503'd.
2. The dashboard swallowed the failure silently:
   `autonomyAction('start')` called `r.json()` without checking
   `r.ok`, logged to `console.error`, and called `refreshAutonomy()`.
   Net effect for the user: a clicked button and no visible change.
3. There was **no UI surface** for "agent backend offline". `/health`
   reported FastAPI status only; the server dot went green and the
   user reasonably assumed the app was healthy.

## What was done

### 1 — Make the startup script reliable (root cause)

The original `scripts/start.sh` launched opencode, waited `sleep 2`,
and then started FastAPI. On any machine where opencode took longer
than 2s to bind its socket, FastAPI's lifespan ran before opencode
was reachable, and the orchestrator was `None` for the life of the
process.

`scripts/start.sh` now:

- Fails hard (exit 2) when `SLAC_API_KEY` or the opencode binary is
  missing instead of silently continuing with the agent disabled.
- Detects an already-running opencode on `:4096` and reuses it.
- Otherwise launches opencode and polls `http://127.0.0.1:4096/session`
  until it returns 200, up to 30 seconds, before starting FastAPI.
- Cleans up the opencode child process on shell exit.

`scripts/stop.sh` (new) kills whatever is listening on `:5005`
(FastAPI) and `:4096` (opencode) by PID, with a SIGTERM → SIGKILL
fallback. Idempotent; safe to run even if nothing is up.

### 2 — Surface agent-backend health in the UI (defence in depth)

Even with a reliable startup, opencode can still crash or be killed
mid-run. The dashboard now reflects this:

- `/health` returns `opencode_reachable`, `orchestrator_initialized`,
  `simulation`, `bl_scan_dir`. The `opencode_reachable` field is a
  live probe, not startup state.
- `/api/orchestrator/status` includes a live `agent_reachable` field
  (same probe), so the existing autonomy poll picks up mid-run
  failures without needing a second fetch.
- The dashboard's **Agent online/offline** pill is driven by
  `agent_reachable`, so it goes red if opencode dies even after a
  successful start. That's the "why would we trust this pill" answer:
  it's not cached startup state — every poll re-probes opencode.
- The Start button is disabled with an explanatory tooltip when
  `agent_reachable` is false.
- `POST /api/orchestrator/start` 503 body now names the launch script
  explicitly; the dashboard surfaces it as an alert instead of a
  silent `console.error`.

### Not done

- **No scripted no-LLM driver.** The agent needs to be running; the
  fix is a reliable startup, not a fallback path that masks the
  problem.
- **No `/health` expansion for simulator internals** beyond what's
  above. The `sim-pill` already indicates simulation mode; a click-to-
  expand panel was judged low value.
- **Richer mock macros, fault injection, deterministic seeds** —
  moved to [simulator_future_work.md](simulator_future_work.md).

## Files touched

- [scripts/start.sh](../scripts/start.sh) — active wait for opencode
- [scripts/stop.sh](../scripts/stop.sh) — new
- [server/app.py](../server/app.py) — expanded `/health`
- [server/ui/orchestrator_api.py](../server/ui/orchestrator_api.py) —
  descriptive 503; `agent_reachable` in `/status`
- [static/dashboard/autonomy.js](../static/dashboard/autonomy.js) —
  alert on start failure; live-probe-driven pill + Start gate
- [static/dashboard/index.html](../static/dashboard/index.html) — pill
  markup
