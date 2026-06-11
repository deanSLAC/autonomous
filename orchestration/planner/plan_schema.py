"""Pydantic schema for the experiment plan document (`ExperimentPlan.plan_json`).

The plan blob is written by three kinds of authors:

  * `build_initial_plan` (trusted, in-process),
  * the ~12 `_mutate_plan` closures (trusted, in-process),
  * the LLM agent via the `update_plan` tool (UNTRUSTED — it replaces the
    document wholesale).

Until now the only shape guard was `isinstance(plan, dict)`, so an agent
writing `{"status": "Done"}` or dropping `reps_completed` corrupted
downstream planning silently. This schema validates at the write choke
points (`replace_plan`, `_mutate_plan`) and normalizes the fields
consumers key-read (statuses lowercased), while `extra="allow"`
preserves any agent-added fields across round-trips.

Validation philosophy: strict on the fields the orchestrator/planner
actually branch on (sample_id, status, reps_completed, modes[].mode),
lenient everywhere else.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = [
    "Budget",
    "ExperimentPlanDoc",
    "ModeSpec",
    "PlanSchemaError",
    "SampleQueueEntry",
    "Thresholds",
    "validate_plan_doc",
]

SAMPLE_STATUSES = ("queued", "in_progress", "done", "skipped", "failed")


class PlanSchemaError(ValueError):
    """A plan document failed schema validation. The message is written
    to be actionable for the LLM agent that produced the plan."""


class ModeSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["xas", "emiss"]
    reps: Optional[int] = Field(default=None, ge=0)
    count_time_s: Optional[float] = Field(default=None, gt=0)
    filter_bitmask: Optional[int] = Field(default=None, ge=0)

    @field_validator("mode", mode="before")
    @classmethod
    def _lower_mode(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


class SampleQueueEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_id: str = Field(min_length=1)
    status: Literal["queued", "in_progress", "done", "skipped", "failed"] = "queued"
    reps_completed: int = Field(default=0, ge=0)
    modes: list[ModeSpec] = Field(default_factory=list)
    sample_name: Optional[str] = None
    element_symbol: Optional[str] = None
    holder_id: Optional[str] = None
    snr_estimate: Optional[float] = None
    efficiency_verdict: Optional[str] = None
    notes: list = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        # Agents write "Done" / "In_Progress" often enough that rejecting
        # case is needless friction — normalize, then let the Literal
        # catch genuinely unknown statuses.
        return v.strip().lower() if isinstance(v, str) else v


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="allow")

    snr_target: Optional[float] = Field(default=None, gt=0)
    min_reps_per_sample: Optional[int] = Field(default=None, ge=0)


class Budget(BaseModel):
    model_config = ConfigDict(extra="allow")

    beamtime_total_hours: Optional[float] = Field(default=None, gt=0)
    started_at: Optional[str] = None


class ExperimentPlanDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_queue: list[SampleQueueEntry] = Field(default_factory=list)
    thresholds: Optional[Thresholds] = None
    budget: Optional[Budget] = None
    updated_at: Optional[str] = None


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:8]:
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    more = len(exc.errors()) - 8
    if more > 0:
        parts.append(f"(+{more} more)")
    return "; ".join(parts)


def validate_plan_doc(plan: dict) -> dict:
    """Validate + normalize a plan document.

    Returns the normalized dict (statuses lowercased, defaults filled,
    agent-added extra fields preserved). Raises PlanSchemaError with an
    agent-actionable message on failure.
    """
    if not isinstance(plan, dict):
        raise PlanSchemaError("plan must be a JSON object")
    try:
        doc = ExperimentPlanDoc.model_validate(plan)
    except ValidationError as e:
        raise PlanSchemaError(
            f"plan failed schema validation: {_format_errors(e)}. "
            f"Sample statuses must be one of {list(SAMPLE_STATUSES)}; every "
            f"sample_queue entry needs a non-empty sample_id."
        ) from e
    return doc.model_dump()
