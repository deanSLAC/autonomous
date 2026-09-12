## `beamtimehero samplealigner`

Agent scope: samplealigner (phase=sample_alignment). Filters spec-write tools and validates motor args.

Invoke every tool as `beamtimehero samplealigner <tree> <command>`; append `--help` at any depth to discover arguments.

Phase: `sample_alignment`

Allowed motors: `Sr`, `Sx`, `Sy`, `Sz`, `emiss`, `energy`, `filter`

### Write tools

Each requires `--justification` and is recorded in the action log.

- `beamtimehero samplealigner db upload-sample-alignment-results` — Persist Sample-Alignment agent results to SamplePosition.
- `beamtimehero samplealigner spec-write abort-current-scan` — Send Ctrl-C to SPEC.
- `beamtimehero samplealigner spec-write fit-emission-peak` — Fit the most recent (or specified) emission scan with the lab's Pseudo-Voigt+skew model and return the suggested emission energy in eV.
- `beamtimehero samplealigner spec-write move-motor` — Absolute motor move (umv).
- `beamtimehero samplealigner spec-write move-motor-relative` — Relative motor move (umvr).
- `beamtimehero samplealigner spec-write mv-energy` — Move incident energy (tracking on; moves mono + gap).
- `beamtimehero samplealigner spec-write open-data-file` — newfile — start a new SPEC data file (per-sample).
- `beamtimehero samplealigner spec-write plotselect` — Select which counter SPEC plots during subsequent scans.
- `beamtimehero samplealigner spec-write run-diagonal-scan` — d2scan — relative scan of two motors moving in lockstep, each spanning the same delta range over the same number of points.
- `beamtimehero samplealigner spec-write run-motor-scan` — ascan — absolute motor scan.
- `beamtimehero samplealigner spec-write run-motor-scan-relative` — dscan — delta scan around the current position.
- `beamtimehero samplealigner spec-write safely-remove-filters` — Remove filters using the XRS-safe macro.
- `beamtimehero samplealigner spec-write select-element` — Switch the beamline to the experiment's configured geometry for a single element (energy, emiss, Vortex ROI, xes_setup).
- `beamtimehero samplealigner spec-write set-filter` — Set the filter motor (0-255 bitmask).
- `beamtimehero samplealigner spec-write set-gain` — Set I0/I1/I2 SRS gain (string, e.g.
- `beamtimehero samplealigner spec-write set-vortex-roi` — Set Vortex ROI.
- `beamtimehero samplealigner spec-write shutter` — Fast-shutter control.
- `beamtimehero samplealigner spec-write tracking` — Enable or disable energy tracking.

### Read tools

**db**

- `beamtimehero samplealigner db get-comprehensive-collection-plan` — Return the per-sample/spot/filter/n_scans plan that Data Collection executes against.
- `beamtimehero samplealigner db get-experiment-config` — Return the operator-entered experiment configuration straight from the DB: experiment-level settings (mono crystal, beam size, mirrors, sample env, data path), the configured elements (edges, energies, crystal/HKL, vortex counter mnemonic — vortDT/vortDT2/vortDT3/vortDT4), and every sample holder with its samples (positions, gains, XAS/RIXS plan).
- `beamtimehero samplealigner db get-holder-time-budget` — Return the time budget for one or all holders: beamtime_hours, stop_time (absolute deadline), and hours_remaining (computed).
- `beamtimehero samplealigner db get-plan` — Return the live experiment plan (config + sample queue + budget).
- `beamtimehero samplealigner db get-remaining-beamtime` — Hours from now until Experiment.end_time.
- `beamtimehero samplealigner db get-scans-for-active-sample` — Return every CollectionScan for the currently-active sample.
- `beamtimehero samplealigner db get-scans-since-last-plan-update` — Return every CollectionScan row whose timestamp is newer than the live ExperimentPlan.updated_at.
- `beamtimehero samplealigner db get-staff-guidance` — Recent staff / user guidance messages (Slack or web).
- `beamtimehero samplealigner db list-open-interventions` — List pause-for-human requests still waiting.
- `beamtimehero samplealigner db recent-actions` — Most recent action_log entries for the current experiment.
- `beamtimehero samplealigner db record-convergence-stats` — Store per-sample convergence statistics from the latest analysis run.
- `beamtimehero samplealigner db record-observable-trend` — Store the per-sample drift verdict of the scientific observable (oxidation-state / white-line / pre-edge trend across the accumulating scan stack, from summarize-sample-chemistry).
- `beamtimehero samplealigner db record-sample-progress` — Update per-sample status (snr_estimate, efficiency_verdict, reps_completed, note).
- `beamtimehero samplealigner db regenerate-plan` — Rebuild the sample plan from the database while preserving per-sample progress (status, reps_completed, notes) and user overrides (thresholds, holder_budgets, budget).
- `beamtimehero samplealigner db request-human-intervention` — Pause the agent and ask a human to complete a physical action (crystal install, sample mount, foil insert, etc.).
- `beamtimehero samplealigner db set-experiment-end-time` — Set the absolute end-of-beamtime timestamp on the active experiment.
- `beamtimehero samplealigner db set-holder-time-budget` — Set a default per-sample time budget for an entire sample holder.
- `beamtimehero samplealigner db set-sample-time-budget` — Adjust the time budget for a single sample.
- `beamtimehero samplealigner db update-plan` — Replace the live experiment plan JSON (structure decided by the agent).

**exafs**

- `beamtimehero samplealigner exafs exafs-products` — Capstone EXAFS reduction: merge reps → normalize → chi(k) → FT → |chi(R)| + first-shell apparent distance, with extraction and R-space plots.
- `beamtimehero samplealigner exafs extract-chi` — Extract EXAFS chi(k) from repeated scans: merge reps (short/aborted sweeps dropped, glitches masked), find E0, apply Athena-style pre/post-edge polynomial normalization, and remove the post-edge background with a quick-look AUTOBK spline (knot budget from R_bkg).
- `beamtimehero samplealigner exafs fourier-transform-chi` — Fourier transform chi(k) to R-space (Ifeffit convention, Hanning window): |chi(R)| with the first-shell apparent distance marked.
- `beamtimehero samplealigner exafs list-collector-scans` — List the scan groups in a directory of SSRL 'EXAFS Data Collector' ASCII files (the DAQ format of SSRL XAS stations like BL 4-3 — one of many formats across SSRL's stations; this tool reads only that one): one row per group (sample stem + scan number) with its sweep numbers.
- `beamtimehero samplealigner exafs overlay-chi-spectra` — Extract and overlay chi(k)·k^w for several scan groups on one plot — the comparison view for operando/potential series or sample vs standards in k-space.

**s3df**

- `beamtimehero samplealigner s3df get-active-counter` — Identify the active fluorescence/absorption counter for a scan stored in S3DF.
- `beamtimehero samplealigner s3df get-latest-scan` — Return metadata for the most-recently inserted scan in the S3DF Postgres metadata table.
- `beamtimehero samplealigner s3df get-scan-deadtime` — Get dead-time stats for a scan (wall-clock vs acquisition seconds and percentage).
- `beamtimehero samplealigner s3df list-scans` — List processed scans from the S3DF Postgres metadata table, most-recent first.
- `beamtimehero samplealigner s3df plot-scan` — Plot one scan from the S3DF pickle store.
- `beamtimehero samplealigner s3df read-scan` — Read a processed scan's metadata + DataFrame from the converter's pickle store.

**s3df/psql**

- `beamtimehero samplealigner s3df psql execute-readonly-sql` — Run a read-only SELECT against the S3DF metadata Postgres.

**slack**

- `beamtimehero samplealigner slack list-channels` — List public Slack channels the bot belongs to.
- `beamtimehero samplealigner slack post-slack-message` — Post a message to a Slack channel or thread reply.
- `beamtimehero samplealigner slack read-channel-messages` — Read recent messages from a Slack channel.
- `beamtimehero samplealigner slack read-thread-replies` — Read all replies in a Slack thread (parent + children).

**spec-file**

- `beamtimehero samplealigner spec-file align-spectra` — Cross-file energy registration: find each spectrum's E0 (derivative maximum), report the shift that lands it on a common target (the FIRST spectrum's E0, or an explicit target_e0), and return a two-panel before/after overlay plot.
- `beamtimehero samplealigner spec-file analyze-convergence` — Check if repeated scans have converged using cosine similarity metrics.
- `beamtimehero samplealigner spec-file analyze-efficiency` — Comprehensive scan repetition efficiency report.
- `beamtimehero samplealigner spec-file analyze-feature-evolution` — Per-rep scalar trace + convergence verdict for a feature defined by an energy window and a statistic.
- `beamtimehero samplealigner spec-file analyze-per-spot` — Run the full convergence/efficiency analysis SEPARATELY for each sample spot in the file (grouped by Sx/Sy/Sz), and report a between-spot vs within-spot heterogeneity F-statistic.
- `beamtimehero samplealigner spec-file assess-xas-quality` — Data-quality gate for the averaged spectrum: monochromator-glitch spike count, detector-saturation (flat-top white line) check, and the honest self-absorption risk statement, with quality flags.
- `beamtimehero samplealigner spec-file average-scans` — Average all energy scans in a SPEC file after edge-step normalization.
- `beamtimehero samplealigner spec-file compare-xas-to-references` — Quantify speciation with XANES linear-combination fitting: non-negative (nnls) fit of a target spectrum against measured reference spectra → component fractions, fit R², residual RMS, and a target/fit/residual plot.
- `beamtimehero samplealigner spec-file detect-per-scan-drift` — Beam-damage / photoreduction test: per-scan trends in E0, white-line height/energy, and pre-edge intensity, each with a monotonic-drift verdict (Kendall tau p<0.05 AND |Theil-Sen total change| > 2x residual MAD) — the monotonic-drift signature a first-half/second-half split can hide.
- `beamtimehero samplealigner spec-file difference-spectrum` — Difference spectrum A − B on a common interpolated energy grid, computed AFTER per-spectrum E0 alignment by default (align=false to difference the raw axes — then a calibration offset shows up as a derivative-shaped artifact).
- `beamtimehero samplealigner spec-file extract-xas-descriptors` — Deterministic numeric descriptors from the averaged, normalized XANES spectrum of a file: E0 (derivative-max AND half-step, with uncertainties), white-line fit (energy/height/area), Wilke-style pre-edge fit (centroid, integrated intensity, component count, fit quality), per-scan descriptor trends (drift/beam-damage test), glitch/saturation/self-absorption quality flags, and full provenance (normalization, baseline model, fit windows).
- `beamtimehero samplealigner spec-file find-edge-e0` — Edge position E0 of the averaged spectrum under both fixed definitions — Savitzky-Golay derivative-max (primary, with uncertainty) and the half-step crossing (cross-check only) — plus the grid step.
- `beamtimehero samplealigner spec-file fit-xas-pre-edge` — Wilke-style pre-edge fit of the averaged spectrum: centroid, integrated intensity, component count, and BIC/fit-quality with uncertainties and full provenance.
- `beamtimehero samplealigner spec-file fit-xas-white-line` — White-line fit of the averaged spectrum: energy, height, and area of the main line (by height) plus the fitted components.
- `beamtimehero samplealigner spec-file get-active-counter` — Identify the 'active' fluorescence/absorption counter for a scan.
- `beamtimehero samplealigner spec-file get-energy-calibration` — Report the current session energy calibration: offset (eV), reference element/edge, age, and drift across all calibration records.
- `beamtimehero samplealigner spec-file get-latest-scan` — Get the most recently processed scan.
- `beamtimehero samplealigner spec-file get-scan-deadtime` — Get the dead time for a scan — the overhead time spent on motor moves, settling, and communication vs actual detector acquisition.
- `beamtimehero samplealigner spec-file group-scans-by-spot` — Cluster a file's scans by sample spot using the recorded Sx/Sy/Sz motor positions.
- `beamtimehero samplealigner spec-file identify-edge` — What edge is this: auto-detect the absorber element/edge from the scan energy window (tabulated edge energies, labels only) and classify the interpretation family (3d/4d/5d K, Ln/An L3, 5d L3, An M4/M5).
- `beamtimehero samplealigner spec-file interpret-coordination-geometry` — Hybrid coordination/site-symmetry verdict for 3d K-edges from the pre-edge intensity + component count on the Wilke 2001 centroid-vs-intensity envelope (weak pre-edge = centrosymmetric/octahedral; strong = non-centrosymmetric/tetrahedral; intermediate = 5-coordinate/distorted/mixed).
- `beamtimehero samplealigner spec-file interpret-oxidation-state` — Hybrid oxidation-state verdict from the file's averaged spectrum, on the family-appropriate basis: 3d K-edge -> pre-edge centroid (Wilke 2001, applied to the re-broadened spectrum) + calibrated edge shift; Ce L3 -> Ce(IV) final-state doublet deconvolution; U M4 -> peak-position/satellite method (Bes 2016); 5d L3 -> white-line trend.
- `beamtimehero samplealigner spec-file list-scans` — List processed scans with metadata (file name, scan number, command, counters, number of points).
- `beamtimehero samplealigner spec-file normalize-scan` — Edge-step normalize a scan: divide signal by I0, then scale so pre-edge is 0 and post-edge is 1.
- `beamtimehero samplealigner spec-file normalize-xas-intensity` — Normalize the averaged spectrum and report the provenance only (method, window, scale/reason).
- `beamtimehero samplealigner spec-file plot-averaged-scans` — Plot averaged energy scans for multiple samples overlaid on one plot.
- `beamtimehero samplealigner spec-file plot-feature-evolution` — Plot a single per-rep scalar (the chosen statistic over [e_min, e_max]) versus rep number, with running mean and ±SEM band.
- `beamtimehero samplealigner spec-file plot-first-half-vs-second-half` — Compare the average of the first half of reps to the second half, with SEM bands.
- `beamtimehero samplealigner spec-file plot-running-average` — Plot the running average across reps as it evolves (one line per cumulative subset, color-progressed by rep #), with the final ±SEM band.
- `beamtimehero samplealigner spec-file plot-scan` — Generate and display a plot of scan data.
- `beamtimehero samplealigner spec-file plot-scan-stack` — Overlay all reps of one sample on a single axis, color-progressed by rep order.
- `beamtimehero samplealigner spec-file read-scan` — Read a processed scan's data and metadata.
- `beamtimehero samplealigner spec-file record-energy-calibration` — Register a session energy calibration from a MEASURED reference foil/compound scan.
- `beamtimehero samplealigner spec-file summarize-sample-chemistry` — Capstone chemical interpretation of a sample's averaged spectrum: composes extract_xas_descriptors + interpret_oxidation_state + interpret_coordination_geometry + detect_per_scan_drift (monotonic E0/white-line/pre-edge trends — the photoreduction/beam-damage signature a half-split misses), and returns one consolidated narration paragraph plus the annotated descriptor plot.

**spec-read**

- `beamtimehero samplealigner spec-read get-anchor` — Read the current tracking anchor from the SPEC session: stored energy, m1vert/Tz (and their 1/2 constituents), crystal id, and SPEAR steering offset captured at anchor time.
- `beamtimehero samplealigner spec-read get-beam-size` — Return the last-measured horizontal and vertical beam FWHM (mm) and the current beam-size mode (big/small/unknown) for each axis.
- `beamtimehero samplealigner spec-read get-beam-status` — SPEAR current + BL15 state + gap ownership + beam_good flag.
- `beamtimehero samplealigner spec-read get-counter` — Count for <count_time> seconds and return one specific counter's value.
- `beamtimehero samplealigner spec-read get-counts` — Count for <count_time> seconds and return all counter values (I0, I1, vortDT, etc.).
- `beamtimehero samplealigner spec-read get-current-datafile` — Returns the active SPEC data file path (DATAFILE global).
- `beamtimehero samplealigner spec-read get-element` — Return the currently active element and all configured elements with their incident and emission energies.
- `beamtimehero samplealigner spec-read get-plotselected-counter` — Return the currently plot-selected counter mnemonic — the counter peak/cen will operate on after a scan, set by the most recent plotselect.
- `beamtimehero samplealigner spec-read get-scan-number` — Current SPEC_N and datafile.
- `beamtimehero samplealigner spec-read read-all-positions` — Read all motor positions (wa) with parsed name→value map.
- `beamtimehero samplealigner spec-read read-motor-position` — Read a single motor's current position (parsed float).

**tool**

- `beamtimehero samplealigner tool capture-sample-image` — Capture a low-resolution JPEG snapshot of the sample from the beamline sample camera (RPi-Cam).
- `beamtimehero samplealigner tool evaluate-spec-macro` — Requires a local spec-eval service: a Docker container with a licensed SPEC install, on an Ubuntu host.
- `beamtimehero samplealigner tool get-counter-config` — Get SPEC counter configuration from the config file.
- `beamtimehero samplealigner tool get-latest-log-entries` — Get the most recent entries from the beamline control logs.
- `beamtimehero samplealigner tool get-motor-config` — Get SPEC motor configuration from the config file.
- `beamtimehero samplealigner tool get-reference-image` — Return a reference image for a known sample environment or diagnostic tool.
- `beamtimehero samplealigner tool list-files` — List non-SPEC files in the scan directory (macros, configs, text files).
- `beamtimehero samplealigner tool list-logs` — List available log files.
- `beamtimehero samplealigner tool log-status-assessment` — Append the planner's STATUS ASSESSMENT block to logs/status_assessments_<experiment_id>.jsonl.
- `beamtimehero samplealigner tool plot-data` — General-purpose plotting tool.
- `beamtimehero samplealigner tool post-status-update` — Post a high-level progress message to Slack + UI.
- `beamtimehero samplealigner tool read-file` — Read a text file from the scan directory.
- `beamtimehero samplealigner tool save-plan` — Save a markdown plan to the project's logs/plans/ directory.
- `beamtimehero samplealigner tool search-logs` — Search the beamline control logs for a specific string or error message.
- `beamtimehero samplealigner tool write-macro` — Save an edited macro as a new .mac file in the scan directory.
- `beamtimehero samplealigner tool write-summary` — Save a conversation summary as a timestamped .txt file in the scan directory.

**xrs**

- `beamtimehero samplealigner xrs align-crystals` — Report per-crystal alignment and outlier-rejection decisions WITHOUT summing: for each channel, its SNR and how far its shape deviates from the channel-median spectrum, and whether it would be kept.
- `beamtimehero samplealigner xrs assess-xrs-quality` — Quality gate for a reduced XRS edge: SNR measured on the edge feature (not the Compton-dominated whole spectrum), the elastic-line energy resolution, and a verdict (publication / usable / marginal / noise_limited).
- `beamtimehero samplealigner xrs average-xrs-scans` — Average repeated XRS scans on the energy-loss axis: load each rep on the chosen counter, divide by I0, re-reference to the elastic line, interpolate onto a common loss grid, and average with per-point SEM.
- `beamtimehero samplealigner xrs build-loss-axis` — Convert one scan's incident-energy axis to energy loss (ω = incident − elastic center) and plot signal/I0 vs loss.
- `beamtimehero samplealigner xrs calibrate-energy-loss` — Fit the elastic (Rayleigh) line of an elastic scan (an `ascan mono` with the analyzer fixed) to set the ZERO of energy loss (ω=0) and the instrumental energy resolution (elastic FWHM), and record it for the file.
- `beamtimehero samplealigner xrs compare-xrs-to-references` — Linear-combination fit (non-negative) of a reduced XRS spectrum to reference spectra → phase/valence fractions.
- `beamtimehero samplealigner xrs extract-xrs-descriptors` — Extract measurable descriptors from a reduced XRS edge: edge onset (loss-axis inflection), pre-edge peak (position + area), white line, integrated edge area, and feature SNR.
- `beamtimehero samplealigner xrs interpret-q-dependence` — Classify a feature's momentum-transfer (q) behavior: dipole (low q, XANES-like) vs monopole/quadrupole (rising with q).
- `beamtimehero samplealigner xrs interpret-xrs-oxidation-state` — Oxidation-state / covalency read from a reduced XRS edge.
- `beamtimehero samplealigner xrs normalize-xrs` — Full XRS reduction to a comparable edge: average reps → subtract the Compton background → area-normalize over the edge window.
- `beamtimehero samplealigner xrs overlay-xrs-spectra` — Overlay reduced XRS spectra from multiple files (samples, states of charge, q-bins) on the energy-loss axis with consistent processing.
- `beamtimehero samplealigner xrs subtract-compton-background` — Average XRS reps, then fit and subtract the Compton/valence background under the edge — the XRS replacement for XAS pre/post-edge normalization (the feature is a bump on a sloping Compton profile, not a step).
- `beamtimehero samplealigner xrs sum-crystals` — Energy-align multiple analyzer-crystal / SDD-ROI channels of ONE scan onto a common loss grid (each channel has its own calibration), reject outlier channels (low SNR or shape deviating from the channel median), and sum.
- `beamtimehero samplealigner xrs summarize-xrs-chemistry` — Capstone XRS interpretation: oxidation/covalency verdict + quality + one narration paragraph and the annotated descriptor plot.
- `beamtimehero samplealigner xrs tag-crystal-q` — Compute the momentum transfer q (Å⁻¹) for each analyzer crystal from the incident energy and the crystal scattering angles 2θ: q = (4π/λ)·sin(θ).
