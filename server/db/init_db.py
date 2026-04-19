"""Initialize the autonomous-beamline SQLite database.

Creates every SQLModel table (original beamline tables + autonomy
extensions) with WAL journaling.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure server/ is importable regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine

# Register every model with the metadata by importing the module.
from db import models  # noqa: F401


def get_default_db_path() -> str:
    """Prefer AUTONOMOUS_DB_PATH, then BEAMLINE_DB_PATH, then project data/ dir."""
    for env in ("AUTONOMOUS_DB_PATH", "BEAMLINE_DB_PATH"):
        if os.environ.get(env):
            return os.environ[env]
    return str(Path(__file__).resolve().parent.parent.parent / "data" / "autonomous.db")


def init_db(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = get_default_db_path()

    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    print(f"Database initialized: {db_path}")
    print(f"Tables: {', '.join(sorted(SQLModel.metadata.tables.keys()))}")


if __name__ == "__main__":
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None
    init_db(custom_path)
