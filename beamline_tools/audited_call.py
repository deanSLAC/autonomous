"""Audited dispatch wrapper around `spec_cmd.call`.

`spec_cmd.call` is the primitive: render → reserve transport → dispatch →
parse → return. It knows nothing about phases, experiments, or the
action_log. This wrapper adds the higher-level concerns:

  * Pull phase + experiment_id from `orchestration.runtime_state`.
  * Enforce that action commands have a justification.
  * Open an `action_log` row before SPEC sees the command (durable trace
    even when SPEC hangs / process is killed) and finalize it after.
  * For read commands, write a row to `query_log` with timing + result.
  * Best-effort scan-number extraction from the SPEC output for the
    scan-emitting commands so the dashboard can correlate.

Returns the same dict shape callers expect today:
  {"ok": bool, "kind": "read"|"action"|"unknown",
   "action_id"?: str, "result"?: any, "elapsed_s"?: float, "error"?: str}
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from beamline_tools.action_log.db import (
    finish_action,
    log_query,
    mark_action_started,
    start_action,
)
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)


_SCAN_EMITTING_COMMANDS = {
    "ascan", "dscan", "run_xas", "emiss_scan", "run_shortcut",
}


def _extract_scan_number(output: str | None) -> Optional[int]:
    if not output:
        return None
    m = re.search(r"(?:scan[_ ]?n|scan)\s*=?\s*#?(\d+)", output, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def audited_call(
    command: str,
    args: list[str] | tuple[str, ...] | None,
    justification: str = "",
    *,
    agent: str = "llm",
    experiment_id: str | None = None,
) -> dict:
    """Phase/experiment-aware audited SPEC dispatch.

    Imports `orchestration.runtime_state` lazily because `beamline_tools`
    is the lower layer; the lazy import keeps test/--help paths that
    don't touch orchestration cheap.
    """
    from orchestration import runtime_state

    args_list = list(args or [])
    phase = runtime_state.get_phase()
    exp_id = experiment_id or runtime_state.get_experiment_id()

    # Look up the command's kind ("read"|"action") via spec_cmd's registry.
    kind = spec_cmd.command_kind(command)
    if kind is None:
        return {"ok": False, "kind": "unknown", "error": f"unknown command: {command}"}

    # -------- READ path ---------------------------------------------------
    if kind == "read":
        t0 = time.time()
        result = spec_cmd.call(command, args_list, action_id="query")
        latency_ms = int((time.time() - t0) * 1000)
        if not result.get("ok"):
            log_query(
                command, args_list, None,
                phase=phase, experiment_id=exp_id,
                error_message=result.get("error"),
                latency_ms=latency_ms,
            )
            return result
        log_query(
            command, args_list, result.get("result"),
            phase=phase, experiment_id=exp_id,
            latency_ms=latency_ms,
        )
        return result

    # -------- ACTION path -------------------------------------------------
    if not (justification or "").strip():
        return {
            "ok": False, "kind": "action",
            "error": "justification is required for action commands",
        }

    # Pre-render the SPEC string for the audit row. If rendering fails we
    # never open the row — spec_cmd.call would have returned the same
    # error on its own.
    try:
        spec_string = spec_cmd.render(command, args_list)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "kind": "action",
            "error": f"failed to render command: {e}",
        }

    row = start_action(
        command=command,
        args=args_list,
        justification=justification,
        phase=phase,
        spec_string=spec_string,
        experiment_id=exp_id,
        agent=agent,
    )
    mark_action_started(row.id)

    result = spec_cmd.call(
        command, args_list,
        justification=justification, action_id=row.id,
    )

    if not result.get("ok"):
        finish_action(
            row.id,
            success=False,
            error_message=result.get("error"),
            screen_output=result.get("output") or "",
        )
        return {**result, "action_id": row.id}

    parsed = result.get("result") or {}
    scan_number = None
    if command in _SCAN_EMITTING_COMMANDS:
        scan_number = _extract_scan_number(result.get("output"))

    finish_action(
        row.id,
        success=True,
        result=parsed,
        screen_output=result.get("output"),
        scan_number=scan_number,
    )
    out: dict[str, Any] = {
        "ok": True, "kind": "action", "action_id": row.id,
        "result": parsed,
    }
    if "elapsed_s" in result:
        out["elapsed_s"] = result["elapsed_s"]
    return out
