"""Tool definitions for BeamtimeHero.

TOOL_DEFINITIONS: Full schemas for MCP mode (10 tools).
CLI_TOOL_DEFINITION: Single run_command tool for CLI mode.
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_latest_scan",
            "description": "Get the most recently processed scan. Returns metadata and a data preview.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scans",
            "description": "List processed scans with metadata (file name, scan number, command, counters, number of points).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of scans to list (default 20)",
                        "default": 20,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_scan",
            "description": "Read a processed scan's data and metadata. Use list_scans first to find available file_name and scan_number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_log_entries",
            "description": "Get the most recent entries from the beamline control logs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "integer",
                        "description": "Number of log lines to return (default 100)",
                        "default": 100,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": "Search the beamline control logs for a specific string or error message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The text to search for in logs"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 50)",
                        "default": 50,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_logs",
            "description": "List available log files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of logs to list (default 20)",
                        "default": 20,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_counter",
            "description": "Identify the 'active' fluorescence/absorption counter for a scan. Logic: ppboff if present, else the vortDT/vortDT2/vortDT3/vortDT4 with highest max counts, else I1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scan_deadtime",
            "description": "Get the dead time for a scan — the overhead time spent on motor moves, settling, and communication vs actual detector acquisition. Returns wall-clock duration, acquisition time, dead time in seconds, and dead time as a percentage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "normalize_scan",
            "description": "Edge-step normalize a scan: divide signal by I0, then scale so pre-edge is 0 and post-edge is 1. Returns the normalized data array.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                    "counter": {
                        "type": "string",
                        "description": "Counter to normalize. Auto-detected if omitted.",
                    },
                    "normalize_by": {
                        "type": "string",
                        "description": "Counter to divide by before edge-step normalization (default: I0)",
                        "default": "I0",
                    },
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "average_scans",
            "description": (
                "Average all energy scans in a SPEC file after edge-step normalization. "
                "Returns mean and standard deviation across scans. If file_name is omitted, "
                "uses the most recent file with >1 energy scan. Optionally crops the average "
                "to a numeric energy window [e_min, e_max] in eV, and supports SNR-aware "
                "inverse-variance weighting across reps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file with >1 energy scan.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower energy bound (eV) for the returned average. Optional; if both e_min and e_max are given, the average is cropped to that window. Normalization is still done on the full scan.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper energy bound (eV) for the returned average.",
                    },
                    "weighting": {
                        "type": "string",
                        "enum": ["equal", "inverse_variance"],
                        "default": "equal",
                        "description": (
                            "'equal' = unweighted mean (default). 'inverse_variance' = weight each "
                            "rep by 1/sigma_i^2 where sigma_i is estimated from that rep's post-edge "
                            "baseline std. Use inverse_variance when reps come from spots with very "
                            "different signal levels and you want SNR-optimal averaging."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_convergence",
            "description": (
                "Check if repeated scans have converged using cosine similarity metrics. "
                "Reports per-scan similarity to the mean, cumulative convergence, and standard error. "
                "WARNING: cosine similarity is amplitude-dominated; the post-edge plateau (defined "
                "to be ~1.0 by edge-step normalization) dominates the metric. ALWAYS pass numeric "
                "e_min/e_max to focus on the dynamic part of the spectrum (e.g. a specific feature "
                "you've identified). Whole-spectrum mode (no bounds) is a structural over-estimate "
                "of convergence — use only as a sanity check."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window to analyze. Identify the feature on the averaged spectrum first, then pass its bounds.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window to analyze.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_efficiency",
            "description": (
                "Comprehensive scan repetition efficiency report. Includes convergence, CV analysis, "
                "rate-based and counts-based Poisson floor comparison, optimal scan count recommendation, "
                "and a verdict (needs_more / reasonable / marginal / wasteful). "
                "ALWAYS pass numeric e_min/e_max bounds for the feature you care about — running on the "
                "whole spectrum averages dynamic content with normalization-defined plateaus and produces "
                "an optimistic verdict. Identify the feature on the averaged spectrum first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window. Required in practice for meaningful verdicts.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window.",
                    },
                    "include_poisson_floor": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "If true (default), also compute the absolute counts-based Poisson floor "
                            "from the raw active counter. Result includes counts_poisson_floor_pct and "
                            "cv_vs_floor_ratio: ratio ~1 means at the floor (more reps still help "
                            "as 1/sqrt(n)); ratio >>1 means systematics-limited (more reps won't help)."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_feature_evolution",
            "description": (
                "Per-rep scalar trace + convergence verdict for a feature defined by an energy window "
                "and a statistic. The agent identifies a feature on the spectrum (white-line peak, "
                "pre-edge shoulder, dip between oscillations, etc.) and passes the numeric eV bounds "
                "and the statistic that captures it. Returns running mean, running SEM, and a verdict "
                "(converged / marginal / needs_more) for that scalar. This is the publication-quality "
                "test: the feature SEM should be a small fraction of its mean and the running mean "
                "should be flat rep-over-rep."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window. REQUIRED.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window. REQUIRED.",
                    },
                    "statistic": {
                        "type": "string",
                        "enum": ["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                        "default": "max",
                        "description": (
                            "Reduction over the window. 'max' = white-line height. 'argmax' = white-line "
                            "energy / edge position. 'integral' = peak area. 'min' / 'argmin' = a dip's "
                            "value / position. 'height' = max - min in window (peak prominence). 'mean' / "
                            "'median' = average value (use when the feature is a plateau)."
                        ),
                    },
                    "sem_threshold_frac": {
                        "type": "number",
                        "default": 0.01,
                        "description": (
                            "Target final SEM as a fraction of the running mean. 0.01 (1%) is the "
                            "default for publication-quality on a prominent feature; tighten to 0.005 "
                            "for very small features driving a result."
                        ),
                    },
                    "drift_threshold_frac": {
                        "type": "number",
                        "default": 0.01,
                        "description": "Step-to-step running-mean drift target as fraction of the latest mean.",
                    },
                },
                "required": ["file_name", "e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "group_scans_by_spot",
            "description": (
                "Cluster a file's scans by sample spot using the recorded Sx/Sy/Sz motor positions. "
                "Two scans are the same spot if their Sx, Sy, Sz all agree within tol_mm. Useful "
                "before convergence analysis when reps came from multiple spots — between-spot "
                "differences can pollute whole-file CV. Pair with analyze_per_spot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "tol_mm": {
                        "type": "number",
                        "default": 0.05,
                        "description": "Position tolerance in mm for grouping. Default 0.05 mm.",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_per_spot",
            "description": (
                "Run the full convergence/efficiency analysis SEPARATELY for each sample spot in "
                "the file (grouped by Sx/Sy/Sz), and report a between-spot vs within-spot "
                "heterogeneity F-statistic. F~1 = spots agree (safe to combine); F>>1 = spots "
                "disagree beyond shot noise (the combined average is a population mean, not a "
                "single chemistry — more reps won't fix it). Pass numeric e_min/e_max for the "
                "feature you care about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window. Strongly recommended.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window.",
                    },
                    "tol_mm": {
                        "type": "number",
                        "default": 0.05,
                        "description": "Position tolerance in mm for grouping.",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_scan",
            "description": "Generate and display a plot of scan data. Use this by default when the user wants to see a plot. The plot is shown directly to the user. Use list_scans to find available file_name and scan_number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                    "counter": {
                        "type": "string",
                        "description": "Counter to plot (e.g. 'I0', 'vortDT'). If omitted, auto-detects the active counter.",
                    },
                    "normalize_by": {
                        "type": "string",
                        "description": "Optional counter to normalize by (e.g. 'I0')",
                    },
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_averaged_scans",
            "description": "Plot averaged energy scans for multiple samples overlaid on one plot. Each sample is edge-step normalized and averaged, then plotted with standard deviation shading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of SPEC file names (one per sample) to compare.",
                    }
                },
                "required": ["file_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_scan_stack",
            "description": (
                "Overlay all reps of one sample on a single axis, color-progressed by rep order. "
                "Use to visually judge whether reps scatter symmetrically around a stable mean "
                "(converged), are still drifting in one direction (more reps needed or evolving "
                "sample), or are being burned away (damage). Pass numeric e_min/e_max to crop to "
                "the feature you care about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional but strongly recommended."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_first_half_vs_second_half",
            "description": (
                "Compare the average of the first half of reps to the second half, with SEM bands. "
                "Reports max |Δ|/SEM. <2σ: halves agree, sample is stationary. >3σ at any feature: "
                "the halves disagree, more reps may not help (drift, damage, or heterogeneity). "
                "This is the strongest single-glance test for whether the sample is publication-clean."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_running_average",
            "description": (
                "Plot the running average across reps as it evolves (one line per cumulative subset, "
                "color-progressed by rep #), with the final ±SEM band. Shows whether the running "
                "mean is still changing rep-over-rep at the feature of interest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_feature_evolution",
            "description": (
                "Plot a single per-rep scalar (the chosen statistic over [e_min, e_max]) versus rep "
                "number, with running mean and ±SEM band. The visual companion to "
                "analyze_feature_evolution. Use to confirm a feature has flatlined; a still-trending "
                "trace means the feature is not yet converged regardless of whole-spectrum verdicts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). REQUIRED."},
                    "e_max": {"type": "number", "description": "Upper bound (eV). REQUIRED."},
                    "statistic": {
                        "type": "string",
                        "enum": ["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                        "default": "max",
                        "description": "Reduction over the window. See analyze_feature_evolution for guidance.",
                    },
                },
                "required": ["file_name", "e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_data",
            "description": "General-purpose plotting tool. Plot any data as a line chart. Use this to visualize results from other tools (e.g. read_scan). Supports multiple series on one plot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "X-axis values.",
                    },
                    "y": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Y-axis values (same length as x).",
                    },
                    "y2": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional second series Y values.",
                    },
                    "y3": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional third series Y values.",
                    },
                    "y4": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional fourth series Y values.",
                    },
                    "xlabel": {"type": "string", "description": "X-axis label."},
                    "ylabel": {"type": "string", "description": "Y-axis label."},
                    "title": {"type": "string", "description": "Plot title."},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Legend labels for each series.",
                    },
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List non-SPEC files in the scan directory (macros, configs, text files).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (default: *). Example: *.mac",
                        "default": "*",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the scan directory. Use list_files to discover available files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the scan directory (e.g. run01.mac)",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_summary",
            "description": "Save a conversation summary as a timestamped .txt file in the scan directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The summary text to write.",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_macro",
            "description": "Save an edited macro as a new .mac file in the scan directory. The file is saved with a _heroic_<date> suffix to preserve the original.",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_name": {
                        "type": "string",
                        "description": "Original macro filename (e.g. run01.mac).",
                    },
                    "content": {
                        "type": "string",
                        "description": "The edited macro content.",
                    },
                },
                "required": ["original_name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_plan",
            "description": (
                "Save a markdown plan to the project's logs/plans/ directory. Use this at the "
                "start of a beamline-optimization session (or any multi-step task) to "
                "persist the step-by-step plan you generated, so future sessions can "
                "review what was attempted and why."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "Filename for the plan. Must end with .md and contain only "
                            "alphanumerics, underscore, hyphen, dot. No path separators "
                            "or directory traversal."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown body of the plan.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "If false (default), refuse to write when the file already "
                            "exists. Set true to overwrite an existing plan."
                        ),
                        "default": False,
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_motor_config",
            "description": "Get SPEC motor configuration from the config file. Shows controller, steps/unit, slew rate, flags, mnemonic, and name for each motor. Motor index (MOTnnn) maps to the A[] array.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_counter_config",
            "description": "Get SPEC counter configuration from the config file. Shows controller, unit, channel, scale, flags, mnemonic, and name for each counter. Counter index (CNTnnn) maps to the S[] array.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_spec_macro",
            "description": (
                "Run a SPEC macro in a disposable, network-isolated sandbox container. "
                "Returns JSON with an `output` key containing the clean command result "
                "and a `log` key with the full session transcript (startup noise included). "
                "Use `output` for parsing; use `log` only for debugging. "
                "Each call is a cold start: no state persists between calls. "
                "Sim-only — does not affect real hardware. Always check `output` even "
                "on ok=True; SPEC sometimes exits 0 despite warnings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "macro": {
                        "type": "string",
                        "description": (
                            "SPEC macro source to evaluate. Single command, sequence, "
                            "or full def block. Do not include a trailing 'exit'."
                        ),
                    },
                    "preload": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional filenames under /usr/local/lib/spec.d/ to qdo "
                            "before running the macro (e.g. 'beamline_align.mac'). "
                            "Plain filenames only — no path components."
                        ),
                    },
                    "timeout_s": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 300,
                        "description": (
                            "Hard kill timeout for the SPEC run in seconds (default 30). "
                            "Sim mode skips real motion so most runs finish in under a second."
                        ),
                    },
                },
                "required": ["macro"],
            },
        },
    },
]

# Single tool definition for CLI mode
CLI_TOOL_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a beamtimehero CLI command to query beamline data, logs, and plots. "
                "Start with 'beamtimehero --help' to discover available commands. "
                "Use 'beamtimehero <command> --help' to see options for a specific command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full CLI command string to execute (e.g. 'beamtimehero list-scans --limit 5')",
                    }
                },
                "required": ["command"],
            },
        },
    },
]
