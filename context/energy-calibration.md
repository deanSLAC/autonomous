
---

## Monochromator energy calibration with reference foil

Calibrate the mono against a reference foil (Au, Cu, Fe, ...) by scanning
the absorption edge, finding the inflection point, and updating the mono
calibration so the measured edge matches the tabulated NIST value.

### Tabulated edge values

Always use **unrounded** NIST values, never rounded ones:

- Au K = **11918.7** eV  (NOT 11919)
- Cu K = **8979.0** eV
- Fe K = **7112.0** eV

Verify against a primary source for unfamiliar elements.

### Detector selection

The experiment config tells you which detector has the foil in front of
it. If in doubt, check both I1 and I2. The `use_I1` selector (3rd arg to
the relevant macros) is `0` when I2 is the transmission detector and `1`
when the foil is in front of I1.

### Procedure

1. **Park at the tabulated edge:**
   ```spec
   plotselect I0                         # plot upstream flux during scan
   umv energy <tabulated_edge>
   ```

2. **Coarse edge scan** (use the CLI rather than raw SPEC for the scan
   itself):
   ```bash
   run-motor-scan-relative --motor energy --start -15 --finish 15 \
                           --intervals 60 --count-time 0.2
   ```
   Equivalent SPEC: `dscan energy -15 15 60 0.2`. Record the scan number
   (`p SCAN_N`).

3. **Find the inflection.** Use the CLI tools (`get-counts`, plotting) to
   pull I0 and the foil-detector trace and locate the peak of the
   derivative. Report the measured edge and the tabulated value.
   If you dont see the edge, expand the scan bounds.

   **Emergency stop:** if the calibration is off by more than **50 eV**,
   stop and escalate — something larger than a calibration drift is wrong.

4. **Apply the calibration:**
   ```spec
   mv energy <measured_inflection>
   calibrate_mono <tabulated_edge>       # updates motor pos + encoder cal
   ```

5. **Iterate.** Re-run the foil scan + `calibrate_mono` (without
   `reset_gap` between iterations — `reset_gap` fights the
   `calibrate_mono` loop) until a self-check edge scan reads within
   **0.3 eV** of the tabulated value. A finer post-cal reference scan
   (`dscan energy -15 15 80 0.2`) is the typical self-check; accept once
   the inflection is within **~0.2 eV** of tabulated.

6. **`absev` vs energy-motor convergence check.** After `calibrate_mono`,
   `ct 1` (or `get-counts`) should show `absev` essentially equal to the
   calibrated energy — both must converge to the tabulated value within
   ~10 eV. `absev` is the encoder readback used for downstream data
   analysis and is the canonical value for science. If `absev` is ~10 eV
   off but the energy motor reads correctly, the calibration is
   incomplete; iterate again.

7. **Final `reset_gap`** — exactly once, at the end, after calibration
   has converged:
   ```spec
   reset_gap                  # re-syncs gap encoder with the new mono cal
   ```
