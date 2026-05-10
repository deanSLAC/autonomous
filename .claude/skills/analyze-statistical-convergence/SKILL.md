---
name: analyze-statistical-convergence
description: Decide whether enough XAS reps have been collected on the active sample to move on, by tracking the SNR / variance trend across the accumulating scan stack. Use after each new rep on the active sample (or after every 2 reps once `reps_completed >= 4`) to update the per-sample `efficiency_verdict` and `snr_estimate`, and to grow / shrink that sample's `reps` budget. Wraps `analyze-efficiency` and `analyze-convergence` with the diminishing-returns logic, the per-sample budget interaction, and the small-feature gotchas.
---

# Analyze Statistical Convergence (when to stop measuring a sample)

You decide when the variance across reps on the active sample has flattened enough that more scans aren't buying meaningful SNR — and therefore the sample's remaining budget should be released to other samples (or the queue advanced). The decision is **not** "does an additional rep buy any improvement" — it's "is the data already at publication quality, and is the marginal rep worth more on this sample than on the next one in the queue."

**The bar is publication quality.** BL15 beamtime is not for exploratory or "good enough" data; the only output that justifies the run is a spectrum we can publish. That changes how you read the CLI verdicts: `reasonable` is calibrated to "near optimal scan count for a survey," which is a lower bar than publication. Default behavior when in doubt is to lean toward `needs_more`, not toward stopping. The freed-budget argument for stopping early only applies when the freed budget moves to *another* publication-quality target — not when it pads an already-good sample.

This skill is the Planner's procedure. It composes existing tools — `analyze-efficiency` (variance / convergence verdict + recommended optimal scan count) and `analyze-convergence` (cosine similarity of cumulative averages) — and adds the budget interaction, small-feature checks, visual inspection, and stop logic. The math lives in `beamline_tools/experiment_planning/scan_efficiency.py` and `beamline_tools/generic_data/cosine_similarity.py`; this skill tells you how to use the verdicts.

**Treat the CLI verdict as a first-pass screen, not a stop signal.** The two analysis tools have a known structural bias toward declaring convergence too early (see "Why the CLI verdict reads optimistic" below). You must always combine the verdict with visual inspection of the accumulating stack and a feature-windowed cross-check before stopping a sample. If the visual evidence and the CLI disagree, trust your eyes and the per-feature numbers.

---

## Why the CLI verdict reads optimistic IN WHOLE-SPECTRUM MODE (read this first)

The original `analyze-efficiency` / `analyze-convergence` defaults are structurally biased. The tools now accept `--e-min`/`--e-max` so you can sidestep the bias — but you must actually pass them. If you call these tools without bounds you will get the optimistic answer.

**Why the bias exists.** Edge-step normalization (run per-scan before stacking) defines the post-edge to be ~1.0 by construction. By the time the convergence math sees the stack, the post-edge has near-zero variance because we *made it that way*, not because it's well-measured. The pre-edge baseline is similarly defined to be ~0. Every point in those regions is a constant the math is averaging *with* the actual dynamic part of the spectrum — averaging the question with the answer.

The dynamic, scientifically interesting part of an XAS / HERFD spectrum is the near-edge feature(s) the experiment actually cares about: a specific white-line peak, a pre-edge shoulder, an oxidation-state-sensitive position. That's where the chemistry lives, and that is the only region whose convergence answers "do we have enough scans for publication?"

The three concrete consequences when running without bounds:

1. **Cosine similarity is amplitude-dominated.** `analyze-convergence` computes `(A·B)/(‖A‖‖B‖)` on the whole edge-step-normalized spectrum. The post-edge plateau (≈1.0 over many points) dominates both the dot product and the norms. A white-line shoulder can change by 20–30% rep-over-rep and the cosine similarity still reads > 0.999.
2. **CV is averaged across the whole spectrum** (with only a 5% edge trim). The flat post-edge and the flat pre-edge baseline drag the mean CV down. The per-rep marginal-improvement knee gets crossed early.
3. **The verdict is therefore optimistic** in whole-spectrum mode and structurally unsuitable for the publication-quality stop decision.

**The fix.** Always run the windowed tools with numeric `--e-min` / `--e-max` bounds you've read off the averaged spectrum (Procedure step 2). Use `analyze-feature-evolution` for the per-feature scalar verdict — that's the publication-quality test. Whole-spectrum mode is now a sanity check, not a stop signal.

---

## When to invoke

Invoke this skill, in order of typical cadence:

- **After every new scan** appears in `list-scans` for a sample with `status=in_progress`, once `reps_completed >= 2` (you need at least 2 scans for any of the convergence math to run).
- **At minimum every 2 reps** once `reps_completed >= 4`, even if you're polling more rarely — diminishing returns kick in fast and a stale verdict wastes budget.
- **Whenever the data-collection agent posts a `record-sample-progress` note mentioning damage, fresh-spot move, or a thrown-out scan.** The reps-completed count may not reflect the usable scan count; you need to re-evaluate against the current good-scan stack.
- **Before issuing `set-sample-time-budget` to change `reps`** on the active sample. Don't change reps without first checking what the current convergence trajectory says.
- **Before promoting the sample to `done`** (writing `record-sample-progress --status done`).

Do **not** invoke if `reps_completed < 2`. The cosine-similarity and CV trends need ≥2 scans; with 1 scan, just wait for the second.

---

## Inputs (tools to call)

All via `beamtimehero ...`. Quick recipe per invocation. Order matters: you must IDENTIFY a feature on the averaged spectrum BEFORE running the windowed analysis tools.

1. `beamtimehero db get-plan` — get the active sample id, its `reps` target, its `reps_completed`, current `efficiency_verdict` and `snr_estimate` (if previously set), and the holder's remaining time budget.
2. `beamtimehero tool list-scans --limit 20` — confirm the actual scan count matches `reps_completed`. The data-collection agent occasionally throws scans out via a SPEC note; the file count is authoritative.
3. **Identify a feature, then read its bounds off the plot.** This is the agent's responsibility — there is no auto-windowing.
    - `beamtimehero tool average-scans --file-name <sample_id>` to see the averaged spectrum first, OR `plot-scan-stack --file-name <sample_id>` for a stacked-reps view. Read off the energy bounds of the feature you care about (white-line peak, pre-edge peak, dip between oscillations 1 and 2, etc.) — pick a tight window that brackets the feature with a small margin.
    - The plan should name the feature(s) of interest. If it doesn't, default to the white-line peak: it's the most prominent dynamic feature for almost every sample, and it's the publication-bar feature most often asked about.
    - Record the numeric `e_min`, `e_max` you've picked. You will pass these into every windowed tool call below.
4. `beamtimehero tool analyze-efficiency --file-name <sample_id> --e-min <e_min> --e-max <e_max>` — primary verdict, run on the windowed feature. Returns `verdict` ∈ {`needs_more`, `reasonable`, `marginal`, `wasteful`}, `cv_mean_pct`, `poisson_limit_pct`, `counts_poisson_floor_pct` (absolute counts-based floor), `cv_vs_floor_ratio` (>>1 = systematics-limited, ~1 = at Poisson floor, more reps still help), `optimal_scan_count`, `marginal_improvement[]`, `cumulative_cv_pct[]`, and the full `convergence` sub-result. **Do not call this tool without bounds on a sample with a known feature** — whole-spectrum mode averages dynamic content with normalization-defined plateaus and produces an optimistic verdict.
5. `beamtimehero tool analyze-feature-evolution --file-name <sample_id> --e-min <e_min> --e-max <e_max> --statistic <stat>` — the publication-quality test. Reduces each rep to a single scalar over the window (white-line height with `max`; white-line position with `argmax`; peak area with `integral`; height-above-baseline with `height`) and reports per-rep trace, running mean, running SEM, and a verdict (`converged` / `marginal` / `needs_more`) from the SEM and step-to-step drift directly. The default convergence target is `sem_threshold_frac=0.01` (1% of mean); tighten to 0.005 for very small features driving a result.
6. `beamtimehero tool analyze-convergence --file-name <sample_id> --e-min <e_min> --e-max <e_max>` — secondary read (cosine similarity). Useful for spotting outliers in `individual_vs_mean` (flag any < 0.95). The cumulative-convergence number is amplitude-dominated even windowed; treat as background context, not as a stop signal.
7. `beamtimehero tool group-scans-by-spot --file-name <sample_id>` — list spot clusters by Sx/Sy/Sz. If `n_spots > 1`, run the per-spot variant next.
8. `beamtimehero tool analyze-per-spot --file-name <sample_id> --e-min <e_min> --e-max <e_max>` — convergence per spot plus a between-spot vs within-spot heterogeneity F-statistic. F~1: spots agree, safe to combine. F>>1 (>5): spots disagree beyond shot noise — the combined average is a population mean, not a single chemistry; more reps will not converge.
9. `beamtimehero tool average-scans --file-name <sample_id> --e-min <e_min> --e-max <e_max> [--weighting inverse_variance]` — get the running mean and std for a sanity-check overlay. Use `inverse_variance` weighting when reps came from spots with very different signal levels and you want SNR-optimal averaging across them.
10. `beamtimehero db recent-actions --limit 10` — confirm no spot moves / filter changes / damage notes since the last assessment (those force a re-think of the variance budget).

---

## Procedure

1. **Reconcile scan count.** If `list-scans` count ≠ `reps_completed`, trust the file. If a scan was flagged as outlier in `analyze-convergence` (`individual_vs_mean < 0.95`), surface it in your status update — but `analyze-efficiency` already includes it in the math; don't try to re-run with it excluded unless staff specifically asks.
2. **Identify the feature(s) of interest and read off numeric bounds.** This is the step that makes everything else honest. Do NOT skip ahead to running the analysis tools without this:
    - Pull up the averaged spectrum: `plot-scan-stack --file-name <id>` (whole spectrum). Look at the plot.
    - Pick the feature(s) the publication will hinge on. Default is the **white-line peak** (the highest, sharpest near-edge feature). Other common choices: pre-edge peak (forbidden-transition shoulder), edge position (inflection of the rising edge, captured via `argmax` of the derivative — for now, use the white-line argmax as a proxy), or a specific EXAFS oscillation if the plan calls for it.
    - **Read the numeric energy bounds off the plot.** Pick `e_min` ~1–3 eV below where the feature starts to rise, `e_max` ~1–3 eV above where it returns to the local baseline. For a typical Fe K-edge white line that's a window of about 7–10 eV wide centered on the peak. Tight enough to exclude flat content; wide enough that small per-rep peak-position drift doesn't push the maximum out of the window.
    - If the plan names multiple features, repeat steps 3–6 below for each. The verdict at the sample level is the *worst* per-feature verdict — one feature still resolving means the sample is not done.
3. **Run `analyze-efficiency` with `--e-min` and `--e-max` for the chosen feature window.** Capture: `verdict`, `cv_mean_pct`, `counts_poisson_floor_pct`, `cv_vs_floor_ratio`, `optimal_scan_count`, last-element of `marginal_improvement`. The `cv_vs_floor_ratio` is the new key signal — if it's near 1, more reps still buy SNR (you're at the Poisson floor and the floor falls as 1/√n); if it's >>1, you are systematics-limited and more reps won't help.
4. **Run `analyze-feature-evolution` for the chosen feature.** Pass the same `--e-min` / `--e-max` plus a statistic that captures what you actually care about:
    - `--statistic max` for white-line height (default).
    - `--statistic argmax` for white-line position / edge position.
    - `--statistic integral` for peak area.
    - `--statistic height` for max−min within the window (peak prominence above any local baseline).
    - This returns the verdict that matters most for publication: a per-rep scalar trace, its running mean, running SEM, and verdict in {`converged`, `marginal`, `needs_more`}. The publication bar is `final_sem_frac < 0.01` (1% of the mean) AND `final_drift_frac < 0.01` (running mean step <1% per rep). Tighten the SEM threshold to 0.005 for a small feature driving a result.
5. **Visually inspect the accumulating stack (mandatory, every invocation).** The numbers above are necessary but not sufficient. Always look at the plot:
    - `plot-scan-stack --file-name <id> --e-min <e_min> --e-max <e_max>` — overlays all reps on the feature window, color-progressed by rep order. Look for: reps scattering symmetrically around a stable mean (converged), reps drifting monotonically in one direction (still resolving or sample is evolving — extend reps if budget allows; bail to `assess-sample-damage` if amplitude is decaying), or reps falling into discrete bands (between-spot heterogeneity, see step 6).
    - `plot-first-half-vs-second-half --file-name <id> --e-min <e_min> --e-max <e_max>` — direct first-half vs second-half comparison with SEM bands. Reports max |Δ|/SEM. <2σ: halves agree, sample is stationary. >3σ: halves disagree, more reps may not help (drift, damage, or heterogeneity). This is the strongest single-glance test for publication-readiness.
    - `plot-feature-evolution --file-name <id> --e-min <e_min> --e-max <e_max> --statistic <stat>` — visual companion to step 4. Should show a flatlining trace with scatter ≤ SEM band before you call it converged.
    - **Write a one-sentence verdict-from-eyes** alongside the numbers ("CLI says reasonable, feature-evolution says converged, plot-stack confirms reps scatter symmetrically; sample is publication-ready"). This is what you'll record in the `record-sample-progress --note`.
6. **If multiple spots are present, run the per-spot analysis.** Call `group-scans-by-spot --file-name <id>` first. If `n_spots > 1`, also call `analyze-per-spot --file-name <id> --e-min <e_min> --e-max <e_max>`:
    - **F-statistic interpretation.** F < 2 = `homogeneous`: spots agree within shot noise, the combined average is honest. F = 2–5 = `borderline`: visually inspect per-spot averages; if they differ at the feature, treat as heterogeneous. F > 5 = `heterogeneous`: the spots represent different chemistries (or the spectrum has been damaged at one and not the other). The combined average is a *population* mean, not a single chemistry — more reps will not converge to a single answer.
    - **What edge-step normalization handles, and what it doesn't.** Each rep is independently scaled so pre-edge → 0 and post-edge → 1 before stacking. So bulk concentration / thickness differences between spots are absorbed; the spectrum *shape* is what's compared. What edge-step normalization does NOT handle: real chemistry difference between spots (different oxidation state, different coordination), or damage at one spot. Those produce real shape differences and drive F up.
    - **SNR-weighted averaging.** When you trust the spots are chemically equivalent (F < 2) but they have very different signal levels, use `average-scans --weighting inverse_variance` to weight high-SNR spots more in the mean. This is the right choice when the experiment wants a single-chemistry mean and you have unequal-quality reps. (Do NOT use it when spots represent genuine heterogeneity — weighting just hides the disagreement.)
    - **What to surface.** If `analyze-per-spot` reports `heterogeneous`, do not mark the sample `done` on the strength of a `reasonable` whole-file verdict. Surface to staff via `post-status-update`: the question becomes whether the experiment wants a population average (continue with the unweighted mean) or per-spot spectra (split the file and analyze each subset; sample stays open).
    - **Spot-move alone is not damage evidence.** Don't cite "absolute counts changed across the spot move" as evidence of damage or convergence — counts change because the spot changed, that's expected. The shape comparison from `analyze-per-spot` is what's diagnostic.
7. **Compare against the per-sample budget.** Pull `reps` (target) and `reps_completed`. Decide based on the table in "Decision criteria" below.
8. **Decide and act.** Update `efficiency_verdict` and `snr_estimate` via `record-sample-progress`; if the budget needs to change, call `set-sample-time-budget`. Post a status update only when the decision is material (sample done, budget changed, projected overrun).

---

## Decision criteria

The primary lever is the **`analyze-feature-evolution` verdict on the chosen feature window** (`converged` / `marginal` / `needs_more`). The secondary lever is the **windowed `analyze-efficiency` verdict** plus `cv_vs_floor_ratio`. The tertiary signal is the visual half-vs-half and stacked-reps plots. The whole-spectrum `analyze-efficiency` verdict is a sanity check only.

| feature-evolution verdict | windowed efficiency verdict | cv_vs_floor_ratio | Recommended action |
|---|---|---|---|
| `needs_more` | any | any | Keep collecting. The feature has not reached publication SEM. If approaching planner-set `reps`, consider extending if budget supports it; if not, accept lower SNR and document the shortfall in `record-sample-progress --note`. |
| `marginal` | `needs_more` or `reasonable` | ~1 (at floor) | Keep collecting — feature is approaching but not at publication target, and reps still buy SNR as 1/√n. |
| `marginal` | `reasonable` or `marginal` | >>1 (≥ ~3) | Hold and surface to staff. The feature isn't at target but variance is plateauing above the Poisson floor — more reps won't get you there at this rate. Probable causes: between-spot heterogeneity (run `analyze-per-spot`), beam stability, or detector saturation. |
| `converged` | `reasonable` or `marginal` | any | Sample is publication-quality on this feature. If multiple features are named, only stop when all are `converged`. If single-feature: stop on schedule (let `reps_completed` reach the planner target if close), trim remaining reps via `set-sample-time-budget` if there's a meaningful budget save and verdict is also `marginal` or `wasteful`. |
| `converged` | `wasteful` | any | Stop now. Trim remaining reps via `set-sample-time-budget --reps <reps_completed>`. Roll freed budget into samples currently flagged `needs_more`. |
| any | any | < 1 (way below floor) | Suspect — likely a wrong active counter or a stack with mixed counters. Re-check `get-active-counter` and the file's column set before trusting anything. |
| outlier present | any | any | `analyze-convergence.individual_vs_mean < 0.95`. Surface via `post-status-update`; staff or data-collection may throw a scan out via SPEC note before the next decision. |

**Hard stop overrides** (regardless of verdict):

- `reps_completed >= reps` and verdict is at least `reasonable` → mark `done`.
- Holder remaining budget can't fit even one more rep on this sample at current per-rep wall time → mark `done` even if verdict is `needs_more`. Note the SNR shortfall in `record-sample-progress --note`.
- Per-rep wall time has grown by >25% (deadtime creep, slower mono moves) — re-project total time before authorizing more reps.

**Hard "keep going" overrides:**

- `analyze-feature-evolution` reports `needs_more` for any named feature, regardless of what the windowed `analyze-efficiency` says. The feature evolution test is the publication-quality bar.
- `plot-first-half-vs-second-half` reports max |Δ|/SEM > 3σ inside the feature window — halves disagree, the sample isn't stationary yet.
- The visual stacked-reps plot shows monotonic rep-over-rep drift at the feature (still resolving) or monotonic decay (bail to `assess-sample-damage`).
- `cv_vs_floor_ratio` ~1 AND feature-evolution is still `marginal` — you're at the Poisson floor and more reps still buy SNR as 1/√n. Continue.

**Hard "do not call done" cases (these aren't stop calls, they're escalations):**

- `analyze-per-spot` reports F-statistic > 5 (`heterogeneous`) — combined average is a population mean, not a single chemistry. Surface to staff via `post-status-update`. Do NOT mark `done` on the strength of a windowed `reasonable` verdict.
- `cv_vs_floor_ratio` >> 1 AND feature-evolution `needs_more` — you're systematics-limited, more reps won't help. Surface (likely an attenuation, beam, or heterogeneity issue), do not silently keep collecting.

---

## Output (what verdict, what action)

For each invocation, end with one of these moves:

- **Continue**: no plan edit needed. Optionally `record-sample-progress --sample-id <id> --snr_estimate <value> --efficiency_verdict <verdict>` to keep the per-sample state fresh. No status post unless the trajectory has changed materially.
- **Trim reps**: `set-sample-time-budget --sample-id <id> --reps <reps_completed>` (or `<reps_completed + 1>` if you want to give it one more for safety). This effectively releases the remaining reps' time. Post a status update: `"<sample> converged at N reps (verdict: <v>); freed ~<H> hours back to budget."`
- **Extend reps**: only when remaining holder budget supports it AND verdict is `needs_more` AND a small feature is materially under-resolved. `set-sample-time-budget --sample-id <id> --reps <new_n>`. Post a status update: `"<sample> needs more reps (CV still improving N% per scan); extended to <new_n>, budget impact ~<H> hours."`
- **Mark done**: `record-sample-progress --sample-id <id> --status done --reps-completed <n> --snr_estimate <value> --efficiency_verdict <verdict> --note "<one-line>"`. The data-collection agent normally writes `done` itself; the planner only writes it when forcing an early stop on the strength of this skill.
- **Surface outlier**: if a scan with `individual_vs_mean < 0.95` is dragging the mean, call `post-status-update` with the scan number and let staff or the data-collection agent decide whether to throw it out via a SPEC note.

The two per-sample fields you write are:

- `snr_estimate`: pick `1 / cv_mean_fraction` (i.e. `100 / cv_mean_pct`). It's a coarse number — the planner uses it for relative comparison across samples in the queue, not absolute calibration.
- `efficiency_verdict`: literal verdict string from `analyze-efficiency` (`needs_more` / `reasonable` / `marginal` / `wasteful`).

---

## Gotchas

- **Whole-spectrum CV and cosine similarity wash out small-feature evolution.** This is the explicit caveat in `context/sample-data-collection.md` § Statistics: "[the CLI tools] look at some statistic applied to the whole spectrum altogether, and claim nothing is changing with successive scans anymore. But this can wash out the tiny details in small features that might still be resolving progressively." See "Why the CLI verdict reads optimistic" at the top of this skill for the underlying mechanism (post-edge plateau dominates both metrics). The mandatory visual inspection in step 4 and the feature-windowed cross-check in step 5 are how you defend against this.
- **`reasonable` is not the same as "stop."** `reasonable` means "near optimal scan count." If the holder budget is tight and other samples are flagged `needs_more`, you can stop a `reasonable` sample to free budget. If the budget is generous, let it ride to its prescribed reps.
- **Edge-step normalization handles bulk concentration drift, not chemistry drift.** Each scan is independently scaled to pre→0, post→1 before stacking. Spot-to-spot concentration differences (dilution, thickness) are absorbed; spot-to-spot chemistry differences (oxidation state, coordination) are *preserved* and look like irreducible noise to the convergence math. If `cv_mean_pct` plateaus well above `poisson_limit_pct` and the per-feature plot shows reps clustered into discrete bands per spot, you have heterogeneity, not unconverged statistics.
- **The averaged spectrum is unweighted (`combined.mean(axis=1)`).** Higher-SNR spots do not carry more weight in the mean than noisy spots — every rep counts equally. This is the right choice when spots agree on chemistry; it is not the SNR-optimal choice when spots have very different absolute counts. The convergence math inherits this: the variance/CV reflect the unweighted mean's spread, not what an inverse-variance-weighted mean would look like. If reps come from spots with widely varying counts, note that the verdict slightly underestimates achievable SNR and surface to staff if the gap matters.
- **Don't use absolute count drift as evidence across spot moves.** `vortDT/I0` will jump when you switch spots regardless of whether anything is wrong — different concentration, different self-absorption geometry, different filter footprint. The shape of the edge-step-normalized spectrum is what carries comparison value across spots; raw counts do not.
- **Spot moves break the i.i.d. assumption** the convergence math relies on. The variance after a spot move includes between-spot systematic differences. Effective convergence is slower than the math reports. Bias one verdict-step less converged when a spot move is in the current stack and you don't have evidence the spots are chemically equivalent.
- **Damage masquerades as convergence.** If the absorbing species is being burned away, the spectrum can stop changing because there's nothing left to change. Cross-check with `assess-sample-damage` before trusting a `wasteful` verdict on a sensitive sample. If damage was suspected during collection (per `record-sample-progress` notes), don't extend reps even if the verdict says `needs_more` — the new reps will be measuring an evolving sample, not converging. The visual per-feature plot in step 4 helps distinguish these: convergence shows a flatlining trace, damage shows a monotonic decay, real evolution under intent shows a step.
- **Saturated counter ceilings the math.** If `vortDT` was at the 200 kcps deadtime cap, more reps cannot lower the per-point CV beyond the deadtime-limited noise floor. The verdict will read `wasteful` or `marginal` early, but the SNR is artificially capped. That's a filter / attenuation question (sample-survey territory), not a convergence question. Note it; don't extend reps to fix it.
- **Outlier scans drag the mean.** `analyze-convergence` reports `individual_vs_mean < 0.95` for outliers. If found, the cumulative convergence will look worse than it actually is for the in-distribution scans. Surface to staff/data-collection rather than re-budgeting around it.
- **SPEAR-normalize before eyeballing.** All the `analyze-*` tools already normalize by I0; if you do a sanity-check via `read-scan` and look at raw vortDT, divide by I0 and remember ring current drifts ~5 mA per session.
- **Don't use this skill on a single scan.** No convergence math runs with `n_scans < 2`. Wait.
- **`xas_reps` / `reps` budget interaction.** `set-sample-time-budget --reps` overrides the planner's per-sample target and re-projects the holder budget. Always reconcile: trim if `wasteful`, extend if `needs_more` and budget allows. If extending breaks the holder budget, post a status update naming the trade — don't silently overrun.

---

## Tool surface (what's available now)

The previous gaps have been closed. Quick reference for the convergence-relevant CLI tools:

- `analyze-efficiency --file-name <id> --e-min <e1> --e-max <e2> [--no-poisson-floor]` — windowed CV + cosine-sim verdict, with absolute counts-based Poisson floor (`counts_poisson_floor_pct`, `cv_vs_floor_ratio`).
- `analyze-feature-evolution --file-name <id> --e-min <e1> --e-max <e2> --statistic {max,argmax,integral,height,...}` — per-rep scalar trace + verdict (`converged` / `marginal` / `needs_more`), the publication-quality test.
- `analyze-convergence --file-name <id> --e-min <e1> --e-max <e2>` — windowed cosine similarity, mainly for outlier detection.
- `average-scans --file-name <id> --e-min <e1> --e-max <e2> [--weighting inverse_variance]` — windowed average with optional SNR-weighted averaging.
- `group-scans-by-spot --file-name <id> [--tol-mm 0.05]` — cluster scans by Sx/Sy/Sz.
- `analyze-per-spot --file-name <id> --e-min <e1> --e-max <e2> [--tol-mm 0.05]` — per-spot convergence + between/within F-statistic for heterogeneity.
- `plot-scan-stack --file-name <id> [--e-min --e-max]` — overlay all reps, color-progressed.
- `plot-first-half-vs-second-half --file-name <id> [--e-min --e-max]` — half-vs-half SEM comparison.
- `plot-running-average --file-name <id> [--e-min --e-max]` — running-mean evolution per rep.
- `plot-feature-evolution --file-name <id> --e-min <e1> --e-max <e2> --statistic <stat>` — per-rep scalar visual companion to `analyze-feature-evolution`.

**Remaining limitations:**

- **No automatic edge-energy detection.** You must read off the feature bounds from the averaged-spectrum plot. There's no `--feature=white_line` shortcut. This is intentional for now: the agent picks the bounds because feature definitions are experiment-specific.
- **`analyze-per-spot` heterogeneity F-stat is per-energy-point, then averaged.** A small dominant feature with a real shape difference can be averaged out by surrounding flat regions. Always pair with the visual per-spot averaged spectra (`plot-averaged-scans` after splitting by spot, or read the per-spot `cv_mean_pct` values).
- **Inverse-variance weighting estimates per-rep noise from the post-edge baseline std.** If a rep has a damaged or anomalous post-edge, its weight is wrong. For pristine samples the estimate is good; for borderline cases verify the weights look reasonable in the `weights_used` array of `average-scans`.

---

## Reporting

After each invocation, the per-sample state in the plan should reflect the latest read:

- `snr_estimate` and `efficiency_verdict` updated via `record-sample-progress`.
- A one-line `note` on every state-changing call: which verdict, what marginal improvement, whether you trimmed/extended.
- A `post-status-update` only when a budget edit happened or a small-feature override fired — keep status traffic low; the supervisory loop sees these every couple of minutes.
- When marking the sample `done` early, the note should include both the verdict and the freed-budget estimate so the supervisory loop can re-project the remaining queue.
