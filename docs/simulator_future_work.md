# Simulator — future work

Picked up from the original `simulator_improvement_plan.md` after the
short-term UX + startup fixes landed. These are not scheduled — they
are notes for when we want richer simulator behaviour than the current
one-line mock-macro responses.

## Richer macro-level scan traces from the mocked SPEC layer

Today `align_the_beamline`, `run_spec_align`, `auto_sample_align`, and
`run_collection` return a single canned success string. That is enough
to let the agent advance between phases, which is all we need right
now — but the phase-detail pages stay empty even after a successful
macro call, and the dashboard doesn't "move" the way it would on a
real beamline.

When we want the simulator to look like a real run:

- **`align_the_beamline`**: before returning, append a sequence of
  `m1m1`, `m1vert`, `m2horz` alias scans with plausible convergence
  (decreasing FWHM, centering on the anchor).
- **`run_spec_align`**: append a per-crystal peak scan for each
  crystal in the experiment config.
- **`auto_sample_align`**: append an Sz survey + per-sample Sx/Sy
  centering scans.
- **`run_collection`**: append XAS/RIXS scans per sample per rep and
  sleep briefly between reps so the UI moves.

Files that would change:
[server/spec/screen_client.py](../server/spec/screen_client.py),
[simulation/engine.py](../simulation/engine.py).

## Explicitly out of scope

These were considered and deferred as too complicated / not worth the
test surface they'd create:

- **Fault injection** (`SIM_FAULTS=beam_drop,bad_gain,...`). Would let
  us exercise the agent's error paths, but the simulator is not the
  right place to validate error handling — real-world faults don't
  look like staged ones.
- **Deterministic seeds + smoke script** (`SIM_SEED`, `sim_smoke.py`).
  Not useful until we have CI that runs it and a failure it catches
  that we can't catch faster another way.
- **Non-LLM scripted driver**. Rejected: if opencode isn't running,
  the right fix is to make the startup script reliable, not to route
  around the LLM. The unified `scripts/start.sh` now does that.
