---
name: analyze-statistical-convergence
description: Decide whether enough XAS reps have been collected on the active sample to move on, by tracking the SNR / variance trend across the accumulating scan stack. Use after each new rep on the active sample (or after every 2 reps once `reps_completed >= 4`) to update the per-sample `efficiency_verdict` and `snr_estimate`, and to grow / shrink that sample's `reps` budget. Wraps `analyze-efficiency` and `analyze-convergence` with the diminishing-returns logic, the per-sample budget interaction, and the small-feature gotchas.
---

# Analyze Statistical Convergence (when to stop measuring a sample)

You decide when the variance across reps on the active sample has flattened enough that more scans aren't buying meaningful SNR — and therefore the sample's remaining budget should be released to other samples (or the queue advanced). The decision is not "is the spectrum perfect" but "does an additional rep meaningfully improve SNR vs cost in beamtime."

This skill is the Planner's procedure. It composes existing tools — `analyze-efficiency` (variance / convergence verdict + recommended optimal scan count) and `analyze-convergence` (cosine similarity of cumulative averages) — and adds the budget interaction, small-feature checks, and stop logic. The math lives in `beamline_tools/experiment_planning/scan_efficiency.py` and `beamline_tools/generic_data/cosine_similarity.py`; this skill tells you how to use the verdicts.

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

All via `beamtimehero ...`. Quick recipe per invocation:

1. `beamtimehero db get-plan` — get the active sample id, its `reps` target, its `reps_completed`, current `efficiency_verdict` and `snr_estimate` (if previously set), and the holder's remaining time budget.
2. `beamtimehero tool list-scans --limit 20` — confirm the actual scan count in the file matches `reps_completed`. The data-collection agent occasionally throws scans out via a SPEC note; the file count is authoritative.
3. `beamtimehero tool analyze-efficiency --file-name <sample_id>` — primary verdict. Returns: `verdict` ∈ {`needs_more`, `reasonable`, `marginal`, `wasteful`}, `optimal_scan_count`, `cv_mean_pct`, `poisson_limit_pct`, `marginal_improvement[]`, `cumulative_cv_pct[]`, `current_vs_optimal` string, and a full `convergence` sub-result.
4. `beamtimehero tool analyze-convergence --file-name <sample_id>` — secondary read. Returns per-scan similarity to the mean (outlier flag if any < 0.95), cumulative-convergence trajectory (target ≥ 0.99), and SEM trajectory (should decay as ~1/√n).
5. `beamtimehero tool average-scans --file-name <sample_id>` (optional, when verdict is on the fence) — get the running mean and std so you can sanity-check small-feature evolution that the whole-spectrum CV may wash out.
6. `beamtimehero db recent-actions --limit 10` — confirm no spot moves / filter changes / damage notes since the last assessment (those force a re-think of the variance budget).

---

## Procedure

1. **Reconcile scan count.** If `list-scans` count ≠ `reps_completed`, trust the file. If a scan was flagged as outlier in `analyze-convergence` (`individual_vs_mean < 0.95`), surface it in your status update — but `analyze-efficiency` already includes it in the math; don't try to re-run with it excluded unless staff specifically asks.
2. **Run `analyze-efficiency`** and capture: `verdict`, `optimal_scan_count`, `cv_mean_pct`, `poisson_limit_pct`, last-element of `marginal_improvement` (the per-scan CV improvement at the latest rep).
3. **Run `analyze-convergence`** and capture: final `cumulative_convergence` value, final SEM, any outliers in `individual_vs_mean`.
4. **Cross-check with the small-feature guidance from `context/sample-data-collection.md` § Statistics.** The whole-spectrum CV can flatten while a small feature (pre-edge, sharp white-line shoulder) is still resolving rep-over-rep. If the sample's plan notes call out a specific feature of interest, use `average-scans` to confirm the feature's running average isn't still moving by more than its SEM. If it is, treat the verdict as one step less converged than `analyze-efficiency` says.
5. **Account for damage / spot-move events.** If the data-collection agent moved spots mid-run, the CV from before-the-move and after-the-move includes systematic between-spot differences, not just shot noise. Effective SNR is lower than the math thinks. If `recent-actions` shows a spot move within the current scan stack, bias one step toward `needs_more`.
6. **Compare against the per-sample budget.** Pull `reps` (target) and `reps_completed`. Decide based on the table in "Decision criteria" below.
7. **Decide and act.** Update `efficiency_verdict` and `snr_estimate` via `record-sample-progress`; if the budget needs to change, call `set-sample-time-budget`. Post a status update only when the decision is material (sample done, budget changed, projected overrun).

---

## Decision criteria

The primary lever is the `analyze-efficiency` verdict plus the marginal improvement at the latest rep (`marginal_improvement[-1]`). The secondary signal is `cumulative_convergence` ≥ 0.99 from `analyze-convergence`. The tertiary check is whether the active sample is within budget.

| analyze-efficiency verdict | cumulative_convergence | last marginal CV improvement | Recommended action |
|---|---|---|---|
| `needs_more` | < 0.99 | > 5% | Keep collecting. If `reps_completed` is approaching the planner-set `reps` target, consider extending — only if remaining budget supports it; if not, accept the lower SNR and prepare to move on at the budget. |
| `reasonable` | ≥ 0.99 | 1–5% | Stop on schedule. Let the data-collection agent finish the planner-set `reps` target if not yet there, then mark `done`. |
| `reasonable` | ≥ 0.99 | < 1% | Stop now. Trim the remaining reps via `set-sample-time-budget --reps <reps_completed>`. The remaining budget redistributes across queued samples. |
| `marginal` | ≥ 0.99 | < 2% | Stop now. Diminishing returns; trim reps to free budget. |
| `wasteful` | ≥ 0.99 | < 1% | Stop immediately. The sample is overcollected; shed reps and ideally roll the freed budget into samples currently flagged `needs_more`. |
| any | < 0.99 | < 1% | Suspect: variance has flattened but cumulative average hasn't converged. Often means an outlier scan is dragging the mean. Check `analyze-convergence.individual_vs_mean` for any < 0.95; if found, surface it via `post-status-update` — staff or data-collection may need to throw a scan out. |

**Hard stop overrides** (regardless of verdict):

- `reps_completed >= reps` and verdict is at least `reasonable` → mark `done`.
- Holder remaining budget can't fit even one more rep on this sample at current per-rep wall time → mark `done` even if verdict is `needs_more`. Note the SNR shortfall in `record-sample-progress --note`.
- Per-rep wall time has grown by >25% (deadtime creep, slower mono moves) — re-project total time before authorizing more reps.

**Hard "keep going" overrides:**

- Plan / staff has called out a small feature (pre-edge specific peak, white-line shoulder) and the running average of that feature is still drifting by more than its SEM rep-over-rep, even when whole-spectrum verdict is `reasonable`. Flag this with the verdict but recommend continuing.

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

- **Whole-spectrum CV washes out small-feature evolution.** This is the explicit caveat in `context/sample-data-collection.md` § Statistics: "[the CLI tools] look at some statistic applied to the whole spectrum altogether, and claim nothing is changing with successive scans anymore. But this can wash out the tiny details in small features that might still be resolving progressively." If the experiment cares about a specific small feature, do the small-feature cross-check with `average-scans` before trusting a `reasonable` / `marginal` verdict.
- **`reasonable` is not the same as "stop."** `reasonable` means "near optimal scan count." If the holder budget is tight and other samples are flagged `needs_more`, you can stop a `reasonable` sample to free budget. If the budget is generous, let it ride to its prescribed reps.
- **Spot moves break the i.i.d. assumption** the convergence math relies on. The variance after a spot move includes between-spot systematic differences. Effective convergence is slower than the math reports. Bias one verdict-step less converged when a spot move is in the current stack.
- **Damage masquerades as convergence.** If the absorbing species is being burned away, the spectrum can stop changing because there's nothing left to change. Cross-check with `assess-sample-damage` before trusting a `wasteful` verdict on a sensitive sample. If damage was suspected during collection (per `record-sample-progress` notes), don't extend reps even if the verdict says `needs_more` — the new reps will be measuring an evolving sample, not converging.
- **Saturated counter ceilings the math.** If `vortDT` was at the 200 kcps deadtime cap, more reps cannot lower the per-point CV beyond the deadtime-limited noise floor. The verdict will read `wasteful` or `marginal` early, but the SNR is artificially capped. That's a filter / attenuation question (sample-survey territory), not a convergence question. Note it; don't extend reps to fix it.
- **Outlier scans drag the mean.** `analyze-convergence` reports `individual_vs_mean < 0.95` for outliers. If found, the cumulative convergence will look worse than it actually is for the in-distribution scans. Surface to staff/data-collection rather than re-budgeting around it.
- **SPEAR-normalize before eyeballing.** All the `analyze-*` tools already normalize by I0; if you do a sanity-check via `read-scan` and look at raw vortDT, divide by I0 and remember ring current drifts ~5 mA per session.
- **Don't use this skill on a single scan.** No convergence math runs with `n_scans < 2`. Wait.
- **`xas_reps` / `reps` budget interaction.** `set-sample-time-budget --reps` overrides the planner's per-sample target and re-projects the holder budget. Always reconcile: trim if `wasteful`, extend if `needs_more` and budget allows. If extending breaks the holder budget, post a status update naming the trade — don't silently overrun.

---

## Reporting

After each invocation, the per-sample state in the plan should reflect the latest read:

- `snr_estimate` and `efficiency_verdict` updated via `record-sample-progress`.
- A one-line `note` on every state-changing call: which verdict, what marginal improvement, whether you trimmed/extended.
- A `post-status-update` only when a budget edit happened or a small-feature override fired — keep status traffic low; the supervisory loop sees these every couple of minutes.
- When marking the sample `done` early, the note should include both the verdict and the freed-budget estimate so the supervisory loop can re-project the remaining queue.
