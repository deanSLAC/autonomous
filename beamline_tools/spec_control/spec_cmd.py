"""Autonomy wrapper around `beamtimehero_cli.spec_control.spec_cmd`.

Upstream's `spec_cmd.call` is transport-agnostic and project-agnostic.
This wrapper layers on a single autonomy-specific post-dispatch hook:
when `measure_beam_size` succeeds, persist the measured h/v FWHM (mm → µm)
onto the active experiment's `ExperimentPlan` row so the dashboard's
Beam field can switch from the configured big/focused mode strings to
the actual numbers once `beamline_alignment` has run.

All other commands pass through unchanged. The render / dispatch /
abort / known-commands API is re-exported as-is.
"""

from __future__ import annotations

import logging

from beamtimehero_cli.spec_control.spec_cmd import (  # noqa: F401
    CommandSpec,
    _ACTION,
    _READ,
    abort_current,
    command_kind,
    dispatch,
    known_commands,
    render,
)
from beamtimehero_cli.spec_control.spec_cmd import call as _upstream_call

logger = logging.getLogger(__name__)


def _record_measured_beam_size(result: dict) -> None:
    """Best-effort write-through to plan_store for measure_beam_size results."""
    parsed = result.get("result") or {}
    h_mm = parsed.get("h_mm")
    v_mm = parsed.get("v_mm")
    if h_mm is None and v_mm is None:
        return
    try:
        from orchestration.runtime_state import get_experiment_id as _xid
        xid = _xid()
        if not xid:
            return
        from orchestration.plan_store.session import record_measured_beam_size
        record_measured_beam_size(
            xid,
            h_mm * 1000.0 if h_mm is not None else None,
            v_mm * 1000.0 if v_mm is not None else None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("measure_beam_size write-through failed: %s", e)


def call(
    command: str,
    args: list[str] | tuple[str, ...] | None,
    justification: str = "",
    *,
    action_id: str | None = None,
) -> dict:
    """Same shape as upstream `spec_cmd.call`; adds measure_beam_size hook."""
    result = _upstream_call(command, args, justification, action_id=action_id)
    if command == "measure_beam_size" and result.get("ok"):
        _record_measured_beam_size(result)
    return result


__all__ = [
    "CommandSpec",
    "abort_current",
    "call",
    "command_kind",
    "dispatch",
    "known_commands",
    "render",
]
