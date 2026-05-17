"""Process-local cache of the current experiment phase + active experiment id.

This is the runtime mirror of the persisted `ExperimentPlan.phase` column.
Every fresh `beamtimehero` subprocess starts cold and reseeds itself from
the DB (see `scripts/beamtimehero` `main()`); within a single process,
this module is the in-memory source of truth.

`set_phase` is the single canonical writer. It validates the slug against
`phases.VALID_PHASES`, updates the in-memory dict, mirrors the value to
`beamtimehero_cli.runtime_state` (which upstream's `audited_call` reads),
AND writes through to `ExperimentPlan.phase` so the next subprocess can
pick the phase back up. There is no separate gating, precondition, or
approval layer — the operator (or whatever pre-spawn step decided the
phase) is trusted.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from beamtimehero_cli import runtime_state as _upstream_rs
from beamtimehero_cli.spec_control import phases

logger = logging.getLogger(__name__)

_STATE: dict[str, Any] = {
    "phase": phases.PHASE_SETUP,
    "experiment_id": None,
}


def get_phase() -> str:
    return _STATE["phase"]


def get_experiment_id() -> Optional[str]:
    return _STATE.get("experiment_id")


def set_phase(phase: str, experiment_id: str | None = None) -> None:
    """Update the in-memory phase and (best-effort) persist to ExperimentPlan.

    The DB write-through is best-effort: callers in test contexts may not
    have an experiment row yet, and we don't want a missing row to break
    the in-memory state update. The CLI bootstrap re-seeds from the DB on
    the next subprocess start regardless.
    """
    if phase not in phases.VALID_PHASES:
        raise ValueError(f"unknown phase: {phase}")
    _STATE["phase"] = phase
    if experiment_id:
        _STATE["experiment_id"] = experiment_id

    # Mirror to upstream so beamtimehero_cli.audited_call sees the same phase.
    _upstream_rs.set_phase(phase, experiment_id=_STATE.get("experiment_id"))

    xid = experiment_id or _STATE.get("experiment_id")
    if xid:
        try:
            from orchestration.plan_store.client import upsert_experiment_plan
            upsert_experiment_plan(xid, phase=phase)
        except Exception as e:  # noqa: BLE001
            logger.warning("runtime_state.set_phase: DB write-through failed: %s", e)


def set_experiment_id(experiment_id: str | None) -> None:
    """Update the active experiment without changing phase. Used by the
    CLI bootstrap when seeding state from the DB."""
    _STATE["experiment_id"] = experiment_id
    _upstream_rs.set_experiment_id(experiment_id)
