"""SQLite action_log writer.

Hard invariant: every `spec_cmd` action is INSERT'd as an ActionLog row
**before** the command is injected to SPEC. This guarantees a durable
trace even when SPEC hangs, the server crashes, or the LLM is killed.
Read-only `spec_cmd` calls go to the lighter QueryLog table instead, so
the action feed stays focused on state-changing operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlmodel import select

from beamline_tools.action_log.models import ActionLog, QueryLog
from beamline_tools.action_log.session import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def start_action(
    command: str,
    args: list[str] | tuple[str, ...],
    justification: str,
    phase: str,
    spec_string: str,
    experiment_id: Optional[str] = None,
    phase_run_id: Optional[str] = None,
    agent: str = "llm",
) -> ActionLog:
    """Insert a row for an action BEFORE it is dispatched to SPEC."""
    justification = (justification or "").strip()
    if not justification:
        raise ValueError("justification is required and must be non-empty")

    row = ActionLog(
        experiment_id=experiment_id,
        phase_run_id=phase_run_id,
        phase=phase,
        command=command,
        args_json=json.dumps(list(args)),
        spec_string_sent=spec_string,
        justification=justification,
        agent=agent,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    logger.info(
        "action_log[%s] START phase=%s cmd=%s args=%s",
        row.id, phase, command, list(args),
    )
    return row


def mark_action_started(action_id: str) -> None:
    """Mark that the SPEC command has been injected (started_at=now)."""
    with get_session() as session:
        row = session.get(ActionLog, action_id)
        if row is None:
            return
        row.started_at = datetime.now()
        session.add(row)
        session.commit()


def finish_action(
    action_id: str,
    *,
    success: bool,
    result: Any = None,
    screen_output: str | None = None,
    scan_number: int | None = None,
    error_message: str | None = None,
) -> None:
    """Finalize an ActionLog row with outcome + result JSON + screen buffer."""
    with get_session() as session:
        row = session.get(ActionLog, action_id)
        if row is None:
            return
        row.completed_at = datetime.now()
        row.success = 1 if success else 0
        if result is not None:
            row.result_json = json.dumps(result, default=str)
        if screen_output is not None:
            row.screen_output = screen_output
        if scan_number is not None:
            row.scan_number = scan_number
        if error_message is not None:
            row.error_message = error_message
        session.add(row)
        session.commit()
    logger.info(
        "action_log[%s] FINISH success=%s scan=%s err=%s",
        action_id, success, scan_number, error_message,
    )


def log_query(
    command: str,
    args: list[str] | tuple[str, ...],
    result: Any,
    *,
    phase: str = "unknown",
    experiment_id: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Record a read-only spec_cmd call to query_log."""
    row = QueryLog(
        experiment_id=experiment_id,
        phase=phase,
        command=command,
        args_json=json.dumps(list(args)),
        result_json=None if result is None else json.dumps(result, default=str),
        error_message=error_message,
        latency_ms=latency_ms,
    )
    with get_session() as session:
        session.add(row)
        session.commit()


# ---------------------------------------------------------------------------
# Readers (for dashboard + history viewer)
# ---------------------------------------------------------------------------

def recent_actions(limit: int = 50, experiment_id: str | None = None) -> list[dict]:
    """Returns live action-log rows (invalidated_at IS NULL).

    Rows marked invalidated by /api/orchestrator/reset are hidden here
    so the re-run guards + dashboard tape treat a reset run as fresh.
    """
    with get_session() as session:
        stmt = select(ActionLog).where(ActionLog.invalidated_at.is_(None))
        if experiment_id:
            stmt = stmt.where(ActionLog.experiment_id == experiment_id)
        stmt = stmt.order_by(ActionLog.timestamp.desc()).limit(limit)
        rows: Iterable[ActionLog] = session.exec(stmt)
        return [_action_to_dict(r) for r in rows]


def recent_queries(limit: int = 50, experiment_id: str | None = None) -> list[dict]:
    with get_session() as session:
        stmt = select(QueryLog).order_by(QueryLog.timestamp.desc()).limit(limit)
        if experiment_id:
            stmt = (
                select(QueryLog)
                .where(QueryLog.experiment_id == experiment_id)
                .order_by(QueryLog.timestamp.desc())
                .limit(limit)
            )
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "phase": r.phase,
                "command": r.command,
                "args": json.loads(r.args_json) if r.args_json else [],
                "result": json.loads(r.result_json) if r.result_json else None,
                "latency_ms": r.latency_ms,
                "error": r.error_message,
            }
            for r in session.exec(stmt)
        ]


def invalidate_for_experiment(experiment_id: str) -> int:
    """Mark every live ActionLog row for this experiment as invalidated.

    Called by orchestration.api.reset_run when the operator triggers a
    hard reset from the dashboard. Rows stay in the DB (audit preserved)
    but `recent_actions()` no longer returns them.
    """
    now = datetime.now()
    with get_session() as session:
        rows = list(session.exec(
            select(ActionLog).where(
                ActionLog.experiment_id == experiment_id,
                ActionLog.invalidated_at.is_(None),
            )
        ))
        for row in rows:
            row.invalidated_at = now
            session.add(row)
        session.commit()
    return len(rows)


def _action_to_dict(r: ActionLog) -> dict:
    return {
        "id": r.id,
        "experiment_id": r.experiment_id,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "phase": r.phase,
        "command": r.command,
        "args": json.loads(r.args_json) if r.args_json else [],
        "spec_string_sent": r.spec_string_sent,
        "justification": r.justification,
        "result": json.loads(r.result_json) if r.result_json else None,
        "scan_number": r.scan_number,
        "success": r.success,
        "error": r.error_message,
        "agent": r.agent,
    }
