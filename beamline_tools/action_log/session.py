"""SQLModel engine + session for the beamline_tools action_log DB.

Bound to `BEAMLINE_TOOLS_DB_PATH` (see beamline_tools.config). WAL +
busy_timeout so multiple processes (FastAPI parent + opencode tool
subprocesses) can hit the same file without contention.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from beamline_tools.action_log import models  # noqa: F401 — register tables

_engine = None


def _db_path() -> str:
    return os.environ.get(
        "BEAMLINE_TOOLS_DB_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "data" / "beamline_tools.db"),
    )


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    db_path = _db_path()
    db_url = f"sqlite:///{db_path}"
    _engine = create_engine(db_url, echo=False)

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    SQLModel.metadata.create_all(_engine)

    # Inline schema migration: ensure additive columns exist on already-created
    # tables. SQLModel.metadata.create_all only creates missing tables; it does
    # NOT add columns. SQLite + this codebase has no migration framework, so we
    # patch in additive columns by hand at startup. Idempotent.
    with _engine.connect() as conn:
        existing_cols = {
            row[1] for row in conn.exec_driver_sql(
                "PRAGMA table_info(cliinvocationlog)"
            ).fetchall()
        }
        if existing_cols and "agent_role" not in existing_cols:
            conn.exec_driver_sql(
                "ALTER TABLE cliinvocationlog ADD COLUMN agent_role TEXT"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS "
                "ix_cliinvocationlog_agent_role ON cliinvocationlog (agent_role)"
            )
            conn.commit()
    return _engine


def get_session() -> Session:
    return Session(get_engine())


def init_db() -> None:
    """Create tables if missing. Idempotent."""
    get_engine()
