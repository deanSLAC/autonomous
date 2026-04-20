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

from sqlalchemy import event, inspect, text
from sqlmodel import SQLModel, create_engine

# Register every model with the metadata by importing the module.
from db import models  # noqa: F401


# Columns added since the original schema. Keep additive only — for
# destructive changes, write a real migration. Each entry is the SQL
# fragment after `ADD COLUMN` (sqlite syntax). Run on every init_db().
_PENDING_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "experimentelement": [
        ("measurement_mode", 'TEXT NOT NULL DEFAULT "XES"'),
        ("emission_line", "TEXT"),
    ],
    "sampleposition": [
        ("i0_gain", "TEXT"),
        ("i0_offset", "TEXT"),
        ("i1_gain", "TEXT"),
    ],
    "sampleholder": [
        ("queue_order", "INTEGER NOT NULL DEFAULT 0"),
        ("notes", "TEXT"),
    ],
}


def _apply_column_migrations(engine) -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _PENDING_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            for col_name, col_def in cols:
                if col_name in existing_cols:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_def}'))
                print(f"  migrated: {table}.{col_name} added")


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
    _apply_column_migrations(engine)
    print(f"Database initialized: {db_path}")
    print(f"Tables: {', '.join(sorted(SQLModel.metadata.tables.keys()))}")


if __name__ == "__main__":
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None
    init_db(custom_path)
