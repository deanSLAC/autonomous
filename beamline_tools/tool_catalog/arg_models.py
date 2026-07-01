"""Pydantic argument models for the CAT-8 orchestration tools.

One ``BaseModel`` per autonomy tool. These models are the single source
of truth for the CAT-8 tool argument surface:

  * ``definitions.py`` generates the OpenAI-function-style JSON schemas
    from them via :func:`to_function_schema`.
  * ``executor.py`` validates incoming arguments against them before
    dispatch (boundary validation — handlers keep their dict interface).

Schema-vocabulary constraint: the generated parameter schemas are
consumed by upstream's ``beamtimehero_cli.cli.__main__.add_arg`` to
build argparse flags, which understands ONLY ``type`` (string / integer
/ number / boolean / array / object), ``description``, ``default``,
``enum``, and the ``required`` list. :func:`to_function_schema` emits
nothing outside that vocabulary — no ``$defs`` / ``$ref`` / ``anyOf`` /
``title`` keys and no nested item schemas. Per-item field documentation
for array params therefore lives in the param ``description`` string.
"""

from __future__ import annotations

import types
from typing import Literal, Optional, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

_JUSTIFICATION_DESC = (
    "REQUIRED for any SPEC-mutating action. Explain in one sentence "
    "why you are taking this action right now (will be stored in "
    "action_log). Empty / missing justifications are rejected."
)


class _ToolArgs(BaseModel):
    """Base for all CAT-8 arg models — unknown extra args pass through."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# CAT-8 · Orchestration arg models
# ---------------------------------------------------------------------------

class RequestHumanInterventionArgs(_ToolArgs):
    kind: Literal["crystal_install", "sample_mount", "foil_insert",
                  "hardware_reset", "custom"]
    detail: str = Field(description="What you want the human to do.")


class PostStatusUpdateArgs(_ToolArgs):
    text: str


class LogStatusAssessmentArgs(_ToolArgs):
    text: str


class UpdatePlanArgs(_ToolArgs):
    plan: dict


class RecordSampleProgressArgs(_ToolArgs):
    sample_id: str
    status: Optional[Literal["queued", "in_progress", "done",
                             "skipped", "failed"]] = None
    snr_estimate: Optional[float] = None
    efficiency_verdict: Optional[Literal["needs_more", "reasonable",
                                         "marginal", "wasteful"]] = None
    reps_completed: Optional[int] = None
    note: Optional[str] = None


class RecordConvergenceStatsArgs(_ToolArgs):
    sample_id: str
    stats: dict = Field(description=(
        "Convergence statistics dict with keys: "
        "feature_window_eV ([e_min, e_max]), statistic, "
        "cumulative_cv_pct (array from analyze-efficiency), "
        "running_sem_frac (array from analyze-feature-evolution), "
        "efficiency_verdict, feature_verdict."
    ))


class GetPlanArgs(_ToolArgs):
    pass


class GetExperimentConfigArgs(_ToolArgs):
    pass


class GetRemainingBeamtimeArgs(_ToolArgs):
    pass


class SetExperimentEndTimeArgs(_ToolArgs):
    end_time: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp (e.g. '2026-05-10T18:00:00').",
    )
    hours_from_now: Optional[float] = Field(
        default=None, description="Hours from current time.",
    )
    reason: Optional[str] = None


class GetStaffGuidanceArgs(_ToolArgs):
    limit: Optional[int] = None


class ListOpenInterventionsArgs(_ToolArgs):
    pass


class SetSampleTimeBudgetArgs(_ToolArgs):
    sample_id: str
    count_time_s: Optional[float] = Field(
        default=None, description="Per-point count time in seconds.",
    )
    reps: Optional[int] = Field(
        default=None,
        description="Total number of repetitions across all spots.",
    )
    reps_per_spot: Optional[Union[int, list]] = Field(
        default=None,
        description=(
            "Either an integer (even split: every spot gets this many) "
            "or a list of integers (explicit per-spot reps; length "
            "implies n_spots and total reps = sum)."
        ),
    )
    n_spots: Optional[int] = Field(
        default=None,
        description="Number of spots to visit on this sample.",
    )
    mode: Optional[Literal["xas", "emiss"]] = Field(
        default=None,
        description="Restrict the change to this mode (optional).",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Short rationale; written to the plan edit log.",
    )


class SetHolderTimeBudgetArgs(_ToolArgs):
    holder_id: Optional[str] = Field(
        default=None, description="Leave blank to apply to every holder.",
    )
    count_time_s: Optional[float] = None
    reps: Optional[int] = None
    mode: Optional[Literal["xas", "emiss"]] = None
    apply_to_existing: bool = True
    stop_time: Optional[str] = Field(
        default=None,
        description="ISO-8601 absolute deadline (e.g. '2026-05-10T18:00:00').",
    )
    hours_remaining: Optional[float] = Field(
        default=None,
        description=("Hours from now until the holder deadline. "
                     "Mutually exclusive with stop_time."),
    )
    reason: Optional[str] = None


class GetHolderTimeBudgetArgs(_ToolArgs):
    holder_id: Optional[str] = Field(
        default=None, description="Optional; omit to return all holders.",
    )


class GetScansSinceLastPlanUpdateArgs(_ToolArgs):
    experiment_id: Optional[str] = Field(
        default=None,
        description="Optional override; defaults to active experiment.",
    )


class GetScansForActiveSampleArgs(_ToolArgs):
    sample_id: Optional[str] = Field(
        default=None, description="Override auto-detected active sample.",
    )


class UploadSampleAlignmentResultsArgs(_ToolArgs):
    justification: str = Field(description=_JUSTIFICATION_DESC)
    results: list = Field(description=(
        "One entry per aligned sample. Each entry is an object with "
        "required keys sample_id (string) and sx_lo/sx_hi/sy_lo/sy_hi/"
        "sz_lo/sz_hi (numbers: Sx/Sy/Sz lower and upper bounds), plus "
        "optional emiss_energy_eV (number: measured optimal emission "
        "energy in eV), suggested_filter (integer >= 0: starting filter "
        "count for this sample), and counts_per_sec (number >= 0: "
        "measured count rate at alignment energy)."
    ))


class UploadSampleSurveyResultsArgs(_ToolArgs):
    justification: str = Field(description=_JUSTIFICATION_DESC)
    results: list = Field(description=(
        "One entry per surveyed sample. Each entry is an object with "
        "required keys sample_id (string), filter_count (integer >= 0), "
        "and counts_per_sec (number >= 0), plus optional "
        "survey_energy_ev (number) and notes (string)."
    ))


class GetComprehensiveCollectionPlanArgs(_ToolArgs):
    sample_holder_id: Optional[str] = Field(
        default=None, description="Optional; defaults to the active holder.",
    )


class RecordCompletedScanArgs(_ToolArgs):
    justification: str = Field(description=_JUSTIFICATION_DESC)
    sample_id: Optional[str] = Field(
        default=None,
        description=(
            "Sample to credit the scan to. Defaults to "
            "the active sample in plan_json (explicit "
            "active_sample_id, else the lowest-queue-"
            "order sample whose status is not "
            "done/skipped)."
        ),
    )
    scan_number: Optional[int] = Field(
        default=None,
        description=("SPEC scan number. Defaults to the latest "
                     "scan number from get_scan_number."),
    )
    technique: Literal["xas", "herfd", "rixs", "vtc"] = Field(
        default="xas", description="Acquisition technique. Default 'xas'.",
    )
    filter_setting: Optional[int] = Field(
        default=None, description="Filter bitmask used for the scan.",
    )
    count_time: Optional[float] = Field(
        default=None, description="Per-point count time in seconds.",
    )
    spec_datafile: Optional[str] = Field(
        default=None,
        description=("SPEC datafile path or basename. Defaults "
                     "to get_current_datafile."),
    )
    spot_index: Optional[int] = Field(
        default=None,
        description=(
            "0-based spot index within the sample (must be >= 0). "
            "Required for multi-spot samples so the "
            "comprehensive plan can return per-spot "
            "remaining reps."
        ),
    )


class RecordAlignmentFluxArgs(_ToolArgs):
    justification: str = Field(description=_JUSTIFICATION_DESC)
    i0_max_cps: Optional[float] = Field(
        default=None,
        description=("Maximum recorded I0 rate (SPEAR-normalized cps) "
                     "from the best post-optimization get_counts."),
    )
    i0_gain: Optional[str] = Field(
        default=None,
        description="I0 SRS gain the reading was taken at, e.g. '50 nA/V'.",
    )
    i1_max_cps: Optional[float] = Field(
        default=None,
        description=("Maximum recorded I1 rate (SPEAR-normalized cps) "
                     "from the best post-optimization get_counts."),
    )
    i1_gain: Optional[str] = Field(
        default=None,
        description="I1 SRS gain the reading was taken at, e.g. '1 mA/V'.",
    )


class RegeneratePlanArgs(_ToolArgs):
    beamtime_hours: Optional[float] = Field(
        default=None,
        description="Optional new total (default: keep current).",
    )
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry — tool name → arg model. Insertion order matches the canonical
# CAT-8 tool order in definitions.AUTONOMY_TOOL_DEFINITIONS.
# ---------------------------------------------------------------------------

ARG_MODELS: dict[str, type[BaseModel]] = {
    "request_human_intervention": RequestHumanInterventionArgs,
    "post_status_update": PostStatusUpdateArgs,
    "log_status_assessment": LogStatusAssessmentArgs,
    "update_plan": UpdatePlanArgs,
    "record_sample_progress": RecordSampleProgressArgs,
    "record_convergence_stats": RecordConvergenceStatsArgs,
    "get_plan": GetPlanArgs,
    "get_experiment_config": GetExperimentConfigArgs,
    "get_remaining_beamtime": GetRemainingBeamtimeArgs,
    "set_experiment_end_time": SetExperimentEndTimeArgs,
    "get_staff_guidance": GetStaffGuidanceArgs,
    "list_open_interventions": ListOpenInterventionsArgs,
    "set_sample_time_budget": SetSampleTimeBudgetArgs,
    "set_holder_time_budget": SetHolderTimeBudgetArgs,
    "get_holder_time_budget": GetHolderTimeBudgetArgs,
    "get_scans_since_last_plan_update": GetScansSinceLastPlanUpdateArgs,
    "get_scans_for_active_sample": GetScansForActiveSampleArgs,
    "upload_sample_alignment_results": UploadSampleAlignmentResultsArgs,
    "upload_sample_survey_results": UploadSampleSurveyResultsArgs,
    "get_comprehensive_collection_plan": GetComprehensiveCollectionPlanArgs,
    "record_completed_scan": RecordCompletedScanArgs,
    "record_alignment_flux": RecordAlignmentFluxArgs,
    "regenerate_plan": RegeneratePlanArgs,
}


# ---------------------------------------------------------------------------
# Model → OpenAI-function-style schema converter
# ---------------------------------------------------------------------------

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    bool: "boolean",  # before int: bool is an int subclass
    int: "integer",
    float: "number",
    list: "array",
    dict: "object",
}


def _json_types_for(annotation) -> tuple[list[str], list | None]:
    """Map a model field annotation to (json_type_names, enum_values).

    ``Optional[X]`` strips to X. A ``Union`` of multiple JSON types
    (e.g. ``int | list``) returns several names — the caller then omits
    ``type`` entirely, matching the historical hand-written schemas.
    """
    origin = get_origin(annotation)
    if origin is Literal:
        values = list(get_args(annotation))
        return [_PY_TO_JSON.get(type(values[0]), "string")], values
    if origin is Union or origin is getattr(types, "UnionType", None):
        names: list[str] = []
        enum: list | None = None
        for arg in get_args(annotation):
            if arg is type(None):
                continue
            sub_names, sub_enum = _json_types_for(arg)
            for n in sub_names:
                if n not in names:
                    names.append(n)
            if sub_enum is not None:
                enum = sub_enum
        return names, enum
    if origin in _PY_TO_JSON:  # list[X], dict[K, V]
        return [_PY_TO_JSON[origin]], None
    if annotation in _PY_TO_JSON:
        return [_PY_TO_JSON[annotation]], None
    return ["string"], None


def to_function_schema(name: str, description: str,
                       model_cls: type[BaseModel]) -> dict:
    """Build the OpenAI-function-style tool definition for a model.

    Output is restricted to the vocabulary upstream's ``add_arg``
    understands: per-property ``type`` / ``description`` / ``default`` /
    ``enum``, plus the top-level ``required`` list. Fields without a
    default are required; ``None`` defaults are omitted (optional
    param, no schema default).
    """
    properties: dict[str, dict] = {}
    required: list[str] = []
    for fname, finfo in model_cls.model_fields.items():
        prop: dict = {}
        type_names, enum = _json_types_for(finfo.annotation)
        if len(type_names) == 1:
            prop["type"] = type_names[0]
        # multi-type unions (e.g. int | list) emit no "type" key at all
        if enum is not None:
            prop["enum"] = enum
        if finfo.default is not PydanticUndefined and finfo.default is not None:
            prop["default"] = finfo.default
        if finfo.description:
            prop["description"] = finfo.description
        properties[fname] = prop
        if finfo.is_required():
            required.append(fname)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


__all__ = ["ARG_MODELS", "to_function_schema"]
