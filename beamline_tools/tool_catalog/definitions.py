"""Autonomy-only tool schemas (CAT-8 orchestration).

The 82 upstream tool schemas (CAT-0..CAT-7, CAT-9) live in
`beamtimehero_cli.tool_catalog.definitions.AUTONOMY_TOOL_DEFINITIONS`.
This module only defines the 22 CAT-8 orchestration tools that are
autonomy-specific (plan edits, intervention requests, sample/holder
budgets, etc.). The package's `__init__.py` concatenates the two
lists into a single `TOOL_DEFINITIONS` view.
"""

# ---- Shared schema fragments -----------------------------------------------

_J = {
    "justification": {
        "type": "string",
        "description": (
            "REQUIRED for any SPEC-mutating action. Explain in one sentence "
            "why you are taking this action right now (will be stored in "
            "action_log). Empty / missing justifications are rejected."
        ),
    },
}

AUTONOMY_TOOL_DEFINITIONS = [
    # -----------------------------------------------------------------
    # CAT-8 · Orchestration
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "request_human_intervention",
            "description": (
                "Pause the agent and ask a human to complete a physical action "
                "(crystal install, sample mount, foil insert, etc.). Posts to Slack "
                "and blocks until resolved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "crystal_install", "sample_mount", "foil_insert",
                            "hardware_reset", "custom",
                        ],
                    },
                    "detail": {"type": "string", "description": "What you want the human to do."},
                },
                "required": ["kind", "detail"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_status_update",
            "description": "Post a high-level progress message to Slack + UI.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_status_assessment",
            "description": (
                "Append the planner's STATUS ASSESSMENT block to "
                "logs/status_assessments_<experiment_id>.jsonl. File-only "
                "record (does not post to Slack)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Replace the live experiment plan JSON (structure decided by the agent).",
            "parameters": {
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_sample_progress",
            "description": "Update per-sample status (snr_estimate, efficiency_verdict, reps_completed, note).",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["queued", "in_progress", "done", "skipped", "failed"]},
                    "snr_estimate": {"type": "number"},
                    "efficiency_verdict": {"type": "string",
                                           "enum": ["needs_more", "reasonable", "marginal", "wasteful"]},
                    "reps_completed": {"type": "integer"},
                    "note": {"type": "string"},
                },
                "required": ["sample_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_convergence_stats",
            "description": (
                "Store per-sample convergence statistics from the latest "
                "analysis run. The orchestrator reads these to auto-generate "
                "a statistics trend plot on the dashboard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "stats": {
                        "type": "object",
                        "description": (
                            "Convergence statistics dict with keys: "
                            "feature_window_eV ([e_min, e_max]), statistic, "
                            "cumulative_cv_pct (array from analyze-efficiency), "
                            "running_sem_frac (array from analyze-feature-evolution), "
                            "efficiency_verdict, feature_verdict."
                        ),
                    },
                },
                "required": ["sample_id", "stats"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan",
            "description": "Return the live experiment plan (config + sample queue + budget).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_config",
            "description": (
                "Return the operator-entered experiment configuration "
                "straight from the DB: experiment-level settings (mono "
                "crystal, beam size, mirrors, sample env, data path), "
                "the configured elements (edges, energies, crystal/HKL, "
                "vortex counter mnemonic — vortDT/vortDT2/vortDT3/vortDT4), "
                "and every sample holder with its "
                "samples (positions, gains, XAS/RIXS plan). Use this "
                "when you need ground truth from the /config form, "
                "independent of the live plan JSON."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_remaining_beamtime",
            "description": (
                "Hours from now until Experiment.end_time. Returns "
                "{remaining_hours, end_time} — or both null with a "
                "note if the operator has not yet called "
                "set_experiment_end_time."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_experiment_end_time",
            "description": (
                "Set the absolute end-of-beamtime timestamp on the "
                "active experiment. Accepts ISO-8601 `end_time` OR "
                "`hours_from_now` (one or the other, not both)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "end_time": {
                        "type": "string",
                        "description": "ISO-8601 timestamp (e.g. '2026-05-10T18:00:00').",
                    },
                    "hours_from_now": {
                        "type": "number",
                        "description": "Hours from current time.",
                    },
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_staff_guidance",
            "description": "Recent staff / user guidance messages (Slack or web).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_interventions",
            "description": "List pause-for-human requests still waiting.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_sample_time_budget",
            "description": (
                "Adjust the time budget for a single sample. Tweak any "
                "of: per-rep count_time_s, total reps, reps_per_spot "
                "(int = even split, list[int] = explicit per-spot), "
                "n_spots. Optionally restrict to one mode ('xas' or "
                "'emiss')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "count_time_s": {"type": "number",
                                     "description": "Per-point count time in seconds."},
                    "reps": {"type": "integer",
                             "description": "Total number of repetitions across all spots."},
                    "reps_per_spot": {
                        "description": (
                            "Either an integer (even split: every spot gets this many) "
                            "or a list of integers (explicit per-spot reps; length "
                            "implies n_spots and total reps = sum)."
                        ),
                    },
                    "n_spots": {"type": "integer",
                                "description": "Number of spots to visit on this sample."},
                    "mode": {"type": "string", "enum": ["xas", "emiss"],
                             "description": "Restrict the change to this mode (optional)."},
                    "reason": {"type": "string",
                               "description": "Short rationale; written to the plan edit log."},
                },
                "required": ["sample_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_holder_time_budget",
            "description": (
                "Set a default per-sample time budget for an entire sample holder. "
                "Stored under the plan's holder_budgets so new samples inherit it; "
                "when apply_to_existing=true (default), existing samples on that "
                "holder also get the new count_time/reps. Can also set a stop_time "
                "(absolute deadline) or hours_remaining (relative deadline) on the "
                "holder row — the holder's collection should finish by that time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_id": {"type": "string",
                                  "description": "Leave blank to apply to every holder."},
                    "count_time_s": {"type": "number"},
                    "reps": {"type": "integer"},
                    "mode": {"type": "string", "enum": ["xas", "emiss"]},
                    "apply_to_existing": {"type": "boolean", "default": True},
                    "stop_time": {
                        "type": "string",
                        "description": "ISO-8601 absolute deadline (e.g. '2026-05-10T18:00:00').",
                    },
                    "hours_remaining": {
                        "type": "number",
                        "description": "Hours from now until the holder deadline. Mutually exclusive with stop_time.",
                    },
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_holder_time_budget",
            "description": (
                "Return the time budget for one or all holders: beamtime_hours, "
                "stop_time (absolute deadline), and hours_remaining (computed). "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_id": {
                        "type": "string",
                        "description": "Optional; omit to return all holders.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scans_since_last_plan_update",
            "description": (
                "Return every CollectionScan row whose timestamp is "
                "newer than the live ExperimentPlan.updated_at. Used by "
                "the Planner to see what data has been collected since "
                "it last revised the plan. Sample names are joined in "
                "from SamplePosition. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string",
                                      "description": "Optional override; defaults to active experiment."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scans_for_active_sample",
            "description": (
                "Return every CollectionScan for the currently-active "
                "sample. The active sample is the lowest-queue-order "
                "entry in plan_json's sample_queue whose status is not "
                "'done' (or the explicit `active_sample_id` plan flag, "
                "if set). Pass `sample_id` to override the auto-detect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string",
                                  "description": "Override auto-detected active sample."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_sample_alignment_results",
            "description": (
                "Persist Sample-Alignment agent results to SamplePosition. "
                "Stores per-sample stage boundaries (sx/sy/sz lo/hi), "
                "measured emission energy, suggested starting filter, and "
                "count rate. Called once per sample after the alignment "
                "recipe completes. Justification is required (write op)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "results": {
                        "type": "array",
                        "description": "One entry per aligned sample.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sample_id": {"type": "string"},
                                "sx_lo": {"type": "number", "description": "Sx lower bound"},
                                "sx_hi": {"type": "number", "description": "Sx upper bound"},
                                "sy_lo": {"type": "number", "description": "Sy lower bound"},
                                "sy_hi": {"type": "number", "description": "Sy upper bound"},
                                "sz_lo": {"type": "number", "description": "Sz lower bound"},
                                "sz_hi": {"type": "number", "description": "Sz upper bound"},
                                "emiss_energy_eV": {"type": "number",
                                                    "description": "Measured optimal emission energy (eV)."},
                                "suggested_filter": {"type": "integer", "minimum": 0,
                                                     "description": "Starting filter count for this sample."},
                                "counts_per_sec": {"type": "number", "minimum": 0,
                                                   "description": "Measured count rate at alignment energy."},
                            },
                            "required": ["sample_id", "sx_lo", "sx_hi",
                                         "sy_lo", "sy_hi", "sz_lo", "sz_hi"],
                        },
                    },
                },
                "required": ["justification", "results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_sample_survey_results",
            "description": (
                "Persist Sample-Surveyor results to SamplePosition. "
                "For each entry, overwrites xas_filter with the "
                "filter_count and stores counts_per_sec, survey energy, "
                "and notes. Justification is required (this is a write)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "results": {
                        "type": "array",
                        "description": "One entry per surveyed sample.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sample_id": {"type": "string"},
                                "filter_count": {"type": "integer", "minimum": 0},
                                "counts_per_sec": {"type": "number", "minimum": 0},
                                "survey_energy_ev": {"type": "number"},
                                "notes": {"type": "string"},
                            },
                            "required": ["sample_id", "filter_count", "counts_per_sec"],
                        },
                    },
                },
                "required": ["justification", "results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_comprehensive_collection_plan",
            "description": (
                "Return the per-sample/spot/filter/n_scans plan that "
                "Data Collection executes against. Synthesizes from "
                "ExperimentPlan.plan_json plus SamplePosition rows "
                "(filter_count = xas_filter, counts_per_sec = "
                "survey_counts_per_sec). planned_scans_total comes "
                "from plan_json when set, falling back to xas_reps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_holder_id": {"type": "string",
                                         "description": "Optional; defaults to the active holder."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_completed_scan",
            "description": (
                "Insert a CollectionScan row keyed by sample_id + "
                "scan_number after a successful run_xas (or sibling "
                "technique). Auto-fills `sample_id` from the active "
                "sample in plan_json, `scan_number` from "
                "get_scan_number, and `spec_datafile` from "
                "get_current_datafile when omitted. The scan row is "
                "what makes the run visible to the Planner's "
                "convergence analysis and to the orchestrator's plan "
                "summary (recent_plots lookup). Justification is "
                "required so the action is auditable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "sample_id": {
                        "type": "string",
                        "description": (
                            "Sample to credit the scan to. Defaults to "
                            "the active sample in plan_json (explicit "
                            "active_sample_id, else the lowest-queue-"
                            "order sample whose status is not "
                            "done/skipped)."
                        ),
                    },
                    "scan_number": {
                        "type": "integer",
                        "description": (
                            "SPEC scan number. Defaults to the latest "
                            "scan number from get_scan_number."
                        ),
                    },
                    "technique": {
                        "type": "string",
                        "enum": ["xas", "herfd", "rixs", "vtc"],
                        "default": "xas",
                        "description": "Acquisition technique. Default 'xas'.",
                    },
                    "filter_setting": {
                        "type": "integer",
                        "description": "Filter bitmask used for the scan.",
                    },
                    "count_time": {
                        "type": "number",
                        "description": "Per-point count time in seconds.",
                    },
                    "spec_datafile": {
                        "type": "string",
                        "description": (
                            "SPEC datafile path or basename. Defaults "
                            "to get_current_datafile."
                        ),
                    },
                    "spot_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "0-based spot index within the sample. "
                            "Required for multi-spot samples so the "
                            "comprehensive plan can return per-spot "
                            "remaining reps."
                        ),
                    },
                },
                "required": ["justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regenerate_plan",
            "description": (
                "Rebuild the sample plan from the database while preserving per-sample "
                "progress (status, reps_completed, notes) and user overrides "
                "(thresholds, holder_budgets, budget). Call this after a new sample "
                "holder is configured or an existing one is edited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "beamtime_hours": {"type": "number",
                                       "description": "Optional new total (default: keep current)."},
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
]

# Category map for the sidebar — autonomy-only categories.
# (Upstream's CAT-0..CAT-7, CAT-9 lists are concatenated by the package
# __init__.) Only CAT-8 is autonomy-specific.
AUTONOMY_TOOL_CATEGORIES = [
    ("CAT-8 Orchestration", [
        "request_human_intervention", "post_status_update",
        "log_status_assessment",
        "update_plan", "record_sample_progress", "get_plan",
        "get_experiment_config",
        "get_scans_since_last_plan_update", "get_scans_for_active_sample",
        "upload_sample_alignment_results",
        "upload_sample_survey_results", "get_comprehensive_collection_plan",
        "get_remaining_beamtime", "get_staff_guidance", "list_open_interventions",
        "set_sample_time_budget", "set_holder_time_budget",
        "get_holder_time_budget",
        "set_experiment_end_time", "regenerate_plan",
        "record_completed_scan", "record_convergence_stats",
    ]),
]
