"""ScanRecord capture — automatic per-scan rows for the dashboard.

`execute_tool` calls `capture_scan_record` after every successful tool
dispatch. When the tool was a scan-emitting SPEC action (its action-log
row carries a `scan_number`) and the agent subprocess was spawned for a
phase run (`BEAMTIMEHERO_PHASE_RUN_ID` in the env), a ScanRecord row is
inserted keyed to that phase run. This is the "authoritative count" path
the dashboard prefers over its SPEC-file time-window fallback (see
`ui/server/routers/dashboard_api.py`).

Capture lives in the tool layer — not in agent prompts — so it cannot be
skipped by a non-compliant agent, and not in the shared
`beamtimehero_cli` package, which must stay free of orchestration
imports.

Everything here is best-effort: a capture failure logs and never breaks
the tool result the agent sees.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# command → motor implied by the command itself (scan commands whose
# first CLI arg is NOT a motor name).
_IMPLIED_MOTOR = {
    "run_xas": "energy",
    "emiss_scan": "emiss",
}

# Commands whose first arg is the scanned motor.
_MOTOR_ARG_COMMANDS = {"ascan", "dscan", "cscan", "cdscan"}


def capture_scan_record(tool_name: str, result_text: str) -> None:
    """Insert a ScanRecord if this tool result was a scan-emitting action.

    Cheap no-ops first: no phase-run context, or the result envelope is
    not a successful action with an action_id.
    """
    phase_run_id = os.environ.get("BEAMTIMEHERO_PHASE_RUN_ID")
    if not phase_run_id:
        return
    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict) or not payload.get("ok"):
        return
    action_id = payload.get("action_id")
    if not action_id:
        return

    try:
        _capture(tool_name, action_id, phase_run_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("scan_capture: failed for %s (%s): %s",
                       tool_name, action_id, e)


def _capture(tool_name: str, action_id: str, phase_run_id: str) -> None:
    from sqlmodel import select

    from beamtimehero_cli.action_log.models import ActionLog
    from beamtimehero_cli.action_log.session import get_session as action_session

    with action_session() as session:
        row = session.exec(
            select(ActionLog).where(ActionLog.id == action_id)
        ).first()
        if row is None or row.scan_number is None:
            return
        # Stamp provenance on the action row while we hold it — the
        # column exists for exactly this linkage.
        if row.phase_run_id is None:
            row.phase_run_id = phase_run_id
            session.add(row)
            session.commit()
        command = row.command
        spec_string = row.spec_string_sent or command
        scan_number = int(row.scan_number)
        try:
            args = json.loads(row.args_json or "[]")
        except ValueError:
            args = []

    if command in _MOTOR_ARG_COMMANDS and args:
        motor = str(args[0])
    else:
        motor = _IMPLIED_MOTOR.get(command, "")

    from orchestration.plan_store.models import ScanRecord
    from orchestration.plan_store.session import get_session

    record = ScanRecord(
        phase_run_id=phase_run_id,
        scan_number=scan_number,
        motor_name=motor,
        scan_type=command,
        command=spec_string,
    )
    with get_session() as session:
        session.add(record)
        session.commit()
    logger.info(
        "scan_capture: ScanRecord scan=%d motor=%s tool=%s phase_run=%s",
        scan_number, motor, tool_name, phase_run_id,
    )
