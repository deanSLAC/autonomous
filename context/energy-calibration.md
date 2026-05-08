
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


## Monochromator Energy calibration w/ Foil

- Foil scan over reference edge, find inflection point against the tabulated NIST edge (use unrounded values, e.g. Au K = 11918.7 eV, Cu K = 8979.0 eV, Fe K = 7112.0 eV, etc)
- mv energy to the tabulated edge value
- Edge scan: `run-motor-scan-relative --motor energy --start -15 --finish 15 --intervals 60 --count-time 0.2`.
- The experiment config should tell you what detector has the foil in front of it, if in doubt check I1 and I2.
- run calibrate_mono to set the measured position to the tabulated value
- Verify `absev` matches calibrated energy via `get-counts`
- Iterate the foil scan + calibration WITHOUT `reset_gap` until self-check < 0.3 eV from tabulated
- Self-check: finer edge scan, re-find inflection. Accept if within ~0.2 eV.
- Then single `reset_gap` at the end



