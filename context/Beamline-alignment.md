# Beamline Alignment — Procedure

This document is intended for the alignment of the upstream components of the beamline.

While spec does have a align_the_beamline script on which this guide is based, it is susceptible to tiny quirks here and there which have affected its reliable performance. The hope is that with you following the general recipe, but applying greater flexibility and reviewing the step by step results as you go, we can get a better result.

---

## Overall flow

| Phase | What |
|------:|------|
| 0 | Pre-flight: snapshot positions, `mv_knife_out`, set gains, verify counts |
| 1 | Energy move: set m2vert for correct stripe, set mirror bends, enable tracking, `mv-energy` |
| 2 | Beam optimization: iterative slit/mirror loop on I1, then B-stage centering |
| 3 | Pinhole zero + beam size |
| 4 | Energy calibration w/ foil |
| 5 | `set-anchor` |

---

## Phase 0 — Pre-flight
1. run read_all_positions
2. mv_knife_out moves the diagnostic tool out of the beam path so I1 sees the beam signal
3. set_gain, i0 50 nA/V, i1 1 mA/V
4. safely_remove_filters; get_counts as a starting reference point

---

## Phase 1 — Energy move

1. Record baseline: read `energy`, `m2vert`, `m2horz`.
2. `tracking --enabled true` — so m1vert/Tz follow the mono. (assuming we want the mirrors in)
3. `mv-energy --energy-ev <target>`.
4. smallbeam looks like: 
mv m1ubend 8.41 m1dbend .39 m2ubend 15 m2dbend -4.7
big beam looks like:
mv m1ubend 10 m1dbend 8 m2ubend 24 m2dbend 32
check our current bend values. if experiment config says we're supposed to have a big beam but we're much closer to small beam values, then run bigbeam (and vice versa). if we are close to these values and the mode matches, do not issue the bigbeam/smallbeam command.
5. Set **m2vert** for the correct reflective stripe: m2_stripe <eV>  
   Then get the m2vert position. expected:
   - Rh stripe: m2vert ~ -3.5 (for E > ~6200 eV).
   - Si stripe: m2vert ~ >4.0 (for E < ~6200 eV).

**Verification:** check gap against the expected harmonic polynomial, and confirm m1vert/Tz shifts are consistent with `2 * MONO_MIN_GAP_A * (cos theta_target - cos theta_anchor)`.

---

## Phase 2 — Beam optimization (iterative loop)

If I1 already has good signal (>= ~20 kcps), `plotselect I1` from the start — skip the macro's I0-first safety pattern.

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

NOTE: if abs(monvtra) > .25 after these steps on I0 and I1, our source beam is not being delivered correctly. Raise human attention via post_status_update. But it is ok to proceed in the meantime. 


### peak_mono_pitch
Be sure to check counts before and after. Sometimes this one fails if the signal is noisy. You might have to run it a second time.
If a second time still doesnt recover counts, its time to HALT and get staff attention.

### B-stage centering (after iteration loop)

| Step | Shortcut | Motor | Apply |
|------|----------|-------|-------|
| 1 | `bzbz` | Bz | `cen` |
| 2 | `bxbx` | Bx | `cen` |

### Optional: diagnostic dscan monvgap

`run-motor-scan-relative --motor monvgap --start -0.3 --finish 0.3 --intervals 20 --count-time 0.2` between the iteration loop and B-stage is a no-action snapshot of mono acceptance.

---

## Phase 3 — Pinhole zero + beam size

1. `mv-pinhole` — move pinhole into beam at sample position.
2. `zero-pinhole` — finds pinhole center, rezeroes sample stage. Tz/Bz/Tx/Bx compensate by equal-and-opposite amounts so the beam stays physically still.
3. `mv-knife-clear` — knives out for beam-size measurement.
4. `measure-beam-size` — `--small-x` / `--small-z` true for focused, false for unfocused.

Verify I1 is stable through the rezero — if counts change, the beam was lost in the coordinate change.

---

## Phase 4 — Monochromator Energy calibration w/ Foil

see energy calibration ref tool

---

## Phase 5 — Set anchor

`set-anchor` stores current m1vert/Tz at the working energy and writes to `/usr/local/lib/spec.d/anchor.cfg` with a timestamped backup. Subsequent energy moves with tracking use this as the reference pivot.

Pinhole zero before `set-anchor` matters — the anchor should be tied to a known-good beam center at the working energy.

---

## Reference docs
Consult reference docs BEFORE attempting unfamiliar procedures:

- `beamtimehero ref --list` -- see all available docs
- `beamtimehero ref changing-energy` -- full step-by-step energy switch procedure
- `beamtimehero ref calibrate-energy` -- calibrate the monochromator with a foil
