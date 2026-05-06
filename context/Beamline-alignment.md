# Beamline Alignment — Procedure

For CLI usage, translation table, decision heuristics, and gotchas see `beamtimehero_context.md`.

Reference macro: `/usr/local/lib/spec.d/beamline_align.mac` (`align_the_beamline`).
Scan definitions: `/usr/local/lib/spec.d/beam_diagnostics.mac`.

---

## Overall flow

| Phase | What |
|------:|------|
| 0 | Pre-flight: snapshot positions, disable noisy counters, `mv-knife-out`, set gains, verify counts |
| 1 | Energy move: set m2vert for correct stripe, enable tracking, `mv-energy` |
| 2 | Beam optimization: iterative slit/mirror loop on I1, then B-stage centering |
| 3 | Pinhole zero + beam size |
| 4 | Foil calibration (if needed) |
| 5 | `set-anchor` |

---

## Phase 1 — Energy move

Reference: `/usr/local/lib/spec.d/energy.mac`.

1. Record baseline: read `energy`, `m2vert`, `m2horz`.
2. Set **m2vert** for the correct reflective stripe:
   - Rh stripe: m2vert ~ -3.5 (for E > ~6200 eV).
   - Si stripe: m2vert ~ +4.0 (for E < ~6200 eV).
3. `tracking --enabled true` — so m1vert/Tz follow the mono.
4. `mv-energy --energy-ev <target>`.

**Verification:** check gap against the expected harmonic polynomial, and confirm m1vert/Tz shifts are consistent with `2 * MONO_MIN_GAP_A * (cos theta_target - cos theta_anchor)`.

---

## Phase 2 — Beam optimization (iterative loop)

If I1 already has good signal (>= ~100 kcps), `plotselect I1` from the start — skip the macro's I0-first safety pattern.

### Iteration loop (run 2 passes)

| Step | Shortcut | Motor | Apply |
|------|----------|-------|-------|
| 1 | `vvv` | monvtra | `peak` |
| 2 | `hhh` | monhtra | `peak` |
| 3 | `m1m1big` (pass 1 only, if aperture clipping suspected) | m1vert | `peak` |
| 4 | `m1m1` (fine) | m1vert | `cen` |
| 5 | `m2m2` | m2horz | `peak` |

After each step: `get-counts`, compare I1/mA to baseline.

**Pass 2:** skip `m1m1big` — only needed in pass 1 to get into the aperture.

### B-stage centering (after iteration loop)

| Step | Shortcut | Motor | Apply |
|------|----------|-------|-------|
| 1 | `bzbz` | Bz | `cen` |
| 2 | `bxbx` | Bx | `cen` |

### Optional: diagnostic dscan monvgap

`run-motor-scan-relative --motor monvgap --start -0.3 --finish 0.3 --intervals 20 --count-time 0.2` between the iteration loop and B-stage is a no-action snapshot of mono acceptance. Skip if pressed for time.

---

## Phase 3 — Pinhole zero + beam size

1. `mv-pinhole` — move pinhole into beam at sample position.
2. `zero-pinhole` — finds pinhole center, rezeroes sample stage. Tz/Bz/Tx/Bx compensate by equal-and-opposite amounts so the beam stays physically still.
3. `mv-knife-clear` — knives out for beam-size measurement.
4. `measure-beam-size` — `--small-x` / `--small-z` true for focused, false for unfocused.

Verify I1 is stable through the rezero — if counts change, the beam was lost in the coordinate change.

---

## Phase 4 — Foil calibration

Only needed when changing to an energy near an absorption edge, or when absev disagrees with the energy pseudo-motor by more than ~0.5 eV. See `beamtimehero_context.md` "Energy calibration" for the iteration protocol and gotchas.

1. Insert reference foil in I1 path.
2. Edge scan: `run-motor-scan-relative --motor energy --start -15 --finish 15 --intervals 60 --count-time 0.2`.
3. Find inflection with `calibrate-mono-from-foil-scan --tabulated-edge-ev <NIST_value>`.
4. Self-check: finer edge scan, re-find inflection. Accept if within ~0.2 eV.
5. Iterate steps 2–4 **without** `reset-gap`.
6. Once converged, `reset-gap` **once** at the end.

---

## Phase 5 — Set anchor

`set-anchor` stores current m1vert/Tz at the working energy and writes to `/usr/local/lib/spec.d/anchor.cfg` with a timestamped backup. Subsequent energy moves with tracking use this as the reference pivot.

Pinhole zero before `set-anchor` matters — the anchor should be tied to a known-good beam center at the working energy.

---

## Post-alignment phases (documented separately)

1. Camera crosshair onto pinhole.
2. Install analyzer crystals + bag.
3. Spectrometer alignment (`xes_setup` / `xes_align`).
4. `vortex enable` when ready for spectrometer alignment.

---

## Reference paths

- `/usr/local/lib/spec.d/beamline_align.mac` — canonical alignment macro.
- `/usr/local/lib/spec.d/beam_diagnostics.mac` — scan definitions (vvv/hhh/m1m1/m2m2/bzbz/bxbx/zero_pinhole/measure_beam_size).
- `/usr/local/lib/spec.d/energy.mac` — energy pseudo-motor and harmonic auto-selection.
- `/usr/local/lib/spec.d/tracking.mac` — `_track()`, `set_anchor`/`save_anchor`.
- `/usr/local/lib/spec.d/anchor.cfg` — current saved anchor.
