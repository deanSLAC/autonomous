## `beamtimehero surveyor`

Agent scope: surveyor (phase=collection). Filters spec-write tools and validates motor args.

Invoke every tool as `beamtimehero surveyor <tree> <command>`; append `--help` at any depth to discover arguments.

Phase: `collection`

Allowed motors: `Sr`, `Sx`, `Sy`, `Sz`, `emiss`, `energy`, `filter`

### Write tools

Each requires `--justification` and is recorded in the action log.

- `beamtimehero surveyor db upload-sample-survey-results` — Persist Sample-Surveyor results to SamplePosition.
- `beamtimehero surveyor spec-write abort-current-scan` — Send Ctrl-C to SPEC.
- `beamtimehero surveyor spec-write fit-emission-peak` — Fit the most recent (or specified) emission scan with the lab's Pseudo-Voigt+skew model and return the suggested emission energy in eV.
- `beamtimehero surveyor spec-write move-motor` — Absolute motor move (umv).
- `beamtimehero surveyor spec-write move-motor-relative` — Relative motor move (umvr).
- `beamtimehero surveyor spec-write mv-energy` — Move incident energy (tracking on; moves mono + gap).
- `beamtimehero surveyor spec-write open-data-file` — newfile — start a new SPEC data file (per-sample).
- `beamtimehero surveyor spec-write plotselect` — Select which counter SPEC plots during subsequent scans.
- `beamtimehero surveyor spec-write run-emiss-scan` — Element-specific emission-energy (_cee) scan.
- `beamtimehero surveyor spec-write run-motor-scan` — ascan — absolute motor scan.
- `beamtimehero surveyor spec-write run-motor-scan-relative` — dscan — delta scan around the current position.
- `beamtimehero surveyor spec-write run-xas` — This command will call the _xas macro function for spectrum collection based on the element set by select_element.
- `beamtimehero surveyor spec-write safely-remove-filters` — Remove filters using the XRS-safe macro.
- `beamtimehero surveyor spec-write select-element` — Switch the beamline to the experiment's configured geometry for a single element (energy, emiss, Vortex ROI, xes_setup).
- `beamtimehero surveyor spec-write set-filter` — Set the filter motor (0-255 bitmask).
- `beamtimehero surveyor spec-write set-gain` — Set I0/I1/I2 SRS gain (string, e.g.
- `beamtimehero surveyor spec-write set-vortex-roi` — Set Vortex ROI.
- `beamtimehero surveyor spec-write shutter` — Fast-shutter control.
- `beamtimehero surveyor spec-write tracking` — Enable or disable energy tracking.

### Read tools

**db**

- `beamtimehero surveyor db get-comprehensive-collection-plan` — Return the per-sample/spot/filter/n_scans plan that Data Collection executes against.
- `beamtimehero surveyor db get-experiment-config` — Return the operator-entered experiment configuration straight from the DB: experiment-level settings (mono crystal, beam size, mirrors, sample env, data path), the configured elements (edges, energies, crystal/HKL, vortex counter mnemonic — vortDT/vortDT2/vortDT3/vortDT4), and every sample holder with its samples (positions, gains, XAS/RIXS plan).
- `beamtimehero surveyor db get-holder-time-budget` — Return the time budget for one or all holders: beamtime_hours, stop_time (absolute deadline), and hours_remaining (computed).
- `beamtimehero surveyor db get-plan` — Return the live experiment plan (config + sample queue + budget).
- `beamtimehero surveyor db get-remaining-beamtime` — Hours from now until Experiment.end_time.
- `beamtimehero surveyor db get-scans-for-active-sample` — Return every CollectionScan for the currently-active sample.
- `beamtimehero surveyor db get-scans-since-last-plan-update` — Return every CollectionScan row whose timestamp is newer than the live ExperimentPlan.updated_at.
- `beamtimehero surveyor db get-staff-guidance` — Recent staff / user guidance messages (Slack or web).
- `beamtimehero surveyor db list-open-interventions` — List pause-for-human requests still waiting.
- `beamtimehero surveyor db recent-actions` — Most recent action_log entries for the current experiment.
- `beamtimehero surveyor db record-convergence-stats` — Store per-sample convergence statistics from the latest analysis run.
- `beamtimehero surveyor db record-observable-trend` — Store the per-sample drift verdict of the scientific observable (oxidation-state / white-line / pre-edge trend across the accumulating scan stack, from summarize-sample-chemistry).
- `beamtimehero surveyor db record-sample-progress` — Update per-sample status (snr_estimate, efficiency_verdict, reps_completed, note).
- `beamtimehero surveyor db regenerate-plan` — Rebuild the sample plan from the database while preserving per-sample progress (status, reps_completed, notes) and user overrides (thresholds, holder_budgets, budget).
- `beamtimehero surveyor db request-human-intervention` — Pause the agent and ask a human to complete a physical action (crystal install, sample mount, foil insert, etc.).
- `beamtimehero surveyor db set-experiment-end-time` — Set the absolute end-of-beamtime timestamp on the active experiment.
- `beamtimehero surveyor db set-holder-time-budget` — Set a default per-sample time budget for an entire sample holder.
- `beamtimehero surveyor db set-sample-time-budget` — Adjust the time budget for a single sample.
- `beamtimehero surveyor db update-plan` — Replace the live experiment plan JSON (structure decided by the agent).

**exafs**

- `beamtimehero surveyor exafs exafs-products` — Capstone EXAFS reduction: merge reps → normalize → chi(k) → FT → |chi(R)| + first-shell apparent distance, with extraction and R-space plots.
- `beamtimehero surveyor exafs extract-chi` — Extract EXAFS chi(k) from repeated scans: merge reps (short/aborted sweeps dropped, glitches masked), find E0, apply Athena-style pre/post-edge polynomial normalization, and remove the post-edge background with a quick-look AUTOBK spline (knot budget from R_bkg).
- `beamtimehero surveyor exafs fourier-transform-chi` — Fourier transform chi(k) to R-space (Ifeffit convention, Hanning window): |chi(R)| with the first-shell apparent distance marked.
- `beamtimehero surveyor exafs list-collector-scans` — List the scan groups in a directory of SSRL 'EXAFS Data Collector' ASCII files (the DAQ format of SSRL XAS stations like BL 4-3 — one of many formats across SSRL's stations; this tool reads only that one): one row per group (sample stem + scan number) with its sweep numbers.
- `beamtimehero surveyor exafs overlay-chi-spectra` — Extract and overlay chi(k)·k^w for several scan groups on one plot — the comparison view for operando/potential series or sample vs standards in k-space.

**s3df**

- `beamtimehero surveyor s3df get-active-counter` — Identify the active fluorescence/absorption counter for a scan stored in S3DF.
- `beamtimehero surveyor s3df get-latest-scan` — Return metadata for the most-recently inserted scan in the S3DF Postgres metadata table.
- `beamtimehero surveyor s3df get-scan-deadtime` — Get dead-time stats for a scan (wall-clock vs acquisition seconds and percentage).
- `beamtimehero surveyor s3df list-scans` — List processed scans from the S3DF Postgres metadata table, most-recent first.
- `beamtimehero surveyor s3df plot-scan` — Plot one scan from the S3DF pickle store.
- `beamtimehero surveyor s3df read-scan` — Read a processed scan's metadata + DataFrame from the converter's pickle store.

**s3df/psql**

- `beamtimehero surveyor s3df psql execute-readonly-sql` — Run a read-only SELECT against the S3DF metadata Postgres.

**slack**

- `beamtimehero surveyor slack list-channels` — List public Slack channels the bot belongs to.
- `beamtimehero surveyor slack post-slack-message` — Post a message to a Slack channel or thread reply.
- `beamtimehero surveyor slack read-channel-messages` — Read recent messages from a Slack channel.
- `beamtimehero surveyor slack read-thread-replies` — Read all replies in a Slack thread (parent + children).

**spec-file**

- `beamtimehero surveyor spec-file align-spectra` — Cross-file energy registration: find each spectrum's E0 (derivative maximum), report the shift that lands it on a common target (the FIRST spectrum's E0, or an explicit target_e0), and return a two-panel before/after overlay plot.
- `beamtimehero surveyor spec-file analyze-convergence` — Check if repeated scans have converged using cosine similarity metrics.
- `beamtimehero surveyor spec-file analyze-efficiency` — Comprehensive scan repetition efficiency report.
- `beamtimehero surveyor spec-file analyze-feature-evolution` — Per-rep scalar trace + convergence verdict for a feature defined by an energy window and a statistic.
- `beamtimehero surveyor spec-file analyze-per-spot` — Run the full convergence/efficiency analysis SEPARATELY for each sample spot in the file (grouped by Sx/Sy/Sz), and report a between-spot vs within-spot heterogeneity F-statistic.
- `beamtimehero surveyor spec-file assess-xas-quality` — Data-quality gate for the averaged spectrum: monochromator-glitch spike count, detector-saturation (flat-top white line) check, and the honest self-absorption risk statement, with quality flags.
- `beamtimehero surveyor spec-file average-scans` — Average all energy scans in a SPEC file after edge-step normalization.
- `beamtimehero surveyor spec-file compare-xas-to-references` — Quantify speciation with XANES linear-combination fitting: non-negative (nnls) fit of a target spectrum against measured reference spectra → component fractions, fit R², residual RMS, and a target/fit/residual plot.
- `beamtimehero surveyor spec-file detect-per-scan-drift` — Beam-damage / photoreduction test: per-scan trends in E0, white-line height/energy, and pre-edge intensity, each with a monotonic-drift verdict (Kendall tau p<0.05 AND |Theil-Sen total change| > 2x residual MAD) — the monotonic-drift signature a first-half/second-half split can hide.
- `beamtimehero surveyor spec-file difference-spectrum` — Difference spectrum A − B on a common interpolated energy grid, computed AFTER per-spectrum E0 alignment by default (align=false to difference the raw axes — then a calibration offset shows up as a derivative-shaped artifact).
- `beamtimehero surveyor spec-file extract-xas-descriptors` — Deterministic numeric descriptors from the averaged, normalized XANES spectrum of a file: E0 (derivative-max AND half-step, with uncertainties), white-line fit (energy/height/area), Wilke-style pre-edge fit (centroid, integrated intensity, component count, fit quality), per-scan descriptor trends (drift/beam-damage test), glitch/saturation/self-absorption quality flags, and full provenance (normalization, baseline model, fit windows).
- `beamtimehero surveyor spec-file find-edge-e0` — Edge position E0 of the averaged spectrum under both fixed definitions — Savitzky-Golay derivative-max (primary, with uncertainty) and the half-step crossing (cross-check only) — plus the grid step.
- `beamtimehero surveyor spec-file fit-xas-pre-edge` — Wilke-style pre-edge fit of the averaged spectrum: centroid, integrated intensity, component count, and BIC/fit-quality with uncertainties and full provenance.
- `beamtimehero surveyor spec-file fit-xas-white-line` — White-line fit of the averaged spectrum: energy, height, and area of the main line (by height) plus the fitted components.
- `beamtimehero surveyor spec-file get-active-counter` — Identify the 'active' fluorescence/absorption counter for a scan.
- `beamtimehero surveyor spec-file get-energy-calibration` — Report the current session energy calibration: offset (eV), reference element/edge, age, and drift across all calibration records.
- `beamtimehero surveyor spec-file get-latest-scan` — Get the most recently processed scan.
- `beamtimehero surveyor spec-file get-scan-deadtime` — Get the dead time for a scan — the overhead time spent on motor moves, settling, and communication vs actual detector acquisition.
- `beamtimehero surveyor spec-file group-scans-by-spot` — Cluster a file's scans by sample spot using the recorded Sx/Sy/Sz motor positions.
- `beamtimehero surveyor spec-file identify-edge` — What edge is this: auto-detect the absorber element/edge from the scan energy window (tabulated edge energies, labels only) and classify the interpretation family (3d/4d/5d K, Ln/An L3, 5d L3, An M4/M5).
- `beamtimehero surveyor spec-file interpret-coordination-geometry` — Hybrid coordination/site-symmetry verdict for 3d K-edges from the pre-edge intensity + component count on the Wilke 2001 centroid-vs-intensity envelope (weak pre-edge = centrosymmetric/octahedral; strong = non-centrosymmetric/tetrahedral; intermediate = 5-coordinate/distorted/mixed).
- `beamtimehero surveyor spec-file interpret-oxidation-state` — Hybrid oxidation-state verdict from the file's averaged spectrum, on the family-appropriate basis: 3d K-edge -> pre-edge centroid (Wilke 2001, applied to the re-broadened spectrum) + calibrated edge shift; Ce L3 -> Ce(IV) final-state doublet deconvolution; U M4 -> peak-position/satellite method (Bes 2016); 5d L3 -> white-line trend.
- `beamtimehero surveyor spec-file list-scans` — List processed scans with metadata (file name, scan number, command, counters, number of points).
- `beamtimehero surveyor spec-file normalize-scan` — Edge-step normalize a scan: divide signal by I0, then scale so pre-edge is 0 and post-edge is 1.
- `beamtimehero surveyor spec-file normalize-xas-intensity` — Normalize the averaged spectrum and report the provenance only (method, window, scale/reason).
- `beamtimehero surveyor spec-file plot-averaged-scans` — Plot averaged energy scans for multiple samples overlaid on one plot.
- `beamtimehero surveyor spec-file plot-feature-evolution` — Plot a single per-rep scalar (the chosen statistic over [e_min, e_max]) versus rep number, with running mean and ±SEM band.
- `beamtimehero surveyor spec-file plot-first-half-vs-second-half` — Compare the average of the first half of reps to the second half, with SEM bands.
- `beamtimehero surveyor spec-file plot-running-average` — Plot the running average across reps as it evolves (one line per cumulative subset, color-progressed by rep #), with the final ±SEM band.
- `beamtimehero surveyor spec-file plot-scan` — Generate and display a plot of scan data.
- `beamtimehero surveyor spec-file plot-scan-stack` — Overlay all reps of one sample on a single axis, color-progressed by rep order.
- `beamtimehero surveyor spec-file read-scan` — Read a processed scan's data and metadata.
- `beamtimehero surveyor spec-file record-energy-calibration` — Register a session energy calibration from a MEASURED reference foil/compound scan.
- `beamtimehero surveyor spec-file summarize-sample-chemistry` — Capstone chemical interpretation of a sample's averaged spectrum: composes extract_xas_descriptors + interpret_oxidation_state + interpret_coordination_geometry + detect_per_scan_drift (monotonic E0/white-line/pre-edge trends — the photoreduction/beam-damage signature a half-split misses), and returns one consolidated narration paragraph plus the annotated descriptor plot.

**spec-read**

- `beamtimehero surveyor spec-read get-anchor` — Read the current tracking anchor from the SPEC session: stored energy, m1vert/Tz (and their 1/2 constituents), crystal id, and SPEAR steering offset captured at anchor time.
- `beamtimehero surveyor spec-read get-beam-size` — Return the last-measured horizontal and vertical beam FWHM (mm) and the current beam-size mode (big/small/unknown) for each axis.
- `beamtimehero surveyor spec-read get-beam-status` — SPEAR current + BL15 state + gap ownership + beam_good flag.
- `beamtimehero surveyor spec-read get-counter` — Count for <count_time> seconds and return one specific counter's value.
- `beamtimehero surveyor spec-read get-counts` — Count for <count_time> seconds and return all counter values (I0, I1, vortDT, etc.).
- `beamtimehero surveyor spec-read get-current-datafile` — Returns the active SPEC data file path (DATAFILE global).
- `beamtimehero surveyor spec-read get-element` — Return the currently active element and all configured elements with their incident and emission energies.
- `beamtimehero surveyor spec-read get-plotselected-counter` — Return the currently plot-selected counter mnemonic — the counter peak/cen will operate on after a scan, set by the most recent plotselect.
- `beamtimehero surveyor spec-read get-scan-number` — Current SPEC_N and datafile.
- `beamtimehero surveyor spec-read read-all-positions` — Read all motor positions (wa) with parsed name→value map.
- `beamtimehero surveyor spec-read read-motor-position` — Read a single motor's current position (parsed float).

**tool**

- `beamtimehero surveyor tool capture-sample-image` — Capture a low-resolution JPEG snapshot of the sample from the beamline sample camera (RPi-Cam).
- `beamtimehero surveyor tool evaluate-spec-macro` — Requires a local spec-eval service: a Docker container with a licensed SPEC install, on an Ubuntu host.
- `beamtimehero surveyor tool get-counter-config` — Get SPEC counter configuration from the config file.
- `beamtimehero surveyor tool get-latest-log-entries` — Get the most recent entries from the beamline control logs.
- `beamtimehero surveyor tool get-motor-config` — Get SPEC motor configuration from the config file.
- `beamtimehero surveyor tool get-reference-image` — Return a reference image for a known sample environment or diagnostic tool.
- `beamtimehero surveyor tool list-files` — List non-SPEC files in the scan directory (macros, configs, text files).
- `beamtimehero surveyor tool list-logs` — List available log files.
- `beamtimehero surveyor tool log-status-assessment` — Append the planner's STATUS ASSESSMENT block to logs/status_assessments_<experiment_id>.jsonl.
- `beamtimehero surveyor tool plot-data` — General-purpose plotting tool.
- `beamtimehero surveyor tool post-status-update` — Post a high-level progress message to Slack + UI.
- `beamtimehero surveyor tool read-file` — Read a text file from the scan directory.
- `beamtimehero surveyor tool save-plan` — Save a markdown plan to the project's logs/plans/ directory.
- `beamtimehero surveyor tool search-logs` — Search the beamline control logs for a specific string or error message.
- `beamtimehero surveyor tool write-macro` — Save an edited macro as a new .mac file in the scan directory.
- `beamtimehero surveyor tool write-summary` — Save a conversation summary as a timestamped .txt file in the scan directory.

**xrs**

- `beamtimehero surveyor xrs align-crystals` — Report per-crystal alignment and outlier-rejection decisions WITHOUT summing: for each channel, its SNR and how far its shape deviates from the channel-median spectrum, and whether it would be kept.
- `beamtimehero surveyor xrs assess-xrs-quality` — Quality gate for a reduced XRS edge: SNR measured on the edge feature (not the Compton-dominated whole spectrum), the elastic-line energy resolution, and a verdict (publication / usable / marginal / noise_limited).
- `beamtimehero surveyor xrs average-xrs-scans` — Average repeated XRS scans on the energy-loss axis: load each rep on the chosen counter, divide by I0, re-reference to the elastic line, interpolate onto a common loss grid, and average with per-point SEM.
- `beamtimehero surveyor xrs build-loss-axis` — Convert one scan's incident-energy axis to energy loss (ω = incident − elastic center) and plot signal/I0 vs loss.
- `beamtimehero surveyor xrs calibrate-energy-loss` — Fit the elastic (Rayleigh) line of an elastic scan (an `ascan mono` with the analyzer fixed) to set the ZERO of energy loss (ω=0) and the instrumental energy resolution (elastic FWHM), and record it for the file.
- `beamtimehero surveyor xrs compare-xrs-to-references` — Linear-combination fit (non-negative) of a reduced XRS spectrum to reference spectra → phase/valence fractions.
- `beamtimehero surveyor xrs extract-xrs-descriptors` — Extract measurable descriptors from a reduced XRS edge: edge onset (loss-axis inflection), pre-edge peak (position + area), white line, integrated edge area, and feature SNR.
- `beamtimehero surveyor xrs interpret-q-dependence` — Classify a feature's momentum-transfer (q) behavior: dipole (low q, XANES-like) vs monopole/quadrupole (rising with q).
- `beamtimehero surveyor xrs interpret-xrs-oxidation-state` — Oxidation-state / covalency read from a reduced XRS edge.
- `beamtimehero surveyor xrs normalize-xrs` — Full XRS reduction to a comparable edge: average reps → subtract the Compton background → area-normalize over the edge window.
- `beamtimehero surveyor xrs overlay-xrs-spectra` — Overlay reduced XRS spectra from multiple files (samples, states of charge, q-bins) on the energy-loss axis with consistent processing.
- `beamtimehero surveyor xrs subtract-compton-background` — Average XRS reps, then fit and subtract the Compton/valence background under the edge — the XRS replacement for XAS pre/post-edge normalization (the feature is a bump on a sloping Compton profile, not a step).
- `beamtimehero surveyor xrs sum-crystals` — Energy-align multiple analyzer-crystal / SDD-ROI channels of ONE scan onto a common loss grid (each channel has its own calibration), reject outlier channels (low SNR or shape deviating from the channel median), and sum.
- `beamtimehero surveyor xrs summarize-xrs-chemistry` — Capstone XRS interpretation: oxidation/covalency verdict + quality + one narration paragraph and the annotated descriptor plot.
- `beamtimehero surveyor xrs tag-crystal-q` — Compute the momentum transfer q (Å⁻¹) for each analyzer crystal from the incident energy and the crystal scattering angles 2θ: q = (4π/λ)·sin(θ).
