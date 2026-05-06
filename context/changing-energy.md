# Changing energy at BL15-2 — minimal subset of `align_the_beamline`

When the beamline is already aligned and you only need to move from one
edge to another (Cu → Au, Fe → Cu, etc.), most of `align_the_beamline`'s
work is unnecessary. This note records the **minimum useful subset** so
future energy switches don't repeat the full alignment.

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

## Energy calibration with reference foil

Au foil (or whichever element) at I2 is the standard. Manual step-through:

```spec
plotselect I0                              # plot upstream flux during scan
umv energy <tabulated_edge>                # park at expected edge
dscan energy -15 15 60 0.2                 # coarse pre-cal scan
p SCAN_N                                   # record scan number
```
use the CLI tools to plot I0/I2, find the peak of the derivative.

`use_I1=0` (3rd arg) selects I2 as transmission detector. Use `1` if the
foil is in front of I1 instead.

Report measured edge, tabulated value. If the calibration is measured to be off by 50 eV this is an emergency and you need to stop.

```spec
mv energy <measured_inflection>
calibrate_mono <tabulated_edge>            # updates motor position and encoder-derived value
dscan energy -15 15 80 0.2                 # post-cal fine reference scan
```

**absev vs the energy motor:** both must converge to the tabulated
value. `absev` (encoder readback used for data analysis) is the canonical
value for downstream science. After `calibrate_mono` and before declaring
done, `ct 1` should show `absev` essentially equal to the calibrated
energy. If absev is ~10 eV off but the energy motor reads correctly,
the calibration is incomplete.

**Tabulated edge values:** use NIST values, not rounded ones. E.g.
- Au K = **11918.7** eV  (NOT 11919)
- Cu K = **8979.0** eV
Verify against a primary source for unfamiliar elements.

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
set_anchor                 # capture m1vert1/2, Tz1/2, energy
                           # plus a timestamped backup under
                           # /usr/local/lib/spec.log/anchors/
get_anchor                 # verify
```