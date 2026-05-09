"""DB CRUD for the `AgentRun` table.

Returns dicts (not ORM rows) from list/get methods so callers don't have
to keep a Session open — every access closes the session before returning.

`list_active(agent_type=<slug>)` is the gate the orchestrator tick uses
to decide whether a phase agent of a given type is currently running.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import select

from orchestration.plan_store.models import AgentRun
from orchestration.plan_store.session import get_session


def _to_dict(row: AgentRun) -> dict:
    return {
        "id": row.id,
        "experiment_id": row.experiment_id,
        "agent_type": row.agent_type,
        "task_text": row.task_text,
        "spawned_by": row.spawned_by,
        "pid": row.pid,
        "pgid": row.pgid,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "killed": row.killed,
        "kill_reason": row.kill_reason,
        "result": row.result,
        "claude_session_id": row.claude_session_id,
        "working_dir": row.working_dir,
        "script_path": row.script_path,
    }


def create_run(
    *,
    agent_type: str,
    task_text: str,
    spawned_by: str,
    experiment_id: Optional[str] = None,
    pid: Optional[int] = None,
    pgid: Optional[int] = None,
    claude_session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    script_path: Optional[str] = None,
) -> AgentRun:
    """Insert a new AgentRun row. PID/PGID may be None at creation time and
    backfilled via `set_pid()` after Popen returns the live pid."""
    row = AgentRun(
        agent_type=agent_type,
        task_text=task_text,
        spawned_by=spawned_by,
        experiment_id=experiment_id,
        pid=pid,
        pgid=pgid,
        claude_session_id=claude_session_id,
        working_dir=working_dir,
        script_path=script_path,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def set_pid(run_id: str, pid: int, pgid: int) -> None:
    """Backfill the pid/pgid after Popen. Called by spawn.py."""
    with get_session() as session:
        row = session.get(AgentRun, run_id)
        if row is None:
            return
        row.pid = pid
        row.pgid = pgid
        session.add(row)
        session.commit()


def set_claude_session_id(run_id: str, claude_session_id: str) -> None:
    """Backfill claude_session_id once we observe it in the stream-json.

    Useful when spawn() didn't pre-supply one (the .sh launcher generated
    it via uuidgen) so we can `--resume` later.
    """
    with get_session() as session:
        row = session.get(AgentRun, run_id)
        if row is None:
            return
        row.claude_session_id = claude_session_id
        session.add(row)
        session.commit()


def complete_run(
    run_id: str,
    *,
    result: Optional[str] = None,
    killed: bool = False,
    kill_reason: Optional[str] = None,
) -> None:
    """Mark a run as completed. Idempotent — calling twice is safe."""
    with get_session() as session:
        row = session.get(AgentRun, run_id)
        if row is None:
            return
        if row.completed_at is None:
            row.completed_at = datetime.now()
        if result is not None:
            row.result = result
        if killed:
            row.killed = True
        if kill_reason is not None:
            row.kill_reason = kill_reason
        session.add(row)
        session.commit()


def get_run(run_id: str) -> Optional[dict]:
    with get_session() as session:
        row = session.get(AgentRun, run_id)
        if row is None:
            return None
        return _to_dict(row)


def list_active(agent_type: Optional[str] = None) -> list[dict]:
    """All rows where completed_at IS NULL, optionally filtered by type."""
    with get_session() as session:
        stmt = select(AgentRun).where(AgentRun.completed_at.is_(None))  # type: ignore[union-attr]
        if agent_type is not None:
            stmt = stmt.where(AgentRun.agent_type == agent_type)
        stmt = stmt.order_by(AgentRun.started_at.desc())  # type: ignore[union-attr]
        return [_to_dict(r) for r in session.exec(stmt).all()]


def list_recent(limit: int = 50) -> list[dict]:
    """Last N rows (for the UI)."""
    with get_session() as session:
        stmt = (
            select(AgentRun)
            .order_by(AgentRun.started_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        return [_to_dict(r) for r in session.exec(stmt).all()]
