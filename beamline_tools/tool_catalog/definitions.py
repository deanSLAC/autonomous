"""Autonomy-only tool schemas (CAT-8 orchestration).

The 82 upstream tool schemas (CAT-0..CAT-7, CAT-9) live in
`beamtimehero_cli.tool_catalog.definitions.AUTONOMY_TOOL_DEFINITIONS`.
This module only defines the 23 CAT-8 orchestration tools that are
autonomy-specific (plan edits, intervention requests, sample/holder
budgets, etc.). The package's `__init__.py` concatenates the two
lists into a single `TOOL_DEFINITIONS` view.

The parameter schemas are generated from the pydantic arg models in
`arg_models.py` (the single source of truth for the CAT-8 argument
surface) via `to_function_schema`, which emits only the vocabulary
upstream's CLI `add_arg` understands: per-property type / description /
default / enum plus the `required` list.
"""

from beamline_tools.tool_catalog.arg_models import (
    ARG_MODELS,
    to_function_schema,
)

# ---- Per-tool descriptions (LLM-facing, one entry per CAT-8 tool) -----------

TOOL_DESCRIPTIONS: dict[str, str] = {
    "request_human_intervention": (
        "Pause the agent and ask a human to complete a physical action "
        "(crystal install, sample mount, foil insert, etc.). Posts to Slack "
        "and blocks until resolved."
    ),
    "post_status_update": "Post a high-level progress message to Slack + UI.",
    "log_status_assessment": (
        "Append the planner's STATUS ASSESSMENT block to "
        "logs/status_assessments_<experiment_id>.jsonl. File-only "
        "record (does not post to Slack)."
    ),
    "update_plan": (
        "Replace the live experiment plan JSON (structure decided by the agent)."
    ),
    "record_sample_progress": (
        "Update per-sample status (snr_estimate, efficiency_verdict, "
        "reps_completed, note)."
    ),
    "record_convergence_stats": (
        "Store per-sample convergence statistics from the latest "
        "analysis run. The orchestrator reads these to auto-generate "
        "a statistics trend plot on the dashboard."
    ),
    "get_plan": "Return the live experiment plan (config + sample queue + budget).",
    "get_experiment_config": (
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
    "get_remaining_beamtime": (
        "Hours from now until Experiment.end_time. Returns "
        "{remaining_hours, end_time} — or both null with a "
        "note if the operator has not yet called "
        "set_experiment_end_time."
    ),
    "set_experiment_end_time": (
        "Set the absolute end-of-beamtime timestamp on the "
        "active experiment. Accepts ISO-8601 `end_time` OR "
        "`hours_from_now` (one or the other, not both)."
    ),
    "get_staff_guidance": "Recent staff / user guidance messages (Slack or web).",
    "list_open_interventions": "List pause-for-human requests still waiting.",
    "set_sample_time_budget": (
        "Adjust the time budget for a single sample. Tweak any "
        "of: per-rep count_time_s, total reps, reps_per_spot "
        "(int = even split, list[int] = explicit per-spot), "
        "n_spots. Optionally restrict to one mode ('xas' or "
        "'emiss')."
    ),
    "set_holder_time_budget": (
        "Set a default per-sample time budget for an entire sample holder. "
        "Stored under the plan's holder_budgets so new samples inherit it; "
        "when apply_to_existing=true (default), existing samples on that "
        "holder also get the new count_time/reps. Can also set a stop_time "
        "(absolute deadline) or hours_remaining (relative deadline) on the "
        "holder row — the holder's collection should finish by that time."
    ),
    "get_holder_time_budget": (
        "Return the time budget for one or all holders: beamtime_hours, "
        "stop_time (absolute deadline), and hours_remaining (computed). "
        "Read-only."
    ),
    "get_scans_since_last_plan_update": (
        "Return every CollectionScan row whose timestamp is "
        "newer than the live ExperimentPlan.updated_at. Used by "
        "the Planner to see what data has been collected since "
        "it last revised the plan. Sample names are joined in "
        "from SamplePosition. Read-only."
    ),
    "get_scans_for_active_sample": (
        "Return every CollectionScan for the currently-active "
        "sample. The active sample is the lowest-queue-order "
        "entry in plan_json's sample_queue whose status is not "
        "'done' (or the explicit `active_sample_id` plan flag, "
        "if set). Pass `sample_id` to override the auto-detect."
    ),
    "upload_sample_alignment_results": (
        "Persist Sample-Alignment agent results to SamplePosition. "
        "Stores per-sample stage boundaries (sx/sy/sz lo/hi), "
        "measured emission energy, suggested starting filter, and "
        "count rate. Called once per sample after the alignment "
        "recipe completes. Justification is required (write op)."
    ),
    "upload_sample_survey_results": (
        "Persist Sample-Surveyor results to SamplePosition. "
        "For each entry, overwrites xas_filter with the "
        "filter_count and stores counts_per_sec, survey energy, "
        "and notes. Justification is required (this is a write)."
    ),
    "get_comprehensive_collection_plan": (
        "Return the per-sample/spot/filter/n_scans plan that "
        "Data Collection executes against. Synthesizes from "
        "ExperimentPlan.plan_json plus SamplePosition rows "
        "(filter_count = xas_filter, counts_per_sec = "
        "survey_counts_per_sec). planned_scans_total comes "
        "from plan_json when set, falling back to xas_reps."
    ),
    "record_completed_scan": (
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
    "record_alignment_flux": (
        "Persist the beamline-alignment flux deliverable to the active "
        "experiment: maximum recorded I0/I1 rate (cps) from the best "
        "post-optimization get_counts, plus the gain setting each "
        "detector was at. Called once by the bl-aligner at completion; "
        "surfaced on the alignment summary report. Justification is "
        "required (write op)."
    ),
    "regenerate_plan": (
        "Rebuild the sample plan from the database while preserving per-sample "
        "progress (status, reps_completed, notes) and user overrides "
        "(thresholds, holder_budgets, budget). Call this after a new sample "
        "holder is configured or an existing one is edited."
    ),
}

# ---- Generated tool definitions ---------------------------------------------
# Order follows ARG_MODELS insertion order (the canonical CAT-8 order).

AUTONOMY_TOOL_DEFINITIONS = [
    to_function_schema(name, TOOL_DESCRIPTIONS[name], model_cls)
    for name, model_cls in ARG_MODELS.items()
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
        "record_alignment_flux",
    ]),
]
