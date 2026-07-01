"""Per-tool lineage metadata for the /tools catalog page (autonomy-only).

Upstream tools (CAT-0..CAT-7, CAT-9) ship their own lineage entries in
`beamtimehero_cli.tool_catalog.lineage.TOOL_LINEAGE`. This module
defines the CAT-8 orchestration entries that are autonomy-specific
and merges the two dicts so the UI sees a single `TOOL_LINEAGE` view.

The helper functions (`extract_inputs`, `build_detailed_tool`) are
re-exported from upstream so existing consumers
(`from beamline_tools.tool_catalog.lineage import build_detailed_tool`)
keep working.

Schema per entry:

    long_description : str
        A few sentences elaborating on the one-line schema description.
    python_func : str
        The concrete Python call chain the executor performs. Shown in
        the UI so operators can trace a tool call to its implementation.
    spec_command : str | None
        The literal SPEC macro/command string (or multi-call chain) sent
        to the running SPEC session. ``None`` for tools that don't touch
        SPEC. Tools with a non-None value appear in the "SPEC-bound"
        section of the page.
    output : str
        One-line description of what the tool returns.
    source : str
        Enum. Used to group tools visually and to colour the source
        badge. Values:
          * ``spec_datafile``  — reads a .dat SPEC file from BL_SCAN_DIR
          * ``spec_session``   — issues a command to the live SPEC session
          * ``spec_logfile``   — reads beamline control log files
          * ``spec_config``    — reads SPEC's config file
          * ``autonomy_db``    — reads/writes the autonomy SQLite DB
          * ``filesystem``     — non-SPEC files in the scan directory
          * ``tool_chain``     — consumes the output of another tool
          * ``slack``          — sends a message to staff Slack
    source_detail : str
        Human-readable specifics about where the data comes from.
    depends_on : list[str]
        Other tools typically called first to obtain required arguments
        (e.g. ``list_scans`` before ``read_scan``). Empty when the tool
        has no prerequisite in the tool chain.
"""

from __future__ import annotations

from beamtimehero_cli.tool_catalog.lineage import (
    TOOL_LINEAGE as _UPSTREAM_LINEAGE,
    build_detailed_tool,
    extract_inputs,
)


_AUTONOMY_LINEAGE: dict[str, dict] = {

    # ---------- Autonomy tools — CAT-8: orchestration (no SPEC) -------------

    "request_human_intervention": {
        "long_description": (
            "Pause the agent and ask a human to perform a physical "
            "action (crystal install, sample mount, foil insert, "
            "hardware reset, or custom). Posts to Slack and blocks "
            "until staff resolves it from the dashboard or Slack."
        ),
        "python_func": "orchestrator.staff_guidance.coordinator.request_intervention(...)",
        "spec_command": None,
        "output": "JSON: {resolved, note, resolver}",
        "source": "autonomy_db",
        "source_detail": "Intervention row stored in autonomy DB; notification dispatched to Slack bridge.",
        "depends_on": [],
    },
    "post_status_update": {
        "long_description": (
            "Post a high-level progress message to Slack and the "
            "dashboard feed. Informational — does not block or gate "
            "anything."
        ),
        "python_func": "orchestrator.loop.get_orchestrator().slack_status_post(text)",
        "spec_command": None,
        "output": "JSON: {posted}",
        "source": "slack",
        "source_detail": "Also emits a dashboard WebSocket event.",
        "depends_on": [],
    },
    "log_status_assessment": {
        "long_description": (
            "Append the planner's STATUS ASSESSMENT block to a "
            "per-experiment JSONL file under logs/. Canonical record "
            "of the per-spawn assessment — separate from Slack."
        ),
        "python_func": "open(logs/status_assessments_<experiment_id>.jsonl, 'a').write(record)",
        "spec_command": None,
        "output": "JSON: {logged, path, spawn}",
        "source": "filesystem",
        "source_detail": "Writes one JSON record per call to logs/status_assessments_<experiment_id>.jsonl.",
        "depends_on": [],
    },
    "update_plan": {
        "long_description": (
            "Replace the live experiment plan JSON wholesale. The "
            "structure is up to the agent, but downstream views expect "
            "a sample_queue + holder_budgets + budget shape."
        ),
        "python_func": "orchestrator.planner.replace_plan(experiment_id, new_plan)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Writes the plan JSON onto the experiment row.",
        "depends_on": ["get_plan"],
    },
    "record_convergence_stats": {
        "long_description": (
            "Store per-sample convergence statistics (cumulative CV, "
            "feature SEM, verdicts, feature window) so the orchestrator "
            "can render a live statistics trend plot on the dashboard."
        ),
        "python_func": "orchestrator.planner.record_convergence_stats(experiment_id, sample_id, stats)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Writes convergence_stats onto a sample entry in the plan JSON.",
        "depends_on": ["analyze_efficiency"],
    },
    "record_sample_progress": {
        "long_description": (
            "Update per-sample status (queued/in_progress/done/skipped/"
            "failed), SNR estimate, efficiency verdict, and reps "
            "completed. Preserves the rest of the plan."
        ),
        "python_func": "orchestrator.planner.record_sample_progress(experiment_id, sample_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Patches a single sample row inside the plan JSON.",
        "depends_on": ["analyze_efficiency"],
    },
    "get_plan": {
        "long_description": (
            "Return the live experiment plan — config, sample queue, "
            "holder budgets, and the beamtime budget."
        ),
        "python_func": "db.autonomy_client.get_plan(experiment_id)",
        "spec_command": None,
        "output": "JSON: the full plan object",
        "source": "autonomy_db",
        "source_detail": "Read-only query against the autonomy SQLite DB.",
        "depends_on": [],
    },
    "get_experiment_config": {
        "long_description": (
            "Return the operator-entered experiment configuration "
            "from the DB: experiment-level settings (mono crystal, "
            "beam, mirrors, sample env, data path), the configured "
            "elements, and every sample holder with its samples. "
            "This is the canonical record of what the user entered "
            "in the /config form — distinct from get_plan, which "
            "returns the live planner state."
        ),
        "python_func": (
            "session.get(Experiment, experiment_id) + ExperimentElement "
            "+ SampleHolder + SamplePosition rows"
        ),
        "spec_command": None,
        "output": "JSON: {experiment, elements[], sample_holders[{samples[]}]}",
        "source": "autonomy_db",
        "source_detail": "Read-only query against the autonomy SQLite DB.",
        "depends_on": [],
    },
    "get_remaining_beamtime": {
        "long_description": (
            "Hours from now until Experiment.end_time. Returns "
            "{remaining_hours, end_time}; both null if end_time has "
            "not been set yet."
        ),
        "python_func": "orchestrator.planner.snapshot(experiment_id)",
        "spec_command": None,
        "output": "JSON: {remaining_hours, end_time}",
        "source": "autonomy_db",
        "source_detail": "end_time lives on Experiment; this tool just subtracts now().",
        "depends_on": ["set_experiment_end_time"],
    },
    "set_experiment_end_time": {
        "long_description": (
            "Set Experiment.end_time. The planner's remaining-beamtime "
            "math is end_time - now(). Accepts ISO-8601 end_time or "
            "hours_from_now."
        ),
        "python_func": "orchestrator.plan_store.session.set_experiment_end_time(...)",
        "spec_command": None,
        "output": "JSON: {ok, end_time, remaining_hours}",
        "source": "autonomy_db",
        "source_detail": "Audit-logged as a plan_edit.",
        "depends_on": [],
    },
    "get_staff_guidance": {
        "long_description": (
            "Recent staff/user guidance messages — either typed into "
            "the dashboard guidance panel or posted to Slack."
        ),
        "python_func": "db.autonomy_client.list_guidance(experiment_id, limit)",
        "spec_command": None,
        "output": "JSON array: [{timestamp, author, text}, ...]",
        "source": "autonomy_db",
        "source_detail": "Guidance rows persisted to the autonomy DB.",
        "depends_on": [],
    },
    "list_open_interventions": {
        "long_description": (
            "List pause-for-human requests that are still waiting for "
            "staff to resolve."
        ),
        "python_func": "db.autonomy_client.list_open_interventions(experiment_id)",
        "spec_command": None,
        "output": "JSON array: [{id, kind, detail, created_at}, ...]",
        "source": "autonomy_db",
        "source_detail": "Sibling table to request_human_intervention.",
        "depends_on": ["request_human_intervention"],
    },
    "set_sample_time_budget": {
        "long_description": (
            "Adjust the time budget for a single sample — change the "
            "per-rep count_time and/or the number of reps. Mode "
            "restricts the change to one of xas or emiss."
        ),
        "python_func": "orchestrator.planner.set_sample_time_budget(experiment_id, sample_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Also logs a plan_edit audit row.",
        "depends_on": ["get_plan"],
    },
    "set_holder_time_budget": {
        "long_description": (
            "Set a default per-sample time budget for a whole sample "
            "holder. New samples inherit the default; when "
            "apply_to_existing is true (default), existing samples on "
            "that holder also pick up the change."
        ),
        "python_func": "orchestrator.planner.set_holder_time_budget(experiment_id, holder_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok, samples_updated}",
        "source": "autonomy_db",
        "source_detail": "Stored under plan.holder_budgets; audit-logged as a plan_edit.",
        "depends_on": [],
    },
    "regenerate_plan": {
        "long_description": (
            "Rebuild the sample plan from the DB while preserving "
            "per-sample progress (status, reps_completed, notes) and "
            "user overrides (thresholds, holder_budgets, total budget). "
            "Call this after a sample holder is added or edited."
        ),
        "python_func": "orchestrator.planner.rebuild_plan_preserving_progress(experiment_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok, sample_count}",
        "source": "autonomy_db",
        "source_detail": "Rewrites the plan JSON in place.",
        "depends_on": ["get_plan"],
    },
    "get_scans_since_last_plan_update": {
        "long_description": (
            "Return the list of CollectionScan rows whose timestamp is "
            "newer than the live ExperimentPlan.updated_at. Lets the "
            "Planner see exactly what data has been collected since the "
            "plan was last revised."
        ),
        "python_func": (
            "plan_store.session.get_collection_scans_since(experiment_id, "
            "ExperimentPlan.updated_at)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, plan_updated_at, count, scans:[{scan_number, sample_id, sample_name, technique, filter_setting, count_time, timestamp, spec_datafile}]}",
        "source": "autonomy_db",
        "source_detail": "Joins CollectionScan with SamplePosition for sample_name.",
        "depends_on": ["get_plan", "update_plan"],
    },
    "get_scans_for_active_sample": {
        "long_description": (
            "Return every CollectionScan for the currently-active "
            "sample. Active = plan_json.active_sample_id (if set) else "
            "the lowest-queue-order sample whose status is not 'done' "
            "or 'skipped'. `sample_id` overrides the auto-detect."
        ),
        "python_func": (
            "plan_store.session.get_collection_scans_for_sample(active_sample_id)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, sample_id, sample_name, count, scans:[...]}",
        "source": "autonomy_db",
        "source_detail": "Reads plan_json to detect the active sample, then joins SamplePosition.",
        "depends_on": ["get_plan"],
    },
    "upload_sample_alignment_results": {
        "long_description": (
            "Persist Sample-Alignment agent outputs to SamplePosition rows. "
            "Stores per-sample stage boundaries (sx/sy/sz lo/hi), measured "
            "emission energy, suggested starting filter count, and count rate. "
            "Called once per sample after the alignment recipe completes."
        ),
        "python_func": "plan_store.session.submit_sample_alignment_results(results)",
        "spec_command": None,
        "output": "JSON: {ok, updated:[sample_ids], count}",
        "source": "autonomy_db",
        "source_detail": (
            "Mutates SamplePosition.sx_lo/sx_hi/sy_lo/sy_hi/sz_lo/sz_hi, "
            ".emiss_energy_eV, .xas_filter (from suggested_filter), "
            ".counts_per_sec (alignment-time reading)."
        ),
        "depends_on": [],
    },
    "upload_sample_survey_results": {
        "long_description": (
            "Persist Sample-Surveyor outputs to SamplePosition rows. "
            "filter_count overwrites xas_filter (so Data Collection picks "
            "it up); counts_per_sec is recorded as the survey reference "
            "rate. survey_energy_ev / notes are stored as-is. "
            "survey_completed_at is set to now()."
        ),
        "python_func": "plan_store.session.submit_survey_results(results)",
        "spec_command": None,
        "output": "JSON: {ok, updated:[sample_ids], count}",
        "source": "autonomy_db",
        "source_detail": (
            "Mutates SamplePosition.xas_filter, .survey_counts_per_sec, "
            ".survey_energy_ev, .survey_notes, .survey_completed_at."
        ),
        "depends_on": [],
    },
    "get_comprehensive_collection_plan": {
        "long_description": (
            "Return the per-sample/spot/filter/n_scans plan that Data "
            "Collection executes against. Synthesizes from "
            "ExperimentPlan.plan_json + SamplePosition rows + survey "
            "results (xas_filter, survey_counts_per_sec). "
            "planned_scans_total comes from plan_json's per-sample "
            "entry when set, falling back to xas_reps."
        ),
        "python_func": (
            "session.get(SampleHolder, ...) + SamplePosition rows + "
            "plan_store.client.get_plan(experiment_id)"
        ),
        "spec_command": None,
        "output": (
            "JSON: {ok, sample_holder_id, sample_holder_name, samples:["
            "{sample_id, sample_name, element_symbol, total_spots, "
            "filter_count, count_time, n_reps, counts_per_sec, "
            "planned_time_s, planned_scans_total}]}"
        ),
        "source": "autonomy_db",
        "source_detail": "Read-only synthesis across SampleHolder, SamplePosition, ExperimentPlan.",
        "depends_on": ["get_plan", "get_experiment_config"],
    },
    "record_completed_scan": {
        "long_description": (
            "Insert a CollectionScan row keyed by sample_id + "
            "scan_number after each successful run_xas (or sibling "
            "technique). Called by the Data Collection / Sample "
            "Surveyor agents between scans so the Planner's "
            "convergence analysis and the orchestrator's plan summary "
            "(recent_plots lookup) can see what's been collected. "
            "Auto-fills sample_id / scan_number / spec_datafile from "
            "the active context when omitted."
        ),
        "python_func": (
            "plan_store.session.create_collection_scan(experiment_id, "
            "sample_id, technique, scan_number, spec_datafile, "
            "filter_setting, count_time)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, scan_id, sample_id, sample_name, scan_number, technique}",
        "source": "autonomy_db",
        "source_detail": (
            "Inserts a CollectionScan row keyed by sample_id + "
            "scan_number; agents call this after each successful "
            "run_xas to make scans queryable for plan summaries and "
            "convergence analysis."
        ),
        "depends_on": ["get_scan_number", "get_current_datafile"],
    },
    "record_alignment_flux": {
        "long_description": (
            "Persist the beamline-alignment flux deliverable to the "
            "active Experiment row: maximum recorded I0/I1 rate "
            "(SPEAR-normalized cps) from the best post-optimization "
            "get_counts, plus the SRS gain each detector was at. "
            "Called once by the bl-aligner at completion so the "
            "numbers survive the agent run and appear on the "
            "alignment summary report footer."
        ),
        "python_func": (
            "plan_store.session.record_alignment_flux(experiment_id, "
            "i0_max_cps, i0_gain, i1_max_cps, i1_gain)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, experiment_id, recorded:{...}}",
        "source": "autonomy_db",
        "source_detail": (
            "Mutates Experiment.i0_max_cps/.i0_gain/.i1_max_cps/"
            ".i1_gain on the active experiment."
        ),
        "depends_on": ["get_counts"],
    },
}


# Merge upstream's lineage (CAT-0..CAT-7, CAT-9 plus shared recent_actions /
# evaluate_spec_macro entries) with autonomy's CAT-8 entries. Autonomy keys
# win on collision so any future overrides take precedence.
TOOL_LINEAGE: dict[str, dict] = {**_UPSTREAM_LINEAGE, **_AUTONOMY_LINEAGE}


__all__ = [
    "TOOL_LINEAGE",
    "build_detailed_tool",
    "extract_inputs",
]
