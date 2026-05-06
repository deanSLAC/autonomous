# Changing energy at BL15-2 — minimal subset of `align_the_beamline`

When the beamline is already aligned and you only need to move from one
edge to another (Cu → Au, Fe → Cu, etc.), most of `align_the_beamline`'s
work is unnecessary. This note records the **minimum useful subset** so
future energy switches don't repeat the full alignment.

Companion docs:
- `/usr/local/lib/spec.d/CLAUDE.md` — top-level macro index
- `claude_notes/BL15-2_alignment_reference.md` — full alignment workflow
- `Beamline-alignment.md` — session writeups (Cu align, Cu→Au switch)

(Lives at the spec.d top level for now because dean lacks write perms in
`claude_notes/`. Move it under `claude_notes/` when convenient.)

---

## Pre-flight (always do these — most issues stem from skipping them)

1. `pwd` / `unix("pwd")` — confirm SPEC's cwd matches the beamtime data dir.
2. `p DATAFILE` — confirm the active datafile is `alignment` (or `newfile alignment`).
3. **`mvknifeclear`** — get the sample-stage diagnostic / sample holder out
   of the beam path **before measuring anything**. If you skip this and
   the holder happens to attenuate the beam, every subsequent gain check
   and beam-size measurement will lie. (Lesson learned the hard way on
   2026-04-24 Cu→Au.)
4. **Set / verify SR570 gains** for the new energy regime. From
   `srs_set.mac`:
   ```spec
   set_i0_gain("50 nA/V")     # align_the_beamline default for Si(111)
   set_i1_gain("1 mA/V")      # align_the_beamline default for Si(111)
   # I2 gain typically left alone unless the foil is changed.
   ```
   The string format must match `SRS_SENS_VAL` in `sr570.mac` ("50 nA/V",
   "1 mA/V", "200 nA/V", etc.). Note that the older `srs N gain L`
   command is **not loaded** in the running session — use the
   `set_iN_gain` helpers.
5. `ct 1` — verify gains are sane: I0 and I1 should land in 10³–10⁵ cps
   range. If a counter looks pegged or flat across an obvious knife-edge
   scan, gain is wrong.
6. `pp disable` if there's pump-probe noise in `ct`.
7. Append a session-header block to `/usr/local/projects/claude_spec_logs/alignment_<date>.log`.

---

## The energy move

```spec
get_anchor              # confirm anchor is reasonable — should be at the
                        # last-calibrated energy
get_tracking            # check
tracking 1              # idempotent ensure
plotselect I1           # working signal for optimization
umv energy <new_eV>     # auto-selects harmonic; tracking moves m1vert/Tz
wm energy gap crystal m1vert Tz
ct 1                    # verify I1 alive
```

**Halt condition:** if `ct 1` shows I1 with no counts at the new energy,
STOP. Do not run any optimization scans on a dead signal — investigate
(filter still in? shutter closed? wrong harmonic? mono pitch grossly
off after a harmonic-band crossing?).

If I1 is only mildly suppressed (within ~30% of energy-scaled baseline),
skip vertical touch-up. Otherwise run the **vertical-only** subset:

```spec
vvv  ; peak       # mono vertical slit translation
m1m1 ; cen        # m1vert fine, aperture plateau → cen
bzbz ; cen        # B-stage vertical
ct 1              # confirm no regression
```

**Skip everything horizontal** (`hhh`, `m2m2`, `bxbx`) for an energy-only
move. Horizontal beam position barely changes with energy.

**Skip `peak_mono_pitch`** — currently unreliable per feedback memory.

**Skip `m1m1big`** unless you have specific evidence the beam clipped the
m1 aperture during the energy move.

---

## Beam size re-measurement

The bender focal length depends on grazing angle, so beam size shifts
slightly with energy. Re-measure if it matters for the science:

```spec
mvknifeclear
measure_beam_size 0 0      # big-beam mode (matches the LiSA bender set)
wbeamsize
```

**Mode selection — `0 0` vs `1 1`:** big mode (`0 0`) for the standard
LiSA big-beam benders (m1ubend=10/m1dbend=5.5/m2ubend=24/m2dbend=32);
fine mode (`1 1`) only for tightly-focused beams (~50 µm). Using the
wrong mode produces artifacts (fine mode on a big beam yields a flat
ramp; the readme.txt has examples).

**Saturation check:** during the Z-scan the I1 column should drop ~90%
when the knife crosses the beam. If I1 stays flat, gain is too high
(saturation) — go back to step 4 of pre-flight and reduce I1 amplification
(e.g. `set_i1_gain("1 mA/V")` from a 2 µA/V starting point is a 500x
reduction).

---

## Energy calibration with reference foil

Au foil (or whichever element) at I2 is the standard. Manual step-through
keeps the user-confirm gate before the irreversible `calibrate_mono`:

```spec
plotselect I0                              # plot upstream flux during scan
umv energy <tabulated_edge>                # park at expected edge
dscan energy -15 15 60 0.2                 # coarse pre-cal scan
p SCAN_N                                   # record scan number
```

Then off-line:
```bash
python3.10 /usr/local/lib/spec.d/find_edge_position.py \
    <datafile> <scan_n> 0
```
Use `python3.10` explicitly — the system `python3` is 3.11 and lacks
numpy; `python3.10` has numpy 2.1.3 in dist-packages.

`use_I1=0` (3rd arg) selects I2 as transmission detector. Use `1` if the
foil is in front of I1 instead.

**PAUSE** — report measured edge, tabulated value, and discrepancy to
the user. Wait for explicit go-ahead before `calibrate_mono`. The
macro's built-in 10 eV abort threshold is the right one (per memory
update 2026-04-24); a smaller imposed threshold should not be applied
unprompted.

After user confirms:
```spec
mv energy <measured_inflection>
calibrate_mono <tabulated_edge>            # rewrites theta-encoder NAO
dscan energy -15 15 80 0.2                 # post-cal fine reference scan
```

**Re-run `find_edge_position.py` on the post-cal scan as a self-check.**
A converged calibration lands within ~0.1 eV of tabulated. If the
self-check is more than ~0.5 eV off, the cause is usually
gap-motion hysteresis from a `reset_gap` call between calibrate and
self-check — iterate one more time WITHOUT another `reset_gap` until
self-check is acceptable, then run a single `reset_gap` at the end.

**absev vs the energy motor:** both must converge to the tabulated
value. `absev` (encoder readback used for data analysis) is the canonical
value for downstream science. After `calibrate_mono` and before declaring
done, `ct 1` should show `absev` essentially equal to the calibrated
energy. If absev is ~10 eV off but the energy motor reads correctly,
the calibration is incomplete — see the morning Cu session in
Beamline-alignment.md for an example of this exact failure.

**Tabulated edge values:** use NIST values, not rounded ones. E.g.
- Au K = **11918.7** eV  (NOT 11919)
- Cu K = **8979.0** eV
Verify against the user / a primary source for unfamiliar elements.

Final `reset_gap` after calibration converges:
```spec
reset_gap                  # re-syncs gap encoder with the new mono cal
```

---

## Pinhole re-zero (always after a multi-keV move)

The pinhole is the most accurate physical fiducial for beam center.
After a big energy move, retie the sample-stage origin to a fresh
pinhole find:

```spec
wsamp                      # capture current sample-of-interest position
                           # (record to store-settings.txt before zeroing!)
mvpinhole                  # move stage to pinhole
zero_pinhole               # find pinhole, zero stage, table-compensate
                           # to keep beam fixed in lab frame
wsamp                      # confirm
```

`zero_pinhole` prints the OLD-frame pinhole coords (e.g. "Sz: 0.622,
Sx: -0.0825"). To convert any OLD-frame coord to NEW-frame:
```
new_Sx = old_Sx - old_pinhole_Sx        (e.g.  old_Sx + 0.0825)
new_Sz = old_Sz - old_pinhole_Sz        (e.g.  old_Sz - 0.622)
Sy and Sr are unaffected.
```

Skip the actual sample restore if you're going to mount a different
holder anyway — leave the stage at `mvknifeclear` so the next person
isn't fighting an obstructed beam.

---

## Anchor refresh

```spec
set_anchor                 # in-memory: capture m1vert1/2, Tz1/2, energy
save_anchor                # write to /usr/local/lib/spec.d/anchor.cfg
                           # plus a timestamped backup under
                           # /usr/local/lib/spec.log/anchors/
get_anchor                 # verify
```

Always refresh after a multi-keV move. The morning's "skip anchor
refresh after Cu cal" decision was reasonable for staying at one edge,
but for any meaningful energy change the anchor must be at a sensible
distance from the working energy or `_track()` will overshoot when the
next energy scan goes back the other direction.

---

## Documentation deliverables

Per the standard pattern:
- `<beamtime_dir>/store-settings.txt` — pre and post snapshots of motors,
  gains, energy, anchor.
- `<beamtime_dir>/readme.txt` — append a calibration block in the same
  shape as the morning Cu block (tabulated, foil geometry, pre/post
  numbers, scan numbers, notes).
- `/usr/local/projects/claude_spec_logs/alignment_<date>.log` — per-step
  command + justification + result entries throughout.
- `Beamline-alignment.md` — session-level writeup with
  lessons learned.
- This file (`changing-energy.md`) — keep updated with new lessons
  every time we run an energy switch.

---

## Common gotchas (running tally)

- **Gain saturation when the beam-blocker comes out of the way.**
  Sample-stage holder may attenuate the beam; if it does, the morning's
  ct readings reflect attenuated signal. Once you `mvknifeclear` (or the
  user mounts a different holder), I1 will jump and likely saturate.
  Always set gains and `mvknifeclear` BEFORE diagnostics.
- to set I0, I1, I2 gains, `set_iN_gain` from `srs_set.mac`.
- **`python3` lacks numpy on this machine; use `python3.10`.**
- **`reset_gap` injects ~0.5 eV mono hysteresis** — don't put it
  between `calibrate_mono` and the self-check scan. Iterate the cal
  without `reset_gap`, then run `reset_gap` once at the end.
- **`measure_beam_size 1 1` (fine mode)** is wrong for big-beam benders;
  it produces 2-3 µm artifact FWHMs. Use `0 0` if we have enlarged the beam by moving to more positive ??bend motor values (eg m1ubend, m2dbend)
- **Au K = 11918.7 eV, not 11919.** Same care for other elements.
- **`absev` is what data analysis uses** — verify both `absev` and the
  energy pseudo-motor reach the tabulated edge after calibration. Don't
  declare done with absev still off.
