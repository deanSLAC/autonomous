---
name: assess-sample-damage
description: Compare two consecutive XAS/HERFD scans on the same sample spot to decide whether the beam is damaging the sample. Use during the Sample Survey phase (before settling on a per-sample filter count) and during Data Collection (between reps, after a fresh-spot move, or whenever a counter trend looks suspicious). Covers what to extract from each scan, the specific spectral features to compare (white-line height, edge position, pre-edge, post-edge), the count-rate decision tree (add filters / remove filters / move spot), and how to record the verdict.
---

# Assess Sample Damage (consecutive-scan comparison)

You compare two back-to-back XAS scans on **the same spot** and taken with the same number of filters, and decide whether the beam is altering the sample faster than acceptable. If yes, you reduce flux (more filters). If no, you can hold filters steady or — during Sample Survey — try removing filters to gain count rate (while keeping count rate below the given max threshold).

This skill encodes the procedure that lives in `context/sample-data-collection.md` (§ "Beam damage") and `context/Sample-collection_system-prompt.md` (steps 7–8). When something contradicts this skill, that source wins.

---

## When to invoke

Invoke this skill when **any** of the following is true:

- **Sample Survey, first encounter with a sample.** After moving to the spot and running the first pair of `run_xas` reps, before deciding the sample's filter count.
- **Sample Survey, after a filter change.** Whenever you remove or add filters during the survey iteration loop, you must move to a fresh spot, take a fresh pair of scans, and re-assess.
- **Data Collection, between reps within a sample.** After every 2 reps (or at minimum: after the first 2, mid-way, and at the end), check that the early reps and the most recent reps are consistent. Damage that develops slowly only shows up across the run.

Do **not** invoke before two consecutive scans on the same spot exist. The whole signal here is the difference between scan N and scan N+1 on identical conditions; with one scan you have nothing to compare.

---

## Inputs (tools to call)

All via `beamtimehero tool ...`. Always work from saved scan data, never from in-memory plot impressions.

1. `beamtimehero tool list-scans --limit 5` — find the two most recent scans on the active sample. Confirm the file name matches the active sample id (`open-data-file --name <sample_id>` is the convention).
2. `beamtimehero tool read-scan --file-name <sample_id> --scan-number <N>` and `--scan-number <N+1>` — pull both scans' raw arrays.
3. use `beamtimhero db get-experiment-config`, get the correct counter to use in comparing the scans (eg vortDT, vortDT2...).
4. `beamtimehero tool normalize-scan --file-name <sample_id> --scan-number <N> --normalize-by I0` — get edge-step normalized intensity for each scan. **You compare normalized data, not raw.** Raw counter / I0 ratios drift with SPEAR ring current and beam motion.
5. `beamtimehero tool plot-scan --file-name <sample_id> --scan-number <N> --normalize-by I0` for each, so the operator can see the comparison.

---

## Procedure

1. **Confirm same conditions.** Both scans must have identical: counter, energy grid, count time, filter setting, sample stage position. If `recent-actions` shows a `set_filter` or `umv Sx/Sy/Sz` between the two scans, abort the assessment — you don't have a controlled pair. Take a fresh pair.
2. **Edge-step normalize each scan.** Pre-edge → 0, post-edge → 1, signal divided by I0 first. Use `normalize-scan`.
3. **Extract the four feature checkpoints** from each normalized scan:
   - **Edge position (E0)**: half-height of the rising edge. Note the energy in eV.
   - **White-line height**: maximum intensity in the immediate post-edge region (typically within ~10–20 eV of E0).
   - **Pre-edge feature(s)**: any small peaks below E0 — record height and energy of each visible feature.
   - **Post-edge baseline**: average normalized intensity in a flat region 50–100 eV above E0 (should sit near 1.0 by construction; it's a normalization sanity check).
4. **Compare scan N to scan N+1** on each feature. Use the thresholds in the next section.
5. **Cross-check with raw counter trend.** Look at vortDT/I0 (or whatever counter is active) at the white-line energy across both scans. If it drops by >5% scan-to-scan with no other explanation (no SPEAR drop, no filter change), that's a damage signal even if the normalized shape looks similar — the sample may be absorbing/fluorescing less because the absorbing species is being consumed.
6. **Render a verdict** (see "Output" below) and act on it.

---

## Decision criteria

A scan pair is **damaging** if any of the following holds (cross-check at least two before committing — single thresholds have false positives from noise alone):

- **Edge shift** > 0.3 eV (suspicious) or > 0.5 eV (committed). Reduction or oxidation of the absorbing species shifts E0; this is the cleanest single damage indicator on a transition-metal edge.
- **White-line height change** > ~3% relative, in the same direction across the pair (i.e. monotonic, not just noise). Reduction of a Cr⁶⁺/V⁵⁺/Mn⁴⁺-type species drops the white line; oxidation often raises it.
- **Pre-edge height change** > ~5% relative on a feature that was clearly resolved in scan N. Pre-edge intensity is geometry- and oxidation-state-sensitive.
- **Counter / I0 at white-line** drops by > 5% scan-to-scan with no SPEAR drop (>2%), no filter change, and no I0-gain change. Catches damage that flattens the spectrum without obviously shifting it.

A scan pair is **not damaging** if all of:

- Edge position matches within 0.2 eV.
- White-line and pre-edge features match within ~1–2% relative.
- Post-edge baseline sits within 1% of unity for both.
- Counter/I0 trend at the white-line energy is flat (within ±2%) once SPEAR-normalized.

If you land in between (e.g. ~3% white-line change, no edge shift, low SNR) call it **inconclusive** — the right move is to take one more scan on the same spot and re-run this skill on the latest pair.

---

## Output (what verdict, what action)

Produce one of four verdicts and act:

- **`damaging`** → Move to a fresh spot (`umvr Sx <2 beam widths>` or per the holder's spot map). At the fresh spot, double the filter count (or add filters until the count rate is halved) before running the next pair. Re-invoke this skill on the new pair. Note in `record-sample-progress`: `note "damage at spot 1; moved to spot 2 with +N filters"`.
- **`safe, count rate room available`** (Sample Survey only) → If filters are non-zero and count rate is well below 50 kcps, remove filters until count rate doubles or hits 50 kcps. Take a new pair and re-assess. Goal: max usable flux without damage.
- **`safe, count rate appropriate`** → Keep filters. Sample Survey: record the converged filter count for this sample on the holder; survey is done for this sample. Data Collection: continue with the planner's prescribed reps.
- **`inconclusive`** → Take one more scan on the same spot, re-run this skill on the latest pair. Do **not** declare damage and do **not** widen flux on the strength of one borderline comparison. if its still inconclusive, call it safe.

When the verdict is `damaging` or `inconclusive` and you've already moved to two fresh spots without a clean pair, stop and surface via `tool post-status-update` — you may have a sample that damages at any flux, and that's a planner / staff conversation. 

---

## Gotchas

- **SPEAR ring current drift looks like damage.** Always SPEAR-normalize (I1/mA, vortDT/I0 with I0 itself bearing the ring-current dependence) before declaring a counter drop. ~5 mA drift over a session is normal. The `normalize-scan` and `analyze-*` tools handle this; if you eyeball, do it yourself.
- **Energy-axis drift can fake an edge shift.** If `absev` and the energy pseudo-motor disagreed before either scan, the apparent E0 shift may be encoder-vs-commanded mismatch, not chemistry. Confirm `absev` is used as the x-axis (it is, in saved scan data) and that no `calibrate_mono` or `reset_gap` happened between the pair.
- **Low-statistics false positives.** A pair of short, noisy scans will show 5–10% white-line wobble from photon counting alone. If the per-point CV in the white-line region is comparable to the inter-scan delta you're flagging, the call is `inconclusive`. Don't react to noise.

---

## Reporting

After deciding, leave a trace:

- Update `record-sample-progress --sample-id <id> --note "<one-line: which features differed and by how much, what filter count you converged on>"`.
- During Data Collection, if damage was observed mid-run, also call `post-status-update` with a one-liner so the Planner sees the cost (sample may need fresh-spot moves and pay setup overhead per spot).
- During Sample Survey, the converged filter count for the sample is the headline output — it goes into the survey result that the Planner reads when sizing reps for this sample.
