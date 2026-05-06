# Beamline Alignment — General Procedure & Lessons

Reference macro: `/usr/local/lib/spec.d/beamline_align.mac` (`align_the_beamline`).
Scan definitions: `/usr/local/lib/spec.d/beam_diagnostics.mac`.

---

## Overall flow

| Phase | What | Notes |
|------:|------|-------|
| 0 | Pre-flight | Snapshot motor positions (`store-settings.txt`), disable noisy counters (`pp disable`, `vortex disable`), `mvknifeclear`, set gains, verify I0/I1 with `ct 1` |
| 1 | Energy move | Set m2vert for correct stripe, enable tracking, `umv energy <target>` |
| 2 | Beam optimization on I1 | Iterative slit/mirror loop, then B-stage centering |
| 3 | Pinhole zero + beam size | Retie sample-stage origin, measure FWHM |
| 4 | Foil calibration (if needed) | Edge scan, `calibrate_mono`, self-check, `reset_gap` |
| 5 | Anchor set | `set_anchor` |

---

## Phase 0 — Pre-flight

1. **Snapshot** current motor positions to a store-settings file.
2. **`mvknifeclear`** — clear sample-stage obstructions so full beam reaches detectors.
3. **Set gains** with `set_i0_gain("...")` and `set_i1_gain(...)` to known-good values for the target energy and crystal. The `srs` macro may not be loaded; use the `set_iN_gain` helpers from `srs_set.mac`. String argument must match `SRS_SENS_VAL` exactly (e.g. `"50 nA/V"`).
4. **`ct 1`** — verify I0 and I1 land in 1e3-1e5 cps with full beam.
5. **`pp disable`** (or equivalent) to silence pump-probe / zaber / adq counters that slow down collection and arent in use.

Order matters: gains set AFTER knives are clear, because gain settings tuned with an obstruction in the beam will saturate once the obstruction is removed.

---

## Phase 1 — Energy move

Reference: `align_the_beamline` energy-change block and `/usr/local/lib/spec.d/energy.mac`.

1. `wm energy m2vert m2horz` — record baseline.
2. `get_anchor` — verify anchor energy is sane.
3. Set **m2vert** for the correct reflective stripe:
   - Rh stripe: m2vert ≈ −3.5 (for E > ~6200 eV).
   - Si stripe: m2vert ≈ +4.0 (for E < ~6200 eV).
4. `tracking 1` — enable energy tracking so m1vert/Tz follow the mono.
5. `umv energy <target>` — the pseudo-motor coordinates gap (auto-selects harmonic), crystal angle, and tracking-driven mirrors.

**Verification:** check gap against the expected harmonic polynomial, and confirm m1vert/Tz shifts are consistent with `2 × MONO_MIN_GAP_A × (cos θ_target − cos θ_anchor)`.

---

## Phase 2 — Beam optimization (iterative loop)

**Detector choice:** if I1 already has good signal (≥ ~100 kcps), run the entire loop on I1 via `plotselect I1` from the start. The macro's I0-first pattern is a safety net for cases where I1 hasn't come up; skip it when unnecessary. I1 is preferable because it's downstream and closer to the experimental signal path.

### Iteration loop (run 2 passes)

Each pass:

| Step | Scan | Motor | Apply |
|------|------|-------|-------|
| 1 | `vvv` | monvtra | `peak` |
| 2 | `hhh` | monhtra | `peak` |
| 3 | `m1m1big` (pass 1 only) | m1vert | `peak` |
| 4 | `m1m1` (fine) | m1vert | `cen` |
| 5 | `m2m2` | m2horz | `peak` |

After each step: `ct 1`, log both raw counts and I1/mA (SPEAR-normalized).

**Pass 2:** skip `m1m1big` — it's only needed in pass 1 to get into the aperture. If pass 2 moves are roughly half of pass 1 (convergence indicator), a third pass won't help.

### B-stage centering (after iteration loop)

| Step | Scan | Motor | Apply |
|------|------|-------|-------|
| 1 | `bzbz` | Bz | `cen` |
| 2 | `bxbx` | Bx | `cen` |

### peak vs cen

- **`peak`**: for transmission peaks (slits, m2 reflection) — peaked passband shape.
- **`cen`**: for aperture plateaus (m1 fine, B-stage) — flat-topped shape where peak hops noisily but cen finds stable geometric center.

### Interpreting results

- **SPEAR-normalize everything.** Ring current drifts during a session; raw count changes that look like flux gain may be ring drift. Always compare I1/mA.
- **Big motor moves ≠ count gain.** A large Bz cen move with no count change means you were already inside the aperture — the move buys edge clearance / stability, not flux.
- **Real optimum can disagree with macro's hardcoded targets.** Trust the data from peak/cen over the macro's nominal positions.
- **`valid_dscan` silently clamps** both range and point count when sub-motor limits would be hit. Check the reported `ascan` line to see what actually executed.

---

## Phase 3 — Pinhole zero + beam size

1. `update_pinhole_pos(0, 0, 0)` — defensive zero of `pinhole_offset[]`.
2. `zero_pinhole` — finds pinhole center, rezeroes sample stage. Tz/Bz/Tx/Bx compensate so the beam stays physically still.
3. `mvknifeclear` — knives out for beam-size measurement.
4. `measure_beam_size <focus_x> <focus_z>` — args are 1 for focused, 0 for unfocused in each dimension.
5. `wbeamsize` — read stored FWHMs.

Verify I1 is stable through the rezero — if counts change, the beam was lost in the coordinate change.

---

## Phase 4 — Foil calibration

Only needed when changing to an energy near an absorption edge, or when absev disagrees with the energy pseudo-motor by more than ~0.5 eV.

1. Insert reference foil in I1 path.
2. `dscan energy -15 15 60 .2` over the target edge.
3. Find inflection point: `python3.10 /usr/local/lib/spec.d/find_edge_position.py <datafile> <scan> <use_I1>` (must use `python3.10` explicitly — system `python3` lacks numpy).
4. * only if the value comes back with something reasonable <50 eV from tabulated * `mv energy <inflection_eV>`
5. `calibrate_mono <tabulated_eV>` — adjusts NAO offset.
6. **Self-check:** fine dscan over the edge, re-find inflection. Accept if within ~0.2 eV of tabulated.
7. If not converged, iterate steps 4–6 **without** `reset_gap` in the loop.
8. Once converged, run `reset_gap` **once** at the end.

**Critical:** `reset_gap` between `calibrate_mono` and the self-check scan injects ~0.5 eV of mono backlash. Always iterate the calibration loop without `reset_gap`, then run it once after convergence.

**`absev` and the energy pseudo-motor are independent.** After `calibrate_mono`, both must read the calibrated energy within ~0.2 eV. A final `ct 1` should confirm `absev` matches. If absev is still off, the calibration is incomplete.

### Common edge energies

Verify from a primary source (NIST) before calibrating — some references use rounded values.
- Cu K: 8979.0 eV
- Au K: 11918.7 eV (not 11919)
- Fe K: 7112.0 eV

---

## Phase 5 — Set anchor position

```spec
set_anchor          # stores current m1vert/Tz at working energy. Subsequent energy moves then make adjustments relative to this known good alignment. also writes to /usr/local/lib/spec.d/anchor.cfg with timestamped backup
```

Pinhole zero before `set_anchor` matters — the anchor should be tied to a known-good beam center at the working energy.

---

## Harness & automation lessons

### Spec command serialization

One command at a time. Back-to-back stuffs without polling for prompt return get blocked. Pattern:

```bash
screen -S spec -X stuff 'cmd\n'
sleep 2
until screen -S spec -X hardcopy /tmp/spec_screen.txt && \
      tail -1 /tmp/spec_screen.txt | grep -qE 'SPEC> *$'; do
    sleep 1
done
```

**Don't lock the poll regex to a specific prompt number.** Spec sometimes increments by 2 (compound macros, set_sim transitions). Use the loose `SPEC> *$` regex.

### Long scans

m1, m2, and `measure_beam_size` each take 2–5 minutes. Use `Bash` with `run_in_background: true` and `TaskOutput` to wait, not the inline `timeout` parameter.

### Screen hardcopy limitations

The hardcopy buffer is only ~30–40 lines. Long scans scroll early points off. `peak`/`cen` operate on the full `SCAN_D` array regardless — trust them. To inspect data directly, use `pl_MAX` / `SCAN_D[i][col]` reads.

### Announcing steps in spec

**Per-step requirement**, not just at phase boundaries. Before each stuffed command, `p "Claude: ..."` covering:
1. The result of the previous step.
2. The idea/reason for the next step.

A watching operator should be able to follow the reasoning from the spec terminal alone.

### Diagnostic dscan monvgap

The `dscan monvgap -.3 .3 20 .2` between the iteration loop and B-stage is a no-action diagnostic snapshot. Skip if pressed for time; run if you want a recorded view of the mono acceptance.

---

## Phases not covered here (post-alignment)

These follow alignment but are documented separately:

1. Camera crosshair onto pinhole.
2. Install analyzer crystals + bag.
3. Spectrometer alignment.
4. `vortex enable` when ready for spectrometer alignment.

---

## Reference paths

- `/usr/local/lib/spec.d/beamline_align.mac` — canonical alignment macro.
- `/usr/local/lib/spec.d/beam_diagnostics.mac` — scan definitions (vvv/hhh/m1m1/m2m2/bzbz/bxbx/zero_pinhole/measure_beam_size).
- `/usr/local/lib/spec.d/energy.mac` — energy pseudo-motor and harmonic auto-selection.
- `/usr/local/lib/spec.d/tracking.mac` — `_track()`, `set_anchor`/`save_anchor`.
- `/usr/local/lib/spec.d/anchor.cfg` — current saved anchor.
- `/usr/local/lib/spec.d/srs_set.mac` — `set_i0_gain` / `set_i1_gain` helpers.
- `/usr/local/lib/spec.d/find_edge_position.py` — edge inflection finder (invoke with `python3.10`).
- `/usr/local/lib/spec.d/changing-energy.md` — generic energy-switch procedure.
