# Beamline Alignment Session — 2026-04-24

Claude (Opus 4.7) drove this alignment via screen-stuffing into the running spec session. Per-command log with timestamps and justifications: `/usr/local/projects/claude_spec_logs/alignment_2026-04-24.log`.

This doc is the "how to do it again" companion — what we did, why, what went wrong, and what to copy-paste next time.

---

## TL;DR — Phases at a glance

| Phase | What | Time | Key result |
|------:|------|------|------------|
| 1 | Move energy 5081 → 9000 eV (Cu K-edge work) | ~3 min | gap 8.10 mm, 5th harmonic, tracking shifted m1vert/Tz +0.76 mm |
| 2 | Optimize beam on I1 (vvv → hhh → m1 → m2 ×2 passes, then bzbz/bxbx) | ~50 min | I1/mA +2.6%; biggest wins: m2horz −342 μm, Bz −849 μm; anchor saved |
| 3 | Zero pinhole + measure beamsize | ~10 min | Sample stage origin = pinhole; FWHM **51 μm × 7 μm** (X × Z) |

Workflow per spec command throughout:
1. Append justification + timestamp to `/usr/local/projects/claude_spec_logs/alignment_2026-04-24.log`.
2. Stuff a `p "..."` into spec with **(a) the result of the previous step** and **(b) the idea/reason for the next step**, so an operator watching the spec session has the same context without reading the log. One or two lines, concise.
3. `screen -S spec -X stuff` the actual command.
4. Poll `screen -X hardcopy` until prompt returns.
5. Read result, decide next step.

---

## Phase 1 — Energy move 5081 → 9000 eV

**Why 9000 eV:** Cu K-edge is at 8979 eV; +21 eV above the edge gives stable post-edge fluorescence for sample finding and beamsize. Round number. Cleanly inside 5th-harmonic band (7683–10761 eV).

**The seven commands** (mirroring the relevant block of `align_the_beamline:147–234`):

1. `wm energy m2vert m2horz` — baseline. m2vert was 4.0, way off the Rh stripe.
2. `get_anchor` — anchor at 4966 eV (sane, recent).
3. `get_tracking` — confirmed `_TRACKING=0` (off).
4. `umv m2vert -3.5` — Rh stripe target for E>6200 eV. ~7.5 mm move, took ~10 s.
5. **Skipped** `umv m2horz 1.8` — current 1.99 was close enough, user opted not to nudge.
6. `tracking 1` — enable energy tracking.
7. `umv energy 9000` — pseudo-motor coordinates gap (auto-selected 5th harmonic, ~8.10 mm), crystal (~12.69° Bragg), and `_track()`-driven m1vert/Tz follow.

**Verification:** gap landed at 8.103 mm matching the 5th-harmonic polynomial fit. m1vert and Tz shifted uniformly +0.758 mm relative to anchor — within 2% of the hand-calculated 0.77 mm prediction (`2 × MONO_MIN_GAP_A × (cos θ_target − cos θ_anchor)`). No safety aborts.

---

## Phase 2 — Beam optimization on I1

**The non-obvious decision:** drove the full optics-iteration loop with `plotselect I1` from the start, skipping `align_the_beamline`'s I0-first safety pattern. User pointed out that I1 already had a clean signal (~192 kcps), so the macro's I0-first conservatism was unnecessary. I0 and I1 give equivalent info for alignment purposes; I1 is preferable when available because it's downstream and closer to the real experimental signal path.

**Skipped vs the macro:**
- `peak_mono_pitch` (and its `fsopen; fsoff` shutter workaround) — not reliable yet per user.
- Pre-loop setup (`fsopen` / `safely_remove_filters` / `mvknifewayout` / gain set) — I1 was already strong, trust the existing state.
- Diagnostic `dscan monvgap -.3 .3 20 .2` — no-action diagnostic, time saver.

**Per-step pattern:**
- Announce next step in spec via `p "..."` (so a watching operator can follow).
- Run scan (vvv / hhh / m1m1big / m1m1 / m2m2 / bzbz / bxbx).
- Apply macro's choice — `peak` for slits + mirrors (peak-shaped passbands), `cen` for fine m1 + B-stage (aperture plateaus).
- `ct 1` to confirm absolute counts. SPEAR-normalize (`I1/mA`) since ring current drifts.

**Results:**

| Pass | Step | Motor | Move | I1/mA |
|------|------|-------|------|-------|
| baseline | — | — | — | 386.8 |
| 1 | vvv → peak | monvtra | 0 | 386.8 |
| 1 | hhh → peak | monhtra | +60 μm | 387.4 |
| 1 | m1m1big → peak | m1vert | −59 μm | 388.1 |
| 1 | m1m1 → cen | m1vert | +150 μm | 387.4 |
| 1 | m2m2 → peak | m2horz | **−229 μm** | **393.7** |
| 2 | vvv → peak | monvtra | 0 | 394.0 |
| 2 | hhh → peak | monhtra | −60 μm | 396.1 |
| 2 | m1m1 → cen | m1vert | +2.7 μm | 395.7 |
| 2 | m2m2 → peak | m2horz | **−113 μm** | 397.0 |
| post | bzbz → cen | Bz | −849 μm | 397.1 |
| post | bxbx → cen | Bx | +45 μm | 396.9 |

Total: I1/mA **386.8 → 396.9 (+2.6%)**.

**Notable findings:**
- The big mover was **m2horz** (−342 μm net). The real optimum landed at 1.65, ~150 μm below the macro's nominal Si(111) Rh-stripe target of 1.8.
- Bz `cen` move was 849 μm but with no count gain — already inside the passband; cen just centered geometrically for better edge clearance. Useful for stability, not flux.
- Mono slits stayed at noise-level center across both passes. peak fit wandered ±60 μm from shot noise.
- m1m1 fine in pass 2 moved only 2.7 μm — m1 was converged.
- Pass 2 m2 moved half what pass 1 did (diminishing returns trajectory). Didn't pursue pass 3.

`set_anchor` between iteration loop and B-stage; `save_anchor` to disk at the end (`/usr/local/lib/spec.d/anchor.cfg`, with timestamped backup at `/usr/local/lib/spec.log/anchors/`).

---

## Phase 3 — Pinhole zero + beam size

Five commands:

1. `update_pinhole_pos(0, 0, 0)` — defensive zero of `pinhole_offset[]`.
2. `zero_pinhole` — found pinhole at Sx=−0.0275, Sz=+0.2585; rezeroed sample stage. Tz/Bz/Tx/Bx compensated by ∓Sz / ∓Sx so the beam stays physically still.
3. `mvknifeclear` — knives out (Sz lifted to 4.3).
4. `measure_beam_size 1 1` — fine X (Sx ±0.1 mm, 40 pts) + fine Z (Sz ±0.03 mm, 60 pts). `1, 1` because focused beam in both dims.
5. `wbeamsize` — read stored FWHMs.

**Result: X = 50.8 μm, Z = 7.08 μm FWHM.**

Sample-stage shifts from the rezero:
- Tz: 23.5147 → 23.7731 (+0.26)
- Bz: 15.1512 → 14.8909 (−0.26)
- Tx: ≈13.7626 → 13.7349 (−0.03)
- Bx: 13.3704 → 13.4000 (+0.03)

I1 stable through the rezero (~395 counts/mA). Confirms the beam was not lost in the coordinate change.

---

## Final state at end of session

- Energy: **9000 eV**, Si(111), 5th harmonic, gap 8.10 mm.
- absev = 9019.81 — about +20 eV from mono. Foil calibration + `reset_gap` is the next step (not done).
- Tracking on; anchor saved at 9000 eV.
- Sample-stage origin = pinhole.
- Filters off; vortex still **disabled** (re-enable when needed for science).
- Beam: 51 × 7 μm FWHM.

---

## Lessons learned

### Operational / harness

- **One spec command at a time** is hard-enforced. Back-to-back stuffs without polling for the prompt return get blocked, even when the user grants "execute the full plan without explicit approval". That permission waives *asking*, not *serialization*. Pattern that works:
  ```bash
  screen -S spec -X stuff 'cmd\n'
  sleep 2  # let the prompt advance off the previous command
  until screen -S spec -X hardcopy /tmp/spec_screen.txt && \
        tail -1 /tmp/spec_screen.txt | grep -qE 'SPEC[^_]*> *$'; do
      sleep 1
  done
  ```
- **Don't lock the poll regex to a specific prompt number.** Spec sometimes increments by 2 (compound macros, set_sim transitions, etc.). I burned a couple cycles when polling for `15958.SPEC>` while spec jumped from 15957 → 15959. Use the loose `SPEC[^_]*> *$` regex.
- **Long scans → background polling.** m1, m2, and measure_beam_size each take 2–5 minutes. Use `Bash` with `run_in_background: true` and then `TaskOutput` to wait, not the inline `timeout` parameter.
- **Screen hardcopy buffer is only ~30–40 lines.** Long scans scroll the early points off. `peak` / `cen` operate on the full `SCAN_D` array regardless, so trust them — but if you really need to see the data, `pl_MAX` / `SCAN_D[i][col]` reads can give you anything from the in-memory scan.
- **Disable noisy counters before alignment.** pp/zaber/adq pump-probe counters cluttered `ct 1` output to ~50 lines. The user ran `pp disable` early and that made every subsequent ct readable.
- **SPEAR-normalize all count comparisons** (`I1 / SPEAR_mA`). Ring current drifted ~5 mA over the session; raw I1 changes that look like real flux gain are often just ring drift.
- **Announcing in spec** (`p "..."`) is a **per-step requirement**, not just a phase-boundary nicety. Before each `stuff`ed command, `p` one or two lines covering (a) the result of the previous step and (b) the idea for the step about to run. A watching operator should be able to follow the reasoning from the spec terminal alone, without reading the alignment log.
- **Sign the announcement.** Start every per-step `p "..."` with `Claude: ` so the operator knows which entries in the spec scrollback came from the AI vs. the human user. Example: `p "Claude: vvv ran clean (peak at -3 um). Now hhh to fix horz."`

### About the macro vs reality

- The macro's `align_the_beamline` does an **I0-first then I1** sequence as a safety pattern for cases where I1 hasn't come up yet. **If I1 already has good signal, run the whole loop on I1 from the start.** I0 and I1 are equivalent for alignment purposes; I1 is preferable because it's downstream.
- `peak_mono_pitch` is currently **not reliable** — skip unless explicitly needed. Its companion `fsopen; fsoff` workaround (which exists only to recover from peak_mono_pitch's loopscan side effect of closing the shutter) can be skipped too.
- The diagnostic `dscan monvgap -.3 .3 20 .2` between iteration loop and B-stage is no-action — skip if pressed for time, run it if you want a recorded snapshot of the mono acceptance.
- **`valid_dscan` silently clamps both range and point count** when sub-motor limits would be hit. The reported `ascan` line that `peak`/`cen` prints (e.g. `ascan m1vert 0.979 3.379 20 0.2`) tells you the actual scan executed — check it if you suspect clamping.
- **`peak_mono_pitch` reads `S[I0]` directly** regardless of `plotselect`. Don't try to redirect it.
- **`set_anchor` is in-memory only**; `save_anchor` writes to disk (`anchor.cfg`). Do `save_anchor` once at the end of an alignment, not after each `set_anchor`.

### Decision-making during the loop

- **Use peak vs cen as the macro does.** Peak is for transmission peaks (slits, m2 reflection); cen is for aperture plateaus (m1 fine, B-stage). On a flat-topped plateau, peak hops noisily within the plateau; cen stably finds the geometric center.
- **Verify each step with `ct 1`.** Scan-local peak/cen tells you the scan *shape* converged, not whether you're actually gaining flux. A 1-second count after each step catches regressions immediately. Stop and investigate if counts drop step-over-step.
- **Convergence indicator: half-step pattern.** Pass 1 m2 = −229 μm, pass 2 m2 = −113 μm. When successive moves are roughly halving, you're converging on the optimum and pass 3 won't help — stop.
- **Big moves don't always mean count gain.** Bz cen moved 849 μm with no count change — we were already inside the aperture, just off-center. The move buys edge clearance / stability, not flux.
- **Real optimum can disagree with the macro's hardcoded targets.** m2horz settled at 1.65, vs the macro's 1.8 nominal. Don't be alarmed when peak/cen pulls a motor off the macro's "obvious" target — trust the data.

### What I'd do differently next time

- Run `pp disable` (or whatever's noisy) **before** the first `ct` so the baseline is clean.
- For the iteration loop: use `m1m1big` only in pass 1 (or only if pass-1 m1m1 fine showed an at-edge problem); skip it in pass 2 once we're known to be in the aperture. Saves ~2 min per pass.
- Consider skipping `dscan monvgap` always unless the user wants the snapshot.
- Establish baseline `ct 1`, then post-step `ct 1` after each `peak`/`cen` — log both raw counts AND I1/mA. The normalized number is what matters; the raw is what's seen on screen.

---

## Phases not done (next time, in order)

1. **Foil calibration** — `dscan energy -15 15 60 .2` over Cu K-edge with foil in I1 path; in PyMCA find inflection of d(I0/I1)/dE; `mv energy <inflection>`; `calibrate_mono <tabulated_8979>`; `reset_gap`.
2. **Camera crosshair** onto pinhole.
3. **Install analyzer crystals + bag.**
4. **Spectrometer alignment** — `xes_setup [Si|Ge] h k l row` then `xes_align "1234567" emiss_eV mono_eV cntSec vortDT`.
5. **`vortex enable`** when ready for science.

## Reference paths

- `/usr/local/lib/spec.d/beamline_align.mac` — the canonical macro this session manually walked through.
- `/usr/local/lib/spec.d/beam_diagnostics.mac` — vvv/hhh/m1m1/m2m2/bzbz/bxbx/zero_pinhole/measure_beam_size definitions.
- `/usr/local/lib/spec.d/energy.mac` — `energy` pseudo-motor and harmonic auto-selection.
- `/usr/local/lib/spec.d/tracking.mac` — `_track()`, `set_anchor`/`save_anchor`.
- `/usr/local/lib/spec.d/anchor.cfg` — current saved anchor (refreshed to 11918.7 eV after Session 2).
- `/usr/local/projects/claude_spec_logs/alignment_2026-04-24.log` — full per-command transcript with timestamps and justifications.
- `/usr/local/lib/spec.d/changing-energy.md` — generic energy-switch procedure (subset of `align_the_beamline`).

---

# Session 2 — Cu → Au energy switch (2026-04-24 afternoon)

Same harness, same workflow, deliberate **subset** of `align_the_beamline`
because the optics were already converged. Plan file:
`/home/dean/.claude/plans/read-the-notes-we-greedy-toast.md`. Per-command
log entries continued in the morning's
`alignment_2026-04-24.log` under a `SESSION 2` header.

## Phases at a glance

| Phase | What | Result |
|------:|------|--------|
| 1 | Pre-flight + state snapshot to `store-settings.txt` | snapshot 1 captured (motors, gains, anchor at Cu) |
| 2 | `umv energy 9100 → 11918.7` (auto 7th harmonic) | gap 8.17 → 7.79 mm; m1vert/Tz tracked +0.13 mm |
| 3 | Verified I1 with `ct 1` | I1/mA = 5.254 vs 5.255 baseline → vert touch-up SKIPPED |
| 4 | `measure_beam_size 0 0` (FIRST attempt, bad gains) | 91 × 82 µm — saturation artifact; flagged & redone |
| 5a | Au foil edge: scan #71 → 11919.08 eV | +0.38 eV vs tabulated 11918.7 (mono slightly high) |
| 5b | `set_i0_gain "50 nA/V"`; `set_i1_gain "1 mA/V"` | I1 saturation cleared |
| 5c | `mv energy 11919.08`; `calibrate_mono 11918.7` | NAO -164.066 → -164.074 |
| 5d | self-check scan #73: edge at 11918.23 (-0.47 eV) | reset_gap hysteresis; iterated |
| 5e | iter 2: `mv → calibrate_mono`, scan #74: 11918.87 (+0.17 eV) | accepted; canonical Au reference |
| 5f | `reset_gap` after convergence | gap encoder -0.001 mm |
| 6 | `measure_beam_size 0 0` (re-do with good gains) | 898 × 208 µm (matches morning 888 × 200) |
| 7 | `mvpinhole; zero_pinhole` | pinhole at OLD-frame Sx=-0.0825, Sz=0.622; stage retied |
| 8 | `set_anchor; save_anchor` | anchor refreshed to 11918.7 eV |

---

## Lessons learned (Session 2)

### `absev` vs the energy pseudo-motor are independent and BOTH must be calibrated

After `umv energy 11919` post-move, `ct 1` showed:
- `energy` (pseudo-motor) = 11919 eV (commanded value)
- `absev` (encoder readback used for **data analysis**) = 11928.5 eV (+9.5 eV off)

The discrepancy was the same +9.5 eV bias seen at Cu pre-cal that morning,
suggesting the energy motor's commanded value can land cleanly while the
encoder readback is biased.

**`absev` is the canonical value for downstream science** — it's what gets
written into scan files and what spectra are plotted against. A calibration
that brings the energy motor to the tabulated edge but leaves absev off is
**not done**. After `calibrate_mono`, both must read the calibrated energy
within ~0.2 eV.

Always run a final `ct 1` after calibration and verify `absev` = calibrated
energy. If absev is still off, the calibration is incomplete — either
iterate, or check whether a separate encoder-zero needs adjustment.

This applies to every energy calibration, not just Au — should also be
checked anywhere `calibrate_mono` is called.

### Set gains and `mvknifeclear` BEFORE any diagnostics

The morning's gain settings (I0 = 1 µA/V, I1 = 2 µA/V) had been tuned with
the sample-stage diagnostic ATTENUATING the upstream beam — i.e. with the
beam already partly blocked. In that state the readings looked sane: I1 =
2611 cps, I0 = 9150 cps.

When we ran `measure_beam_size 0 0` for the Au beam-size check, the macro
called `mvknifeclear` first. With the diagnostic out of the way for the
first time this session, full beam reached I1 — which immediately
saturated. The first beam-size scan returned a flat I1 = 1755 cps across
the entire knife range and a spurious 91 × 82 µm FWHM (the macro fitted a
20% gradual drop in I0 instead of an actual knife transition).

**The fix order matters:** every session should start with
1. `mvknifeclear` (clear sample-stage obstructions)
2. `set_i0_gain(...)` and `set_i1_gain(...)` to known-good values
3. `ct 1` to verify I0 and I1 land in 10³–10⁵ cps with full beam

…BEFORE any diagnostic that depends on those readings.

### `srs` macro is not loaded — use `set_iN_gain` helpers

`/usr/local/lib/spec.d/sr570.mac` defines a `srs N gain L` command but the
session running here doesn't load it (`p whatis("srs")` returned 0).
The active mechanism is `srs_set.mac`:

```spec
set_i0_gain("50 nA/V")     # align_the_beamline default for Si(111)
set_i1_gain("1 mA/V")      # align_the_beamline default for Si(111)
set_i2_gain("200 nA/V")    # I2 typically left alone
set_i0_offset("...")       # also available; values unset by default
```

The string argument must match `SRS_SENS_VAL` in `sr570.mac` exactly
(e.g. "50 nA/V" with the space and slash). The function calls
`epics_put` to write the value to a Local:BL15-2:iN:SensitivityString PV.

### Au K-edge tabulated value is 11918.7, not 11919

The user corrected me on this — NIST tabulates Au K at 11918.7 eV, not
the rounded 11919 that some references show. Always verify tabulated edge
values from a primary source for unfamiliar elements before
`calibrate_mono`. Cu K is 8979.0, Fe K is 7112.0, etc.

### `reset_gap` between calibrate_mono and self-check injects mono hysteresis

First-iteration sequence: `mv energy <inflection>`; `calibrate_mono <tab>`;
`reset_gap`; fine dscan; self-check.

The fine dscan landed -0.47 eV from tabulated — much worse than the
morning's -0.04 eV self-check at Cu. The cause was the gap motion in
`reset_gap` introducing ~0.5 eV mono backlash before the self-check.

**Rule:** iterate `mv energy → calibrate_mono → fine dscan → self-check`
WITHOUT `reset_gap` in the loop. Once self-check is acceptable, run
`reset_gap` ONCE at the end.

Iter 2 (without reset_gap) landed at +0.17 eV and was accepted.

### `python3` lacks numpy on this machine — use `python3.10` explicitly

`/usr/bin/python3` resolves to 3.11, which doesn't have numpy installed
in its dist-packages.  `/usr/bin/python3.10` does (numpy 2.1.3). The
`find_edge_position.py` script's `#!/usr/bin/env python3` shebang
therefore fails. Always invoke explicitly:

```bash
python3.10 /usr/local/lib/spec.d/find_edge_position.py <datafile> <scan> <use_I1>
```

### Anchor refresh ALWAYS after a multi-keV energy move

Morning's anchor stayed at 9000 eV (pre-cal Cu) by user choice — sensible
when staying within ~80 eV of the calibration. For a 3-keV jump across a
harmonic boundary, refreshing is the right call:

```spec
mvpinhole; zero_pinhole          # retie sample-stage origin first
set_anchor; save_anchor          # capture m1vert/Tz at the new energy
```

The pinhole zero before set_anchor matters — the anchor records absolute
m1vert/Tz values, and we want those tied to a known-good beam center at
the working energy.
