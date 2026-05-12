---
name: changing-energy
description: Minimal procedure for switching between absorption edges without full beamline alignment
---

# Changing energy at BL15-2 — minimal subset of `align_the_beamline`

When the beamline is already aligned and the new experiment only requires that you move from one
edge to another (Cu → Au, Fe → Cu, etc.), most of `align_the_beamline`'s
work is unnecessary. This note records the **minimum useful subset** so
future energy switches don't repeat the full alignment.

But note to be extra clear: this should be thought of as a "easy beamline alignment". If you are doing an experiment where you have two elements set up simultaneously in advance, you can just select_element to get between them, you do not need to do this alignment process.


quick summary

1. `spec-write plotselect --counter I0` -- working signal for optimization
2. `spec-write mv-energy --energy-ev <target>` -- auto-selects harmonic
3. `spec-read get-counts --count-time 1` -- Tread carefully if I0 is dead (zero counts = stop and investigate)
4. If I0 suppressed >70% from baseline: run vertical touch-up:
   - `run-align-shortcut m1m1` then `post-scan-move cen`
   - `run-align-shortcut vvv` then `post-scan-move peak`.  This should not change with an energy move.
   - `run-align-shortcut bzbz` then `post-scan-move cen`
   - `get-counts` to confirm no regression
5. Horizontal optics (hhh, m2m2, bxbx) should not change much after energy moves, but you should verify them anyway.
6. `peak-mono-pitch` -- Occasionally this fails and needs to be repeated a second time. Pay close attention to counts before and after,there should not be dramatic changes.


---

## Pre-flight (always do these — most issues stem from skipping them)

1. `pwd` / `unix("pwd")` — confirm SPEC's cwd matches the beamtime data dir.
2. `p DATAFILE` — confirm the active datafile is `alignment` (or `newfile alignment`).
3. **`mvknifeclear`** — get the sample-stage diagnostic / sample holder out
   of the beam path **before measuring anything**. If you skip this and
   the holder happens to attenuate the beam, every subsequent gain check
   and beam-size measurement will lie. 
4. **Set / verify SR570 gains** for the new energy regime. start with the defaults "50 nA/V" for I0, "1 mA/V" for I1. 
But measure the counts we get and scale them appropriately as needed. Ideal I0: 6000-50000 cps, I1 1e4 to 5e5 cps.

---

## The energy move

```spec
get_anchor              # confirm anchor is reasonable — should be at the
                        # last-calibrated energy
get_tracking            # check that the existing values are reasonable. If it wasnt set well before we dont want to activate it now.
tracking 1              # idempotent ensure
plotselect I1           # working signal for optimization
umv energy <new_eV>     # auto-selects harmonic; tracking moves m1vert/Tz
wm energy gap crystal m1vert Tz
ct 1                    # verify I1, I0 alive
```

**Halt condition:** if `ct 1` shows I1 and I0 with no counts at the new energy,
Tread carefully.  (filter still in? shutter closed? ). Stop if you're totally lost.

```spec
vvv  ; peak       # mono vertical slit translation
m1m1 ; cen        # m1vert fine, aperture plateau → cen
bzbz ; cen        # B-stage vertical
ct 1              # confirm no regression
```

**Skip everything horizontal** (`hhh`, `m2m2`, `bxbx`) for an energy-only
move when we were optimized at the previous energy. Horizontal beam position barely changes with energy.

**Skip `m1m1big`** unless you have specific evidence the beam clipped the
m1 aperture during the energy move.

---

## Beam size re-measurement

The bender focal length depends on grazing angle, so beam size shifts
slightly with energy. Re-measure if it matters for the science:

```spec
mvknifeclear
measure_beam_size 0 0 
wbeamsize
```

**Mode selection — `0 0` vs `1 1`:** big mode (`0 0`) for the standard
big-beam benders (m1ubend=10/m1dbend=5.5/m2ubend=24/m2dbend=32);
fine mode (`1 1`) only for tightly-focused beams (<50 µm). Using the
wrong mode produces artifacts (fine mode on a big beam yields a flat
ramp; the readme.txt has examples).

**Saturation check:** during the Z-scan the I1 column should drop ~90%
when the knife crosses the beam. If I1 stays flat, gain is too high
(saturation) — go back to step 4 of pre-flight and reduce I1 amplification
(e.g. `set_i1_gain("1 mA/V")` from a 2 µA/V starting point is a 500x
reduction).


---
## Energy calibration

see energy calibration ref tool

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


---

## Anchor refresh

```spec
set_anchor                 # capture m1vert1/2, Tz1/2, energy
                           # plus a timestamped backup under
                           # /usr/local/lib/spec.log/anchors/
get_anchor                 # verify
```
